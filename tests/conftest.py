import pytest

from app import guards
from app.config import settings
from tests.helpers import ACCESS_CODE, API_KEY


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Every test: its own DATA_DIR (never touches ./data), a test key and access code, high
    limits (tests that check limits lower them), and fresh in-memory counters."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "app_access_code", ACCESS_CODE)
    monkeypatch.setattr(settings, "anthropic_api_key", API_KEY)
    for k in ("rate_limit_claims_per_min", "rate_limit_login_per_min", "rate_limit_requests_per_min"):
        monkeypatch.setattr(settings, k, 10_000)
    guards.LIMITER.reset()
    guards.TRIGGERS.clear()
    guards.CONCURRENCY.active = 0
    return tmp_path / "app.db"
