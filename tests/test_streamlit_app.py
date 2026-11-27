"""Comprehensive Automated Tests for the Stage 5 Complete Streamlit Application.

Covers:
1. Dashboard metrics (empty DB, populated DB, failed runs excluded from completed apps, optional None).
2. Applicant intake schema validation (valid, missing required, age/financial bounds, preserved zeros, dupes).
3. Document upload workflow (valid PDF, wrong extension, bad signature, oversized, 0-byte, multiple docs,
   SHA-256 duplicates, missing required docs, corrupt PDF extraction failure, temp directory cleanup, PII masking).
4. Underwriting submission & fail-closed behavior (APPROVE, MANUAL_REVIEW, REJECT, failed risk/fraud agents,
   audit DB failure containment, duplicate prevention).
5. Results display & Document Review (APPROVE/REJECT/MANUAL_REVIEW mappings, unavailable risk score != 0.0,
   unavailable fraud status != NONE, invalid fields, consistency conflicts).
6. Applications, Application Details & Audit History (multi-run isolation without join duplicates, filtering,
   historical run snapshot loading, missing optional fields).
7. End-to-end Streamlit `AppTest` navigation and form submission user journey without rerun duplication.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.database import init_db
from app.database.applications import (
    count_submitted_applications,
    get_submitted_application,
    list_submitted_applications,
)
from app.database.audit import (
    get_applicant_run_history,
    get_audit_run_by_id,
    get_audit_runs,
    save_underwriting_run,
)
from app.decision.decision_agent import DecisionReasoningAgent
from app.orchestration.orchestrator import UnderwritingOrchestrator
from app.risk.risk_model import RiskModelLoadError
from app.schemas.applicant import (
    Applicant,
    DocumentPackageResult,
    EligibilityResult,
    EligibilityStatus,
    RiskLevel,
    RiskResult,
)
from app.schemas.decision import DecisionOutcome
from app.schemas.underwriting import (
    AgentExecutionStatus,
    AgentStatus,
    OrchestrationStatus,
    UnderwritingAnalysisResult,
)
from app.ui.components import (
    format_fraud_status_display,
    format_risk_score_display,
)
from app.ui.services import (
    compute_dashboard_metrics,
    format_decision_label,
    generate_applicant_reference,
    get_applicant_record,
    mask_extracted_value,
    preview_uploaded_documents,
    submit_application_and_underwrite,
    validate_applicant_form_input,
    validate_uploaded_pdf,
)
from app.ui.views_results import _normalize_view_context
from config.settings import get_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_stage5_db(tmp_path, monkeypatch):
    """Isolate SQLite DB per test cleanly via DATABASE_URL and lru_cache reset."""
    db_file = tmp_path / "stage5_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    get_settings.cache_clear()
    init_db()
    yield db_file
    get_settings.cache_clear()


def _load_real_pdf_bytes(app_id: str) -> list[tuple[str, bytes]]:
    """Read existing synthetic PDF documents from disk for genuine Stage 3 upload tests."""
    doc_dir = PROJECT_ROOT / "data" / "documents" / app_id
    files: list[tuple[str, bytes]] = []
    for p in sorted(doc_dir.glob("*.pdf")):
        files.append((p.name, p.read_bytes()))
    return files


def _make_clean_applicant(
    app_id: str = "APP-UI-0001",
    credit_score: int = 760,
    monthly_income: float = 105000.0,
    existing_emi: float = 15000.0,
    loan_amount: float = 350000.0,
) -> Applicant:
    return Applicant(
        applicant_id=app_id,
        name="Satish Singh",
        age=35,
        employment_type="Salaried",
        employment_years=6.0,
        monthly_income=monthly_income,
        existing_emi=existing_emi,
        loan_amount=loan_amount,
        loan_tenure=36,
        credit_score=credit_score,
        bank_balance=250000.0,
        monthly_expenses=25000.0,
        number_of_dependents=1,
    )


# ==============================================================================
# 1. DASHBOARD METRICS & FAILED RUN SEPARATION
# ==============================================================================


def test_dashboard_metrics_empty_and_failed_run_exclusion():
    """Verify empty DB state and strict separation of failed runs from completed applications."""
    empty_m = compute_dashboard_metrics()
    assert empty_m["submitted_applications_count"] == 0
    assert empty_m["evaluated_completed_applications"] == 0
    assert empty_m["approved_applications"] == 0
    assert empty_m["audit_summary"]["total_runs"] == 0

    # Persist 1 completed APPROVE run and 1 FAILED pipeline run (missing optional risk/fraud)
    orch = UnderwritingOrchestrator()
    dec_agent = DecisionReasoningAgent()

    a_ok = orch.process("APP0002")
    d_ok = dec_agent.evaluate(a_ok)
    save_underwriting_run(a_ok, d_ok, execution_time_ms=25.0)

    a_fail = UnderwritingAnalysisResult(
        application_id="APP_CRASH_99",
        applicant_id="APP_CRASH_99",
        orchestration_status=OrchestrationStatus.FAILED,
        eligibility_result=None,
        risk_result=None,
        anomaly_result=None,
        error_message="Simulated critical crash",
        agent_statuses={
            "risk_agent": AgentExecutionStatus(
                agent_name="risk_agent",
                status=AgentStatus.FAILED,
                success=False,
                output_available=False,
                error="RiskModelLoadError",
            )
        },
    )
    d_fail = dec_agent.evaluate(a_fail)
    fail_run_id = save_underwriting_run(a_fail, d_fail, execution_time_ms=10.0)

    metrics = compute_dashboard_metrics()
    assert metrics["audit_summary"]["total_runs"] == 2
    assert metrics["audit_summary"]["failed_runs_count"] == 1
    assert metrics["evaluated_completed_applications"] == 1
    assert metrics["approved_applications"] == 1
    assert metrics["failed_latest_applications"] == 1

    fail_row = get_audit_run_by_id(fail_run_id)
    assert fail_row is not None
    assert fail_row["risk_score"] is None
    assert format_risk_score_display(fail_row["risk_score"]) == "Unavailable"
    assert "UNAVAILABLE" in format_fraud_status_display(fail_row["anomaly_severity"])


# ==============================================================================
# 2. APPLICANT INTAKE SCHEMA VALIDATION & PRESERVED ZERO VALUES
# ==============================================================================


def test_applicant_intake_validation_rules_and_zero_preservation():
    """Verify required checks, age/financial bounds, and strict preservation of valid zero inputs."""
    # Missing required name and bad age/credit score
    bad_raw = {
        "applicant_id": "BAD ID WITH SPACES",
        "name": "   ",
        "age": 16,
        "employment_type": "Salaried",
        "employment_years": -1.0,
        "monthly_income": -500.0,
        "existing_emi": 0.0,
        "loan_amount": 0.0,
        "loan_tenure": 0,
        "credit_score": 250,
        "bank_balance": 0.0,
    }
    app_none, errors, _ = validate_applicant_form_input(bad_raw)
    assert app_none is None
    assert len(errors) >= 4

    # Valid zero values cleanly preserved (existing_emi=0.0, bank_balance=0.0, monthly_expenses=0.0, dependents=0)
    zero_raw = {
        "applicant_id": "APP-ZERO-01",
        "name": "Meera Nair",
        "age": 29,
        "employment_type": "Salaried",
        "employment_years": 0.0,
        "monthly_income": 65000.0,
        "existing_emi": 0.0,
        "loan_amount": 200000.0,
        "loan_tenure": 24,
        "credit_score": 740,
        "bank_balance": 0.0,
        "monthly_expenses": 0.0,
        "number_of_dependents": 0,
    }
    valid_app, ok_errors, _ = validate_applicant_form_input(zero_raw)
    assert ok_errors == []
    assert valid_app is not None
    assert valid_app.existing_emi == 0.0
    assert valid_app.bank_balance == 0.0
    assert valid_app.employment_years == 0.0
    assert valid_app.monthly_expenses == 0.0
    assert valid_app.number_of_dependents == 0


def test_generate_unique_applicant_reference():
    ref1 = generate_applicant_reference()
    assert ref1.startswith("APP-")
    assert len(ref1) >= 8


# ==============================================================================
# 3. DOCUMENT UPLOAD VALIDATION, DEDUPLICATION, TEMP CLEANUP & MASKING
# ==============================================================================


def test_document_upload_security_validation_dedupe_and_cleanup():
    """Test invalid extension, bad signature, empty, oversized, valid, duplicate, and temp cleanup."""
    real_pdfs = _load_real_pdf_bytes("APP0002")
    assert len(real_pdfs) == 4
    first_name, first_bytes = real_pdfs[0]

    # Invalid file extension
    bad_ext = validate_uploaded_pdf("payload.txt", b"hello")
    assert bad_ext["status"] == "INVALID"
    assert ".pdf" in (bad_ext["validation_error"] or "")

    # Invalid PDF signature
    bad_sig = validate_uploaded_pdf("fake.pdf", b"NOT_A_PDF_HEADER")
    assert bad_sig["status"] == "INVALID"
    assert "%PDF-" in (bad_sig["validation_error"] or "")

    # Empty file
    empty_pdf = validate_uploaded_pdf("empty.pdf", b"")
    assert empty_pdf["status"] == "INVALID"

    # Oversized limit enforced
    oversized = validate_uploaded_pdf(first_name, first_bytes, max_file_size_bytes=64)
    assert oversized["status"] == "INVALID"
    assert "exceeds maximum limit" in (oversized["validation_error"] or "")

    # Valid PDF + SHA-256 duplicate prevention
    staged = []
    seen_hashes: set[str] = set()
    for fname, raw in real_pdfs:
        item = validate_uploaded_pdf(fname, raw, existing_hashes=seen_hashes)
        assert item["status"] == "VALID"
        seen_hashes.add(item["sha256"])
        staged.append(item)

    dup_item = validate_uploaded_pdf(
        f"copy_{first_name}", first_bytes, existing_hashes=seen_hashes
    )
    assert dup_item["status"] == "DUPLICATE"

    # Process through Stage 3 DocumentIntakeAgent & confirm ephemeral temp dir removed cleanly
    pkg = preview_uploaded_documents("APP0002", staged)
    assert len(pkg.documents_found) == 4
    assert pkg.is_complete is True
    assert not os.path.exists(pkg.package_dir)

    # Corrupt PDF (valid %PDF- header, unreadable content) must NEVER verify cleanly
    corrupt_item = validate_uploaded_pdf("broken.pdf", b"%PDF-1.4\n%%corrupt-body")
    assert corrupt_item["status"] == "VALID"
    corrupt_pkg = preview_uploaded_documents("APP_BROKEN", [corrupt_item])
    assert corrupt_pkg.processing_status == "failed"
    assert not os.path.exists(corrupt_pkg.package_dir)

    # Sensitive value masking check
    masked = mask_extracted_value("account_number", "SYN-ACC-99887766")
    assert "99887766" not in masked
    assert masked.endswith("7766")


# ==============================================================================
# 4. UNDERWRITING SUBMISSION, FAILURE ISOLATION & RESULTS CONTEXT
# ==============================================================================


def test_submission_with_missing_and_complete_uploaded_docs_and_duplicate_block():
    """Test APPROVE/MANUAL_REVIEW/REJECT outcomes, duplicate guard, and multi-run persistence."""
    real_pdfs = _load_real_pdf_bytes("APP0002")
    staged_complete = [validate_uploaded_pdf(fname, raw) for fname, raw in real_pdfs]

    # Case A: Clean matching profile (APP0002) + uploaded complete 4-doc package -> APPROVE
    app_0002_raw = get_applicant_record("APP0002")
    assert app_0002_raw is not None
    clean_app = Applicant.model_validate(app_0002_raw)

    res1 = submit_application_and_underwrite(clean_app, staged_uploads=staged_complete)
    assert res1["duplicate_blocked"] is False
    assert res1["audit_persisted"] is True
    assert res1["decision"].recommendation == DecisionOutcome.APPROVE
    assert (
        format_decision_label(res1["decision"].recommendation.value)
        == "APPROVED (APPROVE)"
    )
    assert count_submitted_applications() == 1

    # Case B: Mismatched Applicant ID vs uploaded PDFs -> contract validator catches mismatch & fails closed
    mismatched_app = _make_clean_applicant(app_id="APP-SUB-MISMATCH", credit_score=765)
    res_mismatch = submit_application_and_underwrite(
        mismatched_app, staged_uploads=staged_complete
    )
    assert res_mismatch["decision"].recommendation == DecisionOutcome.MANUAL_REVIEW
    assert any(
        c["conflict_id"] == "CONFLICT-ELIG-UNAVAILABLE"
        for c in res_mismatch["decision"].consistency_conflicts
    )
    assert any(
        r.code in ("DEC-ELIG-004", "DEC-CON-001", "DEC-FRAUD-001")
        for r in res_mismatch["decision"].reasons
    )
    assert count_submitted_applications() == 2

    # Accidental identical resubmission blocked cleanly
    res_dup = submit_application_and_underwrite(
        clean_app, staged_uploads=staged_complete, allow_duplicate=False
    )
    assert res_dup["duplicate_blocked"] is True
    assert count_submitted_applications() == 2

    # Partial docs (missing 3 required docs) for clean applicant -> MANUAL_REVIEW, second run preserved
    loan_only = [staged_complete[2]]  # only 1 PDF
    res2 = submit_application_and_underwrite(
        clean_app, staged_uploads=loan_only, allow_duplicate=True
    )
    assert res2["decision"].recommendation == DecisionOutcome.MANUAL_REVIEW
    assert len(res2["decision"].missing_documents) >= 1
    assert len(get_applicant_run_history("APP0002")) == 2

    # Disqualified low credit score (APP0001 with its 4 PDFs) -> REJECT
    rej_pdfs = [
        validate_uploaded_pdf(fname, raw)
        for fname, raw in _load_real_pdf_bytes("APP0001")
    ]
    app_0001_raw = get_applicant_record("APP0001")
    assert app_0001_raw is not None
    rej_app = Applicant.model_validate(app_0001_raw)
    res_rej = submit_application_and_underwrite(
        rej_app, staged_uploads=rej_pdfs, allow_duplicate=True
    )
    assert res_rej["decision"].recommendation == DecisionOutcome.REJECT
    assert (
        format_decision_label(res_rej["decision"].recommendation.value)
        == "REJECTED (REJECT)"
    )

    # Verify DB snapshot roundtrip preserves details cleanly across sessions
    ctx = _normalize_view_context("APP0002", res1["run_id"])
    assert ctx is not None
    assert ctx["risk_score"] is not None
    assert ctx["eligibility"] is not None
    assert ctx["document_package"] is not None


def test_submission_fail_closed_when_agents_or_audit_fail(monkeypatch):
    """Verify failed risk model, failed fraud detector, and audit DB failure never fabricate clean results."""
    app_model = _make_clean_applicant(app_id="APP-FAIL-UI")

    # Case 1: RiskModelLoadError -> Risk UNAVAILABLE (never 0.0) & MANUAL_REVIEW
    def boom_risk(*args, **kwargs):
        raise RiskModelLoadError("Missing joblib")

    monkeypatch.setattr("app.agents.risk_agent.RiskAgent.assess", boom_risk)
    res_risk_fail = submit_application_and_underwrite(
        app_model, staged_uploads=[], allow_duplicate=True
    )
    assert res_risk_fail["decision"].recommendation == DecisionOutcome.MANUAL_REVIEW
    assert res_risk_fail["decision"].risk_score is None
    assert res_risk_fail["decision"].risk_category == "UNAVAILABLE"
    assert (
        format_risk_score_display(res_risk_fail["decision"].risk_score) == "Unavailable"
    )

    # Case 2: FraudAnomalyAgent exception -> Fraud UNAVAILABLE (never NONE) & MANUAL_REVIEW
    def boom_fraud(*args, **kwargs):
        raise RuntimeError("Detector crash")

    monkeypatch.setattr("app.agents.fraud_agent.FraudAnomalyAgent.detect", boom_fraud)
    res_fraud_fail = submit_application_and_underwrite(
        app_model, staged_uploads=[], allow_duplicate=True
    )
    assert res_fraud_fail["decision"].recommendation == DecisionOutcome.MANUAL_REVIEW
    assert res_fraud_fail["decision"].fraud_status == "UNAVAILABLE"
    assert "UNAVAILABLE" in format_fraud_status_display(
        res_fraud_fail["decision"].fraud_status
    )

    # Case 3: Audit DB OperationalError contained safely without losing decision
    def broken_save(*args, **kwargs):
        raise sqlite3.OperationalError("readonly database")

    monkeypatch.setattr("app.database.audit.save_underwriting_run", broken_save)
    res_db_fail = submit_application_and_underwrite(
        app_model, staged_uploads=[], allow_duplicate=True
    )
    assert res_db_fail["audit_persisted"] is False
    assert "readonly database" in (res_db_fail["audit_error"] or "")
    assert res_db_fail["decision"].recommendation == DecisionOutcome.MANUAL_REVIEW


def test_results_context_exposes_consistency_conflicts_and_invalid_doc_fields():
    """Verify normalized results context preserves consistency conflicts & invalid doc flags faithfully."""
    elig = EligibilityResult(
        applicant_id="APP-CON-UI",
        status=EligibilityStatus.ELIGIBLE,
        eligible=True,
        passed_rules=["MIN_CREDIT_SCORE"],
    )
    risk = RiskResult(
        applicant_id="APP-CON-UI",
        risk_score=18.0,
        risk_category=RiskLevel.LOW,
        method="ML_RANDOM_FOREST",
        model_version="v2",
    )
    doc_pkg = DocumentPackageResult(
        applicant_id="APP-CON-UI",
        package_dir="/tmp/none",
        is_complete=True,
        processing_status="completed_with_errors",
        invalid_fields={
            "salary.pdf": [{"field_name": "net_salary", "message": "Negative"}]
        },
    )
    analysis = UnderwritingAnalysisResult(
        application_id="APP-CON-UI",
        applicant_id="APP-CON-UI",
        orchestration_status=OrchestrationStatus.SUCCESS,
        document_result=doc_pkg,
        eligibility_result=elig,
        risk_result=risk,
        anomaly_result=None,
        consistency_conflicts=[
            {
                "conflict_id": "CONFLICT-FRAUD-UNAVAILABLE",
                "severity": "BLOCKING",
                "conflicting_sources": ["FraudAnomalyAgent"],
                "authoritative_source": "FraudAnomalyAgent",
                "description": "Fraud check unavailable",
            }
        ],
        has_unresolved_conflicts=True,
    )
    decision = DecisionReasoningAgent().evaluate(analysis)
    assert decision.recommendation == DecisionOutcome.MANUAL_REVIEW
    assert decision.risk_score == 18.0
    assert decision.fraud_status == "UNAVAILABLE"
    assert decision.document_verification_status == "UNVERIFIED"
    assert len(decision.consistency_conflicts) == 1

    # Save & restore from SQLite
    rid = save_underwriting_run(analysis, decision, execution_time_ms=22.0)
    db_row = get_audit_run_by_id(rid)
    assert db_row is not None
    assert (
        db_row["consistency_conflicts"][0]["conflict_id"]
        == "CONFLICT-FRAUD-UNAVAILABLE"
    )
    assert db_row["details_snapshot"]["fraud_status"] == "UNAVAILABLE"


# ==============================================================================
# 5. END-TO-END STREAMLIT APPTEST USER JOURNEY & RERUN SAFETY
# ==============================================================================


def test_streamlit_apptest_full_intake_submission_and_navigation():
    """Drive actual Streamlit UI widgets via AppTest: intake -> submit -> inspect across all pages."""
    at = AppTest.from_file(str(PROJECT_ROOT / "app" / "main.py")).run(timeout=20)
    assert not at.exception

    # Navigate to New Application
    at.sidebar.radio(key="sidebar_nav_radio").set_value("New Application").run(
        timeout=20
    )
    assert not at.exception

    # Fill valid Applicant schema fields using widget keys
    at.text_input(key="intake_field_applicant_id").set_value("APP-APPTEST-101")
    at.text_input(key="intake_field_name").set_value("Priya Verma")
    at.number_input(key="intake_field_age").set_value(33)
    at.selectbox(key="intake_field_employment_type").set_value("Salaried")
    at.number_input(key="intake_field_employment_years").set_value(5.0)
    at.number_input(key="intake_field_monthly_income").set_value(95000.0)
    at.number_input(key="intake_field_existing_emi").set_value(0.0)
    at.number_input(key="intake_field_bank_balance").set_value(180000.0)
    at.number_input(key="intake_field_loan_amount").set_value(350000.0)
    at.number_input(key="intake_field_loan_tenure").set_value(36)
    at.number_input(key="intake_field_credit_score").set_value(755)
    at.run(timeout=20)
    assert not at.exception

    # Submit application through actual button -> runs orchestrator + decision + SQLite audit
    at.button(key="btn_submit_underwriting").click().run(timeout=25)
    assert not at.exception

    # Verify DB persistence occurred strictly once
    saved_app = get_submitted_application("APP-APPTEST-101")
    assert saved_app is not None
    assert saved_app["name"] == "Priya Verma"
    assert saved_app["existing_emi"] == 0.0
    runs = get_applicant_run_history("APP-APPTEST-101")
    assert len(runs) == 1
    run_id = runs[0]["run_id"]
    # Without PDF uploads, fail-closed policy must NOT auto-approve
    assert runs[0]["recommendation"] == "MANUAL_REVIEW"

    # Trigger an arbitrary rerun (no button press) -> must NOT duplicate underwriting run
    at.run(timeout=20)
    assert not at.exception
    assert len(get_applicant_run_history("APP-APPTEST-101")) == 1
    assert len(list_submitted_applications()) == 1

    # Navigate cleanly through Results, Applications, Application Details, Document Review, Dashboard, Audit History
    for page in (
        "Underwriting Results",
        "Applications",
        "Application Details",
        "Document Review",
        "Dashboard",
        "Audit History",
    ):
        at.sidebar.radio(key="sidebar_nav_radio").set_value(page).run(timeout=20)
        assert not at.exception, f"Page '{page}' raised exception: {at.exception}"

    # Verify Audit History queries the persisted run cleanly
    filtered = get_audit_runs(application_id="APP-APPTEST-101")
    assert len(filtered) == 1
    assert filtered[0]["run_id"] == run_id

    # Verify Audit History filter widget renders matching row cleanly without crashing
    at.text_input(key="audit_filter_app").set_value("APP-APPTEST-101").run(timeout=20)
    assert not at.exception
    assert len(at.dataframe) >= 1


def test_streamlit_apptest_unavailable_risk_and_fraud_rendering():
    """Verify UI renders Unavailable/UNAVAILABLE cleanly instead of 0.0 or NONE when agents fail."""
    failed_analysis = UnderwritingAnalysisResult(
        application_id="APP-UI-UNAVAIL",
        applicant_id="APP-UI-UNAVAIL",
        orchestration_status=OrchestrationStatus.FAILED,
        eligibility_result=None,
        risk_result=None,
        anomaly_result=None,
        error_message="Simulated model + detector outage",
        agent_statuses={
            "risk_agent": AgentExecutionStatus(
                agent_name="risk_agent",
                status=AgentStatus.FAILED,
                success=False,
                output_available=False,
                error="Missing model",
            ),
            "anomaly_agent": AgentExecutionStatus(
                agent_name="anomaly_agent",
                status=AgentStatus.FAILED,
                success=False,
                output_available=False,
                error="Detector down",
            ),
        },
    )
    decision = DecisionReasoningAgent().evaluate(failed_analysis)
    rid = save_underwriting_run(failed_analysis, decision, execution_time_ms=12.0)

    at = AppTest.from_file(str(PROJECT_ROOT / "app" / "main.py"))
    at.session_state["ui_current_page"] = "Underwriting Results"
    at.session_state["ui_selected_run_id"] = rid
    # Seed a submitted app record matching APP-UI-UNAVAIL so selector picks it
    app_rec = _make_clean_applicant(app_id="APP-UI-UNAVAIL")
    from app.database.applications import save_submitted_application

    save_submitted_application(app_rec, application_status="FAILED", latest_run_id=rid)
    at.session_state["ui_selected_app_id"] = "APP-UI-UNAVAIL"
    at.run(timeout=20)
    assert not at.exception

    # Confirm Risk Score shows 'Unavailable' and never '0.0 / 100' or '0.0/100'
    metric_deltas = [m.delta for m in at.metric]
    metric_values = [m.value for m in at.metric]
    assert any("Unavailable" in str(d) for d in metric_deltas)
    assert "0.0 / 100" not in " ".join(str(v) for v in metric_values + metric_deltas)
    assert "UNAVAILABLE" in " ".join(str(v) for v in metric_values)
