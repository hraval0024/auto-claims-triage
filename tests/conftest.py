import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Every test gets its own SQLite file; tests never touch data/app.db."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(settings, "db_path", str(path))
    return path
