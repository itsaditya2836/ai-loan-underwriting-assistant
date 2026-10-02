"""Document Package Processor module.

Coordinates end-to-end ingestion and intelligence for an applicant's complete document package.
Scans files, invokes PDF extraction, triggers OCR fallback when scanned PDFs are detected,
classifies documents, extracts traceable entity fields, and detects missing mandatory documents.
"""

import os
from typing import Dict, List, Optional, Set

from app.document_processing.extractor import DocumentExtractor
from app.document_processing.ocr import OCRProcessor
from app.document_processing.pdf_reader import PDFReader
from app.schemas.applicant import (
    ClassifiedDocument,
    DocumentPackageResult,
    ExtractedField,
)
from app.utils.helpers import get_logger

logger = get_logger(__name__)

# Standard required document sets by employment category
SALARIED_REQUIRED_DOCS = [
    "loan_application",
    "identity_proof",
    "salary_slip",
    "bank_statement",
]

SELF_EMPLOYED_REQUIRED_DOCS = [
    "loan_application",
    "identity_proof",
    "income_statement",
    "bank_statement",
]


class DocumentPackageProcessor:
    """Processes all submitted documents for an applicant package."""

    def __init__(
        self,
        pdf_reader: Optional[PDFReader] = None,
        ocr_processor: Optional[OCRProcessor] = None,
        extractor: Optional[DocumentExtractor] = None,
    ) -> None:
        self.reader = pdf_reader or PDFReader()
        self.ocr = ocr_processor or OCRProcessor()
        self.extractor = extractor or DocumentExtractor()
        logger.info("DocumentPackageProcessor initialized.")

    def process_package(
        self, applicant_id: str, package_dir: str
    ) -> DocumentPackageResult:
        """Process all documents in an applicant directory into a structured result.

        Args:
            applicant_id: Applicant identifier (e.g. 'APP0001').
            package_dir: Filesystem directory containing submitted PDFs.

        Returns:
            DocumentPackageResult containing documents found, missing documents,
            extracted fields, OCR telemetry, and processing status.
        """
        logger.info(f"Processing document package for {applicant_id} in {package_dir}")

        if not os.path.isdir(package_dir):
            err = f"Document directory does not exist: {package_dir}"
            logger.error(err)
            return DocumentPackageResult(
                applicant_id=applicant_id,
                package_dir=package_dir,
                documents_found=[],
                documents_missing=SALARIED_REQUIRED_DOCS,
                expected_documents=SALARIED_REQUIRED_DOCS,
                is_complete=False,
                ocr_used=False,
                processing_status="failed",
                processing_errors=[err],
                all_extracted_fields={},
            )

        # 1. Discover all PDF files in the directory
        pdf_files = [
            f for f in sorted(os.listdir(package_dir)) if f.lower().endswith(".pdf")
        ]

        documents_found: List[ClassifiedDocument] = []
        found_types: Set[str] = set()
        ocr_triggered_for_package = False
        processing_errors: List[str] = []
        aggregated_fields: Dict[str, ExtractedField] = {}

        # 2. Ingest each document individually
        for filename in pdf_files:
            file_path = os.path.join(package_dir, filename)
            try:
                # Direct PyMuPDF text read
                info = self.reader.read_pdf(file_path)
                doc_text = info.full_text
                is_scanned = info.is_scanned

                # OCR fallback if scanned or low text
                if is_scanned:
                    logger.info(
                        f"Scanned/rasterized PDF detected: {file_path}. Triggering local OCR..."
                    )
                    ocr_pages = self.ocr.ocr_pdf(file_path)
                    doc_text = "\n".join(p.text for p in ocr_pages).strip()
                    ocr_triggered_for_package = True

                # Document classification
                doc_type, conf, ev = self.extractor.classify_document(
                    doc_text, filename
                )

                # Normalize identity_verification to identity_proof
                normalized_type = (
                    "identity_proof"
                    if doc_type in ("identity_proof", "identity_verification")
                    else doc_type
                )
                found_types.add(normalized_type)

                # Field extraction
                fields = self.extractor.extract_fields(
                    doc_text, normalized_type, filename, is_scanned
                )

                # Record classified document
                doc_id = f"DOC-{applicant_id}-{normalized_type.upper()}"
                classified = ClassifiedDocument(
                    document_id=doc_id,
                    file_path=file_path,
                    document_type=normalized_type,
                    classification_confidence=conf,
                    classification_evidence=ev,
                    is_scanned=is_scanned,
                    page_count=info.page_count,
                    raw_text=doc_text,
                    extracted_fields=fields,
                )
                documents_found.append(classified)

                # Aggregate fields into package-level dictionary
                for fn, ef in fields.items():
                    # Prefix with document type if duplicate across documents
                    agg_key = fn
                    if agg_key in aggregated_fields:
                        agg_key = f"{normalized_type}_{fn}"
                    aggregated_fields[agg_key] = ef

            except Exception as exc:
                err_msg = f"Failed to process document {filename}: {exc}"
                logger.error(err_msg)
                processing_errors.append(err_msg)

        # 3. Determine expected documents based on extracted employment type
        expected_docs = self._determine_expected_documents(documents_found, found_types)

        # 4. Check for missing documents
        missing_docs: List[str] = []
        for req in expected_docs:
            if req not in found_types:
                # Handle identity proof alias
                if req in ("identity_proof", "identity_verification"):
                    if (
                        "identity_proof" not in found_types
                        and "identity_verification" not in found_types
                    ):
                        missing_docs.append(req)
                else:
                    missing_docs.append(req)

        is_complete = len(missing_docs) == 0 and len(documents_found) > 0

        return DocumentPackageResult(
            applicant_id=applicant_id,
            package_dir=package_dir,
            documents_found=documents_found,
            documents_missing=missing_docs,
            expected_documents=expected_docs,
            is_complete=is_complete,
            ocr_used=ocr_triggered_for_package,
            processing_status=(
                "completed" if not processing_errors else "completed_with_errors"
            ),
            processing_errors=processing_errors,
            all_extracted_fields=aggregated_fields,
        )

    def _determine_expected_documents(
        self, docs: List[ClassifiedDocument], found_types: Set[str]
    ) -> List[str]:
        """Determine required document set based on employment type or present documents."""
        # Check loan application for declared employment type
        for d in docs:
            if d.document_type == "loan_application":
                emp_type_field = d.extracted_fields.get("employment_type")
                if emp_type_field and emp_type_field.value:
                    val = str(emp_type_field.value).lower()
                    if "self" in val or "business" in val:
                        return list(SELF_EMPLOYED_REQUIRED_DOCS)
                    return list(SALARIED_REQUIRED_DOCS)

        # If loan application missing or employment type unspecified:
        # Check if an income statement is present (indicative of self-employed)
        if "income_statement" in found_types:
            return list(SELF_EMPLOYED_REQUIRED_DOCS)

        # Default standard is salaried set
        return list(SALARIED_REQUIRED_DOCS)
