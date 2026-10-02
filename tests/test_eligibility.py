"""Tests for Underwriting Eligibility Agent and Rules Engine.

Verifies:
- Configurable EligibilityPolicy defaults and custom parameters
- Individual deterministic rules (Age, Income, Employment, Loan Amount, Tenure, Credit Score, DTI)
- Document completeness evaluation (missing documents -> REVIEW_REQUIRED)
- Critical data completeness and confidence handling (< 0.75 -> REVIEW_REQUIRED)
- Deterministic aggregation (ELIGIBLE, INELIGIBLE, REVIEW_REQUIRED)
- Explainability, evidence provenance, and rule remarks
- End-to-end evaluation using Stage 3 DocumentPackageResult on synthetic cohorts
"""

import os

import pytest

from app.agents.eligibility_agent import EligibilityAgent
from app.document_processing.document_package import DocumentPackageProcessor
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
from app.schemas.applicant import (
    Applicant,
    ClassifiedDocument,
    DocumentPackageResult,
    EligibilityResult,
    EligibilityRuleResult,
    EligibilityStatus,
    ExtractedField,
    RuleStatus,
)


@pytest.fixture
def sample_applicant() -> Applicant:
    """Standard eligible applicant fixture."""
    return Applicant(
        applicant_id="app_001",
        name="Alex Mercer",
        age=32,
        employment_type="Salaried",
        employment_years=5.5,
        monthly_income=75000.0,
        existing_emi=15000.0,
        loan_amount=500000.0,
        loan_tenure=36,
        credit_score=750,
        bank_balance=120000.0,
    )


@pytest.fixture
def default_policy() -> EligibilityPolicy:
    """Default underwriting policy fixture."""
    return EligibilityPolicy()


# ---------------------------------------------------------------------------
# Schema and Policy Baseline Tests
# ---------------------------------------------------------------------------


def test_applicant_schema_validation(sample_applicant: Applicant):
    """Verify Applicant Pydantic model instantiates with correct types and constraints."""
    assert sample_applicant.applicant_id == "app_001"
    assert sample_applicant.name == "Alex Mercer"
    assert sample_applicant.monthly_income == 75000.0
    assert sample_applicant.credit_score == 750


def test_applicant_schema_constraints():
    """Verify Applicant Pydantic model enforces age boundaries."""
    with pytest.raises(Exception):
        Applicant(
            applicant_id="app_err",
            name="Young Applicant",
            age=16,
            employment_type="Salaried",
            employment_years=1.0,
            monthly_income=50000.0,
            existing_emi=0.0,
            loan_amount=100000.0,
            loan_tenure=12,
            credit_score=700,
            bank_balance=10000.0,
        )


def test_eligibility_result_schema_and_sync():
    """Verify EligibilityResult schema backwards compatibility and legacy field syncing."""
    result = EligibilityResult(
        is_eligible=True,
        passed_rules=["MIN_INCOME_MET", "DTI_WITHIN_LIMIT"],
        failed_rules=[],
        max_eligible_amount=600000.0,
        dti_ratio=20.0,
        remarks="Eligible under standard policy.",
    )
    assert result.is_eligible is True
    assert result.eligible is True
    assert result.status == EligibilityStatus.ELIGIBLE
    assert len(result.passed_rules) == 2
    assert len(result.rules_passed) == 2
    assert result.max_eligible_amount == 600000.0


def test_policy_defaults_and_customization():
    """Verify default policy values and ability to customize thresholds."""
    policy = EligibilityPolicy()
    assert policy.min_age == 21
    assert policy.max_age == 65
    assert policy.min_monthly_income == 30000.0
    assert policy.min_credit_score == 650
    assert policy.min_confidence_threshold == 0.75
    assert policy.policy_version == "eligibility_policy_v1"

    custom = EligibilityPolicy(
        min_age=25,
        min_credit_score=700,
        policy_version="custom_tier_2026",
    )
    assert custom.min_age == 25
    assert custom.min_credit_score == 700
    assert custom.policy_version == "custom_tier_2026"


# ---------------------------------------------------------------------------
# Individual Rule Evaluations
# ---------------------------------------------------------------------------


