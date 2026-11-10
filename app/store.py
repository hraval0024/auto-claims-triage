"""SQLite store (in DATA_DIR): request audit log, corrections log, daily usage ledger, model
output cache, idempotency keys.

Stores the ClaimResult JSON (no image bytes, no raw model output, no URLs) so a review can be
diffed against what the system actually returned, not what a client claims it returned. The
cache stores model output keyed by image SHA-256, never the images. One file, standard library
only. Production would use a real datastore (see HANDOFF).
"""

import json
import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    request_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    field TEXT NOT NULL,
    original TEXT,
    corrected TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    n_corrections INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_daily (
    day TEXT PRIMARY KEY,
    calls INTEGER NOT NULL DEFAULT 0,
    spend_usd REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS model_cache (
    cache_key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    output_json TEXT NOT NULL,
    usage_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency (
    idem_key TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS health (
    id INTEGER PRIMARY KEY,
    checked_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect():
    """One short-lived connection per operation: commit on success, always closed."""
    path = Path(settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        with conn:
            yield conn


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ---- daily usage ledger (caps) ----
def reserve_call(call_cap: int, spend_cap_usd: float) -> tuple[bool, dict]:
    """Atomically check today's caps and, if under both, count one model call. Fail closed:
    any database error propagates and the caller refuses the request."""
    with _lock, _connect() as c:
        c.execute("INSERT OR IGNORE INTO usage_daily (day) VALUES (?)", (_today(),))
        row = c.execute("SELECT calls, spend_usd FROM usage_daily WHERE day = ?", (_today(),)).fetchone()
        usage = {"day": _today(), "calls": row["calls"], "spend_usd": round(row["spend_usd"], 4)}
        if row["calls"] >= call_cap or row["spend_usd"] >= spend_cap_usd:
            return False, usage
        c.execute("UPDATE usage_daily SET calls = calls + 1 WHERE day = ?", (_today(),))
        usage["calls"] += 1
        return True, usage


def record_usage(extra_calls: int, spend_usd: float) -> None:
    with _lock, _connect() as c:
        c.execute("INSERT OR IGNORE INTO usage_daily (day) VALUES (?)", (_today(),))
        c.execute("UPDATE usage_daily SET calls = calls + ?, spend_usd = spend_usd + ? WHERE day = ?",
                  (extra_calls, spend_usd, _today()))


def usage_today() -> dict:
    with _lock, _connect() as c:
        row = c.execute("SELECT calls, spend_usd FROM usage_daily WHERE day = ?", (_today(),)).fetchone()
    return {"day": _today(), "calls": row["calls"] if row else 0, "spend_usd": round(row["spend_usd"], 4) if row else 0.0}


# ---- model output cache (keyed by image hashes + model + versions; no images stored) ----
def cache_get(key: str) -> tuple[str, str] | None:
    with _lock, _connect() as c:
        row = c.execute("SELECT output_json, usage_json FROM model_cache WHERE cache_key = ?", (key,)).fetchone()
    return (row["output_json"], row["usage_json"]) if row else None


def cache_put(key: str, output_json: str, usage_json: str) -> None:
    with _lock, _connect() as c:
        c.execute("INSERT OR REPLACE INTO model_cache VALUES (?, ?, ?, ?)", (key, _now(), output_json, usage_json))


# ---- idempotency ----
def idem_get(key: str) -> str | None:
    with _lock, _connect() as c:
        row = c.execute("SELECT request_id FROM idempotency WHERE idem_key = ?", (key,)).fetchone()
    return row["request_id"] if row else None


def idem_put(key: str, request_id: str) -> None:
    with _lock, _connect() as c:
        c.execute("INSERT OR IGNORE INTO idempotency VALUES (?, ?, ?)", (key, request_id, _now()))


# ---- health ----
def health_check() -> None:
    """Write and read back a row; raises if the database is not writable."""
    with _lock, _connect() as c:
        c.execute("INSERT OR REPLACE INTO health (id, checked_at) VALUES (1, ?)", (_now(),))
        c.execute("SELECT checked_at FROM health WHERE id = 1").fetchone()


def all_results() -> list[dict]:
    with _lock, _connect() as c:
        return [json.loads(r["result_json"]) for r in c.execute("SELECT result_json FROM requests").fetchall()]


def save_result(request_id: str, result_json: str) -> None:
    with _lock, _connect() as c:
        c.execute("INSERT OR REPLACE INTO requests VALUES (?, ?, ?)", (request_id, _now(), result_json))


def get_result(request_id: str) -> dict | None:
    with _lock, _connect() as c:
        row = c.execute("SELECT result_json FROM requests WHERE request_id = ?", (request_id,)).fetchone()
    return json.loads(row["result_json"]) if row else None


def log_review(request_id: str, decision: str, corrections: list[tuple[str, str, str]]) -> str:
    ts = _now()
    with _lock, _connect() as c:
        c.executemany(
            "INSERT INTO corrections (request_id, field, original, corrected, created_at) VALUES (?, ?, ?, ?, ?)",
            [(request_id, f, o, n, ts) for f, o, n in corrections],
        )
        c.execute("INSERT INTO reviews (request_id, decision, n_corrections, created_at) VALUES (?, ?, ?, ?)",
                  (request_id, decision, len(corrections), ts))
    return ts


def recent_corrections(limit: int = 100) -> list[dict]:
    with _lock, _connect() as c:
        rows = c.execute(
            "SELECT c.request_id, c.field, c.original, c.corrected, c.created_at, r.decision "
            "FROM corrections c LEFT JOIN reviews r ON r.request_id = c.request_id AND r.created_at = c.created_at "
            "ORDER BY c.id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def recent_reviews(limit: int = 100) -> list[dict]:
    with _lock, _connect() as c:
        rows = c.execute("SELECT * FROM reviews ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
