"""Eligibility evaluation package for deterministic loan underwriting.

Exports the centralized EligibilityPolicy, deterministic rule functions,
and the core EligibilityEvaluator.
"""

from app.eligibility.evaluator import EligibilityEvaluator
from app.eligibility.policy import EligibilityPolicy
from app.eligibility.rules import (
    evaluate_data_completeness,
    evaluate_documents_complete,
    evaluate_employment_eligibility,
    evaluate_loan_amount_limits,
    evaluate_loan_tenure_limits,
    evaluate_max_age,
    evaluate_max_dti_ratio,
    evaluate_min_age,
    evaluate_min_credit_score,
    evaluate_min_monthly_income,
)

__all__ = [
    "EligibilityEvaluator",
    "EligibilityPolicy",
    "evaluate_data_completeness",
    "evaluate_documents_complete",
    "evaluate_employment_eligibility",
    "evaluate_loan_amount_limits",
    "evaluate_loan_tenure_limits",
    "evaluate_max_age",
    "evaluate_max_dti_ratio",
    "evaluate_min_age",
    "evaluate_min_credit_score",
    "evaluate_min_monthly_income",
]
