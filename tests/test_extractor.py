"""Unit tests for DocumentExtractor component."""

import os

import pytest

from app.document_processing.extractor import (
    DocumentExtractor,
    parse_currency,
)
from app.document_processing.pdf_reader import PageContent, PDFReader
from app.document_processing.security import mask_identifier, mask_sensitive_text
from app.document_processing.validation import (
    VALIDATION_AMBIGUOUS,
    VALIDATION_INVALID,
    VALIDATION_MISSING,
    VALIDATION_VALID,
)

DOCUMENTS_DIR = "data/documents"


@pytest.fixture
def extractor() -> DocumentExtractor:
    return DocumentExtractor()


@pytest.fixture
def reader() -> PDFReader:
    return PDFReader()


def test_currency_parser():
    """Verify parse_currency with various formats and currency symbols."""
    assert parse_currency("INR 37,500.00") == 37500.0
    assert parse_currency("₹ 1,45,600.50") == 145600.50
    assert parse_currency("Rs. 50000") == 50000.0
    assert parse_currency("10,746.95") == 10746.95
    assert parse_currency("-") is None
    assert parse_currency("") is None
    assert parse_currency(None) is None


def test_classify_all_five_document_types(
    extractor: DocumentExtractor, reader: PDFReader
):
    """Verify classification of all 5 supported document categories."""
    samples = [
        ("APP0001", "loan_application.pdf", "loan_application"),
        ("APP0001", "identity_proof.pdf", "identity_proof"),
        ("APP0001", "salary_slip.pdf", "salary_slip"),
        ("APP0001", "bank_statement.pdf", "bank_statement"),
        ("APP0003", "income_statement.pdf", "income_statement"),
    ]

    for aid, doc_file, expected_type in samples:
        path = os.path.join(DOCUMENTS_DIR, aid, doc_file)
        text = reader.extract_text(path)
        doc_type, conf, ev = extractor.classify_document(text, doc_file)
        assert doc_type == expected_type, f"Failed on {aid}/{doc_file}"
        assert conf >= 0.90
        assert len(ev) > 0


def test_unknown_document_classification(extractor: DocumentExtractor):
    """Verify classification handles random or uninformative text."""
    doc_type, conf, _ = extractor.classify_document(
        "Random unformatted text without banking or underwriting keywords."
    )
    assert doc_type == "unknown"
    assert conf < 0.50


def test_loan_application_field_extraction(
    extractor: DocumentExtractor, reader: PDFReader
):
    """Verify field extraction from a loan application document."""
    path = os.path.join(DOCUMENTS_DIR, "APP0001", "loan_application.pdf")
    text = reader.extract_text(path)
    fields = extractor.extract_fields(text, "loan_application", "loan_application.pdf")

    assert fields["applicant_id"].value == "APP0001"
    assert fields["applicant_name"].value == "Harish Chauhan"
    assert fields["monthly_income"].value == 37500.0
    assert fields["existing_emi"].value == 16000.0
    assert fields["bank_balance"].value == 140000.0
    assert fields["credit_score"].value == 584
    assert fields["loan_amount"].value == 500000.0
    assert fields["loan_tenure"].value == 60
    assert fields["employment_type"].value == "Salaried"


def test_identity_proof_field_extraction(
    extractor: DocumentExtractor, reader: PDFReader
):
    """Verify field extraction from an identity verification document."""
    path = os.path.join(DOCUMENTS_DIR, "APP0001", "identity_proof.pdf")
    text = reader.extract_text(path)
    fields = extractor.extract_fields(text, "identity_proof", "identity_proof.pdf")

    assert fields["applicant_id"].value == "APP0001"
    assert fields["applicant_name"].value == "Harish Chauhan"
    assert fields["registered_city"].value == "Coimbatore"
    assert "SYN-ID-APP0001" in fields["id_ref"].value


def test_salary_slip_field_extraction(extractor: DocumentExtractor, reader: PDFReader):
    """Verify field extraction from a salary slip document."""
    path = os.path.join(DOCUMENTS_DIR, "APP0001", "salary_slip.pdf")
    text = reader.extract_text(path)
    fields = extractor.extract_fields(text, "salary_slip", "salary_slip.pdf")

    assert fields["employee_name"].value == "Harish Chauhan"
    assert fields["applicant_id"].value == "APP0001"
    assert "TECHNOVA SOLUTIONS" in fields["employer_name"].value.upper()
    assert fields["net_salary"].value == 37500.0
    assert fields["gross_earnings"].value == 42000.0


