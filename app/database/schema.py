"""Authoritative SQLAlchemy Core Table Definitions for Underwriting Persistence.

Provides dialect-neutral DDL for both SQLite and PostgreSQL (consumed by
Alembic migrations and SQLite-to-PostgreSQL migration utilities) covering:
- submitted_applications
- underwriting_runs
- human_review_events (with ForeignKey to underwriting_runs.run_id and indexes)
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

app_metadata = MetaData()

submitted_applications_table = Table(
    "submitted_applications",
    app_metadata,
    Column("applicant_id", String(64), primary_key=True),
    Column("name", String(256), nullable=False),
    Column("employment_type", String(64), nullable=False),
    Column("loan_amount", Float, nullable=False),
    Column("loan_tenure", Integer, nullable=False),
    Column("credit_score", Integer, nullable=False),
    Column("monthly_income", Float, nullable=False),
    Column("application_status", String(64), nullable=False, default="SUBMITTED"),
    Column("submission_hash", String(128), nullable=False),
    Column("latest_run_id", String(128), nullable=True),
    Column("applicant_json", Text, nullable=False),
    Column("uploaded_files_json", Text, nullable=False, default="[]"),
    Column("validation_warnings_json", Text, nullable=False, default="[]"),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
    Column("submitted_by_user_id", String(64), nullable=True),
    Column("submitted_by_username", String(64), nullable=True),
    Column("submitted_by_role", String(32), nullable=True),
    Index("idx_submitted_apps_updated", "updated_at"),
    Index("idx_submitted_apps_hash", "submission_hash"),
    Index("idx_submitted_apps_submitter", "submitted_by_user_id"),
)

underwriting_runs_table = Table(
    "underwriting_runs",
    app_metadata,
    Column("run_id", String(128), primary_key=True),
    Column("application_id", String(64), nullable=False),
    Column("timestamp", String(64), nullable=False),
    Column("pipeline_version", String(64), nullable=False),
    Column("decision_policy_version", String(64), nullable=False),
    Column("orchestrator_version", String(64), nullable=False),
    Column("recommendation", String(64), nullable=False),
    Column("decision_confidence", Float, nullable=False),
    Column("eligibility_status", String(64), nullable=False),
    Column("risk_category", String(64), nullable=False),
    Column("risk_score", Float, nullable=False),
    Column("anomaly_severity", String(64), nullable=False),
    Column("anomaly_score", Float, nullable=False),
    Column("documents_found_count", Integer, nullable=False),
    Column("documents_missing_count", Integer, nullable=False),
    Column("human_review_required", Integer, nullable=False),
    Column("pipeline_status", String(64), nullable=False),
    Column("execution_time_ms", Float, nullable=False),
    Column("reasons_json", Text, nullable=False),
    Column("positive_factors_json", Text, nullable=False),
    Column("negative_factors_json", Text, nullable=False),
    Column("blocking_factors_json", Text, nullable=False),
    Column("supporting_evidence_json", Text, nullable=False),
    Column("summary_narrative", Text, nullable=False),
    Column("risk_score_available", Integer, nullable=False, default=1),
    Column("review_reasons_json", Text, nullable=False, default="[]"),
    Column("agent_statuses_json", Text, nullable=False, default="{}"),
    Column("consistency_conflicts_json", Text, nullable=False, default="[]"),
    Column("validation_warnings_json", Text, nullable=False, default="[]"),
    Column("details_snapshot_json", Text, nullable=False, default="{}"),
    Column("initiated_by_user_id", String(64), nullable=True),
    Column("initiated_by_username", String(64), nullable=True),
    Column("initiated_by_role", String(32), nullable=True),
    Index("idx_runs_app_id", "application_id"),
    Index("idx_runs_timestamp", "timestamp"),
    Index("idx_runs_recommendation", "recommendation"),
    Index("idx_runs_initiator", "initiated_by_user_id"),
)

human_review_events_table = Table(
    "human_review_events",
    app_metadata,
    Column("review_id", String(128), primary_key=True),
    Column(
        "source_run_id",
        String(128),
        ForeignKey("underwriting_runs.run_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("application_id", String(64), nullable=False),
    Column("applicant_id", String(64), nullable=False),
    Column("original_ai_recommendation", String(64), nullable=False),
    Column("original_pipeline_status", String(64), nullable=False, default="UNKNOWN"),
    Column("action", String(64), nullable=False),
    Column("human_decision", String(64), nullable=True),
    Column("reviewer_id", String(128), nullable=False),
    Column("reviewer_user_id", String(64), nullable=True),
    Column("reviewer_username", String(64), nullable=True),
    Column("reviewer_role", String(32), nullable=True),
    Column("decision_reason", Text, nullable=False),
    Column("comments", Text, nullable=True),
    Column("additional_info_request", Text, nullable=True),
    Column("additional_info_response", Text, nullable=True),
    Column("investigation_instructions", Text, nullable=True),
    Column("previous_review_status", String(64), nullable=False),
    Column("new_review_status", String(64), nullable=False),
    Column("is_correction", Integer, nullable=False, default=0),
    Column("parent_review_id", String(128), nullable=True),
    Column("correction_explanation", Text, nullable=True),
    Column("submission_hash", String(128), nullable=False, unique=True),
    Column("review_timestamp", String(64), nullable=False),
    Column("event_type", String(64), nullable=False, default="HUMAN_REVIEW_EVENT"),
    Index("idx_reviews_app_ts", "application_id", "review_timestamp"),
    Index("idx_reviews_run_ts", "source_run_id", "review_timestamp"),
    Index("idx_reviews_hash", "submission_hash"),
    Index("idx_reviews_user_id", "reviewer_user_id"),
)

__all__ = [
    "app_metadata",
    "human_review_events_table",
    "submitted_applications_table",
    "underwriting_runs_table",
]
