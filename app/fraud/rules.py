"""Centralized Rule Configuration and Definitions for Anomaly Detection.

Defines configurable thresholds, rule identifiers, weights, and detection
parameters for cross-document consistency checks:
- ANOM-ID-001: Name / Identity mismatch across submitted documents
- ANOM-INC-001: Income mismatch between application and payroll / bank records
- ANOM-FIN-001: Undisclosed recurring liabilities observed in bank statement
- ANOM-FIN-002: Material bank balance discrepancy between declared and statement closing balance
- ANOM-DOC-001: Employer name mismatch between application and salary slip
"""

import re
from typing import Dict, Optional

from pydantic import BaseModel, Field


class AnomalyRulesConfig(BaseModel):
    """Centralized configuration for anomaly detection thresholds and weights."""

    config_version: str = Field(
        default="anomaly_rules_v1",
        description="Version identifier of the anomaly detection policy",
    )
    income_discrepancy_threshold_pct: float = Field(
        default=15.0,
        ge=0.0,
        description="Percentage threshold above which income discrepancies trigger an anomaly flag",
    )
    undisclosed_emi_threshold_inr: float = Field(
        default=2000.0,
        ge=0.0,
        description="Absolute difference (in INR) between bank EMI debits and declared EMI triggering an anomaly",
    )
    balance_discrepancy_threshold_pct: float = Field(
        default=25.0,
        ge=0.0,
        description="Percentage shortfall between declared and closing balance triggering an anomaly",
    )
    balance_discrepancy_min_inr: float = Field(
        default=10000.0,
        ge=0.0,
        description="Minimum absolute shortfall (in INR) required alongside percentage shortfall",
    )
    name_similarity_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Jaccard / Token similarity threshold below which names are flagged as mismatched",
    )
    rule_weights: Dict[str, float] = Field(
        default_factory=lambda: {
            "ANOM-ID-001": 40.0,  # Major identity inconsistency
            "ANOM-INC-001": 35.0,  # Material income mismatch
            "ANOM-FIN-001": 35.0,  # Undisclosed debt liability
            "ANOM-FIN-002": 25.0,  # Bank balance mismatch
            "ANOM-DOC-001": 15.0,  # Employer discrepancy
        },
        description="Point contribution of each rule toward the composite 0-100 anomaly score",
    )

    @classmethod
    def default_config(cls) -> "AnomalyRulesConfig":
        """Instantiate default rules configuration."""
        return cls()


def normalize_string(val: Optional[str]) -> str:
    """Normalize string for robust token and similarity comparisons."""
    if not val:
        return ""
    # Remove punctuation, uppercase, strip extraneous whitespace
    cleaned = re.sub(r"[^\w\s]", " ", val.upper())
    tokens = [t.strip() for t in cleaned.split() if t.strip()]
    return " ".join(tokens)


def calculate_name_similarity(name1: Optional[str], name2: Optional[str]) -> float:
    """Compute token-level similarity between two person names.

    Returns float in [0.0, 1.0].
    """
    n1 = normalize_string(name1)
    n2 = normalize_string(name2)

    if not n1 or not n2:
        return 0.0

    if n1 == n2:
        return 1.0

    tokens1 = set(n1.split())
    tokens2 = set(n2.split())

    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)

    if not union:
        return 0.0

    # Jaccard index on name tokens
    jaccard = len(intersection) / len(union)

    # If first and last name match exactly in different order
    if tokens1 == tokens2:
        return 1.0

    return jaccard
