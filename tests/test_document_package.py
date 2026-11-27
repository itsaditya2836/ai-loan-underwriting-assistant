"""Unit tests for DocumentPackageProcessor including mixed PDFs, duplicates, and conflicts."""

import io
import os
import shutil

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.agents.decision_agent import DecisionReasoningAgent
from app.document_processing.document_package import DocumentPackageProcessor
from app.orchestration.orchestrator import UnderwritingOrchestrator
from app.schemas.applicant import Applicant
from app.schemas.decision import DecisionOutcome
from app.schemas.underwriting import OrchestrationStatus

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


def test_package_mixed_pdf_selective_ocr_duplicates_and_conflicts(
    package_processor: DocumentPackageProcessor, tmp_path
):
    """Verify mixed PDF OCR, binary duplicate skip, conflict preservation, and unclassified docs."""
    # 1. Mixed text+scanned PDF loan application / salary slip hybrid
    mixed_pdf = tmp_path / "salary_slip.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text(
        (72, 72),
        "SYNTHETIC DOCUMENT — FOR SOFTWARE TESTING ONLY\n"
        "ALPHA LABS PVT LTD\n"
        "PAYSLIP FOR THE MONTH OF AUGUST 2026\n"
        "Name: Meera Kulkarni\n"
        "Identifier: EMP-APP7001\n"
        "Period: 01-Aug-2026 to 31-Aug-2026\n",
        fontsize=11,
    )
    img = Image.new("RGB", (1100, 420), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=24)
    draw.text((40, 60), "Basic Salary: 60,000.00", fill="black", font=font)
    draw.text((40, 120), "Total Gross Earnings: 80,000.00", fill="black", font=font)
    draw.text((40, 180), "NET SALARY PAYABLE: INR 72,000.00", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc.new_page().insert_image(pymupdf.Rect(50, 50, 520, 260), stream=buf.getvalue())
    doc.save(str(mixed_pdf))
    doc.close()

    # 2. Exact binary duplicate of salary_slip.pdf
    shutil.copyfile(str(mixed_pdf), str(tmp_path / "salary_slip_copy.pdf"))

    # 3. Distinct second salary slip with different net salary -> preserves conflict
    slip2 = tmp_path / "salary_slip_sep.pdf"
    d2 = pymupdf.open()
    d2.new_page().insert_text(
        (72, 72),
        "ALPHA LABS PVT LTD\n"
        "PAYSLIP FOR THE MONTH OF SEPTEMBER 2026\n"
        "Name: Meera Kulkarni\n"
        "Identifier: EMP-APP7001\n"
        "NET SALARY PAYABLE: INR 76,000.00\n",
        fontsize=11,
    )
    d2.save(str(slip2))
    d2.close()

    # 4. Unclassifiable document
    unk = tmp_path / "misc_note.pdf"
    du = pymupdf.open()
    du.new_page().insert_text(
        (72, 72), "General cover letter without structured data or forms."
    )
    du.save(str(unk))
    du.close()

    res = package_processor.process_package("APP7001", str(tmp_path))
    assert res.ocr_used is True
    assert res.native_text_pages == 3  # page 1 of mixed + slip2 + misc_note
    assert res.ocr_pages == 1  # only page 2 of mixed_pdf triggered OCR
    assert len(res.duplicate_documents) == 1
    assert res.duplicate_documents[0]["duplicate_file"] == "salary_slip_copy.pdf"
    assert "misc_note.pdf" in res.unclassified_documents
    assert "net_salary" in res.field_conflicts
    assert (
        res.is_complete is False
    )  # Missing bank_statement, loan_application, identity_proof


def test_package_empty_and_corrupt_preserves_orchestrator_fallback(tmp_path):
    """Empty/corrupted package emits no fabricated data and triggers manual review."""
    corrupt = tmp_path / "bad.pdf"
    corrupt.write_bytes(b"%PDF-1.4\nbroken")

    pkg_proc = DocumentPackageProcessor()
    res = pkg_proc.process_package("APP8001", str(tmp_path))
    assert res.processing_status == "failed"
    assert res.is_complete is False
    assert res.all_extracted_fields == {}
    assert len(res.processing_errors) == 1

    # End-to-end orchestrator fallback keeps manual-review safeguard intact
    qualifying = Applicant(
        applicant_id="APP8001",
        name="Qualifying Applicant",
        age=33,
        employment_type="Salaried",
        employment_years=5.0,
        monthly_income=95000.0,
        existing_emi=5000.0,
        loan_amount=500000.0,
        loan_tenure=48,
        credit_score=775,
        bank_balance=300000.0,
    )
    orch = UnderwritingOrchestrator()
    analysis = orch.run_pipeline(qualifying, package_dir=str(tmp_path))
    decision = DecisionReasoningAgent().evaluate(analysis)
    assert analysis.orchestration_status == OrchestrationStatus.PARTIAL_SUCCESS
    assert analysis.eligibility_result is not None
    assert "DOCUMENTS_COMPLETE" in analysis.eligibility_result.rules_requiring_review
    assert decision.recommendation == DecisionOutcome.MANUAL_REVIEW
