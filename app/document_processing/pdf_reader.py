"""PDF document reading, validation, and page-level text extraction module.

Uses PyMuPDF (fitz) with page-level mixed-PDF assessment, controlled security
validation (%PDF- header, size limits, encryption checks, passive active-content
inspection), and memory-safe raster rendering for downstream OCR.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import pymupdf
from PIL import Image

from app.document_processing.security import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_MAX_PAGES,
    PDFCorruptedError,
    PDFEncryptedError,
    PDFProcessingError,
    PDFSizeLimitError,
    PDFValidationError,
    validate_pdf_file,
)
from app.utils.helpers import get_logger

logger = get_logger(__name__)


@dataclass
class PageContent:
    """Structured text content, scan status, and extraction provenance for one PDF page."""

    page_number: int  # 1-indexed
    text: str
    char_count: int
    is_scanned: bool
    has_images: bool
    alnum_char_count: int = 0
    extraction_method: str = "native_text"  # native_text | ocr_required | ocr | empty | error
    needs_ocr: bool = False
    is_blank: bool = False
    error: Optional[str] = None


@dataclass
class PDFDocumentInfo:
    """Complete document-level extraction metadata, page statuses, and text contents."""

    file_path: str
    page_count: int
    is_scanned: bool
    pages: List[PageContent] = field(default_factory=list)
    full_text: str = ""
    error: Optional[str] = None
    successful_pages: int = 0
    native_text_pages: int = 0
    ocr_pages: int = 0
    empty_pages: int = 0
    failed_pages: int = 0
    is_mixed: bool = False
    file_size_bytes: int = 0
    content_sha256: str = ""
    security_warnings: List[str] = field(default_factory=list)


class PDFReader:
    """Handles validated parsing, page-level text extraction, and PDF rasterization."""

    def __init__(
        self,
        min_char_threshold: int = 30,
        max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        """Initialize PDFReader with per-page threshold and resource safeguards."""
        self.min_char_threshold = min_char_threshold
        self.max_file_size_bytes = max_file_size_bytes
        self.max_pages = max_pages
        logger.info("PDFReader initialized with PyMuPDF engine.")

    def _open_validated_doc(
        self, file_path: str
    ) -> tuple[pymupdf.Document, int, str, List[str]]:
        """Validate file headers/limits and open a PyMuPDF document safely."""
        file_size, sha256, warnings = validate_pdf_file(
            file_path, max_file_size_bytes=self.max_file_size_bytes
        )
        for warning in warnings:
            logger.warning("PDF security notice: %s", warning)

        try:
            doc = pymupdf.open(file_path)
        except Exception as exc:
            raise PDFCorruptedError(
                f"Failed to open PDF {os.path.basename(file_path)}: {exc}"
            ) from exc

        try:
            if getattr(doc, "needs_pass", False) or getattr(doc, "is_encrypted", False):
                if getattr(doc, "needs_pass", False):
                    raise PDFEncryptedError(
                        f"PDF is password-protected/encrypted: {os.path.basename(file_path)}"
                    )
            page_count = len(doc)
            if page_count <= 0:
                raise PDFCorruptedError(
                    f"PDF contains 0 pages: {os.path.basename(file_path)}"
                )
            if self.max_pages > 0 and page_count > self.max_pages:
                raise PDFSizeLimitError(
                    f"PDF page count ({page_count}) exceeds maximum allowed ({self.max_pages})"
                )
        except Exception:
            doc.close()
            raise

        return doc, file_size, sha256, warnings

    def read_pdf(self, file_path: str, strict: bool = False) -> PDFDocumentInfo:
        """Inspect every PDF page independently to extract digital text and flag OCR pages.

        Args:
            file_path: Path to the PDF document.
            strict: If True, raise controlled exceptions on validation/read errors instead
                of returning PDFDocumentInfo(error=...).
        """
        try:
            doc, file_size, sha256, sec_warnings = self._open_validated_doc(file_path)
        except (FileNotFoundError, PDFProcessingError) as exc:
            err_msg = str(exc)
            logger.error("%s", err_msg)
            if strict:
                raise
            return PDFDocumentInfo(
                file_path=file_path,
                page_count=0,
                is_scanned=False,
                pages=[],
                full_text="",
                error=err_msg,
                failed_pages=0,
            )

        pages: List[PageContent] = []
        text_parts: List[str] = []
        native_text_pages = 0
        ocr_needed_pages = 0
        empty_pages = 0
        failed_pages = 0

        try:
            page_count = len(doc)
            for idx in range(page_count):
                page_num = idx + 1
                try:
                    page = doc[idx]
                    page_text = page.get_text() or ""
                    stripped = page_text.strip()
                    char_count = len(stripped)
                    alnum_count = sum(1 for ch in stripped if ch.isalnum())

                    image_list = page.get_images(full=True)
                    has_images = len(image_list) > 0
                    has_drawings = bool(page.get_drawings())

                    if alnum_count >= self.min_char_threshold:
                        method = "native_text"
                        needs_ocr = False
                        is_blank = False
                        native_text_pages += 1
                    elif has_images or has_drawings or alnum_count > 0:
                        method = "ocr_required"
                        needs_ocr = True
                        is_blank = False
                        ocr_needed_pages += 1
                    else:
                        method = "empty"
                        needs_ocr = False
                        is_blank = True
                        empty_pages += 1

                    pages.append(
                        PageContent(
                            page_number=page_num,
                            text=page_text,
                            char_count=char_count,
                            is_scanned=needs_ocr,
                            has_images=has_images,
                            alnum_char_count=alnum_count,
                            extraction_method=method,
                            needs_ocr=needs_ocr,
                            is_blank=is_blank,
                        )
                    )
                    text_parts.append(page_text)
                except Exception as page_exc:
                    failed_pages += 1
                    page_err = f"Page {page_num} unreadable: {page_exc}"
                    logger.warning("%s (%s)", page_err, os.path.basename(file_path))
                    pages.append(
                        PageContent(
                            page_number=page_num,
                            text="",
                            char_count=0,
                            is_scanned=False,
                            has_images=False,
                            alnum_char_count=0,
                            extraction_method="error",
                            needs_ocr=False,
                            is_blank=False,
                            error=page_err,
                        )
                    )
                    text_parts.append("")

            full_text = "\n".join(text_parts).strip()
            is_mixed = native_text_pages > 0 and ocr_needed_pages > 0
            # Document requires OCR if any page needs OCR (covers both full-scan & mixed PDFs)
            is_doc_scanned = ocr_needed_pages > 0
            successful_pages = page_count - failed_pages

            return PDFDocumentInfo(
                file_path=file_path,
                page_count=page_count,
                is_scanned=is_doc_scanned,
                pages=pages,
                full_text=full_text,
                error=(
                    f"{failed_pages} page(s) failed extraction"
                    if failed_pages == page_count and page_count > 0
                    else None
                ),
                successful_pages=successful_pages,
                native_text_pages=native_text_pages,
                ocr_pages=0,  # Populated once OCRProcessor runs on ocr_needed_pages
                empty_pages=empty_pages,
                failed_pages=failed_pages,
                is_mixed=is_mixed,
                file_size_bytes=file_size,
                content_sha256=sha256,
                security_warnings=sec_warnings,
            )
        except Exception as exc:
            err_msg = f"Error reading pages from {os.path.basename(file_path)}: {exc}"
            logger.error("%s", err_msg)
            if strict:
                raise PDFCorruptedError(err_msg) from exc
            return PDFDocumentInfo(
                file_path=file_path,
                page_count=len(doc) if "doc" in locals() else 0,
                is_scanned=True,
                pages=pages,
                full_text="\n".join(text_parts).strip(),
                error=err_msg,
                failed_pages=failed_pages,
                file_size_bytes=file_size,
                content_sha256=sha256,
                security_warnings=sec_warnings,
            )
        finally:
            doc.close()

    def extract_text(self, file_path: str) -> str:
        """Extract embedded digital text directly from a PDF document."""
        info = self.read_pdf(file_path)
        if info.error:
            logger.warning("extract_text encountered error: %s", info.error)
        return info.full_text

    def render_page_image(
        self, file_path: str, page_number: int, dpi: int = 300
    ) -> Image.Image:
        """Render a single 1-indexed PDF page to a PIL Image safely."""
        if page_number < 1:
            raise PDFValidationError(f"Page number must be >= 1 (got {page_number})")

        doc, _, _, _ = self._open_validated_doc(file_path)
        pix = None
        try:
            if page_number > len(doc):
                raise PDFValidationError(
                    f"Page number {page_number} out of range (1..{len(doc)})"
                )
            page = doc[page_number - 1]
            pix = page.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            img.load()
            return img
        finally:
            pix = None
            doc.close()

    def convert_to_images(
        self,
        file_path: str,
        dpi: int = 300,
        page_numbers: Optional[Sequence[int]] = None,
    ) -> List[Image.Image]:
        """Render requested (or all) pages of a PDF as raster PIL Images safely."""
        doc, _, _, _ = self._open_validated_doc(file_path)
        images: List[Image.Image] = []
        try:
            target_indices = (
                [p - 1 for p in page_numbers if 1 <= p <= len(doc)]
                if page_numbers is not None
                else list(range(len(doc)))
            )
            for idx in target_indices:
                pix = doc[idx].get_pixmap(dpi=dpi)
                try:
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    img.load()
                    images.append(img)
                finally:
                    pix = None
            return images
        finally:
            doc.close()

    def is_scanned_pdf(self, file_path: str) -> bool:
        """Return True when any page in the PDF requires OCR extraction."""
        info = self.read_pdf(file_path)
        return info.is_scanned


__all__ = [
    "PDFCorruptedError",
    "PDFDocumentInfo",
    "PDFEncryptedError",
    "PDFProcessingError",
    "PDFReader",
    "PDFSizeLimitError",
    "PDFValidationError",
    "PageContent",
]
