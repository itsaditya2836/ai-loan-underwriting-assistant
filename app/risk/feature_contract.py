"""Authoritative Risk Model Feature Contract.

Defines the single source of truth for risk model input features, including:
- Feature names and strict column order
- Data types and business meanings
- Domain bounds and validation rules
- Missing-value handling semantics (error vs. zero default vs. training-fitted imputer)
- Deterministic feature extraction and transformations
- Feature contract version identifier
"""

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from app.schemas.applicant import Applicant, DocumentPackageResult

FEATURE_CONTRACT_VERSION = "risk_features_v2"
DEFAULT_ANNUAL_INTEREST_RATE = 0.105  # 10.5% p.a. benchmark


class FeatureValidationError(ValueError):
    """Raised when input data violates the risk feature contract."""


@dataclass(frozen=True)
class FeatureSpec:
    """Specification for a single risk model feature."""

    name: str
    order: int
    dtype: str
    meaning: str
    required: bool
    missing_policy: str
    transformation: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    strictly_positive: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize feature specification to JSON-compatible dictionary."""
        return {
            "name": self.name,
            "order": self.order,
            "dtype": self.dtype,
            "meaning": self.meaning,
            "required": self.required,
            "missing_policy": self.missing_policy,
            "transformation": self.transformation,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "strictly_positive": self.strictly_positive,
        }


FEATURE_SPECS: Tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="age",
        order=0,
        dtype="float64",
        meaning="Applicant age in years",
        required=True,
        missing_policy="error",
        transformation="direct",
        min_value=18.0,
        max_value=100.0,
    ),
    FeatureSpec(
        name="employment_years",
        order=1,
        dtype="float64",
        meaning="Total years of employment or business operation",
        required=False,
        missing_policy="impute_median",
        transformation="direct",
        min_value=0.0,
    ),
    FeatureSpec(
        name="monthly_income",
        order=2,
        dtype="float64",
        meaning="Net verifiable monthly income in INR",
        required=True,
        missing_policy="error",
        transformation="direct",
        min_value=0.0,
        strictly_positive=True,
    ),
    FeatureSpec(
        name="existing_emi",
        order=3,
        dtype="float64",
        meaning="Ongoing monthly debt EMI obligations in INR",
        required=False,
        missing_policy="default_zero",
        transformation="direct",
        min_value=0.0,
    ),
    FeatureSpec(
        name="loan_amount",
        order=4,
        dtype="float64",
        meaning="Requested principal loan amount in INR",
        required=True,
        missing_policy="error",
        transformation="direct",
        min_value=0.0,
        strictly_positive=True,
    ),
    FeatureSpec(
        name="loan_tenure",
        order=5,
        dtype="float64",
        meaning="Requested repayment duration in months",
        required=True,
        missing_policy="error",
        transformation="direct",
        min_value=0.0,
        strictly_positive=True,
    ),
    FeatureSpec(
        name="credit_score",
        order=6,
        dtype="float64",
        meaning="Bureau credit score (300-900 scale)",
        required=True,
        missing_policy="error",
        transformation="direct",
        min_value=300.0,
        max_value=900.0,
    ),
    FeatureSpec(
        name="bank_balance",
        order=7,
        dtype="float64",
        meaning="Average or closing verifiable bank balance in INR",
        required=False,
        missing_policy="impute_median",
        transformation="direct",
        min_value=0.0,
    ),
    FeatureSpec(
        name="monthly_expenses",
        order=8,
        dtype="float64",
        meaning="Declared monthly household/living expenses in INR",
        required=False,
        missing_policy="impute_median",
        transformation="direct",
        min_value=0.0,
    ),
    FeatureSpec(
        name="number_of_dependents",
        order=9,
        dtype="float64",
        meaning="Number of financial dependents",
        required=False,
        missing_policy="impute_median",
        transformation="direct",
        min_value=0.0,
        max_value=20.0,
    ),
    FeatureSpec(
        name="estimated_new_emi",
        order=10,
        dtype="float64",
        meaning="Amortized monthly EMI for requested facility at 10.5% p.a.",
        required=True,
        missing_policy="derived_from_loan",
        transformation="calculate_emi(loan_amount, 0.105, loan_tenure)",
        min_value=0.0,
    ),
    FeatureSpec(
        name="dti_ratio",
        order=11,
        dtype="float64",
        meaning="Post-loan Debt-to-Income / FOIR percentage",
        required=True,
        missing_policy="derived_from_income_and_emi",
        transformation="((existing_emi + estimated_new_emi) / monthly_income) * 100.0",
        min_value=0.0,
    ),
    FeatureSpec(
        name="loan_to_income_ratio",
        order=12,
        dtype="float64",
        meaning="Requested loan relative to annualized income",
        required=True,
        missing_policy="derived_from_loan_and_income",
        transformation="loan_amount / (monthly_income * 12.0)",
        min_value=0.0,
    ),
    FeatureSpec(
        name="net_disposable_income",
        order=13,
        dtype="float64",
        meaning="Remaining monthly cash flow after existing EMI, new EMI, and expenses",
        required=False,
        missing_policy="impute_median",
        transformation="monthly_income - existing_emi - estimated_new_emi - monthly_expenses",
    ),
    FeatureSpec(
        name="is_salaried",
        order=14,
        dtype="float64",
        meaning="Binary indicator (1.0 for Salaried, 0.0 for Self-Employed/Other)",
        required=False,
        missing_policy="impute_median",
        transformation="1.0 if 'SALARIED' in employment_type.upper() else 0.0",
        min_value=0.0,
        max_value=1.0,
    ),
)

RISK_FEATURE_NAMES: List[str] = [spec.name for spec in FEATURE_SPECS]
_SPEC_BY_NAME: Dict[str, FeatureSpec] = {spec.name: spec for spec in FEATURE_SPECS}


def calculate_emi(
    principal: float,
    annual_rate: float = DEFAULT_ANNUAL_INTEREST_RATE,
    tenure_months: int = 60,
) -> float:
    """Calculate monthly loan installment using standard amortization formula."""
    if principal <= 0 or tenure_months <= 0:
        return 0.0

    r = annual_rate / 12.0
    if r == 0:
        return round(principal / tenure_months, 2)

    factor = (1.0 + r) ** tenure_months
    emi = principal * r * factor / (factor - 1.0)
    return round(emi, 2)


def _is_missing(value: Any) -> bool:
    """Return True if value represents a missing/null value."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (float, np.floating)) and math.isnan(float(value)):
        return True
    return False


