"""Cross-Document Consistency and Anomaly Detection Engine.

Performs deterministic cross-document consistency checks:
- Identity verification (Name consistency across application, identity proof, salary slip, bank statement)
- Income verification (Declared income vs salary slip net pay / bank salary credit)
- Liability verification (Declared existing EMI vs bank statement EMI auto-debits)
- Balance verification (Declared liquid balance vs verified statement closing balance)
- Employer verification (Declared employer vs payroll organization)
"""

from typing import Any, Dict, List, Optional, Tuple, Union

from app.fraud.rules import (
    AnomalyRulesConfig,
    calculate_name_similarity,
    normalize_string,
)
from app.fraud.scoring import AnomalyScorer
from app.schemas.anomaly import AnomalyFlag, AnomalyResult, AnomalySeverity
from app.schemas.applicant import (
    Applicant,
    DocumentPackageResult,
    ExtractedField,
)
from app.utils.helpers import get_logger

logger = get_logger(__name__)


class CrossDocumentAnomalyDetector:
    """Deterministic cross-document inconsistency and anomaly detection engine."""

    def __init__(self, config: Optional[AnomalyRulesConfig] = None) -> None:
        """Initialize detector with centralized rules configuration."""
        self.config = config or AnomalyRulesConfig.default_config()
        self.scorer = AnomalyScorer(config=self.config)
        logger.info(
            "CrossDocumentAnomalyDetector initialized with config '%s'.",
            self.config.config_version,
        )

    def detect_anomalies(
        self,
        target: Union[DocumentPackageResult, Applicant, Dict[str, Any]],
        applicant_profile: Optional[Applicant] = None,
    ) -> AnomalyResult:
        """Detect cross-document discrepancies across all submitted documents and profile.

        Args:
            target: DocumentPackageResult (Stage 3), Applicant model, or raw data dict.
            applicant_profile: Optional reference Applicant model.

        Returns:
            Structured AnomalyResult detailing score, severity, flags, and missing evidence.
        """
        applicant_id, declared_data, doc_fields, missing_docs = self._extract_context(
            target, applicant_profile
        )

        flags: List[AnomalyFlag] = []

        # 1. Identity Consistency (ANOM-ID-001)
        flag_id = self._check_identity_consistency(declared_data, doc_fields)
        if flag_id:
            flags.extend(flag_id)

        # 2. Income Consistency (ANOM-INC-001)
        flag_inc = self._check_income_consistency(declared_data, doc_fields)
        if flag_inc:
            flags.extend(flag_inc)

        # 3. Financial Inconsistency: Undisclosed Liabilities (ANOM-FIN-001)
        flag_emi = self._check_liability_consistency(declared_data, doc_fields)
        if flag_emi:
            flags.extend(flag_emi)

        # 4. Bank Balance Consistency (ANOM-FIN-002)
        flag_bal = self._check_balance_consistency(declared_data, doc_fields)
        if flag_bal:
            flags.extend(flag_bal)

        # 5. Employer Consistency (ANOM-DOC-001)
        flag_emp = self._check_employer_consistency(declared_data, doc_fields)
        if flag_emp:
            flags.extend(flag_emp)

        # Calculate composite score and severity
        score, severity = self.scorer.calculate_score(flags)
        has_anomalies = len(flags) > 0

        # Synthesize explainable summary
        summary = self.scorer.synthesize_summary(
            flags=flags,
            missing_evidence=missing_docs,
            severity=severity,
            score=score,
        )

        return AnomalyResult(
            applicant_id=applicant_id,
            anomaly_score=score,
            severity=severity,
            has_anomalies=has_anomalies,
            flags=flags,
            anomalies_detected=[f.description for f in flags],
            missing_evidence=missing_docs,
            confidence_score=1.0 if not missing_docs else 0.85,
            summary=summary,
            detector_version=self.config.config_version,
        )

    # -----------------------------------------------------------------------
    # Rule Evaluation Methods
    # -----------------------------------------------------------------------

    def _check_identity_consistency(
        self, declared: Dict[str, Any], doc_fields: Dict[str, Dict[str, ExtractedField]]
    ) -> List[AnomalyFlag]:
        """Check for name discrepancies across application and supporting documents (ANOM-ID-001)."""
        flags: List[AnomalyFlag] = []
        decl_name = declared.get("name") or declared.get("applicant_name")
        if not decl_name:
            return flags

        # Check names in each document type
        name_keys = ["applicant_name", "employee_name", "account_holder"]
        for doc_type, fields in doc_fields.items():
            for key in name_keys:
                ef = fields.get(key)
                if ef and ef.value:
                    observed_name = str(ef.value).strip()
                    sim = calculate_name_similarity(decl_name, observed_name)
                    if sim < self.config.name_similarity_threshold:
                        flags.append(
                            AnomalyFlag(
                                rule_id="ANOM-ID-001",
                                anomaly_type="NAME_MISMATCH",
                                severity=AnomalySeverity.HIGH,
                                description=(
                                    f"Identity mismatch detected: Supporting document '{doc_type}' records "
                                    f"name '{observed_name}', which does not match declared applicant name '{decl_name}'."
                                ),
                                expected_value=decl_name,
                                observed_value=observed_name,
                                source_documents=[
                                    "loan_application",
                                    ef.source_document or doc_type,
                                ],
                                evidence=f"Extracted from {ef.source_document} (Page {ef.page_number}): '{ef.evidence}'",
                            )
                        )
                        break  # One flag per document is sufficient

        return flags

    def _check_income_consistency(
        self, declared: Dict[str, Any], doc_fields: Dict[str, Dict[str, ExtractedField]]
    ) -> List[AnomalyFlag]:
        """Check for material income discrepancy between declaration and documents (ANOM-INC-001)."""
        flags: List[AnomalyFlag] = []
        decl_income = declared.get("monthly_income")
        if not decl_income or decl_income <= 0:
            return flags

        # Check Bank Statement Salary Credit
        bank_fields = doc_fields.get("bank_statement", {})
        ef_cred = bank_fields.get("salary_credit")
        if ef_cred and ef_cred.value is not None:
            cred_val = float(ef_cred.value)
            if cred_val < decl_income:
                pct_diff = ((decl_income - cred_val) / decl_income) * 100.0
                if pct_diff > self.config.income_discrepancy_threshold_pct:
                    sev = (
                        AnomalySeverity.HIGH
                        if pct_diff >= 30.0
                        else AnomalySeverity.MEDIUM
                    )
                    flags.append(
                        AnomalyFlag(
                            rule_id="ANOM-INC-001",
                            anomaly_type="INCOME_MISMATCH",
                            severity=sev,
                            description=(
                                f"Income discrepancy detected: Declared monthly income (INR {decl_income:,.2f}) "
                                f"materially exceeds verified bank statement recurring salary credit (INR {cred_val:,.2f}) "
                                f"by {pct_diff:.1f}%."
                            ),
                            expected_value=f"INR {decl_income:,.2f}",
                            observed_value=f"INR {cred_val:,.2f}",
                            source_documents=[
                                "loan_application",
                                ef_cred.source_document or "bank_statement",
                            ],
                            evidence=f"Bank statement credit excerpt: '{ef_cred.evidence}'",
                        )
                    )

        # Check Salary Slip Net Salary (if bank statement did not already flag)
        salary_fields = doc_fields.get("salary_slip", {})
        ef_sal = salary_fields.get("net_salary")
        if ef_sal and ef_sal.value is not None and not flags:
            sal_val = float(ef_sal.value)
            if sal_val < decl_income:
                pct_diff = ((decl_income - sal_val) / decl_income) * 100.0
                if pct_diff > self.config.income_discrepancy_threshold_pct:
                    sev = (
                        AnomalySeverity.HIGH
                        if pct_diff >= 30.0
                        else AnomalySeverity.MEDIUM
                    )
                    flags.append(
                        AnomalyFlag(
                            rule_id="ANOM-INC-001",
                            anomaly_type="INCOME_MISMATCH",
                            severity=sev,
                            description=(
                                f"Income discrepancy detected: Declared monthly income (INR {decl_income:,.2f}) "
                                f"materially exceeds salary slip net earnings (INR {sal_val:,.2f}) by {pct_diff:.1f}%."
                            ),
                            expected_value=f"INR {decl_income:,.2f}",
                            observed_value=f"INR {sal_val:,.2f}",
                            source_documents=[
                                "loan_application",
                                ef_sal.source_document or "salary_slip",
                            ],
                            evidence=f"Salary slip earnings excerpt: '{ef_sal.evidence}'",
                        )
                    )

        return flags

    def _check_liability_consistency(
        self, declared: Dict[str, Any], doc_fields: Dict[str, Dict[str, ExtractedField]]
    ) -> List[AnomalyFlag]:
        """Check for undisclosed recurring liabilities observed in bank statements (ANOM-FIN-001)."""
        flags: List[AnomalyFlag] = []
        decl_emi = float(declared.get("existing_emi") or 0.0)

        bank_fields = doc_fields.get("bank_statement", {})
        ef_emi = bank_fields.get("emi_debit")
        if ef_emi and ef_emi.value is not None:
            observed_emi = float(ef_emi.value)
            undisclosed_amount = observed_emi - decl_emi
            if undisclosed_amount > self.config.undisclosed_emi_threshold_inr:
                flags.append(
                    AnomalyFlag(
                        rule_id="ANOM-FIN-001",
                        anomaly_type="UNDISCLOSED_LIABILITY",
                        severity=AnomalySeverity.HIGH,
                        description=(
                            f"Undisclosed debt liability detected: Bank statement ledger exhibits ongoing recurring "
                            f"loan EMI debits (INR {observed_emi:,.2f}) exceeding declared existing obligations "
                            f"(INR {decl_emi:,.2f}) by INR {undisclosed_amount:,.2f}."
                        ),
                        expected_value=f"Declared EMI: INR {decl_emi:,.2f}",
                        observed_value=f"Bank EMI Debits: INR {observed_emi:,.2f}",
                        source_documents=[
                            "loan_application",
                            ef_emi.source_document or "bank_statement",
                        ],
                        evidence=f"Bank statement debit transaction: '{ef_emi.evidence}'",
                    )
                )

        return flags

    def _check_balance_consistency(
        self, declared: Dict[str, Any], doc_fields: Dict[str, Dict[str, ExtractedField]]
    ) -> List[AnomalyFlag]:
        """Check for bank balance discrepancies between declared and closing balance (ANOM-FIN-002)."""
        flags: List[AnomalyFlag] = []
        decl_bal = float(declared.get("bank_balance") or 0.0)
        if decl_bal <= 0:
            return flags

        bank_fields = doc_fields.get("bank_statement", {})
        ef_bal = bank_fields.get("closing_balance")
        if ef_bal and ef_bal.value is not None:
            observed_bal = float(ef_bal.value)
            if decl_bal > observed_bal:
                shortfall = decl_bal - observed_bal
                pct_shortfall = (shortfall / decl_bal) * 100.0
                if (
                    pct_shortfall > self.config.balance_discrepancy_threshold_pct
                    and shortfall > self.config.balance_discrepancy_min_inr
                ):
                    sev = (
                        AnomalySeverity.HIGH
                        if pct_shortfall >= 50.0
                        else AnomalySeverity.MEDIUM
                    )
                    flags.append(
                        AnomalyFlag(
                            rule_id="ANOM-FIN-002",
                            anomaly_type="BALANCE_MISMATCH",
                            severity=sev,
                            description=(
                                f"Bank balance inconsistency detected: Declared bank balance (INR {decl_bal:,.2f}) "
                                f"materially exceeds verified statement closing balance (INR {observed_bal:,.2f}) "
                                f"by {pct_shortfall:.1f}% (Shortfall: INR {shortfall:,.2f})."
                            ),
                            expected_value=f"Declared Balance: INR {decl_bal:,.2f}",
                            observed_value=f"Verified Closing Balance: INR {observed_bal:,.2f}",
                            source_documents=[
                                "loan_application",
                                ef_bal.source_document or "bank_statement",
                            ],
                            evidence=f"Bank statement balance excerpt: '{ef_bal.evidence}'",
                        )
                    )

        return flags

    def _check_employer_consistency(
        self, declared: Dict[str, Any], doc_fields: Dict[str, Dict[str, ExtractedField]]
    ) -> List[AnomalyFlag]:
        """Check for employer name discrepancies between application and payroll slips (ANOM-DOC-001)."""
        flags: List[AnomalyFlag] = []
        decl_emp = declared.get("employer_name")
        if not decl_emp:
            return flags

        salary_fields = doc_fields.get("salary_slip", {})
        ef_emp = salary_fields.get("employer_name")
        if ef_emp and ef_emp.value:
            obs_emp = str(ef_emp.value).strip()
            # Normalize and check token intersection
            n_decl = normalize_string(decl_emp)
            n_obs = normalize_string(obs_emp)
            if n_decl and n_obs:
                sim = calculate_name_similarity(n_decl, n_obs)
                if sim < 0.50:
                    flags.append(
                        AnomalyFlag(
                            rule_id="ANOM-DOC-001",
                            anomaly_type="EMPLOYER_MISMATCH",
                            severity=AnomalySeverity.LOW,
                            description=(
                                f"Employer name discrepancy: Application declares '{decl_emp}', whereas "
                                f"salary slip records '{obs_emp}'."
                            ),
                            expected_value=decl_emp,
                            observed_value=obs_emp,
                            source_documents=[
                                "loan_application",
                                ef_emp.source_document or "salary_slip",
                            ],
                            evidence=f"Salary slip employer excerpt: '{ef_emp.evidence}'",
                        )
                    )

        return flags

    # -----------------------------------------------------------------------
    # Helper Context Extraction
    # -----------------------------------------------------------------------

    def _extract_context(
        self,
        target: Union[DocumentPackageResult, Applicant, Dict[str, Any]],
        applicant_profile: Optional[Applicant] = None,
    ) -> Tuple[str, Dict[str, Any], Dict[str, Dict[str, ExtractedField]], List[str]]:
        """Normalize target inputs into applicant ID, declared values, and doc-level fields."""
        declared_data: Dict[str, Any] = {}
        doc_fields: Dict[str, Dict[str, ExtractedField]] = {}
        missing_docs: List[str] = []
        applicant_id = "UNKNOWN"

        if applicant_profile:
            applicant_id = applicant_profile.applicant_id
            declared_data = {
                "name": applicant_profile.name,
                "monthly_income": applicant_profile.monthly_income,
                "existing_emi": applicant_profile.existing_emi,
                "bank_balance": applicant_profile.bank_balance,
            }

        if isinstance(target, DocumentPackageResult):
            applicant_id = target.applicant_id
            missing_docs = list(target.documents_missing)

            # Organize fields by document type
            for doc in target.documents_found:
                doc_fields[doc.document_type] = dict(doc.extracted_fields)

            # Check loan_application document for declared attributes
            app_fields = doc_fields.get("loan_application", {})
            if "applicant_name" in app_fields:
                declared_data["name"] = app_fields["applicant_name"].value
            if "monthly_income" in app_fields:
                declared_data["monthly_income"] = app_fields["monthly_income"].value
            elif "declared_monthly_income" in app_fields:
                declared_data["monthly_income"] = app_fields[
                    "declared_monthly_income"
                ].value
            if "existing_emi" in app_fields:
                declared_data["existing_emi"] = app_fields["existing_emi"].value
            elif "declared_existing_emi" in app_fields:
                declared_data["existing_emi"] = app_fields[
                    "declared_existing_emi"
                ].value
            if "bank_balance" in app_fields:
                declared_data["bank_balance"] = app_fields["bank_balance"].value
            elif "declared_bank_balance" in app_fields:
                declared_data["bank_balance"] = app_fields[
                    "declared_bank_balance"
                ].value
            if "employer_name" in app_fields:
                declared_data["employer_name"] = app_fields["employer_name"].value

        elif isinstance(target, Applicant):
            applicant_id = target.applicant_id
            declared_data = {
                "name": target.name,
                "monthly_income": target.monthly_income,
                "existing_emi": target.existing_emi,
                "bank_balance": target.bank_balance,
            }

        elif isinstance(target, dict):
            applicant_id = str(target.get("applicant_id", "UNKNOWN"))
            declared_data = dict(target)
            missing_docs = list(target.get("documents_missing", []))

        return applicant_id, declared_data, doc_fields, missing_docs
