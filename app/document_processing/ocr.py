"""Optical Character Recognition (OCR) module.

Provides a robust, local OCR pipeline using PyMuPDF page rendering, Pillow,
and pytesseract interfacing with the local Tesseract OCR engine.
"""

import io
import os
import shutil
from typing import Any, List, Optional

import pymupdf
import pytesseract
from PIL import Image

from app.document_processing.pdf_reader import PageContent
from app.utils.helpers import get_logger

logger = get_logger(__name__)


def _find_tesseract_binary() -> Optional[str]:
    """Locate local tesseract executable across standard system paths."""
    # 1. Check if already in PATH
    found = shutil.which("tesseract")
    if found:
        return found

    # 2. Check known environments
    candidates = [
        "/opt/anaconda3/bin/tesseract",
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/usr/bin/tesseract",
        os.path.abspath(".venv/bin/tesseract"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


class OCRProcessor:
    """Handles optical character recognition on scanned images and document pages."""

    def __init__(
        self,
        tesseract_cmd: Optional[str] = None,
        default_dpi: int = 300,
        tesseract_config: str = "--oem 3 --psm 6",
    ) -> None:
        """Initialize OCRProcessor with local Tesseract configuration.

        Args:
            tesseract_cmd: Optional explicit path to tesseract binary.
            default_dpi: Raster rendering DPI for PDF pages before OCR.
            tesseract_config: Tesseract engine mode and page segmentation flags.
        """
        self.default_dpi = default_dpi
        self.tesseract_config = tesseract_config

        cmd = tesseract_cmd or _find_tesseract_binary()
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
            logger.info(f"OCRProcessor initialized with Tesseract at: {cmd}")
        else:
            logger.warning(
                "Tesseract executable not found in PATH or standard locations. "
                "OCR may fail if called."
            )

    def process_image(self, image: Any) -> str:
        """Extract text from an image using local Tesseract OCR.

        Args:
            image: PIL.Image instance or image bytes/array.

        Returns:
            Extracted text string.
        """
        if image is None:
            raise ValueError("Cannot process None image in OCRProcessor.")

        if not isinstance(image, Image.Image):
            try:
                if isinstance(image, (bytes, bytearray)):
                    image = Image.open(io.BytesIO(image))
                else:
                    image = Image.fromarray(image)
            except Exception as exc:
                err_msg = f"Failed to convert image for OCR: {exc}"
                logger.error(err_msg)
                raise ValueError(err_msg) from exc

        try:
            # Ensure RGB mode for clean OCR processing
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")

            text = pytesseract.image_to_string(image, config=self.tesseract_config)
            return text or ""
        except Exception as exc:
            logger.error(f"Tesseract OCR processing failed: {exc}")
            raise RuntimeError(f"OCR execution failed: {exc}") from exc

    def ocr_page(self, page: pymupdf.Page, dpi: Optional[int] = None) -> str:
        """Render a single PyMuPDF page as raster image and perform OCR.

        Args:
            page: PyMuPDF Page instance.
            dpi: Resolution dots-per-inch override (defaults to self.default_dpi).

        Returns:
            Extracted text string from page.
        """
        resolution = dpi or self.default_dpi
        pix = page.get_pixmap(dpi=resolution)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        try:
            return self.process_image(img)
        finally:
            img.close()

    def ocr_pdf(self, file_path: str, dpi: Optional[int] = None) -> List[PageContent]:
        """Perform OCR across all pages of a PDF document.

        Args:
            file_path: Path to the target PDF file.
            dpi: Resolution dots-per-inch override.

        Returns:
            List of PageContent objects with OCR-extracted text per page.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF not found for OCR: {file_path}")

        resolution = dpi or self.default_dpi
        pages: List[PageContent] = []
        doc = pymupdf.open(file_path)

        try:
            for idx, page in enumerate(doc):
                page_num = idx + 1
                try:
                    ocr_text = self.ocr_page(page, dpi=resolution)
                except Exception as exc:
                    logger.warning(
                        f"OCR failed for page {page_num} of {file_path}: {exc}"
                    )
                    ocr_text = ""

                pages.append(
                    PageContent(
                        page_number=page_num,
                        text=ocr_text,
                        char_count=len(ocr_text.strip()),
                        is_scanned=True,
                        has_images=True,
                    )
                )
            return pages
        finally:
            doc.close()