def _parse_numeric(
    raw_val: Any,
    spec: FeatureSpec,
    allow_missing: bool = False,
) -> Optional[float]:
    """Validate and convert an input value to finite float according to FeatureSpec."""
    if _is_missing(raw_val):
        if allow_missing and not spec.required:
            return None
        raise FeatureValidationError(
            f"Required feature '{spec.name}' is missing or empty."
        )

    if isinstance(raw_val, bool):
        raise FeatureValidationError(
            f"Feature '{spec.name}' cannot be boolean (got {raw_val!r})."
        )

    try:
        num = float(raw_val)
    except (TypeError, ValueError) as exc:
        raise FeatureValidationError(
            f"Feature '{spec.name}' must be numeric (got {raw_val!r})."
        ) from exc

    if math.isnan(num) or math.isinf(num):
        raise FeatureValidationError(
            f"Feature '{spec.name}' must be finite (got {raw_val!r})."
        )

    if spec.strictly_positive and num <= 0.0:
        raise FeatureValidationError(
            f"Feature '{spec.name}' must be strictly positive (got {num})."
        )
    if spec.min_value is not None and num < spec.min_value:
        raise FeatureValidationError(
            f"Feature '{spec.name}' ({num}) is below minimum {spec.min_value}."
        )
    if spec.max_value is not None and num > spec.max_value:
        raise FeatureValidationError(
            f"Feature '{spec.name}' ({num}) exceeds maximum {spec.max_value}."
        )

    return num


