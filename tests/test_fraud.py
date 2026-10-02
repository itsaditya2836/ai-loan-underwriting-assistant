"""Tests for Stage 6 Fraud & Anomaly Detection Agent, Rules, Scorer, and Schemas."""

import os

import pytest

from app.agents.decision_agent import DecisionReasoningAgent
from app.agents.document_agent import DocumentIntakeAgent
from app.agents.fraud_agent import FraudAnomalyAgent
from app.agents.orchestrator import OrchestratorAgent
from app.database.db import get_database_connection
from app.fraud.anomaly_detection import AnomalyDetector
from app.fraud.detectors import CrossDocumentAnomalyDetector
from app.fraud.rules import (
    calculate_name_similarity,
    normalize_string,
)
from app.fraud.scoring import AnomalyScorer
from app.schemas.anomaly import AnomalyFlag, AnomalyResult, AnomalySeverity
from app.schemas.applicant import (
    Applicant,
    DecisionResult,
    DocumentPackageResult,
    EligibilityResult,
    RecommendationType,
    RiskResult,
)
from config.settings import get_settings

DOCUMENTS_DIR = os.path.join("data", "documents")


@pytest.fixture
def sample_applicant() -> Applicant:
    """Fixture providing a standard valid Applicant instance."""
    return Applicant(
        applicant_id="APP0001",
        name="Harish Chauhan",
        age=45,
        employment_type="Salaried",
        employment_years=12.0,
        monthly_income=37500.0,
        existing_emi=16000.0,
        loan_amount=500000.0,
        loan_tenure=36,
        credit_score=680,
        bank_balance=140000.0,
    )


@pytest.fixture
def intake_agent() -> DocumentIntakeAgent:
    """Fixture providing DocumentIntakeAgent."""
    return DocumentIntakeAgent()


@pytest.fixture
def fraud_agent() -> FraudAnomalyAgent:
    """Fixture providing FraudAnomalyAgent."""
    return FraudAnomalyAgent()


# ==============================================================================
# SCHEMA & UNIT TESTS
# ==============================================================================


def test_anomaly_result_schema():
    """Verify AnomalyResult schema validation and default fields."""
    result = AnomalyResult(
        applicant_id="APP0001",
        has_anomalies=False,
        anomaly_score=0.0,
        severity=AnomalySeverity.NONE,
        flags=[],
        missing_evidence=[],
        confidence_score=0.95,
        summary="No cross-document inconsistencies detected.",
    )
    assert result.has_anomalies is False
    assert result.anomaly_score == 0.0
    assert result.severity == AnomalySeverity.NONE
    assert len(result.flags) == 0
    assert len(result.anomalies_detected) == 0  # Sync validator check


def test_anomaly_score_bounds_and_severity():
    """Verify scoring constraints, clamping to [0, 100], and severity tier mapping."""
    scorer = AnomalyScorer()

    # Empty flags -> Score 0, NONE
    score, sev = scorer.calculate_score([])
    assert score == 0.0
    assert sev == AnomalySeverity.NONE
    summary = scorer.synthesize_summary([], [], sev, score)
    assert "consistent" in summary.lower()

    # Single flag with score contribution 25 -> Score 25, LOW
    flag_low = AnomalyFlag(
        rule_id="ANOM-FIN-002",
        anomaly_type="BALANCE_SHORTFALL",
        severity=AnomalySeverity.LOW,
        description="Minor balance discrepancy",
        expected_value="200000.0",
        observed_value="180000.0",
        source_documents=["bank_statement"],
        evidence="Bank balance variance",
    )
    score, sev = scorer.calculate_score([flag_low])
    assert score == 25.0
    assert sev == AnomalySeverity.LOW

    # Flags accumulating to > 100 clamped at 100.0, HIGH
    flag_high1 = AnomalyFlag(
        rule_id="ANOM-ID-001",
        anomaly_type="NAME_MISMATCH",
        severity=AnomalySeverity.HIGH,
        description="Name discrepancy",
        expected_value="Alice",
        observed_value="Bob",
        source_documents=["salary_slip"],
        evidence="Identity mismatch",
    )
    flag_high2 = AnomalyFlag(
        rule_id="ANOM-INC-001",
        anomaly_type="INCOME_MISMATCH",
        severity=AnomalySeverity.HIGH,
        description="Income discrepancy",
        expected_value="100000",
        observed_value="40000",
        source_documents=["salary_slip"],
        evidence="Income mismatch",
    )
    flag_high3 = AnomalyFlag(
        rule_id="ANOM-FIN-001",
        anomaly_type="UNDISCLOSED_LIABILITY",
        severity=AnomalySeverity.HIGH,
        description="Undisclosed EMI",
        expected_value="10000",
        observed_value="35000",
        source_documents=["bank_statement"],
        evidence="EMI debit",
    )
    # Sum of weights: 40 + 35 + 35 = 110 -> clamped to 100.0
    score, sev = scorer.calculate_score([flag_high1, flag_high2, flag_high3])
    assert score == 100.0
    assert sev == AnomalySeverity.HIGH


