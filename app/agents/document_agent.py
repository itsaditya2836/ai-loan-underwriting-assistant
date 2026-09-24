"""Document Intake Agent module.

Responsible for ingesting loan application documents, orchestrating PDF/image
processing, triggering OCR when required, and extracting structured applicant data.
"""

from typing import List

from app.schemas.applicant import Document
from app.utils.helpers import get_logger

logger = get_logger(__name__)


class DocumentIntakeAgent:
    """Agent responsible for document ingestion, OCR, and field extraction.

    Implementation will be added in Stage 3.
    """

    def __init__(self) -> None:
        logger.info("DocumentIntakeAgent initialized (Placeholder).")

    def process(self, documents: List[Document]) -> List[Document]:
        """Process loan documents and extract structured text and key fields.

        TODO: Implement PDF text extraction, OCR fallback, and structured data parsing.
        """
        raise NotImplementedError(
            "Document Intake Agent will be implemented in Stage 3."
        )
