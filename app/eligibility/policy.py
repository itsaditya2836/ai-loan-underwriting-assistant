"""Centralized Underwriting Eligibility Policy.

Defines configurable thresholds, bounds, and criteria for deterministic
loan eligibility evaluation.
"""

from typing import List

from pydantic import BaseModel, Field


class EligibilityPolicy(BaseModel):
    """Centralized, configurable underwriting eligibility policy."""

    policy_version: str = Field(
        default="eligibility_policy_v1",
        description="Semantic or identifier version of the eligibility policy",
    )
    min_age: int = Field(
        default=21,
        ge=18,
        description="Minimum applicant age permitted at application time",
    )
    max_age: int = Field(
        default=65,
        le=100,
        description="Maximum applicant age permitted at application time",
    )
    min_monthly_income: float = Field(
        default=30000.0,
        ge=0.0,
        description="Minimum declared/verified monthly net income (in INR)",
    )
    allowed_employment_types: List[str] = Field(
        default_factory=lambda: [
            "SALARIED",
            "SELF_EMPLOYED",
            "BUSINESS_OWNER",
        ],
        description="Permitted employment classifications for loan issuance",
    )
    min_loan_amount: float = Field(
        default=50000.0,
        ge=1000.0,
        description="Minimum permissible loan request amount (in INR)",
    )
    max_loan_amount: float = Field(
        default=5000000.0,
        description="Maximum permissible loan request amount (in INR)",
    )
    min_loan_tenure_months: int = Field(
        default=12,
        ge=1,
        description="Minimum permissible loan duration in months",
    )
    max_loan_tenure_months: int = Field(
        default=240,
        description="Maximum permissible loan duration in months",
    )
    min_credit_score: int = Field(
        default=650,
        ge=300,
        le=900,
        description="Minimum bureau credit score required for baseline eligibility",
    )
    max_dti_ratio: float = Field(
        default=60.0,
        ge=0.0,
        le=100.0,
        description="Maximum Debt-to-Income / FOIR ratio (percentage)",
    )
    min_confidence_threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Minimum extraction confidence required for critical eligibility fields",
    )
    required_document_types: List[str] = Field(
        default_factory=lambda: [
            "loan_application",
            "identity_verification",
            "bank_statement",
        ],
        description="Core mandatory document types required across all applicant profiles",
    )
    critical_fields: List[str] = Field(
        default_factory=lambda: [
            "applicant_id",
            "applicant_name",
            "age",
            "employment_type",
            "monthly_income",
            "credit_score",
            "loan_amount",
            "loan_tenure",
        ],
        description="Required fields whose absence triggers REVIEW_REQUIRED",
    )

    @classmethod
    def default_policy(cls) -> "EligibilityPolicy":
        """Instantiate policy with default regulatory and risk thresholds."""
        return cls()
