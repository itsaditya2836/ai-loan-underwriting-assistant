"""Deterministic Eligibility Rules.

Implements rule evaluations for loan underwriting criteria:
- Document completeness (from Stage 3 intake)
- Minimum and maximum age
- Minimum monthly income
- Employment category eligibility
- Loan amount within policy limits
- Loan tenure within policy limits
- Bureau credit score threshold
- Debt-to-income (DTI) ratio
- Critical field completeness and extraction confidence
"""

from typing import Any, Dict, List, Optional

from app.eligibility.policy import EligibilityPolicy
from app.schemas.applicant import EligibilityRuleResult, ExtractedField, RuleStatus


def _extract_provenance(
    field_record: Optional[ExtractedField], fallback_evidence: str
) -> Dict[str, Any]:
    """Helper to extract documentary evidence and provenance if available."""
    if field_record is not None:
        return {
            "evidence": field_record.evidence or fallback_evidence,
            "source_document": field_record.source_document,
            "page_number": field_record.page_number,
        }
    return {
        "evidence": fallback_evidence,
        "source_document": None,
        "page_number": None,
    }


def evaluate_documents_complete(
    documents_missing: List[str],
    documents_found: List[str],
    is_complete: bool,
    policy: EligibilityPolicy,
) -> EligibilityRuleResult:
    """Evaluate whether all mandatory and expected documents are present.

    Note: Missing documents lead to REVIEW_REQUIRED, not fraud rejection.
    """
    rule_id = "DOCUMENTS_COMPLETE"
    rule_name = "Required Documents Completeness"
    expected = "All expected documents present (no missing files)"
    actual = {
        "documents_found": documents_found,
        "documents_missing": documents_missing,
    }

    if documents_missing or not is_complete:
        missing_str = (
            ", ".join(documents_missing) if documents_missing else "Incomplete package"
        )
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.REVIEW_REQUIRED,
            actual_value=actual,
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=f"Mandatory document(s) missing from application package: {missing_str}.",
            evidence=f"Missing: {missing_str}; Found: {', '.join(documents_found) if documents_found else 'None'}",
            source_document="document_package",
            page_number=1,
        )

    return EligibilityRuleResult(
        rule_id=rule_id,
        rule_name=rule_name,
        status=RuleStatus.PASS,
        actual_value=actual,
        expected_value=expected,
        passed=True,
        severity="MANDATORY",
        reason="All expected document types are present and verified in application package.",
        evidence=f"Present documents: {', '.join(documents_found)}",
        source_document="document_package",
        page_number=1,
    )


def evaluate_min_age(
    age: Optional[int],
    field_record: Optional[ExtractedField],
    policy: EligibilityPolicy,
) -> EligibilityRuleResult:
    """Evaluate applicant age against configured minimum age requirement."""
    rule_id = "MIN_AGE"
    rule_name = "Minimum Age Requirement"
    expected = f">= {policy.min_age} years"
    prov = _extract_provenance(field_record, f"Age: {age}")

    if age is None:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.REVIEW_REQUIRED,
            actual_value=None,
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason="Applicant age is missing; eligibility cannot be verified.",
            **prov,
        )

    if field_record and field_record.confidence < policy.min_confidence_threshold:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.REVIEW_REQUIRED,
            actual_value=age,
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=(
                f"Applicant age extraction confidence ({field_record.confidence:.2f}) "
                f"is below required threshold ({policy.min_confidence_threshold:.2f})."
            ),
            **prov,
        )

    if age < policy.min_age:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.FAIL,
            actual_value=f"{age} years",
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=f"Applicant age ({age} years) is below configured policy minimum of {policy.min_age} years.",
            **prov,
        )

    return EligibilityRuleResult(
        rule_id=rule_id,
        rule_name=rule_name,
        status=RuleStatus.PASS,
        actual_value=f"{age} years",
        expected_value=expected,
        passed=True,
        severity="MANDATORY",
        reason=f"Applicant age ({age} years) satisfies policy minimum of {policy.min_age} years.",
        **prov,
    )


