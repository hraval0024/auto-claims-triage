"""Claim pipeline: intake -> prechecks -> model (gate + extraction) -> gate enforcement -> merge
-> deterministic cost -> routing [-> optional LLM free-guess baseline, eval only].

The gate is enforced in CODE: if no photo passes, no vehicle or damage is returned, whatever
the model wrote. Every outcome, including errors and gate failures, gets a routing decision.
"""

import hashlib
import json
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from app import store
from app.config import COST_TABLE_VERSION, LLM_BASELINE_PROMPT_VERSION, PROMPT_VERSION, SCHEMA_VERSION, settings
from app.cost_engine import estimate
from app.intake import IntakeError, prepare_image
from app.llm import LLMError, UsageTally, call_model, guess_cost
from app.prechecks import run_prechecks
from app.routing import route
from app.schemas import (
    BLOCKING_GATE_CODES,
    Audit,
    ClaimResult,
    Confidence,
    GateCode,
    GateResult,
    LLMBaseline,
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
    region: str | None = None,
    include_llm_baseline: bool | None = None,
    guard=None,
    use_cache: bool = False,
) -> ClaimResult:
    """guard: the API's daily-cap guard (reserve() before each model call, record() after);
    None for scripts. use_cache: reuse model output for byte-identical photos (API only; the
    eval's repeatability runs must not hit the cache). A cap hit raises guards.CapError."""
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
        kw["routing"] = route(kw["status"], kw.get("damage", []), kw.get("cost"), kw.get("flags", []),
                              kw.get("conflicts", []), kw["gate"].reasons)
        return ClaimResult(audit=audit, prechecks=prechecks, latency_ms=int((time.monotonic() - t0) * 1000), **kw)

    # Photos blocked by deterministic prechecks never reach the model (saves a paid call).
    sent = [i for i, pc in enumerate(prechecks) if not pc.blocking]
    if not sent:
        reasons = [msg for pc in prechecks for msg in pc.blocking]
        return finish(status="gate_failed", gate=GateResult(passed=False, usable_photo_indices=[], reasons=reasons, retake_advice=reasons))

    out, cached = None, False
    key = _cache_key([prepared[i].sha256 for i in sent], model_id, effort)
    if use_cache and (hit := store.cache_get(key)):
        out, cached = ModelOutput.model_validate_json(hit[0]), True
        tally = UsageTally(model_id=model_id)  # no model call, no spend
    if out is None:
        if guard:
            guard.reserve()  # raises CapError when a daily cap is reached: no model call
        try:
            out, tally = call_model([prepared[i].jpeg_bytes for i in sent], model_id=model_id, effort=effort,
                                    deadline=t0 + settings.claim_deadline_s)
        except LLMError as e:
            if guard:
                guard.record(e.usage.attempts, e.usage.cost_usd)
            return finish(
                status="error",
                gate=GateResult(passed=False, usable_photo_indices=[], reasons=["Automated assessment unavailable."], retake_advice=[]),
                error=f"{e} Routed to a human adjuster; no automated assessment was produced.",
                flags=["route_to_human"],
                usage=_usage(e.usage),
            )
        if guard:
            guard.record(tally.attempts, tally.cost_usd)
        if use_cache:  # cache BEFORE indices are remapped below; the key covers exactly the sent photos
            store.cache_put(key, out.model_dump_json(), json.dumps({"model_id": model_id, "cost_usd": tally.cost_usd}))

    # Map the model's photo indices back to the caller's original indices.
    for p in out.photos:
        p.photo_index = sent[p.photo_index]
    for d in out.damage:
        d.photo_index = sent[d.photo_index]

    reasons, advice, flags, usable, gate_codes = [], [], [], [], []
    for pc in prechecks:
        reasons += pc.blocking
    for p in out.photos:
        codes = {iss.code for iss in p.issues}
        gate_codes += [c.value for c in codes]
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
    usage = _usage(tally, cached=cached)
    raw = out if include_raw else None
    gate_codes = sorted(set(gate_codes))

    if not usable:
        # The model may still have filled vehicle/damage; we discard them (no made-up assessment).
        return finish(status="gate_failed", gate=GateResult(passed=False, usable_photo_indices=[], codes=gate_codes,
                                                            reasons=reasons, retake_advice=advice),
                      flags=flags, usage=usage, raw_model_output=raw)

    damage, conflicts = merge_damage(out, set(usable))
    conflicts += vehicle_conflicts(out, set(usable))
    cost = estimate(damage, make=out.vehicle.make.value, region=region)

    baseline = None
    if settings.llm_baseline_enabled if include_llm_baseline is None else include_llm_baseline:
        from app.guards import CapError

        try:
            if guard:
                guard.reserve()
            guess, btally = guess_cost([prepared[i].jpeg_bytes for i in usable], model_id=model_id, effort=effort)
            if guard:
                guard.record(btally.attempts, btally.cost_usd)
            baseline = LLMBaseline(guess=guess, usage=_usage(btally), prompt_version=LLM_BASELINE_PROMPT_VERSION)
        except CapError as e:  # a capped baseline never blocks the main result
            baseline = LLMBaseline(guess=None, error=str(e), prompt_version=LLM_BASELINE_PROMPT_VERSION)
        except LLMError as e:  # a failed baseline never affects the main result
            if guard:
                guard.record(e.usage.attempts, e.usage.cost_usd)
            baseline = LLMBaseline(guess=None, error=str(e), usage=_usage(e.usage), prompt_version=LLM_BASELINE_PROMPT_VERSION)

    return finish(
        status="ok",
        gate=GateResult(passed=True, usable_photo_indices=usable, codes=gate_codes, reasons=reasons, retake_advice=advice),
        vehicle=out.vehicle,
        damage=damage,
        damage_summary=out.damage_summary,
        not_assessable=out.not_assessable,
        conflicts=conflicts,
        flags=flags,
        cost=cost,
        llm_baseline=baseline,
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


def _usage(t: UsageTally, cached: bool = False) -> Usage:
    return Usage(model_id=t.model_id, input_tokens=t.input_tokens, cache_write_tokens=t.cache_write_tokens,
                 cache_read_tokens=t.cache_read_tokens, output_tokens=t.output_tokens,
                 cost_usd=round(t.cost_usd, 5), attempts=t.attempts, cached=cached)


def _cache_key(hashes: list[str], model_id: str, effort: str) -> str:
    """Same photos (in order) + same model, effort, prompt and schema -> same model output."""
    raw = "|".join(hashes + [model_id, effort, PROMPT_VERSION, SCHEMA_VERSION])
    return hashlib.sha256(raw.encode()).hexdigest()
