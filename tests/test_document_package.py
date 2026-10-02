"""Unit tests for DocumentPackageProcessor component."""

import os

import pytest

from app.document_processing.document_package import DocumentPackageProcessor

DOCUMENTS_DIR = "data/documents"


@pytest.fixture
def package_processor() -> DocumentPackageProcessor:
    return DocumentPackageProcessor()


def test_process_normal_applicant_package(
    package_processor: DocumentPackageProcessor,
):
    """Verify processing of normal applicant APP0001 (all 4 documents present)."""
    package_dir = os.path.join(DOCUMENTS_DIR, "APP0001")
    res = package_processor.process_package("APP0001", package_dir)

    assert res.applicant_id == "APP0001"
    assert res.is_complete is True
    assert len(res.documents_missing) == 0
    assert len(res.documents_found) == 4
    assert res.ocr_used is False
    assert res.processing_status == "completed"

    found_types = {d.document_type for d in res.documents_found}
    assert found_types == {
        "loan_application",
        "identity_proof",
        "salary_slip",
        "bank_statement",
    }


def test_process_scanned_document_applicant(
    package_processor: DocumentPackageProcessor,
):
    """Verify processing of scanned applicant APP0004 (triggers OCR on salary slip)."""
    package_dir = os.path.join(DOCUMENTS_DIR, "APP0004")
    res = package_processor.process_package("APP0004", package_dir)

    assert res.applicant_id == "APP0004"
    assert res.is_complete is True
    assert res.ocr_used is True
    assert len(res.documents_found) == 4


def test_process_missing_document_cohort(
    package_processor: DocumentPackageProcessor,
):
    """Verify detection of missing documents across APP0016-APP0020 cohort."""
    expected_missing_map = {
        "APP0016": ["bank_statement"],
        "APP0017": ["salary_slip"],
        "APP0018": ["identity_proof"],
        "APP0019": ["bank_statement"],
        "APP0020": ["salary_slip"],
    }

    for aid, expected_missing in expected_missing_map.items():
        package_dir = os.path.join(DOCUMENTS_DIR, aid)
        res = package_processor.process_package(aid, package_dir)
        assert res.is_complete is False
        for exp in expected_missing:
            assert exp in res.documents_missing, f"Missing {exp} not detected in {aid}"


def test_nonexistent_package_directory(
    package_processor: DocumentPackageProcessor,
):
    """Verify graceful handling when package directory is missing."""
    res = package_processor.process_package(
        "APP9999", "data/documents/APP9999_nonexistent"
    )
    assert res.processing_status == "failed"
    assert res.is_complete is False
    assert len(res.processing_errors) > 0
