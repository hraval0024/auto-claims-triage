"""End-to-end wiring with the model stubbed (no API cost): API -> pipeline -> cost -> routing."""

from fastapi.testclient import TestClient

from app import pipeline
from app.llm import LLMError, UsageTally
from app.main import app
from app.schemas import LLMCostGuess, ModelOutput
from tests.helpers import AUTH, model_output_dict, textured_jpeg

client = TestClient(app, headers=AUTH)


def _stub(monkeypatch, payload=None, baseline=None):
    calls = {"extract": 0, "baseline": 0}

    def fake_call(images, **kw):
        calls["extract"] += 1
        return ModelOutput.model_validate(payload or model_output_dict()), UsageTally("claude-sonnet-5-5", 1000, 0, 0, 200, 1)

    def fake_guess(images, **kw):
        calls["baseline"] += 1
        if baseline == "fail":
            raise LLMError("Baseline call failed.", UsageTally("claude-sonnet-5-5"))
        return LLMCostGuess(low_usd=1, point_usd=999999, high_usd=9999999, rationale="t"), UsageTally("claude-sonnet-5-5", 500, 0, 0, 50, 1)

    monkeypatch.setattr(pipeline, "call_model", fake_call)
    monkeypatch.setattr(pipeline, "guess_cost", fake_guess)
    return calls


def post(**form):
    return client.post("/api/claims", files=[("files", ("a.jpg", textured_jpeg(), "image/jpeg"))], data=form)


def test_ok_claim_has_cost_routing_and_assumption_label(monkeypatch):
    _stub(monkeypatch)
    body = post().json()
    assert body["status"] == "ok"
    assert body["cost"]["status"] == "estimated" and body["cost"]["is_assumption"] is True
    assert body["cost"]["region"] == "standard"
    assert body["routing"]["outcome"] in {"fast_track_candidate", "adjuster_review", "request_more_photos", "possible_total_loss"}
    assert body["routing"]["reasons"]
    assert body["audit"]["cost_table_version"] == "cost_table_v1"
    assert body["llm_baseline"] is None  # off by default


def test_region_input_changes_labor(monkeypatch):
    _stub(monkeypatch)
    std = post(region="standard").json()["cost"]
    high = post(region="high_cost").json()["cost"]
    assert high["labor_rate_usd_per_hour"] > std["labor_rate_usd_per_hour"] and high["low_usd"] > std["low_usd"]


def test_invalid_region_rejected(monkeypatch):
    _stub(monkeypatch)
    assert post(region="mars").status_code == 422


def test_baseline_never_changes_cost_or_routing(monkeypatch):
    calls = _stub(monkeypatch)
    off = post().json()
    on = post(include_llm_baseline="true").json()
    assert calls["baseline"] == 1
    assert on["llm_baseline"]["guess"]["point_usd"] == 999999
    assert on["cost"]["low_usd"] == off["cost"]["low_usd"] and on["cost"]["high_usd"] == off["cost"]["high_usd"]
    assert on["routing"] == off["routing"]


def test_failed_baseline_is_reported_and_harmless(monkeypatch):
    _stub(monkeypatch, baseline="fail")
    body = post(include_llm_baseline="true").json()
    assert body["status"] == "ok" and body["cost"]["status"] == "estimated"
    assert body["llm_baseline"]["guess"] is None and "failed" in body["llm_baseline"]["error"]


def test_gate_failure_is_routed_and_unpriced(monkeypatch):
    calls = _stub(monkeypatch, payload=model_output_dict(issues={0: [{"code": "not_a_vehicle", "detail": "a dog"}]}))
    body = post(include_llm_baseline="true").json()
    assert body["status"] == "gate_failed" and body["cost"] is None
    assert body["routing"]["outcome"] == "request_more_photos"
    assert calls["baseline"] == 0  # no baseline spend on refused photos


def test_model_error_is_routed_to_adjuster(monkeypatch):
    def boom(images, **kw):
        raise LLMError("Model API unreachable or timed out.", UsageTally("claude-sonnet-5-5"))

    monkeypatch.setattr(pipeline, "call_model", boom)
    body = post().json()
    assert body["status"] == "error" and body["routing"]["outcome"] == "adjuster_review"


def test_severity4_claim_is_not_estimable_with_partial_label(monkeypatch):
    payload = model_output_dict(damage=[
        {"photo_index": 0, "panel": "fender", "side": "left", "damage_type": "deformation", "severity": 4, "confidence": "high", "cues": "x"},
        {"photo_index": 0, "panel": "headlamp", "side": "left", "damage_type": "shatter", "severity": 3, "confidence": "high", "cues": "y"},
    ])
    _stub(monkeypatch, payload=payload)
    c = post().json()["cost"]
    assert c["status"] == "not_estimable" and c["low_usd"] is None
    assert c["partial_label"] == "partial, excludes severity-4 items" and c["partial_high_usd"] > 0