def test_income_statement_field_extraction(
    extractor: DocumentExtractor, reader: PDFReader
):
    """Verify field extraction from an income statement document."""
    path = os.path.join(DOCUMENTS_DIR, "APP0003", "income_statement.pdf")
    text = reader.extract_text(path)
    fields = extractor.extract_fields(text, "income_statement", "income_statement.pdf")

    assert fields["applicant_name"].value == "Ashish Singh"
    assert fields["applicant_id"].value == "APP0003"
    assert "VANGUARD LOGISTICS" in fields["business_name"].value.upper()
    assert fields["net_income"].value == 195000.0


def test_bank_statement_field_extraction(
    extractor: DocumentExtractor, reader: PDFReader
):
    """Verify field extraction and transaction parsing from a bank statement."""
    path = os.path.join(DOCUMENTS_DIR, "APP0001", "bank_statement.pdf")
    text = reader.extract_text(path)
    fields = extractor.extract_fields(text, "bank_statement", "bank_statement.pdf")

    assert fields["account_holder"].value == "Harish Chauhan"
    assert "SYN-ACC-9041-APP0001" in fields["account_number"].value
    assert fields["applicant_id"].value == "APP0001"
    assert fields["closing_balance"].value == 140000.0
    assert fields["salary_credit"].value == 37500.0
    assert fields["emi_debit"].value == 16000.0
    assert fields["transaction_count"].value >= 10


def test_classification_single_keyword_rejected_and_ambiguous_flagged(
    extractor: DocumentExtractor,
):
    """Single generic keyword does not classify; competing markers trigger AMBIGUOUS."""
    weak = extractor.classify_document_detailed(
        "Thank you. This memo briefly mentions Basic Salary in passing.",
        filename="random.pdf",
    )
    assert weak.document_type == "unknown"
    assert weak.status == "UNCLASSIFIED"
    assert weak.confidence < 0.45

    ambiguous_text = (
        "ACCOUNT STATEMENT\n"
        "ACCOUNT HOLDER: Test User\n"
        "STATEMENT PERIOD: 01-Aug-2026 to 31-Aug-2026\n"
        "PAYSLIP FOR THE MONTH\n"
        "EARNINGS COMPONENT\n"
        "DEDUCTIONS COMPONENT\n"
        "BASIC SALARY: 40,000.00\n"
    )
    amb = extractor.classify_document_detailed(ambiguous_text, filename="mixed.pdf")
    assert amb.document_type == "unknown"
    assert amb.status == "AMBIGUOUS"
    assert amb.is_ambiguous is True


def test_classification_and_extraction_for_address_and_employment_proof(
    extractor: DocumentExtractor,
):
    """Verify support for address_proof and employment_proof multi-signal classification & fields."""
    addr_text = (
        "PROOF OF ADDRESS\n"
        "Full Name: Kavita Nair\n"
        "Residential Address: 42 MG Road, Indiranagar, Bengaluru\n"
        "Postal Code: 560038\n"
        "Consumer ID: CON-88991\n"
        "Issue Date: 10-Jun-2026\n"
    )
    clf_addr = extractor.classify_document_detailed(addr_text)
    assert clf_addr.document_type == "address_proof"
    assert clf_addr.status == "CLASSIFIED"
    addr_fields = extractor.extract_fields(addr_text, "address_proof")
    assert addr_fields["applicant_name"].value == "Kavita Nair"
    assert "MG Road" in addr_fields["address"].value
    assert addr_fields["issue_date"].value == "10-Jun-2026"

    emp_text = (
        "CERTIFICATE OF EMPLOYMENT\n"
        "HUMAN RESOURCES DEPARTMENT\n"
        "Employee Name: Kavita Nair\n"
        "Employee ID: EMP-APP0201\n"
        "Employer Name: Orion Cloud Systems Pvt Ltd\n"
        "Designation: Senior Architect\n"
        "Date of Joining: 15-Mar-2021\n"
    )
    clf_emp = extractor.classify_document_detailed(emp_text)
    assert clf_emp.document_type == "employment_proof"
    emp_fields = extractor.extract_fields(emp_text, "employment_proof")
    assert emp_fields["applicant_name"].value == "Kavita Nair"
    assert emp_fields["employer_name"].value == "Orion Cloud Systems Pvt Ltd"
    assert emp_fields["designation"].value == "Senior Architect"
    assert emp_fields["employment_start_date"].value == "15-Mar-2021"


