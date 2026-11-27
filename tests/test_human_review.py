"""Comprehensive Tests for Stage 6 Human Underwriter Review & Audit.

Covers:
1. Review queue filtering & unbiased summary metrics (excluding failed runs from completed AI decisions).
2. Lifecycle actions: APPROVE, REJECT, REQUEST_ADDITIONAL_INFO, RETURN_FOR_INVESTIGATION, START_REVIEW, RETURN_TO_PENDING.
3. Server-side validation (reviewer ID, reason, comment bounds, conditional details, confirmation, run integrity).
4. Explicit transition rules, terminal immutability, linked correction events, and duplicate prevention.
5. Append-only SQLite persistence, transaction failure handling, and idempotent schema migrations.
6. End-to-end Streamlit AppTest interaction across Underwriter Review Queue, Results, Details, and Audit History,
   strictly asserting original AI recommendations remain unchanged after human decisions.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.database import init_db
from app.database.applications import save_submitted_application
from app.database.audit import get_audit_run_by_id, save_underwriting_run
from app.database.reviews import (
    get_human_review_by_id,
    get_human_review_events,
    get_latest_review_for_run,
    get_review_history_for_run,
    init_reviews_table,
)
from app.decision.decision_agent import DecisionReasoningAgent
from app.orchestration.orchestrator import UnderwritingOrchestrator
from app.review.service import (
    DuplicateReviewSubmissionError,
    InvalidReviewSubmissionError,
    InvalidReviewTransitionError,
    compute_review_queue_metrics,
    get_case_review_summary,
    list_review_queue,
    record_additional_info_return,
    submit_human_review,
    submit_human_review_safe,
)
from app.schemas.applicant import Applicant
from app.schemas.review import ReviewStatus
from app.schemas.underwriting import (
    AgentExecutionStatus,
    AgentStatus,
    OrchestrationStatus,
    UnderwritingAnalysisResult,
)
from app.ui.services import load_applicant_catalog
from config.settings import get_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_stage6_db(tmp_path, monkeypatch):
    """Provide a clean isolated SQLite DB per test without touching loan_underwriting.db."""
    db_file = tmp_path / "stage6_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    get_settings.cache_clear()
    init_db()
    yield db_file
    get_settings.cache_clear()


def _seed_ai_run(
    app_id: str = "APP0006",
) -> tuple[str, str, UnderwritingAnalysisResult]:
    """Run real pipeline for a synthetic applicant and persist AI audit row."""
    orch = UnderwritingOrchestrator()
    dec_agent = DecisionReasoningAgent()
    analysis = orch.process(app_id)
    decision = dec_agent.evaluate(analysis)
    run_id = save_underwriting_run(analysis, decision, execution_time_ms=42.0)
    return run_id, decision.recommendation.value, analysis


def _seed_failed_ai_run(app_id: str = "APP_FAIL_Q1") -> str:
    """Persist a FAILED pipeline execution cleanly for queue triage testing."""
    dec_agent = DecisionReasoningAgent()
    analysis = UnderwritingAnalysisResult(
        application_id=app_id,
        applicant_id=app_id,
        orchestration_status=OrchestrationStatus.FAILED,
        eligibility_result=None,
        risk_result=None,
        anomaly_result=None,
        error_message="Simulated critical pipeline failure",
        agent_statuses={
            "risk_agent": AgentExecutionStatus(
                agent_name="risk_agent",
                status=AgentStatus.FAILED,
                success=False,
                output_available=False,
                error="Missing artifact",
            )
        },
    )
    decision = dec_agent.evaluate(analysis)
    return save_underwriting_run(analysis, decision, execution_time_ms=8.0)


# ==============================================================================
# 1. QUEUE FILTERING, METRICS & FAILED PIPELINE SEPARATION
# ==============================================================================


def test_review_queue_filtering_and_failed_run_exclusion():
    """Verify queue filters, pending counts, and strict separation of failed runs from completed AI decisions."""
    run_manual, rec_manual, _ = _seed_ai_run("APP0006")  # MANUAL_REVIEW / LOW
    run_approve, rec_approve, _ = _seed_ai_run("APP0002")  # APPROVE / MEDIUM
    run_reject, rec_reject, _ = _seed_ai_run("APP0001")  # REJECT / HIGH
    run_failed = _seed_failed_ai_run("APP_FAIL_999")

    assert rec_manual == "MANUAL_REVIEW"
    assert rec_approve == "APPROVE"
    assert rec_reject == "REJECT"

    catalog_map = {r["applicant_id"]: r for r in load_applicant_catalog()}
    full_queue = list_review_queue(
        applicant_catalog_by_id=catalog_map, include_finalized=True
    )
    assert len(full_queue) == 4

    metrics = compute_review_queue_metrics(full_queue)
    assert metrics["pending_reviews"] == 4
    assert metrics["completed_ai_decisions"] == 3
    assert metrics["failed_pipeline_runs"] == 1
    assert metrics["approved_by_underwriter"] == 0

    # Approve APP0002 by human -> pending decreases cleanly while failed run remains uncounted in completed AI
    submit_human_review(
        {
            "source_run_id": run_approve,
            "application_id": "APP0002",
            "action": "APPROVE",
            "reviewer_id": "UW_PATEL",
            "decision_reason": "Clean underwriting profile confirmed manually.",
            "confirmed": True,
        }
    )

    refreshed_full = list_review_queue(
        applicant_catalog_by_id=catalog_map, include_finalized=True
    )
    m2 = compute_review_queue_metrics(refreshed_full)
    assert m2["pending_reviews"] == 3
    assert m2["approved_by_underwriter"] == 1

    # Filter checks
    assert (
        len(
            list_review_queue(
                applicant_catalog_by_id=catalog_map,
                ai_recommendation_filter="MANUAL_REVIEW",
            )
        )
        >= 1
    )
    assert (
        len(
            list_review_queue(
                applicant_catalog_by_id=catalog_map, pipeline_status_filter="FAILED"
            )
        )
        == 1
    )
    assert (
        list_review_queue(
            applicant_catalog_by_id=catalog_map, pipeline_status_filter="FAILED"
        )[0]["source_run_id"]
        == run_failed
    )
    assert (
        len(
            list_review_queue(
                applicant_catalog_by_id=catalog_map, review_status_filter="APPROVED"
            )
        )
        == 1
    )
    assert (
        len(
            list_review_queue(
                applicant_catalog_by_id=catalog_map, application_id_filter="APP0006"
            )
        )
        == 1
    )
    assert (
        len(
            list_review_queue(
                applicant_catalog_by_id=catalog_map, risk_category_filter="HIGH"
            )
        )
        >= 1
    )


# ==============================================================================
# 2. ACTIONS, LIFECYCLE TRANSITIONS, CORRECTIONS & PRESERVED AI RECOMMENDATION
# ==============================================================================


def test_human_review_actions_and_immutable_ai_preservation():
    """Test APPROVE, REJECT, REQUEST_ADDITIONAL_INFO, RETURN_FOR_INVESTIGATION, and AI immutability."""
    # Case 1: AI says MANUAL_REVIEW, Human approves -> AI recommendation stays MANUAL_REVIEW!
    run_6, ai_rec_6, _ = _seed_ai_run("APP0006")
    assert ai_rec_6 == "MANUAL_REVIEW"

    # First claim PENDING -> IN_REVIEW
    ev_claim = submit_human_review(
        {
            "source_run_id": run_6,
            "application_id": "APP0006",
            "action": "START_REVIEW",
            "reviewer_id": "UW_01",
            "decision_reason": "Claimed case for verification.",
            "confirmed": True,
        }
    )
    assert ev_claim["new_review_status"] == ReviewStatus.IN_REVIEW.value
    assert ev_claim["human_decision"] is None

    # Then Approve -> IN_REVIEW -> APPROVED
    ev_app = submit_human_review(
        {
            "source_run_id": run_6,
            "application_id": "APP0006",
            "action": "APPROVE",
            "reviewer_id": "UW_01",
            "decision_reason": "Verified variable bonus deposits explain income delta.",
            "comments": "Reviewed employer bonus letter; account 123456789012 checked.",
            "confirmed": True,
        }
    )
    assert ev_app["new_review_status"] == ReviewStatus.APPROVED.value
    assert ev_app["human_decision"] == "APPROVE"
    # Verify PII digits inside comments masked cleanly
    assert "123456789012" not in (ev_app["comments"] or "")
    # Verify AI record in underwriting_runs is 100% unchanged
    ai_row = get_audit_run_by_id(run_6)
    assert ai_row is not None
    assert ai_row["recommendation"] == "MANUAL_REVIEW"

    summary = get_case_review_summary("APP0006", run_id=run_6)
    assert summary["ai_recommendation"] == "MANUAL_REVIEW"
    assert summary["pipeline_status"] == "SUCCESS"
    assert summary["human_review_status"] == "APPROVED"
    assert summary["human_decision"] == "APPROVE"

    # Case 2: Valid REJECT
    run_2, _, _ = _seed_ai_run("APP0002")
    ev_rej = submit_human_review(
        {
            "source_run_id": run_2,
            "application_id": "APP0002",
            "action": "REJECT",
            "reviewer_id": "UW_02",
            "decision_reason": "Declined under internal portfolio concentration cap.",
            "confirmed": True,
        }
    )
    assert ev_rej["new_review_status"] == "REJECTED"
    assert ev_rej["human_decision"] == "REJECT"
    assert get_audit_run_by_id(run_2)["recommendation"] == "APPROVE"

    # Case 3: Additional Info Requested is NEVER treated as approval/rejection + Return to PENDING without AI rerun
    run_16, _, _ = _seed_ai_run("APP0016")
    ev_info = submit_human_review(
        {
            "source_run_id": run_16,
            "application_id": "APP0016",
            "action": "REQUEST_ADDITIONAL_INFO",
            "reviewer_id": "UW_03",
            "decision_reason": "Bank statement missing from submission package.",
            "additional_info_request": "Please upload latest 6-month stamped bank statement PDF.",
            "confirmed": True,
        }
    )
    assert ev_info["new_review_status"] == "ADDITIONAL_INFO_REQUESTED"
    assert ev_info["human_decision"] is None

    # Return to PENDING queue without triggering any new AI run
    ret = record_additional_info_return(
        source_run_id=run_16,
        application_id="APP0016",
        reviewer_id="INTAKE_CLERK",
        info_response="Updated bank statement received and verified for re-review.",
    )
    assert ret["saved"] is True
    assert ret["event"]["previous_review_status"] == "ADDITIONAL_INFO_REQUESTED"
    assert ret["event"]["new_review_status"] == "PENDING"
    assert ret["event"]["human_decision"] is None

    # Case 4: Investigation Required is NEVER treated as final decision
    run_8, _, _ = _seed_ai_run("APP0008")
    ev_inv = submit_human_review(
        {
            "source_run_id": run_8,
            "application_id": "APP0008",
            "action": "RETURN_FOR_INVESTIGATION",
            "reviewer_id": "UW_04",
            "decision_reason": "Material income mismatch combined with borderline risk score.",
            "investigation_instructions": "Perform direct employer HR salary verification.",
            "confirmed": True,
        }
    )
    assert ev_inv["new_review_status"] == "INVESTIGATION_REQUIRED"
    assert ev_inv["human_decision"] is None


def test_validation_rejects_missing_and_invalid_inputs():
    """Verify server-side validation blocks empty reviewer, reason, details, confirmation & bad length."""
    run_6, _, _ = _seed_ai_run("APP0006")

    invalid_cases = [
        # Missing reviewer identifier
        {
            "source_run_id": run_6,
            "application_id": "APP0006",
            "action": "APPROVE",
            "reviewer_id": "",
            "decision_reason": "Valid reason text here.",
            "confirmed": True,
        },
        # Missing decision reason
        {
            "source_run_id": run_6,
            "application_id": "APP0006",
            "action": "APPROVE",
            "reviewer_id": "UW_01",
            "decision_reason": "  ",
            "confirmed": True,
        },
        # Missing additional-info details on REQUEST_ADDITIONAL_INFO
        {
            "source_run_id": run_6,
            "application_id": "APP0006",
            "action": "REQUEST_ADDITIONAL_INFO",
            "reviewer_id": "UW_01",
            "decision_reason": "Docs missing.",
            "additional_info_request": "",
            "confirmed": True,
        },
        # Missing investigation instructions on RETURN_FOR_INVESTIGATION
        {
            "source_run_id": run_6,
            "application_id": "APP0006",
            "action": "RETURN_FOR_INVESTIGATION",
            "reviewer_id": "UW_01",
            "decision_reason": "Suspicious anomaly.",
            "investigation_instructions": "no",
            "confirmed": True,
        },
        # Missing explicit confirmation
        {
            "source_run_id": run_6,
            "application_id": "APP0006",
            "action": "APPROVE",
            "reviewer_id": "UW_01",
            "decision_reason": "Valid reason text here.",
            "confirmed": False,
        },
        # Over-length comments > 2000 chars
        {
            "source_run_id": run_6,
            "application_id": "APP0006",
            "action": "APPROVE",
            "reviewer_id": "UW_01",
            "decision_reason": "Valid reason text here.",
            "comments": "x" * 2005,
            "confirmed": True,
        },
        # Fabricated/non-existent source run
        {
            "source_run_id": "RUN-FAKE-999",
            "application_id": "APP0006",
            "action": "APPROVE",
            "reviewer_id": "UW_01",
            "decision_reason": "Valid reason text here.",
            "confirmed": True,
        },
    ]

    for payload in invalid_cases:
        with pytest.raises(InvalidReviewSubmissionError):
            submit_human_review(payload)
        safe_res = submit_human_review_safe(payload)
        assert safe_res["saved"] is False
        assert safe_res["error"]

    assert get_review_history_for_run(run_6) == []


def test_transitions_duplicate_protection_and_linked_corrections():
    """Verify transition rules, duplicate block, append-only preservation, and linked corrections."""
    run_6, _, _ = _seed_ai_run("APP0006")

    # Cannot jump PENDING -> PENDING via RETURN_TO_PENDING
    with pytest.raises(InvalidReviewTransitionError):
        submit_human_review(
            {
                "source_run_id": run_6,
                "application_id": "APP0006",
                "action": "RETURN_TO_PENDING",
                "reviewer_id": "UW_01",
                "decision_reason": "Trying meaningless no-op transition.",
                "confirmed": True,
            }
        )

    # Record initial APPROVAL
    ev1 = submit_human_review(
        {
            "source_run_id": run_6,
            "application_id": "APP0006",
            "action": "APPROVE",
            "reviewer_id": "UW_SENIOR_1",
            "decision_reason": "Initial manual approval after doc inspection.",
            "confirmed": True,
        }
    )

    # Duplicate exact submission (even before correction or exact same payload) -> blocked cleanly
    with pytest.raises(InvalidReviewTransitionError):
        # Attempting non-correction transition from APPROVED is rejected cleanly
        submit_human_review(
            {
                "source_run_id": run_6,
                "application_id": "APP0006",
                "action": "REJECT",
                "reviewer_id": "UW_SENIOR_1",
                "decision_reason": "Silent overwrite attempt.",
                "confirmed": True,
            }
        )

    # Correction without explanation rejected cleanly
    with pytest.raises(InvalidReviewTransitionError):
        submit_human_review(
            {
                "source_run_id": run_6,
                "application_id": "APP0006",
                "action": "REJECT",
                "reviewer_id": "UW_SENIOR_1",
                "decision_reason": "Reversing prior decision.",
                "is_correction": True,
                "parent_review_id": ev1["review_id"],
                "correction_explanation": "",
                "confirmed": True,
            }
        )

    # Valid linked correction appends NEW record and keeps ev1 completely intact!
    ev2 = submit_human_review(
        {
            "source_run_id": run_6,
            "application_id": "APP0006",
            "action": "REJECT",
            "reviewer_id": "UW_SUPERVISOR_2",
            "decision_reason": "Post-QA income audit disproved salary claim.",
            "is_correction": True,
            "parent_review_id": ev1["review_id"],
            "correction_explanation": "Quality control discovered forged employer verification stamp.",
            "confirmed": True,
        }
    )
    assert ev2["review_id"] != ev1["review_id"]
    assert ev2["is_correction"] is True
    assert ev2["parent_review_id"] == ev1["review_id"]
    assert ev2["previous_review_status"] == "APPROVED"
    assert ev2["new_review_status"] == "REJECTED"
    assert ev2["human_decision"] == "REJECT"

    # Original record ev1 remains unmodified
    ev1_reload = get_human_review_by_id(ev1["review_id"])
    assert ev1_reload is not None
    assert ev1_reload["new_review_status"] == "APPROVED"
    assert ev1_reload["human_decision"] == "APPROVE"
    assert ev1_reload["reviewer_id"] == "UW_SENIOR_1"

    # Duplicate identical submission on active state blocked by hash guard
    run_2, _, _ = _seed_ai_run("APP0002")
    claim_payload = {
        "source_run_id": run_2,
        "application_id": "APP0002",
        "action": "START_REVIEW",
        "reviewer_id": "UW_DUP",
        "decision_reason": "Starting review cleanly.",
        "confirmed": True,
    }
    submit_human_review(claim_payload)
    # Submitting another correction with identical payload hash fails as duplicate!
    corr_payload = {
        "source_run_id": run_2,
        "application_id": "APP0002",
        "action": "APPROVE",
        "reviewer_id": "UW_DUP",
        "decision_reason": "Approve clean.",
        "confirmed": True,
    }
    first_app = submit_human_review(corr_payload)
    dup_corr = dict(corr_payload)
    dup_corr["is_correction"] = True
    dup_corr["parent_review_id"] = first_app["review_id"]
    dup_corr["correction_explanation"] = "Duplicate correction test."
    submit_human_review(dup_corr)
    # Submitting the exact same correction payload when previous status returned to APPROVED matches hash
    with pytest.raises(DuplicateReviewSubmissionError):
        submit_human_review(dup_corr)


# ==============================================================================
# 3. DB FAILURE CONTAINMENT & IDEMPOTENT MIGRATIONS
# ==============================================================================


def test_human_review_db_failure_and_idempotent_migration(tmp_path, monkeypatch):
    """Verify DB write failures never falsely succeed and legacy schema migrates idempotently."""
    run_6, _, _ = _seed_ai_run("APP0006")

    def failing_insert(*args, **kwargs):
        raise sqlite3.OperationalError("simulated review db write lock")

    monkeypatch.setattr("app.review.service.insert_human_review_event", failing_insert)
    res = submit_human_review_safe(
        {
            "source_run_id": run_6,
            "application_id": "APP0006",
            "action": "APPROVE",
            "reviewer_id": "UW_01",
            "decision_reason": "Attempting save during DB outage.",
            "confirmed": True,
        }
    )
    assert res["saved"] is False
    assert res["event"] is None
    assert "simulated review db write lock" in (res["error"] or "")
    assert get_latest_review_for_run(run_6) is None

    # Idempotent legacy migration check
    legacy_db = tmp_path / "legacy_reviews.db"
    conn = sqlite3.connect(legacy_db)
    conn.execute("""
        CREATE TABLE human_review_events (
            review_id TEXT PRIMARY KEY,
            source_run_id TEXT NOT NULL,
            application_id TEXT NOT NULL,
            applicant_id TEXT NOT NULL,
            original_ai_recommendation TEXT NOT NULL,
            action TEXT NOT NULL,
            human_decision TEXT,
            reviewer_id TEXT NOT NULL,
            decision_reason TEXT NOT NULL,
            comments TEXT,
            additional_info_request TEXT,
            investigation_instructions TEXT,
            previous_review_status TEXT NOT NULL,
            new_review_status TEXT NOT NULL,
            is_correction INTEGER NOT NULL DEFAULT 0,
            parent_review_id TEXT,
            correction_explanation TEXT,
            submission_hash TEXT NOT NULL,
            review_timestamp TEXT NOT NULL
        );
        """)
    conn.commit()
    conn.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{legacy_db}")
    get_settings.cache_clear()
    init_reviews_table()
    init_reviews_table()  # Run twice -> strictly idempotent!

    conn = sqlite3.connect(legacy_db)
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(human_review_events);").fetchall()
    }
    conn.close()
    assert "original_pipeline_status" in cols
    assert "additional_info_response" in cols
    assert "event_type" in cols


# ==============================================================================
# 4. STREAMLIT APPTEST END-TO-END HUMAN REVIEW WORKFLOW
# ==============================================================================


def test_streamlit_apptest_human_review_queue_and_audit_separation():
    """Drive Underwriter Review Queue end-to-end via AppTest, verifying submission, rerun safety & Audit History."""
    run_id, ai_rec, _ = _seed_ai_run("APP0006")
    assert ai_rec == "MANUAL_REVIEW"

    # Also register submitted_application record for richness
    app_model = Applicant(
        applicant_id="APP0006",
        name="Kavita Deshmukh",
        age=31,
        employment_type="Salaried",
        employment_years=5.0,
        monthly_income=85000.0,
        existing_emi=10000.0,
        loan_amount=450000.0,
        loan_tenure=36,
        credit_score=760,
        bank_balance=200000.0,
    )
    save_submitted_application(
        applicant=app_model, application_status="UNDERWRITTEN", latest_run_id=run_id
    )

    at = AppTest.from_file(str(PROJECT_ROOT / "app" / "main.py")).run(timeout=20)
    assert not at.exception

    # Open Underwriter Review Queue page
    at.sidebar.radio(key="sidebar_nav_radio").set_value("Underwriter Review Queue").run(
        timeout=20
    )
    assert not at.exception

    # Select Approve and submit valid human review decision
    at.selectbox(key=f"rq_action_{run_id}").set_value("Approve")
    at.text_input(key=f"rq_reviewer_id_{run_id}").set_value("UW_VERIFIER_99")
    at.text_input(key=f"rq_reason_{run_id}").set_value(
        "Bonus slips verified offline; income discrepancy resolved."
    )
    at.text_area(key=f"rq_comments_{run_id}").set_value(
        "Manual review complete; AI flag documented cleanly."
    )
    at.checkbox(key=f"rq_confirm_{run_id}").set_value(True)
    at.run(timeout=20)
    assert not at.exception

    at.button(key=f"rq_btn_submit_{run_id}").click().run(timeout=20)
    assert not at.exception

    # Verify DB state: 1 human review event created, AI recommendation STILL MANUAL_REVIEW!
    events = get_human_review_events(source_run_id=run_id)
    assert len(events) == 1
    assert events[0]["reviewer_id"] == "UW_VERIFIER_99"
    assert events[0]["human_decision"] == "APPROVE"
    assert events[0]["new_review_status"] == "APPROVED"
    assert events[0]["original_ai_recommendation"] == "MANUAL_REVIEW"

    ai_row = get_audit_run_by_id(run_id)
    assert ai_row is not None
    assert ai_row["recommendation"] == "MANUAL_REVIEW"

    # Arbitrary Streamlit rerun must NOT create a duplicate review event
    at.run(timeout=20)
    assert not at.exception
    assert len(get_human_review_events(source_run_id=run_id)) == 1

    # Navigate to Underwriting Results & Application Details & Audit History cleanly
    for page in ("Underwriting Results", "Application Details", "Audit History"):
        at.sidebar.radio(key="sidebar_nav_radio").set_value(page).run(timeout=20)
        assert not at.exception, f"Page '{page}' crashed: {at.exception}"

    # Verify Audit History displays human review events cleanly without edits/deletions
    assert len(at.dataframe) >= 1
