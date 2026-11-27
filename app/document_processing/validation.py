"""Field-Level Validation and Transparent Confidence Scoring for Document Extraction.

Distinguishes five explicit validation states for every extracted or expected field:
- valid: Matched with expected context and passed domain/format checks
- unverified: Extracted plausibly but weaker context or below normal verification bar
- invalid: Matched value violated format/domain rules (e.g., negative income, bad date)
- missing: Expected field for this document type was absent
- ambiguous: Conflicting distinct candidate values matched for the same field
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

VALIDATION_VALID = "valid"
VALIDATION_UNVERIFIED = "unverified"
VALIDATION_INVALID = "invalid"
VALIDATION_MISSING = "missing"
VALIDATION_AMBIGUOUS = "ambiguous"

# Expected schema fields checked for completeness tracking per classified category.
EXPECTED_SCHEMA_FIELDS_BY_DOC_TYPE: Dict[str, List[str]] = {
    "loan_application": [
        "applicant_id",
        "applicant_name",
        "age",
        "employment_type",
        "monthly_income",
        "existing_emi",
        "bank_balance",
        "credit_score",
        "loan_amount",
        "loan_tenure",
    ],
    "identity_proof": [
        "applicant_id",
        "applicant_name",
        "id_ref",
    ],
    "address_proof": [
        "applicant_name",
        "address",
    ],
    "salary_slip": [
        "employee_name",
        "applicant_id",
        "employer_name",
        "net_salary",
        "gross_earnings",
    ],
    "income_statement": [
        "applicant_name",
        "applicant_id",
        "business_name",
        "net_income",
        "gross_earnings",
    ],
    "employment_proof": [
        "applicant_name",
        "employer_name",
    ],
    "bank_statement": [
        "account_holder",
        "account_number",
        "statement_period",
        "closing_balance",
    ],
}

NON_NEGATIVE_NUMERIC_FIELDS = {
    "existing_emi",
    "declared_existing_emi",
    "bank_balance",
    "declared_bank_balance",
    "opening_balance",
    "closing_balance",
    "total_credits",
    "total_debits",
    "other_income",
    "total_deductions",
    "monthly_expenses",
    "estimated_new_emi",
    "basic_salary",
    "hra",
    "provident_fund",
    "emi_debit",
    "salary_credit",
    "employment_years",
    "number_of_dependents",
    "transaction_count",
}

STRICTLY_POSITIVE_MONETARY_FIELDS = {
    "monthly_income",
    "declared_monthly_income",
    "net_salary",
    "net_income",
    "gross_earnings",
    "loan_amount",
}

DATE_SINGLE_FIELDS = {
    "submission_date",
    "issue_date",
    "dob",
    "employment_start_date",
}

DATE_PERIOD_FIELDS = {"statement_period", "salary_period"}

_DATE_FORMATS = (
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d %b %Y",
    "%d %B %Y",
)


def parse_and_validate_date(
    value: Any,
) -> Tuple[Optional[datetime], bool, Optional[str]]:
    """Parse a date string strictly against calendar bounds (rejects e.g. 32-Feb-2026)."""
    if value is None:
        return None, False, "Empty date value"
    text = str(value).strip()
    if not text:
        return None, False, "Empty date value"

    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
            if not (1900 <= parsed.year <= 2100):
                return None, False, f"Date year {parsed.year} outside [1900, 2100]"
            return parsed, True, None
        except ValueError:
            continue

    return None, False, f"Invalid calendar date '{text}'"


def validate_date_period(period_str: Any) -> Tuple[str, Optional[str]]:
    """Validate single period labels or 'start to end' date ranges."""
    if period_str is None:
        return VALIDATION_INVALID, "Empty period string"
    text = str(period_str).strip()
    parts = re.split(r"\s+(?:to|-|–)\s+", text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        start_dt, ok_start, msg_start = parse_and_validate_date(parts[0])
        end_dt, ok_end, msg_end = parse_and_validate_date(parts[1])
        if not ok_start or not ok_end:
            return VALIDATION_INVALID, msg_start or msg_end
        if start_dt and end_dt and start_dt > end_dt:
            return VALIDATION_INVALID, f"Start date exceeds end date in '{text}'"
        return VALIDATION_VALID, None

    # Allow Month YYYY format (e.g. 'August 2026' or 'Aug 2026')
    for fmt in ("%B %Y", "%b %Y"):
        try:
            datetime.strptime(text, fmt)
            return VALIDATION_VALID, None
        except ValueError:
            continue

    _, ok_single, msg_single = parse_and_validate_date(text)
    if ok_single:
        return VALIDATION_VALID, None
    return VALIDATION_INVALID, msg_single or f"Unrecognized date period '{text}'"


def validate_field_value(
    field_name: str,
    value: Any,
    contextual_confidence: float = 0.90,
) -> Tuple[str, Any, Optional[str]]:
    """Validate an extracted candidate value and return (status, sanitized_value, message)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return VALIDATION_MISSING, None, f"Missing value for '{field_name}'"

    if field_name in STRICTLY_POSITIVE_MONETARY_FIELDS:
        try:
            num = float(value)
        except (ValueError, TypeError):
            return VALIDATION_INVALID, None, f"Non-numeric amount for '{field_name}'"
        if num <= 0.0:
            return (
                VALIDATION_INVALID,
                None,
                f"Value for '{field_name}' must be positive (got {num})",
            )
        if num > 1_000_000_000.0:
            return (
                VALIDATION_UNVERIFIED,
                round(num, 2),
                f"Unusually large monetary amount for '{field_name}' ({num:,.2f})",
            )
        return (
            (
                VALIDATION_VALID
                if contextual_confidence >= 0.70
                else VALIDATION_UNVERIFIED
            ),
            round(num, 2),
            None,
        )

    if field_name in NON_NEGATIVE_NUMERIC_FIELDS:
        try:
            num = float(value)
        except (ValueError, TypeError):
            return VALIDATION_INVALID, None, f"Non-numeric value for '{field_name}'"
        if num < 0.0:
            return (
                VALIDATION_INVALID,
                None,
                f"Negative value for '{field_name}' is invalid (got {num})",
            )
        if field_name == "employment_years" and num > 70.0:
            return (
                VALIDATION_INVALID,
                None,
                f"Implausible employment_years ({num})",
            )
        if field_name == "number_of_dependents":
            int_val = int(round(num))
            if int_val > 20:
                return (
                    VALIDATION_INVALID,
                    None,
                    f"Implausible number_of_dependents ({int_val})",
                )
            return VALIDATION_VALID, int_val, None
        if field_name == "transaction_count":
            return VALIDATION_VALID, int(num), None
        return (
            (
                VALIDATION_VALID
                if contextual_confidence >= 0.70
                else VALIDATION_UNVERIFIED
            ),
            round(num, 2),
            None,
        )

    if field_name == "age":
        try:
            age_val = int(value)
        except (ValueError, TypeError):
            return VALIDATION_INVALID, None, f"Invalid integer age '{value}'"
        if age_val < 18 or age_val > 100:
            return (
                VALIDATION_INVALID,
                None,
                f"Age {age_val} outside valid adult range [18, 100]",
            )
        return VALIDATION_VALID, age_val, None

    if field_name == "credit_score":
        try:
            score_val = int(value)
        except (ValueError, TypeError):
            return VALIDATION_INVALID, None, f"Invalid credit_score '{value}'"
        if score_val < 300 or score_val > 900:
            return (
                VALIDATION_INVALID,
                None,
                f"Credit score {score_val} outside valid bureau range [300, 900]",
            )
        return VALIDATION_VALID, score_val, None

    if field_name == "loan_tenure":
        try:
            tenure_val = int(value)
        except (ValueError, TypeError):
            return VALIDATION_INVALID, None, f"Invalid loan_tenure '{value}'"
        if tenure_val <= 0 or tenure_val > 480:
            return (
                VALIDATION_INVALID,
                None,
                f"Loan tenure {tenure_val} outside valid range [1, 480] months",
            )
        return VALIDATION_VALID, tenure_val, None

    if field_name == "days_paid":
        try:
            days_val = int(value)
        except (ValueError, TypeError):
            return VALIDATION_INVALID, None, f"Invalid days_paid '{value}'"
        if days_val < 0 or days_val > 31:
            return (
                VALIDATION_INVALID,
                None,
                f"days_paid {days_val} outside valid month range [0, 31]",
            )
        return VALIDATION_VALID, days_val, None

    if field_name in DATE_SINGLE_FIELDS:
        _, ok_dt, msg_dt = parse_and_validate_date(value)
        if not ok_dt:
            return VALIDATION_INVALID, None, msg_dt
        return VALIDATION_VALID, str(value).strip(), None

    if field_name in DATE_PERIOD_FIELDS:
        period_status, period_msg = validate_date_period(value)
        if period_status == VALIDATION_INVALID:
            return VALIDATION_INVALID, None, period_msg
        return VALIDATION_VALID, str(value).strip(), None

    cleaned_str = str(value).strip()
    status = (
        VALIDATION_VALID if contextual_confidence >= 0.70 else VALIDATION_UNVERIFIED
    )
    return status, cleaned_str, None