def test_min_age_rule(default_policy: EligibilityPolicy):
    """Verify MIN_AGE evaluation against policy threshold."""
    # Pass: exactly at boundary
    res_pass = evaluate_min_age(21, None, default_policy)
    assert res_pass.status == RuleStatus.PASS
    assert res_pass.passed is True

    # Fail: below boundary
    res_fail = evaluate_min_age(20, None, default_policy)
    assert res_fail.status == RuleStatus.FAIL
    assert res_fail.passed is False
    assert "below configured policy minimum" in res_fail.reason

    # Missing value -> REVIEW_REQUIRED
    res_missing = evaluate_min_age(None, None, default_policy)
    assert res_missing.status == RuleStatus.REVIEW_REQUIRED
    assert res_missing.passed is False


def test_max_age_rule(default_policy: EligibilityPolicy):
    """Verify MAX_AGE evaluation against policy threshold."""
    res_pass = evaluate_max_age(65, None, default_policy)
    assert res_pass.status == RuleStatus.PASS
    assert res_pass.passed is True

    res_fail = evaluate_max_age(66, None, default_policy)
    assert res_fail.status == RuleStatus.FAIL
    assert res_fail.passed is False
    assert "exceeds configured policy maximum" in res_fail.reason


def test_min_monthly_income_rule(default_policy: EligibilityPolicy):
    """Verify MIN_MONTHLY_INCOME evaluation against policy threshold."""
    res_pass = evaluate_min_monthly_income(35000.0, None, default_policy)
    assert res_pass.status == RuleStatus.PASS
    assert res_pass.passed is True

    res_fail = evaluate_min_monthly_income(25000.0, None, default_policy)
    assert res_fail.status == RuleStatus.FAIL
    assert res_fail.passed is False
    assert "below configured policy minimum" in res_fail.reason

    res_missing = evaluate_min_monthly_income(None, None, default_policy)
    assert res_missing.status == RuleStatus.REVIEW_REQUIRED


def test_employment_eligibility_rule(default_policy: EligibilityPolicy):
    """Verify EMPLOYMENT_ELIGIBILITY against permitted categories."""
    assert (
        evaluate_employment_eligibility("Salaried", None, default_policy).passed is True
    )
    assert (
        evaluate_employment_eligibility("SELF_EMPLOYED", None, default_policy).passed
        is True
    )
    assert (
        evaluate_employment_eligibility("Business Owner", None, default_policy).passed
        is True
    )

    res_fail = evaluate_employment_eligibility("Student", None, default_policy)
    assert res_fail.status == RuleStatus.FAIL
    assert res_fail.passed is False
    assert "not supported" in res_fail.reason


def test_loan_amount_limits_rule(default_policy: EligibilityPolicy):
    """Verify LOAN_AMOUNT_LIMITS against lower and upper boundaries."""
    # Pass within bounds
    assert evaluate_loan_amount_limits(500000.0, None, default_policy).passed is True

    # Below min
    res_low = evaluate_loan_amount_limits(40000.0, None, default_policy)
    assert res_low.status == RuleStatus.FAIL
    assert "below minimum policy limit" in res_low.reason

    # Above max
    res_high = evaluate_loan_amount_limits(6000000.0, None, default_policy)
    assert res_high.status == RuleStatus.FAIL
    assert "exceeds maximum policy limit" in res_high.reason


def test_loan_tenure_limits_rule(default_policy: EligibilityPolicy):
    """Verify LOAN_TENURE_LIMITS against lower and upper boundaries."""
    assert evaluate_loan_tenure_limits(36, None, default_policy).passed is True

    res_low = evaluate_loan_tenure_limits(6, None, default_policy)
    assert res_low.status == RuleStatus.FAIL

    res_high = evaluate_loan_tenure_limits(300, None, default_policy)
    assert res_high.status == RuleStatus.FAIL


def test_min_credit_score_rule(default_policy: EligibilityPolicy):
    """Verify MIN_CREDIT_SCORE against baseline threshold."""
    res_pass = evaluate_min_credit_score(720, None, default_policy)
    assert res_pass.status == RuleStatus.PASS
    assert res_pass.passed is True

    res_fail = evaluate_min_credit_score(620, None, default_policy)
    assert res_fail.status == RuleStatus.FAIL
    assert res_fail.passed is False
    assert "below the configured eligibility threshold" in res_fail.reason


