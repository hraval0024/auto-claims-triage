"""Adjuster review: accept/reject, field edits, corrections log, re-price with corrections.

Originals come from the stored result (app/store.py), never from the client. Every changed
field becomes one corrections row: (field, original, corrected, timestamp, request id).
Items an adjuster sets are treated as high confidence: a human has confirmed them.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app import store
from app.cost_engine import estimate
from app.routing import route
from app.schemas import (
    ClaimResult,
    Confidence,
    CostEstimate,
    DamageType,
    MergedDamageItem,
    Panel,
    RoutingDecision,
    Side,
)


class ReviewDamageItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    orig_index: int | None = None  # index in the stored damage list; None = added by adjuster
    removed: bool = False
    panel: Panel
    side: Side
    damage_type: DamageType
    severity: Literal[1, 2, 3, 4]


class ReviewVehicle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    make: str
    model: str
    color: str
    year_start: int | None = None
    year_end: int | None = None


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accept", "reject"]
    vehicle: ReviewVehicle | None = None
    damage: list[ReviewDamageItem] = []
    damage_summary: str | None = None
    not_assessable: list[str] | None = None
    region: Literal["low_cost", "standard", "high_cost"] | None = None


class ReviewResult(BaseModel):
    request_id: str
    decision: str
    corrections: list[dict]
    logged_at: str
    cost: CostEstimate | None
    routing: RoutingDecision
    note: str


def _item_str(panel, side, dtype, sev) -> str:
    return f"{side} {panel} {dtype} severity {sev}"


def diff(orig: ClaimResult, req: ReviewRequest) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    if req.vehicle and orig.vehicle:
        v, rv = orig.vehicle, req.vehicle
        for name, old, new in [
            ("vehicle.make", v.make.value, rv.make), ("vehicle.model", v.model.value, rv.model),
            ("vehicle.color", v.color.value, rv.color),
            ("vehicle.year_start", v.year_range.start, rv.year_start), ("vehicle.year_end", v.year_range.end, rv.year_end),
        ]:
            if str(old) != str(new):
                out.append((name, str(old), str(new)))
    seen = set()
    for it in req.damage:
        new = _item_str(it.panel, it.side, it.damage_type, it.severity)
        if it.orig_index is None:
            if not it.removed:
                out.append(("damage[+]", "(none)", new))
            continue
        if not 0 <= it.orig_index < len(orig.damage):
            raise ValueError(f"orig_index {it.orig_index} does not exist")
        seen.add(it.orig_index)
        o = orig.damage[it.orig_index]
        if it.removed:
            out.append((f"damage[{it.orig_index}]", _item_str(o.panel, o.side, o.damage_type, o.severity), "(removed)"))
            continue
        for fname in ("panel", "side", "damage_type", "severity"):
            old_v, new_v = getattr(o, fname), getattr(it, fname)
            if str(old_v) != str(new_v):
                out.append((f"damage[{it.orig_index}].{fname}", str(old_v), str(new_v)))
    if req.damage and len(seen) != len(orig.damage):
        missing = sorted(set(range(len(orig.damage))) - seen)
        raise ValueError(f"every original damage item must be sent back (missing indices {missing}); mark deletions with removed=true")
    if req.damage_summary is not None and req.damage_summary != (orig.damage_summary or ""):
        out.append(("damage_summary", orig.damage_summary or "", req.damage_summary))
    if req.not_assessable is not None and req.not_assessable != orig.not_assessable:
        out.append(("not_assessable", "; ".join(orig.not_assessable), "; ".join(req.not_assessable)))
    if req.region is not None and orig.cost is not None and req.region != orig.cost.region:
        out.append(("cost.region", orig.cost.region, req.region))
    return out


def review(request_id: str, req: ReviewRequest) -> ReviewResult:
    stored = store.get_result(request_id)
    if stored is None:
        raise KeyError(request_id)
    orig = ClaimResult.model_validate(stored)
    corrections = diff(orig, req)
    logged_at = store.log_review(request_id, req.decision, corrections)

    cost, routing, note = orig.cost, orig.routing, "No re-pricing: the claim was rejected or had no assessment."
    if req.decision == "accept" and orig.status == "ok":
        if req.damage:
            items = [MergedDamageItem(panel=i.panel, side=i.side, damage_type=i.damage_type, severity=i.severity,
                                      confidence=Confidence.high, photo_indices=[], cues=["set by adjuster"],
                                      severity_conflict=False)
                     for i in req.damage if not i.removed]
        else:
            items = orig.damage
        make = req.vehicle.make if req.vehicle else (orig.vehicle.make.value if orig.vehicle else None)
        region = req.region or (orig.cost.region if orig.cost else None)
        cost = estimate(items, make=make, region=region)
        routing = route("ok", items, cost, orig.flags, orig.conflicts, orig.gate.reasons)
        note = "Re-priced and re-routed with the adjuster's corrections (adjuster-set items count as high confidence)."
    return ReviewResult(request_id=request_id, decision=req.decision,
                        corrections=[{"field": f, "original": o, "corrected": n} for f, o, n in corrections],
                        logged_at=logged_at, cost=cost, routing=routing, note=note)
