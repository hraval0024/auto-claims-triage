"""Claim pipeline: intake -> prechecks -> model (gate + extraction) -> gate enforcement -> merge.

The gate is enforced in CODE: if no photo passes, no vehicle or damage is returned, whatever
the model wrote. Phase 2 adds cost and routing after the merge step.
"""

import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from app.config import COST_TABLE_VERSION, PROMPT_VERSION, SCHEMA_VERSION, settings
from app.intake import IntakeError, prepare_image
from app.llm import LLMError, UsageTally, call_model
from app.prechecks import run_prechecks
from app.schemas import (
    BLOCKING_GATE_CODES,
    Audit,
    ClaimResult,
    Confidence,
    GateCode,
    GateResult,
    MergedDamageItem,
    ModelOutput,
    Usage,
)

_CONF_RANK = {Confidence.low: 0, Confidence.medium: 1, Confidence.high: 2}

_GATE_TEXT = {
    GateCode.not_a_vehicle: "no vehicle is the subject of the photo",
    GateCode.multiple_vehicles: "more than one vehicle could be the claimed vehicle",
    GateCode.too_blurry_or_dark: "too blurry or dark to judge damage",
    GateCode.damage_area_not_visible: "the damaged area is not visible",
    GateCode.bad_angle_or_crop: "the angle or crop prevents identifying panels",
    GateCode.likely_screenshot_or_stock: "looks like a screenshot or stock photo, not an original photo",
    GateCode.embedded_instruction_text: "contains text that looks like instructions (ignored)",
}


def run_claim(
    images: list[bytes],
    *,
    model_id: str | None = None,
    effort: str | None = None,
    include_raw: bool = False,
    request_id: str | None = None,
) -> ClaimResult:
    t0 = time.monotonic()
    model_id = model_id or settings.model_id
    effort = effort or settings.model_effort
    if not images:
        raise IntakeError("Send at least one photo.")
    if len(images) > settings.max_photos_per_claim:
        raise IntakeError(f"At most {settings.max_photos_per_claim} photos per claim.")

    prepared = [prepare_image(b) for b in images]  # raises IntakeError with a user-safe message
    prechecks = [run_prechecks(i, p) for i, p in enumerate(prepared)]
    audit = Audit(
        request_id=request_id or str(uuid.uuid4()),
        timestamp=datetime.now(timezone.utc),
        model_id=model_id,
        model_effort=effort,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        cost_table_version=COST_TABLE_VERSION,
        input_hashes=[p.sha256 for p in prepared],
    )

    def finish(**kw) -> ClaimResult:
        return ClaimResult(audit=audit, prechecks=prechecks, latency_ms=int((time.monotonic() - t0) * 1000), **kw)

    # Photos blocked by deterministic prechecks never reach the model (saves a paid call).
    sent = [i for i, pc in enumerate(prechecks) if not pc.blocking]
    if not sent:
        reasons = [msg for pc in prechecks for msg in pc.blocking]
        return finish(status="gate_failed", gate=GateResult(passed=False, usable_photo_indices=[], reasons=reasons, retake_advice=reasons))

    try:
        out, tally = call_model([prepared[i].jpeg_bytes for i in sent], model_id=model_id, effort=effort)
    except LLMError as e:
        return finish(
            status="error",
            gate=GateResult(passed=False, usable_photo_indices=[], reasons=["Automated assessment unavailable."], retake_advice=[]),
            error=f"{e} Routed to a human adjuster; no automated assessment was produced.",
            flags=["route_to_human"],
            usage=_usage(e.usage),
        )

    # Map the model's photo indices back to the caller's original indices.
    for p in out.photos:
        p.photo_index = sent[p.photo_index]
    for d in out.damage:
        d.photo_index = sent[d.photo_index]

    reasons, advice, flags, usable = [], [], [], []
    for pc in prechecks:
        reasons += pc.blocking
    for p in out.photos:
        codes = {iss.code for iss in p.issues}
        for iss in p.issues:
            reasons.append(f"Photo {p.photo_index}: {_GATE_TEXT[iss.code]} ({iss.detail})")
        if codes & BLOCKING_GATE_CODES:
            if p.retake_advice:
                advice.append(f"Photo {p.photo_index}: {p.retake_advice}")
        else:
            usable.append(p.photo_index)
        if GateCode.embedded_instruction_text in codes:
            flags.append("embedded_instruction_text")
        if p.license_plate_visible:
            flags.append("license_plate_visible")
        if p.person_face_visible:
            flags.append("person_face_visible")
    flags = sorted(set(flags))
    usage = _usage(tally)
    raw = out if include_raw else None

    if not usable:
        # The model may still have filled vehicle/damage; we discard them (no made-up assessment).
        return finish(status="gate_failed", gate=GateResult(passed=False, usable_photo_indices=[], reasons=reasons, retake_advice=advice),
                      flags=flags, usage=usage, raw_model_output=raw)

    damage, conflicts = merge_damage(out, set(usable))
    conflicts += vehicle_conflicts(out, set(usable))
    return finish(
        status="ok",
        gate=GateResult(passed=True, usable_photo_indices=usable, reasons=reasons, retake_advice=advice),
        vehicle=out.vehicle,
        damage=damage,
        damage_summary=out.damage_summary,
        not_assessable=out.not_assessable,
        conflicts=conflicts,
        flags=flags,
        usage=usage,
        raw_model_output=raw,
    )


def merge_damage(out: ModelOutput, usable: set[int]) -> tuple[list[MergedDamageItem], list[str]]:
    """Group per-photo observations by (panel, side, type). Severity = max seen; confidence =
    lowest seen; a spread of 2+ levels between photos is flagged as a conflict."""
    groups = defaultdict(list)
    for d in out.damage:
        if d.photo_index in usable:
            groups[(d.panel, d.side, d.damage_type)].append(d)
    items, conflicts = [], []
    for (panel, side, dtype), obs in groups.items():
        sevs = [o.severity for o in obs]
        conflict = max(sevs) - min(sevs) >= 2
        if conflict:
            conflicts.append(f"{side} {panel} {dtype}: photos disagree on severity ({sorted(set(sevs))}).")
        items.append(
            MergedDamageItem(
                panel=panel,
                side=side,
                damage_type=dtype,
                severity=max(sevs),
                confidence=min((o.confidence for o in obs), key=_CONF_RANK.get),
                photo_indices=sorted({o.photo_index for o in obs}),
                cues=[o.cues for o in obs],
                severity_conflict=conflict,
            )
        )
    items.sort(key=lambda m: (-m.severity, m.panel))
    return items, conflicts


def vehicle_conflicts(out: ModelOutput, usable: set[int]) -> list[str]:
    conflicts = []
    for attr, label in (("vehicle_make_seen", "makes"), ("vehicle_color_seen", "colors")):
        seen = {getattr(p, attr).strip().lower() for p in out.photos if p.photo_index in usable}
        seen.discard("unknown")
        seen.discard("")
        # "dark blue" vs "blue" is not a conflict: drop values contained in another value.
        distinct = {s for s in seen if not any(s != o and s in o for o in seen)}
        if len(distinct) > 1:
            conflicts.append(f"Photos show different vehicle {label}: {sorted(distinct)}. They may be different vehicles.")
    return conflicts


def _usage(t: UsageTally) -> Usage:
    return Usage(model_id=t.model_id, input_tokens=t.input_tokens, cache_write_tokens=t.cache_write_tokens,
                 cache_read_tokens=t.cache_read_tokens, output_tokens=t.output_tokens,
                 cost_usd=round(t.cost_usd, 5), attempts=t.attempts)
