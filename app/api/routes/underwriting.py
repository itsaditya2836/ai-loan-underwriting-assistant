"""Underwriting pipeline execution and result retrieval API routes."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import require_permission, sanitize_applicant_id
from app.api.routes import documents as documents_route
from app.auth.models import Role, User
from app.auth.permissions import Permission
from app.database.applications import get_submitted_application
from app.database.audit import get_audit_run_by_id
from app.orchestration.orchestrator import UnderwritingOrchestrator
from app.schemas.applicant import Applicant
from app.utils.helpers import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post(
    "/{applicant_id}/run",
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
)
async def run_underwriting(
    applicant_id: str,
    user: User = Depends(require_permission(Permission.UNDERWRITING_INITIATE)),
) -> Dict[str, Any]:
    """Execute the full underwriting pipeline for a submitted or synthetic applicant."""
    safe_app_id = sanitize_applicant_id(applicant_id)
    orchestrator = UnderwritingOrchestrator()

    applicant_model: Optional[Applicant] = None
    submitted = get_submitted_application(safe_app_id)
    if submitted is not None:
        owner_id = submitted.get("submitted_by_user_id")
        if user.role == Role.LOAN_OFFICER and owner_id and owner_id != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to initiate underwriting for another officer's application.",
            )
        applicant_model = Applicant.model_validate(submitted)
    else:
        applicant_model = orchestrator.load_applicant(safe_app_id)

    if applicant_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Applicant '{safe_app_id}' not found.",
        )

    uploaded_dir = os.path.join(documents_route.DOCUMENTS_BASE_DIR, safe_app_id)
    package_dir = uploaded_dir if os.path.isdir(uploaded_dir) else None

    try:
        analysis, decision = orchestrator.execute_end_to_end(
            application_id=safe_app_id,
            package_dir=package_dir,
            persist_audit=True,
            applicant=applicant_model,
            initiated_by_user_id=user.user_id,
            initiated_by_username=user.username,
            initiated_by_role=user.role.value,
        )

        logger.info(
            "Underwriting pipeline executed for '%s' by user '%s' (role=%s, run_id=%s).",
            safe_app_id,
            user.username,
            user.role.value,
            analysis.audit_run_id,
        )

        return {
            "applicant_id": safe_app_id,
            "run_id": analysis.audit_run_id,
            "pipeline_status": analysis.orchestration_status.value,
            "recommendation": decision.recommendation.value,
            "confidence": decision.confidence,
            "risk_category": decision.risk_category,
            "risk_score": decision.risk_score,
            "eligibility_status": decision.eligibility_status,
            "human_review_required": decision.human_review_required,
            "summary": decision.summary,
            "initiated_by": user.user_id,
            "initiated_by_username": user.username,
            "initiated_by_role": user.role.value,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Underwriting pipeline failed for '%s': %s", safe_app_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal underwriting execution error.",
        )


def _get_authorized_run(run_id: str, user: User) -> Dict[str, Any]:
    """Retrieve a run by ID and enforce Loan Officer ownership boundaries."""
    run = get_audit_run_by_id(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Underwriting run '{run_id}' not found.",
        )
    owner_id = run.get("initiated_by_user_id")
    if user.role == Role.LOAN_OFFICER and owner_id and owner_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view another officer's underwriting run.",
        )
    return run


@router.get("/{run_id}", response_model=Dict[str, Any])
async def get_underwriting_result(
    run_id: str,
    user: User = Depends(require_permission(Permission.UNDERWRITING_VIEW_RESULTS)),
) -> Dict[str, Any]:
    """Retrieve a specific underwriting run result."""
    return _get_authorized_run(run_id, user)


@router.get("/{run_id}/status", response_model=Dict[str, Any])
async def get_underwriting_status(
    run_id: str,
    user: User = Depends(require_permission(Permission.UNDERWRITING_VIEW_RESULTS)),
) -> Dict[str, Any]:
    """Get the pipeline status of a specific underwriting run."""
    run = _get_authorized_run(run_id, user)
    return {
        "run_id": run["run_id"],
        "application_id": run["application_id"],
        "pipeline_status": run["pipeline_status"],
        "recommendation": run["recommendation"],
        "timestamp": run["timestamp"],
    }