def test_max_dti_ratio_rule(default_policy: EligibilityPolicy):
    """Verify MAX_DTI_RATIO against policy cap."""
    res_pass = evaluate_max_dti_ratio(35.0, default_policy)
    assert res_pass.status == RuleStatus.PASS
    assert res_pass.passed is True

    res_fail = evaluate_max_dti_ratio(68.5, default_policy)
    assert res_fail.status == RuleStatus.FAIL
    assert res_fail.passed is False
    assert "exceeds maximum policy cap" in res_fail.reason


# ---------------------------------------------------------------------------
# Document Completeness and Confidence Handling
# ---------------------------------------------------------------------------


def test_documents_completeness_evaluation(default_policy: EligibilityPolicy):
    """Verify document package evaluation distinguishes complete from incomplete packages."""
    # Complete
    res_comp = evaluate_documents_complete(
        documents_missing=[],
        documents_found=["loan_application", "salary_slip", "bank_statement"],
        is_complete=True,
        policy=default_policy,
    )
    assert res_comp.status == RuleStatus.PASS
    assert res_comp.passed is True

    # Missing documents -> REVIEW_REQUIRED (Never classified as fraud)
    res_missing = evaluate_documents_complete(
        documents_missing=["bank_statement"],
        documents_found=["loan_application", "salary_slip"],
        is_complete=False,
        policy=default_policy,
    )
    assert res_missing.status == RuleStatus.REVIEW_REQUIRED
    assert res_missing.passed is False
    assert "bank_statement" in res_missing.reason
    assert "fraud" not in res_missing.reason.lower()


def test_extraction_confidence_threshold_enforcement(default_policy: EligibilityPolicy):
    """Verify extraction confidence below threshold (0.75) triggers REVIEW_REQUIRED."""
    # High confidence field
    ef_high = ExtractedField(
        field_name="monthly_income",
        value=85000.0,
        confidence=0.98,
        source_document="salary_slip.pdf",
        page_number=1,
        evidence="Net Salary: INR 85,000",
    )
    res_high = evaluate_min_monthly_income(85000.0, ef_high, default_policy)
    assert res_high.status == RuleStatus.PASS
    assert res_high.passed is True
    assert res_high.source_document == "salary_slip.pdf"

    # Low confidence field (< 0.75)
    ef_low = ExtractedField(
        field_name="monthly_income",
        value=85000.0,
        confidence=0.55,
        source_document="salary_slip.pdf",
        page_number=1,
        evidence="Net Salary: INR 85,000 (smudged OCR)",
    )
    res_low = evaluate_min_monthly_income(85000.0, ef_low, default_policy)
    assert res_low.status == RuleStatus.REVIEW_REQUIRED
    assert res_low.passed is False
    assert "below required threshold" in res_low.reason


def test_data_completeness_critical_fields(default_policy: EligibilityPolicy):
    """Verify all critical fields check detects missing attributes."""
    present_fields = {
        "applicant_id": "APP001",
        "applicant_name": "Test User",
        "age": 30,
        "employment_type": "SALARIED",
        "monthly_income": 50000.0,
        "credit_score": 750,
        "loan_amount": 300000.0,
        "loan_tenure": 24,
    }
    field_records = {}

    res_pass = evaluate_data_completeness(present_fields, field_records, default_policy)
    assert res_pass.status == RuleStatus.PASS
    assert res_pass.passed is True

    # Missing credit_score
    incomplete_fields = dict(present_fields)
    incomplete_fields["credit_score"] = None
    res_missing = evaluate_data_completeness(
        incomplete_fields, field_records, default_policy
    )
    assert res_missing.status == RuleStatus.REVIEW_REQUIRED
    assert res_missing.passed is False
    assert "credit_score" in res_missing.reason


# ---------------------------------------------------------------------------
# Aggregation Logic Tests
# ---------------------------------------------------------------------------


