"""Append-Only SQLite Persistence for Stage 6 Human Underwriter Reviews.

Maintains a strict append-only table (`human_review_events`) preserving every
review action, status transition, additional-information request, investigation
instruction, and linked decision correction without mutating prior review
records or overwriting original AI `underwriting_runs`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.database.db import get_database_connection
from app.utils.helpers import get_logger

logger = get_logger(__name__)

_REVIEW_EXTRA_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("original_pipeline_status", "TEXT NOT NULL DEFAULT 'UNKNOWN'"),
    ("additional_info_response", "TEXT"),
    ("event_type", "TEXT NOT NULL DEFAULT 'HUMAN_REVIEW_EVENT'"),
    ("reviewer_user_id", "TEXT"),
    ("reviewer_username", "TEXT"),
    ("reviewer_role", "TEXT"),
)


class ConcurrentReviewConflictError(ValueError):
    """Raised when optimistic concurrency detects another writer changed review state."""


def init_reviews_table() -> None:
    """Create human_review_events table cleanly and apply idempotent column migrations."""
    create_sql = """
    CREATE TABLE IF NOT EXISTS human_review_events (
        review_id TEXT PRIMARY KEY,
        source_run_id TEXT NOT NULL,
        application_id TEXT NOT NULL,
        applicant_id TEXT NOT NULL,
        original_ai_recommendation TEXT NOT NULL,
        original_pipeline_status TEXT NOT NULL DEFAULT 'UNKNOWN',
        action TEXT NOT NULL,
        human_decision TEXT,
        reviewer_id TEXT NOT NULL,
        reviewer_user_id TEXT,
        reviewer_username TEXT,
        reviewer_role TEXT,
        decision_reason TEXT NOT NULL,
        comments TEXT,
        additional_info_request TEXT,
        additional_info_response TEXT,
        investigation_instructions TEXT,
        previous_review_status TEXT NOT NULL,
        new_review_status TEXT NOT NULL,
        is_correction INTEGER NOT NULL DEFAULT 0,
        parent_review_id TEXT,
        correction_explanation TEXT,
        submission_hash TEXT NOT NULL,
        review_timestamp TEXT NOT NULL,
        event_type TEXT NOT NULL DEFAULT 'HUMAN_REVIEW_EVENT'
    );
    """
    idx_app_sql = """
    CREATE INDEX IF NOT EXISTS idx_reviews_app_ts
    ON human_review_events (application_id, review_timestamp DESC);
    """
    idx_run_sql = """
    CREATE INDEX IF NOT EXISTS idx_reviews_run_ts
    ON human_review_events (source_run_id, review_timestamp DESC);
    """
    idx_hash_sql = """
    CREATE INDEX IF NOT EXISTS idx_reviews_hash
    ON human_review_events (submission_hash);
    """
    idx_user_sql = """
    CREATE INDEX IF NOT EXISTS idx_reviews_user_id
    ON human_review_events (reviewer_user_id);
    """
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(create_sql)
        cursor.execute("PRAGMA table_info(human_review_events);")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col_name, col_def in _REVIEW_EXTRA_COLUMNS:
            if col_name not in existing_cols:
                cursor.execute(
                    f"ALTER TABLE human_review_events ADD COLUMN {col_name} {col_def};"
                )
        cursor.execute(idx_app_sql)
        cursor.execute(idx_run_sql)
        cursor.execute(idx_hash_sql)
        cursor.execute(idx_user_sql)


def _row_to_review_dict(row: Any) -> Dict[str, Any]:
    """Decode an sqlite3.Row from human_review_events into clean Python primitives."""
    d = dict(row)
    d["is_correction"] = bool(d.get("is_correction", 0))
    d.setdefault("event_type", "HUMAN_REVIEW_EVENT")
    return d


def insert_human_review_event(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Append a validated human review event atomically into SQLite (never UPDATEs/DELETEs)."""
    init_reviews_table()

    now_utc = datetime.now(timezone.utc).isoformat()
    app_id = str(event_data["application_id"])
    review_id = str(
        event_data.get("review_id")
        or f"REV-{app_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    )
    review_ts = str(event_data.get("review_timestamp") or now_utc)

    insert_sql = """
    INSERT INTO human_review_events (
        review_id,
        source_run_id,
        application_id,
        applicant_id,
        original_ai_recommendation,
        original_pipeline_status,
        action,
        human_decision,
        reviewer_id,
        reviewer_user_id,
        reviewer_username,
        reviewer_role,
        decision_reason,
        comments,
        additional_info_request,
        additional_info_response,
        investigation_instructions,
        previous_review_status,
        new_review_status,
        is_correction,
        parent_review_id,
        correction_explanation,
        submission_hash,
        review_timestamp,
        event_type
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """

    source_run_id = str(event_data["source_run_id"])
    expected_prev = str(event_data["previous_review_status"])

    with get_database_connection() as conn:
        cursor = conn.cursor()
        # Acquire immediate write lock in SQLite to serialize concurrent review writers
        cursor.execute("BEGIN IMMEDIATE;")
        cursor.execute(
            "SELECT new_review_status FROM human_review_events WHERE source_run_id = ? ORDER BY review_timestamp DESC, rowid DESC LIMIT 1;",
            (source_run_id,),
        )
        cur_row = cursor.fetchone()
        actual_prev = str(cur_row[0]) if cur_row is not None else "PENDING"
        if actual_prev != expected_prev:
            raise ConcurrentReviewConflictError(
                f"Concurrent review conflict on run '{source_run_id}': status moved from "
                f"'{expected_prev}' to '{actual_prev}' before commit."
            )
        cursor.execute(
            insert_sql,
            (
                review_id,
                source_run_id,
                app_id,
                str(event_data.get("applicant_id") or app_id),
                str(event_data["original_ai_recommendation"]),
                str(event_data.get("original_pipeline_status") or "UNKNOWN"),
                str(event_data["action"]),
                event_data.get("human_decision"),
                str(event_data["reviewer_id"]),
                event_data.get("reviewer_user_id"),
                event_data.get("reviewer_username"),
                event_data.get("reviewer_role"),
                str(event_data["decision_reason"]),
                event_data.get("comments"),
                event_data.get("additional_info_request"),
                event_data.get("additional_info_response"),
                event_data.get("investigation_instructions"),
                expected_prev,
                str(event_data["new_review_status"]),
                1 if event_data.get("is_correction") else 0,
                event_data.get("parent_review_id"),
                event_data.get("correction_explanation"),
                str(event_data["submission_hash"]),
                review_ts,
                str(event_data.get("event_type") or "HUMAN_REVIEW_EVENT"),
            ),
        )

    logger.info(
        "Persisted append-only human review '%s' (run='%s', %s -> %s).",
        review_id,
        event_data["source_run_id"],
        event_data["previous_review_status"],
        event_data["new_review_status"],
    )
    saved = get_human_review_by_id(review_id)
    assert saved is not None
    return saved


def get_human_review_by_id(review_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a single human review event by review_id."""
    init_reviews_table()
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM human_review_events WHERE review_id = ?;",
            (review_id,),
        )
        row = cursor.fetchone()
        return _row_to_review_dict(row) if row else None


def find_duplicate_review_submission(submission_hash: str) -> Optional[Dict[str, Any]]:
    """Return an existing review event with the exact same submission fingerprint."""
    if not submission_hash:
        return None
    init_reviews_table()
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM human_review_events WHERE submission_hash = ? ORDER BY review_timestamp DESC LIMIT 1;",
            (submission_hash,),
        )
        row = cursor.fetchone()
        return _row_to_review_dict(row) if row else None


def get_review_history_for_run(source_run_id: str) -> List[Dict[str, Any]]:
    """Return all append-only human review events for a specific underwriting run (newest first)."""
    init_reviews_table()
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM human_review_events WHERE source_run_id = ? ORDER BY review_timestamp DESC, rowid DESC;",
            (source_run_id,),
        )
        return [_row_to_review_dict(r) for r in cursor.fetchall()]


def get_latest_review_for_run(source_run_id: str) -> Optional[Dict[str, Any]]:
    """Return the latest human review event for a specific run_id, or None if never reviewed."""
    init_reviews_table()
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM human_review_events WHERE source_run_id = ? ORDER BY review_timestamp DESC, rowid DESC LIMIT 1;",
            (source_run_id,),
        )
        row = cursor.fetchone()
        return _row_to_review_dict(row) if row else None


def get_review_history_for_application(application_id: str) -> List[Dict[str, Any]]:
    """Return all append-only human review events across runs for an applicant (newest first)."""
    init_reviews_table()
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM human_review_events WHERE application_id = ? ORDER BY review_timestamp DESC, rowid DESC;",
            (application_id,),
        )
        return [_row_to_review_dict(r) for r in cursor.fetchall()]


def get_latest_review_for_application(application_id: str) -> Optional[Dict[str, Any]]:
    """Return the latest human review event for an applicant across runs."""
    init_reviews_table()
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM human_review_events WHERE application_id = ? ORDER BY review_timestamp DESC, rowid DESC LIMIT 1;",
            (application_id,),
        )
        row = cursor.fetchone()
        return _row_to_review_dict(row) if row else None


def get_human_review_events(
    application_id_prefix: Optional[str] = None,
    source_run_id: Optional[str] = None,
    reviewer_id: Optional[str] = None,
    reviewer_user_id: Optional[str] = None,
    new_review_status: Optional[str] = None,
    human_decision: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 300,
) -> List[Dict[str, Any]]:
    """Query filtered append-only human review audit events."""
    init_reviews_table()
    query = "SELECT * FROM human_review_events WHERE 1=1"
    params: List[Any] = []

    if application_id_prefix:
        query += " AND application_id LIKE ?"
        params.append(f"%{application_id_prefix}%")
    if source_run_id:
        query += " AND source_run_id = ?"
        params.append(source_run_id)
    if reviewer_id:
        query += " AND reviewer_id LIKE ?"
        params.append(f"%{reviewer_id}%")
    if reviewer_user_id:
        query += " AND reviewer_user_id = ?"
        params.append(reviewer_user_id)
    if new_review_status:
        query += " AND new_review_status = ?"
        params.append(new_review_status)
    if human_decision:
        query += " AND human_decision = ?"
        params.append(human_decision)
    if start_date:
        query += " AND substr(review_timestamp, 1, 10) >= ?"
        params.append(start_date)
    if end_date:
        query += " AND substr(review_timestamp, 1, 10) <= ?"
        params.append(end_date)

    query += " ORDER BY review_timestamp DESC, rowid DESC LIMIT ?"
    params.append(limit)

    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [_row_to_review_dict(r) for r in cursor.fetchall()]


__all__ = [
    "ConcurrentReviewConflictError",
    "find_duplicate_review_submission",
    "get_human_review_by_id",
    "get_human_review_events",
    "get_latest_review_for_application",
    "get_latest_review_for_run",
    "get_review_history_for_application",
    "get_review_history_for_run",
    "init_reviews_table",
    "insert_human_review_event",
]
