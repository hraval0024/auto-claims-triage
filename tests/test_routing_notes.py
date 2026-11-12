"""routing_v1.1: secondary 'better photos' note on adjuster_review, outcomes and reasons unchanged."""

import pytest
from fastapi.testclient import TestClient

from app import pipeline
from app.cost_engine import estimate
from app.llm import UsageTally
from app.main import app
from app.routing import RULES_VERSION, route
from app.schemas import Confidence, DamageType, MergedDamageItem, ModelOutput, Panel, Side
from tests.helpers import AUTH, model_output_dict, textured_jpeg

L, M, H = Confidence.low, Confidence.medium, Confidence.high


def item(panel, severity, conf, side=Side.right, dtype=DamageType.deformation):
    return MergedDamageItem(panel=panel, side=side, damage_type=dtype, severity=severity, confidence=conf,
                            photo_indices=[0], cues=["t"], severity_conflict=False)


def r(items, status="ok", flags=(), make="Mercedes-Benz", gate_reasons=None):
    cost = estimate(items, make=make) if status == "ok" else None
    return route(status, items, cost, list(flags), [], gate_reasons)


# 1. The Mercedes shape (case8_multiphoto_mercedes_a.jpg, local rehearsal request 835809ea)
def test_mercedes_case_keeps_v1_outcome_and_reasons_and_adds_note():
    d = r([item(Panel.wheel, 4, L, dtype=DamageType.misalignment), item(Panel.fender, 3, L)])
    assert d.outcome == "adjuster_review"
    assert d.reasons == [  # exactly the routing_v1 reasons
        "Severity-4 damage (right wheel): cost not estimable from photos.",
        "Replacement-level damage reported with low confidence (right wheel, right fender).",
    ]
    assert d.notes == ["Better photos of the right wheel and right fender would help: 2 of 2 findings are low confidence."]
    assert d.rules_version == "routing_v1.1" == RULES_VERSION


# 2. Below the threshold: 1 of 3 low
def test_below_threshold_no_note():
    d = r([item(Panel.hood, 3, H, Side.center), item(Panel.front_bumper, 3, H, Side.center), item(Panel.taillamp, 2, L)])
    assert d.outcome == "adjuster_review" and d.notes == []


# 3. Exactly at the threshold: 1 of 2 low (0.5 >= 0.5)
def test_at_threshold_note_present():
    d = r([item(Panel.hood, 3, H, Side.center), item(Panel.taillamp, 2, L, Side.left)])
    assert d.outcome == "adjuster_review"
    assert d.notes == ["Better photos of the left taillamp would help: 1 of 2 findings are low confidence."]


# 4. Wording: only low items, deduplicated, centre panels without "center", underscores to spaces
def test_note_wording():
    d = r([item(Panel.front_bumper, 3, L, Side.center, DamageType.crack),
           item(Panel.front_bumper, 3, L, Side.center, DamageType.missing_part),
           item(Panel.side_mirror, 3, L, Side.left),
           item(Panel.hood, 2, H, Side.center)])
    assert d.notes == ["Better photos of the front bumper and left side mirror would help: 3 of 4 findings are low confidence."]
    three = r([item(Panel.hood, 3, L, Side.center), item(Panel.fender, 3, L, Side.left), item(Panel.headlamp, 3, L, Side.left)])
    assert three.notes[0].startswith("Better photos of the hood, left fender and left headlamp would help")


# 5. No regression: every outcome and its reasons are unchanged from routing_v1; notes are separate
@pytest.mark.parametrize("items,kw,outcome", [
    ([], {"status": "error"}, "adjuster_review"),
    ([], {"status": "gate_failed", "gate_reasons": ["Photo 0: no vehicle"]}, "request_more_photos"),
    ([item(Panel.roof, 4, H, Side.center)], {}, "possible_total_loss"),
    ([item(Panel.fender, 4, H), item(Panel.front_door, 4, H), item(Panel.wheel, 4, H)], {}, "possible_total_loss"),
    ([item(Panel.rear_bumper, 1, H, Side.center)], {"flags": ["embedded_instruction_text"]}, "adjuster_review"),
    ([item(Panel.rear_bumper, 2, L, Side.center), item(Panel.taillamp, 1, L), item(Panel.trunk_tailgate, 1, H, Side.center)], {}, "request_more_photos"),
    ([], {}, "request_more_photos"),
    ([item(Panel.rear_bumper, 2, H, Side.center)], {"make": "Toyota"}, "fast_track_candidate"),
])
def test_outcomes_unchanged_and_notes_never_leak_into_reasons(items, kw, outcome):
    d = r(items, **kw)
    assert d.outcome == outcome
    assert not any("Better photos of the" in x for x in d.reasons)


