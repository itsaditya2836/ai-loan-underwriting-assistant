"""Automated Unit and Integration Tests for Stage 7 Multi-Agent Orchestrator."""

from unittest.mock import MagicMock

import pytest

from app.agents.decision_agent import DecisionReasoningAgent
from app.agents.document_agent import DocumentIntakeAgent
from app.agents.fraud_agent import FraudAnomalyAgent
from app.agents.orchestrator import OrchestratorAgent
from app.agents.risk_agent import RiskAgent
from app.orchestration.orchestrator import UnderwritingOrchestrator
from app.schemas.anomaly import AnomalySeverity
from app.schemas.applicant import (
    Applicant,
    DocumentPackageResult,
    EligibilityStatus,
    RiskLevel,
)
from app.schemas.decision import DecisionOutcome
from app.schemas.underwriting import AgentStatus, OrchestrationStatus


@pytest.fixture
def orchestrator() -> UnderwritingOrchestrator:
    """Fixture providing an UnderwritingOrchestrator instance."""
    return UnderwritingOrchestrator()


@pytest.fixture
def orchestrator_agent() -> OrchestratorAgent:
    """Fixture providing an OrchestratorAgent facade instance."""
    return OrchestratorAgent()


# ==============================================================================
# COHORT INTEGRATION TESTS
# ==============================================================================


def test_orchestrator_normal_applicant(orchestrator: UnderwritingOrchestrator):
    """Test 1: APP0001 Normal applicant coordinates all 4 agents with clean success."""
    result = orchestrator.process("APP0001")

    assert result.application_id == "APP0001"
    assert result.orchestration_status == OrchestrationStatus.SUCCESS
    assert result.document_result is not None
    assert result.eligibility_result is not None
    assert result.risk_result is not None
    assert result.anomaly_result is not None

    # Verify agent execution statuses
    assert len(result.agent_statuses) == 4
    for st in result.agent_statuses.values():
        assert st.status == AgentStatus.SUCCESS
        assert st.duration_ms is not None and st.duration_ms >= 0.0

    # Clean anomaly findings
    assert result.anomaly_result.has_anomalies is False
    assert result.anomaly_result.anomaly_score == 0.0
    assert result.anomaly_result.severity == AnomalySeverity.NONE

    # Verify Stage 8 boundary: No final decision recommendation
    assert not hasattr(result, "decision_result")
    assert not hasattr(result, "recommendation")
    assert "Stage 8" in result.summary


def test_orchestrator_income_mismatch(orchestrator: UnderwritingOrchestrator):
    """Test 2: APP0006 Income mismatch detected while risk and eligibility remain independent."""
    result = orchestrator.process("APP0006")

    assert result.application_id == "APP0006"
    assert result.orchestration_status == OrchestrationStatus.SUCCESS

    # Anomaly agent flags income mismatch
    assert result.anomaly_result is not None
    assert result.anomaly_result.has_anomalies is True
    assert any(f.rule_id == "ANOM-INC-001" for f in result.anomaly_result.flags)

    # Eligibility and risk remain independent
    assert result.eligibility_result is not None
    assert result.eligibility_result.status == EligibilityStatus.ELIGIBLE
    assert result.risk_result is not None
    assert result.risk_result.risk_category == RiskLevel.LOW


def test_orchestrator_name_mismatch(orchestrator: UnderwritingOrchestrator):
    """Test 3: APP0011 Name mismatch anomaly identified and preserved in unified result."""
    result = orchestrator.process("APP0011")

    assert result.application_id == "APP0011"
    assert result.orchestration_status == OrchestrationStatus.SUCCESS
    assert result.anomaly_result is not None
    assert result.anomaly_result.has_anomalies is True
    assert any(f.rule_id == "ANOM-ID-001" for f in result.anomaly_result.flags)

    # Anomaly evidence is preserved
    id_flag = next(f for f in result.anomaly_result.flags if f.rule_id == "ANOM-ID-001")
    assert id_flag.expected_value != id_flag.observed_value


