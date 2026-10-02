"""Automated Unit and Integration Tests for Stage 7 Multi-Agent Orchestrator."""

from unittest.mock import MagicMock

import pytest

from app.agents.document_agent import DocumentIntakeAgent
from app.agents.fraud_agent import FraudAnomalyAgent
from app.agents.orchestrator import OrchestratorAgent
from app.agents.risk_agent import RiskAgent
from app.orchestration.orchestrator import UnderwritingOrchestrator
from app.schemas.anomaly import AnomalySeverity
from app.schemas.applicant import Applicant, EligibilityStatus, RiskLevel
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
