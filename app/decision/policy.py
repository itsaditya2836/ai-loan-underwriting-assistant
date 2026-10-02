"""Centralized Underwriting Decision Policy Configuration.

Defines configurable thresholds, precedence rules, and governance parameters
governing multi-agent decision synthesis.
"""

from typing import Dict, List, Set

from pydantic import BaseModel, Field

from app.schemas.anomaly import AnomalySeverity
from app.schemas.applicant import EligibilityStatus, RiskLevel
from app.schemas.decision import DecisionOutcome


class DecisionPolicy(BaseModel):
    """Centralized policy configuration for the Decision & Reasoning Agent."""

    policy_version: str = Field(
        default="decision_policy_v1",
        description="Version identifier of the decisioning policy",
    )
    permitted_approval_risk_tiers: List[RiskLevel] = Field(
        default_factory=lambda: [RiskLevel.LOW, RiskLevel.MEDIUM],
        description="Risk tiers permissible for automated APPROVE recommendation",
    )
    borderline_risk_action: DecisionOutcome = Field(
        default=DecisionOutcome.MANUAL_REVIEW,
        description="Action for applicants assessed in the BORDERLINE risk category",
    )
    high_risk_action: DecisionOutcome = Field(
        default=DecisionOutcome.REJECT,
        description="Action for applicants assessed in the HIGH risk category",
    )
    min_confidence_for_approval: float = Field(
        default=70.0,
        ge=0.0,
        le=100.0,
        description="Minimum evidence completeness confidence required for an APPROVE recommendation",
    )
    tolerated_anomaly_severities_for_approval: Set[AnomalySeverity] = Field(
        default_factory=lambda: {AnomalySeverity.NONE, AnomalySeverity.LOW},
        description="Anomaly severity levels that do not block an APPROVE recommendation",
    )
    blocking_anomaly_severities: Set[AnomalySeverity] = Field(
        default_factory=lambda: {AnomalySeverity.HIGH, AnomalySeverity.MEDIUM},
        description="Anomaly severities that mandate human underwriter MANUAL_REVIEW",
    )
    mandatory_eligibility_status_for_approval: EligibilityStatus = Field(
        default=EligibilityStatus.ELIGIBLE,
        description="Required Stage 4 status for an APPROVE recommendation",
    )
    enforce_complete_documents: bool = Field(
        default=True,
        description="If True, missing required documents block APPROVE and require MANUAL_REVIEW",
    )

    @classmethod
    def default_policy(cls) -> "DecisionPolicy":
        """Instantiate standard production underwriting decision policy."""
        return cls()


# Standard reason code constants
REASON_CODES: Dict[str, Dict[str, str]] = {
    "DEC-SYS-001": {
        "category": "SYSTEM",
        "severity": "BLOCKING",
        "description": "Pipeline execution failed or was aborted; manual verification required.",
    },
    "DEC-SYS-002": {
        "category": "SYSTEM",
        "severity": "WARNING",
        "description": "Pipeline completed with partial success; one or more analytical agents failed.",
    },
    "DEC-DOC-001": {
        "category": "DOCUMENT",
        "severity": "BLOCKING",
        "description": "Mandatory document evidence missing; complete verification cannot be performed.",
    },
    "DEC-DOC-002": {
        "category": "DOCUMENT",
        "severity": "INFO",
        "description": "All required application and supporting documents are present and verified.",
    },
    "DEC-ELIG-001": {
        "category": "ELIGIBILITY",
        "severity": "BLOCKING",
        "description": "Applicant is INELIGIBLE due to failure of mandatory underwriting policy rules.",
    },
    "DEC-ELIG-002": {
        "category": "ELIGIBILITY",
        "severity": "WARNING",
        "description": "Underwriting eligibility requires manual review under configured policy.",
    },
    "DEC-ELIG-003": {
        "category": "ELIGIBILITY",
        "severity": "INFO",
        "description": "All underwriting eligibility policy criteria are satisfied.",
    },
    "DEC-RISK-001": {
        "category": "RISK",
        "severity": "WARNING",
        "description": "Assessed credit risk is BORDERLINE; requires human credit underwriter review.",
    },
    "DEC-RISK-002": {
        "category": "RISK",
        "severity": "BLOCKING",
        "description": "Assessed credit risk profile is HIGH, exceeding acceptable lending tolerance.",
    },
    "DEC-RISK-003": {
        "category": "RISK",
        "severity": "INFO",
        "description": "Assessed repayment risk profile is within acceptable policy limits.",
    },
    "DEC-ANOM-001": {
        "category": "ANOMALY",
        "severity": "BLOCKING",
        "description": "High-severity cross-document identity or evidence inconsistency detected.",
    },
    "DEC-ANOM-002": {
        "category": "ANOMALY",
        "severity": "WARNING",
        "description": "Material cross-document discrepancy detected; human verification required.",
    },
    "DEC-ANOM-003": {
        "category": "ANOMALY",
        "severity": "INFO",
        "description": "No suspicious cross-document anomalies or discrepancies detected.",
    },
    "DEC-APP-001": {
        "category": "SYNTHESIS",
        "severity": "INFO",
        "description": "Application satisfies all eligibility, risk, consistency, and documentation criteria for approval.",
    },
}

__all__ = ["DecisionPolicy", "REASON_CODES"]
