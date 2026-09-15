"""One-off migration: add the referral-bump columns to `users` (SPEC+, see
docs/spec-deviations.md). No Alembic in this project (see app/db.py) — same
direct-ALTER-TABLE pattern as every other production schema change so far.

    STYLESIGNAL_DATABASE_URL=<production URL> python scripts/migrate_referral_columns.py

Safe to run more than once — every step is guarded (IF NOT EXISTS / a
existence check before adding the constraint), so a partial prior run or a
second accidental run just does nothing on the steps already applied.

What it does, in order:
  1. Add `referral_code` (nullable at first — existing rows have none yet).
  2. Backfill a unique code for every existing NULL row, reusing the app's
     own generate_referral_code() so backfilled codes look identical to
     ones minted at registration.
  3. Make `referral_code` NOT NULL and UNIQUE, now that every row has one.
  4. Add `referred_by_id` (nullable FK to users.id — existing accounts were
     never referred by anyone, so NULL is correct for all of them).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402
from app.security import generate_referral_code  # noqa: E402


def main() -> int:
    with engine.begin() as conn:
        print("1/4 adding referral_code column (nullable)...")
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_code VARCHAR(10)"))

        print("2/4 backfilling referral_code for existing rows...")
        rows = conn.execute(
            text("SELECT id FROM users WHERE referral_code IS NULL")
        ).fetchall()
        for (user_id,) in rows:
            for _ in range(5):
                code = generate_referral_code()
                clash = conn.execute(
                    text("SELECT 1 FROM users WHERE referral_code = :code"),
                    {"code": code},
                ).first()
                if clash is None:
                    conn.execute(
                        text("UPDATE users SET referral_code = :code WHERE id = :id"),
                        {"code": code, "id": user_id},
                    )
                    break
            else:
                raise RuntimeError(f"Could not mint a unique referral_code for user {user_id}")
        print(f"    backfilled {len(rows)} row(s).")

        print("3/4 making referral_code NOT NULL + UNIQUE...")
        conn.execute(text("ALTER TABLE users ALTER COLUMN referral_code SET NOT NULL"))
        constraint_exists = conn.execute(
            text(
                "SELECT 1 FROM pg_constraint WHERE conname = 'users_referral_code_key'"
            )
        ).first()
        if constraint_exists is None:
            conn.execute(
                text("ALTER TABLE users ADD CONSTRAINT users_referral_code_key UNIQUE (referral_code)")
            )

        print("4/4 adding referred_by_id column...")
        conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by_id UUID "
                "REFERENCES users(id) ON DELETE SET NULL"
            )
        )

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
