"""Tests for Fraud foundation, AnomalyDetector, and cross-system foundation."""

import pytest

from app.agents.decision_agent import DecisionReasoningAgent
from app.agents.fraud_agent import FraudAnomalyAgent
from app.agents.orchestrator import OrchestratorAgent
from app.database.db import get_database_connection
from app.fraud.anomaly_detection import AnomalyDetector
from app.schemas.applicant import (
    AnomalyResult,
    Applicant,
    DecisionResult,
    EligibilityResult,
    RecommendationType,
    RiskResult,
)
from config.settings import get_settings


@pytest.fixture
def sample_applicant() -> Applicant:
    """Fixture providing a standard valid Applicant instance."""
    return Applicant(
        applicant_id="app_003",
        name="Morgan Smith",
        age=45,
        employment_type="Salaried",
        employment_years=12.0,
        monthly_income=120000.0,
        existing_emi=30000.0,
        loan_amount=2000000.0,
        loan_tenure=84,
        credit_score=810,
        bank_balance=400000.0,
    )


def test_anomaly_result_schema():
    """Verify AnomalyResult schema validation."""
    result = AnomalyResult(
        has_anomalies=False,
        anomalies_detected=[],
        confidence_score=0.95,
        remarks="No cross-document inconsistencies detected.",
    )
    assert result.has_anomalies is False
    assert len(result.anomalies_detected) == 0


def test_fraud_agent_placeholder(sample_applicant: Applicant):
    """Verify FraudAnomalyAgent can be initialized and raises NotImplementedError."""
    agent = FraudAnomalyAgent()
    assert agent is not None

    with pytest.raises(NotImplementedError, match="Stage 6"):
        agent.detect(sample_applicant, [])


def test_anomaly_detector_placeholder(sample_applicant: Applicant):
    """Verify AnomalyDetector can be initialized and raises NotImplementedError."""
    detector = AnomalyDetector()
    with pytest.raises(NotImplementedError):
        detector.detect_inconsistencies(sample_applicant, [])


def test_decision_agent_placeholder(sample_applicant: Applicant):
    """Verify DecisionReasoningAgent can be initialized and raises NotImplementedError."""
    agent = DecisionReasoningAgent()
    assert agent is not None

    eligibility = EligibilityResult(is_eligible=True)
    risk = RiskResult()
    anomaly = AnomalyResult()

    with pytest.raises(NotImplementedError, match="Stage 7"):
        agent.decide(sample_applicant, eligibility, risk, anomaly)


def test_orchestrator_placeholder(sample_applicant: Applicant):
    """Verify OrchestratorAgent can be initialized and raises NotImplementedError."""
    orchestrator = OrchestratorAgent()
    assert orchestrator is not None

    with pytest.raises(NotImplementedError, match="Stage 7"):
        orchestrator.run_pipeline(sample_applicant, [])


def test_decision_result_schema():
    """Verify DecisionResult schema defaults and types."""
    decision = DecisionResult(
        recommendation=RecommendationType.APPROVE,
        confidence=0.92,
        reasoning=["All policy criteria passed", "Low risk profile"],
        summary="Applicant strongly qualifies for requested facility.",
    )
    assert decision.recommendation == RecommendationType.APPROVE
    assert decision.requires_manual_review is True  # Enforces human-in-the-loop


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
