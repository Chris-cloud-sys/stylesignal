"""One-off migration: add `comments.image_key` — SPEC+ (docs/spec-
deviations.md). No Alembic in this project (see app/db.py) — same direct-
ALTER-TABLE pattern as every other production schema change so far.

    STYLESIGNAL_DATABASE_URL=<production URL> python scripts/migrate_comment_image_column.py

Safe to run more than once — the ADD COLUMN is IF NOT EXISTS.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402


def main() -> int:
    with engine.begin() as conn:
        print("Adding comments.image_key column...")
        conn.execute(text("ALTER TABLE comments ADD COLUMN IF NOT EXISTS image_key TEXT"))
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
