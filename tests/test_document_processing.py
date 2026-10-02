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


def test_document_agent_execution():
    """Verify DocumentIntakeAgent can process empty list cleanly."""
    agent = DocumentIntakeAgent()
    assert agent is not None
    assert agent.process([]) == []


def test_document_processing_components():
    """Verify PDFReader, OCRProcessor, and DocumentExtractor functionality."""
    reader = PDFReader()
    ocr = OCRProcessor()
    extractor = DocumentExtractor()

    # Reader handles non-existent gracefully
    info = reader.read_pdf("dummy.pdf")
    assert info.error is not None

    # OCR raises ValueError on None input
    with pytest.raises(ValueError):
        ocr.process_image(None)

    # Extractor extracts fields on dummy text without error
    fields = extractor.extract_fields("dummy text", "salary_slip")
    assert isinstance(fields, dict)
