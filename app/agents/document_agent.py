"""Document Intake Agent module.

Responsible for ingesting loan application documents, orchestrating PDF/image
processing, triggering OCR when required, and extracting structured, traceable applicant data.
"""

import os
from typing import List, Optional

from app.document_processing.document_package import DocumentPackageProcessor
from app.document_processing.extractor import DocumentExtractor
from app.document_processing.ocr import OCRProcessor
from app.document_processing.pdf_reader import PDFReader
from app.schemas.applicant import Document, DocumentPackageResult
from app.utils.helpers import get_logger

logger = get_logger(__name__)


class DocumentIntakeAgent:
    """Agent responsible for document ingestion, local OCR, and field extraction.

    Serves as a deterministic intake layer for applicant document packages.
    Produces structured, explainable findings with source evidence and confidence scores.
    """

    def __init__(
        self,
        pdf_reader: Optional[PDFReader] = None,
        ocr_processor: Optional[OCRProcessor] = None,
        extractor: Optional[DocumentExtractor] = None,
    ) -> None:
        """Initialize DocumentIntakeAgent with underlying processing components."""
        self.reader = pdf_reader or PDFReader()
        self.ocr = ocr_processor or OCRProcessor()
        self.extractor = extractor or DocumentExtractor()
        self.package_processor = DocumentPackageProcessor(
            pdf_reader=self.reader,
            ocr_processor=self.ocr,
            extractor=self.extractor,
        )
        logger.info("DocumentIntakeAgent initialized.")

    def process_package(
        self, applicant_id: str, package_dir: Optional[str] = None
    ) -> DocumentPackageResult:
        """Process an entire applicant document package directory.

        Args:
            applicant_id: Unique applicant identifier (e.g. 'APP0001').
            package_dir: Directory containing applicant documents.
                Defaults to 'data/documents/{applicant_id}'.

        Returns:
            DocumentPackageResult with classified documents, extracted fields,
            evidence references, and missing document detection.
        """
        dir_path = package_dir or os.path.join("data", "documents", applicant_id)
        return self.package_processor.process_package(applicant_id, dir_path)

    def process(self, documents: List[Document]) -> List[Document]:
        """Process a list of Document schemas, populating extracted text and fields.

        Maintains backward compatibility with the Stage 1 Document schema contract.

        Args:
            documents: List of input Document instances.

        Returns:
            List of updated Document instances with extracted fields and text.
        """
        processed_docs: List[Document] = []
        for doc in documents:
            if not doc.file_path or not os.path.exists(doc.file_path):
                doc.status = "failed"
                processed_docs.append(doc)
                continue

            try:
                info = self.reader.read_pdf(doc.file_path)
                doc_text = info.full_text
                is_scanned = info.is_scanned

                if is_scanned:
                    ocr_pages = self.ocr.ocr_pdf(doc.file_path)
                    doc_text = "\n".join(p.text for p in ocr_pages)

                doc.extracted_text = doc_text
                classified_type, conf, ev = self.extractor.classify_document(
                    doc_text, doc.file_path
                )
                if not doc.document_type or doc.document_type == "pending":
                    doc.document_type = classified_type

                fields = self.extractor.extract_fields(
                    doc_text,
                    doc.document_type,
                    doc.file_path,
                    is_scanned=is_scanned,
                )
                # Store plain serializable dict in Document.extracted_fields
                doc.extracted_fields = {
                    fn: {
                        "value": ef.value,
                        "confidence": ef.confidence,
                        "evidence": ef.evidence,
                        "source": ef.source_document,
                    }
                    for fn, ef in fields.items()
                }
                doc.status = "processed"
            except Exception as exc:
                logger.error(f"Error processing document {doc.document_id}: {exc}")
                doc.status = "failed"

            processed_docs.append(doc)

        return processed_docs
