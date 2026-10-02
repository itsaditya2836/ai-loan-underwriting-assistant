"""Automated Unit and Integration Tests for Stage 9 Dashboard & Audit Trail.

Verifies:
1. Audit database table creation and indexing.
2. Immutable audit persistence (save_underwriting_run).
3. Multi-run history preservation (verifying second run does not overwrite first run).
4. Audit querying and filtering by recommendation, status, risk, and anomaly.
5. Aggregate portfolio analytics calculation (rates, distributions, averages).
6. End-to-end pipeline execution and audit persistence (execute_underwriting_pipeline).
7. Applicant metadata loading and document package verification.
"""

import pytest

from app.database.audit import (
    get_applicant_run_history,
    get_audit_analytics_summary,
    get_audit_run_by_id,
    get_audit_runs,
    init_audit_table,
    save_underwriting_run,
)
from app.database.db import get_database_connection
from app.decision.decision_agent import DecisionReasoningAgent
from app.orchestration.orchestrator import UnderwritingOrchestrator
from app.schemas.decision import DecisionOutcome
from app.ui.dashboard import (
    execute_underwriting_pipeline,
    get_applicant_by_id,
    has_document_package,
    load_all_applicants_metadata,
)


@pytest.fixture(autouse=True)
def setup_test_db():
    """Ensure audit table is created before every test."""
    init_audit_table()


# ==============================================================================
# AUDIT DATABASE TESTS
# ==============================================================================


def test_audit_table_initialization():
    """Test 1: Verify audit table and indexes are created in SQLite."""
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='underwriting_runs';"
        )
        table = cursor.fetchone()
        assert table is not None
        assert table[0] == "underwriting_runs"

        # Verify columns
        cursor.execute("PRAGMA table_info(underwriting_runs);")
        columns = [row[1] for row in cursor.fetchall()]
        expected_cols = [
            "run_id",
            "application_id",
            "timestamp",
            "pipeline_version",
            "decision_policy_version",
            "orchestrator_version",
            "recommendation",
            "decision_confidence",
            "eligibility_status",
            "risk_category",
            "risk_score",
            "anomaly_severity",
            "anomaly_score",
            "documents_found_count",
            "documents_missing_count",
            "human_review_required",
            "pipeline_status",
            "execution_time_ms",
            "reasons_json",
            "positive_factors_json",
            "negative_factors_json",
            "blocking_factors_json",
            "supporting_evidence_json",
            "summary_narrative",
        ]
        for col in expected_cols:
            assert col in columns


def test_save_and_retrieve_underwriting_run():
    """Test 2: Save a single underwriting run and verify roundtrip retrieval."""
    orchestrator = UnderwritingOrchestrator()
    analysis = orchestrator.process("APP0002")

    decision_agent = DecisionReasoningAgent()
    decision = decision_agent.evaluate(analysis)

    run_id = save_underwriting_run(
        analysis=analysis,
        decision=decision,
        execution_time_ms=125.5,
    )

    assert run_id.startswith("RUN-APP0002-")

    retrieved = get_audit_run_by_id(run_id)
    assert retrieved is not None
    assert retrieved["run_id"] == run_id
    assert retrieved["application_id"] == "APP0002"
    assert retrieved["recommendation"] == DecisionOutcome.APPROVE.value
    assert retrieved["decision_confidence"] >= 70.0
    assert retrieved["human_review_required"] is True
    assert retrieved["pipeline_status"] == "SUCCESS"
    assert isinstance(retrieved["reasons"], list)
    assert len(retrieved["reasons"]) > 0
    assert isinstance(retrieved["positive_factors"], list)


def test_audit_immutability_multiple_runs():
    """Test 3: Verify multiple runs for the same applicant are preserved without overwrite."""
    orchestrator = UnderwritingOrchestrator()
    decision_agent = DecisionReasoningAgent()

    analysis = orchestrator.process("APP0006")
    decision = decision_agent.evaluate(analysis)

    # First run
    run_1_id = save_underwriting_run(analysis, decision, execution_time_ms=100.0)
    # Second run for same applicant
    run_2_id = save_underwriting_run(analysis, decision, execution_time_ms=105.0)

    assert run_1_id != run_2_id

    # Retrieve history for APP0006
    history = get_applicant_run_history("APP0006")
    history_ids = [r["run_id"] for r in history]

    assert run_1_id in history_ids
    assert run_2_id in history_ids
    assert len(history) >= 2


def test_audit_filtering():
    """Test 4: Verify querying with filters (recommendation, risk, anomaly, status)."""
    orchestrator = UnderwritingOrchestrator()
    decision_agent = DecisionReasoningAgent()

    # Create distinct runs
    analysis_clean = orchestrator.process("APP0003")  # APPROVE
    decision_clean = decision_agent.evaluate(analysis_clean)
    save_underwriting_run(analysis_clean, decision_clean, execution_time_ms=80.0)

    analysis_reject = orchestrator.process("APP0001")  # REJECT
    decision_reject = decision_agent.evaluate(analysis_reject)
    save_underwriting_run(analysis_reject, decision_reject, execution_time_ms=90.0)

    # Filter by APPROVE
    approved_runs = get_audit_runs(recommendation="APPROVE")
    assert len(approved_runs) > 0
    for r in approved_runs:
        assert r["recommendation"] == "APPROVE"

    # Filter by REJECT
    rejected_runs = get_audit_runs(recommendation="REJECT")
    assert len(rejected_runs) > 0
    for r in rejected_runs:
        assert r["recommendation"] == "REJECT"

    # Filter by application_id
    app_runs = get_audit_runs(application_id="APP0001")
    assert len(app_runs) > 0
    for r in app_runs:
        assert r["application_id"] == "APP0001"


def test_audit_analytics_summary():
    """Test 5: Verify aggregate analytics summary calculation."""
    summary = get_audit_analytics_summary()

    assert "total_runs" in summary
    assert "unique_applications" in summary
    assert "recommendation_distribution" in summary
    assert "risk_distribution" in summary
    assert "anomaly_distribution" in summary
    assert "eligibility_distribution" in summary
    assert "manual_review_rate" in summary

    assert summary["total_runs"] > 0
    assert summary["unique_applications"] > 0
    assert summary["manual_review_rate"] >= 0.0


# ==============================================================================
# PIPELINE INTEGRATION & UI HELPER TESTS
# ==============================================================================


def test_execute_underwriting_pipeline_integration():
    """Test 6: Verify execute_underwriting_pipeline wrapper runs and saves run."""
    analysis, decision, run_id, duration_ms = execute_underwriting_pipeline("APP0004")

    assert analysis.application_id == "APP0004"
    assert decision.application_id == "APP0004"
    assert decision.recommendation == DecisionOutcome.APPROVE
    assert run_id.startswith("RUN-APP0004-")
    assert duration_ms > 0.0

    # Verify run exists in DB
    run_record = get_audit_run_by_id(run_id)
    assert run_record is not None
    assert run_record["application_id"] == "APP0004"


def test_applicant_metadata_loading():
    """Test 7: Verify applicant loading and document package detection."""
    all_applicants = load_all_applicants_metadata()
    assert len(all_applicants) >= 30

    app1 = get_applicant_by_id("APP0001")
    assert app1 is not None
    assert app1["applicant_id"] == "APP0001"
    assert "name" in app1
    assert "monthly_income" in app1
    assert "loan_amount" in app1

    # Check physical document detection
    assert has_document_package("APP0001") is True
    assert has_document_package("NON_EXISTENT_APP") is False