def test_field_validation_invalid_missing_zeros_ambiguity_and_context_guards(
    extractor: DocumentExtractor,
):
    """Verify validation rejects negative/invalid values, preserves zeros, and guards context."""
    bad_loan_text = (
        "SYNTHETIC LOAN APPLICATION FORM\n"
        "Applicant ID: APP8888\n"
        "Full Name: Invalid Case\n"
        "Submission Date: 32-Feb-2026\n"
        "Experience / Tenure: 10 Years\n"
        "Employment Type: SALARIED\n"
        "Declared Monthly Income: INR -50,000.00\n"
        "Existing Monthly EMI: INR 0.00\n"
        "Declared Bank Balance: INR 0.00\n"
        "Number of Dependents: 0\n"
        "Self-Reported Credit Score: 999\n"
        "Requested Amount: INR 250,000.00\n"
        "Requested Tenure: 36 Months\n"
    )
    usable, validations = extractor.extract_fields_with_diagnostics(
        bad_loan_text, "loan_application", "loan_application.pdf"
    )

    # Negative income, invalid calendar date, and credit_score > 900 rejected
    assert "monthly_income" not in usable
    assert "submission_date" not in usable
    assert "credit_score" not in usable
    assert validations["monthly_income"]["validation_status"] == VALIDATION_INVALID
    assert validations["submission_date"]["validation_status"] == VALIDATION_INVALID
    assert validations["credit_score"]["validation_status"] == VALIDATION_INVALID

    # Unlabeled '10 Years' experience does NOT wrongly match age
    assert "age" not in usable
    assert validations["age"]["validation_status"] == VALIDATION_MISSING
    assert usable["employment_years"].value == 10.0

    # Zero-valued legitimate fields preserved
    assert usable["existing_emi"].value == 0.0
    assert usable["bank_balance"].value == 0.0
    assert usable["number_of_dependents"].value == 0
    assert usable["existing_emi"].validation_status == VALIDATION_VALID

    # Non-salary bank deposit is tracked as other_income, NOT salary_credit
    bank_no_sal = (
        "SYNTHETIC APEX BANK OF INDIA\n"
        "ACCOUNT STATEMENT\n"
        "Account Holder: Priya Nair\n"
        "Statement Period: 01-Aug-2026 to 31-Aug-2026\n"
        "Account Number: SYN-ACC-9041-APP0001-82\n"
        "14-Aug-2026 INTEREST CREDIT - Q2 TXN0107 - 850.00 156,749.00\n"
    )
    b_fields = extractor.extract_fields(bank_no_sal, "bank_statement")
    assert "salary_credit" not in b_fields
    assert b_fields["other_income"].value == 850.0
    assert b_fields["account_number"].masked_value == ("*" * 19) + "1-82"
    assert "APP0001" not in mask_sensitive_text("SYN-ACC-9041-APP0001-82")
    assert mask_identifier("SYN-ID-APP0001-33737").endswith("3737")

    # Multi-page provenance & conflicting candidate ambiguity
    pages = [
        PageContent(
            page_number=1,
            text="Name: Aarti Rao\nNET SALARY PAYABLE: INR 50,000.00",
            char_count=50,
            is_scanned=False,
            has_images=False,
            extraction_method="native_text",
        ),
        PageContent(
            page_number=2,
            text="Identifier: EMP-APP0301\nNET SALARY PAYABLE: INR 65,000.00",
            char_count=55,
            is_scanned=True,
            has_images=True,
            extraction_method="ocr",
        ),
    ]
    mp_usable, mp_val = extractor.extract_fields_with_diagnostics(
        "", "salary_slip", "slip.pdf", pages=pages
    )
    assert mp_usable["employee_name"].page_number == 1
    assert mp_usable["applicant_id"].page_number == 2
    assert mp_usable["applicant_id"].extraction_method == "regex_ocr"
    assert "net_salary" not in mp_usable
    assert mp_val["net_salary"]["validation_status"] == VALIDATION_AMBIGUOUS
