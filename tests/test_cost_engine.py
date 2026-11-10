import pytest

from app.cost_engine import estimate, load_table
from app.schemas import Confidence, DamageType, MergedDamageItem, Panel, Side


def item(panel, severity, side=Side.left, dtype=DamageType.dent, conf=Confidence.high):
    return MergedDamageItem(panel=panel, side=side, damage_type=dtype, severity=severity, confidence=conf,
                            photo_indices=[0], cues=["test"], severity_conflict=False)


def test_every_row_has_source_and_confidence_and_low_le_high():
    t = load_table()
    for r in t["rows"]:
        assert r["source"] and r["confidence"]
        if r["source"] == "assumption":
            assert r["confidence"] == "low"
        for k in ("body_hours", "refinish_hours", "parts_usd"):
            assert r[k][0] <= r[k][1], (r, k)


def test_table_covers_every_priced_class_and_severity_1_to_3():
    t = load_table()
    for cls in t["panel_classes"]:
        if cls == "not_estimable":
            continue
        for sev in (1, 2, 3):
            assert (cls, sev) in t["_rows"], (cls, sev)


def test_every_panel_in_the_schema_has_a_class():
    t = load_table()
    assert {p.value for p in Panel} == set(t["_panel_class"])


def test_hand_computed_bumper_repair_mainstream():
    # bumper_cover sev2: body 1.0-3.0, refinish 2.0-3.5, parts 0-50; rate 68; materials 30-50
    e = estimate([item(Panel.rear_bumper, 2)], make="Toyota")
    low = (1.0 + 2.0) * 68 + 2.0 * 30 + 0
    high = (3.0 + 3.5) * 68 + 3.5 * 50 + 50
    assert e.status == "estimated"
    assert e.low_usd == round(low / 10) * 10 and e.high_usd == round(high / 10) * 10
    assert e.mid_usd == round(((e.low_usd + e.high_usd) / 2) / 10) * 10
    assert not e.hidden_damage_uplift_applied


def test_side_does_not_change_cost():
    left = estimate([item(Panel.fender, 3, Side.left), item(Panel.headlamp, 2, Side.left)], make="Honda")
    right = estimate([item(Panel.fender, 3, Side.right), item(Panel.headlamp, 2, Side.right)], make="Honda")
    assert (left.low_usd, left.mid_usd, left.high_usd) == (right.low_usd, right.mid_usd, right.high_usd)


def test_severity_4_is_not_estimable_but_subtotal_kept():
    e = estimate([item(Panel.fender, 4), item(Panel.headlamp, 3)], make="Nissan")
    assert e.status == "not_estimable"
    assert e.low_usd is None and e.mid_usd is None and e.high_usd is None
    assert e.estimable_subtotal_low_usd and e.estimable_subtotal_high_usd
    assert any("severity 4" in r for r in e.not_estimable_reasons)


def test_pillar_is_never_priced():
    e = estimate([item(Panel.pillar, 1)], make="Ford")
    assert e.status == "not_estimable"


def test_same_part_priced_once_at_highest_severity():
    one = estimate([item(Panel.hood, 3, Side.center)], make="Ford")
    two = estimate([item(Panel.hood, 3, Side.center, DamageType.deformation),
                    item(Panel.hood, 2, Side.center, DamageType.scratch_scuff)], make="Ford")
    assert (one.low_usd, one.high_usd) == (two.low_usd, two.high_usd)
    assert len(two.lines) == 1


def test_luxury_make_raises_parts_and_unknown_make_widens():
    mainstream = estimate([item(Panel.headlamp, 3)], make="Toyota")
    luxury = estimate([item(Panel.headlamp, 3)], make="BMW")
    unknown = estimate([item(Panel.headlamp, 3)], make="unknown")
    assert luxury.high_usd > mainstream.high_usd and luxury.vehicle_class == "luxury_truck"
    assert unknown.low_usd < mainstream.low_usd and unknown.high_usd == luxury.high_usd


def test_replacement_adds_hidden_damage_uplift_to_high_only():
    e = estimate([item(Panel.front_bumper, 3, Side.center)], make="Toyota")
    t = load_table()
    r = t["_rows"][("bumper_cover", 3)]
    raw_high = (r["body_hours"][1] + r["refinish_hours"][1]) * 68 + r["refinish_hours"][1] * 50 + r["parts_usd"][1]
    assert e.hidden_damage_uplift_applied
    assert e.high_usd == round(raw_high * 1.25 / 10) * 10


def test_region_scales_labor():
    std = estimate([item(Panel.front_door, 2)], make="Kia", region="standard")
    high = estimate([item(Panel.front_door, 2)], make="Kia", region="high_cost")
    assert high.low_usd > std.low_usd


def test_no_damage_is_zero_range():
    e = estimate([], make="Toyota")
    assert e.status == "no_damage" and e.high_usd == 0


def test_response_is_labeled_as_assumption():
    e = estimate([item(Panel.hood, 1)], make="Toyota")
    assert e.is_assumption and "assumption" in e.assumption_notice.lower()
    assert e.cost_table_version == "cost_table_v1"
    assert any("not real pricing" in c for c in e.caveats)


@pytest.mark.parametrize("make", ["Toyota", "BMW", "unknown"])
def test_low_never_exceeds_high(make):
    items = [item(p, s) for p, s in [(Panel.front_bumper, 3), (Panel.hood, 2), (Panel.windshield, 3), (Panel.tire, 1)]]
    e = estimate(items, make=make)
    assert e.low_usd <= e.mid_usd <= e.high_usd
