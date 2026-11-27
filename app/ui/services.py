"""Backend-Connected Service Layer for the Stage 5 Streamlit Application.

Handles:
- Authoritative Applicant validation (Pydantic + Stage 4 consistency checks)
- PDF upload validation matching Stage 3 security safeguards (signature, size, markers, SHA-256 dedupe)
- Ephemeral temporary staging cleanup (no unsafe permanent upload storage)
- Duplicate submission fingerprinting
- Stage 4 pipeline orchestration & safe audit persistence
- Merged SQLite + read-only synthetic catalog lookups and honest dashboard metrics
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple

from pydantic import ValidationError

from app.agents.decision_agent import DecisionReasoningAgent
from app.agents.document_agent import DocumentIntakeAgent
from app.database.applications import (
    count_submitted_applications,
    find_duplicate_submission,
    get_submitted_application,
    init_applications_table,
    list_submitted_applications,
    save_submitted_application,
)
from app.database.audit import (
    get_audit_analytics_summary,
    get_audit_daily_trends,
    get_audit_runs,
    get_latest_runs_per_application,
    init_audit_table,
    save_underwriting_run_safe,
)
from app.document_processing.document_package import (
    SALARIED_REQUIRED_DOCS,
    SELF_EMPLOYED_REQUIRED_DOCS,
)
from app.document_processing.extractor import _FILENAME_TYPE_HINTS
from app.document_processing.security import (
    _ACTIVE_CONTENT_MARKERS,
    ALLOWED_PDF_EXTENSIONS,
    DEFAULT_MAX_FILE_SIZE_BYTES,
    mask_identifier,
    mask_sensitive_text,
)
from app.orchestration.consistency import validate_applicant_data
from app.orchestration.orchestrator import UnderwritingOrchestrator
from app.schemas.applicant import Applicant, DocumentPackageResult
from app.schemas.decision import DecisionOutcome, DecisionReasoningResult
from app.schemas.underwriting import OrchestrationStatus, UnderwritingAnalysisResult
from app.utils.helpers import get_logger

logger = get_logger(__name__)

APPLICANTS_DATA_PATH = os.path.join("data", "synthetic_data", "applicants.json")
DOCUMENTS_BASE_DIR = os.path.join("data", "documents")

CANONICAL_DOCUMENT_CATEGORIES: Tuple[str, ...] = (
    "auto",
    "loan_application",
    "identity_proof",
    "address_proof",
    "salary_slip",
    "bank_statement",
    "income_statement",
    "employment_proof",
)

DECISION_DISPLAY_MAP: Dict[str, str] = {
    DecisionOutcome.APPROVE.value: "APPROVED",
    DecisionOutcome.REJECT.value: "REJECTED",
    DecisionOutcome.MANUAL_REVIEW.value: "MANUAL_REVIEW",
}

EMPLOYMENT_TYPE_OPTIONS: Tuple[str, ...] = (
    "Salaried",
    "Self-Employed",
    "Business Owner",
    "Other",
)


def format_decision_label(rec: Optional[str]) -> str:
    """Format DecisionOutcome enum string cleanly with standard display mapping."""
    if not rec:
        return "UNAVAILABLE"
    up = str(rec).upper()
    if up in DECISION_DISPLAY_MAP:
        mapped = DECISION_DISPLAY_MAP[up]
        return f"{mapped} ({up})" if mapped != up else mapped
    return up


def load_synthetic_applicants_raw() -> List[Dict[str, Any]]:
    """Read synthetic applicants cleanly without mutating disk data."""
    if not os.path.exists(APPLICANTS_DATA_PATH):
        return []
    try:
        with open(APPLICANTS_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            for rec in data:
                rec.setdefault("source", "synthetic")
            return data
    except Exception as exc:
        logger.error("Failed loading synthetic applicants: %s", exc)
    return []


def has_physical_document_package(applicant_id: str) -> bool:
    """Return True when synthetic on-disk PDF directory exists with files."""
    folder = os.path.join(DOCUMENTS_BASE_DIR, applicant_id)
    return os.path.isdir(folder) and any(
        not f.startswith(".") and f.lower().endswith(".pdf") for f in os.listdir(folder)
    )


def load_applicant_catalog() -> List[Dict[str, Any]]:
    """Merge persisted user-submitted applications (newest first) with synthetic catalog."""
    init_applications_table()
    submitted = list_submitted_applications(limit=500)
    synthetic = load_synthetic_applicants_raw()

    merged: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for rec in submitted:
        aid = rec["applicant_id"]
        if aid not in seen_ids:
            seen_ids.add(aid)
            rec_copy = dict(rec)
            rec_copy["has_documents"] = bool(
                rec.get("uploaded_files")
            ) or has_physical_document_package(aid)
            merged.append(rec_copy)

    for rec in synthetic:
        aid = rec.get("applicant_id")
        if aid and aid not in seen_ids:
            seen_ids.add(aid)
            rec_copy = dict(rec)
            rec_copy["source"] = "synthetic"
            rec_copy["has_documents"] = has_physical_document_package(aid)
            merged.append(rec_copy)

    return merged


def get_applicant_record(applicant_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Look up an applicant dictionary first in SQLite submissions, then synthetic JSON."""
    if not applicant_id:
        return None
    sub = get_submitted_application(applicant_id)
    if sub:
        sub["has_documents"] = bool(
            sub.get("uploaded_files")
        ) or has_physical_document_package(applicant_id)
        return sub
    for rec in load_synthetic_applicants_raw():
        if rec.get("applicant_id") == applicant_id:
            out = dict(rec)
            out["source"] = "synthetic"
            out["has_documents"] = has_physical_document_package(applicant_id)
            return out
    return None


