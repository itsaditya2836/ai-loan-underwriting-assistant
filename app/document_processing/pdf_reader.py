"""PDF document reading and text extraction module.

Provides an abstraction layer over PDF processing libraries (such as PyMuPDF).
Can be swapped for alternative PDF engines without altering consumer agents.
"""

from app.utils.helpers import get_logger

logger = get_logger(__name__)


class PDFReader:
    """Handles parsing and direct text extraction from PDF files."""

    def __init__(self) -> None:
        logger.info("PDFReader initialized (Placeholder).")

    def extract_text(self, file_path: str) -> str:
        """Extract embedded textual content from a PDF document.

        TODO: Implement PyMuPDF (fitz) page-by-page extraction in Stage 3.
        """
        raise NotImplementedError("PDFReader will be implemented in Stage 3.")

    def convert_to_images(self, file_path: str) -> list:
        """Render PDF pages as image buffers for downstream OCR if needed.

        TODO: Implement PDF-to-image rasterization in Stage 3.
        """
        raise NotImplementedError(
            "PDF-to-image conversion will be implemented in Stage 3."
        )
