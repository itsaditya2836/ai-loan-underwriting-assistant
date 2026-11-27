"""Document processing package for reading, OCR, validation, and field extraction."""

from app.document_processing.document_package import DocumentPackageProcessor
from app.document_processing.extractor import ClassificationResult, DocumentExtractor
from app.document_processing.ocr import OCRConfig, OCRPageResult, OCRProcessor
from app.document_processing.pdf_reader import PDFDocumentInfo, PDFReader, PageContent
from app.document_processing.security import (
    DocumentProcessingError,
    OCRProcessingError,
    PDFCorruptedError,
    PDFEncryptedError,
    PDFSizeLimitError,
    PDFValidationError,
    mask_identifier,
    mask_sensitive_text,
)

__all__ = [
    "ClassificationResult",
    "DocumentExtractor",
    "DocumentPackageProcessor",
    "DocumentProcessingError",
    "OCRConfig",
    "OCRPageResult",
    "OCRProcessingError",
    "OCRProcessor",
    "PDFCorruptedError",
    "PDFDocumentInfo",
    "PDFEncryptedError",
    "PDFReader",
    "PDFSizeLimitError",
    "PDFValidationError",
    "PageContent",
    "mask_identifier",
    "mask_sensitive_text",
]