def test_string_similarity_and_normalization():
    """Verify name normalization and token-based similarity."""
    assert normalize_string("  Dr. Rajesh   Kumar  ") == "DR RAJESH KUMAR"
    assert calculate_name_similarity("Rajesh Kumar", "Rajesh Kumar") == 1.0
    assert (
        calculate_name_similarity("Kumar Rajesh", "Rajesh Kumar") == 1.0
    )  # Token order invariant
    assert calculate_name_similarity("Rajesh Kumar", "Mukesh Kumar") < 0.85
    assert calculate_name_similarity("", "Rajesh") == 0.0


def test_no_duplicate_flags():
    """Verify that detectors produce unique, non-duplicative rule flags per applicant."""
    detector = CrossDocumentAnomalyDetector()
    pkg_dir = os.path.join(DOCUMENTS_DIR, "APP0006")
    intake = DocumentIntakeAgent()
    pkg = intake.process_package("APP0006", pkg_dir)
    res = detector.detect_anomalies(pkg)
    rule_ids = [f.rule_id for f in res.flags]
    assert len(rule_ids) == len(set(rule_ids))


def test_malformed_and_low_confidence_fields():
    """Verify detector handles missing or malformed fields gracefully without crashing."""
    detector = CrossDocumentAnomalyDetector()
    malformed_pkg = DocumentPackageResult(
        applicant_id="APP9999",
        package_dir="data/documents/dummy",
        documents_found=[],
        documents_missing=["loan_application"],
    )
    res = detector.detect_anomalies(malformed_pkg)
    assert res.has_anomalies is False
    assert res.anomaly_score == 0.0
    assert "loan_application" in res.missing_evidence


def test_empty_document_package(sample_applicant: Applicant):
    """Verify graceful handling when an empty DocumentPackageResult is passed."""
    agent = FraudAnomalyAgent()
    empty_pkg = DocumentPackageResult(
        applicant_id=sample_applicant.applicant_id,
        package_dir="data/documents/empty",
        documents_found=[],
        documents_missing=[
            "loan_application",
            "identity_proof",
            "salary_slip",
            "bank_statement",
        ],
    )
    res = agent.detect(empty_pkg)
    assert res.has_anomalies is False
    assert res.anomaly_score == 0.0
    assert res.severity == AnomalySeverity.NONE
    assert len(res.flags) == 0
    assert len(res.missing_evidence) == 4


def test_anomaly_detector_legacy_interface(sample_applicant: Applicant):
    """Verify AnomalyDetector backward-compatible detect_inconsistencies method."""
    detector = AnomalyDetector()
    results = detector.detect_inconsistencies(sample_applicant, [])
    assert isinstance(results, list)
    assert len(results) == 0


# ==============================================================================
# COHORT INTEGRATION TESTS (APP0001 - APP0030)
# ==============================================================================


@pytest.mark.parametrize("app_num", range(1, 6))
def test_cohort_normal_applicants(
    app_num: int, intake_agent: DocumentIntakeAgent, fraud_agent: FraudAnomalyAgent
):
    """APP0001-APP0005: Normal / consistent applicants have no anomalies and no fraud flags."""
    app_id = f"APP{app_num:04d}"
    pkg_dir = os.path.join(DOCUMENTS_DIR, app_id)
    pkg = intake_agent.process_package(app_id, pkg_dir)
    res = fraud_agent.detect(pkg)

    assert res.has_anomalies is False
    assert res.anomaly_score == 0.0
    assert res.severity == AnomalySeverity.NONE
    assert len(res.flags) == 0
    assert len(res.missing_evidence) == 0


@pytest.mark.parametrize("app_num", range(6, 11))
def test_cohort_income_mismatch_applicants(
    app_num: int, intake_agent: DocumentIntakeAgent, fraud_agent: FraudAnomalyAgent
):
    """APP0006-APP0010: Income mismatch cohort triggers ANOM-INC-001 anomaly."""
    app_id = f"APP{app_num:04d}"
    pkg_dir = os.path.join(DOCUMENTS_DIR, app_id)
    pkg = intake_agent.process_package(app_id, pkg_dir)
    res = fraud_agent.detect(pkg)

    assert res.has_anomalies is True
    assert res.anomaly_score > 0.0
    assert any(f.rule_id == "ANOM-INC-001" for f in res.flags)
    # Ensure explainability evidence exists
    income_flag = next(f for f in res.flags if f.rule_id == "ANOM-INC-001")
    assert income_flag.expected_value is not None
    assert income_flag.observed_value is not None
    assert "Income discrepancy" in income_flag.description
    assert len(income_flag.evidence) > 0


