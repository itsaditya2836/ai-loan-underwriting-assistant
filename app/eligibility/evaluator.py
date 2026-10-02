"""Centralized Underwriting Eligibility Evaluator.

Coordinates deterministic rule evaluation, provenance tracing, DTI
computation, and aggregation into an explainable EligibilityResult.
"""

from typing import Any, Dict, List, Optional, Union

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
    DocumentPackageResult,
    EligibilityResult,
    EligibilityRuleResult,
    EligibilityStatus,
    ExtractedField,
    RuleStatus,
)
from app.utils.helpers import get_logger

logger = get_logger(__name__)


class EligibilityEvaluator:
    """Deterministic loan eligibility evaluation engine.

    Evaluates structured data from Stage 3 document intelligence or Applicant profiles
    against an underwriting policy. Does not perform OCR, PDF reading, ML risk scoring,
    or fraud prediction.
    """

    def __init__(self, policy: Optional[EligibilityPolicy] = None) -> None:
        """Initialize the evaluator with a configurable policy."""
        self.policy = policy or EligibilityPolicy.default_policy()
        logger.info(
            "EligibilityEvaluator initialized with policy version '%s'.",
            self.policy.policy_version,
        )

    def evaluate(
        self, target: Union[DocumentPackageResult, Applicant, Dict[str, Any]]
    ) -> EligibilityResult:
        """Evaluate eligibility for a document package, applicant model, or raw data dict."""
        if isinstance(target, DocumentPackageResult):
            return self.evaluate_package(target)
        if isinstance(target, Applicant):
            return self.evaluate_applicant(target)
        if isinstance(target, dict):
            return self._evaluate_dict(target)
        raise TypeError(
            f"Unsupported target type for eligibility evaluation: {type(target).__name__}"
        )

    def evaluate_applicant(self, applicant: Applicant) -> EligibilityResult:
        """Evaluate a structured Applicant model directly."""
        fields_present: Dict[str, Any] = {
            "applicant_id": applicant.applicant_id,
            "applicant_name": applicant.name,
            "age": applicant.age,
            "employment_type": (
                applicant.employment_type.value
                if hasattr(applicant.employment_type, "value")
                else str(applicant.employment_type)
            ),
            "monthly_income": applicant.monthly_income,
            "existing_emi": applicant.existing_emi,
            "credit_score": applicant.credit_score,
            "loan_amount": applicant.loan_amount,
            "loan_tenure": applicant.loan_tenure,
            "bank_balance": applicant.bank_balance,
        }

        # Convert directly to ExtractedFields with confidence=1.0 for manual/direct profiles
        field_records: Dict[str, ExtractedField] = {
            name: ExtractedField(
                field_name=name,
                value=val,
                confidence=1.0,
                source_document="applicant_profile",
                page_number=1,
                evidence=f"{name}={val}",
            )
            for name, val in fields_present.items()
            if val is not None
        }

        # For direct applicant profiles, documents are treated as provided/verified
        documents_found = [
            "loan_application",
            "identity_verification",
            "bank_statement",
        ]
        documents_missing: List[str] = []
        is_complete = True

        return self._run_evaluation(
            applicant_id=applicant.applicant_id,
            fields=fields_present,
            field_records=field_records,
            documents_found=documents_found,
            documents_missing=documents_missing,
            is_complete=is_complete,
        )

    def evaluate_package(self, package: DocumentPackageResult) -> EligibilityResult:
        """Evaluate structured output from Stage 3 Document Intelligence."""
        # 1. Resolve flat and classified fields
        extracted = package.all_extracted_fields

        # Helper to search in package extracted fields
        def get_field(names: List[str]) -> Optional[ExtractedField]:
            for n in names:
                if n in extracted:
                    return extracted[n]
            # Search within individual document records
            for doc in package.documents_found:
                for n in names:
                    if n in doc.extracted_fields:
                        return doc.extracted_fields[n]
            return None

        # Resolve core applicant attributes
        ef_id = get_field(["applicant_id"])
        applicant_id = (
            str(ef_id.value) if ef_id and ef_id.value else package.applicant_id
        )

        ef_name = get_field(["applicant_name", "employee_name", "account_holder"])
        name = ef_name.value if ef_name else None

        ef_age = get_field(["age"])
        age: Optional[int] = None
        if ef_age and ef_age.value is not None:
            try:
                age = int(ef_age.value)
            except (ValueError, TypeError):
                age = None

        ef_emp = get_field(["employment_type"])
        emp_type = str(ef_emp.value) if ef_emp and ef_emp.value else None

        ef_inc = get_field(
            ["declared_monthly_income", "monthly_income", "net_salary", "net_income"]
        )
        monthly_income: Optional[float] = None
        if ef_inc and ef_inc.value is not None:
            try:
                monthly_income = float(ef_inc.value)
            except (ValueError, TypeError):
                monthly_income = None

        ef_emi = get_field(["declared_existing_emi", "existing_emi", "emi_debit"])
        existing_emi: Optional[float] = None
        if ef_emi and ef_emi.value is not None:
            try:
                existing_emi = float(ef_emi.value)
            except (ValueError, TypeError):
                existing_emi = None

        ef_score = get_field(["credit_score"])
        credit_score: Optional[int] = None
        if ef_score and ef_score.value is not None:
            try:
                credit_score = int(ef_score.value)
            except (ValueError, TypeError):
                credit_score = None

        ef_loan = get_field(["loan_amount"])
        loan_amount: Optional[float] = None
        if ef_loan and ef_loan.value is not None:
            try:
                loan_amount = float(ef_loan.value)
            except (ValueError, TypeError):
                loan_amount = None

        ef_tenure = get_field(["loan_tenure"])
        loan_tenure: Optional[int] = None
        if ef_tenure and ef_tenure.value is not None:
            try:
                loan_tenure = int(ef_tenure.value)
            except (ValueError, TypeError):
                loan_tenure = None

        ef_bal = get_field(["declared_bank_balance", "bank_balance", "closing_balance"])
        bank_balance: Optional[float] = None
        if ef_bal and ef_bal.value is not None:
            try:
                bank_balance = float(ef_bal.value)
            except (ValueError, TypeError):
                bank_balance = None

        fields_present: Dict[str, Any] = {
            "applicant_id": applicant_id,
            "applicant_name": name,
            "age": age,
            "employment_type": emp_type,
            "monthly_income": monthly_income,
            "existing_emi": existing_emi,
            "credit_score": credit_score,
            "loan_amount": loan_amount,
            "loan_tenure": loan_tenure,
            "bank_balance": bank_balance,
        }

        field_records: Dict[str, ExtractedField] = {}
        if ef_id:
            field_records["applicant_id"] = ef_id
        if ef_name:
            field_records["applicant_name"] = ef_name
        if ef_age:
            field_records["age"] = ef_age
        if ef_emp:
            field_records["employment_type"] = ef_emp
        if ef_inc:
            field_records["monthly_income"] = ef_inc
        if ef_emi:
            field_records["existing_emi"] = ef_emi
        if ef_score:
            field_records["credit_score"] = ef_score
        if ef_loan:
            field_records["loan_amount"] = ef_loan
        if ef_tenure:
            field_records["loan_tenure"] = ef_tenure
        if ef_bal:
            field_records["bank_balance"] = ef_bal

        found_types = [doc.document_type for doc in package.documents_found]

        return self._run_evaluation(
            applicant_id=applicant_id,
            fields=fields_present,
            field_records=field_records,
            documents_found=found_types,
            documents_missing=package.documents_missing,
            is_complete=package.is_complete,
        )

    def _evaluate_dict(self, data: Dict[str, Any]) -> EligibilityResult:
        """Evaluate raw applicant data dictionary."""
        applicant_id = str(data.get("applicant_id", "UNKNOWN"))
        fields_present: Dict[str, Any] = {
            "applicant_id": applicant_id,
            "applicant_name": data.get("name") or data.get("applicant_name"),
            "age": data.get("age"),
            "employment_type": data.get("employment_type"),
            "monthly_income": data.get("monthly_income")
            or data.get("declared_monthly_income"),
            "existing_emi": data.get("existing_emi")
            or data.get("declared_existing_emi"),
            "credit_score": data.get("credit_score"),
            "loan_amount": data.get("loan_amount"),
            "loan_tenure": data.get("loan_tenure"),
            "bank_balance": data.get("bank_balance")
            or data.get("declared_bank_balance"),
        }
        field_records: Dict[str, ExtractedField] = {}
        for k, v in fields_present.items():
            if v is not None:
                field_records[k] = ExtractedField(
                    field_name=k,
                    value=v,
                    confidence=1.0,
                    source_document="raw_input",
                    page_number=1,
                    evidence=f"{k}={v}",
                )

        documents_found = data.get("documents_found", ["loan_application"])
        documents_missing = data.get("documents_missing", [])
        is_complete = len(documents_missing) == 0

        return self._run_evaluation(
            applicant_id=applicant_id,
            fields=fields_present,
            field_records=field_records,
            documents_found=documents_found,
            documents_missing=documents_missing,
            is_complete=is_complete,
        )

    def _run_evaluation(
        self,
        applicant_id: str,
        fields: Dict[str, Any],
        field_records: Dict[str, ExtractedField],
        documents_found: List[str],
        documents_missing: List[str],
        is_complete: bool,
    ) -> EligibilityResult:
        """Execute all deterministic rules and aggregate into an EligibilityResult."""
        rule_results: List[EligibilityRuleResult] = []

        # 1. Required Documents Rule
        r_docs = evaluate_documents_complete(
            documents_missing=documents_missing,
            documents_found=documents_found,
            is_complete=is_complete,
            policy=self.policy,
        )
        rule_results.append(r_docs)

        # 2. Minimum Age
        r_min_age = evaluate_min_age(
            age=fields.get("age"),
            field_record=field_records.get("age"),
            policy=self.policy,
        )
        rule_results.append(r_min_age)

        # 3. Maximum Age
        r_max_age = evaluate_max_age(
            age=fields.get("age"),
            field_record=field_records.get("age"),
            policy=self.policy,
        )
        rule_results.append(r_max_age)

        # 4. Minimum Monthly Income
        r_inc = evaluate_min_monthly_income(
            monthly_income=fields.get("monthly_income"),
            field_record=field_records.get("monthly_income"),
            policy=self.policy,
        )
        rule_results.append(r_inc)

        # 5. Employment Eligibility
        r_emp = evaluate_employment_eligibility(
            employment_type=fields.get("employment_type"),
            field_record=field_records.get("employment_type"),
            policy=self.policy,
        )
        rule_results.append(r_emp)

        # 6. Loan Amount Limits
        r_amt = evaluate_loan_amount_limits(
            loan_amount=fields.get("loan_amount"),
            field_record=field_records.get("loan_amount"),
            policy=self.policy,
        )
        rule_results.append(r_amt)

        # 7. Loan Tenure Limits
        r_ten = evaluate_loan_tenure_limits(
            loan_tenure=fields.get("loan_tenure"),
            field_record=field_records.get("loan_tenure"),
            policy=self.policy,
        )
        rule_results.append(r_ten)

        # 8. Minimum Credit Score
        r_score = evaluate_min_credit_score(
            credit_score=fields.get("credit_score"),
            field_record=field_records.get("credit_score"),
            policy=self.policy,
        )
        rule_results.append(r_score)

        # Calculate DTI Ratio
        dti_ratio: Optional[float] = None
        monthly_income = fields.get("monthly_income")
        existing_emi = fields.get("existing_emi")
        if monthly_income and monthly_income > 0:
            emi_val = existing_emi if existing_emi is not None else 0.0
            dti_ratio = round((emi_val / monthly_income) * 100.0, 2)

        # 9. Maximum DTI Ratio
        r_dti = evaluate_max_dti_ratio(
            dti_ratio=dti_ratio,
            policy=self.policy,
        )
        rule_results.append(r_dti)

        # 10. Data Completeness & Confidence
        r_complete = evaluate_data_completeness(
            critical_fields_present=fields,
            field_records=field_records,
            policy=self.policy,
        )
        rule_results.append(r_complete)

        # Calculate Max Eligible Amount
        max_eligible_amount: Optional[float] = None
        if monthly_income and monthly_income > 0:
            tenure_months = fields.get("loan_tenure") or 60
            max_emi_capacity = (
                monthly_income * (self.policy.max_dti_ratio / 100.0)
            ) - (existing_emi or 0.0)
            if max_emi_capacity > 0:
                # Standard loan affordability estimate at benchmark 10.5% p.a.
                r = 0.105 / 12.0
                n = tenure_months
                factor = ((1.0 + r) ** n - 1.0) / (r * ((1.0 + r) ** n))
                estimated_max = max_emi_capacity * factor
                max_eligible_amount = round(
                    min(estimated_max, self.policy.max_loan_amount), 2
                )
            else:
                max_eligible_amount = 0.0

        # Aggregation Logic
        rules_evaluated = [r.rule_id for r in rule_results]
        rules_passed = [r.rule_id for r in rule_results if r.status == RuleStatus.PASS]
        rules_failed = [r.rule_id for r in rule_results if r.status == RuleStatus.FAIL]
        rules_requiring_review = [
            r.rule_id for r in rule_results if r.status == RuleStatus.REVIEW_REQUIRED
        ]

        if len(rules_failed) > 0:
            status = EligibilityStatus.INELIGIBLE
            eligible = False
            reasons = [r.reason for r in rule_results if r.status == RuleStatus.FAIL]
        elif len(rules_requiring_review) > 0:
            status = EligibilityStatus.REVIEW_REQUIRED
            eligible = False
            reasons = [
                r.reason for r in rule_results if r.status == RuleStatus.REVIEW_REQUIRED
            ]
        else:
            status = EligibilityStatus.ELIGIBLE
            eligible = True
            reasons = [
                f"Applicant satisfies all {len(rules_passed)} underwriting eligibility criteria under policy {self.policy.policy_version}."
            ]

        # Evidence aggregation
        evidence_list: List[Dict[str, Any]] = [
            {
                "rule_id": r.rule_id,
                "evidence": r.evidence,
                "source_document": r.source_document,
                "page_number": r.page_number,
            }
            for r in rule_results
            if r.evidence
        ]

        # Summary remarks
        remarks = (
            f"Status: {status.value}. Rules passed: {len(rules_passed)}/{len(rules_evaluated)}. "
            f"Policy: {self.policy.policy_version}. "
            f"DTI: {f'{dti_ratio:.1f}%' if dti_ratio is not None else 'N/A'}. "
            f"Max eligible amount: {f'INR {max_eligible_amount:,.2f}' if max_eligible_amount is not None else 'N/A'}."
        )

        return EligibilityResult(
            applicant_id=applicant_id,
            status=status,
            eligible=eligible,
            is_eligible=eligible,
            rules_evaluated=rules_evaluated,
            rules_passed=rules_passed,
            rules_failed=rules_failed,
            rules_requiring_review=rules_requiring_review,
            passed_rules=rules_passed,
            failed_rules=rules_failed,
            rule_results=rule_results,
            reasons=reasons,
            evidence=evidence_list,
            policy_version=self.policy.policy_version,
            max_eligible_amount=max_eligible_amount,
            dti_ratio=dti_ratio,
            remarks=remarks,
        )
