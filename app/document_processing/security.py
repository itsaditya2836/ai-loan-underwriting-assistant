"""Security, Validation, and PII Masking Safeguards for Document Processing.

Provides:
- Controlled document-processing exception hierarchy
- File extension, PDF signature (%PDF-), and file-size validation
- Non-executing PDF active-content detection (/JS, /JavaScript, /OpenAction, /Launch, /AA)
- Sensitive identifier masking for diagnostic logs and summaries
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import List, Optional, Tuple

DEFAULT_MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB safeguard
DEFAULT_MAX_PAGES = 100
ALLOWED_PDF_EXTENSIONS = {".pdf"}

# Markers for potentially active/executable PDF structures (inspected passively, never executed).
_ACTIVE_CONTENT_MARKERS: Tuple[Tuple[bytes, str], ...] = (
    (b"/JavaScript", "Embedded /JavaScript dictionary entry detected"),
    (b"/JS", "Embedded /JS action entry detected"),
    (b"/OpenAction", "Automatic /OpenAction trigger detected"),
    (b"/Launch", "External /Launch action entry detected"),
    (b"/AA", "Additional-Actions (/AA) entry detected"),
)


class DocumentProcessingError(Exception):
    """Base controlled exception for Stage 3 document processing failures."""


class PDFProcessingError(DocumentProcessingError):
    """Base controlled exception for PDF parsing and reading errors."""


class PDFValidationError(PDFProcessingError):
    """Raised when a file fails extension, existence, or PDF header validation."""


class PDFEncryptedError(PDFValidationError):
    """Raised when a PDF is password-protected or encrypted and cannot be read."""


class PDFCorruptedError(PDFValidationError):
    """Raised when a PDF structure is corrupted, truncated, or contains zero pages."""


class PDFSizeLimitError(PDFValidationError):
    """Raised when a PDF exceeds configured file size or page count limits."""


class OCRProcessingError(DocumentProcessingError):
    """Raised when local OCR execution fails unrecoverably."""


def mask_identifier(value: Optional[str], visible_suffix: int = 4) -> str:
    """Mask an identifier or account string while preserving trailing verification chars."""
    if not value:
        return ""
    s = str(value).strip()
    if len(s) <= visible_suffix:
        return "*" * len(s)
    # Preserve non-sensitive synthetic prefix up to second hyphen if present, mask remainder
    return f"{'*' * (len(s) - visible_suffix)}{s[-visible_suffix:]}"


def mask_sensitive_text(text: str) -> str:
    """Mask synthetic or standard account numbers, ID refs, and long digit runs in logs."""
    if not text:
        return ""
    masked = re.sub(
        r"\b(SYN-(?:ACC|ID)-[A-Za-z0-9-]+?-)([A-Za-z0-9]{2,8})\b",
        lambda m: f"***{m.group(2)[-4:]}",
        text,
        flags=re.IGNORECASE,
    )
    masked = re.sub(
        r"\b([A-Z]{5}\d{4}[A-Z])\b",
        lambda m: f"******{m.group(1)[-4:]}",
        masked,
    )
    masked = re.sub(
        r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
        lambda m: f"********{m.group(0).replace('-', '').replace(' ', '')[-4:]}",
        masked,
    )
    masked = re.sub(
        r"\b\d{9,18}\b",
        lambda m: f"{'*' * (len(m.group(0)) - 4)}{m.group(0)[-4:]}",
        masked,
    )
    return masked


def compute_bytes_sha256(file_path: str) -> str:
    """Compute SHA-256 hex digest of a file using fixed-size chunk reads."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def validate_pdf_file(
    file_path: str,
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
) -> Tuple[int, str, List[str]]:
    """Validate path, extension, size limit, %PDF- header, and active-content markers.

    Returns:
        Tuple of (file_size_bytes, sha256_hex, security_warnings).

    Raises:
        FileNotFoundError: If file_path does not exist on disk.
        PDFValidationError: If extension, type, or PDF signature is invalid.
        PDFSizeLimitError: If file size exceeds max_file_size_bytes.
        PDFCorruptedError: If file is empty (0 bytes).
    """
    if not file_path or not isinstance(file_path, str):
        raise PDFValidationError("Invalid PDF file path.")

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"PDF file not found: {file_path}")

    if not os.path.isfile(file_path):
        raise PDFValidationError(f"Path is not a regular file: {file_path}")

    _, ext = os.path.splitext(file_path)
    if ext.lower() not in ALLOWED_PDF_EXTENSIONS:
        raise PDFValidationError(
            f"Unsupported file extension '{ext or '(none)'}' for PDF reader; expected .pdf"
        )

    file_size = os.path.getsize(file_path)
    if file_size <= 0:
        raise PDFCorruptedError(f"Empty PDF file (0 bytes): {file_path}")

    if max_file_size_bytes > 0 and file_size > max_file_size_bytes:
        raise PDFSizeLimitError(
            f"PDF size ({file_size} bytes) exceeds maximum allowed "
            f"({max_file_size_bytes} bytes): {file_path}"
        )

    # Check %PDF- magic signature within first 1024 bytes per PDF specification
    with open(file_path, "rb") as f:
        header = f.read(1024)
    if b"%PDF-" not in header:
        raise PDFValidationError(
            f"Invalid PDF signature (missing %PDF- header): {file_path}"
        )

    # Passive scan for active/scripted PDF actions; never executed
    hasher = hashlib.sha256()
    found_warnings: List[str] = []
    seen_labels: set[str] = set()
    tail = b""
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
            window = tail + chunk
            for marker, message in _ACTIVE_CONTENT_MARKERS:
                if message not in seen_labels and re.search(
                    re.escape(marker) + rb"(?![A-Za-z])", window
                ):
                    seen_labels.add(message)
                    found_warnings.append(
                        f"{os.path.basename(file_path)}: {message} (ignored passively)"
                    )
            tail = chunk[-32:]

    return file_size, hasher.hexdigest(), found_warnings
