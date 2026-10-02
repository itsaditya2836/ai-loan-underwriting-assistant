# Stage 4 — Underwriting Eligibility Agent Specification & Report

## 1. Purpose

The **Eligibility Agent** implements deterministic, policy-driven verification of loan applications against predefined underwriting criteria. 

Operating strictly downstream of **Stage 3 (Document Intelligence / Document Intake)**, the Eligibility Agent consumes structured entity extractions (`DocumentPackageResult` or `Applicant` domain models) without directly accessing raw PDFs, running OCR, or performing entity extraction.

The primary objective is to evaluate whether an applicant satisfies baseline policy requirements and return a transparent, explainable result:

```text
ELIGIBLE
INELIGIBLE
REVIEW_REQUIRED
```

> **Explicit Scope Boundary & Responsible AI Notice:**  
> Stage 4 evaluates predefined eligibility criteria only. It does not perform credit-risk prediction, default modeling, fraud detection, cross-document anomaly detection, final loan decisioning (`APPROVE`/`REJECT`/`MANUAL_REVIEW`), or multi-agent orchestration. The output statuses are **eligibility statuses**, NOT final loan decisions.

---

## 2. Centralized Eligibility Policy

Underwriting parameters and criteria are strictly centralized within `app/eligibility/policy.py`. No threshold values or rules are scattered or hardcoded within agent logic.

```python
class EligibilityPolicy(BaseModel):
    policy_version: str = "eligibility_policy_v1"
    min_age: int = 21
    max_age: int = 65
    min_monthly_income: float = 30000.0  # INR
    allowed_employment_types: List[str] = [
        "SALARIED",
        "SELF_EMPLOYED",
        "BUSINESS_OWNER",
    ]
    min_loan_amount: float = 50000.0  # INR
    max_loan_amount: float = 5000000.0  # INR
    min_loan_tenure_months: int = 12
    max_loan_tenure_months: int = 240
    min_credit_score: int = 650
    max_dti_ratio: float = 60.0  # percentage
    min_confidence_threshold: float = 0.75
    required_document_types: List[str] = [
        "loan_application",
        "identity_verification",
        "bank_statement",
    ]
    critical_fields: List[str] = [
        "applicant_id",
        "applicant_name",
        "age",
        "employment_type",
        "monthly_income",
        "credit_score",
        "loan_amount",
        "loan_tenure",
    ]
```

---

## 3. Rules Implemented

| Rule ID | Rule Name | Description | Severity | Expected Condition |
| :--- | :--- | :--- | :--- | :--- |
| `DOCUMENTS_COMPLETE` | Required Documents Completeness | Verifies that all mandatory document types are present in the ingested package | MANDATORY | `documents_missing == []` and `is_complete == True` |
| `MIN_AGE` | Minimum Age Requirement | Evaluates applicant age at application time | MANDATORY | `>= policy.min_age` (21 years) |
| `MAX_AGE` | Maximum Age Requirement | Ensures applicant does not exceed maximum allowable age | MANDATORY | `<= policy.max_age` (65 years) |
| `MIN_MONTHLY_INCOME` | Minimum Monthly Income | Validates declared/verified net monthly earnings | MANDATORY | `>= policy.min_monthly_income` (INR 30,000) |
| `EMPLOYMENT_ELIGIBILITY` | Employment Category Eligibility | Confirms employment category is supported under lending policy | MANDATORY | In `["SALARIED", "SELF_EMPLOYED", "BUSINESS_OWNER"]` |
| `LOAN_AMOUNT_LIMITS` | Loan Amount Policy Limits | Validates requested facility amount against institutional ceilings | MANDATORY | Between INR 50,000 and INR 5,000,000 |
| `LOAN_TENURE_LIMITS` | Loan Tenure Policy Limits | Validates requested repayment term against policy windows | MANDATORY | Between 12 and 240 months |
| `MIN_CREDIT_SCORE` | Minimum Credit Score Threshold | Baseline bureau score eligibility policy rule (not ML risk prediction) | MANDATORY | `>= policy.min_credit_score` (650) |
| `MAX_DTI_RATIO` | Debt-to-Income (DTI) Cap | Limits existing monthly obligations relative to monthly income | MANDATORY | `<= policy.max_dti_ratio` (60.0%) |
| `DATA_COMPLETENESS` | Critical Data Completeness & Confidence | Verifies presence and extraction reliability for all critical attributes | MANDATORY | All critical fields present with confidence `>= 0.75` |

