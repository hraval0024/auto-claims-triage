"""scripts/clear_review_history.py: dry run by default, backup first, only reviews + corrections."""

import sqlite3

from app import store
from scripts import clear_review_history as clr


def seed():
    store.save_result("r1", "{}")
    store.cache_put("k1", "{}", "{}")
    store.record_usage(1, 0.01)
    store.idem_put("i1", "r1")
    store.health_check()
    store.log_review("r1", "accept", [("vehicle.model", "A", "B")], notes="n")
    store.log_review("r1", "reject", [])


def table_counts(db):
    with sqlite3.connect(db) as c:
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("requests", "model_cache", "usage_daily", "idempotency", "health", "reviews", "corrections")}


def test_dry_run_without_yes_deletes_nothing(tmp_db, monkeypatch, capsys):
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    seed()
    before = table_counts(tmp_db)
    assert clr.main([]) == 1
    assert table_counts(tmp_db) == before and "Dry run" in capsys.readouterr().out
    assert not (tmp_db.parent / "backups").exists()


def test_yes_backs_up_then_clears_only_the_two_tables(tmp_db, capsys):
    seed()
    before = table_counts(tmp_db)
    assert clr.main(["--yes"]) == 0
    after = table_counts(tmp_db)
    assert after["reviews"] == 0 and after["corrections"] == 0
    assert {k: v for k, v in after.items() if k not in ("reviews", "corrections")} == \
           {k: v for k, v in before.items() if k not in ("reviews", "corrections")}
    (backup,) = (tmp_db.parent / "backups").glob("app-*.db")
    assert table_counts(backup) == before  # the backup holds everything as it was
    out = capsys.readouterr().out
    assert "Before: reviews=2 corrections=1" in out and "After:  reviews=0 corrections=0" in out and str(backup) in out


def test_refuses_in_railway_environment(tmp_db, monkeypatch, capsys):
    seed()
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    before = table_counts(tmp_db)
    assert clr.main(["--yes"]) == 2
    assert table_counts(tmp_db) == before and "Refusing" in capsys.readouterr().out


def test_refuses_database_under_slash_data(monkeypatch):
    from pathlib import Path
    assert clr.production_reason(Path("/data/app.db")) is not None
    assert clr.production_reason(Path("data/app.db")) is None  # relative local path