def test_orchestrator_missing_document(orchestrator: UnderwritingOrchestrator):
    """Test 4: APP0016 Missing document tracked as incomplete evidence, not fraud."""
    result = orchestrator.process("APP0016")

    assert result.application_id == "APP0016"
    assert result.orchestration_status == OrchestrationStatus.SUCCESS

    # Document intelligence records missing evidence
    assert result.document_result is not None
    assert "bank_statement" in result.document_result.documents_missing

    # Eligibility routes to review/ineligible according to policy
    assert result.eligibility_result is not None
    assert result.eligibility_result.status in [
        EligibilityStatus.REVIEW_REQUIRED,
        EligibilityStatus.INELIGIBLE,
    ]

    # Crucial: Missing document is NOT flagged as an anomaly or fraud
    assert result.anomaly_result is not None
    assert result.anomaly_result.has_anomalies is False
    assert result.anomaly_result.anomaly_score == 0.0
    assert "bank_statement" in result.anomaly_result.missing_evidence


def test_orchestrator_financial_inconsistency(orchestrator: UnderwritingOrchestrator):
    """Test 5: APP0021 Financial inconsistency detected and aggregated alongside risk result."""
    result = orchestrator.process("APP0021")

    assert result.application_id == "APP0021"
    assert result.orchestration_status == OrchestrationStatus.SUCCESS

    # Anomaly flag present
    assert result.anomaly_result is not None
    assert result.anomaly_result.has_anomalies is True
    assert any(
        f.rule_id in ["ANOM-FIN-001", "ANOM-FIN-002"]
        for f in result.anomaly_result.flags
    )

    # Risk result intact and unmodified
    assert result.risk_result is not None
    assert result.risk_result.risk_score > 0.0


def test_orchestrator_borderline_applicant(orchestrator: UnderwritingOrchestrator):
    """Test 6: APP0026 Borderline risk category is not falsely converted into an anomaly."""
    result = orchestrator.process("APP0026")

    assert result.application_id == "APP0026"
    assert result.orchestration_status == OrchestrationStatus.SUCCESS

    # Risk category is borderline
    assert result.risk_result is not None
    assert result.risk_result.risk_category == RiskLevel.BORDERLINE

    # Anomaly detector clean: borderline credit is not an anomaly
    assert result.anomaly_result is not None
    assert result.anomaly_result.has_anomalies is False
    assert result.anomaly_result.anomaly_score == 0.0


# ==============================================================================
# FAILURE INJECTION & RESILIENCE TESTS
# ==============================================================================


def test_orchestrator_missing_applicant(orchestrator: UnderwritingOrchestrator):
    """Verify non-existent applicant produces structured FAILED status without crashing."""
    result = orchestrator.process("APP9999")

    assert result.application_id == "APP9999"
    assert result.orchestration_status == OrchestrationStatus.FAILED
    assert result.error_message is not None
    assert "not found" in result.error_message.lower()
    assert result.document_result is None
    assert result.eligibility_result is None
    assert result.risk_result is None
    assert result.anomaly_result is None


def test_orchestrator_risk_agent_failure_isolation():
    """Verify simulated RiskAgent failure preserves other agent findings in PARTIAL_SUCCESS."""
    failing_risk_agent = MagicMock(spec=RiskAgent)
    failing_risk_agent.assess.side_effect = RuntimeError(
        "Risk scoring service timeout."
    )

    orch = UnderwritingOrchestrator(risk_agent=failing_risk_agent)
    result = orch.process("APP0001")

    # Pipeline completes with PARTIAL_SUCCESS
    assert result.orchestration_status == OrchestrationStatus.PARTIAL_SUCCESS
    assert result.risk_result is None
    assert result.agent_statuses["risk_agent"].status == AgentStatus.FAILED
    assert "timeout" in (result.agent_statuses["risk_agent"].error or "")

    # Independent agents succeeded
    assert result.document_result is not None
    assert result.agent_statuses["document_agent"].status == AgentStatus.SUCCESS
    assert result.eligibility_result is not None
    assert result.agent_statuses["eligibility_agent"].status == AgentStatus.SUCCESS
    assert result.anomaly_result is not None
    assert result.agent_statuses["anomaly_agent"].status == AgentStatus.SUCCESS


def test_orchestrator_anomaly_agent_failure_isolation():
    """Verify simulated AnomalyAgent failure produces PARTIAL_SUCCESS without fabricated flags."""
    failing_anomaly_agent = MagicMock(spec=FraudAnomalyAgent)
    failing_anomaly_agent.detect.side_effect = ValueError("Corrupt extraction tensor.")

    orch = UnderwritingOrchestrator(fraud_agent=failing_anomaly_agent)
    result = orch.process("APP0001")

    assert result.orchestration_status == OrchestrationStatus.PARTIAL_SUCCESS
    assert result.anomaly_result is None
    assert result.agent_statuses["anomaly_agent"].status == AgentStatus.FAILED

    # Other agents succeeded cleanly
    assert result.document_result is not None
    assert result.eligibility_result is not None
    assert result.risk_result is not None


