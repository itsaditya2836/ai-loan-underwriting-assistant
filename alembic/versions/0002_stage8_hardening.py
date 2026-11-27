"""Stage 8 hardening migration: token_version and append-only SQLite audit triggers.

Revision ID: 0002_stage8_hardening
Revises: 0001_stage7_initial
Create Date: 2026-11-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0002_stage8_hardening"
down_revision: Union[str, Sequence[str], None] = "0001_stage7_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add users.token_version idempotently and install append-only SQLite triggers."""
    bind = op.get_bind()
    if op.get_context().as_sql:
        # Offline SQL generation: 0001 creates latest schema including token_version
        return

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" in tables:
        cols = {c["name"] for c in inspector.get_columns("users")}
        if "token_version" not in cols:
            op.add_column(
                "users",
                sa.Column(
                    "token_version",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                ),
            )

    if bind.dialect.name == "sqlite":
        if "underwriting_runs" in tables:
            op.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_underwriting_runs_no_update
                BEFORE UPDATE ON underwriting_runs
                BEGIN
                    SELECT RAISE(ABORT, 'Audit table underwriting_runs is append-only; UPDATE is prohibited.');
                END;
                """)
            op.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_underwriting_runs_no_delete
                BEFORE DELETE ON underwriting_runs
                BEGIN
                    SELECT RAISE(ABORT, 'Audit table underwriting_runs is append-only; DELETE is prohibited.');
                END;
                """)
        if "human_review_events" in tables:
            op.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_human_reviews_no_update
                BEFORE UPDATE ON human_review_events
                BEGIN
                    SELECT RAISE(ABORT, 'Audit table human_review_events is append-only; UPDATE is prohibited.');
                END;
                """)
            op.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_human_reviews_no_delete
                BEFORE DELETE ON human_review_events
                BEGIN
                    SELECT RAISE(ABORT, 'Audit table human_review_events is append-only; DELETE is prohibited.');
                END;
                """)


def downgrade() -> None:
    """Drop Stage 8 triggers while preserving historical data and columns."""
    bind = op.get_bind()
    if op.get_context().as_sql:
        return
    if bind.dialect.name == "sqlite":
        for trg in (
            "trg_underwriting_runs_no_update",
            "trg_underwriting_runs_no_delete",
            "trg_human_reviews_no_update",
            "trg_human_reviews_no_delete",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trg};")
