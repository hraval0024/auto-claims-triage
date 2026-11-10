"""Cost protection: rate limits, daily call/spend caps (fail closed), concurrency cap,
image-hash cache, idempotency, claim deadline. The model is stubbed: no API cost."""

import json
import logging
import time

from fastapi.testclient import TestClient

from app import guards, llm, pipeline, store
from app.config import settings
from app.llm import UsageTally
from app.main import app
from app.schemas import ModelOutput
from tests.helpers import AUTH, model_output_dict, textured_jpeg

client = TestClient(app, headers=AUTH)


def stub(monkeypatch, cost_usd=0.01):
    calls = []

    def fake(images, **kw):
        calls.append(kw)
        t = UsageTally("claude-sonnet-5-5", input_tokens=int(cost_usd * 1e6 / 2), attempts=1)  # input @ $2/MTok
        return ModelOutput.model_validate(model_output_dict(n_photos=len(images))), t

    monkeypatch.setattr(pipeline, "call_model", fake)
    return calls


def post(img=None, headers=None):
    return client.post("/api/claims", files=[("files", ("a.jpg", img or textured_jpeg(), "image/jpeg"))], headers=headers or {})


def test_claims_rate_limit_per_ip(monkeypatch, caplog):
    stub(monkeypatch)
    monkeypatch.setattr(settings, "rate_limit_claims_per_min", 2)
    assert post().status_code == 200 and post().status_code == 200
    r = post()
    assert r.status_code == 429 and "Too many requests" in r.json()["error"]
    assert guards.TRIGGERS["rate_limit_claims"] == 1