def test_aggregation_eligible(sample_applicant: Applicant):
    """Verify that an applicant passing all rules is aggregated as ELIGIBLE."""
    evaluator = EligibilityEvaluator()
    result = evaluator.evaluate(sample_applicant)

    assert result.status == EligibilityStatus.ELIGIBLE
    assert result.eligible is True
    assert result.is_eligible is True
    assert len(result.rules_failed) == 0
    assert len(result.rules_requiring_review) == 0
    assert len(result.rules_passed) > 0
    assert result.max_eligible_amount is not None
    assert result.dti_ratio == 20.0
    assert result.policy_version == "eligibility_policy_v1"


def test_aggregation_ineligible(sample_applicant: Applicant):
    """Verify that an applicant failing a mandatory rule is aggregated as INELIGIBLE."""
    evaluator = EligibilityEvaluator()
    # Credit score below threshold
    sample_applicant.credit_score = 580
    result = evaluator.evaluate(sample_applicant)

    assert result.status == EligibilityStatus.INELIGIBLE
    assert result.eligible is False
    assert result.is_eligible is False
    assert "MIN_CREDIT_SCORE" in result.rules_failed
    assert len(result.reasons) > 0


def test_aggregation_review_required():
    """Verify that missing documents result in REVIEW_REQUIRED status."""
    package = DocumentPackageResult(
        applicant_id="APP_REV",
        package_dir="/dummy/dir",
        documents_found=[
            ClassifiedDocument(
                document_id="doc1",
                file_path="/dummy/app.pdf",
                document_type="loan_application",
                classification_confidence=0.98,
                classification_evidence="Loan Application Form",
                extracted_fields={
                    "age": ExtractedField(
                        field_name="age",
                        value=30,
                        confidence=0.95,
                        source_document="app.pdf",
                        evidence="Age: 30",
                    ),
                    "employment_type": ExtractedField(
                        field_name="employment_type",
                        value="SALARIED",
                        confidence=0.95,
                        source_document="app.pdf",
                        evidence="Employment: Salaried",
                    ),
                    "monthly_income": ExtractedField(
                        field_name="monthly_income",
                        value=70000.0,
                        confidence=0.95,
                        source_document="app.pdf",
                        evidence="Income: 70000",
                    ),
                    "credit_score": ExtractedField(
                        field_name="credit_score",
                        value=750,
                        confidence=0.95,
                        source_document="app.pdf",
                        evidence="Score: 750",
                    ),
                    "loan_amount": ExtractedField(
                        field_name="loan_amount",
                        value=500000.0,
                        confidence=0.95,
                        source_document="app.pdf",
                        evidence="Amount: 500000",
                    ),
                    "loan_tenure": ExtractedField(
                        field_name="loan_tenure",
                        value=36,
                        confidence=0.95,
                        source_document="app.pdf",
                        evidence="Tenure: 36",
                    ),
                },
            )
        ],
        documents_missing=["bank_statement", "salary_slip"],
        expected_documents=["loan_application", "salary_slip", "bank_statement"],
        is_complete=False,
    )
    # Populate all_extracted_fields
    package.all_extracted_fields = package.documents_found[0].extracted_fields

    evaluator = EligibilityEvaluator()
    result = evaluator.evaluate(package)

    assert result.status == EligibilityStatus.REVIEW_REQUIRED
    assert result.eligible is False
    assert "DOCUMENTS_COMPLETE" in result.rules_requiring_review
    assert any("missing" in r.lower() for r in result.reasons)