def test_orchestrator_document_agent_failure_isolation():
    """Verify simulated DocumentIntakeAgent failure falls back to applicant data where possible."""
    failing_doc_agent = MagicMock(spec=DocumentIntakeAgent)
    failing_doc_agent.process_package.side_effect = IOError("Corrupt PDF file header.")

    orch = UnderwritingOrchestrator(document_agent=failing_doc_agent)
    result = orch.process("APP0001")

    assert result.orchestration_status == OrchestrationStatus.PARTIAL_SUCCESS
    assert result.document_result is None
    assert result.agent_statuses["document_agent"].status == AgentStatus.FAILED

    # Downstream agents fall back to applicant profile and still execute
    assert result.risk_result is not None
    assert result.agent_statuses["risk_agent"].status == AgentStatus.SUCCESS
    assert result.eligibility_result is not None
    assert result.agent_statuses["eligibility_agent"].status == AgentStatus.SUCCESS


# ==============================================================================
# DETERMINISM & FACADE TESTS
# ==============================================================================


def test_orchestrator_deterministic_execution(orchestrator: UnderwritingOrchestrator):
    """Verify executing pipeline twice on the same applicant produces identical analytical results."""
    run1 = orchestrator.process("APP0006")
    run2 = orchestrator.process("APP0006")

    assert run1.orchestration_status == run2.orchestration_status

    # Eligibility equivalence
    assert run1.eligibility_result is not None and run2.eligibility_result is not None
    assert run1.eligibility_result.status == run2.eligibility_result.status
    assert run1.eligibility_result.rules_passed == run2.eligibility_result.rules_passed

    # Risk equivalence
    assert run1.risk_result is not None and run2.risk_result is not None
    assert run1.risk_result.risk_score == run2.risk_result.risk_score
    assert run1.risk_result.risk_category == run2.risk_result.risk_category

    # Anomaly equivalence and flag ordering
    assert run1.anomaly_result is not None and run2.anomaly_result is not None
    assert run1.anomaly_result.anomaly_score == run2.anomaly_result.anomaly_score
    assert run1.anomaly_result.severity == run2.anomaly_result.severity
    assert len(run1.anomaly_result.flags) == len(run2.anomaly_result.flags)
    assert [f.rule_id for f in run1.anomaly_result.flags] == [
        f.rule_id for f in run2.anomaly_result.flags
    ]


def test_orchestrator_agent_facade(orchestrator_agent: OrchestratorAgent):
    """Verify OrchestratorAgent facade exposes both process() and run_pipeline() methods."""
    res_process = orchestrator_agent.process("APP0001")
    assert res_process.application_id == "APP0001"
    assert res_process.orchestration_status == OrchestrationStatus.SUCCESS

    # Test run_pipeline with pre-loaded Applicant model
    applicant = Applicant(
        applicant_id="APP0002",
        name="Satish Singh",
        age=51,
        employment_type="Salaried",
        employment_years=6.5,
        monthly_income=105000.0,
        existing_emi=21000.0,
        loan_amount=400000.0,
        loan_tenure=120,
        credit_score=695,
        bank_balance=385000.0,
    )
    res_pipeline = orchestrator_agent.run_pipeline(applicant)
    assert res_pipeline.application_id == "APP0002"
    assert res_pipeline.orchestration_status == OrchestrationStatus.SUCCESS


# ==============================================================================
# FALLBACK & MISSING-DOCUMENT REGRESSION TESTS (STAGE 1)
# ==============================================================================


def test_regression_valid_complete_document_package(
    orchestrator: UnderwritingOrchestrator,
):
    """Case 1: Applicant with complete valid documents passes via document extraction."""
    analysis = orchestrator.process("APP0002")
    decision = DecisionReasoningAgent().evaluate(analysis)

    assert analysis.orchestration_status == OrchestrationStatus.SUCCESS
    assert analysis.document_result is not None
    assert analysis.document_result.is_complete is True
    assert analysis.eligibility_result is not None
    assert analysis.eligibility_result.status == EligibilityStatus.ELIGIBLE
    assert decision.recommendation == DecisionOutcome.APPROVE


