"""Audit Trail Persistence and Query Module for Underwriting Analyses.

Provides immutable persistence, schema-safe migrations, structured audit
retrieval, historical tracking, stable JSON serialization, and analytics
aggregation across Stage 4/9 runs.
"""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.database.db import get_database_connection
from app.schemas.decision import DecisionReasoningResult
from app.schemas.underwriting import UnderwritingAnalysisResult
from app.utils.helpers import get_logger

logger = get_logger(__name__)

_EXTRA_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("risk_score_available", "INTEGER NOT NULL DEFAULT 1"),
    ("review_reasons_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("agent_statuses_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("consistency_conflicts_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("validation_warnings_json", "TEXT NOT NULL DEFAULT '[]'"),
)


def _sanitize_for_json(value: Any) -> Any:
    """Recursively normalize objects into strict JSON-safe primitives."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return _sanitize_for_json(value.model_dump())
    if isinstance(value, dict):
        return {str(k): _sanitize_for_json(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_json(v) for v in value]
    return str(value)


def _stable_json_dumps(value: Any) -> str:
    """Serialize data deterministically with sorted keys and strict JSON compliance."""
    return json.dumps(
        _sanitize_for_json(value),
        sort_keys=True,
        allow_nan=False,
        default=str,
    )


def init_audit_table() -> None:
    """Initialize underwriting_runs table, migrate new columns safely, and create indexes."""
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS underwriting_runs (
        run_id TEXT PRIMARY KEY,
        application_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        pipeline_version TEXT NOT NULL,
        decision_policy_version TEXT NOT NULL,
        orchestrator_version TEXT NOT NULL,
        recommendation TEXT NOT NULL,
        decision_confidence REAL NOT NULL,
        eligibility_status TEXT NOT NULL,
        risk_category TEXT NOT NULL,
        risk_score REAL NOT NULL,
        anomaly_severity TEXT NOT NULL,
        anomaly_score REAL NOT NULL,
        documents_found_count INTEGER NOT NULL,
        documents_missing_count INTEGER NOT NULL,
        human_review_required INTEGER NOT NULL,
        pipeline_status TEXT NOT NULL,
        execution_time_ms REAL NOT NULL,
        reasons_json TEXT NOT NULL,
        positive_factors_json TEXT NOT NULL,
        negative_factors_json TEXT NOT NULL,
        blocking_factors_json TEXT NOT NULL,
        supporting_evidence_json TEXT NOT NULL,
        summary_narrative TEXT NOT NULL,
        risk_score_available INTEGER NOT NULL DEFAULT 1,
        review_reasons_json TEXT NOT NULL DEFAULT '[]',
        agent_statuses_json TEXT NOT NULL DEFAULT '{}',
        consistency_conflicts_json TEXT NOT NULL DEFAULT '[]',
        validation_warnings_json TEXT NOT NULL DEFAULT '[]'
    );
    """
    create_index_app_sql = """
    CREATE INDEX IF NOT EXISTS idx_runs_app_id ON underwriting_runs (application_id);
    """
    create_index_ts_sql = """
    CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON underwriting_runs (timestamp DESC);
    """
    create_index_rec_sql = """
    CREATE INDEX IF NOT EXISTS idx_runs_recommendation ON underwriting_runs (recommendation);
    """

    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(create_table_sql)

        cursor.execute("PRAGMA table_info(underwriting_runs);")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for col_name, col_def in _EXTRA_COLUMNS:
            if col_name not in existing_cols:
                cursor.execute(
                    f"ALTER TABLE underwriting_runs ADD COLUMN {col_name} {col_def};"
                )

        cursor.execute(create_index_app_sql)
        cursor.execute(create_index_ts_sql)
        cursor.execute(create_index_rec_sql)
        logger.info("Audit table 'underwriting_runs' initialized successfully.")


def save_underwriting_run(
    analysis: UnderwritingAnalysisResult,
    decision: DecisionReasoningResult,
    execution_time_ms: float = 0.0,
    run_id: Optional[str] = None,
) -> str:
    """Record an immutable underwriting analysis run into the SQLite audit trail."""
    init_audit_table()

    app_id = analysis.application_id or decision.application_id
    now_utc = datetime.now(timezone.utc).isoformat()

    if not run_id:
        short_id = uuid.uuid4().hex[:8]
        timestamp_slug = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run_id = f"RUN-{app_id}-{timestamp_slug}-{short_id}"

    # Distinguish unavailable/failed outputs accurately rather than synthesizing clean defaults
    elig_status = (
        analysis.eligibility_result.status.value
        if analysis.eligibility_result is not None
        else "UNAVAILABLE"
    )
    risk_cat = (
        analysis.risk_result.risk_category.value
        if analysis.risk_result is not None
        else "UNAVAILABLE"
    )
    raw_risk_score = (
        analysis.risk_result.risk_score
        if (
            analysis.risk_result is not None
            and analysis.risk_result.risk_score is not None
            and math.isfinite(float(analysis.risk_result.risk_score))
        )
        else None
    )
    risk_score_available = 1 if raw_risk_score is not None else 0
    risk_score_db = float(raw_risk_score) if raw_risk_score is not None else -1.0

    anom_sev = (
        analysis.anomaly_result.severity.value
        if analysis.anomaly_result is not None
        else "UNAVAILABLE"
    )
    anom_score = (
        float(analysis.anomaly_result.anomaly_score)
        if (
            analysis.anomaly_result is not None
            and math.isfinite(float(analysis.anomaly_result.anomaly_score))
        )
        else 0.0
    )

    docs_found = (
        len(analysis.document_result.documents_found)
        if analysis.document_result is not None
        else 0
    )
    docs_missing = (
        len(analysis.document_result.documents_missing)
        if analysis.document_result is not None
        else 0
    )

    reasons_data = [r.model_dump() for r in decision.reasons]
    pos_factors = decision.positive_factors
    neg_factors = decision.negative_factors
    block_factors = decision.blocking_factors
    evidence_data = decision.supporting_evidence
    review_reasons = decision.review_reasons or (
        [r.description for r in decision.reasons]
        if decision.recommendation.value == "MANUAL_REVIEW"
        else []
    )
    agent_statuses = decision.agent_statuses or {
        k: st.status.value for k, st in sorted(analysis.agent_statuses.items())
    }
    conflicts = decision.consistency_conflicts or analysis.consistency_conflicts
    val_warnings = decision.validation_warnings or analysis.validation_warnings

    insert_sql = """
    INSERT INTO underwriting_runs (
        run_id,
        application_id,
        timestamp,
        pipeline_version,
        decision_policy_version,
        orchestrator_version,
        recommendation,
        decision_confidence,
        eligibility_status,
        risk_category,
        risk_score,
        anomaly_severity,
        anomaly_score,
        documents_found_count,
        documents_missing_count,
        human_review_required,
        pipeline_status,
        execution_time_ms,
        reasons_json,
        positive_factors_json,
        negative_factors_json,
        blocking_factors_json,
        supporting_evidence_json,
        summary_narrative,
        risk_score_available,
        review_reasons_json,
        agent_statuses_json,
        consistency_conflicts_json,
        validation_warnings_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """

    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            insert_sql,
            (
                run_id,
                app_id,
                now_utc,
                analysis.pipeline_version,
                decision.policy_version,
                analysis.pipeline_version,
                decision.recommendation.value,
                float(decision.confidence),
                elig_status,
                risk_cat,
                risk_score_db,
                anom_sev,
                anom_score,
                docs_found,
                docs_missing,
                1 if decision.human_review_required else 0,
                analysis.orchestration_status.value,
                float(execution_time_ms),
                _stable_json_dumps(reasons_data),
                _stable_json_dumps(pos_factors),
                _stable_json_dumps(neg_factors),
                _stable_json_dumps(block_factors),
                _stable_json_dumps(evidence_data),
                decision.summary,
                risk_score_available,
                _stable_json_dumps(review_reasons),
                _stable_json_dumps(agent_statuses),
                _stable_json_dumps(conflicts),
                _stable_json_dumps(val_warnings),
            ),
        )
        logger.info(
            "Persisted immutable audit record '%s' for application '%s' (status=%s).",
            run_id,
            app_id,
            analysis.orchestration_status.value,
        )

    return run_id