def generate_applicant_reference() -> str:
    """Generate a unique non-colliding applicant identifier."""
    existing_ids = {
        rec.get("applicant_id")
        for rec in load_applicant_catalog()
        if rec.get("applicant_id")
    }
    date_slug = datetime.now(timezone.utc).strftime("%Y%m%d")
    for _ in range(25):
        candidate = f"APP-{date_slug}-{uuid.uuid4().hex[:4].upper()}"
        if candidate not in existing_ids:
            return candidate
    return f"APP-{uuid.uuid4().hex[:8].upper()}"


def validate_applicant_form_input(
    raw_data: Dict[str, Any],
) -> Tuple[Optional[Applicant], List[str], List[str]]:
    """Validate applicant form payload strictly via Applicant Pydantic schema & Stage 4 validators.

    Preserves valid zero values cleanly (never treats 0 or 0.0 as missing).
    Returns (Applicant | None, blocking_errors, non_blocking_warnings).
    """
    errors: List[str] = []
    warnings: List[str] = []

    applicant_id = str(raw_data.get("applicant_id") or "").strip()
    name = str(raw_data.get("name") or "").strip()
    employment_type = str(raw_data.get("employment_type") or "").strip()

    if not applicant_id:
        errors.append("Applicant ID is required.")
    elif not re.fullmatch(r"[A-Za-z0-9_-]{3,40}", applicant_id):
        errors.append(
            "Applicant ID must be 3–40 alphanumeric, hyphen, or underscore characters."
        )

    if not name:
        errors.append("Full name is required.")

    if not employment_type:
        errors.append("Employment type is required.")

    # Optional fields: preserve explicit 0 / 0.0 while keeping None when blank/unset
    monthly_expenses_val = raw_data.get("monthly_expenses")
    if monthly_expenses_val == "" or monthly_expenses_val is None:
        monthly_expenses_clean = None
    else:
        monthly_expenses_clean = monthly_expenses_val

    dependents_val = raw_data.get("number_of_dependents")
    if dependents_val == "" or dependents_val is None:
        dependents_clean = None
    else:
        dependents_clean = dependents_val

    candidate_payload = {
        "applicant_id": applicant_id,
        "name": name,
        "age": raw_data.get("age"),
        "employment_type": employment_type,
        "employment_years": raw_data.get("employment_years"),
        "monthly_income": raw_data.get("monthly_income"),
        "existing_emi": raw_data.get("existing_emi", 0.0),
        "loan_amount": raw_data.get("loan_amount"),
        "loan_tenure": raw_data.get("loan_tenure"),
        "credit_score": raw_data.get("credit_score"),
        "bank_balance": raw_data.get("bank_balance", 0.0),
        "monthly_expenses": monthly_expenses_clean,
        "number_of_dependents": dependents_clean,
    }

    # Collect both format/bound Pydantic errors and custom checks simultaneously
    has_non_finite = False
    for fld in (
        "employment_years",
        "monthly_income",
        "existing_emi",
        "loan_amount",
        "bank_balance",
        "monthly_expenses",
    ):
        val = candidate_payload.get(fld)
        if isinstance(val, float) and not math.isfinite(val):
            has_non_finite = True
            errors.append(f"Field '{fld}' must be a finite numeric value.")

    if has_non_finite:
        return None, errors, warnings

    try:
        applicant = Applicant.model_validate(candidate_payload)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", [])) or "input"
            msg = f"{loc}: {err.get('msg')}"
            if msg not in errors:
                errors.append(msg)
        return None, errors, warnings

    if errors:
        return None, errors, warnings

    try:
        warnings = validate_applicant_data(applicant)
    except ValueError as exc:
        errors.append(str(exc))
        return None, errors, warnings

    return applicant, errors, warnings


