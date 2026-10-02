"""Unit tests for OCRProcessor component."""

import os

import pytest

from app.document_processing.ocr import OCRProcessor
from app.document_processing.pdf_reader import PDFReader

DOCUMENTS_DIR = "data/documents"


@pytest.fixture
def ocr() -> OCRProcessor:
    return OCRProcessor()


@pytest.fixture
def reader() -> PDFReader:
    return PDFReader()


def test_ocr_scanned_salary_slip(ocr: OCRProcessor):
    """Verify OCR text recovery on scanned salary slip APP0004."""
    pdf_path = os.path.join(DOCUMENTS_DIR, "APP0004", "salary_slip.pdf")
    assert os.path.exists(pdf_path)

    pages = ocr.ocr_pdf(pdf_path, dpi=300)
    assert len(pages) >= 1
    ocr_text = "\n".join(p.text for p in pages)

    assert "Lavanya Saxena" in ocr_text
    assert "EMP-APP0004" in ocr_text
    assert "PAYSLIP" in ocr_text.upper()
    assert "130,000" in ocr_text or "130000" in ocr_text


def test_ocr_scanned_bank_statement(ocr: OCRProcessor):
    """Verify OCR text recovery on scanned bank statement APP0005."""
    pdf_path = os.path.join(DOCUMENTS_DIR, "APP0005", "bank_statement.pdf")
    assert os.path.exists(pdf_path)

    pages = ocr.ocr_pdf(pdf_path, dpi=300)
    assert len(pages) >= 1
    ocr_text = "\n".join(p.text for p in pages)

    assert "Shruti Tiwari" in ocr_text
    assert "ACCOUNT STATEMENT" in ocr_text.upper()
    assert "SYN-ACC-9041-APP0005-82" in ocr_text


def test_ocr_process_direct_image(ocr: OCRProcessor, reader: PDFReader):
    """Verify process_image on a PIL Image object."""
    pdf_path = os.path.join(DOCUMENTS_DIR, "APP0009", "salary_slip.pdf")
    images = reader.convert_to_images(pdf_path, dpi=200)
    assert len(images) > 0

    text = ocr.process_image(images[0])
    assert "Siddharth Sen" in text
    assert "EMP-APP0009" in text


def test_ocr_invalid_input(ocr: OCRProcessor):
    """Verify error handling on invalid image inputs."""
    with pytest.raises(ValueError):
        ocr.process_image(None)

    with pytest.raises(FileNotFoundError):
        ocr.ocr_pdf("data/documents/nonexistent/doc.pdf")