def test_regression_missing_required_documents_preserved(
    orchestrator: UnderwritingOrchestrator,
):
    """Case 2: Applicant with partial package preserves missing docs and routes to review."""
    analysis = orchestrator.process("APP0016")
    decision = DecisionReasoningAgent().evaluate(analysis)

    assert analysis.orchestration_status == OrchestrationStatus.SUCCESS
    assert analysis.document_result is not None
    assert "bank_statement" in analysis.document_result.documents_missing
    assert analysis.eligibility_result is not None
    assert analysis.eligibility_result.status == EligibilityStatus.REVIEW_REQUIRED
    assert "DOCUMENTS_COMPLETE" in analysis.eligibility_result.rules_requiring_review
    assert analysis.anomaly_result is not None
    assert "bank_statement" in analysis.anomaly_result.missing_evidence
    assert decision.recommendation == DecisionOutcome.MANUAL_REVIEW


def test_regression_no_document_directory_qualifying_profile(
    orchestrator: UnderwritingOrchestrator,
):
    """Case 3: Applicant with no document folder evaluates profile rules yet requires docs."""
    analysis = orchestrator.process("APP0031")
    decision = DecisionReasoningAgent().evaluate(analysis)

    assert analysis.orchestration_status == OrchestrationStatus.PARTIAL_SUCCESS
    assert analysis.agent_statuses["document_agent"].status == AgentStatus.FAILED
    assert analysis.agent_statuses["eligibility_agent"].status == AgentStatus.SUCCESS
    assert analysis.document_result is not None
    assert len(analysis.document_result.documents_missing) > 0

    elig = analysis.eligibility_result
    assert elig is not None
    assert elig.status == EligibilityStatus.REVIEW_REQUIRED
    assert elig.rules_failed == []
    assert elig.rules_requiring_review == ["DOCUMENTS_COMPLETE"]
    assert "MIN_CREDIT_SCORE" in elig.rules_passed
    assert "MIN_MONTHLY_INCOME" in elig.rules_passed
    assert decision.recommendation == DecisionOutcome.MANUAL_REVIEW
    assert any(r.code == "DEC-DOC-001" for r in decision.reasons)


def test_regression_failed_or_empty_document_package_fallback():
    """Case 4: Empty/failed DocumentPackageResult falls back to Applicant without hiding missing docs."""
    empty_failed_pkg = DocumentPackageResult(
        applicant_id="APP0002",
        package_dir="data/documents/APP0002",
        documents_found=[],
        documents_missing=[],
        expected_documents=[
            "loan_application",
            "identity_proof",
            "salary_slip",
            "bank_statement",
        ],
        is_complete=False,
        processing_status="failed",
        processing_errors=["Simulated unreadable PDF package"],
        all_extracted_fields={},
    )
    mock_doc_agent = MagicMock(spec=DocumentIntakeAgent)
    mock_doc_agent.process_package.return_value = empty_failed_pkg

    orch = UnderwritingOrchestrator(document_agent=mock_doc_agent)
    analysis = orch.process("APP0002")
    decision = DecisionReasoningAgent().evaluate(analysis)

    assert analysis.orchestration_status == OrchestrationStatus.PARTIAL_SUCCESS
    assert analysis.eligibility_result is not None
    assert analysis.eligibility_result.status == EligibilityStatus.REVIEW_REQUIRED
    assert "DOCUMENTS_COMPLETE" in analysis.eligibility_result.rules_requiring_review
    assert "MIN_CREDIT_SCORE" in analysis.eligibility_result.rules_passed
    assert decision.recommendation == DecisionOutcome.MANUAL_REVIEW
    assert any(r.code == "DEC-DOC-001" for r in decision.reasons)


def test_regression_document_agent_exception_qualifying_profile():
    """DocumentIntakeAgent exception must still block auto-approval and require review."""
    failing_doc_agent = MagicMock(spec=DocumentIntakeAgent)
    failing_doc_agent.process_package.side_effect = IOError("Disk read failure")

    orch = UnderwritingOrchestrator(document_agent=failing_doc_agent)
    analysis = orch.process("APP0002")
    decision = DecisionReasoningAgent().evaluate(analysis)

    assert analysis.orchestration_status == OrchestrationStatus.PARTIAL_SUCCESS
    assert analysis.eligibility_result is not None
    assert analysis.eligibility_result.status == EligibilityStatus.REVIEW_REQUIRED
    assert "DOCUMENTS_COMPLETE" in analysis.eligibility_result.rules_requiring_review
    assert decision.recommendation == DecisionOutcome.MANUAL_REVIEW


