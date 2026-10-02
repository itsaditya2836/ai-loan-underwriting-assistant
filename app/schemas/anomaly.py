"""Pydantic schemas for cross-document fraud and anomaly detection.

Defines structured data contracts for:
- AnomalySeverity: Categorical severity classification tiers.
- AnomalyFlag: Granular cross-document inconsistency findings.
- AnomalyResult: Comprehensive agent output detailing scores, evidence, and missing documents.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class AnomalySeverity(str, Enum):
    """Categorical severity tiers for detected anomalies and inconsistencies."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AnomalyFlag(BaseModel):
    """Structured record of an individual cross-document discrepancy or anomaly."""

    rule_id: str = Field(..., description="Unique rule identifier (e.g. ANOM-ID-001)")
    anomaly_type: str = Field(
        ...,
        description="Categorical anomaly type (NAME_MISMATCH, INCOME_MISMATCH, UNDISCLOSED_LIABILITY, BALANCE_MISMATCH, EMPLOYER_MISMATCH)",
    )
    severity: AnomalySeverity = Field(
        ..., description="Assigned severity tier: LOW, MEDIUM, or HIGH"
    )
    description: str = Field(
        ..., description="Human-readable explanation of the detected discrepancy"
    )
    expected_value: Any = Field(
        default=None,
        description="Declared applicant attribute or benchmark expectation",
    )
    observed_value: Any = Field(
        default=None,
        description="Verified value extracted from supporting documentation",
    )
    source_documents: List[str] = Field(
        default_factory=list,
        description="Filenames or document types exhibiting the inconsistency",
    )
    evidence: str = Field(
        default="",
        description="Documentary excerpt or reference establishing the discrepancy",
    )


class AnomalyResult(BaseModel):
    """Comprehensive evaluation result from the Fraud & Anomaly Detection Agent."""

    applicant_id: str = Field(default="", description="Target applicant identifier")
    anomaly_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Normalized anomaly score (0-100; 0=clean/consistent, 100=severe inconsistencies)",
    )
    severity: AnomalySeverity = Field(
        default=AnomalySeverity.NONE,
        description="Overall composite severity: NONE, LOW, MEDIUM, or HIGH",
    )
    has_anomalies: bool = Field(
        default=False,
        description="Binary indicator: True if any material discrepancies are detected",
    )
    flags: List[AnomalyFlag] = Field(
        default_factory=list,
        description="Granular anomaly flags detailing specific cross-document discrepancies",
    )
    anomalies_detected: List[str] = Field(
        default_factory=list,
        description="Legacy alias: textual list of detected anomaly descriptions",
    )
    flagged_items: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Legacy alias: list of dictionaries detailing flagged inconsistencies",
    )
    missing_evidence: List[str] = Field(
        default_factory=list,
        description="Expected document types absent from submission (tracked separately from anomalies)",
    )
    confidence_score: Optional[float] = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Detector confidence based on available evidence completeness",
    )
    summary: str = Field(
        default="",
        description="Transparent synthesized summary of cross-document findings",
    )
    remarks: Optional[str] = Field(
        default=None,
        description="Legacy alias for summary / authenticity observations",
    )
    detector_version: str = Field(
        default="anomaly_detector_v1",
        description="Version identifier of the anomaly detection rule set and logic",
    )

    @model_validator(mode="before")
    @classmethod
    def sync_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Sync summary and remarks
            if "remarks" in data and "summary" not in data:
                data["summary"] = data["remarks"]
            elif "summary" in data and "remarks" not in data:
                data["remarks"] = data["summary"]

            # Sync flags and anomalies_detected
            if "flags" in data and data["flags"]:
                if "anomalies_detected" not in data or not data["anomalies_detected"]:
                    data["anomalies_detected"] = [
                        (
                            f.description
                            if hasattr(f, "description")
                            else str(f.get("description", ""))
                        )
                        for f in data["flags"]
                    ]
                if "flagged_items" not in data or not data["flagged_items"]:
                    data["flagged_items"] = [
                        f.model_dump() if hasattr(f, "model_dump") else dict(f)
                        for f in data["flags"]
                    ]
                if "has_anomalies" not in data:
                    data["has_anomalies"] = len(data["flags"]) > 0
            elif "anomalies_detected" in data and data["anomalies_detected"]:
                if "has_anomalies" not in data:
                    data["has_anomalies"] = len(data["anomalies_detected"]) > 0

        return data
