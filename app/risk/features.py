"""Risk Feature Engineering and Amortization Calculation.

Extracts normalized numerical features from structured applicant data,
computes standard financial metrics (DTI, Loan-to-Income, Disposable Income),
and provides deterministic EMI amortization calculations.
"""

from typing import Any, Dict, List, Optional, Union

from app.schemas.applicant import Applicant, DocumentPackageResult

# Default underwriting benchmark annual interest rate for retail facility estimation
DEFAULT_ANNUAL_INTEREST_RATE = 0.105  # 10.5% p.a.

# Explicit ordered feature vector for ML risk modeling (No target leakage)
RISK_FEATURE_NAMES = [
    "age",
    "employment_years",
    "monthly_income",
    "existing_emi",
    "loan_amount",
    "loan_tenure",
    "credit_score",
    "bank_balance",
    "monthly_expenses",
    "number_of_dependents",
    "estimated_new_emi",
    "dti_ratio",
    "loan_to_income_ratio",
    "net_disposable_income",
    "is_salaried",
]


def calculate_emi(
    principal: float,
    annual_rate: float = DEFAULT_ANNUAL_INTEREST_RATE,
    tenure_months: int = 60,
) -> float:
    """Calculate monthly loan installment using standard amortization formula.

    Formula:
        EMI = P * r * (1 + r)^n / ((1 + r)^n - 1)
    where:
        P = principal amount
        r = monthly nominal interest rate (annual_rate / 12)
        n = number of monthly installments

    Args:
        principal: Principal loan amount in INR.
        annual_rate: Annual nominal interest rate (e.g. 0.105 for 10.5%).
        tenure_months: Total loan repayment duration in months.

    Returns:
        Rounded monthly EMI payment.
    """
    if principal <= 0 or tenure_months <= 0:
        return 0.0

    r = annual_rate / 12.0
    if r == 0:
        return round(principal / tenure_months, 2)

    factor = (1.0 + r) ** tenure_months
    emi = principal * r * factor / (factor - 1.0)
    return round(emi, 2)


def get_feature_names() -> List[str]:
    """Return the canonical list of risk feature column names."""
    return list(RISK_FEATURE_NAMES)


def extract_features(
    target: Union[Applicant, DocumentPackageResult, Dict[str, Any]],
    annual_rate: float = DEFAULT_ANNUAL_INTEREST_RATE,
) -> Dict[str, float]:
    """Extract and derive normalized risk features from structured applicant data.

    Accepts structured Applicant domain models, Stage 3 DocumentPackageResults,
    or raw dictionary records.

    Args:
        target: Input data source.
        annual_rate: Benchmark interest rate for new EMI computation.

    Returns:
        Mapping of feature names to float values.
    """
    data = _normalize_target_to_dict(target)

    # Core attributes with safe fallbacks
    age = float(data.get("age") or 30.0)
    employment_years = float(data.get("employment_years") or 3.0)
    monthly_income = float(
        data.get("monthly_income")
        or data.get("declared_monthly_income")
        or data.get("net_salary")
        or data.get("net_income")
        or 50000.0
    )
    existing_emi = float(
        data.get("existing_emi") or data.get("declared_existing_emi") or 0.0
    )
    loan_amount = float(data.get("loan_amount") or 500000.0)
    loan_tenure = int(data.get("loan_tenure") or 60)
    credit_score = float(data.get("credit_score") or 700.0)
    bank_balance = float(
        data.get("bank_balance") or data.get("declared_bank_balance") or 50000.0
    )

    # Secondary attributes
    monthly_expenses = float(data.get("monthly_expenses") or (monthly_income * 0.35))
    dependents = float(data.get("number_of_dependents") or 1.0)

    # Employment classification
    emp_type = str(data.get("employment_type") or "SALARIED").upper()
    is_salaried = 1.0 if "SALARIED" in emp_type else 0.0

    # Derived financial indicators
    if "estimated_new_emi" in data and data["estimated_new_emi"] is not None:
        estimated_new_emi = float(data["estimated_new_emi"])
    else:
        estimated_new_emi = calculate_emi(loan_amount, annual_rate, loan_tenure)

    # DTI Ratio (FOIR): (existing_emi + estimated_new_emi) / monthly_income * 100
    if "dti_ratio" in data and data["dti_ratio"] is not None:
        dti_ratio = float(data["dti_ratio"])
    else:
        dti_ratio = (
            round(((existing_emi + estimated_new_emi) / monthly_income) * 100.0, 2)
            if monthly_income > 0
            else 100.0
        )

    # Loan-to-Annual-Income ratio
    if "loan_to_income_ratio" in data and data["loan_to_income_ratio"] is not None:
        loan_to_income_ratio = float(data["loan_to_income_ratio"])
    else:
        loan_to_income_ratio = (
            round(loan_amount / (monthly_income * 12.0), 2)
            if monthly_income > 0
            else 5.0
        )

    # Net Disposable Income: monthly income minus total monthly obligations
    net_disposable = round(
        monthly_income - existing_emi - estimated_new_emi - monthly_expenses, 2
    )

    return {
        "age": age,
        "employment_years": employment_years,
        "monthly_income": monthly_income,
        "existing_emi": existing_emi,
        "loan_amount": loan_amount,
        "loan_tenure": float(loan_tenure),
        "credit_score": credit_score,
        "bank_balance": bank_balance,
        "monthly_expenses": monthly_expenses,
        "number_of_dependents": dependents,
        "estimated_new_emi": estimated_new_emi,
        "dti_ratio": dti_ratio,
        "loan_to_income_ratio": loan_to_income_ratio,
        "net_disposable_income": net_disposable,
        "is_salaried": is_salaried,
    }


def _normalize_target_to_dict(
    target: Union[Applicant, DocumentPackageResult, Dict[str, Any]],
) -> Dict[str, Any]:
    """Helper to convert various structured applicant inputs into a flat key-value dict."""
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
        }

    if isinstance(target, dict):
        return dict(target)

    raise TypeError(
        f"Unsupported applicant data source type for feature extraction: {type(target).__name__}"
    )
