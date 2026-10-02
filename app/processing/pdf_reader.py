"""Processing module proxy for PDFReader."""

from app.document_processing.pdf_reader import (
    PageContent,
    PDFDocumentInfo,
    PDFReader,
)

__all__ = ["PDFDocumentInfo", "PDFReader", "PageContent"]