def test_regression_disqualifying_profile_without_documents(
    orchestrator: UnderwritingOrchestrator,
):
    """Case 5: Disqualifying profile without docs must evaluate INELIGIBLE (not REVIEW_REQUIRED)."""
    analysis = orchestrator.process("APP0040")
    decision = DecisionReasoningAgent().evaluate(analysis)

    assert analysis.document_result is not None
    assert len(analysis.document_result.documents_missing) > 0
    assert analysis.eligibility_result is not None
    assert analysis.eligibility_result.status == EligibilityStatus.INELIGIBLE
    assert "MIN_CREDIT_SCORE" in analysis.eligibility_result.rules_failed
    assert "DOCUMENTS_COMPLETE" in analysis.eligibility_result.rules_requiring_review
    assert decision.recommendation == DecisionOutcome.REJECT
    assert any(r.code == "DEC-ELIG-001" for r in decision.reasons)

    # Also verify via run_pipeline with zero-EMI, low-income disqualifying profile and no directory
    disqualified = Applicant(
        applicant_id="APP_NO_DOCS_FAIL",
        name="Low Score Applicant",
        age=30,
        employment_type="Salaried",
        employment_years=3.0,
        monthly_income=20000.0,
        existing_emi=0.0,
        loan_amount=300000.0,
        loan_tenure=36,
        credit_score=560,
        bank_balance=10000.0,
    )
    res_custom = orchestrator.run_pipeline(
        disqualified, package_dir="data/documents/APP_DOES_NOT_EXIST"
    )
    assert res_custom.eligibility_result is not None
    assert res_custom.eligibility_result.status == EligibilityStatus.INELIGIBLE
    assert "MIN_CREDIT_SCORE" in res_custom.eligibility_result.rules_failed
    assert "MIN_MONTHLY_INCOME" in res_custom.eligibility_result.rules_failed
    assert res_custom.eligibility_result.dti_ratio == 0.0
    assert "DOCUMENTS_COMPLETE" in res_custom.eligibility_result.rules_requiring_review


# ==============================================================================
# STAGE 4: ORCHESTRATION DEPENDENCY, CONTRACT, AND END-TO-END RELIABILITY TESTS
# ==============================================================================


def test_orchestrator_execution_order_dependency():
    """Verify strict dependency order: Document -> Eligibility -> Fraud -> Risk."""
    from app.agents.document_agent import DocumentIntakeAgent
    from app.agents.eligibility_agent import EligibilityAgent
    from app.agents.fraud_agent import FraudAnomalyAgent
    from app.agents.risk_agent import RiskAgent

    call_order: list[str] = []
    real_doc = DocumentIntakeAgent()
    real_elig = EligibilityAgent()
    real_fraud = FraudAnomalyAgent()
    real_risk = RiskAgent()

    spy_doc = MagicMock()
    spy_doc.process_package.side_effect = lambda *a, **kw: (
        call_order.append("document") or real_doc.process_package(*a, **kw)
    )
    spy_elig = MagicMock()
    spy_elig.evaluate.side_effect = lambda *a, **kw: (
        call_order.append("eligibility") or real_elig.evaluate(*a, **kw)
    )
    spy_fraud = MagicMock()
    spy_fraud.detect.side_effect = lambda *a, **kw: (
        call_order.append("fraud") or real_fraud.detect(*a, **kw)
    )
    spy_risk = MagicMock()
    spy_risk.assess.side_effect = lambda *a, **kw: (
        call_order.append("risk") or real_risk.assess(*a, **kw)
    )

    orch = UnderwritingOrchestrator(
        document_agent=spy_doc,
        eligibility_agent=spy_elig,
        fraud_agent=spy_fraud,
        risk_agent=spy_risk,
    )
    analysis = orch.process("APP0002")

    assert call_order == ["document", "eligibility", "fraud", "risk"]
    assert analysis.orchestration_status == OrchestrationStatus.SUCCESS
    assert analysis.authoritative_sources
    for key in ("document_agent", "eligibility_agent", "anomaly_agent", "risk_agent"):
        assert analysis.agent_statuses[key].success is True
        assert analysis.agent_statuses[key].output_available is True


