"""Unit tests for OCRProcessor component including preprocessing, rotation, caching, and errors."""

import io
import os
from unittest.mock import patch

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.document_processing.ocr import OCRConfig, OCRProcessingError, OCRProcessor
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


def test_ocr_preprocessing_and_low_resolution_text(ocr: OCRProcessor):
    """Verify grayscale conversion, contrast handling, upscaling, and low-res recovery."""
    # Small low-resolution image (< 1200 px width) triggers upscaling & contrast handling
    img = Image.new("RGB", (650, 220), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=24)
    draw.text((25, 45), "ACCOUNT HOLDER: PRIYA VERMA", fill=(25, 25, 25), font=font)
    draw.text((25, 110), "CLOSING BALANCE: INR 95000.00", fill=(25, 25, 25), font=font)

    pre_img, steps, _ = ocr.preprocess_image(img)
    assert pre_img.mode == "L"
    assert pre_img.width >= 1200
    assert "grayscale" in steps
    assert any(s.startswith("upscale(") for s in steps)

    extracted = ocr.process_image(img)
    assert "PRIYA" in extracted.upper()
    assert "95000" in extracted.replace(",", "")


def test_ocr_orientation_correction_and_empty_image():
    """Verify 90-degree rotated document restoration when OSD detects reliable orientation."""
    ocr = OCRProcessor(config=OCRConfig(min_osd_confidence=2.0))
    reader = PDFReader()
    sample_pdf = os.path.join(DOCUMENTS_DIR, "APP0001", "loan_application.pdf")
    base_img = reader.convert_to_images(sample_pdf, dpi=200)[0]

    rotated = base_img.rotate(90, expand=True)
    res = ocr.process_image_with_details(rotated)
    assert res.success is True
    assert res.orientation_corrected_deg == 90
    assert "HARISH CHAUHAN" in res.text.upper()

    # Empty white page returns empty string cleanly
    blank = Image.new("RGB", (800, 800), color="white")
    blank_res = ocr.process_image_with_details(blank)
    assert blank_res.success is True
    assert blank_res.text.strip() == ""


def test_ocr_selective_pages_caching_and_failure(tmp_path):
    """Verify selective ocr_pages, in-memory cache reuse, and controlled error handling."""
    ocr = OCRProcessor()
    pdf_path = tmp_path / "multi_ocr.pdf"
    doc = pymupdf.open()
    for pno in range(1, 3):
        img = Image.new("RGB", (900, 300), "white")
        draw = ImageDraw.Draw(img)
        draw.text(
            (40, 80),
            f"PAGE {pno} NET SALARY PAYABLE: INR {pno * 40000}.00",
            fill="black",
            font=ImageFont.load_default(size=24),
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page = doc.new_page()
        page.insert_image(pymupdf.Rect(50, 50, 500, 220), stream=buf.getvalue())
    doc.save(str(pdf_path))
    doc.close()

    only_p2 = ocr.ocr_pages(str(pdf_path), page_numbers=[2])
    assert len(only_p2) == 1
    assert only_p2[0].page_number == 2
    assert only_p2[0].from_cache is False
    assert "80000" in only_p2[0].text.replace(",", "").replace(" ", "")

    # Second identical call hits cache instead of rerunning Tesseract
    cached_p2 = ocr.ocr_pages(str(pdf_path), page_numbers=[2])
    assert cached_p2[0].from_cache is True

    # Failure propagation & graceful page error capture
    fresh_ocr = OCRProcessor(config=OCRConfig(cache_enabled=False))
    with patch("app.document_processing.ocr.pytesseract.image_to_string") as mock_tess:
        mock_tess.side_effect = RuntimeError("Simulated Tesseract crash")
        with pytest.raises(OCRProcessingError):
            fresh_ocr.process_image_with_details(Image.new("RGB", (200, 200), "white"))
        err_pages = fresh_ocr.ocr_pages(str(pdf_path), page_numbers=[1])
        assert len(err_pages) == 1
        assert err_pages[0].success is False
        assert "Simulated Tesseract crash" in (err_pages[0].error or "")
