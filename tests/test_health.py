from fastapi.testclient import TestClient

from app.main import app
from tests.helpers import AUTH


def test_healthz_open_and_checks_db():
    r = TestClient(app).get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok", "db": "writable"}


def test_health_detail_requires_code_and_reports_versions():
    assert TestClient(app).get("/health").status_code == 401
    body = TestClient(app, headers=AUTH).get("/health").json()
    for key in ("model_id", "prompt_version", "schema_version", "cost_table_version"):
        assert key in body
