"""Document Information Extractor module.

Parses unstructured document text (from direct PyMuPDF extraction or OCR)
into structured key-value pairs, classification results, and traceable ExtractedField records.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.applicant import ExtractedField
from app.utils.helpers import get_logger

logger = get_logger(__name__)


def parse_currency(value_str: Optional[str]) -> Optional[float]:
    """Parse monetary strings with currency codes, commas, and decimals to float.

    Examples:
        'INR 37,500.00' -> 37500.0
        '₹ 1,45,600.50' -> 145600.5
        'Rs. 50000'     -> 50000.0
        '21000'         -> 21000.0
    """
    if not value_str:
        return None
    s = re.sub(r"^(?:INR|RS\.?|₹|\$)\s*", "", value_str.strip(), flags=re.IGNORECASE)
    m = re.search(r"[-+]?\d[\d,]*\.?\d*", s)
    if not m:
        return None
    cleaned = m.group(0).replace(",", "")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def clean_label_value(value: str, stop_keywords: Optional[List[str]] = None) -> str:
    """Trim stop keywords and trailing separators from extracted label values."""
    if not value:
        return ""
    v = value
    if stop_keywords:
        for kw in stop_keywords:
            pattern = re.compile(re.escape(kw), re.IGNORECASE)
            match = pattern.search(v)
            if match:
                v = v[: match.start()]
    return v.strip(" :-\t\r\n")


def find_label_value(
    text: str,
    label_patterns: List[str],
    stop_keywords: Optional[List[str]] = None,
) -> Tuple[Optional[str], str]:
    """Search for a value associated with given label patterns in text.

    Supports both inline format ('Label: Value') and stacked multi-line format
    ('Label:\nValue').

    Returns:
        Tuple of (extracted_value, supporting_evidence_string).
    """
    for pat in label_patterns:
        # 1. Inline match: Label: Value
        m_inline = re.search(pat + r"[:\s]+([^\n]+)", text, re.IGNORECASE)
        if m_inline:
            candidate = clean_label_value(m_inline.group(1), stop_keywords)
            if candidate:
                return candidate, m_inline.group(0).strip()

        # 2. Next-line match: Label:\nValue
        m_multiline = re.search(pat + r"[:\s]*\n\s*([^\n]+)", text, re.IGNORECASE)
        if m_multiline:
            candidate = clean_label_value(m_multiline.group(1), stop_keywords)
            if candidate:
                ev = f"{pat}: {candidate}"
                return candidate, ev

    return None, ""


class DocumentExtractor:
    """Extracts structured key-value data and classifies document types from raw text."""

    def __init__(self) -> None:
        logger.info("DocumentExtractor initialized.")

    def classify_document(
        self, raw_text: str, filename: str = ""
    ) -> Tuple[str, float, str]:
        """Classify document type using deterministic content patterns.

        Args:
            raw_text: Extracted text from PDF or OCR.
            filename: Original document filename as secondary clue.

        Returns:
            Tuple of (document_type, confidence_score, supporting_evidence).
            Supported types:
                - 'loan_application'
                - 'identity_proof'
                - 'salary_slip'
                - 'income_statement'
                - 'bank_statement'
                - 'unknown'
        """
        upper_text = raw_text.upper()

        # Priority 1: Bank Statement
        if (
            "ACCOUNT STATEMENT" in upper_text
            or "SYNTHETIC APEX BANK" in upper_text
            or ("ACCOUNT HOLDER:" in upper_text and "STATEMENT PERIOD:" in upper_text)
            or ("DEBIT (INR)" in upper_text and "CREDIT (INR)" in upper_text)
        ):
            ev = "Found banking markers: ACCOUNT STATEMENT / ACCOUNT HOLDER ledger headers"
            return "bank_statement", 0.98, ev

        # Priority 2: Income Statement (distinct from salary slip)
        if (
            "MONTHLY INCOME & REVENUE STATEMENT" in upper_text
            or "INCOME & REVENUE STATEMENT" in upper_text
            or "GROSS REVENUE SHARE" in upper_text
            or "DRAWINGS ALLOWANCE" in upper_text
        ):
            ev = "Found revenue markers: INCOME & REVENUE STATEMENT / GROSS REVENUE SHARE"
            return "income_statement", 0.97, ev

        # Priority 3: Salary Slip / Payslip
        if (
            "PAYSLIP FOR THE MONTH" in upper_text
            or "NET SALARY PAYABLE" in upper_text
            or (
                "EARNINGS COMPONENT" in upper_text
                and "DEDUCTIONS COMPONENT" in upper_text
            )
            or ("BASIC SALARY" in upper_text and "PROVIDENT FUND" in upper_text)
        ):
            ev = "Found payroll markers: PAYSLIP FOR THE MONTH / NET SALARY PAYABLE"
            return "salary_slip", 0.98, ev

        # Priority 4: Loan Application
        if (
            "SYNTHETIC LOAN APPLICATION FORM" in upper_text
            or "LOAN APPLICATION FORM" in upper_text
            or "FACILITY REQUESTED:" in upper_text
            or ("REQUESTED AMOUNT:" in upper_text and "REQUESTED TENURE:" in upper_text)
            or "ESTIMATED MONTHLY EMI:" in upper_text
        ):
            ev = "Found loan application markers: LOAN APPLICATION FORM / FACILITY REQUESTED"
            return "loan_application", 0.99, ev

        # Priority 5: Identity Proof / Verification
        if (
            "IDENTITY VERIFICATION RECORD" in upper_text
            or "SIMULATED CITIZEN RECORD" in upper_text
            or "SYNTHETIC ID REF:" in upper_text
            or "VERIFICATION AGENCY:" in upper_text
            or ("FULL LEGAL NAME:" in upper_text and "REGISTERED CITY:" in upper_text)
        ):
            ev = "Found identity verification markers: IDENTITY VERIFICATION RECORD / ID REF"
            return "identity_proof", 0.98, ev

        # Fallback to filename hints if text is low/noisy
        fn = filename.lower()
        if "bank_statement" in fn:
            return "bank_statement", 0.70, f"Classified from filename: {filename}"
        if "salary_slip" in fn or "payslip" in fn:
            return "salary_slip", 0.70, f"Classified from filename: {filename}"
        if "income_statement" in fn:
            return "income_statement", 0.70, f"Classified from filename: {filename}"
        if "loan_application" in fn or "loan_app" in fn:
            return "loan_application", 0.70, f"Classified from filename: {filename}"
        if "identity_proof" in fn or "id_proof" in fn:
            return "identity_proof", 0.70, f"Classified from filename: {filename}"

        return "unknown", 0.20, "No recognized document markers found"

    def extract_fields(
        self,
        raw_text: str,
        document_type: str,
        filename: str = "",
        is_scanned: bool = False,
    ) -> Dict[str, ExtractedField]:
        """Extract structured entity fields from document text based on document type.

        Args:
            raw_text: Raw text string (from PyMuPDF or OCR).
            document_type: Document classification category.
            filename: Source document filename for evidence tracking.
            is_scanned: Flag indicating if source was scanned OCR.

        Returns:
            Dictionary mapping field names to traceable ExtractedField instances.
        """
        # Baseline confidence modifier based on OCR vs digital PDF
        base_conf = 0.92 if is_scanned else 0.97
        src = filename or document_type

        # Dispatch to document-specific extractors
        if document_type == "loan_application":
            return self._extract_loan_application(raw_text, src, base_conf)
        elif document_type in ("identity_proof", "identity_verification"):
            return self._extract_identity_proof(raw_text, src, base_conf)
        elif document_type == "salary_slip":
            return self._extract_salary_slip(raw_text, src, base_conf)
        elif document_type == "income_statement":
            return self._extract_income_statement(raw_text, src, base_conf)
        elif document_type == "bank_statement":
            return self._extract_bank_statement(raw_text, src, base_conf)
        else:
            return self._extract_generic(raw_text, src, 0.70)

    # -------------------------------------------------------------------------
    # Document Specific Extractors
    # -------------------------------------------------------------------------

    def _extract_loan_application(
        self, text: str, src: str, base_conf: float
    ) -> Dict[str, ExtractedField]:
        fields: Dict[str, ExtractedField] = {}

        # 1. Applicant ID
        m_id = re.search(r"Applicant ID[:\s]+(APP\d{4})", text, re.IGNORECASE)
        if not m_id:
            m_id = re.search(r"APP-REQ-(APP\d{4})-", text)
        if m_id:
            fields["applicant_id"] = ExtractedField(
                field_name="applicant_id",
                value=m_id.group(1).upper(),
                confidence=min(base_conf + 0.02, 1.0),
                source_document=src,
                evidence=m_id.group(0).strip(),
            )

        # 2. Applicant Name
        val, ev = find_label_value(
            text, [r"Full Name", r"Applicant Name"], ["Gender", "Age", "City"]
        )
        if val:
            fields["applicant_name"] = ExtractedField(
                field_name="applicant_name",
                value=val,
                confidence=base_conf,
                source_document=src,
                evidence=ev,
            )

        # 3. Age and Gender
        m_ag = re.search(
            r"Gender\s*/\s*Age[:\s]+(Male|Female|Other)\s*/\s*(\d+)\s*Years?",
            text,
            re.IGNORECASE,
        )
        if m_ag:
            fields["gender"] = ExtractedField(
                field_name="gender",
                value=m_ag.group(1).capitalize(),
                confidence=base_conf,
                source_document=src,
                evidence=m_ag.group(0).strip(),
            )
            fields["age"] = ExtractedField(
                field_name="age",
                value=int(m_ag.group(2)),
                confidence=base_conf,
                source_document=src,
                evidence=m_ag.group(0).strip(),
            )
        else:
            m_age_alone = re.search(r"(\d{2})\s*Years?", text)
            if m_age_alone:
                fields["age"] = ExtractedField(
                    field_name="age",
                    value=int(m_age_alone.group(1)),
                    confidence=base_conf - 0.05,
                    source_document=src,
                    evidence=m_age_alone.group(0).strip(),
                )

        # 4. Employment Type
        val, ev = find_label_value(
            text,
            [r"Employment Type"],
            ["Employer", "Business", "Experience", "Tenure"],
        )
        if val:
            # Normalize to standard casing: Salaried, Self-Employed, Business Owner
            val_norm = val.title()
            if "Salaried" in val_norm:
                val_norm = "Salaried"
            elif "Self-Employed" in val_norm or "Self Employed" in val_norm:
                val_norm = "Self-Employed"
            elif "Business" in val_norm:
                val_norm = "Business Owner"
            fields["employment_type"] = ExtractedField(
                field_name="employment_type",
                value=val_norm,
                confidence=base_conf,
                source_document=src,
                evidence=ev,
            )

        # 5. Employer / Business Name
        val, ev = find_label_value(
            text,
            [r"Employer\s*/\s*Business", r"Employer Name", r"Business Name"],
            ["Experience", "Tenure", "Declared Monthly", "Income"],
        )
        if val:
            fields["employer_name"] = ExtractedField(
                field_name="employer_name",
                value=val,
                confidence=base_conf,
                source_document=src,
                evidence=ev,
            )

        # 6. Declared Monthly Income
        m_inc = re.search(
            r"Declared Monthly[\s\n]+Income:?[\s\n]+(?:INR\s*)?([0-9,.]+)",
            text,
            re.IGNORECASE,
        )
        if m_inc:
            num_inc = parse_currency(m_inc.group(1))
            ev = m_inc.group(0).strip().replace("\n", " ")
        else:
            val, ev = find_label_value(
                text,
                [r"Declared Monthly Income", r"Monthly Income"],
                ["Existing Monthly", "EMI", "Declared Bank"],
            )
            num_inc = parse_currency(val)

        if num_inc is not None:
            inc_field = ExtractedField(
                field_name="monthly_income",
                value=num_inc,
                confidence=min(base_conf + 0.02, 1.0),
                source_document=src,
                evidence=ev,
            )
            fields["monthly_income"] = inc_field
            fields["declared_monthly_income"] = inc_field

        # 7. Existing Monthly EMI
        m_emi = re.search(
            r"Existing Monthly[\s\n]+EMI:?[\s\n]+(?:INR\s*)?([0-9,.]+)",
            text,
            re.IGNORECASE,
        )
        if m_emi:
            num_emi = parse_currency(m_emi.group(1))
            ev = m_emi.group(0).strip().replace("\n", " ")
        else:
            val, ev = find_label_value(
                text,
                [r"Existing Monthly EMI", r"Existing EMI"],
                ["Declared Bank Balance", "Monthly Expenses"],
            )
            num_emi = parse_currency(val)

        if num_emi is not None:
            emi_field = ExtractedField(
                field_name="existing_emi",
                value=num_emi,
                confidence=min(base_conf + 0.02, 1.0),
                source_document=src,
                evidence=ev,
            )
            fields["existing_emi"] = emi_field
            fields["declared_existing_emi"] = emi_field

        # 8. Declared Bank Balance
        m_bal = re.search(
            r"Declared Bank[\s\n]+Balance:?[\s\n]+(?:INR\s*)?([0-9,.]+)",
            text,
            re.IGNORECASE,
        )
        if m_bal:
            num_bal = parse_currency(m_bal.group(1))
            ev = m_bal.group(0).strip().replace("\n", " ")
        else:
            val, ev = find_label_value(
                text,
                [r"Declared Bank Balance", r"Bank Balance"],
                ["Monthly Expenses", "Self-Reported"],
            )
            num_bal = parse_currency(val)

        if num_bal is not None:
            bal_field = ExtractedField(
                field_name="bank_balance",
                value=num_bal,
                confidence=min(base_conf + 0.02, 1.0),
                source_document=src,
                evidence=ev,
            )
            fields["bank_balance"] = bal_field
            fields["declared_bank_balance"] = bal_field

        # 9. Self-Reported Credit Score
        m_cs = re.search(
            r"Self-Reported Credit\s*Score[:\s]+(\d{3})", text, re.IGNORECASE
        )
        if not m_cs:
            m_cs = re.search(r"Credit Score[:\s]+(\d{3})", text, re.IGNORECASE)
        if m_cs:
            fields["credit_score"] = ExtractedField(
                field_name="credit_score",
                value=int(m_cs.group(1)),
                confidence=min(base_conf + 0.02, 1.0),
                source_document=src,
                evidence=m_cs.group(0).strip(),
            )

        # 10. Requested Loan Amount
        val, ev = find_label_value(
            text,
            [r"Requested Amount", r"Loan Amount"],
            ["Requested Tenure", "Estimated Monthly"],
        )
        num_la = parse_currency(val)
        if num_la is not None:
            fields["loan_amount"] = ExtractedField(
                field_name="loan_amount",
                value=num_la,
                confidence=min(base_conf + 0.02, 1.0),
                source_document=src,
                evidence=ev,
            )

        # 11. Requested Loan Tenure
        m_lt = re.search(r"Requested Tenure[:\s]+(\d+)\s*Months?", text, re.IGNORECASE)
        if m_lt:
            fields["loan_tenure"] = ExtractedField(
                field_name="loan_tenure",
                value=int(m_lt.group(1)),
                confidence=base_conf,
                source_document=src,
                evidence=m_lt.group(0).strip(),
            )

        # 12. City of Residence
        val, ev = find_label_value(
            text, [r"City of Residence", r"City"], ["Number of Dependents"]
        )
        if val:
            fields["city"] = ExtractedField(
                field_name="city",
                value=val,
                confidence=base_conf - 0.02,
                source_document=src,
                evidence=ev,
            )

        # 13. Loan Purpose
        val, ev = find_label_value(
            text, [r"Loan Purpose"], ["I hereby declare", "Applicant Signature"]
        )
        if val:
            fields["loan_purpose"] = ExtractedField(
                field_name="loan_purpose",
                value=val,
                confidence=base_conf - 0.02,
                source_document=src,
                evidence=ev,
            )

        return fields

    def _extract_identity_proof(
        self, text: str, src: str, base_conf: float
    ) -> Dict[str, ExtractedField]:
        fields: Dict[str, ExtractedField] = {}

        # 1. Applicant ID
        m_id = re.search(r"Applicant ID[:\s]+(APP\d{4})", text, re.IGNORECASE)
        if not m_id:
            m_id = re.search(r"SYN-ID-(APP\d{4})-", text)
        if m_id:
            fields["applicant_id"] = ExtractedField(
                field_name="applicant_id",
                value=m_id.group(1).upper(),
                confidence=min(base_conf + 0.02, 1.0),
                source_document=src,
                evidence=m_id.group(0).strip(),
            )

        # 2. Full Legal Name
        val, ev = find_label_value(
            text,
            [r"Full Legal Name", r"Legal Name", r"Full Name"],
            ["Age / Gender", "Registered City", "Status"],
        )
        if val:
            fields["applicant_name"] = ExtractedField(
                field_name="applicant_name",
                value=val,
                confidence=base_conf,
                source_document=src,
                evidence=ev,
            )

        # 3. Synthetic ID Reference
        val, ev = find_label_value(
            text, [r"Synthetic ID Ref", r"ID Ref"], ["Applicant ID"]
        )
        if val:
            fields["id_ref"] = ExtractedField(
                field_name="id_ref",
                value=val,
                confidence=base_conf,
                source_document=src,
                evidence=ev,
            )

        # 4. Age / Gender
        m_ag = re.search(
            r"Age\s*/\s*Gender[:\s]+(\d+)\s*Years?\s*/\s*(Male|Female|Other)",
            text,
            re.IGNORECASE,
        )
        if m_ag:
            fields["age"] = ExtractedField(
                field_name="age",
                value=int(m_ag.group(1)),
                confidence=base_conf,
                source_document=src,
                evidence=m_ag.group(0).strip(),
            )
            fields["gender"] = ExtractedField(
                field_name="gender",
                value=m_ag.group(2).capitalize(),
                confidence=base_conf,
                source_document=src,
                evidence=m_ag.group(0).strip(),
            )

        # 5. Registered City
        val, ev = find_label_value(
            text, [r"Registered City", r"City"], ["Status", "Issue Date"]
        )
        if val:
            fields["registered_city"] = ExtractedField(
                field_name="registered_city",
                value=val,
                confidence=base_conf,
                source_document=src,
                evidence=ev,
            )

        # 6. Status
        val, ev = find_label_value(
            text, [r"Status"], ["Issue Date", "Verification Agency"]
        )
        if val:
            fields["status"] = ExtractedField(
                field_name="status",
                value=val,
                confidence=base_conf - 0.05,
                source_document=src,
                evidence=ev,
            )

        return fields

    def _extract_salary_slip(
        self, text: str, src: str, base_conf: float
    ) -> Dict[str, ExtractedField]:
        fields: Dict[str, ExtractedField] = {}

        # 1. Applicant Name / Employee Name
        val, ev = find_label_value(
            text, [r"Name"], ["Period", "Identifier", "City", "Designation"]
        )
        if val:
            fields["employee_name"] = ExtractedField(
                field_name="employee_name",
                value=val,
                confidence=base_conf,
                source_document=src,
                evidence=ev,
            )

        # 2. Applicant ID / Identifier
        m_id = re.search(r"Identifier[:\s]+(?:EMP-)?(APP\d{4})", text, re.IGNORECASE)
        if m_id:
            fields["applicant_id"] = ExtractedField(
                field_name="applicant_id",
                value=m_id.group(1).upper(),
                confidence=min(base_conf + 0.02, 1.0),
                source_document=src,
                evidence=m_id.group(0).strip(),
            )

        # 3. Employer Name (Found in header lines before PAYSLIP FOR THE MONTH)
        lines = [
            line_item.strip() for line_item in text.split("\n") if line_item.strip()
        ]
        for idx, line in enumerate(lines[:8]):

            if (
                "PAYSLIP FOR THE MONTH" in line.upper()
                or "MONTHLY INCOME" in line.upper()
            ):
                # The employer is typically the line immediately preceding
                if idx > 0 and "SYNTHETIC DOCUMENT" not in lines[idx - 1].upper():
                    fields["employer_name"] = ExtractedField(
                        field_name="employer_name",
                        value=lines[idx - 1],
                        confidence=base_conf,
                        source_document=src,
                        evidence=lines[idx - 1],
                    )
                break

        # 4. Net Salary Payable
        m_net = re.search(
            r"NET SALARY PAYABLE[:\s]+(?:INR\s*)?([0-9,.]+)", text, re.IGNORECASE
        )
        if m_net:
            net_val = parse_currency(m_net.group(1))
            if net_val is not None:
                fields["net_salary"] = ExtractedField(
                    field_name="net_salary",
                    value=net_val,
                    confidence=min(base_conf + 0.02, 1.0),
                    source_document=src,
                    evidence=m_net.group(0).strip(),
                )

        # 5. Total Gross Earnings
        m_gross = re.search(
            r"Total Gross Earnings[:\s]+(?:INR\s*)?([0-9,.]+)", text, re.IGNORECASE
        )
        if m_gross:
            gross_val = parse_currency(m_gross.group(1))
            if gross_val is not None:
                fields["gross_earnings"] = ExtractedField(
                    field_name="gross_earnings",
                    value=gross_val,
                    confidence=base_conf,
                    source_document=src,
                    evidence=m_gross.group(0).strip(),
                )

        # 6. Total Deductions
        m_ded = re.search(
            r"Total Deductions[:\s]+(?:INR\s*)?([0-9,.]+)", text, re.IGNORECASE
        )
        if m_ded:
            ded_val = parse_currency(m_ded.group(1))
            if ded_val is not None:
                fields["total_deductions"] = ExtractedField(
                    field_name="total_deductions",
                    value=ded_val,
                    confidence=base_conf,
                    source_document=src,
                    evidence=m_ded.group(0).strip(),
                )

        # 7. Salary Period
        val, ev = find_label_value(
            text, [r"Period"], ["Identifier", "City", "Designation"]
        )
        if val:
            fields["salary_period"] = ExtractedField(
                field_name="salary_period",
                value=val,
                confidence=base_conf - 0.02,
                source_document=src,
                evidence=ev,
            )

        return fields

    def _extract_income_statement(
        self, text: str, src: str, base_conf: float
    ) -> Dict[str, ExtractedField]:
        fields: Dict[str, ExtractedField] = {}

        # 1. Applicant Name
        val, ev = find_label_value(
            text, [r"Name"], ["Period", "Identifier", "City", "Designation"]
        )
        if val:
            fields["applicant_name"] = ExtractedField(
                field_name="applicant_name",
                value=val,
                confidence=base_conf,
                source_document=src,
                evidence=ev,
            )

        # 2. Applicant ID / Identifier
        m_id = re.search(r"Identifier[:\s]+(?:EMP-)?(APP\d{4})", text, re.IGNORECASE)
        if m_id:
            fields["applicant_id"] = ExtractedField(
                field_name="applicant_id",
                value=m_id.group(1).upper(),
                confidence=min(base_conf + 0.02, 1.0),
                source_document=src,
                evidence=m_id.group(0).strip(),
            )

        # 3. Business Name (Header line before MONTHLY INCOME & REVENUE STATEMENT)
        lines = [
            line_item.strip() for line_item in text.split("\n") if line_item.strip()
        ]
        for idx, line in enumerate(lines[:8]):

            if "MONTHLY INCOME & REVENUE STATEMENT" in line.upper():
                if idx > 0 and "SYNTHETIC DOCUMENT" not in lines[idx - 1].upper():
                    fields["business_name"] = ExtractedField(
                        field_name="business_name",
                        value=lines[idx - 1],
                        confidence=base_conf,
                        source_document=src,
                        evidence=lines[idx - 1],
                    )
                break

        # 4. Net Income / Net Salary Payable
        m_net = re.search(
            r"NET (?:SALARY PAYABLE|INCOME|REVENUE)[:\s]+(?:INR\s*)?([0-9,.]+)",
            text,
            re.IGNORECASE,
        )
        if m_net:
            net_val = parse_currency(m_net.group(1))
            if net_val is not None:
                fields["net_income"] = ExtractedField(
                    field_name="net_income",
                    value=net_val,
                    confidence=min(base_conf + 0.02, 1.0),
                    source_document=src,
                    evidence=m_net.group(0).strip(),
                )

        # 5. Total Gross Earnings
        m_gross = re.search(
            r"Total Gross Earnings[:\s]+(?:INR\s*)?([0-9,.]+)", text, re.IGNORECASE
        )
        if m_gross:
            gross_val = parse_currency(m_gross.group(1))
            if gross_val is not None:
                fields["gross_earnings"] = ExtractedField(
                    field_name="gross_earnings",
                    value=gross_val,
                    confidence=base_conf,
                    source_document=src,
                    evidence=m_gross.group(0).strip(),
                )

        # 6. Total Deductions
        m_ded = re.search(
            r"Total Deductions[:\s]+(?:INR\s*)?([0-9,.]+)", text, re.IGNORECASE
        )
        if m_ded:
            ded_val = parse_currency(m_ded.group(1))
            if ded_val is not None:
                fields["total_deductions"] = ExtractedField(
                    field_name="total_deductions",
                    value=ded_val,
                    confidence=base_conf,
                    source_document=src,
                    evidence=m_ded.group(0).strip(),
                )

        # 7. Period
        val, ev = find_label_value(
            text, [r"Period"], ["Identifier", "City", "Designation"]
        )
        if val:
            fields["statement_period"] = ExtractedField(
                field_name="statement_period",
                value=val,
                confidence=base_conf - 0.02,
                source_document=src,
                evidence=ev,
            )

        return fields

    def _extract_bank_statement(
        self, text: str, src: str, base_conf: float
    ) -> Dict[str, ExtractedField]:
        fields: Dict[str, ExtractedField] = {}

        # 1. Account Holder Name
        val, ev = find_label_value(
            text,
            [r"Account Holder"],
            ["Statement Period", "Account Number", "Account Type", "Branch"],
        )
        if val:
            fields["account_holder"] = ExtractedField(
                field_name="account_holder",
                value=val,
                confidence=base_conf,
                source_document=src,
                evidence=ev,
            )

        # 2. Account Number & Applicant ID from Account Number
        m_acc = re.search(r"(SYN-ACC-\d+-(APP\d{4})-\d+)", text, re.IGNORECASE)
        if m_acc:
            fields["account_number"] = ExtractedField(
                field_name="account_number",
                value=m_acc.group(1),
                confidence=min(base_conf + 0.02, 1.0),
                source_document=src,
                evidence=m_acc.group(0).strip(),
            )
            fields["applicant_id"] = ExtractedField(
                field_name="applicant_id",
                value=m_acc.group(2).upper(),
                confidence=min(base_conf + 0.02, 1.0),
                source_document=src,
                evidence=m_acc.group(0).strip(),
            )

        # 3. Statement Period
        val, ev = find_label_value(
            text,
            [r"Statement Period"],
            ["Account Number", "Account Type", "Branch"],
        )
        if val:
            fields["statement_period"] = ExtractedField(
                field_name="statement_period",
                value=val,
                confidence=base_conf - 0.02,
                source_document=src,
                evidence=ev,
            )

        # 4. Bank Ledger Transactions: Parse line items
        # Pattern handles: Date Description Ref Debit Credit Balance
        txn_pattern = re.compile(
            r"(\d{2}-[A-Za-z]{3}-\d{4})\s+(.+?)\s+(TXN[O0-9]+|\w+)\s+([\d,.-]+|-)\s+([\d,.-]+|-)\s+([\d,.]+)"
        )
        txns: List[Dict[str, Any]] = []
        salary_credits: List[float] = []
        emi_debits: List[float] = []

        for match in txn_pattern.finditer(text):
            date_str, desc, ref, debit_str, credit_str, bal_str = match.groups()
            debit_val = parse_currency(debit_str) if debit_str != "-" else None
            credit_val = parse_currency(credit_str) if credit_str != "-" else None
            bal_val = parse_currency(bal_str) or 0.0

            txns.append(
                {
                    "date": date_str,
                    "description": desc.strip(),
                    "ref": ref,
                    "debit": debit_val,
                    "credit": credit_val,
                    "balance": bal_val,
                }
            )

            desc_upper = desc.upper()
            if "SALARY CREDIT" in desc_upper and credit_val:
                salary_credits.append(credit_val)
            if "EMI AUTO-DEBIT" in desc_upper and debit_val:
                emi_debits.append(debit_val)

        if txns:
            fields["transaction_count"] = ExtractedField(
                field_name="transaction_count",
                value=len(txns),
                confidence=base_conf,
                source_document=src,
                evidence=f"Parsed {len(txns)} transactions from ledger table",
            )
            fields["closing_balance"] = ExtractedField(
                field_name="closing_balance",
                value=txns[-1]["balance"],
                confidence=base_conf,
                source_document=src,
                evidence=f"Final transaction on {txns[-1]['date']}: Balance INR {txns[-1]['balance']:.2f}",
            )

        if salary_credits:
            # Primary salary credit is the first/most prominent credit
            fields["salary_credit"] = ExtractedField(
                field_name="salary_credit",
                value=salary_credits[0],
                confidence=base_conf,
                source_document=src,
                evidence=f"Salary credit transaction: INR {salary_credits[0]:.2f}",
            )

        if emi_debits:
            fields["emi_debit"] = ExtractedField(
                field_name="emi_debit",
                value=emi_debits[0],
                confidence=base_conf,
                source_document=src,
                evidence=f"EMI auto-debit transaction: INR {emi_debits[0]:.2f}",
            )

        return fields

    def _extract_generic(
        self, text: str, src: str, base_conf: float
    ) -> Dict[str, ExtractedField]:
        """Generic fallback extractor looking for common identifier patterns."""
        fields: Dict[str, ExtractedField] = {}
        m_id = re.search(r"\b(APP\d{4})\b", text)
        if m_id:
            fields["applicant_id"] = ExtractedField(
                field_name="applicant_id",
                value=m_id.group(1),
                confidence=base_conf,
                source_document=src,
                evidence=m_id.group(0),
            )
        return fields