def test_general_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_requests_per_min", 3)
    codes = [client.get("/api/vocab").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert TestClient(app).get("/healthz").status_code == 200  # healthz is never rate limited


def test_login_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_login_per_min", 2)
    c = TestClient(app)
    codes = [c.post("/login", data={"code": "wrong-wrong-wrong"}, follow_redirects=False).status_code for _ in range(3)]
    assert codes == [401, 401, 429]


def test_rate_limit_is_per_client_ip_behind_proxy(monkeypatch):
    stub(monkeypatch)
    monkeypatch.setattr(settings, "trust_proxy_hops", 1)
    monkeypatch.setattr(settings, "rate_limit_claims_per_min", 1)
    a, b = {"X-Forwarded-For": "1.1.1.1"}, {"X-Forwarded-For": "2.2.2.2"}
    assert post(headers=a).status_code == 200 and post(headers=b).status_code == 200
    assert post(headers=a).status_code == 429


def test_daily_call_cap_fails_closed_with_message(monkeypatch):
    calls = stub(monkeypatch)
    monkeypatch.setattr(settings, "daily_call_cap", 2)
    assert post(textured_jpeg((800, 600))).status_code == 200
    assert post(textured_jpeg((801, 600))).status_code == 200
    r = post(textured_jpeg((802, 600)))
    assert r.status_code == 429 and "daily usage limit" in r.json()["error"] and r.json()["status"] == "refused"
    assert len(calls) == 2  # the third request never reached the model
    assert store.usage_today()["calls"] == 2 and guards.TRIGGERS["daily_cap"] == 1


def test_daily_spend_cap(monkeypatch):
    stub(monkeypatch, cost_usd=0.03)
    monkeypatch.setattr(settings, "daily_spend_cap_usd", 0.05)
    assert post(textured_jpeg((800, 600))).status_code == 200
    assert post(textured_jpeg((801, 600))).status_code == 200  # spend 0.03 < 0.05 when checked
    r = post(textured_jpeg((802, 600)))
    assert r.status_code == 429 and store.usage_today()["spend_usd"] >= 0.05


def test_caps_persist_across_restart_in_the_db(monkeypatch):
    stub(monkeypatch)
    post()
    guards.LIMITER.reset()  # in-memory state gone, as after a restart
    assert store.usage_today()["calls"] == 1


def test_ledger_error_fails_closed(monkeypatch):
    calls = stub(monkeypatch)

    def broken(*a):
        raise OSError("disk gone")

    monkeypatch.setattr(store, "reserve_call", broken)
    r = post()
    assert r.status_code == 503 and "could not be checked" in r.json()["error"] and calls == []


def test_concurrency_cap(monkeypatch):
    stub(monkeypatch)
    monkeypatch.setattr(settings, "max_concurrent_claims", 1)
    guards.CONCURRENCY.active = 1  # one claim already running
    r = post()
    assert r.status_code == 503 and "busy" in r.json()["error"]
    guards.CONCURRENCY.active = 0
    assert post().status_code == 200 and guards.CONCURRENCY.active == 0  # released after the request


def test_identical_images_hit_the_cache_without_a_model_call_or_spend(monkeypatch):
    calls = stub(monkeypatch)
    img = textured_jpeg((900, 700))
    first, second = post(img).json(), post(img).json()
    assert len(calls) == 1
    assert second["usage"]["cached"] is True and second["usage"]["cost_usd"] == 0
    assert second["audit"]["request_id"] != first["audit"]["request_id"]  # every request still gets its own id
    assert second["damage"] == first["damage"] and store.usage_today()["calls"] == 1


def test_cache_key_changes_with_model_or_prompt(monkeypatch):
    k = pipeline._cache_key(["abc"], "claude-sonnet-5-5", "medium")
    assert k != pipeline._cache_key(["abc"], "claude-opus-5-5", "medium")
    monkeypatch.setattr(pipeline, "PROMPT_VERSION", "extract_v9")
    assert k != pipeline._cache_key(["abc"], "claude-sonnet-5-5", "medium")


def test_scripts_do_not_use_the_cache_by_default(monkeypatch):
    calls = stub(monkeypatch)
    img = textured_jpeg((910, 700))
    pipeline.run_claim([img])
    pipeline.run_claim([img])
    assert len(calls) == 2  # eval repeatability runs must reach the model every time


def test_idempotency_key_replays_the_same_result(monkeypatch):
    calls = stub(monkeypatch)
    h = {"Idempotency-Key": "claim-123"}
    a = post(textured_jpeg((920, 700)), headers=h).json()
    b = post(textured_jpeg((921, 700)), headers=h).json()
    assert a["audit"]["request_id"] == b["audit"]["request_id"] and len(calls) == 1


def test_deadline_stops_retries_and_routes_to_human(monkeypatch):
    monkeypatch.setattr(settings, "claim_deadline_s", 0.0)
    r = pipeline.run_claim([textured_jpeg()])
    assert r.status == "error" and "too long" in r.error and r.routing.outcome == "adjuster_review"


def test_slow_model_attempt_gets_capped_timeout(monkeypatch):
    seen = {}

    class Slow:
        def __init__(self):
            self.messages = self

        def with_options(self, **kw):
            seen.update(kw)
            return self

        def create(self, **kw):
            import httpx2

            raise llm.anthropic.APITimeoutError(request=httpx2.Request("POST", "https://api.example"))

    import pytest

    with pytest.raises(llm.LLMError, match="too long"):
        llm.call_model([b"x"], client=Slow(), deadline=time.monotonic() + 10)
    assert seen["timeout"] <= 10  # each attempt's timeout is capped by the time left


def test_limit_trigger_is_logged(monkeypatch, capsys):
    from app.logs import setup_logging

    setup_logging()
    stub(monkeypatch)
    monkeypatch.setattr(settings, "daily_call_cap", 0)
    post()
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert any(e["event"] == "limit_triggered" and e["kind"] == "daily_cap" and e["level"] == "WARNING" for e in lines)
    logging.getLogger("claims").handlers = []


def test_metrics_summary(monkeypatch):
    stub(monkeypatch)
    post(textured_jpeg((930, 700)))
    post(textured_jpeg((930, 700)))  # cache hit
    m = client.get("/metrics").json()
    assert m["claims_total"] == 2 and m["cache_hits"] == 1 and m["by_status"] == {"ok": 2}
    assert m["latency_ms"]["n"] == 2 and m["usage_today"]["calls"] == 1 and "by_routing" in m