@pytest.mark.parametrize("app_num", range(11, 16))
def test_cohort_name_mismatch_applicants(
    app_num: int, intake_agent: DocumentIntakeAgent, fraud_agent: FraudAnomalyAgent
):
    """APP0011-APP0015: Name mismatch cohort triggers ANOM-ID-001 identity anomaly."""
    app_id = f"APP{app_num:04d}"
    pkg_dir = os.path.join(DOCUMENTS_DIR, app_id)
    pkg = intake_agent.process_package(app_id, pkg_dir)
    res = fraud_agent.detect(pkg)

    assert res.has_anomalies is True
    assert res.anomaly_score > 0.0
    assert any(f.rule_id == "ANOM-ID-001" for f in res.flags)
    id_flag = next(f for f in res.flags if f.rule_id == "ANOM-ID-001")
    assert id_flag.expected_value != id_flag.observed_value


@pytest.mark.parametrize("app_num", range(16, 21))
def test_cohort_missing_documents_applicants(
    app_num: int, intake_agent: DocumentIntakeAgent, fraud_agent: FraudAnomalyAgent
):
    """APP0016-APP0020: Missing documents are tracked under missing_evidence, NOT as fraud/anomalies."""
    app_id = f"APP{app_num:04d}"
    pkg_dir = os.path.join(DOCUMENTS_DIR, app_id)
    pkg = intake_agent.process_package(app_id, pkg_dir)
    res = fraud_agent.detect(pkg)

    # Missing documents alone must NOT trigger anomaly flags or fraud classifications
    assert res.has_anomalies is False
    assert res.anomaly_score == 0.0
    assert res.severity == AnomalySeverity.NONE
    assert len(res.flags) == 0
    assert len(res.missing_evidence) >= 1


@pytest.mark.parametrize("app_num", range(21, 26))
def test_cohort_financial_inconsistency_applicants(
    app_num: int, intake_agent: DocumentIntakeAgent, fraud_agent: FraudAnomalyAgent
):
    """APP0021-APP0025: Financial inconsistency cohort triggers ANOM-FIN-001 or ANOM-FIN-002."""
    app_id = f"APP{app_num:04d}"
    pkg_dir = os.path.join(DOCUMENTS_DIR, app_id)
    pkg = intake_agent.process_package(app_id, pkg_dir)
    res = fraud_agent.detect(pkg)

    assert res.has_anomalies is True
    assert res.anomaly_score > 0.0
    assert any(f.rule_id in ["ANOM-FIN-001", "ANOM-FIN-002"] for f in res.flags)


@pytest.mark.parametrize("app_num", range(26, 31))
def test_cohort_borderline_applicants(
    app_num: int, intake_agent: DocumentIntakeAgent, fraud_agent: FraudAnomalyAgent
):
    """APP0026-APP0030: Borderline risk profile is NOT falsely flagged as an anomaly."""
    app_id = f"APP{app_num:04d}"
    pkg_dir = os.path.join(DOCUMENTS_DIR, app_id)
    pkg = intake_agent.process_package(app_id, pkg_dir)
    res = fraud_agent.detect(pkg)

    assert res.has_anomalies is False
    assert res.anomaly_score == 0.0
    assert res.severity == AnomalySeverity.NONE
    assert len(res.flags) == 0
    assert len(res.missing_evidence) == 0


# ==============================================================================
# BOUNDARY & STAGE 7/8 PLACEHOLDER TESTS
# ==============================================================================


def test_decision_agent_execution(sample_applicant: Applicant):
    """Verify DecisionReasoningAgent executes decision synthesis cleanly."""
    agent = DecisionReasoningAgent()
    assert agent is not None

    eligibility = EligibilityResult(is_eligible=True)
    risk = RiskResult()
    anomaly = AnomalyResult()

    result = agent.decide(sample_applicant, eligibility, risk, anomaly)
    assert result.recommendation.value in ["APPROVE", "REJECT", "MANUAL_REVIEW"]
    assert result.confidence >= 0.0


def test_orchestrator_agent_execution(sample_applicant: Applicant):
    """Verify OrchestratorAgent executes the underwriting pipeline."""
    orchestrator = OrchestratorAgent()
    assert orchestrator is not None

    result = orchestrator.run_pipeline(sample_applicant)
    assert result.application_id == sample_applicant.applicant_id
    assert result.orchestration_status.value in ["SUCCESS", "PARTIAL_SUCCESS"]


def test_decision_result_schema():
    """Verify DecisionResult schema defaults and types."""
    decision = DecisionResult(
        recommendation=RecommendationType.APPROVE,
        confidence=0.92,
        reasoning=["All policy criteria passed", "Low risk profile"],
        summary="Applicant strongly qualifies for requested facility.",
    )
    assert decision.recommendation == RecommendationType.APPROVE
    assert decision.requires_manual_review is True


def test_configuration_loading():
    """Verify configuration loads cleanly with default development settings."""
    settings = get_settings()
    assert settings.app_env in ["development", "test", "production"]
    assert "sqlite" in settings.database_url


def test_database_connection():
    """Verify SQLite database connection context manager functions cleanly."""
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 AS alive;")
        row = cursor.fetchone()
        assert row["alive"] == 1
