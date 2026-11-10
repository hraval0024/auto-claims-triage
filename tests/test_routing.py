from app.cost_engine import estimate
from app.routing import route
from app.schemas import Confidence, DamageType, MergedDamageItem, Panel, Side


def item(panel, severity, conf=Confidence.high, side=Side.left):
    return MergedDamageItem(panel=panel, side=side, damage_type=DamageType.dent, severity=severity, confidence=conf,
                            photo_indices=[0], cues=["t"], severity_conflict=False)


def r(items, flags=(), conflicts=(), status="ok", make="Toyota", gate_reasons=None):
    cost = estimate(items, make=make) if status == "ok" else None
    return route(status, items, cost, list(flags), list(conflicts), gate_reasons)


def test_error_goes_to_adjuster():
    d = r([], status="error")
    assert d.outcome == "adjuster_review" and "unavailable" in d.reasons[0]


def test_gate_failure_requests_photos_with_reason():
    d = r([], status="gate_failed", gate_reasons=["Photo 0: no vehicle is the subject"])
    assert d.outcome == "request_more_photos" and "no vehicle" in d.reasons[0]


def test_small_clear_damage_is_fast_track_candidate():
    d = r([item(Panel.rear_bumper, 2), item(Panel.taillamp, 1)])
    assert d.outcome == "fast_track_candidate"
    assert any("human still approves" in x for x in d.reasons)


def test_three_severity4_parts_is_possible_total_loss():
    d = r([item(Panel.fender, 4), item(Panel.front_door, 4), item(Panel.wheel, 4)])
    assert d.outcome == "possible_total_loss"


def test_roof_severity4_is_possible_total_loss():
    d = r([item(Panel.roof, 4, side=Side.center)])
    assert d.outcome == "possible_total_loss" and any("cabin" in x for x in d.reasons)


def test_single_severity4_goes_to_adjuster_with_not_estimable_reason():
    d = r([item(Panel.fender, 4), item(Panel.headlamp, 3)])
    assert d.outcome == "adjuster_review" and any("not estimable" in x for x in d.reasons)


def test_injection_flag_forces_human_even_for_small_damage():
    d = r([item(Panel.rear_bumper, 1)], flags=["embedded_instruction_text"])
    assert d.outcome == "adjuster_review" and any("instructions" in x for x in d.reasons)


def test_photo_conflict_forces_human():
    d = r([item(Panel.rear_bumper, 1)], conflicts=["Photos show different vehicle makes"])
    assert d.outcome == "adjuster_review"


def test_low_confidence_severe_damage_goes_to_human_not_photos():
    d = r([item(Panel.hood, 3, Confidence.low)])
    assert d.outcome == "adjuster_review"


def test_mostly_low_confidence_minor_damage_requests_photos():
    d = r([item(Panel.rear_bumper, 2, Confidence.low), item(Panel.taillamp, 1, Confidence.low), item(Panel.trunk_tailgate, 1)])
    assert d.outcome == "request_more_photos"


def test_no_damage_found_requests_photos():
    d = r([])
    assert d.outcome == "request_more_photos" and "No damage" in d.reasons[0]


def test_high_cost_goes_to_adjuster():
    items = [item(Panel.quarter_panel, 2), item(Panel.rear_door, 2), item(Panel.rocker_panel, 2), item(Panel.rear_bumper, 2)]
    d = r(items)
    assert d.outcome == "adjuster_review" and any("fast-track limit" in x for x in d.reasons)


def test_replacement_is_never_fast_track():
    d = r([item(Panel.side_mirror, 3)])
    assert d.outcome != "fast_track_candidate"


def test_uncertainty_never_moves_toward_fast_track():
    """Lowering confidence on a fast-track claim must never keep it on fast track."""
    base = [item(Panel.rear_bumper, 2)]
    assert r(base).outcome == "fast_track_candidate"
    assert r([item(Panel.rear_bumper, 2, Confidence.low)]).outcome != "fast_track_candidate"