def evaluate_max_age(
    age: Optional[int],
    field_record: Optional[ExtractedField],
    policy: EligibilityPolicy,
) -> EligibilityRuleResult:
    """Evaluate applicant age against configured maximum age requirement."""
    rule_id = "MAX_AGE"
    rule_name = "Maximum Age Requirement"
    expected = f"<= {policy.max_age} years"
    prov = _extract_provenance(field_record, f"Age: {age}")

    if age is None:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.REVIEW_REQUIRED,
            actual_value=None,
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason="Applicant age is missing; eligibility cannot be verified.",
            **prov,
        )

    if field_record and field_record.confidence < policy.min_confidence_threshold:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.REVIEW_REQUIRED,
            actual_value=age,
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=(
                f"Applicant age extraction confidence ({field_record.confidence:.2f}) "
                f"is below required threshold ({policy.min_confidence_threshold:.2f})."
            ),
            **prov,
        )

    if age > policy.max_age:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.FAIL,
            actual_value=f"{age} years",
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=f"Applicant age ({age} years) exceeds configured policy maximum of {policy.max_age} years.",
            **prov,
        )

    return EligibilityRuleResult(
        rule_id=rule_id,
        rule_name=rule_name,
        status=RuleStatus.PASS,
        actual_value=f"{age} years",
        expected_value=expected,
        passed=True,
        severity="MANDATORY",
        reason=f"Applicant age ({age} years) satisfies policy maximum of {policy.max_age} years.",
        **prov,
    )


def evaluate_min_monthly_income(
    monthly_income: Optional[float],
    field_record: Optional[ExtractedField],
    policy: EligibilityPolicy,
) -> EligibilityRuleResult:
    """Evaluate declared/verified monthly income against configured minimum."""
    rule_id = "MIN_MONTHLY_INCOME"
    rule_name = "Minimum Monthly Income"
    expected = f">= INR {policy.min_monthly_income:,.2f}"
    prov = _extract_provenance(
        field_record,
        (
            f"Monthly Income: INR {monthly_income:,.2f}"
            if monthly_income is not None
            else "None"
        ),
    )

    if monthly_income is None:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.REVIEW_REQUIRED,
            actual_value=None,
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason="Monthly income is missing or could not be extracted; manual review required.",
            **prov,
        )

    if field_record and field_record.confidence < policy.min_confidence_threshold:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.REVIEW_REQUIRED,
            actual_value=f"INR {monthly_income:,.2f}",
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=(
                f"Monthly income extraction confidence ({field_record.confidence:.2f}) "
                f"is below required threshold ({policy.min_confidence_threshold:.2f})."
            ),
            **prov,
        )

    if monthly_income < policy.min_monthly_income:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.FAIL,
            actual_value=f"INR {monthly_income:,.2f}",
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=(
                f"Applicant monthly income (INR {monthly_income:,.2f}) is below "
                f"configured policy minimum of INR {policy.min_monthly_income:,.2f}."
            ),
            **prov,
        )

    return EligibilityRuleResult(
        rule_id=rule_id,
        rule_name=rule_name,
        status=RuleStatus.PASS,
        actual_value=f"INR {monthly_income:,.2f}",
        expected_value=expected,
        passed=True,
        severity="MANDATORY",
        reason=(
            f"Applicant declared monthly income (INR {monthly_income:,.2f}) "
            f"satisfies configured minimum of INR {policy.min_monthly_income:,.2f}."
        ),
        **prov,
    )


def evaluate_employment_eligibility(
    employment_type: Optional[str],
    field_record: Optional[ExtractedField],
    policy: EligibilityPolicy,
) -> EligibilityRuleResult:
    """Evaluate applicant employment category against policy allowed types."""
    rule_id = "EMPLOYMENT_ELIGIBILITY"
    rule_name = "Employment Category Eligibility"
    expected = f"One of: {', '.join(policy.allowed_employment_types)}"
    prov = _extract_provenance(field_record, f"Employment Type: {employment_type}")

    if not employment_type:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.REVIEW_REQUIRED,
            actual_value=None,
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason="Employment category is missing; eligibility cannot be verified.",
            **prov,
        )

    norm_type = employment_type.strip().upper().replace(" ", "_").replace("-", "_")
    allowed_norm = [
        t.strip().upper().replace(" ", "_").replace("-", "_")
        for t in policy.allowed_employment_types
    ]

    if norm_type not in allowed_norm:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.FAIL,
            actual_value=employment_type,
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=f"Applicant employment type '{employment_type}' is not supported by current policy.",
            **prov,
        )

    return EligibilityRuleResult(
        rule_id=rule_id,
        rule_name=rule_name,
        status=RuleStatus.PASS,
        actual_value=employment_type,
        expected_value=expected,
        passed=True,
        severity="MANDATORY",
        reason=f"Employment category '{employment_type}' is approved under underwriting policy.",
        **prov,
    )


