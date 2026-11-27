"""Document Intake Agent module.

Responsible for ingesting loan application documents, coordinating page-level
PDF reading, selective OCR on scanned/mixed pages, multi-signal classification,
and structured, validated entity extraction.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import List, Optional

from app.document_processing.document_package import DocumentPackageProcessor
from app.document_processing.extractor import DocumentExtractor
from app.document_processing.ocr import OCRProcessor
from app.document_processing.pdf_reader import PageContent, PDFReader
from app.document_processing.security import mask_identifier
from app.schemas.applicant import Document, DocumentPackageResult
from app.utils.helpers import get_logger

logger = get_logger(__name__)


class DocumentIntakeAgent:
    """Agent responsible for document ingestion, local OCR, and field extraction."""

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
        """Process an entire applicant document package directory."""
        dir_path = package_dir or os.path.join("data", "documents", applicant_id)
        return self.package_processor.process_package(applicant_id, dir_path)

    def process(self, documents: List[Document]) -> List[Document]:
        """Process a list of Document schemas using page-level PDF + selective OCR."""
        processed_docs: List[Document] = []
        for doc in documents:
            if not doc.file_path or not os.path.exists(doc.file_path):
                doc.status = "failed"
                processed_docs.append(doc)
                continue

            try:
                info = self.reader.read_pdf(doc.file_path)
                if info.error and not info.pages:
                    raise RuntimeError(info.error)

                merged_pages: List[PageContent] = [replace(p) for p in info.pages]
                ocr_needed = [p.page_number for p in merged_pages if p.needs_ocr]
                if ocr_needed:
                    ocr_results = {
                        r.page_number: r
                        for r in self.ocr.ocr_pages(
                            doc.file_path, page_numbers=ocr_needed
                        )
                    }
                    for idx, p in enumerate(merged_pages):
                        if (
                            p.page_number in ocr_results
                            and ocr_results[p.page_number].success
                        ):
                            ocr_txt = ocr_results[p.page_number].text
                            merged_pages[idx] = replace(
                                p,
                                text=ocr_txt,
                                char_count=len(ocr_txt.strip()),
                                extraction_method="ocr",
                                needs_ocr=False,
                            )

                doc_text = "\n".join(p.text for p in merged_pages if p.text).strip()
                is_scanned = info.is_scanned or any(
                    p.extraction_method == "ocr" for p in merged_pages
                )
                doc.extracted_text = doc_text

                if not doc_text:
                    doc.status = "failed"
                    processed_docs.append(doc)
                    continue

                classified_type, _, _ = self.extractor.classify_document(
                    doc_text, doc.file_path
                )
                if not doc.document_type or doc.document_type == "pending":
                    doc.document_type = classified_type

                fields = self.extractor.extract_fields(
                    raw_text=doc_text,
                    document_type=doc.document_type,
                    filename=os.path.basename(doc.file_path),
                    is_scanned=is_scanned,
                    pages=merged_pages,
                )
                doc.extracted_fields = {
                    fn: {
                        "value": ef.value,
                        "confidence": ef.confidence,
                        "evidence": ef.evidence,
                        "source": ef.source_document,
                        "page_number": ef.page_number,
                        "extraction_method": ef.extraction_method,
                        "validation_status": ef.validation_status,
                        "masked_value": ef.masked_value,
                    }
                    for fn, ef in fields.items()
                }
                doc.status = "processed"
            except Exception as exc:
                logger.error(
                    "Error processing document %s: %s",
                    mask_identifier(doc.document_id),
                    exc,
                )
                doc.status = "failed"

            processed_docs.append(doc)

        return processed_docs
