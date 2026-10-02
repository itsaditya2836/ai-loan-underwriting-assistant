"""Unit tests for PDFReader component."""

import os

import pytest
from PIL import Image

from app.document_processing.pdf_reader import PDFReader

DOCUMENTS_DIR = "data/documents"


@pytest.fixture
def reader() -> PDFReader:
    return PDFReader()


def test_digital_pdf_text_extraction(reader: PDFReader):
    """Verify text extraction from a standard digital PDF."""
    pdf_path = os.path.join(DOCUMENTS_DIR, "APP0001", "loan_application.pdf")
    assert os.path.exists(pdf_path)

    info = reader.read_pdf(pdf_path)
    assert info.error is None
    assert info.page_count >= 1
    assert not info.is_scanned
    assert "LOAN APPLICATION" in info.full_text.upper()
    assert "Harish Chauhan" in info.full_text


def test_scanned_pdf_detection(reader: PDFReader):
    """Verify that rasterized/scanned PDFs are detected as scanned."""
    pdf_path = os.path.join(DOCUMENTS_DIR, "APP0004", "salary_slip.pdf")
    assert os.path.exists(pdf_path)

    info = reader.read_pdf(pdf_path)
    assert info.is_scanned is True
    assert len(info.full_text.strip()) == 0
    assert reader.is_scanned_pdf(pdf_path) is True


def test_convert_to_images(reader: PDFReader):
    """Verify conversion of PDF pages to PIL Image objects."""
    pdf_path = os.path.join(DOCUMENTS_DIR, "APP0001", "identity_proof.pdf")
    assert os.path.exists(pdf_path)

    images = reader.convert_to_images(pdf_path, dpi=150)
    assert len(images) >= 1
    assert isinstance(images[0], Image.Image)
    assert images[0].width > 100
    assert images[0].height > 100


def test_nonexistent_pdf_handling(reader: PDFReader):
    """Verify graceful handling when PDF file does not exist."""
    fake_path = "data/documents/APP9999/nonexistent.pdf"
    info = reader.read_pdf(fake_path)
    assert info.error is not None
    assert info.page_count == 0

    with pytest.raises(FileNotFoundError):
        reader.convert_to_images(fake_path)


def test_page_content_preservation(reader: PDFReader):
    """Verify page numbers and individual page metadata are preserved."""
    pdf_path = os.path.join(DOCUMENTS_DIR, "APP0001", "bank_statement.pdf")
    info = reader.read_pdf(pdf_path)
    assert len(info.pages) == info.page_count
    for idx, page in enumerate(info.pages):
        assert page.page_number == idx + 1
        assert page.char_count == len(page.text.strip())
