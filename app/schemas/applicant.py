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

from app.schemas.anomaly import AnomalyFlag, AnomalyResult, AnomalySeverity


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
    monthly_expenses: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Declared monthly living expenses in INR (optional; imputed by risk pipeline if omitted)",
    )
    number_of_dependents: Optional[int] = Field(
        default=None,
        ge=0,
        le=20,
        description="Number of financial dependents (optional; imputed by risk pipeline if omitted)",
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
    """Traceable extracted entity with provenance, confidence, validation, and evidence."""

    field_name: str = Field(..., description="Canonical entity/attribute name")
    value: Any = Field(..., description="Extracted and normalized field value")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Heuristic extraction confidence score"
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
    extraction_method: str = Field(
        default="regex_digital",
        description="Extraction mechanism (regex_digital, regex_ocr, table_parser, header_positional, fallback)",
    )
    validation_status: str = Field(
        default="valid",
        description="Validation state: valid, unverified, invalid, missing, or ambiguous",
    )
    validation_message: Optional[str] = Field(
        default=None,
        description="Explanation when field is invalid, unverified, ambiguous, or missing",
    )
    masked_value: Optional[str] = Field(
        default=None,
        description="Safe masked representation for sensitive identifiers/account numbers",
    )


class ClassifiedDocument(BaseModel):
    """Processed document metadata, classification, page telemetry, and extracted fields."""

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
    classification_status: str = Field(
        default="CLASSIFIED",
        description="Classification outcome: CLASSIFIED, AMBIGUOUS, or UNCLASSIFIED",
    )
    classification_signals: List[str] = Field(
        default_factory=list,
        description="Individual weighted classification signals detected in text",
    )
    is_scanned: bool = Field(
        default=False,
        description="Indicates if document or any page required OCR",
    )
    extraction_method: str = Field(
        default="digital",
        description="Document-level text extraction mode: digital, ocr, hybrid, or failed",
    )
    page_count: int = Field(default=1, ge=1, description="Total number of pages")
    native_text_pages: int = Field(
        default=0,
        ge=0,
        description="Number of pages extracted with native digital text",
    )
    ocr_pages: int = Field(
        default=0, ge=0, description="Number of pages processed via OCR"
    )
    empty_pages: int = Field(
        default=0, ge=0, description="Number of blank or zero-text pages"
    )
    failed_pages: int = Field(
        default=0, ge=0, description="Number of pages that failed extraction"
    )
    raw_text: str = Field(
        default="", description="Full extracted text (direct PDF, OCR, or hybrid)"
    )
    content_sha256: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of source file contents for duplicate detection",
    )
    extracted_fields: Dict[str, ExtractedField] = Field(
        default_factory=dict,
        description="Mapping of usable field names to ExtractedField records",
    )
    field_validations: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict,
        description="Complete field validation audit including valid, unverified, invalid, missing, and ambiguous",
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
        description="Indicates whether OCR was triggered for any document/page in package",
    )
    processing_status: str = Field(
        default="completed",
        description="Overall intake status (completed, completed_with_errors, failed)",
    )
    processing_errors: List[str] = Field(
        default_factory=list,
        description="Non-fatal warnings or processing error messages",
    )
    all_extracted_fields: Dict[str, ExtractedField] = Field(
        default_factory=dict,
        description="Flat aggregated key-value map of all usable extracted fields across documents",
    )
    total_pages: int = Field(
        default=0, ge=0, description="Total pages read across package"
    )
    native_text_pages: int = Field(
        default=0, ge=0, description="Total pages extracted via native PDF text"
    )
    ocr_pages: int = Field(
        default=0, ge=0, description="Total pages extracted via local OCR"
    )
    empty_pages: int = Field(
        default=0, ge=0, description="Total blank/unreadable pages encountered"
    )
    failed_pages: int = Field(
        default=0, ge=0, description="Total pages whose extraction failed"
    )
    unclassified_documents: List[str] = Field(
        default_factory=list,
        description="Filenames that could not be reliably classified into a known document type",
    )
    duplicate_documents: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Detected exact or content-duplicate documents in package",
    )
    field_conflicts: Dict[str, List[Dict[str, Any]]] = Field(
        default_factory=dict,
        description="Conflicting field values preserved across multiple documents in package",
    )
    missing_fields: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Expected document fields not found per classified document",
    )
    invalid_fields: Dict[str, List[Dict[str, Any]]] = Field(
        default_factory=dict,
        description="Fields rejected by field validation per document",
    )
    ambiguous_fields: Dict[str, List[Dict[str, Any]]] = Field(
        default_factory=dict,
        description="Fields with conflicting ambiguous matches within a document",
    )
    security_warnings: List[str] = Field(
        default_factory=list,
        description="Passive security warnings discovered during PDF validation",
    )


__all__ = [
    "EmploymentType",
    "RecommendationType",
    "RiskLevel",
    "Applicant",
    "Document",
    "EligibilityResult",
    "RiskResult",
    "DecisionResult",
    "AnomalyFlag",
    "AnomalyResult",
    "AnomalySeverity",
    "ExtractedField",
    "ClassifiedDocument",
    "DocumentPackageResult",
]