def evaluate_loan_amount_limits(
    loan_amount: Optional[float],
    field_record: Optional[ExtractedField],
    policy: EligibilityPolicy,
) -> EligibilityRuleResult:
    """Evaluate requested loan amount against configured policy boundaries."""
    rule_id = "LOAN_AMOUNT_LIMITS"
    rule_name = "Loan Amount Policy Limits"
    expected = f"Between INR {policy.min_loan_amount:,.2f} and INR {policy.max_loan_amount:,.2f}"
    prov = _extract_provenance(
        field_record,
        f"Loan Amount: INR {loan_amount:,.2f}" if loan_amount is not None else "None",
    )

    if loan_amount is None:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.REVIEW_REQUIRED,
            actual_value=None,
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason="Requested loan amount is missing; eligibility cannot be verified.",
            **prov,
        )

    if loan_amount < policy.min_loan_amount:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.FAIL,
            actual_value=f"INR {loan_amount:,.2f}",
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=(
                f"Requested loan amount (INR {loan_amount:,.2f}) is below "
                f"minimum policy limit of INR {policy.min_loan_amount:,.2f}."
            ),
            **prov,
        )

    if loan_amount > policy.max_loan_amount:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.FAIL,
            actual_value=f"INR {loan_amount:,.2f}",
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=(
                f"Requested loan amount (INR {loan_amount:,.2f}) exceeds "
                f"maximum policy limit of INR {policy.max_loan_amount:,.2f}."
            ),
            **prov,
        )

    return EligibilityRuleResult(
        rule_id=rule_id,
        rule_name=rule_name,
        status=RuleStatus.PASS,
        actual_value=f"INR {loan_amount:,.2f}",
        expected_value=expected,
        passed=True,
        severity="MANDATORY",
        reason=(
            f"Requested loan amount (INR {loan_amount:,.2f}) satisfies policy bounds "
            f"[INR {policy.min_loan_amount:,.2f} - INR {policy.max_loan_amount:,.2f}]."
        ),
        **prov,
    )


def evaluate_loan_tenure_limits(
    loan_tenure: Optional[int],
    field_record: Optional[ExtractedField],
    policy: EligibilityPolicy,
) -> EligibilityRuleResult:
    """Evaluate requested loan duration against configured policy bounds."""
    rule_id = "LOAN_TENURE_LIMITS"
    rule_name = "Loan Tenure Policy Limits"
    expected = f"Between {policy.min_loan_tenure_months} and {policy.max_loan_tenure_months} months"
    prov = _extract_provenance(
        field_record,
        f"Loan Tenure: {loan_tenure} months" if loan_tenure is not None else "None",
    )

    if loan_tenure is None:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.REVIEW_REQUIRED,
            actual_value=None,
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason="Requested loan tenure is missing; eligibility cannot be verified.",
            **prov,
        )

    if loan_tenure < policy.min_loan_tenure_months:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.FAIL,
            actual_value=f"{loan_tenure} months",
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=(
                f"Requested loan tenure ({loan_tenure} months) is below "
                f"minimum policy limit of {policy.min_loan_tenure_months} months."
            ),
            **prov,
        )

    if loan_tenure > policy.max_loan_tenure_months:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.FAIL,
            actual_value=f"{loan_tenure} months",
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=(
                f"Requested loan tenure ({loan_tenure} months) exceeds "
                f"maximum policy limit of {policy.max_loan_tenure_months} months."
            ),
            **prov,
        )

    return EligibilityRuleResult(
        rule_id=rule_id,
        rule_name=rule_name,
        status=RuleStatus.PASS,
        actual_value=f"{loan_tenure} months",
        expected_value=expected,
        passed=True,
        severity="MANDATORY",
        reason=(
            f"Requested loan tenure ({loan_tenure} months) is within policy limits "
            f"[{policy.min_loan_tenure_months} - {policy.max_loan_tenure_months}] months."
        ),
        **prov,
    )


def evaluate_min_credit_score(
    credit_score: Optional[int],
    field_record: Optional[ExtractedField],
    policy: EligibilityPolicy,
) -> EligibilityRuleResult:
    """Evaluate bureau credit score against configured baseline eligibility threshold."""
    rule_id = "MIN_CREDIT_SCORE"
    rule_name = "Minimum Credit Score Threshold"
    expected = f">= {policy.min_credit_score}"
    prov = _extract_provenance(
        field_record,
        f"Credit Score: {credit_score}" if credit_score is not None else "None",
    )

    if credit_score is None:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.REVIEW_REQUIRED,
            actual_value=None,
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason="Credit score is missing or unverified; manual review required.",
            **prov,
        )

    if field_record and field_record.confidence < policy.min_confidence_threshold:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.REVIEW_REQUIRED,
            actual_value=credit_score,
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=(
                f"Credit score extraction confidence ({field_record.confidence:.2f}) "
                f"is below required threshold ({policy.min_confidence_threshold:.2f})."
            ),
            **prov,
        )

    if credit_score < policy.min_credit_score:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.FAIL,
            actual_value=credit_score,
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=(
                f"Applicant credit score ({credit_score}) is below "
                f"the configured eligibility threshold of {policy.min_credit_score}."
            ),
            **prov,
        )

    return EligibilityRuleResult(
        rule_id=rule_id,
        rule_name=rule_name,
        status=RuleStatus.PASS,
        actual_value=credit_score,
        expected_value=expected,
        passed=True,
        severity="MANDATORY",
        reason=(
            f"Applicant credit score ({credit_score}) satisfies "
            f"configured eligibility threshold of {policy.min_credit_score}."
        ),
        **prov,
    )


