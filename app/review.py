"""Adjuster review: accept/reject, field edits, corrections log, re-price with corrections.

Originals come from the stored result (app/store.py), never from the client. Every changed
field becomes one corrections row: (field, original, corrected, timestamp, request id).
Items an adjuster sets are treated as high confidence: a human has confirmed them.

An accept with zero corrections changes nothing: the stored cost and route stand. Only an accept
with at least one correction re-prices and re-routes.

Route override (accept only): the adjuster may set a final route different from the system's
recommendation, with a required reason in `notes`. It changes ONLY the route: never the cost, and
there is no approved/paid state.

Estimate override (accept only): the adjuster may set a final low/high range (whole dollars). It
replaces the displayed final estimate only: it never re-routes and never touches the cost engine.
It is logged as corrections "estimate.low" / "estimate.high". Notes may contain personal data: stored in reviews.notes only,
never logged.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    RoutingOutcome,
    Side,
)

NOTES_MAX = 1000
USD_MAX = 500_000


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
    notes: str | None = Field(default=None, max_length=NOTES_MAX)
    final_route: RoutingOutcome | None = None  # None or the system's own route = no override
    # Adjuster-set estimate: both or neither; None = the system range stands (also after re-pricing).
    final_low_usd: int | None = Field(default=None, ge=0, le=USD_MAX)
    final_high_usd: int | None = Field(default=None, ge=0, le=USD_MAX)

    @field_validator("notes", mode="before")
    @classmethod
    def _trim_notes(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v


class ReviewResult(BaseModel):
    request_id: str
    decision: str
    corrections: list[dict]
    logged_at: str
    cost: CostEstimate | None
    routing: RoutingDecision  # the system's recommendation (re-routed only if there were corrections)
    note: str
    notes: str | None
    system_route: RoutingOutcome  # what the stored result recommended
    final_route: RoutingOutcome  # the route that stands after the review
    route_overridden: bool
    system_low_usd: int | None  # the stored result's range before the review; None when not estimated
    system_high_usd: int | None
    final_low_usd: int | None  # the adjuster's range when overridden, else the range that stands
    final_high_usd: int | None
    estimate_overridden: bool


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


def _range(cost: CostEstimate | None) -> tuple[int | None, int | None]:
    """The priced low/high in whole dollars, or (None, None) when there is no full estimate."""
    if cost is None or cost.status != "estimated" or cost.low_usd is None or cost.high_usd is None:
        return None, None
    return int(round(cost.low_usd)), int(round(cost.high_usd))


def review(request_id: str, req: ReviewRequest) -> ReviewResult:
    stored = store.get_result(request_id)
    if stored is None:
        raise KeyError(request_id)
    orig = ClaimResult.model_validate(stored)
    system_route = orig.routing.outcome
    # Selecting the system's own route is not an override.
    overridden = req.final_route is not None and req.final_route != system_route
    if overridden and req.decision != "accept":
        raise ValueError("A route override is only allowed with accept, not reject.")
    if overridden and not req.notes:
        raise ValueError("A route override needs a reason: add it in the adjuster notes.")
    if (req.final_low_usd is None) != (req.final_high_usd is None):
        raise ValueError("Enter both a low and a high value for the final estimate, or neither.")
    if req.final_low_usd is not None and req.final_low_usd > req.final_high_usd:
        raise ValueError("Final estimate: low must not be higher than high.")
    system_low, system_high = _range(orig.cost)
    # Sending the system's own range is not an override (same rule as the route).
    est_overridden = req.final_low_usd is not None and (req.final_low_usd, req.final_high_usd) != (system_low, system_high)
    if est_overridden and req.decision != "accept":
        raise ValueError("An adjuster-set estimate is only allowed with accept, not reject.")
    corrections = diff(orig, req)  # validates before anything is logged

    cost, routing, note = orig.cost, orig.routing, "No re-pricing: the claim was rejected or had no assessment."
    if req.decision == "accept" and not corrections:
        note = "Accepted as is. No changes were made."
    elif req.decision == "accept" and orig.status == "ok":
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
    # The override replaces the route that stands after any re-routing; the cost is untouched.
    final_route = req.final_route if overridden else routing.outcome
    # The adjuster's range replaces the displayed final estimate only: computed after routing, never
    # fed back into it. Without an override, the range that stands (re-priced if corrected) is final.
    if est_overridden:
        final_low, final_high = req.final_low_usd, req.final_high_usd
        note = ("Accepted with an adjuster-set estimate." if not corrections else note) + \
            " The adjuster's range replaces the displayed estimate only; routing is unchanged by it."
        for name, sys_v, new_v in (("estimate.low", system_low, final_low), ("estimate.high", system_high, final_high)):
            corrections.append((name, "not estimable" if sys_v is None else str(sys_v), str(new_v)))
    else:
        final_low, final_high = _range(cost)
    logged_at = store.log_review(request_id, req.decision, corrections, notes=req.notes, system_route=system_route,
                                 final_route=final_route, route_overridden=overridden,
                                 system_low_usd=system_low, system_high_usd=system_high, final_low_usd=final_low,
                                 final_high_usd=final_high, estimate_overridden=est_overridden)
    return ReviewResult(request_id=request_id, decision=req.decision,
                        corrections=[{"field": f, "original": o, "corrected": n} for f, o, n in corrections],
                        logged_at=logged_at, cost=cost, routing=routing, note=note, notes=req.notes,
                        system_route=system_route, final_route=final_route, route_overridden=overridden,
                        system_low_usd=system_low, system_high_usd=system_high, final_low_usd=final_low,
                        final_high_usd=final_high, estimate_overridden=est_overridden)
