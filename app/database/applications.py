"""Application Intake Persistence Module for Submitted Loan Applications.

Provides isolated SQLite storage for user-submitted applications created via
the Streamlit UI without mutating the read-only synthetic reference dataset.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.database.db import get_database_connection
from app.schemas.applicant import Applicant
from app.utils.helpers import get_logger

logger = get_logger(__name__)


def init_applications_table() -> None:
    """Create the submitted_applications table and indexes if absent."""
    create_sql = """
    CREATE TABLE IF NOT EXISTS submitted_applications (
        applicant_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        employment_type TEXT NOT NULL,
        loan_amount REAL NOT NULL,
        loan_tenure INTEGER NOT NULL,
        credit_score INTEGER NOT NULL,
        monthly_income REAL NOT NULL,
        application_status TEXT NOT NULL DEFAULT 'SUBMITTED',
        submission_hash TEXT NOT NULL,
        latest_run_id TEXT,
        applicant_json TEXT NOT NULL,
        uploaded_files_json TEXT NOT NULL DEFAULT '[]',
        validation_warnings_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """
    idx_updated_sql = """
    CREATE INDEX IF NOT EXISTS idx_submitted_apps_updated
    ON submitted_applications (updated_at DESC);
    """
    idx_hash_sql = """
    CREATE INDEX IF NOT EXISTS idx_submitted_apps_hash
    ON submitted_applications (submission_hash);
    """
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(create_sql)
        cursor.execute(idx_updated_sql)
        cursor.execute(idx_hash_sql)


def _row_to_application_dict(row: Any) -> Dict[str, Any]:
    """Decode an sqlite3.Row from submitted_applications into a clean dict."""
    d = dict(row)
    try:
        profile = json.loads(d.get("applicant_json") or "{}")
    except Exception:
        profile = {}
    try:
        uploads = json.loads(d.get("uploaded_files_json") or "[]")
    except Exception:
        uploads = []
    try:
        warnings = json.loads(d.get("validation_warnings_json") or "[]")
    except Exception:
        warnings = []

    merged = dict(profile)
    merged.update(
        {
            "applicant_id": d["applicant_id"],
            "name": d["name"],
            "employment_type": d["employment_type"],
            "loan_amount": d["loan_amount"],
            "loan_tenure": d["loan_tenure"],
            "credit_score": d["credit_score"],
            "monthly_income": d["monthly_income"],
            "application_status": d["application_status"],
            "submission_hash": d["submission_hash"],
            "latest_run_id": d.get("latest_run_id"),
            "uploaded_files": uploads,
            "validation_warnings": warnings,
            "created_at": d["created_at"],
            "updated_at": d["updated_at"],
            "source": "submitted",
        }
    )
    return merged


def save_submitted_application(
    applicant: Applicant,
    uploaded_files_meta: Optional[List[Dict[str, Any]]] = None,
    submission_hash: str = "",
    application_status: str = "SUBMITTED",
    latest_run_id: Optional[str] = None,
    validation_warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Insert or update a persisted applicant submission record."""
    init_applications_table()
    now_utc = datetime.now(timezone.utc).isoformat()
    existing = get_submitted_application(applicant.applicant_id)
    created_at = existing["created_at"] if existing else now_utc

    applicant_payload = json.dumps(applicant.model_dump(), sort_keys=True)
    uploads_payload = json.dumps(uploaded_files_meta or [], sort_keys=True)
    warnings_payload = json.dumps(validation_warnings or [], sort_keys=True)

    upsert_sql = """
    INSERT INTO submitted_applications (
        applicant_id,
        name,
        employment_type,
        loan_amount,
        loan_tenure,
        credit_score,
        monthly_income,
        application_status,
        submission_hash,
        latest_run_id,
        applicant_json,
        uploaded_files_json,
        validation_warnings_json,
        created_at,
        updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(applicant_id) DO UPDATE SET
        name = excluded.name,
        employment_type = excluded.employment_type,
        loan_amount = excluded.loan_amount,
        loan_tenure = excluded.loan_tenure,
        credit_score = excluded.credit_score,
        monthly_income = excluded.monthly_income,
        application_status = excluded.application_status,
        submission_hash = excluded.submission_hash,
        latest_run_id = COALESCE(excluded.latest_run_id, submitted_applications.latest_run_id),
        applicant_json = excluded.applicant_json,
        uploaded_files_json = excluded.uploaded_files_json,
        validation_warnings_json = excluded.validation_warnings_json,
        updated_at = excluded.updated_at;
    """
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            upsert_sql,
            (
                applicant.applicant_id,
                applicant.name,
                str(applicant.employment_type),
                float(applicant.loan_amount),
                int(applicant.loan_tenure),
                int(applicant.credit_score),
                float(applicant.monthly_income),
                application_status,
                submission_hash,
                latest_run_id,
                applicant_payload,
                uploads_payload,
                warnings_payload,
                created_at,
                now_utc,
            ),
        )

    logger.info(
        "Persisted submitted application '%s' (status=%s).",
        applicant.applicant_id,
        application_status,
    )
    saved = get_submitted_application(applicant.applicant_id)
    assert saved is not None
    return saved


def get_submitted_application(applicant_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single submitted application record by applicant_id."""
    init_applications_table()
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM submitted_applications WHERE applicant_id = ?;",
            (applicant_id,),
        )
        row = cursor.fetchone()
        return _row_to_application_dict(row) if row else None


def list_submitted_applications(limit: int = 500) -> List[Dict[str, Any]]:
    """List submitted application records ordered by most recently updated."""
    init_applications_table()
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM submitted_applications ORDER BY updated_at DESC LIMIT ?;",
            (limit,),
        )
        return [_row_to_application_dict(r) for r in cursor.fetchall()]


def find_duplicate_submission(submission_hash: str) -> Optional[Dict[str, Any]]:
    """Return an existing application matching the given exact submission fingerprint."""
    if not submission_hash:
        return None
    init_applications_table()
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM submitted_applications WHERE submission_hash = ? LIMIT 1;",
            (submission_hash,),
        )
        row = cursor.fetchone()
        return _row_to_application_dict(row) if row else None


def count_submitted_applications() -> int:
    """Count total unique submitted application records in SQLite."""
    init_applications_table()
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM submitted_applications;")
        return int(cursor.fetchone()[0])


__all__ = [
    "count_submitted_applications",
    "find_duplicate_submission",
    "get_submitted_application",
    "init_applications_table",
    "list_submitted_applications",
    "save_submitted_application",
]
