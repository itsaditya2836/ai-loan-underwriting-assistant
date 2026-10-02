"""Audit Trail Persistence and Query Module for Underwriting Analyses.

Provides immutable persistence, structured audit retrieval, historical tracking,
and analytics aggregation for Stage 9.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.database.db import get_database_connection
from app.schemas.decision import DecisionReasoningResult
from app.schemas.underwriting import UnderwritingAnalysisResult
from app.utils.helpers import get_logger

logger = get_logger(__name__)


def init_audit_table() -> None:
    """Initialize the underwriting_runs audit table and necessary indexes."""
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
        summary_narrative TEXT NOT NULL
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
    """Record an immutable underwriting analysis run into the audit trail.

    Args:
        analysis: Output from Stage 7 Multi-Agent Orchestrator.
        decision: Output from Stage 8 Decision & Reasoning Agent.
        execution_time_ms: Wall-clock execution latency.
        run_id: Optional custom run identifier. If None, a unique ID is generated.

    Returns:
        The unique run_id recorded.
    """
    init_audit_table()

    app_id = analysis.application_id or decision.application_id
    now_utc = datetime.now(timezone.utc).isoformat()

    if not run_id:
        short_id = uuid.uuid4().hex[:8]
        timestamp_slug = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run_id = f"RUN-{app_id}-{timestamp_slug}-{short_id}"

    # Extract metrics safely
    elig_status = (
        analysis.eligibility_result.status.value
        if analysis.eligibility_result
        else "UNKNOWN"
    )
    risk_cat = (
        analysis.risk_result.risk_category.value if analysis.risk_result else "UNKNOWN"
    )
    risk_score = analysis.risk_result.risk_score if analysis.risk_result else 0.0
    anom_sev = (
        analysis.anomaly_result.severity.value if analysis.anomaly_result else "NONE"
    )
    anom_score = (
        analysis.anomaly_result.anomaly_score if analysis.anomaly_result else 0.0
    )

    docs_found = (
        len(analysis.document_result.documents_found) if analysis.document_result else 0
    )
    docs_missing = (
        len(analysis.document_result.documents_missing)
        if analysis.document_result
        else 0
    )

    reasons_data = [r.model_dump() for r in decision.reasons]
    pos_factors = decision.positive_factors
    neg_factors = decision.negative_factors
    block_factors = decision.blocking_factors
    evidence_data = decision.supporting_evidence

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
        summary_narrative
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                decision.confidence,
                elig_status,
                risk_cat,
                risk_score,
                anom_sev,
                anom_score,
                docs_found,
                docs_missing,
                1 if decision.human_review_required else 0,
                analysis.orchestration_status.value,
                execution_time_ms,
                json.dumps(reasons_data),
                json.dumps(pos_factors),
                json.dumps(neg_factors),
                json.dumps(block_factors),
                json.dumps(evidence_data),
                decision.summary,
            ),
        )
        logger.info(
            "Persisted immutable audit record '%s' for application '%s'.",
            run_id,
            app_id,
        )

    return run_id


def get_audit_runs(
    application_id: Optional[str] = None,
    recommendation: Optional[str] = None,
    pipeline_status: Optional[str] = None,
    risk_category: Optional[str] = None,
    anomaly_severity: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Retrieve filtered historical underwriting runs from the audit database.

    Args:
        application_id: Optional filter for applicant ID.
        recommendation: Optional filter for APPROVE, REJECT, MANUAL_REVIEW.
        pipeline_status: Optional filter for SUCCESS, PARTIAL_SUCCESS, FAILED.
        risk_category: Optional filter for LOW, MEDIUM, HIGH, BORDERLINE.
        anomaly_severity: Optional filter for NONE, LOW, MEDIUM, HIGH.
        limit: Maximum number of rows to return (default: 200).

    Returns:
        List of audit record dictionaries ordered by timestamp DESC.
    """
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
    """Calculate aggregate statistics and distributions from all audit runs.

    Returns:
        Dictionary containing counts, distributions, and review rates.
    """
    init_audit_table()

    with get_database_connection() as conn:
        cursor = conn.cursor()

        # Total runs & unique applicants
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
                "manual_review_rate": 0.0,
                "avg_confidence": 0.0,
                "avg_latency_ms": 0.0,
            }

        # Recommendations
        cursor.execute(
            "SELECT recommendation, COUNT(*) FROM underwriting_runs GROUP BY recommendation;"
        )
        rec_dist = {r[0]: r[1] for r in cursor.fetchall()}
        for k in ["APPROVE", "REJECT", "MANUAL_REVIEW"]:
            rec_dist.setdefault(k, 0)

        # Risk categories
        cursor.execute(
            "SELECT risk_category, COUNT(*) FROM underwriting_runs GROUP BY risk_category;"
        )
        risk_dist = {r[0]: r[1] for r in cursor.fetchall()}
        for k in ["LOW", "MEDIUM", "HIGH", "BORDERLINE"]:
            risk_dist.setdefault(k, 0)

        # Anomaly severities
        cursor.execute(
            "SELECT anomaly_severity, COUNT(*) FROM underwriting_runs GROUP BY anomaly_severity;"
        )
        anom_dist = {r[0]: r[1] for r in cursor.fetchall()}
        for k in ["NONE", "LOW", "MEDIUM", "HIGH"]:
            anom_dist.setdefault(k, 0)

        # Eligibility statuses
        cursor.execute(
            "SELECT eligibility_status, COUNT(*) FROM underwriting_runs GROUP BY eligibility_status;"
        )
        elig_dist = {r[0]: r[1] for r in cursor.fetchall()}
        for k in ["ELIGIBLE", "INELIGIBLE", "REVIEW_REQUIRED"]:
            elig_dist.setdefault(k, 0)

        # Averages
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
            "manual_review_rate": round(manual_review_rate, 1),
            "avg_confidence": round(avg_conf or 0.0, 1),
            "avg_latency_ms": round(avg_lat or 0.0, 1),
        }


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert an sqlite3.Row to a clean dictionary with parsed JSON fields."""
    d = dict(row)
    for json_col in [
        "reasons_json",
        "positive_factors_json",
        "negative_factors_json",
        "blocking_factors_json",
        "supporting_evidence_json",
    ]:
        if json_col in d and d[json_col]:
            try:
                base_name = json_col.replace("_json", "")
                d[base_name] = json.loads(d[json_col])
            except Exception:
                d[json_col.replace("_json", "")] = []
        else:
            d[json_col.replace("_json", "")] = []

    d["human_review_required"] = bool(d.get("human_review_required", 1))
    return d


__all__ = [
    "init_audit_table",
    "save_underwriting_run",
    "get_audit_runs",
    "get_audit_run_by_id",
    "get_applicant_run_history",
    "get_audit_analytics_summary",
]
