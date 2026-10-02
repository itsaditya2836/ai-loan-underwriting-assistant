"""Unit tests for DocumentExtractor component."""

import os

import pytest

from app.document_processing.extractor import (
    DocumentExtractor,
    parse_currency,
)
from app.document_processing.pdf_reader import PDFReader

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
