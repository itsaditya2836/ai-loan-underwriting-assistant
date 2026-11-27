"""Cross-Document Consistency and Anomaly Detection Engine.

Performs deterministic cross-document consistency checks:
- ANOM-ID-001: Name consistency across application, identity, address, payroll, employment, and bank records
- ANOM-INC-001: Income consistency (declared vs bank salary credits / salary slips, salary slip vs bank credits, multi-slip consistency)
- ANOM-FIN-001: Liability verification (declared existing EMI vs bank statement EMI auto-debits)
- ANOM-FIN-002: Balance verification (declared liquid balance vs verified statement closing balance)
- ANOM-DOC-001: Employer verification across loan application, salary slips, and employment proof
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Union

from app.document_processing.validation import VALIDATION_INVALID
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

_CORPORATE_SUFFIX_RE = re.compile(
    r"\b(?:PVT\.?|PRIVATE|LTD\.?|LIMITED|LLP|INC\.?|CORP\.?|CORPORATION|CO\.?)\b",
    re.IGNORECASE,
)
_HONORIFIC_RE = re.compile(r"\b(?:MR|MRS|MS|DR|SHRI|SMT)\.?\b", re.IGNORECASE)


def _is_usable_field(ef: Optional[ExtractedField]) -> bool:
    """Return True if an ExtractedField holds a non-None, non-invalid value."""
    if ef is None or ef.value is None:
        return False
    return getattr(ef, "validation_status", "valid") != VALIDATION_INVALID


def _normalize_person_name(name: Optional[str]) -> str:
    """Normalize honorifics, punctuation, and whitespace before name comparison."""
    if not name:
        return ""
    stripped = _HONORIFIC_RE.sub(" ", str(name))
    return normalize_string(stripped)


def _normalize_employer_name(name: Optional[str]) -> str:
    """Normalize punctuation and benign corporate suffixes for employer matching."""
    if not name:
        return ""
    stripped = _CORPORATE_SUFFIX_RE.sub(" ", str(name))
    norm = normalize_string(stripped)
    return norm or normalize_string(name)


def _period_overlap_or_compatible(period_a: str, period_b: str) -> bool:
    """Return True unless two explicit period strings clearly reference mismatched months."""
    months = (
        "JAN",
        "FEB",
        "MAR",
        "APR",
        "MAY",
        "JUN",
        "JUL",
        "AUG",
        "SEP",
        "OCT",
        "NOV",
        "DEC",
    )
    up_a = period_a.upper()
    up_b = period_b.upper()
    months_a = {m for m in months if re.search(rf"\b{m}", up_a)}
    months_b = {m for m in months if re.search(rf"\b{m}", up_b)}
    if months_a and months_b and months_a.isdisjoint(months_b):
        return False
    return True


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
        """Detect cross-document discrepancies across all submitted documents and profile."""
        (
            applicant_id,
            declared_data,
            doc_fields,
            doc_fields_by_type,
            missing_docs,
        ) = self._extract_context(target, applicant_profile)

        flags: List[AnomalyFlag] = []

        flags.extend(
            self._check_identity_consistency(declared_data, doc_fields_by_type)
        )
        flags.extend(self._check_income_consistency(declared_data, doc_fields_by_type))
        flags.extend(self._check_liability_consistency(declared_data, doc_fields))
        flags.extend(self._check_balance_consistency(declared_data, doc_fields))
        flags.extend(
            self._check_employer_consistency(declared_data, doc_fields_by_type)
        )

        score, severity = self.scorer.calculate_score(flags)
        has_anomalies = len(flags) > 0

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
        self,
        declared: Dict[str, Any],
        doc_fields_by_type: Dict[str, List[Dict[str, ExtractedField]]],
    ) -> List[AnomalyFlag]:
        """Check for name discrepancies across application and supporting documents (ANOM-ID-001)."""
        flags: List[AnomalyFlag] = []
        decl_name = declared.get("name") or declared.get("applicant_name")

        name_keys = ["applicant_name", "employee_name", "account_holder"]
        observed_entries: List[Tuple[str, ExtractedField]] = []
        for doc_type, doc_list in doc_fields_by_type.items():
            for fields in doc_list:
                for key in name_keys:
                    ef = fields.get(key)
                    if _is_usable_field(ef):
                        observed_entries.append((doc_type, ef))
                        break

        if not decl_name and observed_entries:
            # Fallback baseline: use identity_proof if present, else first observed
            ref_doc = next(
                (ef.value for dt, ef in observed_entries if dt == "identity_proof"),
                observed_entries[0][1].value,
            )
            decl_name = str(ref_doc)

        if not decl_name:
            return flags

        norm_decl = _normalize_person_name(str(decl_name))
        for doc_type, ef in observed_entries:
            observed_name = str(ef.value).strip()
            norm_obs = _normalize_person_name(observed_name)
            sim = calculate_name_similarity(norm_decl, norm_obs)
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
                        expected_value=str(decl_name),
                        observed_value=observed_name,
                        source_documents=[
                            "loan_application",
                            ef.source_document or doc_type,
                        ],
                        evidence=(
                            f"Extracted from {ef.source_document} (Page {ef.page_number}): '{ef.evidence}'"
                        ),
                    )
                )

        return flags

    def _check_income_consistency(
        self,
        declared: Dict[str, Any],
        doc_fields_by_type: Dict[str, List[Dict[str, ExtractedField]]],
    ) -> List[AnomalyFlag]:
        """Check declared income, bank salary credits, salary slips, and multi-slip agreement."""
        flags: List[AnomalyFlag] = []
        decl_income = declared.get("monthly_income")
        thresh = self.config.income_discrepancy_threshold_pct

        bank_docs = doc_fields_by_type.get("bank_statement", [])
        salary_docs = doc_fields_by_type.get("salary_slip", [])

        ef_cred = next(
            (
                d.get("salary_credit")
                for d in bank_docs
                if _is_usable_field(d.get("salary_credit"))
            ),
            None,
        )
        valid_slips = [d for d in salary_docs if _is_usable_field(d.get("net_salary"))]

        bank_flagged = False
        # 1. Declared Monthly Income vs Bank Statement Salary Credit
        if decl_income and float(decl_income) > 0 and ef_cred is not None:
            cred_val = float(ef_cred.value)
            decl_val = float(decl_income)
            if cred_val < decl_val:
                pct_diff = ((decl_val - cred_val) / decl_val) * 100.0
                if pct_diff > thresh:
                    bank_flagged = True
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
                                f"Income discrepancy detected: Declared monthly income (INR {decl_val:,.2f}) "
                                f"materially exceeds verified bank statement recurring salary credit "
                                f"(INR {cred_val:,.2f}) by {pct_diff:.1f}%."
                            ),
                            expected_value=f"INR {decl_val:,.2f}",
                            observed_value=f"INR {cred_val:,.2f}",
                            source_documents=[
                                "loan_application",
                                ef_cred.source_document or "bank_statement",
                            ],
                            evidence=f"Bank statement credit excerpt: '{ef_cred.evidence}'",
                        )
                    )

        # 2. Declared Monthly Income vs Salary Slip Net Salary (if bank did not already flag)
        if decl_income and float(decl_income) > 0 and valid_slips and not bank_flagged:
            ef_sal = valid_slips[0]["net_salary"]
            sal_val = float(ef_sal.value)
            decl_val = float(decl_income)
            if sal_val < decl_val:
                pct_diff = ((decl_val - sal_val) / decl_val) * 100.0
                if pct_diff > thresh:
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
                                f"Income discrepancy detected: Declared monthly income (INR {decl_val:,.2f}) "
                                f"materially exceeds salary slip net earnings (INR {sal_val:,.2f}) by {pct_diff:.1f}%."
                            ),
                            expected_value=f"INR {decl_val:,.2f}",
                            observed_value=f"INR {sal_val:,.2f}",
                            source_documents=[
                                "loan_application",
                                ef_sal.source_document or "salary_slip",
                            ],
                            evidence=f"Salary slip earnings excerpt: '{ef_sal.evidence}'",
                        )
                    )

        # 3. Direct Cross-Document Comparison: Salary Slip Net Salary vs Bank Salary Credit
        # Avoid double-counting when application vs bank already raised ANOM-INC-001
        if valid_slips and ef_cred is not None and not flags:
            ef_sal = valid_slips[0]["net_salary"]
            sal_val = float(ef_sal.value)
            cred_val = float(ef_cred.value)
            denom = max(sal_val, cred_val, 1.0)
            pct_diff = (abs(sal_val - cred_val) / denom) * 100.0
            if pct_diff > thresh:
                # Note period context if both exist
                sal_per = valid_slips[0].get("salary_period")
                bank_per = bank_docs[0].get("statement_period") if bank_docs else None
                period_note = ""
                if (
                    _is_usable_field(sal_per)
                    and _is_usable_field(bank_per)
                    and not _period_overlap_or_compatible(
                        str(sal_per.value), str(bank_per.value)
                    )
                ):
                    period_note = f" (Note: differing periods '{sal_per.value}' vs '{bank_per.value}')"
                sev = (
                    AnomalySeverity.HIGH if pct_diff >= 30.0 else AnomalySeverity.MEDIUM
                )
                flags.append(
                    AnomalyFlag(
                        rule_id="ANOM-INC-001",
                        anomaly_type="INCOME_MISMATCH",
                        severity=sev,
                        description=(
                            f"Salary slip vs bank statement mismatch: Net salary (INR {sal_val:,.2f}) "
                            f"differs from bank salary credit (INR {cred_val:,.2f}) by {pct_diff:.1f}%{period_note}."
                        ),
                        expected_value=f"Salary Slip: INR {sal_val:,.2f}",
                        observed_value=f"Bank Credit: INR {cred_val:,.2f}",
                        source_documents=[
                            ef_sal.source_document or "salary_slip",
                            ef_cred.source_document or "bank_statement",
                        ],
                        evidence=(
                            f"Salary slip ({ef_sal.evidence}) vs bank credit ({ef_cred.evidence})"
                        ),
                    )
                )

        # 4. Consistency across multiple submitted salary slips
        if len(valid_slips) >= 2 and not flags:
            base_sal = valid_slips[0]["net_salary"]
            base_val = float(base_sal.value)
            for other_doc in valid_slips[1:]:
                other_sal = other_doc["net_salary"]
                other_val = float(other_sal.value)
                denom = max(base_val, other_val, 1.0)
                pct_diff = (abs(base_val - other_val) / denom) * 100.0
                if pct_diff > thresh:
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
                                f"Multi-payslip variance detected: {base_sal.source_document} "
                                f"(INR {base_val:,.2f}) diverges from {other_sal.source_document} "
                                f"(INR {other_val:,.2f}) by {pct_diff:.1f}%."
                            ),
                            expected_value=f"INR {base_val:,.2f}",
                            observed_value=f"INR {other_val:,.2f}",
                            source_documents=[
                                base_sal.source_document or "salary_slip",
                                other_sal.source_document or "salary_slip",
                            ],
                            evidence=f"{base_sal.evidence} vs {other_sal.evidence}",
                        )
                    )
                    break

        return flags

    def _check_liability_consistency(
        self,
        declared: Dict[str, Any],
        doc_fields: Dict[str, Dict[str, ExtractedField]],
    ) -> List[AnomalyFlag]:
        """Check for undisclosed recurring liabilities observed in bank statements (ANOM-FIN-001)."""
        flags: List[AnomalyFlag] = []
        decl_emi = float(declared.get("existing_emi") or 0.0)

        bank_fields = doc_fields.get("bank_statement", {})
        ef_emi = bank_fields.get("emi_debit")
        if _is_usable_field(ef_emi):
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
        self,
        declared: Dict[str, Any],
        doc_fields: Dict[str, Dict[str, ExtractedField]],
    ) -> List[AnomalyFlag]:
        """Check for bank balance discrepancies between declared and closing balance (ANOM-FIN-002)."""
        flags: List[AnomalyFlag] = []
        decl_bal = float(declared.get("bank_balance") or 0.0)
        if decl_bal <= 0:
            return flags

        bank_fields = doc_fields.get("bank_statement", {})
        ef_bal = bank_fields.get("closing_balance")
        if _is_usable_field(ef_bal):
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
        self,
        declared: Dict[str, Any],
        doc_fields_by_type: Dict[str, List[Dict[str, ExtractedField]]],
    ) -> List[AnomalyFlag]:
        """Check for employer name discrepancies across application, salary slips, and employment proof."""
        flags: List[AnomalyFlag] = []
        employer_docs: List[Tuple[str, ExtractedField]] = []
        for dt in ("salary_slip", "employment_proof"):
            for fields in doc_fields_by_type.get(dt, []):
                ef_emp = fields.get("employer_name")
                if _is_usable_field(ef_emp):
                    employer_docs.append((dt, ef_emp))

        if not employer_docs:
            return flags

        decl_emp = declared.get("employer_name")
        reference_source = "loan_application"
        if not decl_emp and len(employer_docs) >= 2:
            reference_source = (
                employer_docs[0][1].source_document or employer_docs[0][0]
            )
            decl_emp = str(employer_docs[0][1].value)
            compare_items = employer_docs[1:]
        else:
            compare_items = employer_docs

        if not decl_emp:
            return flags

        n_decl = _normalize_employer_name(str(decl_emp))
        if not n_decl:
            return flags

        for dt, ef_emp in compare_items:
            obs_emp = str(ef_emp.value).strip()
            n_obs = _normalize_employer_name(obs_emp)
            if not n_obs:
                continue
            sim = calculate_name_similarity(n_decl, n_obs)
            if sim < 0.50:
                flags.append(
                    AnomalyFlag(
                        rule_id="ANOM-DOC-001",
                        anomaly_type="EMPLOYER_MISMATCH",
                        severity=AnomalySeverity.LOW,
                        description=(
                            f"Employer name discrepancy: {reference_source} records '{decl_emp}', "
                            f"whereas {dt} records '{obs_emp}'."
                        ),
                        expected_value=str(decl_emp),
                        observed_value=obs_emp,
                        source_documents=[
                            reference_source,
                            ef_emp.source_document or dt,
                        ],
                        evidence=f"Employer excerpt from {ef_emp.source_document}: '{ef_emp.evidence}'",
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
    ) -> Tuple[
        str,
        Dict[str, Any],
        Dict[str, Dict[str, ExtractedField]],
        Dict[str, List[Dict[str, ExtractedField]]],
        List[str],
    ]:
        """Normalize target inputs into applicant ID, declared values, and doc-level fields."""
        declared_data: Dict[str, Any] = {}
        doc_fields: Dict[str, Dict[str, ExtractedField]] = {}
        doc_fields_by_type: Dict[str, List[Dict[str, ExtractedField]]] = {}
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

            for doc in target.documents_found:
                fields_copy = dict(doc.extracted_fields)
                doc_fields.setdefault(doc.document_type, fields_copy)
                doc_fields_by_type.setdefault(doc.document_type, []).append(fields_copy)

            app_fields = doc_fields.get("loan_application", {})
            if _is_usable_field(app_fields.get("applicant_name")):
                declared_data["name"] = app_fields["applicant_name"].value
            if _is_usable_field(app_fields.get("monthly_income")):
                declared_data["monthly_income"] = app_fields["monthly_income"].value
            elif _is_usable_field(app_fields.get("declared_monthly_income")):
                declared_data["monthly_income"] = app_fields[
                    "declared_monthly_income"
                ].value
            if _is_usable_field(app_fields.get("existing_emi")):
                declared_data["existing_emi"] = app_fields["existing_emi"].value
            elif _is_usable_field(app_fields.get("declared_existing_emi")):
                declared_data["existing_emi"] = app_fields[
                    "declared_existing_emi"
                ].value
            if _is_usable_field(app_fields.get("bank_balance")):
                declared_data["bank_balance"] = app_fields["bank_balance"].value
            elif _is_usable_field(app_fields.get("declared_bank_balance")):
                declared_data["bank_balance"] = app_fields[
                    "declared_bank_balance"
                ].value
            if _is_usable_field(app_fields.get("employer_name")):
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

        return applicant_id, declared_data, doc_fields, doc_fields_by_type, missing_docs