def test_orchestrator_corrupt_or_invalid_agent_outputs_handled_safely():
    """Verify invalid return types, NaN risk scores, and RiskModelLoadError are contained."""
    from app.risk.risk_model import RiskModelLoadError
    from app.schemas.applicant import RiskLevel, RiskResult

    # Case 1: Wrong return type from RiskAgent
    mock_risk_bad_type = MagicMock()
    mock_risk_bad_type.assess.return_value = "CORRUPT_STRING_OUTPUT"
    res1 = UnderwritingOrchestrator(risk_agent=mock_risk_bad_type).process("APP0002")
    assert res1.orchestration_status == OrchestrationStatus.PARTIAL_SUCCESS
    assert res1.risk_result is None
    assert res1.agent_statuses["risk_agent"].status == AgentStatus.FAILED
    assert res1.agent_statuses["risk_agent"].output_available is False
    assert any(
        c["conflict_id"] == "CONFLICT-RISK-UNAVAILABLE"
        for c in res1.consistency_conflicts
    )

    # Case 2: Non-finite NaN risk_score in RiskResult
    nan_risk = RiskResult.model_construct(
        applicant_id="APP0002",
        risk_score=float("nan"),
        risk_category=RiskLevel.LOW,
        risk_level="LOW",
        risk_factors=[],
        protective_factors=[],
        features_used={},
        feature_importance={},
        model_version="test",
        method="ML_RANDOM_FOREST",
    )
    mock_risk_nan = MagicMock()
    mock_risk_nan.assess.return_value = nan_risk
    res2 = UnderwritingOrchestrator(risk_agent=mock_risk_nan).process("APP0002")
    assert res2.risk_result is None
    assert res2.agent_statuses["risk_agent"].status == AgentStatus.FAILED
    assert res2.agent_statuses["risk_agent"].success is False

    # Case 3: RiskModelLoadError raised during assessment
    mock_risk_err = MagicMock()
    mock_risk_err.assess.side_effect = RiskModelLoadError("Corrupt joblib artifact")
    res3 = UnderwritingOrchestrator(risk_agent=mock_risk_err).process("APP0002")
    assert res3.risk_result is None
    assert res3.agent_statuses["risk_agent"].status == AgentStatus.FAILED
    dec3 = DecisionReasoningAgent().evaluate(res3)
    assert dec3.recommendation == DecisionOutcome.MANUAL_REVIEW
    assert "DEC-RISK-004" in [r.code for r in dec3.reasons]

    # Case 4: EligibilityAgent raises exception & FraudAnomalyAgent returns wrong type
    mock_elig_err = MagicMock()
    mock_elig_err.evaluate.side_effect = RuntimeError("Eligibility crash")
    mock_fraud_bad = MagicMock()
    mock_fraud_bad.detect.return_value = {"invalid": "dict"}
    res4 = UnderwritingOrchestrator(
        eligibility_agent=mock_elig_err, fraud_agent=mock_fraud_bad
    ).process("APP0002")
    assert res4.eligibility_result is None
    assert res4.anomaly_result is None
    assert res4.agent_statuses["eligibility_agent"].status == AgentStatus.FAILED
    assert res4.agent_statuses["anomaly_agent"].status == AgentStatus.FAILED
    conflict_ids = {c["conflict_id"] for c in res4.consistency_conflicts}
    assert "CONFLICT-ELIG-UNAVAILABLE" in conflict_ids
    assert "CONFLICT-FRAUD-UNAVAILABLE" in conflict_ids


def test_orchestrator_applicant_validation_warnings_and_blank_name(
    orchestrator: UnderwritingOrchestrator,
):
    """Verify applicant profile validation catches blank names cleanly and emits non-blocking warnings."""
    from app.schemas.applicant import Applicant

    # Non-blocking warning: high existing_emi > monthly_income
    warn_applicant = Applicant(
        applicant_id="APP_WARN_01",
        name="Warning Profile",
        age=28,
        employment_type="salaried",
        employment_years=4.0,
        monthly_income=40000.0,
        existing_emi=50000.0,
        loan_amount=100000.0,
        loan_tenure=12,
        credit_score=740,
        bank_balance=80000.0,
    )
    res_warn = orchestrator.run_pipeline(
        warn_applicant, package_dir="data/documents/APP_DOES_NOT_EXIST"
    )
    assert res_warn.validation_warnings
    assert any("existing_emi" in w for w in res_warn.validation_warnings)

    # Fatal validation error: whitespace-only name fails cleanly without unhandled exception
    bad_applicant = Applicant(
        applicant_id="APP_BLANK_01",
        name="   ",
        age=30,
        employment_type="salaried",
        employment_years=5.0,
        monthly_income=50000.0,
        existing_emi=0.0,
        loan_amount=100000.0,
        loan_tenure=12,
        credit_score=720,
        bank_balance=50000.0,
    )
    res_bad = orchestrator.run_pipeline(
        bad_applicant, package_dir="data/documents/APP_DOES_NOT_EXIST"
    )
    assert res_bad.orchestration_status == OrchestrationStatus.PARTIAL_SUCCESS
    assert res_bad.agent_statuses["eligibility_agent"].status == AgentStatus.SKIPPED
    assert res_bad.agent_statuses["risk_agent"].status == AgentStatus.SKIPPED
    dec_bad = DecisionReasoningAgent().evaluate(res_bad)
    assert dec_bad.recommendation == DecisionOutcome.MANUAL_REVIEW


