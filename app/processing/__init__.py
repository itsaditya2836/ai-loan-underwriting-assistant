"""Document processing package alias."""

from app.document_processing.document_package import DocumentPackageProcessor
from app.document_processing.extractor import DocumentExtractor
from app.document_processing.ocr import OCRProcessor
from app.document_processing.pdf_reader import PDFReader

__all__ = [
    "DocumentExtractor",
    "DocumentPackageProcessor",
    "OCRProcessor",
    "PDFReader",
]
