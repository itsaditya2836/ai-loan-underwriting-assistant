"""Tests for Document Processing foundation and DocumentIntakeAgent."""

import pytest

from app.agents.document_agent import DocumentIntakeAgent
from app.document_processing.extractor import DocumentExtractor
from app.document_processing.ocr import OCRProcessor
from app.document_processing.pdf_reader import PDFReader
from app.schemas.applicant import Document


def test_document_schema_instantiation():
    """Verify Document Pydantic model can be instantiated with valid fields."""
    doc = Document(
        document_id="doc_001",
        applicant_id="app_123",
        document_type="salary_slip",
        file_path="data/documents/sample_slip.pdf",
    )
    assert doc.document_id == "doc_001"
    assert doc.status == "pending"
    assert doc.extracted_text is None
    assert doc.extracted_fields == {}


def test_document_agent_placeholder():
    """Verify DocumentIntakeAgent can be initialized and raises NotImplementedError."""
    agent = DocumentIntakeAgent()
    assert agent is not None

    with pytest.raises(NotImplementedError, match="Stage 3"):
        agent.process([])


def test_document_processing_components():
    """Verify PDFReader, OCRProcessor, and DocumentExtractor placeholders."""
    reader = PDFReader()
    ocr = OCRProcessor()
    extractor = DocumentExtractor()

    with pytest.raises(NotImplementedError):
        reader.extract_text("dummy.pdf")

    with pytest.raises(NotImplementedError):
        ocr.process_image(None)

    with pytest.raises(NotImplementedError):
        extractor.extract_fields("dummy text", "salary_slip")
