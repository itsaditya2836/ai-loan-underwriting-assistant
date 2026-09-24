"""Tests for Risk foundation, RiskAgent, and risk modules."""

import pytest

from app.agents.risk_agent import RiskAgent
from app.risk.risk_model import MLRiskModel
from app.risk.rules import RiskRulesEngine
from app.risk.scoring import RiskScorer
from app.schemas.applicant import Applicant, RiskLevel, RiskResult


@pytest.fixture
def sample_applicant() -> Applicant:
    """Fixture providing a standard valid Applicant instance."""
    return Applicant(
        applicant_id="app_002",
        name="Jordan Lee",
        age=28,
        employment_type="Self-Employed",
        employment_years=3.0,
        monthly_income=90000.0,
        existing_emi=20000.0,
        loan_amount=1000000.0,
        loan_tenure=60,
        credit_score=780,
        bank_balance=250000.0,
    )


def test_risk_result_schema():
    """Verify RiskResult schema instantiation and validation."""
    result = RiskResult(
        risk_score=24.5,
        risk_level=RiskLevel.LOW,
        risk_factors=["Self-employed profile"],
        model_version="rule_v1",
        remarks="Low probability of default.",
    )
    assert result.risk_score == 24.5
    assert result.risk_level == RiskLevel.LOW
    assert len(result.risk_factors) == 1


def test_risk_agent_placeholder(sample_applicant: Applicant):
    """Verify RiskAgent can be initialized and raises NotImplementedError."""
    agent = RiskAgent()
    assert agent is not None

    with pytest.raises(NotImplementedError, match="Stage 5"):
        agent.assess(sample_applicant)


def test_risk_subcomponents(sample_applicant: Applicant):
    """Verify RiskRulesEngine, RiskScorer, and MLRiskModel placeholders."""
    engine = RiskRulesEngine()
    scorer = RiskScorer()
    ml_model = MLRiskModel()

    with pytest.raises(NotImplementedError):
        engine.evaluate_rules(sample_applicant)

    with pytest.raises(NotImplementedError):
        scorer.calculate_score(sample_applicant)

    with pytest.raises(NotImplementedError):
        ml_model.predict_default_probability(sample_applicant)
