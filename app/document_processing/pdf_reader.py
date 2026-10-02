"""PDF document reading and text extraction module.

Provides an abstraction layer over PDF processing using PyMuPDF (fitz).
Extracts native text, detects rasterized/scanned image pages, and rasterizes pages
to PIL Images for downstream OCR when necessary.
"""

import io
import os
from dataclasses import dataclass, field
from typing import List, Optional

import pymupdf
from PIL import Image

from app.utils.helpers import get_logger

logger = get_logger(__name__)


@dataclass
class PageContent:
    """Structured text content and metadata for a single PDF page."""

    page_number: int  # 1-indexed
    text: str
    char_count: int
    is_scanned: bool
    has_images: bool


@dataclass
class PDFDocumentInfo:
    """Complete document-level extraction metadata and text contents."""

    file_path: str
    page_count: int
    is_scanned: bool
    pages: List[PageContent] = field(default_factory=list)
    full_text: str = ""
    error: Optional[str] = None


class PDFReader:
    """Handles parsing, direct text extraction, and rasterization from PDF files."""

    def __init__(self, min_char_threshold: int = 30) -> None:
        """Initialize PDFReader.

        Args:
            min_char_threshold: Minimum extracted alphanumeric characters per page
                required to classify a page as containing usable digital text.
        """
        self.min_char_threshold = min_char_threshold
        logger.info("PDFReader initialized with PyMuPDF engine.")

    def read_pdf(self, file_path: str) -> PDFDocumentInfo:
        """Open a PDF safely, extract text page-by-page, and assess scan status.

        Args:
            file_path: Absolute or relative path to the PDF document.

        Returns:
            PDFDocumentInfo containing page-level contents, overall scan classification,
            and aggregated text.
        """
        if not os.path.exists(file_path):
            err_msg = f"File not found: {file_path}"
            logger.error(err_msg)
            return PDFDocumentInfo(
                file_path=file_path,
                page_count=0,
                is_scanned=True,
                pages=[],
                full_text="",
                error=err_msg,
            )

        try:
            doc = pymupdf.open(file_path)
        except Exception as exc:
            err_msg = f"Failed to open PDF {file_path}: {exc}"
            logger.error(err_msg)
            return PDFDocumentInfo(
                file_path=file_path,
                page_count=0,
                is_scanned=True,
                pages=[],
                full_text="",
                error=err_msg,
            )

        pages: List[PageContent] = []
        text_parts: List[str] = []
        scanned_page_count = 0

        try:
            page_count = len(doc)
            for idx in range(page_count):
                page = doc[idx]
                page_num = idx + 1
                page_text = page.get_text() or ""
                stripped = page_text.strip()
                char_count = len(stripped)

                # Check if page has images
                image_list = page.get_images(full=True)
                has_images = len(image_list) > 0

                # Determine whether page is scanned/image-only
                is_page_scanned = char_count < self.min_char_threshold
                if is_page_scanned:
                    scanned_page_count += 1

                pages.append(
                    PageContent(
                        page_number=page_num,
                        text=page_text,
                        char_count=char_count,
                        is_scanned=is_page_scanned,
                        has_images=has_images,
                    )
                )
                text_parts.append(page_text)

            full_text = "\n".join(text_parts).strip()
            # If all pages or majority are scanned, flag document as scanned
            is_doc_scanned = scanned_page_count > 0 and (
                scanned_page_count == page_count
                or len(full_text) < self.min_char_threshold * page_count
            )

            return PDFDocumentInfo(
                file_path=file_path,
                page_count=page_count,
                is_scanned=is_doc_scanned,
                pages=pages,
                full_text=full_text,
            )

        except Exception as exc:
            err_msg = f"Error reading pages from {file_path}: {exc}"
            logger.error(err_msg)
            return PDFDocumentInfo(
                file_path=file_path,
                page_count=len(doc) if "doc" in locals() else 0,
                is_scanned=True,
                pages=pages,
                full_text="\n".join(text_parts).strip(),
                error=err_msg,
            )
        finally:
            doc.close()

    def extract_text(self, file_path: str) -> str:
        """Extract embedded textual content directly from a PDF document.

        Args:
            file_path: Path to the target PDF file.

        Returns:
            Aggregated raw text extracted from all pages.
        """
        info = self.read_pdf(file_path)
        if info.error:
            logger.warning(f"extract_text encountered error: {info.error}")
        return info.full_text

    def convert_to_images(self, file_path: str, dpi: int = 300) -> List[Image.Image]:
        """Render all pages of a PDF as raster PIL Images for downstream OCR.

        Args:
            file_path: Path to the target PDF file.
            dpi: Resolution dots-per-inch for rendering (defaults to 300 DPI for OCR).

        Returns:
            List of PIL Image objects, one per page.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        images: List[Image.Image] = []
        doc = pymupdf.open(file_path)
        try:
            for page in doc:
                pix = page.get_pixmap(dpi=dpi)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                # Load image data into memory before closing bytes
                img.load()
                images.append(img)
            return images
        finally:
            doc.close()

    def is_scanned_pdf(self, file_path: str) -> bool:
        """Determine whether a PDF document is scanned/image-only without usable digital text.

        Args:
            file_path: Path to the target PDF file.

        Returns:
            True if document is scanned or lacks extractable text, False otherwise.
        """
        info = self.read_pdf(file_path)
        return info.is_scanned
