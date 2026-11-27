"""Non-Destructive Database Migration Strategy (SQLite -> PostgreSQL / Target DB).

Copies historical underwriting, review, submitted application, and auth rows
from a source database into a target SQLAlchemy database idempotently without
modifying, truncating, or deleting rows in the source database.
"""

from __future__ import annotations

from typing import Dict

from sqlalchemy import MetaData, Table, inspect, select

from app.auth.models import (
    auth_metadata,
    login_attempts_table,
    refresh_tokens_table,
    users_table,
)
from app.database.engine import create_configured_engine
from app.database.schema import (
    app_metadata,
    human_review_events_table,
    submitted_applications_table,
    underwriting_runs_table,
)
from app.utils.helpers import get_logger

logger = get_logger(__name__)


def _copy_table_rows(
    src_engine,
    src_conn,
    dst_conn,
    tbl_name: str,
    dst_table: Table,
    pk_col: str,
) -> int:
    """Copy rows from a reflected source table into target table skipping existing PKs."""
    src_reflected = Table(tbl_name, MetaData(), autoload_with=src_engine)
    dst_cols = {c.name for c in dst_table.columns}
    shared_cols = [c.name for c in src_reflected.columns if c.name in dst_cols]
    if pk_col not in shared_cols:
        return 0

    src_stmt = select(*(src_reflected.c[c] for c in shared_cols))
    src_rows = src_conn.execute(src_stmt).mappings().all()
    if not src_rows:
        return 0

    existing_pks = {
        row[0] for row in dst_conn.execute(select(dst_table.c[pk_col])).fetchall()
    }

    inserted = 0
    for row in src_rows:
        if row[pk_col] in existing_pks:
            continue
        payload = {col: row[col] for col in shared_cols}
        dst_conn.execute(dst_table.insert().values(**payload))
        inserted += 1
    return inserted


def migrate_database_data(
    source_database_url: str,
    target_database_url: str,
) -> Dict[str, int]:
    """Copy all historical and auth records from source DB to target DB idempotently.

    Order respects foreign keys (users -> refresh_tokens; underwriting_runs -> human_review_events).
    The source database is only queried (read-only) and is never mutated, even if
    it uses a pre-Stage-7 column layout.
    """
    src_engine = create_configured_engine(source_database_url)
    dst_engine = create_configured_engine(target_database_url)

    try:
        # Ensure target schema exists with explicit FKs, indexes, and constraints
        app_metadata.create_all(dst_engine, checkfirst=True)
        auth_metadata.create_all(dst_engine, checkfirst=True)

        src_tables = set(inspect(src_engine).get_table_names())
        counts: Dict[str, int] = {}

        copy_plan = (
            ("submitted_applications", submitted_applications_table, "applicant_id"),
            ("underwriting_runs", underwriting_runs_table, "run_id"),
            ("human_review_events", human_review_events_table, "review_id"),
            ("users", users_table, "user_id"),
            ("refresh_tokens", refresh_tokens_table, "token_id"),
            ("login_attempts", login_attempts_table, "attempt_id"),
        )

        with src_engine.connect() as src_conn, dst_engine.begin() as dst_conn:
            for tbl_name, tbl_obj, pk in copy_plan:
                if tbl_name not in src_tables:
                    counts[tbl_name] = 0
                    continue
                counts[tbl_name] = _copy_table_rows(
                    src_engine, src_conn, dst_conn, tbl_name, tbl_obj, pk
                )

        logger.info("Non-destructive migration completed: %s", counts)
        return counts
    finally:
        src_engine.dispose()
        dst_engine.dispose()


__all__ = ["migrate_database_data"]