# 6. Notes only on rule-4 adjuster_review
@pytest.mark.parametrize("items,kw", [
    ([], {"status": "error"}),
    ([], {"status": "gate_failed", "gate_reasons": ["x"]}),
    ([item(Panel.roof, 4, L, Side.center), item(Panel.pillar, 4, L, Side.left)], {}),  # possible_total_loss with all-low findings
    ([item(Panel.rear_bumper, 2, L, Side.center), item(Panel.taillamp, 1, L)], {"make": "Toyota"}),  # rule 5 already asks for photos
    ([item(Panel.rear_bumper, 2, H, Side.center)], {"make": "Toyota"}),  # fast track
])
def test_no_note_outside_rule_4(items, kw):
    d = r(items, **kw)
    assert d.notes == [], (d.outcome, d.notes)


# 7. After an adjuster accepts corrections, items count as high confidence: the note goes away.
#    An unedited accept changes nothing (review_ux), so the note stays.
def test_note_disappears_after_adjuster_review(monkeypatch):
    damage = [
        {"photo_index": 0, "panel": "wheel", "side": "right", "damage_type": "misalignment", "severity": 4, "confidence": "low", "cues": "a"},
        {"photo_index": 0, "panel": "fender", "side": "right", "damage_type": "deformation", "severity": 3, "confidence": "low", "cues": "b"},
    ]
    monkeypatch.setattr(pipeline, "call_model", lambda images, **kw: (
        ModelOutput.model_validate(model_output_dict(damage=damage)), UsageTally("claude-sonnet-5-5", 1000, 0, 0, 100, 1)))
    c = TestClient(app, headers=AUTH)
    claim = c.post("/api/claims", files=[("files", ("a.jpg", textured_jpeg(), "image/jpeg"))]).json()
    assert claim["routing"]["notes"] and claim["routing"]["outcome"] == "adjuster_review"
    items = [{"orig_index": i, "removed": False, "panel": d["panel"], "side": d["side"], "damage_type": d["damage_type"],
              "severity": d["severity"]} for i, d in enumerate(claim["damage"])]
    url = f"/api/claims/{claim['audit']['request_id']}/review"
    as_is = c.post(url, json={"decision": "accept", "damage": items}).json()
    assert as_is["corrections"] == [] and as_is["routing"] == claim["routing"]
    items[1]["severity"] = 2  # one real correction: fender severity 3 -> 2
    rev = c.post(url, json={"decision": "accept", "damage": items}).json()
    assert len(rev["corrections"]) == 1 and rev["routing"]["notes"] == []


# 8. API carries the new versions and field; the UI renders notes as text
def test_api_versions_and_ui_rendering(monkeypatch):
    monkeypatch.setattr(pipeline, "call_model", lambda images, **kw: (
        ModelOutput.model_validate(model_output_dict()), UsageTally("claude-sonnet-5-5", 1000, 0, 0, 100, 1)))
    c = TestClient(app, headers=AUTH)
    body = c.post("/api/claims", files=[("files", ("a.jpg", textured_jpeg(), "image/jpeg"))]).json()
    assert body["audit"]["schema_version"] == "1.3.0" and body["routing"]["rules_version"] == "routing_v1.1"
    assert "notes" in body["routing"]
    js = c.get("/static/app.js").text
    assert "Also recommended" in js and "routing.notes.map((x) => el(\"li\", {}, x))" in js and ".innerHTML" not in js
