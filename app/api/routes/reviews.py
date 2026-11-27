"""Human review queue and decision submission API routes.

Integrates with existing app.review.service and enforces:
- Authenticated reviewer identity (derived from token, never client-supplied).
- RBAC permission checks for review operations.
- Maker-Checker: supervisor-only corrections, no self-review of submitted apps or runs.
- Optimistic concurrency via expected_previous_status + atomic DB transaction lock.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import require_any_permission
from app.auth.models import User
from app.auth.permissions import (
    MakerCheckerError,
    Permission,
    check_permission,
    enforce_correction_requires_supervisor,
    enforce_not_self_review,
)
from app.database.applications import get_submitted_application
from app.database.audit import get_audit_run_by_id
from app.database.reviews import get_review_history_for_run
from app.review.service import (
    compute_review_queue_metrics,
    get_case_review_summary,
    list_review_queue,
    submit_human_review_safe,
)
from app.schemas.review import HumanReviewAction, ReviewStatus
from app.utils.helpers import get_logger

logger = get_logger(__name__)

router = APIRouter()

_ACTION_PERMISSION_MAP: Dict[HumanReviewAction, Permission] = {
    HumanReviewAction.START_REVIEW: Permission.REVIEW_SUBMIT_DECISION,
    HumanReviewAction.APPROVE: Permission.REVIEW_SUBMIT_DECISION,
    HumanReviewAction.REJECT: Permission.REVIEW_SUBMIT_DECISION,
    HumanReviewAction.RETURN_TO_PENDING: Permission.REVIEW_SUBMIT_DECISION,
    HumanReviewAction.REQUEST_ADDITIONAL_INFO: Permission.REVIEW_REQUEST_INFO,
    HumanReviewAction.RETURN_FOR_INVESTIGATION: Permission.REVIEW_RETURN_INVESTIGATION,
}


class ReviewSubmissionRequest(BaseModel):
    """API request body for submitting a human review decision.

    Note: reviewer identity fields (reviewer_id, reviewer_user_id, reviewer_role)
    are forbidden in client requests and derived solely from the validated token.
    """

    model_config = ConfigDict(extra="forbid")

    source_run_id: str = Field(..., min_length=1)
    application_id: str = Field(..., min_length=1)
    action: HumanReviewAction
    decision_reason: str = Field(..., min_length=5, max_length=500)
    comments: Optional[str] = Field(default=None, max_length=2000)
    additional_info_request: Optional[str] = Field(default=None, max_length=1000)
    additional_info_response: Optional[str] = Field(default=None, max_length=1000)
    investigation_instructions: Optional[str] = Field(default=None, max_length=1000)
    is_correction: bool = False
    parent_review_id: Optional[str] = None
    correction_explanation: Optional[str] = Field(default=None, max_length=500)
    expected_previous_status: Optional[ReviewStatus] = None
    confirmed: bool = False


@router.get("/queue", response_model=Dict[str, Any])
async def get_review_queue(
    application_id: Optional[str] = Query(default=None),
    ai_recommendation: Optional[str] = Query(default=None),
    pipeline_status: Optional[str] = Query(default=None),
    risk_category: Optional[str] = Query(default=None),
    review_status: Optional[str] = Query(default=None),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    user: User = Depends(
        require_any_permission(
            Permission.REVIEW_VIEW_ASSIGNED, Permission.REVIEW_VIEW_ALL
        )
    ),
) -> Dict[str, Any]:
    """Retrieve the human review queue with filters.

    Underwriters see assigned/open cases; Supervisors and Admins see all cases including finalized.
    """
    has_view_all = check_permission(user.role, Permission.REVIEW_VIEW_ALL)

    queue_items = list_review_queue(
        application_id_filter=application_id,
        ai_recommendation_filter=ai_recommendation,
        pipeline_status_filter=pipeline_status,
        risk_category_filter=risk_category,
        review_status_filter=review_status,
        start_date=start_date,
        end_date=end_date,
        include_finalized=has_view_all,
    )

    metrics = compute_review_queue_metrics(queue_items)

    return {
        "queue": queue_items,
        "metrics": metrics,
        "total": len(queue_items),
    }


@router.get("/case/{application_id}", response_model=Dict[str, Any])
async def get_case_summary(
    application_id: str,
    run_id: Optional[str] = Query(default=None),
    _user: User = Depends(
        require_any_permission(
            Permission.REVIEW_VIEW_ASSIGNED,
            Permission.REVIEW_VIEW_ALL,
            Permission.AUDIT_VIEW_ALL,
        )
    ),
) -> Dict[str, Any]:
    """Get the review summary for a specific application."""
    return get_case_review_summary(application_id, run_id=run_id)


@router.post("/submit", response_model=Dict[str, Any])
async def submit_review(
    body: ReviewSubmissionRequest,
    user: User = Depends(
        require_any_permission(
            Permission.REVIEW_SUBMIT_DECISION,
            Permission.REVIEW_REQUEST_INFO,
            Permission.REVIEW_RETURN_INVESTIGATION,
        )
    ),
) -> Dict[str, Any]:
    """Submit a human review decision using authoritative token identity.

    Enforces:
    - Fine-grained action permission via ROLE_PERMISSIONS
    - Supervisor-only linked corrections
    - Maker-Checker blocking self-review of own submitted apps or initiated runs
    - Optimistic concurrency checks via expected_previous_status
    """
    required_perm = _ACTION_PERMISSION_MAP[body.action]
    if not check_permission(user.role, required_perm):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission '{required_perm.value}' required for action '{body.action.value}'.",
        )

    # Maker-Checker: corrections require Supervisor/Admin
    if body.is_correction:
        try:
            enforce_correction_requires_supervisor(user.role)
        except MakerCheckerError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            )

    # Maker-Checker: cannot review/approve own submitted application or underwriting run
    run_row = get_audit_run_by_id(body.source_run_id)
    if run_row:
        snapshot = run_row.get("details_snapshot") or {}
        run_initiator_id = run_row.get("initiated_by_user_id") or snapshot.get(
            "initiated_by_user_id"
        )
        try:
            enforce_not_self_review(
                user.user_id,
                run_initiator_id,
                operation="review their own underwriting submission",
            )
        except MakerCheckerError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            )

    app_row = get_submitted_application(body.application_id)
    if app_row:
        app_submitter_id = app_row.get("submitted_by_user_id")
        try:
            enforce_not_self_review(
                user.user_id,
                app_submitter_id,
                operation="approve or review their own submitted application",
            )
        except MakerCheckerError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            )

    # Build submission payload with AUTHORITATIVE token identity (never trust client)
    submission_payload = {
        "source_run_id": body.source_run_id,
        "application_id": body.application_id,
        "action": body.action.value,
        "reviewer_id": f"{user.username} ({user.user_id})",
        "reviewer_user_id": user.user_id,
        "reviewer_username": user.username,
        "reviewer_role": user.role.value,
        "decision_reason": body.decision_reason,
        "comments": body.comments,
        "additional_info_request": body.additional_info_request,
        "additional_info_response": body.additional_info_response,
        "investigation_instructions": body.investigation_instructions,
        "is_correction": body.is_correction,
        "parent_review_id": body.parent_review_id,
        "correction_explanation": body.correction_explanation,
        "expected_previous_status": (
            body.expected_previous_status.value
            if body.expected_previous_status is not None
            else None
        ),
        "confirmed": body.confirmed,
    }

    result = submit_human_review_safe(submission_payload)

    if not result.get("saved"):
        error_msg = result.get("error", "Unknown error")
        if result.get("duplicate_blocked") or result.get("conflict"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    logger.info(
        "Human review submitted by '%s' (user_id=%s, role=%s) for run '%s': action=%s",
        user.username,
        user.user_id,
        user.role.value,
        body.source_run_id,
        body.action.value,
    )

    return result


@router.get("/history/{run_id}", response_model=List[Dict[str, Any]])
async def get_review_history(
    run_id: str,
    _user: User = Depends(
        require_any_permission(
            Permission.REVIEW_VIEW_ASSIGNED,
            Permission.REVIEW_VIEW_ALL,
            Permission.AUDIT_VIEW_ALL,
        )
    ),
) -> List[Dict[str, Any]]:
    """Get the review history for a specific underwriting run."""
    return get_review_history_for_run(run_id)
