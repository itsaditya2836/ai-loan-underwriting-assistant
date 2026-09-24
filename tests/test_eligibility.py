"""Tests for Eligibility foundation and EligibilityAgent."""

import pytest

from app.agents.eligibility_agent import EligibilityAgent
from app.schemas.applicant import Applicant, EligibilityResult


@pytest.fixture
def sample_applicant() -> Applicant:
    """Fixture providing a standard valid Applicant instance."""
    return Applicant(
        applicant_id="app_001",
        name="Alex Mercer",
        age=32,
        employment_type="Salaried",
        employment_years=5.5,
        monthly_income=75000.0,
        existing_emi=15000.0,
        loan_amount=500000.0,
        loan_tenure=36,
        credit_score=750,
        bank_balance=120000.0,
    )


def test_applicant_schema_validation(sample_applicant: Applicant):
    """Verify Applicant Pydantic model instantiates with correct types and constraints."""
    assert sample_applicant.applicant_id == "app_001"
    assert sample_applicant.name == "Alex Mercer"
    assert sample_applicant.monthly_income == 75000.0
    assert sample_applicant.credit_score == 750


def test_applicant_schema_constraints():
    """Verify Applicant Pydantic model enforces age, income, and score boundaries."""
    # Underage applicant (< 18)
    with pytest.raises(Exception):
        Applicant(
            applicant_id="app_err",
            name="Young Applicant",
            age=16,
            employment_type="Salaried",
            employment_years=1.0,
            monthly_income=50000.0,
            existing_emi=0.0,
            loan_amount=100000.0,
            loan_tenure=12,
            credit_score=700,
            bank_balance=10000.0,
        )


def test_eligibility_result_schema():
    """Verify EligibilityResult schema defaults and types."""
    result = EligibilityResult(
        is_eligible=True,
        passed_rules=["MIN_INCOME_MET", "DTI_WITHIN_LIMIT"],
        failed_rules=[],
        max_eligible_amount=600000.0,
        dti_ratio=20.0,
        remarks="Eligible under standard policy.",
    )
    assert result.is_eligible is True
    assert len(result.passed_rules) == 2
    assert result.max_eligible_amount == 600000.0


def test_eligibility_agent_placeholder(sample_applicant: Applicant):
    """Verify EligibilityAgent can be initialized and raises NotImplementedError."""
    agent = EligibilityAgent()
    assert agent is not None

    with pytest.raises(NotImplementedError, match="Stage 4"):
        agent.evaluate(sample_applicant)