def sanitize_upload_filename(filename: str) -> str:
    """Return a path-traversal-safe PDF filename."""
    base = os.path.basename(str(filename or "").strip()) or "upload.pdf"
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return cleaned or "upload.pdf"


def infer_document_category_hint(filename: str) -> str:
    """Infer canonical document category from upload filename when unambiguous."""
    lower = sanitize_upload_filename(filename).lower()
    for token, canonical in _FILENAME_TYPE_HINTS.items():
        if token in lower:
            return canonical
    return "auto"


def validate_uploaded_pdf(
    filename: str,
    file_bytes: bytes,
    existing_hashes: Optional[set[str]] = None,
    declared_category: str = "auto",
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
) -> Dict[str, Any]:
    """Validate uploaded bytes against Stage 3 PDF security rules before staging."""
    safe_name = sanitize_upload_filename(filename)
    _, ext = os.path.splitext(safe_name)
    size_bytes = len(file_bytes) if file_bytes is not None else 0
    sha256 = hashlib.sha256(file_bytes or b"").hexdigest()
    category = (
        declared_category
        if declared_category in CANONICAL_DOCUMENT_CATEGORIES
        else "auto"
    )
    suggested_cat = (
        category if category != "auto" else infer_document_category_hint(safe_name)
    )

    if ext.lower() not in ALLOWED_PDF_EXTENSIONS:
        return {
            "file_id": f"{safe_name}:{sha256[:12]}",
            "original_filename": filename,
            "safe_filename": safe_name,
            "category": category,
            "detected_hint": suggested_cat,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "status": "INVALID",
            "validation_error": (
                f"Unsupported file type '{ext or '(none)'}'. Only .pdf documents are accepted."
            ),
            "security_warnings": [],
            "content_bytes": b"",
        }

    if size_bytes <= 0:
        return {
            "file_id": f"{safe_name}:{sha256[:12]}",
            "original_filename": filename,
            "safe_filename": safe_name,
            "category": category,
            "detected_hint": suggested_cat,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "status": "INVALID",
            "validation_error": f"Empty PDF file (0 bytes): {safe_name}",
            "security_warnings": [],
            "content_bytes": b"",
        }

    if max_file_size_bytes > 0 and size_bytes > max_file_size_bytes:
        limit_mb = max_file_size_bytes / (1024 * 1024)
        return {
            "file_id": f"{safe_name}:{sha256[:12]}",
            "original_filename": filename,
            "safe_filename": safe_name,
            "category": category,
            "detected_hint": suggested_cat,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "status": "INVALID",
            "validation_error": (
                f"File size ({size_bytes / (1024 * 1024):.2f} MB) exceeds maximum limit ({limit_mb:.0f} MB)."
            ),
            "security_warnings": [],
            "content_bytes": b"",
        }

    if b"%PDF-" not in file_bytes[:1024]:
        return {
            "file_id": f"{safe_name}:{sha256[:12]}",
            "original_filename": filename,
            "safe_filename": safe_name,
            "category": category,
            "detected_hint": suggested_cat,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "status": "INVALID",
            "validation_error": "Invalid PDF signature (missing %PDF- header).",
            "security_warnings": [],
            "content_bytes": b"",
        }

    if existing_hashes and sha256 in existing_hashes:
        return {
            "file_id": f"{safe_name}:{sha256[:12]}",
            "original_filename": filename,
            "safe_filename": safe_name,
            "category": category,
            "detected_hint": suggested_cat,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "status": "DUPLICATE",
            "validation_error": "Identical file content (SHA-256) already staged; skipped duplicate.",
            "security_warnings": [],
            "content_bytes": b"",
        }

    security_warnings: List[str] = []
    for marker, msg in _ACTIVE_CONTENT_MARKERS:
        if re.search(re.escape(marker) + rb"(?![A-Za-z])", file_bytes):
            security_warnings.append(f"{safe_name}: {msg} (ignored passively)")

    return {
        "file_id": f"{safe_name}:{sha256[:12]}",
        "original_filename": filename,
        "safe_filename": safe_name,
        "category": category,
        "detected_hint": suggested_cat,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "status": "VALID",
        "validation_error": None,
        "security_warnings": security_warnings,
        "content_bytes": file_bytes,
    }