def compute_extraction_confidence(
    *,
    extraction_method: str,
    label_specificity: str,
    text_quality: float = 1.0,
    validation_status: str = VALIDATION_VALID,
) -> float:
    """Compute a transparent, heuristic (non-calibrated) extraction confidence score.

    Confidence reflects extraction method, contextual label specificity, readable
    text quality, and field validation outcome. Never returns calibrated probability.
    """
    method_base = {
        "regex_digital": 0.94,
        "table_parser": 0.92,
        "regex_ocr": 0.87,
        "header_positional": 0.88,
        "generic_fallback": 0.65,
    }.get(extraction_method, 0.80)

    label_adj = {
        "exact_label": 0.01,
        "multiline_label": -0.02,
        "table_column": 0.0,
        "positional": -0.02,
        "weak_context": -0.14,
    }.get(label_specificity, -0.05)

    quality_clamped = min(max(float(text_quality), 0.4), 1.0)
    raw_score = (method_base + label_adj) * (0.85 + 0.15 * quality_clamped)

    if validation_status == VALIDATION_MISSING:
        return 0.0
    if validation_status == VALIDATION_INVALID:
        return round(min(raw_score, 0.20), 2)
    if validation_status == VALIDATION_AMBIGUOUS:
        return round(min(raw_score, 0.48), 2)
    if validation_status == VALIDATION_UNVERIFIED:
        return round(min(raw_score, 0.72), 2)

    return round(min(max(raw_score, 0.05), 0.96), 2)
