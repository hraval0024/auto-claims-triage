"""Routing rules: decide the next step for a claim. Never a payout or coverage decision.

Rules are checked in this order; the first outcome whose rules fire wins, and every fired rule
is listed as a reason:
  1. model/API error                      -> adjuster_review
  2. photo quality gate failed             -> request_more_photos
  3. total-loss indicators                 -> possible_total_loss
  4. anything that needs a human           -> adjuster_review
  5. not enough confidence to decide       -> request_more_photos
  6. every fast-track condition holds      -> fast_track_candidate
  7. otherwise                             -> adjuster_review
Uncertainty always moves a claim toward a human, never toward fast track.

routing_v1.1 adds secondary NOTES without changing any outcome or reason: when rule 4 sends a
claim to an adjuster and half or more findings are low confidence, the decision also says which
areas better photos would help with. (Rule 5 can't fire then, because rule 4 returns first;
rule 3, possible total loss, deliberately gets no note: better photos don't change that review.)
"""

from app.schemas import Confidence, CostEstimate, MergedDamageItem, Panel, RoutingDecision

RULES_VERSION = "routing_v1.1"

# ASSUMPTIONS (no source), to be tuned with the carrier:
FAST_TRACK_MAX_HIGH_USD = 2500  # fast track only if the HIGH end is at or below this
FAST_TRACK_MAX_SEVERITY = 2  # no replacement-level damage on fast track
WIDE_RANGE_RATIO = 3.0  # high / low above this = too uncertain for automation
LOW_CONFIDENCE_SHARE = 0.5  # this share of items at low confidence -> ask for better photos
TOTAL_LOSS_MIN_SEVERITY4_ITEMS = 3  # this many severity-4 parts -> possible total loss
CABIN_STRUCTURE = {Panel.roof, Panel.pillar}  # severity 4 here -> possible total loss


def route(
    status: str,
    damage: list[MergedDamageItem],
    cost: CostEstimate | None,
    flags: list[str],
    conflicts: list[str],
    gate_reasons: list[str] | None = None,
) -> RoutingDecision:
    def decide(outcome: str, reasons: list[str], notes: list[str] | None = None) -> RoutingDecision:
        return RoutingDecision(outcome=outcome, reasons=reasons, notes=notes or [], rules_version=RULES_VERSION)

    # 1. Error: never fabricate, send to a person.
    if status == "error":
        return decide("adjuster_review", ["Automated assessment was unavailable, so a human adjuster must review the photos."])

    # 2. Gate failed: say what photo to send.
    if status == "gate_failed":
        return decide("request_more_photos", ["The photos could not be assessed: " + "; ".join(gate_reasons or ["photo quality check failed"])])

    sev4 = [d for d in damage if d.severity >= 4]

    # 3. Total-loss indicators.
    tl = []
    if len({(d.panel, d.side) for d in sev4}) >= TOTAL_LOSS_MIN_SEVERITY4_ITEMS:
        tl.append(f"{len(sev4)} parts have structural or safety-level damage (severity 4).")
    cabin = [d for d in sev4 if d.panel in CABIN_STRUCTURE]
    if cabin:
        tl.append("Severity-4 damage to the cabin structure (" + ", ".join(f"{d.side} {d.panel}" for d in cabin) + ").")
    if tl:
        return decide("possible_total_loss", tl + ["Possible total loss only: an adjuster must confirm against the vehicle's value."])

    # 4. Needs a human.
    human = []
    if sev4:
        human.append("Severity-4 damage (" + ", ".join(f"{d.side} {d.panel}" for d in sev4) + "): cost not estimable from photos.")
    if cost is not None and cost.status == "not_estimable" and not sev4:
        human.append("Part of the damage cannot be priced from photos: " + "; ".join(cost.not_estimable_reasons) + ".")
    if "embedded_instruction_text" in flags:
        human.append("A photo contains text that looks like instructions to the system; it was ignored, but a human should check the claim.")
    if conflicts:
        human.append("The photos disagree: " + " ".join(conflicts))
    low_conf_severe = [d for d in damage if d.severity >= 3 and d.confidence == Confidence.low]
    if low_conf_severe:
        human.append("Replacement-level damage reported with low confidence (" + ", ".join(f"{d.side} {d.panel}" for d in low_conf_severe) + ").")
    if cost is not None and cost.status == "estimated":
        if cost.high_usd > FAST_TRACK_MAX_HIGH_USD:
            human.append(f"Estimated range reaches ${cost.high_usd:,.0f}, above the ${FAST_TRACK_MAX_HIGH_USD:,} fast-track limit.")
        if cost.low_usd and cost.high_usd / cost.low_usd > WIDE_RANGE_RATIO:
            human.append(f"The cost range is wide (high is {cost.high_usd / cost.low_usd:.1f}x the low), so the estimate is too uncertain to automate.")
    if human:
        return decide("adjuster_review", human, notes=_better_photos_note(damage))

    # 5. Not enough confidence to decide.
    unsure = []
    if not damage:
        unsure.append("No damage was found in the photos. Send close-ups of the area that was damaged.")
    elif sum(d.confidence == Confidence.low for d in damage) / len(damage) >= LOW_CONFIDENCE_SHARE:
        unsure.append("Most damage findings have low confidence. Clearer, closer photos of the damaged area are needed.")
    if unsure:
        return decide("request_more_photos", unsure)

    # 6. Fast track: every condition must hold.
    blockers = []
    if any(d.severity > FAST_TRACK_MAX_SEVERITY for d in damage):
        blockers.append(f"some damage is above severity {FAST_TRACK_MAX_SEVERITY}")
    if any(d.confidence == Confidence.low for d in damage):
        blockers.append("some findings have low confidence")
    if cost is None or cost.status != "estimated":
        blockers.append("no complete cost estimate")
    if not blockers:
        return decide("fast_track_candidate", [
            f"All damage is severity {FAST_TRACK_MAX_SEVERITY} or lower with medium or high confidence.",
            f"Estimated range ${cost.low_usd:,.0f}-${cost.high_usd:,.0f} is within the ${FAST_TRACK_MAX_HIGH_USD:,} fast-track limit.",
            "Candidate only: a human still approves any payment.",
        ])

    # 7. Default to a human.
    return decide("adjuster_review", ["Does not meet fast-track criteria: " + "; ".join(blockers) + "."])


def _area(d: MergedDamageItem) -> str:
    panel = d.panel.value.replace("_", " ")
    return f"{d.side.value} {panel}" if d.side.value in ("left", "right") else panel


def _better_photos_note(damage: list[MergedDamageItem]) -> list[str]:
    """routing_v1.1: secondary note for adjuster_review when half or more findings are low confidence."""
    if not damage:
        return []
    low = [d for d in damage if d.confidence == Confidence.low]
    if len(low) / len(damage) < LOW_CONFIDENCE_SHARE:
        return []
    areas = list(dict.fromkeys(_area(d) for d in low))  # unique, in order
    joined = areas[0] if len(areas) == 1 else ", ".join(areas[:-1]) + " and " + areas[-1]
    return [f"Better photos of the {joined} would help: {len(low)} of {len(damage)} findings are low confidence."]
