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

from pydantic import BaseModel, Field, model_validator


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
    BORDERLINE = "BORDERLINE"


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


class EligibilityStatus(str, Enum):
    """Categorical eligibility status outcomes."""

    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class RuleStatus(str, Enum):
    """Evaluation status for an individual eligibility rule."""

    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class EligibilityRuleResult(BaseModel):
    """Structured evaluation result for a single eligibility rule."""

    rule_id: str = Field(
        ..., description="Unique identifier for the rule (e.g. MIN_AGE)"
    )
    rule_name: str = Field(..., description="Human-readable rule name")
    status: RuleStatus = Field(
        ..., description="Evaluation outcome: PASS, FAIL, or REVIEW_REQUIRED"
    )
    actual_value: Any = Field(default=None, description="Actual observed value")
    expected_value: Any = Field(
        default=None, description="Expected threshold or permissible range"
    )
    passed: bool = Field(
        default=False, description="Convenience flag: True if status is PASS"
    )
    severity: str = Field(
        default="MANDATORY",
        description="Rule severity tier: MANDATORY or ADVISORY",
    )
    reason: str = Field(..., description="Clear explanation of evaluation result")
    evidence: Optional[str] = Field(
        default=None, description="Documentary or textual evidence citation"
    )
    source_document: Optional[str] = Field(
        default=None, description="Source document filename or identifier"
    )
    page_number: Optional[int] = Field(
        default=None, description="1-indexed page number containing evidence"
    )


class EligibilityResult(BaseModel):
    """Structured output from the Eligibility Agent."""

    applicant_id: str = Field(default="", description="Target applicant identifier")
    status: EligibilityStatus = Field(
        default=EligibilityStatus.REVIEW_REQUIRED,
        description="Overall eligibility status: ELIGIBLE, INELIGIBLE, or REVIEW_REQUIRED",
    )
    eligible: bool = Field(
        default=False,
        description="Binary indicator of eligibility (True only if status == ELIGIBLE)",
    )
    is_eligible: bool = Field(
        default=False,
        description="Legacy alias for eligible",
    )
    rules_evaluated: List[str] = Field(
        default_factory=list,
        description="List of all rule IDs evaluated",
    )
    rules_passed: List[str] = Field(
        default_factory=list,
        description="List of rule IDs that passed",
    )
    rules_failed: List[str] = Field(
        default_factory=list,
        description="List of rule IDs that failed",
    )
    rules_requiring_review: List[str] = Field(
        default_factory=list,
        description="List of rule IDs requiring manual review",
    )
    passed_rules: List[str] = Field(
        default_factory=list,
        description="Legacy alias for rules_passed",
    )
    failed_rules: List[str] = Field(
        default_factory=list,
        description="Legacy alias for rules_failed",
    )
    rule_results: List[EligibilityRuleResult] = Field(
        default_factory=list,
        description="Granular result details for each evaluated rule",
    )
    reasons: List[str] = Field(
        default_factory=list,
        description="Summary explanations for the eligibility determination",
    )
    evidence: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Structured citations and evidence for evaluated rules",
    )
    policy_version: str = Field(
        default="eligibility_policy_v1",
        description="Version identifier of the eligibility policy applied",
    )
    max_eligible_amount: Optional[float] = Field(
        default=None,
        description="Maximum loan amount permitted by policy calculations",
    )
    dti_ratio: Optional[float] = Field(
        default=None,
        description="Calculated Debt-to-Income ratio (percentage)",
    )
    remarks: Optional[str] = Field(
        default=None,
        description="Detailed explanatory observations",
    )

    @model_validator(mode="before")
    @classmethod
    def sync_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Sync is_eligible and eligible
            if "is_eligible" in data and "eligible" not in data:
                data["eligible"] = bool(data["is_eligible"])
                if "status" not in data:
                    data["status"] = (
                        EligibilityStatus.ELIGIBLE
                        if data["is_eligible"]
                        else EligibilityStatus.INELIGIBLE
                    )
            elif "eligible" in data and "is_eligible" not in data:
                data["is_eligible"] = bool(data["eligible"])
            elif "status" in data:
                st = data["status"]
                if isinstance(st, str):
                    st = st.upper()
                is_el = (
                    st == EligibilityStatus.ELIGIBLE
                    or st == "ELIGIBLE"
                    or (hasattr(st, "value") and st.value == "ELIGIBLE")
                )
                if "eligible" not in data:
                    data["eligible"] = is_el
                if "is_eligible" not in data:
                    data["is_eligible"] = is_el

            # Sync rules_passed and passed_rules
            if "passed_rules" in data and "rules_passed" not in data:
                data["rules_passed"] = list(data["passed_rules"])
            elif "rules_passed" in data and "passed_rules" not in data:
                data["passed_rules"] = list(data["rules_passed"])

            # Sync rules_failed and failed_rules
            if "failed_rules" in data and "rules_failed" not in data:
                data["rules_failed"] = list(data["failed_rules"])
            elif "rules_failed" in data and "failed_rules" not in data:
                data["failed_rules"] = list(data["rules_failed"])
        return data


