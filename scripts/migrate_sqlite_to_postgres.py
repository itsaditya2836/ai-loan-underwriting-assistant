"""CLI Utility for Non-Destructive SQLite-to-PostgreSQL Data Migration.

Usage:
    python scripts/migrate_sqlite_to_postgres.py \
        --source sqlite:///./loan_underwriting.db \
        --target postgresql+psycopg://user:pass@localhost:5432/underwriting
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.migration import migrate_database_data


def main() -> int:
    """Run idempotent migration from source DATABASE_URL to target DATABASE_URL."""
    parser = argparse.ArgumentParser(
        description="Non-destructively migrate underwriting & audit records between databases."
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Source SQLAlchemy DATABASE_URL (read-only; never mutated).",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Target SQLAlchemy DATABASE_URL (e.g., postgresql+psycopg://...).",
    )
    args = parser.parse_args()

    counts = migrate_database_data(args.source, args.target)
    print("Migration complete (rows copied):")
    for table_name, inserted in counts.items():
        print(f"  - {table_name}: {inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
