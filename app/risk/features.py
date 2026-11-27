"""Risk Feature Engineering and Amortization Calculation.

Delegates extraction, ordering, validation, and missing-value policy to the
authoritative RiskFeatureContract in app/risk/feature_contract.py.
"""

from typing import Any, Dict, List, Mapping, Optional, Union

from app.risk.feature_contract import (
    DEFAULT_ANNUAL_INTEREST_RATE,
    FEATURE_CONTRACT_VERSION,
    RISK_FEATURE_CONTRACT,
    RISK_FEATURE_NAMES,
    FeatureSpec,
    FeatureValidationError,
    RiskFeatureContract,
    calculate_emi,
    normalize_target_to_dict,
)
from app.schemas.applicant import Applicant, DocumentPackageResult


def get_feature_names() -> List[str]:
    """Return the canonical ordered list of risk feature column names."""
    return list(RISK_FEATURE_CONTRACT.feature_names)


def extract_features(
    target: Union[Applicant, DocumentPackageResult, Mapping[str, Any]],
    annual_rate: float = DEFAULT_ANNUAL_INTEREST_RATE,
) -> Dict[str, Optional[float]]:
    """Extract, validate, and normalize risk features using RISK_FEATURE_CONTRACT."""
    return RISK_FEATURE_CONTRACT.extract(target, annual_rate=annual_rate)


__all__ = [
    "DEFAULT_ANNUAL_INTEREST_RATE",
    "FEATURE_CONTRACT_VERSION",
    "FeatureSpec",
    "FeatureValidationError",
    "RISK_FEATURE_CONTRACT",
    "RISK_FEATURE_NAMES",
    "RiskFeatureContract",
    "calculate_emi",
    "extract_features",
    "get_feature_names",
    "normalize_target_to_dict",
]
