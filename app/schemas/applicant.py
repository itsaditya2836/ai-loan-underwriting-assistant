"""Pydantic data schemas for applicant and agent inter-communication.

Defines structured data contracts for:
- Applicant profiles
- Documents
- Eligibility check results
- Risk assessment findings
- Anomaly / fraud flags
- Final AI decision recommendations
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EmploymentType(str, Enum):
    """Permitted applicant employment categories."""

    SALARIED = "Salaried"
    SELF_EMPLOYED = "Self-Employed"
    BUSINESS_OWNER = "Business Owner"
    OTHER = "Other"


class RecommendationType(str, Enum):
    """Categorical recommendation outputs for loan decisioning."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class RiskLevel(str, Enum):
    """Categorical risk tiers."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Applicant(BaseModel):
    """Structured representation of a loan applicant.

    Excludes sensitive personally identifiable information (PII)
    in compliance with data minimization best practices.
    """

    applicant_id: str = Field(..., description="Unique applicant identifier")
    name: str = Field(..., description="Applicant full name")
    age: int = Field(..., ge=18, le=100, description="Applicant age in years")
    employment_type: str = Field(
        ..., description="Type of employment (e.g. Salaried, Self-Employed)"
    )
    employment_years: float = Field(
        ..., ge=0.0, description="Total years of employment / business operation"
    )
    monthly_income: float = Field(
        ..., ge=0.0, description="Net monthly verifiable income"
    )
    existing_emi: float = Field(
        default=0.0, ge=0.0, description="Total ongoing monthly debt obligations / EMI"
    )
    loan_amount: float = Field(
        ..., gt=0.0, description="Requested principal loan amount"
    )
    loan_tenure: int = Field(..., gt=0, description="Requested loan tenure in months")
    credit_score: int = Field(
        ..., ge=300, le=900, description="Bureau credit score (e.g. CIBIL/FICO range)"
    )
    bank_balance: float = Field(
        default=0.0, ge=0.0, description="Average verifiable bank balance"
    )


class Document(BaseModel):
    """Metadata and extracted payload for an uploaded applicant document."""

    document_id: str = Field(..., description="Unique document identifier")
    applicant_id: Optional[str] = Field(
        default=None, description="Associated applicant ID if resolved"
    )
    document_type: str = Field(
        ...,
        description="Type of document (e.g., salary_slip, bank_statement, id_proof)",
    )
    file_path: str = Field(..., description="File system or storage location path")
    uploaded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC upload timestamp",
    )
    status: str = Field(
        default="pending", description="Processing status (pending, processed, failed)"
    )
    extracted_text: Optional[str] = Field(
        default=None, description="Raw OCR or extracted text content"
    )
    extracted_fields: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured key-value pairs extracted from document",
    )


class EligibilityResult(BaseModel):
    """Structured output from the Eligibility Agent."""

    is_eligible: bool = Field(
        ..., description="Binary indicator of rule-based eligibility"
    )
    passed_rules: List[str] = Field(
        default_factory=list, description="List of rule codes or descriptions passed"
    )
    failed_rules: List[str] = Field(
        default_factory=list, description="List of rule codes or descriptions failed"
    )
    max_eligible_amount: Optional[float] = Field(
        default=None, description="Maximum loan amount permitted by policy calculations"
    )
    dti_ratio: Optional[float] = Field(
        default=None, description="Calculated Debt-to-Income ratio (percentage)"
    )
    remarks: Optional[str] = Field(
        default=None, description="Detailed explanatory observations"
    )


class RiskResult(BaseModel):
    """Structured output from the Risk Assessment Agent."""

    risk_score: Optional[float] = Field(
        default=None, ge=0.0, le=100.0, description="Normalized risk score (0-100)"
    )
    risk_level: Optional[RiskLevel] = Field(
        default=None, description="Categorized risk tier: LOW, MEDIUM, or HIGH"
    )
    risk_factors: List[str] = Field(
        default_factory=list,
        description="Identified risk factors contributing to score",
    )
    model_version: Optional[str] = Field(
        default=None, description="Identifier of the risk model/rule set used"
    )
    remarks: Optional[str] = Field(
        default=None, description="Detailed risk assessment notes"
    )


class AnomalyResult(BaseModel):
    """Structured output from the Fraud and Anomaly Detection Agent."""

    has_anomalies: bool = Field(
        default=False, description="Flag indicating if any anomalies were detected"
    )
    anomalies_detected: List[str] = Field(
        default_factory=list,
        description="Descriptions of inconsistencies found across documents",
    )
    confidence_score: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Model or heuristic confidence score"
    )
    flagged_items: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Detailed flagged inconsistencies with context",
    )
    remarks: Optional[str] = Field(
        default=None,
        description="Summary observations regarding application authenticity",
    )


class DecisionResult(BaseModel):
    """Structured synthesis output from the Decision & Reasoning Agent."""

    recommendation: RecommendationType = Field(
        ..., description="Decision recommendation: APPROVE, REJECT, or MANUAL_REVIEW"
    )
    confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Confidence in the recommendation"
    )
    reasoning: List[str] = Field(
        default_factory=list,
        description="Explainable rationale points supporting the decision",
    )
    summary: Optional[str] = Field(
        default=None, description="Synthesized executive summary for the loan officer"
    )
    requires_manual_review: bool = Field(
        default=True,
        description="Always true for human-in-the-loop decision-support architecture",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of decision generation",
    )
