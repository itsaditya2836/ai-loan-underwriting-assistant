"""Optical Character Recognition (OCR) module.

Provides an abstraction layer over OCR engines (such as pytesseract).
Can be replaced with alternative OCR engines or cloud OCR services without
rewriting document extraction logic.
"""

from typing import Any

from app.utils.helpers import get_logger

logger = get_logger(__name__)


class OCRProcessor:
    """Handles optical character recognition on scanned images and documents."""

    def __init__(self) -> None:
        logger.info("OCRProcessor initialized (Placeholder).")

    def process_image(self, image: Any) -> str:
        """Extract text from an image using OCR.

        TODO: Implement pytesseract image-to-string extraction in Stage 3.
        """
        raise NotImplementedError("OCRProcessor will be implemented in Stage 3.")