class RiskResult(BaseModel):
    """Structured output from the Risk Assessment Agent."""

    applicant_id: str = Field(default="", description="Target applicant identifier")
    risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Normalized risk score (0-100; higher score indicates higher modeled risk)",
    )
    risk_category: RiskLevel = Field(
        default=RiskLevel.MEDIUM,
        description="Categorized risk tier: LOW, MEDIUM, HIGH, or BORDERLINE",
    )
    risk_level: Optional[RiskLevel] = Field(
        default=None,
        description="Legacy alias for risk_category",
    )
    risk_factors: List[str] = Field(
        default_factory=list,
        description="Identified adverse financial/credit risk factors contributing to score",
    )
    protective_factors: List[str] = Field(
        default_factory=list,
        description="Identified favorable financial attributes mitigating risk",
    )
    features_used: Dict[str, Any] = Field(
        default_factory=dict,
        description="Feature values input to the risk model for evaluation",
    )
    feature_importance: Dict[str, float] = Field(
        default_factory=dict,
        description="Model-level feature importance or coefficient weights",
    )
    model_version: str = Field(
        default="risk_model_v1",
        description="Identifier and version of the risk model applied",
    )
    method: str = Field(
        default="ML_RANDOM_FOREST",
        description="Methodology used: ML_RANDOM_FOREST, BASELINE_WEIGHTED, etc.",
    )
    explanation: str = Field(
        default="",
        description="Comprehensive synthesized explanation of the risk assessment",
    )
    evidence: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Quantitative and documentary evidence citations",
    )
    remarks: Optional[str] = Field(
        default=None,
        description="Legacy alias for explanation / summary observations",
    )

    @model_validator(mode="before")
    @classmethod
    def sync_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Sync risk_level and risk_category
            if "risk_level" in data and "risk_category" not in data:
                data["risk_category"] = data["risk_level"]
            elif "risk_category" in data and "risk_level" not in data:
                data["risk_level"] = data["risk_category"]

            # Sync remarks and explanation
            if "remarks" in data and "explanation" not in data:
                data["explanation"] = data["remarks"]
            elif "explanation" in data and "remarks" not in data:
                data["remarks"] = data["explanation"]
        return data


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


class ExtractedField(BaseModel):
    """Traceable extracted entity with provenance, confidence, and source evidence."""

    field_name: str = Field(..., description="Canonical entity/attribute name")
    value: Any = Field(..., description="Extracted and normalized field value")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Deterministic extraction confidence score"
    )
    source_document: str = Field(
        ..., description="Filename or identifier of the originating document"
    )
    page_number: int = Field(
        default=1, ge=1, description="1-indexed document page number of evidence"
    )
    evidence: str = Field(
        ..., description="Exact textual excerpt or line supporting extraction"
    )


class ClassifiedDocument(BaseModel):
    """Processed document metadata, classification, and extracted structured fields."""

    document_id: str = Field(..., description="Unique document identifier")
    file_path: str = Field(..., description="Physical filesystem path of document")
    document_type: str = Field(
        ...,
        description="Classified document type (e.g. loan_application, salary_slip, bank_statement)",
    )
    classification_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence of document type classification"
    )
    classification_evidence: str = Field(
        ..., description="Keywords or structural markers identifying document type"
    )
    is_scanned: bool = Field(
        default=False,
        description="Indicates if document was rasterized/scanned requiring OCR",
    )
    page_count: int = Field(default=1, ge=1, description="Total number of pages")
    raw_text: str = Field(
        default="", description="Full extracted text (direct PDF or OCR)"
    )
    extracted_fields: Dict[str, ExtractedField] = Field(
        default_factory=dict,
        description="Mapping of field names to ExtractedField records",
    )


class DocumentPackageResult(BaseModel):
    """Comprehensive package-level intelligence result for an applicant's document folder."""

    applicant_id: str = Field(..., description="Applicant identifier")
    package_dir: str = Field(..., description="Directory path containing documents")
    documents_found: List[ClassifiedDocument] = Field(
        default_factory=list, description="List of successfully ingested documents"
    )
    documents_missing: List[str] = Field(
        default_factory=list,
        description="List of expected document types absent from the package",
    )
    expected_documents: List[str] = Field(
        default_factory=list,
        description="List of required document types based on employment profile",
    )
    is_complete: bool = Field(
        default=False,
        description="True if all expected documents are present and successfully processed",
    )
    ocr_used: bool = Field(
        default=False,
        description="Indicates whether OCR was triggered for any document in package",
    )
    processing_status: str = Field(
        default="completed", description="Overall intake status (completed, failed)"
    )
    processing_errors: List[str] = Field(
        default_factory=list,
        description="Non-fatal warnings or processing error messages",
    )
    all_extracted_fields: Dict[str, ExtractedField] = Field(
        default_factory=dict,
        description="Flat aggregated key-value map of all extracted fields across documents",
    )
