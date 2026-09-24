"""Document Information Extractor module.

Parses unstructured document text (from direct extraction or OCR) into structured
key-value pairs such as applicant income, employer name, dates, and account numbers.
"""

from typing import Any, Dict

from app.utils.helpers import get_logger

logger = get_logger(__name__)


class DocumentExtractor:
    """Extracts structured key-value data from raw document text."""

    def __init__(self) -> None:
        logger.info("DocumentExtractor initialized (Placeholder).")

    def extract_fields(self, raw_text: str, document_type: str) -> Dict[str, Any]:
        """Extract structured entities from raw document text based on document type.

        TODO: Implement regex/NLP pattern extraction in Stage 3.
        """
        raise NotImplementedError("DocumentExtractor will be implemented in Stage 3.")
