"""Document upload and retrieval API routes with Stage 3 security validation."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.api.dependencies import require_permission, sanitize_applicant_id
from app.auth.models import Role, User
from app.auth.permissions import Permission
from app.database.applications import get_submitted_application
from app.document_processing.security import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    PDFProcessingError,
    validate_pdf_file,
)
from app.ui.services import sanitize_upload_filename
from app.utils.helpers import get_logger

logger = get_logger(__name__)

DOCUMENTS_BASE_DIR = os.path.join("data", "documents")
MAX_FILES_PER_UPLOAD = 10

router = APIRouter()


def _enforce_document_access(applicant_id: str, user: User) -> None:
    """Ensure a Loan Officer can only upload/view documents for permitted applicants."""
    if user.role != Role.LOAN_OFFICER:
        return
    submitted = get_submitted_application(applicant_id)
    if submitted:
        owner_id = submitted.get("submitted_by_user_id")
        if owner_id and owner_id != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access documents for another user's application.",
            )


@router.post(
    "/{applicant_id}/documents",
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
)
async def upload_documents(
    applicant_id: str,
    files: List[UploadFile] = File(...),
    user: User = Depends(require_permission(Permission.DOCUMENT_UPLOAD)),
) -> Dict[str, Any]:
    """Upload and validate PDF documents for an applicant."""
    safe_app_id = sanitize_applicant_id(applicant_id)
    _enforce_document_access(safe_app_id, user)

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one PDF file is required.",
        )
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {MAX_FILES_PER_UPLOAD} documents allowed per upload request.",
        )

    base_real = os.path.realpath(DOCUMENTS_BASE_DIR)
    doc_dir = os.path.realpath(os.path.join(base_real, safe_app_id))
    if os.path.commonpath([base_real, doc_dir]) != base_real:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid target document directory.",
        )
    os.makedirs(doc_dir, exist_ok=True)

    saved_files: List[Dict[str, Any]] = []
    errors: List[str] = []

    for upload_file in files:
        raw_name = upload_file.filename or "unknown.pdf"
        if ".." in raw_name or "/" in raw_name or "\\" in raw_name:
            errors.append(
                f"'{os.path.basename(raw_name)}': invalid filename characters."
            )
            continue

        safe_name = sanitize_upload_filename(raw_name)
        content = await upload_file.read()

        if len(content) <= 0:
            errors.append(f"'{safe_name}': empty file (0 bytes).")
            continue
        if len(content) > DEFAULT_MAX_FILE_SIZE_BYTES:
            errors.append(
                f"'{safe_name}': file exceeds maximum size "
                f"({len(content)} > {DEFAULT_MAX_FILE_SIZE_BYTES} bytes)."
            )
            continue

        dest_path = os.path.realpath(os.path.join(doc_dir, safe_name))
        if os.path.commonpath([doc_dir, dest_path]) != doc_dir:
            errors.append(f"'{safe_name}': unsafe destination path.")
            continue

        with open(dest_path, "wb") as f:
            f.write(content)

        try:
            file_size, sha256_hex, warnings = validate_pdf_file(dest_path)
        except PDFProcessingError as exc:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            errors.append(f"'{safe_name}': {exc}")
            continue

        saved_files.append(
            {
                "filename": safe_name,
                "size_bytes": file_size,
                "sha256": sha256_hex,
                "security_warnings": warnings,
                "path": dest_path,
            }
        )
        logger.info(
            "Document '%s' uploaded for applicant '%s' by user '%s'.",
            safe_name,
            safe_app_id,
            user.username,
        )

    if not saved_files and errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="; ".join(errors),
        )

    return {
        "applicant_id": safe_app_id,
        "uploaded": len(saved_files),
        "files": saved_files,
        "errors": errors,
    }


@router.get("/{applicant_id}/documents", response_model=List[Dict[str, Any]])
async def list_documents(
    applicant_id: str,
    user: User = Depends(require_permission(Permission.DOCUMENT_VIEW)),
) -> List[Dict[str, Any]]:
    """List documents available for an applicant."""
    safe_app_id = sanitize_applicant_id(applicant_id)
    _enforce_document_access(safe_app_id, user)

    base_real = os.path.realpath(DOCUMENTS_BASE_DIR)
    doc_dir = os.path.realpath(os.path.join(base_real, safe_app_id))
    if os.path.commonpath([base_real, doc_dir]) != base_real or not os.path.exists(
        doc_dir
    ):
        return []

    documents: List[Dict[str, Any]] = []
    for filename in sorted(os.listdir(doc_dir)):
        filepath = os.path.join(doc_dir, filename)
        if os.path.isfile(filepath) and filename.lower().endswith(".pdf"):
            documents.append(
                {
                    "filename": filename,
                    "size_bytes": os.path.getsize(filepath),
                    "applicant_id": safe_app_id,
                }
            )
    return documents