def evaluate_max_dti_ratio(
    dti_ratio: Optional[float],
    policy: EligibilityPolicy,
) -> EligibilityRuleResult:
    """Evaluate Debt-to-Income / FOIR ratio against configured policy cap."""
    rule_id = "MAX_DTI_RATIO"
    rule_name = "Debt-to-Income (DTI) Cap"
    expected = f"<= {policy.max_dti_ratio:.1f}%"

    if dti_ratio is None:
        # Advisory: If obligations are not provided, pass with observation
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.PASS,
            actual_value="Not calculated",
            expected_value=expected,
            passed=True,
            severity="ADVISORY",
            reason="Existing debt obligations not reported; DTI assumed within bounds.",
            evidence="DTI: N/A",
            source_document=None,
            page_number=None,
        )

    if dti_ratio > policy.max_dti_ratio:
        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.FAIL,
            actual_value=f"{dti_ratio:.1f}%",
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason=(
                f"Debt-to-Income ratio ({dti_ratio:.1f}%) exceeds "
                f"maximum policy cap of {policy.max_dti_ratio:.1f}%."
            ),
            evidence=f"DTI: {dti_ratio:.1f}%",
            source_document=None,
            page_number=None,
        )

    return EligibilityRuleResult(
        rule_id=rule_id,
        rule_name=rule_name,
        status=RuleStatus.PASS,
        actual_value=f"{dti_ratio:.1f}%",
        expected_value=expected,
        passed=True,
        severity="MANDATORY",
        reason=(
            f"Debt-to-Income ratio ({dti_ratio:.1f}%) is within "
            f"permissible policy threshold of {policy.max_dti_ratio:.1f}%."
        ),
        evidence=f"DTI: {dti_ratio:.1f}%",
        source_document=None,
        page_number=None,
    )


def evaluate_data_completeness(
    critical_fields_present: Dict[str, Any],
    field_records: Dict[str, ExtractedField],
    policy: EligibilityPolicy,
) -> EligibilityRuleResult:
    """Evaluate whether all critical data fields are present with satisfactory extraction confidence."""
    rule_id = "DATA_COMPLETENESS"
    rule_name = "Critical Data Completeness and Confidence"
    expected = f"All {len(policy.critical_fields)} critical fields present with confidence >= {policy.min_confidence_threshold:.2f}"

    missing_fields: List[str] = []
    low_confidence_fields: List[str] = []

    for f_name in policy.critical_fields:
        val = critical_fields_present.get(f_name)
        if val is None:
            missing_fields.append(f_name)
            continue

        record = field_records.get(f_name)
        if record and record.confidence < policy.min_confidence_threshold:
            low_confidence_fields.append(f"{f_name} ({record.confidence:.2f})")

    if missing_fields or low_confidence_fields:
        issues: List[str] = []
        if missing_fields:
            issues.append(f"Missing critical fields: {', '.join(missing_fields)}")
        if low_confidence_fields:
            issues.append(
                f"Fields with confidence < {policy.min_confidence_threshold:.2f}: {', '.join(low_confidence_fields)}"
            )

        return EligibilityRuleResult(
            rule_id=rule_id,
            rule_name=rule_name,
            status=RuleStatus.REVIEW_REQUIRED,
            actual_value={
                "missing_fields": missing_fields,
                "low_confidence_fields": low_confidence_fields,
            },
            expected_value=expected,
            passed=False,
            severity="MANDATORY",
            reason="; ".join(issues) + ". Manual underwriting review required.",
            evidence="; ".join(issues),
            source_document="applicant_intake",
            page_number=1,
        )

    return EligibilityRuleResult(
        rule_id=rule_id,
        rule_name=rule_name,
        status=RuleStatus.PASS,
        actual_value=f"All {len(policy.critical_fields)} critical fields verified",
        expected_value=expected,
        passed=True,
        severity="MANDATORY",
        reason="All critical applicant data fields are present and satisfy extraction confidence standards.",
        evidence=f"Critical fields: {', '.join(policy.critical_fields)}",
        source_document="applicant_intake",
        page_number=1,
    )
