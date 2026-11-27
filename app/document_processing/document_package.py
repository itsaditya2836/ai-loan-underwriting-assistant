"""Document Package Processor module.

Coordinates end-to-end ingestion and intelligence for an applicant's complete
document folder: page-level PDF reading, selective OCR on scanned/mixed pages,
multi-signal classification, validated field extraction, duplicate detection,
conflict-preserving aggregation, and mandatory document completeness checks.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import replace
from typing import Any, Dict, List, Optional, Set, Tuple

from app.document_processing.extractor import DocumentExtractor
from app.document_processing.ocr import OCRProcessor
from app.document_processing.pdf_reader import PageContent, PDFDocumentInfo, PDFReader
from app.document_processing.security import mask_identifier
from app.document_processing.validation import (
    VALIDATION_AMBIGUOUS,
    VALIDATION_INVALID,
    VALIDATION_MISSING,
)
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


def _normalize_text_hash(text: str) -> str:
    """Compute a normalized text hash to detect logically duplicate documents."""
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _safe_field_repr(field_name: str, val: Any) -> Any:
    """Mask sensitive field values before recording conflict/validation telemetry."""
    if val is None:
        return None
    if field_name in {"account_number", "id_ref"}:
        return mask_identifier(str(val))
    return val


def _values_equivalent(val_a: Any, val_b: Any) -> bool:
    """Compare field values tolerating benign case and whitespace formatting differences."""
    if val_a == val_b:
        return True
    if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
        return abs(float(val_a) - float(val_b)) < 1e-6
    norm_a = re.sub(r"\s+", " ", str(val_a).strip()).lower()
    norm_b = re.sub(r"\s+", " ", str(val_b).strip()).lower()
    return norm_a == norm_b


class DocumentPackageProcessor:
    """Processes all submitted documents for an applicant package safely."""

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

    def _merge_ocr_on_info(
        self, info: PDFDocumentInfo, file_path: str
    ) -> Tuple[List[PageContent], str, int, int, int, int, bool]:
        """Run OCR selectively only on pages needing OCR and merge results."""
        merged_pages: List[PageContent] = [replace(p) for p in info.pages]
        ocr_needed_nums = [p.page_number for p in merged_pages if p.needs_ocr]

        ocr_used_here = False
        if ocr_needed_nums:
            logger.info(
                "Triggering selective OCR on page(s) %s for %s",
                ocr_needed_nums,
                os.path.basename(file_path),
            )
            ocr_results = self.ocr.ocr_pages(file_path, page_numbers=ocr_needed_nums)
            ocr_by_page = {res.page_number: res for res in ocr_results}
            ocr_used_here = True

            for idx, page in enumerate(merged_pages):
                if page.page_number in ocr_by_page:
                    res = ocr_by_page[page.page_number]
                    if res.success:
                        stripped = res.text.strip()
                        alnum = sum(1 for ch in stripped if ch.isalnum())
                        merged_pages[idx] = replace(
                            page,
                            text=res.text,
                            char_count=len(stripped),
                            alnum_char_count=alnum,
                            extraction_method="ocr",
                            needs_ocr=False,
                            is_blank=(alnum == 0),
                            error=None,
                        )
                    else:
                        merged_pages[idx] = replace(
                            page,
                            text="",
                            char_count=0,
                            alnum_char_count=0,
                            extraction_method="error",
                            needs_ocr=False,
                            is_blank=False,
                            error=res.error or "OCR failed on page",
                        )

        native_count = sum(
            1 for p in merged_pages if p.extraction_method == "native_text"
        )
        ocr_count = sum(1 for p in merged_pages if p.extraction_method == "ocr")
        empty_count = sum(1 for p in merged_pages if p.extraction_method == "empty")
        failed_count = sum(1 for p in merged_pages if p.extraction_method == "error")

        final_text = "\n".join(p.text for p in merged_pages if p.text).strip()
        return (
            merged_pages,
            final_text,
            native_count,
            ocr_count,
            empty_count,
            failed_count,
            ocr_used_here,
        )

    def process_package(
        self, applicant_id: str, package_dir: str
    ) -> DocumentPackageResult:
        """Process all documents in an applicant directory into a structured result."""
        logger.info("Processing document package for %s", applicant_id)

        if not os.path.isdir(package_dir):
            err = f"Document directory does not exist: {package_dir}"
            logger.error("%s", err)
            return DocumentPackageResult(
                applicant_id=applicant_id,
                package_dir=package_dir,
                documents_found=[],
                documents_missing=list(SALARIED_REQUIRED_DOCS),
                expected_documents=list(SALARIED_REQUIRED_DOCS),
                is_complete=False,
                ocr_used=False,
                processing_status="failed",
                processing_errors=[err],
                all_extracted_fields={},
            )

        dir_entries = sorted(os.listdir(package_dir))
        pdf_files: List[str] = []
        processing_errors: List[str] = []

        for entry in dir_entries:
            if entry.startswith("."):
                continue
            full_entry = os.path.join(package_dir, entry)
            if not os.path.isfile(full_entry):
                continue
            if entry.lower().endswith(".pdf"):
                pdf_files.append(entry)
            else:
                msg = f"Unsupported non-PDF file ignored: {entry}"
                logger.warning("%s", msg)
                processing_errors.append(msg)

        documents_found: List[ClassifiedDocument] = []
        found_types: Set[str] = set()
        type_counts: Dict[str, int] = {}
        seen_file_hashes: Dict[str, str] = {}
        seen_content_hashes: Dict[str, str] = {}

        ocr_triggered_for_package = False
        aggregated_fields: Dict[str, ExtractedField] = {}
        field_conflicts: Dict[str, List[Dict[str, Any]]] = {}
        unclassified_docs: List[str] = []
        duplicate_docs: List[Dict[str, Any]] = []
        missing_fields: Dict[str, List[str]] = {}
        invalid_fields: Dict[str, List[Dict[str, Any]]] = {}
        ambiguous_fields: Dict[str, List[Dict[str, Any]]] = {}
        security_warnings: List[str] = []

        total_pages = 0
        total_native_pages = 0
        total_ocr_pages = 0
        total_empty_pages = 0
        total_failed_pages = 0

        for filename in pdf_files:
            file_path = os.path.join(package_dir, filename)
            try:
                info = self.reader.read_pdf(file_path)
                if info.error and not info.pages:
                    raise RuntimeError(info.error)

                security_warnings.extend(info.security_warnings)

                # Exact binary duplicate detection before OCR and page-count aggregation
                if info.content_sha256 and info.content_sha256 in seen_file_hashes:
                    duplicate_docs.append(
                        {
                            "duplicate_file": filename,
                            "original_file": seen_file_hashes[info.content_sha256],
                            "reason": "exact_file_sha256_match",
                            "sha256": info.content_sha256,
                        }
                    )
                    logger.warning(
                        "Skipping exact binary duplicate file '%s' (matches '%s').",
                        filename,
                        seen_file_hashes[info.content_sha256],
                    )
                    continue
                if info.content_sha256:
                    seen_file_hashes[info.content_sha256] = filename

                (
                    merged_pages,
                    doc_text,
                    native_pages,
                    ocr_pages,
                    empty_pages,
                    failed_pages,
                    ocr_used_here,
                ) = self._merge_ocr_on_info(info, file_path)

                total_pages += info.page_count
                total_native_pages += native_pages
                total_ocr_pages += ocr_pages
                total_empty_pages += empty_pages
                total_failed_pages += failed_pages

                if ocr_used_here:
                    ocr_triggered_for_package = True

                for p in merged_pages:
                    if p.error:
                        processing_errors.append(
                            f"{filename} (Page {p.page_number}): {p.error}"
                        )

                # Unreadable or completely empty document cannot be classified or verified
                if not doc_text.strip():
                    err_msg = (
                        f"Document '{filename}' yielded no readable text "
                        f"(pages={info.page_count}, empty={empty_pages}, failed={failed_pages})."
                    )
                    logger.warning("%s", err_msg)
                    processing_errors.append(err_msg)
                    unclassified_docs.append(filename)
                    continue

                clf_res = self.extractor.classify_document_detailed(doc_text, filename)
                doc_type = clf_res.document_type
                normalized_type = (
                    "identity_proof"
                    if doc_type in ("identity_proof", "identity_verification")
                    else doc_type
                )

                # Logical content duplicate detection (identical normalized text & type)
                content_sig = f"{normalized_type}:{_normalize_text_hash(doc_text)}"
                if content_sig in seen_content_hashes:
                    duplicate_docs.append(
                        {
                            "duplicate_file": filename,
                            "original_file": seen_content_hashes[content_sig],
                            "document_type": normalized_type,
                            "reason": "duplicate_normalized_text_content",
                        }
                    )
                else:
                    seen_content_hashes[content_sig] = filename

                if normalized_type == "unknown":
                    unclassified_docs.append(filename)
                else:
                    found_types.add(normalized_type)

                doc_method = (
                    "hybrid"
                    if native_pages > 0 and ocr_pages > 0
                    else ("ocr" if ocr_pages > 0 else "digital")
                )

                fields, field_validations = (
                    self.extractor.extract_fields_with_diagnostics(
                        raw_text=doc_text,
                        document_type=normalized_type,
                        filename=filename,
                        is_scanned=(ocr_pages > 0),
                        pages=merged_pages,
                    )
                )

                # Record validation diagnostics per document
                doc_missing = [
                    k
                    for k, v in field_validations.items()
                    if v.get("validation_status") == VALIDATION_MISSING
                ]
                if doc_missing:
                    missing_fields[filename] = doc_missing

                doc_invalid = [
                    {
                        "field_name": v.get("field_name"),
                        "raw_value": _safe_field_repr(
                            str(v.get("field_name")), v.get("raw_value")
                        ),
                        "message": v.get("validation_message"),
                        "page_number": v.get("page_number"),
                    }
                    for v in field_validations.values()
                    if v.get("validation_status") == VALIDATION_INVALID
                ]
                if doc_invalid:
                    invalid_fields[filename] = doc_invalid

                doc_ambiguous = [
                    {
                        "field_name": v.get("field_name"),
                        "raw_value": v.get("raw_value"),
                        "message": v.get("validation_message"),
                        "page_number": v.get("page_number"),
                    }
                    for v in field_validations.values()
                    if v.get("validation_status") == VALIDATION_AMBIGUOUS
                ]
                if doc_ambiguous:
                    ambiguous_fields[filename] = doc_ambiguous

                type_counts[normalized_type] = type_counts.get(normalized_type, 0) + 1
                idx_suffix = (
                    f"-{type_counts[normalized_type]}"
                    if type_counts[normalized_type] > 1
                    else ""
                )
                doc_id = f"DOC-{applicant_id}-{normalized_type.upper()}{idx_suffix}"

                classified = ClassifiedDocument(
                    document_id=doc_id,
                    file_path=file_path,
                    document_type=normalized_type,
                    classification_confidence=clf_res.confidence,
                    classification_evidence=clf_res.evidence,
                    classification_status=clf_res.status,
                    classification_signals=clf_res.signals,
                    is_scanned=(ocr_pages > 0),
                    extraction_method=doc_method,
                    page_count=info.page_count,
                    native_text_pages=native_pages,
                    ocr_pages=ocr_pages,
                    empty_pages=empty_pages,
                    failed_pages=failed_pages,
                    raw_text=doc_text,
                    content_sha256=info.content_sha256,
                    extracted_fields=fields,
                    field_validations=field_validations,
                )
                documents_found.append(classified)

                # Conflict-preserving aggregation (never silently overwrite conflicting values)
                for fn, ef in fields.items():
                    if fn not in aggregated_fields:
                        aggregated_fields[fn] = ef
                    else:
                        existing_ef = aggregated_fields[fn]
                        if not _values_equivalent(existing_ef.value, ef.value):
                            conflict_key = fn
                            if conflict_key not in field_conflicts:
                                field_conflicts[conflict_key] = [
                                    {
                                        "source_document": existing_ef.source_document,
                                        "page_number": existing_ef.page_number,
                                        "value": _safe_field_repr(
                                            fn, existing_ef.value
                                        ),
                                    }
                                ]
                            field_conflicts[conflict_key].append(
                                {
                                    "source_document": ef.source_document,
                                    "page_number": ef.page_number,
                                    "value": _safe_field_repr(fn, ef.value),
                                }
                            )
                        agg_key = f"{normalized_type}{idx_suffix}_{fn}"
                        if agg_key in aggregated_fields:
                            agg_key = f"{normalized_type}_{len(documents_found)}_{fn}"
                        aggregated_fields[agg_key] = ef

            except Exception as exc:
                err_msg = f"Failed to process document {filename}: {exc}"
                logger.error("%s", err_msg)
                processing_errors.append(err_msg)

        expected_docs = self._determine_expected_documents(documents_found, found_types)
        missing_docs: List[str] = []
        for req in expected_docs:
            if req not in found_types:
                if req in ("identity_proof", "identity_verification"):
                    if (
                        "identity_proof" not in found_types
                        and "identity_verification" not in found_types
                    ):
                        missing_docs.append(req)
                else:
                    missing_docs.append(req)

        usable_doc_count = sum(
            1 for d in documents_found if d.document_type != "unknown"
        )
        is_complete = (
            len(missing_docs) == 0 and usable_doc_count > 0 and not processing_errors
        )

        if not documents_found and processing_errors:
            overall_status = "failed"
        elif processing_errors:
            overall_status = "completed_with_errors"
        elif not documents_found:
            overall_status = "failed"
        else:
            overall_status = "completed"

        return DocumentPackageResult(
            applicant_id=applicant_id,
            package_dir=package_dir,
            documents_found=documents_found,
            documents_missing=missing_docs,
            expected_documents=expected_docs,
            is_complete=is_complete,
            ocr_used=ocr_triggered_for_package,
            processing_status=overall_status,
            processing_errors=processing_errors,
            all_extracted_fields=aggregated_fields,
            total_pages=total_pages,
            native_text_pages=total_native_pages,
            ocr_pages=total_ocr_pages,
            empty_pages=total_empty_pages,
            failed_pages=total_failed_pages,
            unclassified_documents=unclassified_docs,
            duplicate_documents=duplicate_docs,
            field_conflicts=field_conflicts,
            missing_fields=missing_fields,
            invalid_fields=invalid_fields,
            ambiguous_fields=ambiguous_fields,
            security_warnings=security_warnings,
        )

    def _determine_expected_documents(
        self, docs: List[ClassifiedDocument], found_types: Set[str]
    ) -> List[str]:
        """Determine required document set based on employment type or present documents."""
        for d in docs:
            if d.document_type == "loan_application":
                emp_type_field = d.extracted_fields.get("employment_type")
                if emp_type_field and emp_type_field.value:
                    val = str(emp_type_field.value).lower()
                    if "self" in val or "business" in val:
                        return list(SELF_EMPLOYED_REQUIRED_DOCS)
                    return list(SALARIED_REQUIRED_DOCS)

        if "income_statement" in found_types:
            return list(SELF_EMPLOYED_REQUIRED_DOCS)

        return list(SALARIED_REQUIRED_DOCS)


__all__ = [
    "DocumentPackageProcessor",
    "SALARIED_REQUIRED_DOCS",
    "SELF_EMPLOYED_REQUIRED_DOCS",
]
