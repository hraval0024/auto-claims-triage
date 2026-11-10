"""SQLite store for the request audit log and the adjuster corrections log.

Stores the ClaimResult JSON (no image bytes, no raw model output, no URLs) so a review can be
diffed against what the system actually returned, not what a client claims it returned.
One file, standard library only. Production would use a real datastore (see HANDOFF).
"""

import json
import sqlite3
import threading
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
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    path = Path(settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


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