def save_underwriting_run_safe(
    analysis: UnderwritingAnalysisResult,
    decision: DecisionReasoningResult,
    execution_time_ms: float = 0.0,
    run_id: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Persist audit run without masking persistence failures behind exceptions.

    Returns:
        Tuple of (run_id, None) on success or (None, error_message) on failure.
    """
    try:
        saved_id = save_underwriting_run(
            analysis=analysis,
            decision=decision,
            execution_time_ms=execution_time_ms,
            run_id=run_id,
        )
        return saved_id, None
    except Exception as exc:
        err_msg = f"Audit persistence failed: {exc}"
        logger.error(
            "Failed to persist audit record for '%s': %s",
            analysis.application_id or decision.application_id,
            err_msg,
        )
        return None, err_msg


def get_audit_runs(
    application_id: Optional[str] = None,
    recommendation: Optional[str] = None,
    pipeline_status: Optional[str] = None,
    risk_category: Optional[str] = None,
    anomaly_severity: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Retrieve filtered historical underwriting runs from the audit database."""
    init_audit_table()

    query = "SELECT * FROM underwriting_runs WHERE 1=1"
    params: List[Any] = []

    if application_id:
        query += " AND application_id = ?"
        params.append(application_id)
    if recommendation:
        query += " AND recommendation = ?"
        params.append(recommendation)
    if pipeline_status:
        query += " AND pipeline_status = ?"
        params.append(pipeline_status)
    if risk_category:
        query += " AND risk_category = ?"
        params.append(risk_category)
    if anomaly_severity:
        query += " AND anomaly_severity = ?"
        params.append(anomaly_severity)

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [_row_to_dict(r) for r in rows]


def get_audit_run_by_id(run_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve full details of a specific historical underwriting run."""
    init_audit_table()

    query = "SELECT * FROM underwriting_runs WHERE run_id = ?"
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (run_id,))
        row = cursor.fetchone()
        if row:
            return _row_to_dict(row)
    return None


def get_applicant_run_history(application_id: str) -> List[Dict[str, Any]]:
    """Retrieve all historical underwriting runs for a given application ID."""
    return get_audit_runs(application_id=application_id)


def get_audit_analytics_summary() -> Dict[str, Any]:
    """Calculate aggregate statistics and distributions from all audit runs."""
    init_audit_table()

    with get_database_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*), COUNT(DISTINCT application_id) FROM underwriting_runs;"
        )
        total_runs, unique_apps = cursor.fetchone()

        if total_runs == 0:
            return {
                "total_runs": 0,
                "unique_applications": 0,
                "recommendation_distribution": {
                    "APPROVE": 0,
                    "REJECT": 0,
                    "MANUAL_REVIEW": 0,
                },
                "risk_distribution": {
                    "LOW": 0,
                    "MEDIUM": 0,
                    "HIGH": 0,
                    "BORDERLINE": 0,
                },
                "anomaly_distribution": {"NONE": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0},
                "eligibility_distribution": {
                    "ELIGIBLE": 0,
                    "INELIGIBLE": 0,
                    "REVIEW_REQUIRED": 0,
                },
                "pipeline_status_distribution": {
                    "SUCCESS": 0,
                    "PARTIAL_SUCCESS": 0,
                    "FAILED": 0,
                },
                "failed_runs_count": 0,
                "manual_review_rate": 0.0,
                "avg_confidence": 0.0,
                "avg_latency_ms": 0.0,
            }

        cursor.execute(
            "SELECT recommendation, COUNT(*) FROM underwriting_runs GROUP BY recommendation;"
        )
        rec_dist = {r[0]: r[1] for r in cursor.fetchall()}
        for k in ["APPROVE", "REJECT", "MANUAL_REVIEW"]:
            rec_dist.setdefault(k, 0)

        cursor.execute(
            "SELECT risk_category, COUNT(*) FROM underwriting_runs GROUP BY risk_category;"
        )
        risk_dist = {r[0]: r[1] for r in cursor.fetchall()}
        for k in ["LOW", "MEDIUM", "HIGH", "BORDERLINE"]:
            risk_dist.setdefault(k, 0)

        cursor.execute(
            "SELECT anomaly_severity, COUNT(*) FROM underwriting_runs GROUP BY anomaly_severity;"
        )
        anom_dist = {r[0]: r[1] for r in cursor.fetchall()}
        for k in ["NONE", "LOW", "MEDIUM", "HIGH"]:
            anom_dist.setdefault(k, 0)

        cursor.execute(
            "SELECT eligibility_status, COUNT(*) FROM underwriting_runs GROUP BY eligibility_status;"
        )
        elig_dist = {r[0]: r[1] for r in cursor.fetchall()}
        for k in ["ELIGIBLE", "INELIGIBLE", "REVIEW_REQUIRED"]:
            elig_dist.setdefault(k, 0)

        cursor.execute(
            "SELECT pipeline_status, COUNT(*) FROM underwriting_runs GROUP BY pipeline_status;"
        )
        status_dist = {r[0]: r[1] for r in cursor.fetchall()}
        for k in ["SUCCESS", "PARTIAL_SUCCESS", "FAILED"]:
            status_dist.setdefault(k, 0)

        cursor.execute(
            "SELECT AVG(decision_confidence), AVG(execution_time_ms) FROM underwriting_runs;"
        )
        avg_conf, avg_lat = cursor.fetchone()

        manual_rev_count = rec_dist.get("MANUAL_REVIEW", 0)
        manual_review_rate = (
            (manual_rev_count / total_runs) * 100.0 if total_runs > 0 else 0.0
        )

        return {
            "total_runs": total_runs,
            "unique_applications": unique_apps,
            "recommendation_distribution": rec_dist,
            "risk_distribution": risk_dist,
            "anomaly_distribution": anom_dist,
            "eligibility_distribution": elig_dist,
            "pipeline_status_distribution": status_dist,
            "failed_runs_count": status_dist.get("FAILED", 0),
            "manual_review_rate": round(manual_review_rate, 1),
            "avg_confidence": round(avg_conf or 0.0, 1),
            "avg_latency_ms": round(avg_lat or 0.0, 1),
        }


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert an sqlite3.Row to a clean dictionary with parsed JSON fields."""
    d = dict(row)
    json_defaults = {
        "reasons_json": [],
        "positive_factors_json": [],
        "negative_factors_json": [],
        "blocking_factors_json": [],
        "supporting_evidence_json": [],
        "review_reasons_json": [],
        "agent_statuses_json": {},
        "consistency_conflicts_json": [],
        "validation_warnings_json": [],
    }
    for json_col, default_val in json_defaults.items():
        base_name = json_col.replace("_json", "")
        raw = d.get(json_col)
        if raw:
            try:
                d[base_name] = json.loads(raw)
            except Exception:
                d[base_name] = (
                    list(default_val)
                    if isinstance(default_val, list)
                    else dict(default_val)
                )
        else:
            d[base_name] = (
                list(default_val)
                if isinstance(default_val, list)
                else dict(default_val)
            )

    score_avail = bool(d.get("risk_score_available", 1))
    d["risk_score_available"] = score_avail
    if not score_avail or d.get("risk_score") == -1.0:
        d["risk_score"] = None

    d["human_review_required"] = bool(d.get("human_review_required", 1))
    return d


__all__ = [
    "get_applicant_run_history",
    "get_audit_analytics_summary",
    "get_audit_run_by_id",
    "get_audit_runs",
    "init_audit_table",
    "save_underwriting_run",
    "save_underwriting_run_safe",
]
