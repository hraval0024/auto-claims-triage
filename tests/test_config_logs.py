"""Fail-fast config, DATA_DIR, /healthz DB check, and secret-free logs."""

import base64
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, pipeline, ssrf
from app.config import check_config, settings
from app.llm import UsageTally
from app.logs import setup_logging
from app.main import app
from app.schemas import ModelOutput
from tests.helpers import ACCESS_CODE, API_KEY, AUTH, model_output_dict, textured_jpeg

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("field,value,msg", [
    ("anthropic_api_key", "", "ANTHROPIC_API_KEY is not set"),
    ("app_access_code", "", "APP_ACCESS_CODE is not set"),
    ("app_access_code", "short", "at least 12 characters"),
])
def test_check_config_fails_fast_with_clear_message(monkeypatch, field, value, msg):
    monkeypatch.setattr(settings, field, value)
    with pytest.raises(RuntimeError, match=msg) as e:
        check_config()
    assert API_KEY not in str(e.value) and ACCESS_CODE not in str(e.value)


def test_check_config_rejects_unwritable_data_dir(monkeypatch, tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    monkeypatch.setattr(settings, "data_dir", str(ro / "sub"))
    try:
        with pytest.raises(RuntimeError, match="DATA_DIR"):
            check_config()
    finally:
        ro.chmod(0o700)


def test_real_server_refuses_to_start_without_secrets(tmp_path):
    """Start uvicorn for real with the secrets blanked (env overrides .env): it must exit with the message."""
    env = os.environ | {"ANTHROPIC_API_KEY": "", "APP_ACCESS_CODE": "", "DATA_DIR": str(tmp_path)}
    p = subprocess.run([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "0"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=60)
    out = p.stdout + p.stderr
    assert p.returncode != 0
    assert "ANTHROPIC_API_KEY is not set" in out and "APP_ACCESS_CODE is not set" in out


def test_data_dir_controls_db_location(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "custom"))
    assert TestClient(app).get("/healthz").status_code == 200
    assert (tmp_path / "custom" / "app.db").exists()


def test_healthz_reports_unwritable_db(monkeypatch):
    def broken():
        raise OSError("read-only")

    monkeypatch.setattr("app.main.store.health_check", broken)
    r = TestClient(app).get("/healthz")
    assert r.status_code == 503 and r.json() == {"status": "error", "db": "not writable"}


def test_healthz_never_calls_the_model(monkeypatch):
    monkeypatch.setattr(pipeline, "call_model", lambda *a, **k: pytest.fail("model called"))
    assert TestClient(app).get("/healthz").status_code == 200


def test_logs_contain_no_images_keys_codes_or_url_paths(monkeypatch, capsys):
    setup_logging()
    img = textured_jpeg()

    def fake(images, **kw):
        return ModelOutput.model_validate(model_output_dict()), UsageTally("claude-sonnet-5-5", 1000, 0, 0, 100, 1)

    monkeypatch.setattr(pipeline, "call_model", fake)
    monkeypatch.setattr(ssrf, "fetch_image", lambda u, **k: img)
    monkeypatch.setattr("app.main.fetch_image", lambda u, **k: img)
    c = TestClient(app, headers=AUTH)
    c.post("/api/claims", files=[("files", ("a.jpg", img, "image/jpeg"))])
    c.post("/api/claims", data={"urls": "https://cdn.example.com/private/photo.jpg?token=SECRETTOKEN123"})
    c.post("/login", data={"code": ACCESS_CODE})
    c.post("/login", data={"code": "wrong-but-long-guess"})
    from app.logs import log_event
    log_event("test_scrub", note=f"key {API_KEY} code {ACCESS_CODE} img {base64.b64encode(img).decode()[:200]}")
    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    assert lines and all("event" in e and "ts" in e for e in lines)
    assert any(e["event"] == "claim_done" and e.get("request_id") for e in lines)
    for bad in (API_KEY, ACCESS_CODE, "wrong-but-long-guess", "SECRETTOKEN123", "/private/photo.jpg", base64.b64encode(img).decode()[:40], "/9j/4"):
        assert bad not in out, bad
    assert "[REDACTED]" in out and "[IMAGE-DATA-REDACTED]" in out  # the scrubber caught the planted values
    assert "https://cdn.example.com/..." in out  # URLs are logged as scheme + host only
    logging.getLogger("claims").handlers = []


def test_uploaded_images_are_not_written_to_disk(monkeypatch, tmp_path):
    def fake(images, **kw):
        return ModelOutput.model_validate(model_output_dict()), UsageTally("claude-sonnet-5-5", 1000, 0, 0, 100, 1)

    monkeypatch.setattr(pipeline, "call_model", fake)
    img = textured_jpeg((777, 555))
    TestClient(app, headers=AUTH).post("/api/claims", files=[("files", ("a.jpg", img, "image/jpeg"))])
    for f in Path(settings.data_dir).rglob("*"):
        if f.is_file():
            data = f.read_bytes()
            assert img[:200] not in data and b"\xff\xd8\xff" not in data, f
