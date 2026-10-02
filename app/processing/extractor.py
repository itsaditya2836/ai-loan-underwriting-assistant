"""Processing module proxy for DocumentExtractor."""

from app.document_processing.extractor import (
    DocumentExtractor,
    clean_label_value,
    find_label_value,
    parse_currency,
)

__all__ = [
    "DocumentExtractor",
    "clean_label_value",
    "find_label_value",
    "parse_currency",
]
