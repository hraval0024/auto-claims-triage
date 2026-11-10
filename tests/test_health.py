from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_200_and_versions():
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    for key in ("model_id", "prompt_version", "schema_version", "cost_table_version"):
        assert key in body