def _first_present(data: Mapping[str, Any], keys: Sequence[str]) -> Any:
    """Return the first non-None value across alias keys without swallowing 0/0.0."""
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def normalize_target_to_dict(
    target: Union[Applicant, DocumentPackageResult, Mapping[str, Any]],
) -> Dict[str, Any]:
    """Normalize Applicant, DocumentPackageResult, or dict into a flat input mapping."""
    if isinstance(target, Applicant):
        emp = (
            target.employment_type.value
            if hasattr(target.employment_type, "value")
            else str(target.employment_type)
        )
        return {
            "applicant_id": target.applicant_id,
            "name": target.name,
            "age": target.age,
            "employment_type": emp,
            "employment_years": target.employment_years,
            "monthly_income": target.monthly_income,
            "existing_emi": target.existing_emi,
            "loan_amount": target.loan_amount,
            "loan_tenure": target.loan_tenure,
            "credit_score": target.credit_score,
            "bank_balance": target.bank_balance,
            "monthly_expenses": target.monthly_expenses,
            "number_of_dependents": target.number_of_dependents,
        }

    if isinstance(target, DocumentPackageResult):
        extracted = target.all_extracted_fields

        def get_val(keys: List[str]) -> Optional[Any]:
            for k in keys:
                if k in extracted and extracted[k].value is not None:
                    return extracted[k].value
            for doc in target.documents_found:
                for k in keys:
                    if (
                        k in doc.extracted_fields
                        and doc.extracted_fields[k].value is not None
                    ):
                        return doc.extracted_fields[k].value
            return None

        return {
            "applicant_id": target.applicant_id,
            "age": get_val(["age"]),
            "employment_type": get_val(["employment_type"]),
            "employment_years": get_val(["employment_years"]),
            "monthly_income": get_val(
                [
                    "declared_monthly_income",
                    "monthly_income",
                    "net_salary",
                    "net_income",
                ]
            ),
            "existing_emi": get_val(
                ["declared_existing_emi", "existing_emi", "emi_debit"]
            ),
            "loan_amount": get_val(["loan_amount"]),
            "loan_tenure": get_val(["loan_tenure"]),
            "credit_score": get_val(["credit_score"]),
            "bank_balance": get_val(
                ["declared_bank_balance", "bank_balance", "closing_balance"]
            ),
            "monthly_expenses": get_val(["monthly_expenses"]),
            "number_of_dependents": get_val(["number_of_dependents"]),
        }

    if isinstance(target, Mapping):
        return dict(target)

    raise FeatureValidationError(
        f"Unsupported applicant data source type for feature extraction: {type(target).__name__}"
    )


