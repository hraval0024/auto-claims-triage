"""Clear the LOCAL review history: every row in `reviews` and `corrections`, nothing else.

Keeps requests, model_cache (cached results keep demos fast and repeatable), usage_daily,
idempotency and health untouched. Backs the database up first (sqlite backup API, consistent
even while the app is running) to <DATA_DIR>/backups/app-YYYYmmdd-HHMMSS.db; data/ is
git-ignored, so backups (which contain review notes) are never committed.

Refuses to run in production: if any RAILWAY_* environment variable is set, or the database
is under /data (the Railway volume).

Usage:
  uv run python -m scripts.clear_review_history          # dry run: shows what would be deleted
  uv run python -m scripts.clear_review_history --yes    # backup, then delete
"""

import argparse
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

from app.config import settings

TABLES = ("reviews", "corrections")


def counts(db: Path) -> dict[str, int]:
    with closing(sqlite3.connect(db)) as c:
        have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return {t: (c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] if t in have else 0) for t in TABLES}


def production_reason(db: Path) -> str | None:
    railway = sorted(k for k in os.environ if k.startswith("RAILWAY_"))
    if railway:
        return f"Railway environment detected ({', '.join(railway)})."
    if db.resolve().is_relative_to(Path("/data")):
        return f"Database {db} is under /data (the production volume)."
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="actually back up and delete (default: dry run)")
    args = ap.parse_args(argv)

    db = Path(settings.db_path)
    reason = production_reason(db)
    if reason:
        print(f"Refusing to run: {reason} This script is for the local database only.")
        return 2
    if not db.exists():
        print(f"No database at {db}; nothing to clear.")
        return 1

    before = counts(db)
    print(f"Database: {db.resolve()}")
    print(f"Before: reviews={before['reviews']} corrections={before['corrections']}")
    if not args.yes:
        print(f"Dry run: would delete {before['reviews']} review rows and {before['corrections']} correction rows "
              "(no other table). Re-run with --yes to back up and delete.")
        return 1

    backup = db.parent / "backups" / f"app-{datetime.now():%Y%m%d-%H%M%S}.db"
    backup.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as src, closing(sqlite3.connect(backup)) as dst:
        src.backup(dst)
    print(f"Backup: {backup.resolve()}")

    with closing(sqlite3.connect(db, timeout=10)) as c, c:
        for t in TABLES:
            c.execute(f"DELETE FROM {t}")  # table names are the constants above
    after = counts(db)
    print(f"After:  reviews={after['reviews']} corrections={after['corrections']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
