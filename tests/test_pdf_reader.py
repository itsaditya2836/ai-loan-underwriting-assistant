"""Unit tests for PDFReader component including mixed PDFs and failure safeguards."""

import io
import os

import pymupdf
import pytest
from PIL import Image, ImageDraw

from app.document_processing.pdf_reader import (
    PDFCorruptedError,
    PDFEncryptedError,
    PDFReader,
    PDFSizeLimitError,
    PDFValidationError,
)

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


def test_mixed_text_scanned_and_blank_pdf_pages(reader: PDFReader, tmp_path):
    """Verify page-level tracking on a mixed PDF (digital + scanned + blank)."""
    pdf_path = tmp_path / "mixed_test.pdf"
    doc = pymupdf.open()

    p1 = doc.new_page()
    p1.insert_text(
        (72, 72),
        "LOAN APPLICATION FORM\nApplicant ID: APP9991\nFull Name: Priya Verma\nDeclared Monthly Income: INR 75,000.00",
        fontsize=11,
    )

    img = Image.new("RGB", (800, 300), "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 80), "NET SALARY PAYABLE: INR 75,000.00", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    p2 = doc.new_page()
    p2.insert_image(pymupdf.Rect(50, 50, 500, 220), stream=buf.getvalue())

    doc.new_page()  # Blank Page 3
    doc.save(str(pdf_path))
    doc.close()

    info = reader.read_pdf(str(pdf_path))
    assert info.error is None
    assert info.page_count == 3
    assert info.is_mixed is True
    assert info.is_scanned is True
    assert info.native_text_pages == 1
    assert info.empty_pages == 1
    assert info.pages[0].extraction_method == "native_text"
    assert info.pages[0].needs_ocr is False
    assert info.pages[1].extraction_method == "ocr_required"
    assert info.pages[1].needs_ocr is True
    assert info.pages[2].extraction_method == "empty"
    assert info.pages[2].is_blank is True


def test_pdf_security_and_reliability_failures(reader: PDFReader, tmp_path):
    """Verify empty, corrupted, wrong extension, encrypted, oversized, and active-content PDFs."""
    # 1. Empty 0-byte PDF
    empty_pdf = tmp_path / "empty.pdf"
    empty_pdf.write_bytes(b"")
    assert reader.read_pdf(str(empty_pdf)).error is not None
    with pytest.raises(PDFCorruptedError):
        reader.read_pdf(str(empty_pdf), strict=True)

    # 2. Invalid signature / corrupted header
    bad_sig = tmp_path / "not_a_pdf.pdf"
    bad_sig.write_text("Plain text masquerading as PDF", encoding="utf-8")
    with pytest.raises(PDFValidationError):
        reader.read_pdf(str(bad_sig), strict=True)

    # 3. Corrupted PDF body with %PDF- prefix
    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"%PDF-1.4\n%%corrupted-truncated-xref")
    assert reader.read_pdf(str(corrupt_pdf)).error is not None
    with pytest.raises(PDFCorruptedError):
        reader.read_pdf(str(corrupt_pdf), strict=True)

    # 4. Unsupported extension
    wrong_ext = tmp_path / "doc.txt"
    wrong_ext.write_text("%PDF-1.4", encoding="utf-8")
    with pytest.raises(PDFValidationError):
        reader.read_pdf(str(wrong_ext), strict=True)

    # 5. Password-protected PDF
    enc_pdf = tmp_path / "encrypted.pdf"
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((72, 72), "Confidential financial statement")
    doc.save(
        str(enc_pdf),
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner123",
        user_pw="user123",
    )
    doc.close()
    assert "password-protected" in (reader.read_pdf(str(enc_pdf)).error or "").lower()
    with pytest.raises(PDFEncryptedError):
        reader.read_pdf(str(enc_pdf), strict=True)

    # 6. Size limit & max_pages enforcement
    valid_pdf = os.path.join(DOCUMENTS_DIR, "APP0001", "loan_application.pdf")
    tiny_limit_reader = PDFReader(max_file_size_bytes=50)
    with pytest.raises(PDFSizeLimitError):
        tiny_limit_reader.read_pdf(valid_pdf, strict=True)

    multi_pdf = tmp_path / "many_pages.pdf"
    mdoc = pymupdf.open()
    for _ in range(4):
        mdoc.new_page().insert_text((72, 72), "Page body content with enough text.")
    mdoc.save(str(multi_pdf))
    mdoc.close()
    page_limit_reader = PDFReader(max_pages=2)
    with pytest.raises(PDFSizeLimitError):
        page_limit_reader.read_pdf(str(multi_pdf), strict=True)

    # 7. Passive /JavaScript warning detection
    js_pdf = tmp_path / "active_marker.pdf"
    jdoc = pymupdf.open()
    jdoc.new_page().insert_text(
        (72, 72), "Safe body text for testing passive warning scan."
    )
    jdoc.save(str(js_pdf))
    jdoc.close()
    raw_bytes = js_pdf.read_bytes() + b"\n% /OpenAction /JavaScript test marker\n"
    js_pdf.write_bytes(raw_bytes)
    js_info = reader.read_pdf(str(js_pdf))
    assert any(
        "/JavaScript" in w or "/OpenAction" in w for w in js_info.security_warnings
    )