@contextmanager
def temporary_upload_directory(
    staged_uploads: List[Dict[str, Any]],
) -> Generator[str, None, None]:
    """Write validated PDF bytes to an ephemeral directory cleaned on exit."""
    with tempfile.TemporaryDirectory(prefix="loan_underwriting_upload_") as tmp_dir:
        used_names: set[str] = set()
        for idx, item in enumerate(staged_uploads):
            if item.get("status") != "VALID" or not item.get("content_bytes"):
                continue
            safe_name = sanitize_upload_filename(item.get("safe_filename", "doc.pdf"))
            category = item.get("category", "auto")
            if category != "auto" and category not in safe_name.lower():
                target_name = f"{category}_{safe_name}"
            else:
                target_name = safe_name

            if target_name in used_names:
                stem, ext = os.path.splitext(target_name)
                target_name = f"{stem}_{idx + 1}{ext}"
            used_names.add(target_name)

            dest_path = os.path.join(tmp_dir, target_name)
            with open(dest_path, "wb") as f:
                f.write(item["content_bytes"])
        yield tmp_dir


def expected_documents_for_employment(employment_type: str) -> List[str]:
    """Return mandatory Stage 3 document categories for the given employment category."""
    emp = str(employment_type or "").lower()
    if "self" in emp or "business" in emp:
        return list(SELF_EMPLOYED_REQUIRED_DOCS)
    return list(SALARIED_REQUIRED_DOCS)


def preview_uploaded_documents(
    applicant_id: str,
    staged_uploads: List[Dict[str, Any]],
) -> DocumentPackageResult:
    """Process staged valid PDFs once using Stage 3 DocumentIntakeAgent and clean temp storage."""
    valid_items = [u for u in staged_uploads if u.get("status") == "VALID"]
    agent = DocumentIntakeAgent()
    with temporary_upload_directory(valid_items) as tmp_dir:
        return agent.process_package(applicant_id=applicant_id, package_dir=tmp_dir)


