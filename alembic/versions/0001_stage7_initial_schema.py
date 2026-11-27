"""Stage 7 idempotent schema initialization and additive column migrations.

Revision ID: 0001_stage7_initial
Revises:
Create Date: 2026-11-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from app.auth.models import auth_metadata
from app.database.schema import app_metadata

revision: str = "0001_stage7_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ensure_column(table_name: str, column: sa.Column) -> None:
    """Add column cleanly if it is absent from an existing pre-Stage-7 table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
    if column.name not in existing_cols:
        op.add_column(table_name, column)


def upgrade() -> None:
    """Create missing Stage 7 auth/application tables and apply non-destructive additive columns."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # Create auth tables cleanly if absent
    auth_metadata.create_all(bind, checkfirst=True)

    # Create core underwriting tables cleanly if absent
    app_metadata.create_all(bind, checkfirst=True)

    # Non-destructive additive attribution columns on existing SQLite/PG tables
    if "submitted_applications" in existing_tables:
        _ensure_column(
            "submitted_applications",
            sa.Column("submitted_by_user_id", sa.String(64), nullable=True),
        )
        _ensure_column(
            "submitted_applications",
            sa.Column("submitted_by_username", sa.String(64), nullable=True),
        )
        _ensure_column(
            "submitted_applications",
            sa.Column("submitted_by_role", sa.String(32), nullable=True),
        )

    if "underwriting_runs" in existing_tables:
        _ensure_column(
            "underwriting_runs",
            sa.Column("initiated_by_user_id", sa.String(64), nullable=True),
        )
        _ensure_column(
            "underwriting_runs",
            sa.Column("initiated_by_username", sa.String(64), nullable=True),
        )
        _ensure_column(
            "underwriting_runs",
            sa.Column("initiated_by_role", sa.String(32), nullable=True),
        )

    if "human_review_events" in existing_tables:
        _ensure_column(
            "human_review_events",
            sa.Column("reviewer_user_id", sa.String(64), nullable=True),
        )
        _ensure_column(
            "human_review_events",
            sa.Column("reviewer_username", sa.String(64), nullable=True),
        )
        _ensure_column(
            "human_review_events",
            sa.Column("reviewer_role", sa.String(32), nullable=True),
        )


def downgrade() -> None:
    """Downgrade only removes newly created Stage 7 auth tables; historical records remain safe."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for tbl in ("login_attempts", "refresh_tokens", "users"):
        if tbl in existing:
            op.drop_table(tbl)
