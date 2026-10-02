"""Unit tests for DocumentIntakeAgent."""

import os

import pytest

from app.agents.document_agent import DocumentIntakeAgent
from app.schemas.applicant import Document

DOCUMENTS_DIR = "data/documents"


@pytest.fixture
def agent() -> DocumentIntakeAgent:
    return DocumentIntakeAgent()


def test_agent_process_package(agent: DocumentIntakeAgent):
    """Verify DocumentIntakeAgent processes package for APP0001."""
    res = agent.process_package("APP0001")
    assert res.applicant_id == "APP0001"
    assert res.is_complete is True
    assert len(res.documents_found) == 4
    assert len(res.all_extracted_fields) > 0


def test_agent_process_document_list(agent: DocumentIntakeAgent):
    """Verify agent process() method works with List[Document] models."""
    sample_path = os.path.join(DOCUMENTS_DIR, "APP0001", "loan_application.pdf")
    assert os.path.exists(sample_path)

    doc = Document(
        document_id="doc_test_001",
        applicant_id="APP0001",
        document_type="pending",
        file_path=sample_path,
    )

    results = agent.process([doc])
    assert len(results) == 1
    processed = results[0]
    assert processed.status == "processed"
    assert processed.document_type == "loan_application"
    assert processed.extracted_text is not None
    assert len(processed.extracted_text) > 100
    assert "applicant_name" in processed.extracted_fields
    assert processed.extracted_fields["applicant_name"]["value"] == "Harish Chauhan"


def test_agent_traceable_evidence(agent: DocumentIntakeAgent):
    """Verify that extracted fields preserve provenance and confidence scores."""
    res = agent.process_package("APP0001")
    for name, field in res.all_extracted_fields.items():
        assert field.confidence > 0.5
        assert len(field.evidence) > 0
        assert len(field.source_document) > 0