def test_failure_precedence_over_review_required():
    """Verify that a definitive policy failure takes precedence over review required."""
    package = DocumentPackageResult(
        applicant_id="APP_FAIL_REV",
        package_dir="/dummy/dir",
        documents_found=[],
        documents_missing=["bank_statement"],
        expected_documents=["loan_application", "bank_statement"],
        is_complete=False,
        all_extracted_fields={
            "age": ExtractedField(
                field_name="age",
                value=19,  # Under policy minimum 21 -> Definite FAIL
                confidence=0.95,
                source_document="app.pdf",
                evidence="Age: 19",
            ),
            "monthly_income": ExtractedField(
                field_name="monthly_income",
                value=50000.0,
                confidence=0.95,
                source_document="app.pdf",
                evidence="Income: 50000",
            ),
            "credit_score": ExtractedField(
                field_name="credit_score",
                value=700,
                confidence=0.95,
                source_document="app.pdf",
                evidence="Score: 700",
            ),
            "loan_amount": ExtractedField(
                field_name="loan_amount",
                value=200000.0,
                confidence=0.95,
                source_document="app.pdf",
                evidence="Amount: 200000",
            ),
            "loan_tenure": ExtractedField(
                field_name="loan_tenure",
                value=24,
                confidence=0.95,
                source_document="app.pdf",
                evidence="Tenure: 24",
            ),
            "employment_type": ExtractedField(
                field_name="employment_type",
                value="SALARIED",
                confidence=0.95,
                source_document="app.pdf",
                evidence="Type: Salaried",
            ),
        },
    )

    evaluator = EligibilityEvaluator()
    result = evaluator.evaluate(package)

    # Ineligible because MIN_AGE failed
    assert result.status == EligibilityStatus.INELIGIBLE
    assert result.eligible is False
    assert "MIN_AGE" in result.rules_failed
    assert "DOCUMENTS_COMPLETE" in result.rules_requiring_review


def test_explainability_and_evidence(sample_applicant: Applicant):
    """Verify that detailed rule-level evidence and reasoning are recorded in result."""
    agent = EligibilityAgent()
    result = agent.evaluate(sample_applicant)

    assert len(result.rule_results) > 0
    for r in result.rule_results:
        assert isinstance(r, EligibilityRuleResult)
        assert r.rule_id
        assert r.rule_name
        assert r.status in (
            RuleStatus.PASS,
            RuleStatus.FAIL,
            RuleStatus.REVIEW_REQUIRED,
        )
        assert r.reason
        assert r.expected_value is not None

    assert len(result.evidence) > 0
    assert result.remarks is not None
    assert "Status: ELIGIBLE" in result.remarks


# ---------------------------------------------------------------------------
# Synthetic Applicant Cohort Tests (Real Stage 3 Intake -> Eligibility)
# ---------------------------------------------------------------------------


def test_synthetic_applicant_app0001_ineligible():
    """Verify APP0001 (Credit Score 584 < 650) evaluates deterministically to INELIGIBLE."""
    doc_dir = "data/documents/APP0001"
    if not os.path.exists(doc_dir):
        pytest.skip(f"Document directory {doc_dir} not available.")

    processor = DocumentPackageProcessor()
    package = processor.process_package(applicant_id="APP0001", package_dir=doc_dir)

    agent = EligibilityAgent()
    result = agent.evaluate(package)

    assert result.status == EligibilityStatus.INELIGIBLE
    assert result.eligible is False
    assert "MIN_CREDIT_SCORE" in result.rules_failed
    assert any("credit score" in r.lower() for r in result.reasons)


def test_synthetic_applicant_app0003_eligible():
    """Verify APP0003 (Credit Score 788, High Income, Complete Docs) evaluates to ELIGIBLE."""
    doc_dir = "data/documents/APP0003"
    if not os.path.exists(doc_dir):
        pytest.skip(f"Document directory {doc_dir} not available.")

    processor = DocumentPackageProcessor()
    package = processor.process_package(applicant_id="APP0003", package_dir=doc_dir)

    agent = EligibilityAgent()
    result = agent.evaluate(package)

    assert result.status == EligibilityStatus.ELIGIBLE
    assert result.eligible is True
    assert len(result.rules_failed) == 0
    assert result.max_eligible_amount > 0


def test_synthetic_applicant_app0016_review_required():
    """Verify APP0016 (Missing bank statement in Stage 2) evaluates to REVIEW_REQUIRED."""
    doc_dir = "data/documents/APP0016"
    if not os.path.exists(doc_dir):
        pytest.skip(f"Document directory {doc_dir} not available.")

    processor = DocumentPackageProcessor()
    package = processor.process_package(applicant_id="APP0016", package_dir=doc_dir)

    agent = EligibilityAgent()
    result = agent.evaluate(package)

    assert result.status == EligibilityStatus.REVIEW_REQUIRED
    assert result.eligible is False
    assert "DOCUMENTS_COMPLETE" in result.rules_requiring_review
    assert any("bank_statement" in r for r in result.reasons)
