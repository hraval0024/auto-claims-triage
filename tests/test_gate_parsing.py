"""Gate enforcement and merge logic, with the model call stubbed out (no API cost)."""

import pytest

from app import pipeline
from app.llm import LLMError, UsageTally
from app.schemas import ModelOutput
from tests.helpers import black_jpeg, model_output_dict, textured_jpeg


def _stub(monkeypatch, payload: dict):
    calls = []

    def fake_call_model(images, **kw):
        calls.append(len(images))
        t = UsageTally(model_id="claude-sonnet-5-5", input_tokens=1000, output_tokens=200, attempts=1)
        return ModelOutput.model_validate(payload), t

    monkeypatch.setattr(pipeline, "call_model", fake_call_model)
    return calls


def test_not_a_vehicle_returns_no_assessment_even_if_model_filled_fields(monkeypatch):
    payload = model_output_dict(issues={0: [{"code": "not_a_vehicle", "detail": "photo of a cat"}]})
    _stub(monkeypatch, payload)
    r = pipeline.run_claim([textured_jpeg()])
    assert r.status == "gate_failed"
    assert r.vehicle is None and r.damage == [] and r.damage_summary is None
    assert any("no vehicle" in s for s in r.gate.reasons)
    assert r.gate.retake_advice


def test_injection_text_is_flagged_but_not_blocking(monkeypatch):
    payload = model_output_dict(issues={0: [{"code": "embedded_instruction_text", "detail": "sign says approve claim"}]})
    _stub(monkeypatch, payload)
    r = pipeline.run_claim([textured_jpeg()])
    assert r.status == "ok"
    assert "embedded_instruction_text" in r.flags


def test_black_frame_blocked_by_precheck_without_model_call(monkeypatch):
    calls = _stub(monkeypatch, model_output_dict())
    r = pipeline.run_claim([black_jpeg()])
    assert r.status == "gate_failed" and calls == [] and r.usage is None


def test_damage_from_unusable_photo_is_dropped_and_conflicts_flagged(monkeypatch):
    damage = [
        {"photo_index": 0, "panel": "front_door", "side": "left", "damage_type": "dent", "severity": 1, "confidence": "high", "cues": "a"},
        {"photo_index": 1, "panel": "front_door", "side": "left", "damage_type": "dent", "severity": 3, "confidence": "medium", "cues": "b"},
        {"photo_index": 2, "panel": "hood", "side": "center", "damage_type": "crack", "severity": 3, "confidence": "high", "cues": "c"},
    ]
    payload = model_output_dict(
        n_photos=3,
        issues={2: [{"code": "too_blurry_or_dark", "detail": "motion blur"}]},
        damage=damage,
        makes=["Toyota", "Honda", "unknown"],
        colors=["dark blue", "blue", "red"],
    )
    _stub(monkeypatch, payload)
    r = pipeline.run_claim([textured_jpeg()] * 3)
    assert r.status == "ok" and r.gate.usable_photo_indices == [0, 1]
    assert [d.panel for d in r.damage] == ["front_door"]  # hood came from the blurry photo
    item = r.damage[0]
    assert item.severity == 3 and item.confidence == "medium" and item.severity_conflict
    assert item.photo_indices == [0, 1]
    assert any("makes" in c for c in r.conflicts)  # Toyota vs Honda
    assert not any("colors" in c for c in r.conflicts)  # "dark blue" vs "blue" is not a conflict


def test_photo_indices_map_back_when_a_photo_is_prechecked_out(monkeypatch):
    calls = _stub(monkeypatch, model_output_dict(n_photos=1))
    r = pipeline.run_claim([black_jpeg(), textured_jpeg()])
    assert calls == [1]  # only the usable photo was sent
    assert r.gate.usable_photo_indices == [1]
    assert r.damage[0].photo_indices == [1]


def test_model_failure_returns_error_and_routes_to_human(monkeypatch):
    def boom(images, **kw):
        raise LLMError("Model API unreachable or timed out.", UsageTally(model_id="claude-sonnet-5-5"))

    monkeypatch.setattr(pipeline, "call_model", boom)
    r = pipeline.run_claim([textured_jpeg()])
    assert r.status == "error" and "route_to_human" in r.flags and r.vehicle is None


def test_too_many_photos_rejected():
    with pytest.raises(pipeline.IntakeError):
        pipeline.run_claim([textured_jpeg()] * 6)