def test_orchestrator_execute_end_to_end_and_audit_failure_resilience(
    orchestrator: UnderwritingOrchestrator, tmp_path, monkeypatch
):
    """Verify end-to-end orchestration with isolated DB persistence and safe DB failure containment."""
    import sqlite3

    from app.database.audit import get_audit_run_by_id
    from config.settings import get_settings

    test_db = tmp_path / "e2e_orchestrator_audit.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db}")
    get_settings.cache_clear()

    try:
        analysis, decision = orchestrator.execute_end_to_end(
            "APP0002", persist_audit=True
        )
        assert analysis.orchestration_status == OrchestrationStatus.SUCCESS
        assert decision.recommendation == DecisionOutcome.APPROVE
        assert analysis.audit_persisted is True
        assert analysis.audit_run_id is not None
        assert analysis.audit_persistence_error is None

        persisted = get_audit_run_by_id(analysis.audit_run_id)
        assert persisted is not None
        assert persisted["application_id"] == "APP0002"
        assert persisted["recommendation"] == "APPROVE"
        assert persisted["risk_score_available"] in (1, True)

        # Inject database OperationalError: underwriting results must survive safely
        def failing_save(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr("app.database.audit.save_underwriting_run", failing_save)
        analysis_err, decision_err = orchestrator.execute_end_to_end(
            "APP0002", persist_audit=True
        )
        assert analysis_err.orchestration_status == OrchestrationStatus.SUCCESS
        assert decision_err.recommendation == DecisionOutcome.APPROVE
        assert analysis_err.audit_persisted is False
        assert analysis_err.audit_run_id is None
        assert analysis_err.audit_persistence_error is not None
        assert "database is locked" in analysis_err.audit_persistence_error
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_orchestrator_end_to_end_determinism_stage4(
    orchestrator: UnderwritingOrchestrator,
):
    """Verify repeated end-to-end runs yield byte-for-byte deterministic core decision snapshots."""
    import json

    def _snapshot(app_id: str) -> str:
        analysis, decision = orchestrator.execute_end_to_end(
            app_id, persist_audit=False
        )
        payload = {
            "orchestration_status": analysis.orchestration_status.value,
            "eligibility": (
                {
                    "status": analysis.eligibility_result.status.value,
                    "rules_passed": analysis.eligibility_result.rules_passed,
                    "rules_failed": analysis.eligibility_result.rules_failed,
                    "rules_requiring_review": analysis.eligibility_result.rules_requiring_review,
                }
                if analysis.eligibility_result
                else None
            ),
            "risk": (
                {
                    "category": analysis.risk_result.risk_category.value,
                    "score": analysis.risk_result.risk_score,
                }
                if analysis.risk_result
                else None
            ),
            "anomaly": (
                {
                    "severity": analysis.anomaly_result.severity.value,
                    "score": analysis.anomaly_result.anomaly_score,
                    "flags": [f.rule_id for f in analysis.anomaly_result.flags],
                }
                if analysis.anomaly_result
                else None
            ),
            "consistency_conflicts": analysis.consistency_conflicts,
            "recommendation": decision.recommendation.value,
            "confidence": decision.confidence,
            "reason_codes": [r.code for r in decision.reasons],
            "review_reasons": decision.review_reasons,
            "material_anomalies": decision.material_anomalies,
        }
        return json.dumps(payload, sort_keys=True)

    for app_id in ("APP0002", "APP0006", "APP0016"):
        assert _snapshot(app_id) == _snapshot(app_id)
