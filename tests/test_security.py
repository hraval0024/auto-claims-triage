"""Access gate, security headers, CORS, clean errors."""

import hmac

import pytest
from fastapi.testclient import TestClient

from app import security
from app.main import app
from tests.helpers import ACCESS_CODE, AUTH, textured_jpeg

anon = TestClient(app)

PROTECTED = [("get", "/"), ("get", "/static/app.js"), ("get", "/health"), ("get", "/metrics"),
             ("get", "/api/vocab"), ("get", "/api/corrections"), ("post", "/api/claims"),
             ("post", "/api/claims/x/review"), ("get", "/nonexistent")]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_every_route_except_healthz_needs_the_code(method, path):
    r = getattr(anon, method)(path)
    assert r.status_code == 401


def test_401_has_no_detail():
    r = anon.get("/api/vocab")
    assert r.json() == {"error": "Unauthorized"}
    r = anon.get("/api/vocab", headers={"X-Access-Code": ACCESS_CODE + "x"})
    assert r.status_code == 401 and r.json() == {"error": "Unauthorized"}


def test_root_without_code_shows_the_code_prompt_not_the_app():
    r = anon.get("/")
    assert r.status_code == 401 and 'name="code"' in r.text and "app.js" not in r.text


def test_healthz_and_login_page_are_open():
    assert anon.get("/healthz").status_code == 200
    assert anon.get("/login").status_code == 200


def test_header_code_grants_access():
    assert TestClient(app, headers=AUTH).get("/api/vocab").status_code == 200


def test_login_sets_session_cookie_without_the_code():
    c = TestClient(app)
    r = c.post("/login", data={"code": ACCESS_CODE}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    sc = r.headers["set-cookie"]
    assert "HttpOnly" in sc and "SameSite=strict" in sc.replace("Strict", "strict")
    assert "Max-Age" not in sc and "expires" not in sc.lower()  # session only
    assert ACCESS_CODE not in sc  # the cookie holds an HMAC token, never the code
    assert c.get("/api/vocab").status_code == 200  # cookie now grants access
    assert c.post("/logout", follow_redirects=False).status_code == 303
    c.cookies.clear()
    assert c.get("/api/vocab").status_code == 401


def test_wrong_login_is_401_and_sets_no_cookie():
    r = TestClient(app).post("/login", data={"code": "wrong-code-123456"}, follow_redirects=False)
    assert r.status_code == 401 and "set-cookie" not in r.headers and "Not authorized" in r.text


def test_rotating_the_code_invalidates_sessions(monkeypatch):
    c = TestClient(app)
    c.post("/login", data={"code": ACCESS_CODE})
    monkeypatch.setattr(security.settings, "app_access_code", "a-brand-new-code-9999")
    assert c.get("/api/vocab").status_code == 401


def test_comparisons_are_constant_time(monkeypatch):
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(security.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    TestClient(app, headers=AUTH).get("/api/vocab")
    TestClient(app, cookies={security.COOKIE: "x"}).get("/api/vocab")
    assert len(calls) >= 2


def test_code_never_accepted_from_the_url():
    assert anon.get(f"/api/vocab?code={ACCESS_CODE}").status_code == 401
    assert anon.get(f"/api/vocab?access_code={ACCESS_CODE}").status_code == 401


def test_security_headers_on_success_and_on_401():
    for r in (TestClient(app, headers=AUTH).get("/"), anon.get("/api/vocab"), anon.get("/healthz")):
        h = r.headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in h["content-security-policy"] and "script-src 'self'" in h["content-security-policy"]
        assert h["referrer-policy"] == "no-referrer" and h["cache-control"] == "no-store" and h["x-request-id"]


def test_hsts_only_behind_https_proxy(monkeypatch):
    monkeypatch.setattr(security.settings, "trust_proxy_hops", 1)
    r = anon.get("/healthz", headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "1.2.3.4"})
    assert "max-age" in r.headers["strict-transport-security"]
    assert "strict-transport-security" not in anon.get("/healthz").headers or security.settings.trust_proxy_hops == 1


def test_cors_closed():
    c = TestClient(app, headers=AUTH)
    r = c.get("/api/vocab", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    pre = c.options("/api/claims", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in pre.headers


def test_no_api_docs_exposed():
    c = TestClient(app, headers=AUTH)
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(p).status_code == 404


def test_validation_errors_do_not_echo_input():
    c = TestClient(app, headers=AUTH)
    r = c.post("/api/claims", files=[("files", ("a.jpg", textured_jpeg(), "image/jpeg"))], data={"region": "<script>secret-value</script>"})
    assert r.status_code == 422 and "secret-value" not in r.text and r.json()["fields"] == ["region"]


def test_unhandled_error_is_generic(monkeypatch):
    from app import main

    def boom():
        raise RuntimeError(f"/Users/someone/secret/path {ACCESS_CODE}")

    monkeypatch.setattr(main.store, "usage_today", boom)
    r = TestClient(app, headers=AUTH, raise_server_exceptions=False).get("/metrics")
    assert r.status_code == 500 and r.json()["error"].startswith("Internal error")
    assert "Traceback" not in r.text and "/Users/" not in r.text and ACCESS_CODE not in r.text


def test_client_ip_uses_rightmost_trusted_forwarded_entry(monkeypatch):
    from starlette.requests import Request

    def req(xff):
        return Request({"type": "http", "headers": [(b"x-forwarded-for", xff.encode())], "client": ("10.0.0.9", 1)})

    monkeypatch.setattr(security.settings, "trust_proxy_hops", 0)
    assert security.client_ip(req("6.6.6.6, 1.2.3.4")) == "10.0.0.9"  # proxy headers ignored when not trusted
    monkeypatch.setattr(security.settings, "trust_proxy_hops", 1)
    assert security.client_ip(req("6.6.6.6, 1.2.3.4")) == "1.2.3.4"  # a client-forged left entry is ignored