---

## 4. Rule Evaluation Design

Each rule is implemented as an isolated, deterministic function in `app/eligibility/rules.py` returning an `EligibilityRuleResult`:

```python
class EligibilityRuleResult(BaseModel):
    rule_id: str
    rule_name: str
    status: RuleStatus  # PASS, FAIL, or REVIEW_REQUIRED
    actual_value: Any
    expected_value: Any
    passed: bool
    severity: str  # MANDATORY or ADVISORY
    reason: str
    evidence: Optional[str]
    source_document: Optional[str]
    page_number: Optional[int]
```

### Traceability and Provenance
When evaluating output from Stage 3 `DocumentPackageResult`, each rule preserves the originating document name, page number, and text excerpt from the underlying `ExtractedField`.

---

## 5. Confidence Handling

Deterministic entity extraction from OCR or digital PDF reading produces a confidence score `[0.0, 1.0]`.

- If extraction confidence for a critical eligibility field is `>= policy.min_confidence_threshold` (0.75), the value is accepted for policy evaluation.
- If confidence is `< 0.75` (e.g. smudged text or noisy OCR), the field is **not silently replaced or guessed**. Instead, the rule produces `RuleStatus.REVIEW_REQUIRED`, signaling that a human underwriter must inspect the document.

---

## 6. Missing-Data & Document Behavior

1. **Missing Documents**:
   - If an expected document is omitted (such as in test cohort `APP0016`–`APP0020`), the `DOCUMENTS_COMPLETE` rule returns `RuleStatus.REVIEW_REQUIRED`.
   - **Crucial Distinction**: Missing documents are **never classified as fraud or rejected automatically**. They are flagged for document collection follow-up or underwriter verification.
2. **Missing Fields**:
   - If a critical field (e.g. `age`, `credit_score`, `monthly_income`) is absent, the rule evaluating that criterion returns `RuleStatus.REVIEW_REQUIRED` with an explicit reason citing the missing attribute.

---

## 7. Status Aggregation Logic

The overall `EligibilityResult.status` is deterministically aggregated from individual rule outcomes:

```text
Any MANDATORY rule status == FAIL?
  ├── YES ──> Status: INELIGIBLE (eligible = False)
  └── NO  ──> Any rule status == REVIEW_REQUIRED?
                ├── YES ──> Status: REVIEW_REQUIRED (eligible = False)
                └── NO  ──> Status: ELIGIBLE (eligible = True)
```

### Precedence Principle
- **Definitive Failure Takes Precedence**: If an applicant has a definitive policy breach (e.g. credit score 545 < 650) and also has a missing document, the status is `INELIGIBLE`. Underwriting policy rejects outright disqualifications without needing follow-up document chasing.
- **Review Required**: Only applications with no definitive policy failures but containing missing documents, low extraction confidence, or unverified fields receive `REVIEW_REQUIRED`.
- **Eligible**: Only applications where all mandatory criteria pass and data integrity is verified receive `ELIGIBLE`.

---

## 8. Policy Versioning

To ensure regulatory compliance and immutable audit trails, every evaluation embeds:
- `policy_version`: e.g. `"eligibility_policy_v1"`
- Complete snapshot of rules evaluated, pass/fail/review counts, and granular timestamps.

---

## 9. Architectural Integration

The `EligibilityAgent` wraps `EligibilityEvaluator` to preserve agent modularity:

```text
DocumentPackageResult (Stage 3)
           │
           ▼
   EligibilityAgent (Thin Wrapper)
           │
           ▼
  EligibilityEvaluator (Engine)
           │
           ├── Policy Lookups (EligibilityPolicy)
           ├── Rule Functions (app/eligibility/rules.py)
           ├── DTI & Affordability Calculations
           └── Precedence-Based Aggregation
           │
           ▼
   EligibilityResult
```

### Zero Hardcoded Applicant Logic
All logic operates strictly on applicant attributes, extracted entity values, and policy configuration. No conditional branches reference applicant identifiers (`APP0001`, `APP0016`, etc.).

---

## 10. Evaluation Results

The evaluation benchmark script `scripts/evaluate_eligibility.py` executed across both the 30 document packages (Stage 3 intake) and the full 100 synthetic applicant dataset:

### Part 1: Document Packages (Stage 3 Intake, N=30)
- **Total Applicants**: 30
- **ELIGIBLE**: 18 (60.0%)
- **INELIGIBLE**: 8 (26.7%) — Applicants with credit score < 650
- **REVIEW_REQUIRED**: 4 (13.3%) — Applicants with missing physical documents (`APP0016`–`APP0019`)
  *(Note: `APP0020` has both a missing document and credit score 545 < 650; failure precedence correctly classified it as INELIGIBLE).*

#### Cohort Breakdown:
- **APP0001–APP0005 (Consistent Baseline)**: 4 Eligible, 1 Ineligible (`APP0001` credit score 584)
- **APP0006–APP0010 (Income Mismatch Cohort)**: 5 Eligible (Income mismatch is evaluated by the downstream Fraud Agent, not rejected in Stage 4)
- **APP0011–APP0015 (Name Mismatch Cohort)**: 3 Eligible, 2 Ineligible (`APP0012` score 558, `APP0014` score 530)
- **APP0016–APP0020 (Missing Documents Cohort)**: 4 Review Required, 1 Ineligible (`APP0020` score 545)
- **APP0021–APP0025 (Financial Inconsistency Cohort)**: 2 Eligible, 3 Ineligible (`APP0021` score 548, `APP0023` score 612, `APP0024` score 589)
- **APP0026–APP0030 (Borderline Cohort)**: 4 Eligible, 1 Ineligible (`APP0027` score 638)

#### Rule Pass Rates:
- `DOCUMENTS_COMPLETE`: 25 Passed (83.3%), 5 Review Required (16.7%)
- `MIN_CREDIT_SCORE`: 22 Passed (73.3%), 8 Failed (26.7%)
- `MIN_AGE`, `MAX_AGE`, `MIN_MONTHLY_INCOME`, `EMPLOYMENT_ELIGIBILITY`, `LOAN_AMOUNT_LIMITS`, `LOAN_TENURE_LIMITS`, `MAX_DTI_RATIO`, `DATA_COMPLETENESS`: 100% Passed.

### Part 2: Full Synthetic Dataset (N=100)
- **Total Applicants**: 100
- **ELIGIBLE**: 72 (72.0%)
- **INELIGIBLE**: 28 (28.0%) — 28 applicants with credit score < 650, 2 with monthly income < INR 30,000
- **REVIEW_REQUIRED**: 0 (0.0%) — All records structurally complete

---

## 11. Test Coverage & Quality Verification

All 76 tests in the test suite pass cleanly:

```bash
$ .venv/bin/pytest tests/
============================== 76 passed in 3.52s ==============================

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/black --check .
All done! ✨ 🍰 ✨
55 files would be left unchanged.
```

---

## 12. Limitations & Next Steps

1. **Credit Score as Policy vs. Risk Prediction**: Stage 4 evaluates credit score solely as a binary eligibility threshold (`>= 650`). It does not model default probability, credit loss distributions, or risk tiers.
2. **Document Inconsistencies**: Cross-document variances (such as salary slip vs. bank statement credit) are preserved without disqualification. Stage 6 (Fraud / Anomaly Agent) will handle cross-document discrepancy detection.
3. **Next Stage**: **Stage 5 — Risk Assessment Agent** will implement statistical risk scoring and a default prediction model.
