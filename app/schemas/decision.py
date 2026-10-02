"""Pydantic schemas for the Stage 8 Decision & Reasoning Agent.

Defines structured data contracts for:
- DecisionOutcome: Public categorical underwriting recommendations (APPROVE, REJECT, MANUAL_REVIEW).
- DecisionReason: Machine-readable reason with code, evidence, and originating agent.
- DecisionReasoningResult: Comprehensive explainable synthesis of multi-agent underwriting analysis.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class DecisionOutcome(str, Enum):
    """Permitted final underwriting recommendation outcomes."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class DecisionReason(BaseModel):
    """Machine-readable, traceable reason supporting a decision recommendation."""

    code: str = Field(
        ...,
        description="Standardized reason code (e.g. DEC-ELIG-FAIL, DEC-RISK-BORDER, DEC-ANOM-ID)",
    )
    category: str = Field(
        ...,
        description="Analytical domain: ELIGIBILITY, RISK, ANOMALY, DOCUMENT, or SYSTEM",
    )
    severity: str = Field(
        default="INFO",
        description="Impact tier of the reason: INFO, WARNING, or BLOCKING",
    )
    description: str = Field(
        ..., description="Clear human-readable explanation of the finding"
    )
    evidence: Optional[str] = Field(
        default=None,
        description="Specific documentary excerpt or numerical evidence citation",
    )
    source_agent: str = Field(
        ...,
        description="Originating analytical agent (e.g. EligibilityAgent, RiskAgent)",
    )


class DecisionReasoningResult(BaseModel):
    """Comprehensive explainable underwriting synthesis from the Decision & Reasoning Agent.

    Synthesizes findings across Document Intelligence, Underwriting Eligibility,
    Risk Assessment, and Fraud/Anomaly Detection into a transparent recommendation.
    Always maintains a human-in-the-loop notice: the AI recommendation does not
    replace authorized human loan officer approval.
    """

    application_id: str = Field(
        ..., description="Unique application or applicant identifier"
    )
    applicant_id: str = Field(..., description="Applicant identifier")
    recommendation: DecisionOutcome = Field(
        ..., description="Final recommendation: APPROVE, REJECT, or MANUAL_REVIEW"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Evidence completeness and analytical agreement score (0-100 scale)",
    )
    human_review_required: bool = Field(
        default=True,
        description="True for human-in-the-loop decision-support governance",
    )
    requires_manual_review: bool = Field(
        default=True,
        description="Backward-compatible alias for human_review_required",
    )
    reasons: List[DecisionReason] = Field(
        default_factory=list,
        description="Structured, code-indexed reasons supporting the recommendation",
    )
    positive_factors: List[str] = Field(
        default_factory=list,
        description="Key credit-positive factors and protective indicators",
    )
    negative_factors: List[str] = Field(
        default_factory=list,
        description="Key adverse indicators, debt burdens, or inconsistencies",
    )
    blocking_factors: List[str] = Field(
        default_factory=list,
        description="Policy or verification hurdles preventing automated approval",
    )
    supporting_evidence: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Granular entity and citation evidence collected from agents",
    )
    summary: str = Field(
        default="",
        description="Executive underwriting narrative synthesizing all agent findings",
    )
    policy_version: str = Field(
        default="decision_policy_v1",
        description="Centralized decision policy version identifier",
    )
    reasoning_version: str = Field(
        default="reasoning_v1",
        description="Version identifier of the decision synthesis engine",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the decision recommendation was generated",
    )

    @model_validator(mode="before")
    @classmethod
    def sync_aliases(cls, data: Any) -> Any:
        """Synchronize field aliases for seamless interoperability."""
        if isinstance(data, dict):
            if "application_id" in data and "applicant_id" not in data:
                data["applicant_id"] = data["application_id"]
            elif "applicant_id" in data and "application_id" not in data:
                data["application_id"] = data["applicant_id"]

            if "decision" in data and "recommendation" not in data:
                data["recommendation"] = data["decision"]
            elif "recommendation" in data and "decision" not in data:
                data["decision"] = data["recommendation"]

            if "reasoning_summary" in data and "summary" not in data:
                data["summary"] = data["reasoning_summary"]
            elif "summary" in data and "reasoning_summary" not in data:
                data["reasoning_summary"] = data["summary"]

            if "human_review_required" in data and "requires_manual_review" not in data:
                data["requires_manual_review"] = data["human_review_required"]
            elif (
                "requires_manual_review" in data and "human_review_required" not in data
            ):
                data["human_review_required"] = data["requires_manual_review"]
        return data

    @property
    def decision(self) -> DecisionOutcome:
        """Convenience property for recommendation."""
        return self.recommendation

    @property
    def reasoning_summary(self) -> str:
        """Convenience property for narrative summary."""
        return self.summary


__all__ = [
    "DecisionOutcome",
    "DecisionReason",
    "DecisionReasoningResult",
]
