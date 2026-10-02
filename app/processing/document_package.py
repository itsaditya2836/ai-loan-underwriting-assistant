"""Processing module proxy for DocumentPackageProcessor."""

from app.document_processing.document_package import (
    SALARIED_REQUIRED_DOCS,
    SELF_EMPLOYED_REQUIRED_DOCS,
    DocumentPackageProcessor,
)

__all__ = [
    "DocumentPackageProcessor",
    "SALARIED_REQUIRED_DOCS",
    "SELF_EMPLOYED_REQUIRED_DOCS",
]
