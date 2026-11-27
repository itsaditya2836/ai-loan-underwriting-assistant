"""Audit history API routes with RBAC scoping."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import require_any_permission, require_permission
from app.auth.models import Role, User
from app.auth.permissions import Permission, check_permission
from app.database.audit import (
    get_audit_analytics_summary,
    get_audit_daily_trends,
    get_audit_run_by_id,
    get_audit_runs,
)
from app.database.reviews import get_human_review_events
from app.utils.helpers import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/runs", response_model=List[Dict[str, Any]])
async def list_audit_runs(
    application_id: Optional[str] = Query(default=None),
    recommendation: Optional[str] = Query(default=None),
    pipeline_status: Optional[str] = Query(default=None),
    risk_category: Optional[str] = Query(default=None),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    limit: int = Query(default=200, le=500),
    user: User = Depends(
        require_any_permission(Permission.AUDIT_VIEW_ALL, Permission.AUDIT_VIEW_OWN)
    ),
) -> List[Dict[str, Any]]:
    """List audit underwriting runs scoped by caller role."""
    # Loan Officers only view runs they initiated; Underwriters, Supervisors, Admins inspect all runs
    scoped_initiator = user.user_id if user.role == Role.LOAN_OFFICER else None
    return get_audit_runs(
        application_id=application_id,
        recommendation=recommendation,
        pipeline_status=pipeline_status,
        risk_category=risk_category,
        start_date=start_date,
        end_date=end_date,
        initiated_by_user_id=scoped_initiator,
        limit=limit,
    )


@router.get("/runs/{run_id}", response_model=Dict[str, Any])
async def get_run_detail(
    run_id: str,
    user: User = Depends(
        require_any_permission(Permission.AUDIT_VIEW_ALL, Permission.AUDIT_VIEW_OWN)
    ),
) -> Dict[str, Any]:
    """Get details of a specific underwriting run."""
    run = get_audit_run_by_id(run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit run '{run_id}' not found.",
        )
    owner_id = run.get("initiated_by_user_id")
    if user.role == Role.LOAN_OFFICER and owner_id and owner_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to inspect another user's underwriting audit run.",
        )
    return run


@router.get("/reviews", response_model=List[Dict[str, Any]])
async def list_review_events(
    application_id_prefix: Optional[str] = Query(default=None),
    reviewer_id: Optional[str] = Query(default=None),
    new_review_status: Optional[str] = Query(default=None),
    human_decision: Optional[str] = Query(default=None),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    limit: int = Query(default=200, le=500),
    user: User = Depends(
        require_any_permission(
            Permission.AUDIT_VIEW_ALL, Permission.REVIEW_VIEW_ASSIGNED
        )
    ),
) -> List[Dict[str, Any]]:
    """List human review audit events."""
    has_audit_all = check_permission(user.role, Permission.AUDIT_VIEW_ALL)
    scoped_user_id: Optional[str] = None
    if not has_audit_all:
        # Underwriters can inspect only their own review events
        scoped_user_id = user.user_id
        reviewer_id = None

    return get_human_review_events(
        application_id_prefix=application_id_prefix,
        reviewer_id=reviewer_id,
        reviewer_user_id=scoped_user_id,
        new_review_status=new_review_status,
        human_decision=human_decision,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


@router.get("/summary", response_model=Dict[str, Any])
async def get_audit_summary(
    _user: User = Depends(require_permission(Permission.AUDIT_VIEW_ALL)),
) -> Dict[str, Any]:
    """Get aggregate audit analytics summary (Admin/Supervisor only)."""
    return get_audit_analytics_summary()


@router.get("/trends", response_model=List[Dict[str, Any]])
async def get_trends(
    _user: User = Depends(require_permission(Permission.AUDIT_VIEW_ALL)),
) -> List[Dict[str, Any]]:
    """Get daily audit trend data (Admin/Supervisor only)."""
    return get_audit_daily_trends()