class RiskFeatureContract:
    """Authoritative contract for extracting, validating, and ordering risk features."""

    version: str = FEATURE_CONTRACT_VERSION
    specs: Tuple[FeatureSpec, ...] = FEATURE_SPECS
    feature_names: List[str] = list(RISK_FEATURE_NAMES)

    def extract(
        self,
        target: Union[Applicant, DocumentPackageResult, Mapping[str, Any]],
        annual_rate: float = DEFAULT_ANNUAL_INTEREST_RATE,
    ) -> Dict[str, Optional[float]]:
        """Extract and validate ordered risk features from supported inputs."""
        data = normalize_target_to_dict(target)

        # Primary required features (strictly validated; zero values never swallowed)
        age = _parse_numeric(_first_present(data, ("age",)), _SPEC_BY_NAME["age"])
        monthly_income = _parse_numeric(
            _first_present(
                data,
                (
                    "monthly_income",
                    "declared_monthly_income",
                    "net_salary",
                    "net_income",
                ),
            ),
            _SPEC_BY_NAME["monthly_income"],
        )
        loan_amount = _parse_numeric(
            _first_present(data, ("loan_amount",)), _SPEC_BY_NAME["loan_amount"]
        )
        loan_tenure_num = _parse_numeric(
            _first_present(data, ("loan_tenure",)), _SPEC_BY_NAME["loan_tenure"]
        )
        if not float(loan_tenure_num).is_integer():
            raise FeatureValidationError(
                f"Feature 'loan_tenure' must be an integer number of months (got {loan_tenure_num})."
            )
        loan_tenure = int(loan_tenure_num)

        credit_score = _parse_numeric(
            _first_present(data, ("credit_score",)), _SPEC_BY_NAME["credit_score"]
        )

        # Optional primary inputs:
        # existing_emi defaults to 0.0 when omitted (matches Applicant schema default=0.0)
        raw_existing_emi = _first_present(
            data, ("existing_emi", "declared_existing_emi", "emi_debit")
        )
        existing_emi = (
            0.0
            if _is_missing(raw_existing_emi)
            else _parse_numeric(
                raw_existing_emi, _SPEC_BY_NAME["existing_emi"], allow_missing=False
            )
        )

        # Remaining optional fields remain None when absent so training-fitted imputer handles them
        employment_years = _parse_numeric(
            _first_present(data, ("employment_years",)),
            _SPEC_BY_NAME["employment_years"],
            allow_missing=True,
        )
        bank_balance = _parse_numeric(
            _first_present(
                data, ("bank_balance", "declared_bank_balance", "closing_balance")
            ),
            _SPEC_BY_NAME["bank_balance"],
            allow_missing=True,
        )
        monthly_expenses = _parse_numeric(
            _first_present(data, ("monthly_expenses",)),
            _SPEC_BY_NAME["monthly_expenses"],
            allow_missing=True,
        )
        number_of_dependents = _parse_numeric(
            _first_present(data, ("number_of_dependents",)),
            _SPEC_BY_NAME["number_of_dependents"],
            allow_missing=True,
        )
        if (
            number_of_dependents is not None
            and not float(number_of_dependents).is_integer()
        ):
            raise FeatureValidationError(
                f"Feature 'number_of_dependents' must be an integer (got {number_of_dependents})."
            )

        # Employment category transformation (preserves None if omitted)
        raw_emp = _first_present(data, ("employment_type",))
        if raw_emp is None or (isinstance(raw_emp, str) and raw_emp.strip() == ""):
            is_salaried: Optional[float] = None
        else:
            emp_str = (
                raw_emp.value if hasattr(raw_emp, "value") else str(raw_emp)
            ).upper()
            is_salaried = 1.0 if "SALARIED" in emp_str else 0.0

        # Deterministic derived features computed identically in training and serving
        assert monthly_income is not None and loan_amount is not None
        assert existing_emi is not None

        estimated_new_emi = calculate_emi(loan_amount, annual_rate, loan_tenure)
        dti_ratio = round(
            ((existing_emi + estimated_new_emi) / monthly_income) * 100.0, 2
        )
        loan_to_income_ratio = round(loan_amount / (monthly_income * 12.0), 2)
        net_disposable_income: Optional[float] = (
            round(
                monthly_income - existing_emi - estimated_new_emi - monthly_expenses,
                2,
            )
            if monthly_expenses is not None
            else None
        )

        features: Dict[str, Optional[float]] = {
            "age": age,
            "employment_years": employment_years,
            "monthly_income": monthly_income,
            "existing_emi": existing_emi,
            "loan_amount": loan_amount,
            "loan_tenure": float(loan_tenure),
            "credit_score": credit_score,
            "bank_balance": bank_balance,
            "monthly_expenses": monthly_expenses,
            "number_of_dependents": number_of_dependents,
            "estimated_new_emi": estimated_new_emi,
            "dti_ratio": dti_ratio,
            "loan_to_income_ratio": loan_to_income_ratio,
            "net_disposable_income": net_disposable_income,
            "is_salaried": is_salaried,
        }
        return self.validate_feature_vector(features)

    def validate_feature_vector(
        self, features: Mapping[str, Any]
    ) -> Dict[str, Optional[float]]:
        """Validate a feature mapping has exact contract keys, types, and bounds."""
        if list(features.keys()) != self.feature_names:
            missing = [f for f in self.feature_names if f not in features]
            extra = [f for f in features if f not in _SPEC_BY_NAME]
            raise FeatureValidationError(
                f"Feature vector mismatch against contract '{self.version}'. "
                f"Missing: {missing}, Extra: {extra}, Expected order: {self.feature_names}."
            )

        validated: Dict[str, Optional[float]] = {}
        for spec in self.specs:
            val = _parse_numeric(
                features[spec.name], spec, allow_missing=not spec.required
            )
            validated[spec.name] = val
        return validated

    def to_dataframe(
        self, feature_rows: Sequence[Mapping[str, Optional[float]]]
    ) -> pd.DataFrame:
        """Convert validated feature dicts into a strictly ordered float64 DataFrame."""
        if not feature_rows:
            return pd.DataFrame(columns=self.feature_names, dtype="float64")

        ordered_rows = []
        for row in feature_rows:
            validated = self.validate_feature_vector(row)
            ordered_rows.append(
                {
                    name: (
                        np.nan if validated[name] is None else float(validated[name])
                    )
                    for name in self.feature_names
                }
            )
        return pd.DataFrame(ordered_rows, columns=self.feature_names).astype("float64")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize complete contract specification for artifact metadata."""
        return {
            "feature_contract_version": self.version,
            "feature_names": list(self.feature_names),
            "feature_order": list(self.feature_names),
            "feature_count": len(self.specs),
            "features": [spec.to_dict() for spec in self.specs],
        }


RISK_FEATURE_CONTRACT = RiskFeatureContract()

__all__ = [
    "DEFAULT_ANNUAL_INTEREST_RATE",
    "FEATURE_CONTRACT_VERSION",
    "FEATURE_SPECS",
    "FeatureSpec",
    "FeatureValidationError",
    "RISK_FEATURE_CONTRACT",
    "RISK_FEATURE_NAMES",
    "RiskFeatureContract",
    "calculate_emi",
    "normalize_target_to_dict",
]