def compute_submission_fingerprint(
    applicant: Applicant,
    staged_uploads: List[Dict[str, Any]],
) -> str:
    """Build deterministic SHA-256 fingerprint of applicant payload + valid uploaded files."""
    file_sigs = sorted(
        f"{u.get('safe_filename')}:{u.get('category')}:{u.get('sha256')}"
        for u in staged_uploads
        if u.get("status") == "VALID"
    )
    payload = {
        "applicant": applicant.model_dump(),
        "files": file_sigs,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def upload_signature_key(staged_uploads: List[Dict[str, Any]]) -> str:
    """Return compact cache signature for upload list so unchanged files aren't re-OCR'd."""
    parts = [
        f"{u.get('sha256')}:{u.get('category')}:{u.get('status')}"
        for u in staged_uploads
    ]
    return hashlib.sha256("|".join(sorted(parts)).encode("utf-8")).hexdigest()


def mask_extracted_value(
    field_name: str, value: Any, explicit_masked: Optional[str] = None
) -> str:
    """Mask sensitive personal or banking values consistently across Document Review."""
    if explicit_masked:
        return str(explicit_masked)
    if value is None:
        return "N/A"
    s = str(value)
    if str(field_name).lower() in {
        "id_ref",
        "account_number",
        "pan",
        "aadhaar",
        "aadhar",
        "ssn",
        "phone",
        "mobile",
    }:
        return mask_identifier(s)
    return mask_sensitive_text(s)


def submit_application_and_underwrite(
    applicant: Applicant,
    staged_uploads: Optional[List[Dict[str, Any]]] = None,
    use_existing_package_if_empty: bool = False,
    allow_duplicate: bool = False,
) -> Dict[str, Any]:
    """Run full validated Stage 4 underwriting workflow & persist application/audit safely.

    Never duplicates pipeline rules in the UI; delegates strictly to
    UnderwritingOrchestrator and DecisionReasoningAgent and always cleans temporary uploads.
    """
    init_applications_table()
    init_audit_table()

    uploads = list(staged_uploads or [])
    valid_uploads = [u for u in uploads if u.get("status") == "VALID"]
    invalid_uploads = [u for u in uploads if u.get("status") == "INVALID"]
    if invalid_uploads:
        invalid_names = ", ".join(
            u.get("original_filename", "file") for u in invalid_uploads
        )
        raise ValueError(
            f"Remove invalid uploaded file(s) before submission: {invalid_names}"
        )

    submission_hash = compute_submission_fingerprint(applicant, valid_uploads)
    if not allow_duplicate:
        existing_dup = find_duplicate_submission(submission_hash)
        if existing_dup is not None:
            return {
                "duplicate_blocked": True,
                "existing_application": existing_dup,
                "submission_hash": submission_hash,
                "audit_run_id": existing_dup.get("latest_run_id"),
                "audit_persisted": False,
                "audit_error": None,
            }

    val_warnings = validate_applicant_data(applicant)
    upload_meta = [
        {
            "filename": u.get("safe_filename"),
            "category": u.get("category"),
            "size_bytes": u.get("size_bytes"),
            "sha256": u.get("sha256"),
        }
        for u in valid_uploads
    ]

    orchestrator = UnderwritingOrchestrator()
    decision_agent = DecisionReasoningAgent()
    start_perf = time.perf_counter()

    analysis: Optional[UnderwritingAnalysisResult] = None
    decision: Optional[DecisionReasoningResult] = None

    if valid_uploads:
        with temporary_upload_directory(valid_uploads) as tmp_dir:
            analysis = orchestrator.run_pipeline(applicant, package_dir=tmp_dir)
    elif use_existing_package_if_empty and has_physical_document_package(
        applicant.applicant_id
    ):
        analysis = orchestrator.run_pipeline(
            applicant,
            package_dir=os.path.join(DOCUMENTS_BASE_DIR, applicant.applicant_id),
        )
    else:
        with tempfile.TemporaryDirectory(
            prefix="loan_underwriting_empty_"
        ) as empty_dir:
            analysis = orchestrator.run_pipeline(applicant, package_dir=empty_dir)

    decision = decision_agent.evaluate(analysis)
    duration_ms = round((time.perf_counter() - start_perf) * 1000.0, 2)

    run_id, db_err = save_underwriting_run_safe(
        analysis=analysis,
        decision=decision,
        execution_time_ms=duration_ms,
    )
    analysis.audit_run_id = run_id
    analysis.audit_persisted = run_id is not None and db_err is None
    analysis.audit_persistence_error = db_err

    if analysis.orchestration_status == OrchestrationStatus.FAILED:
        app_status = "FAILED"
    elif (
        analysis.orchestration_status == OrchestrationStatus.PARTIAL_SUCCESS
        or (analysis.document_result and not analysis.document_result.is_complete)
        or analysis.document_result is None
    ):
        app_status = "INCOMPLETE"
    else:
        app_status = "UNDERWRITTEN"

    app_persist_error: Optional[str] = None
    saved_app_record: Optional[Dict[str, Any]] = None
    try:
        saved_app_record = save_submitted_application(
            applicant=applicant,
            uploaded_files_meta=upload_meta,
            submission_hash=submission_hash,
            application_status=app_status,
            latest_run_id=run_id,
            validation_warnings=val_warnings,
        )
    except Exception as exc:
        app_persist_error = f"Application record persistence failed: {exc}"
        logger.error(
            "Failed to persist application '%s': %s", applicant.applicant_id, exc
        )

    return {
        "duplicate_blocked": False,
        "submission_hash": submission_hash,
        "applicant": applicant,
        "application_record": saved_app_record,
        "analysis": analysis,
        "decision": decision,
        "run_id": run_id,
        "audit_run_id": run_id,
        "audit_persisted": analysis.audit_persisted,
        "audit_error": db_err or app_persist_error,
        "duration_ms": duration_ms,
        "source": "submitted",
    }


def compute_dashboard_metrics() -> Dict[str, Any]:
    """Compute honest portfolio KPIs separating unique applications from underwriting runs."""
    init_applications_table()
    init_audit_table()

    audit_summary = get_audit_analytics_summary()
    submitted_apps = list_submitted_applications(limit=1000)
    latest_completed_runs = get_latest_runs_per_application(
        exclude_failed=True, limit=1000
    )
    latest_all_runs = get_latest_runs_per_application(exclude_failed=False, limit=1000)
    recent_runs = get_audit_runs(limit=15)
    trends = get_audit_daily_trends()

    completed_decisions = {"APPROVE": 0, "REJECT": 0, "MANUAL_REVIEW": 0}
    risk_dist_completed = {
        "LOW": 0,
        "MEDIUM": 0,
        "HIGH": 0,
        "BORDERLINE": 0,
        "UNAVAILABLE": 0,
    }
    for r in latest_completed_runs:
        rec = r.get("recommendation")
        if rec in completed_decisions:
            completed_decisions[rec] += 1
        rc = r.get("risk_category") or "UNAVAILABLE"
        risk_dist_completed[rc] = risk_dist_completed.get(rc, 0) + 1

    pending_ids = {
        a["applicant_id"]
        for a in submitted_apps
        if a.get("application_status")
        in {"SUBMITTED", "INCOMPLETE", "DRAFT", "PARTIAL"}
    }
    incomplete_eval_ids = {
        r["application_id"]
        for r in latest_completed_runs
        if int(r.get("documents_missing_count", 0)) > 0
        or r.get("pipeline_status") == "PARTIAL_SUCCESS"
    }

    failed_apps_count = sum(
        1 for r in latest_all_runs if r.get("pipeline_status") == "FAILED"
    )

    return {
        "submitted_applications_count": count_submitted_applications(),
        "evaluated_completed_applications": len(latest_completed_runs),
        "approved_applications": completed_decisions["APPROVE"],
        "rejected_applications": completed_decisions["REJECT"],
        "manual_review_applications": completed_decisions["MANUAL_REVIEW"],
        "incomplete_or_pending_applications": len(pending_ids | incomplete_eval_ids),
        "failed_latest_applications": failed_apps_count,
        "audit_summary": audit_summary,
        "completed_decision_distribution": completed_decisions,
        "completed_risk_distribution": {
            k: v
            for k, v in risk_dist_completed.items()
            if v > 0 or k in ("LOW", "MEDIUM", "HIGH", "BORDERLINE")
        },
        "recent_runs": recent_runs,
        "daily_trends": trends,
    }
