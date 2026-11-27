"""Applicant management API routes."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import (
    require_any_permission,
    require_permission,
    sanitize_applicant_id,
)
from app.auth.models import User
from app.auth.permissions import Permission, check_permission
from app.database.applications import (
    get_submitted_application,
    list_submitted_applications,
    save_submitted_application,
)
from app.schemas.applicant import Applicant
from app.utils.helpers import get_logger

logger = get_logger(__name__)

APPLICANTS_DATA_PATH = os.path.join("data", "synthetic_data", "applicants.json")

router = APIRouter()


def _load_synthetic_catalog() -> Dict[str, Dict[str, Any]]:
    """Load synthetic applicant records from disk."""
    catalog: Dict[str, Dict[str, Any]] = {}
    if os.path.exists(APPLICANTS_DATA_PATH):
        with open(APPLICANTS_DATA_PATH, "r") as f:
            data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    aid = item.get("applicant_id")
                    if aid:
                        catalog[aid] = item
    return catalog


@router.get("", response_model=List[Dict[str, Any]])
async def list_applicants(
    limit: int = Query(default=200, le=500),
    user: User = Depends(
        require_any_permission(
            Permission.APPLICANT_VIEW_OWN, Permission.APPLICANT_VIEW_ALL
        )
    ),
) -> List[Dict[str, Any]]:
    """List applicants from submitted applications and synthetic catalog."""
    has_view_all = check_permission(user.role, Permission.APPLICANT_VIEW_ALL)
    submitted = list_submitted_applications(
        limit=limit,
        submitted_by_user_id=None if has_view_all else user.user_id,
    )
    catalog = _load_synthetic_catalog()

    # Merge: submitted take precedence over synthetic
    result: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for app in submitted:
        seen_ids.add(app["applicant_id"])
        result.append(app)
    for aid, record in catalog.items():
        if aid not in seen_ids and len(result) < limit:
            record["source"] = "synthetic"
            result.append(record)

    return result[:limit]


@router.get("/{applicant_id}", response_model=Dict[str, Any])
async def get_applicant(
    applicant_id: str,
    user: User = Depends(
        require_any_permission(
            Permission.APPLICANT_VIEW_OWN, Permission.APPLICANT_VIEW_ALL
        )
    ),
) -> Dict[str, Any]:
    """Get a specific applicant by ID."""
    safe_id = sanitize_applicant_id(applicant_id)
    has_view_all = check_permission(user.role, Permission.APPLICANT_VIEW_ALL)

    # Check submitted first
    submitted = get_submitted_application(safe_id)
    if submitted:
        owner_id = submitted.get("submitted_by_user_id")
        if not has_view_all and owner_id and owner_id != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access another user's submitted application.",
            )
        return submitted

    # Fall back to synthetic catalog
    catalog = _load_synthetic_catalog()
    if safe_id in catalog:
        record = catalog[safe_id]
        record["source"] = "synthetic"
        return record

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Applicant '{safe_id}' not found.",
    )


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_applicant(
    applicant: Applicant,
    user: User = Depends(require_permission(Permission.APPLICANT_CREATE)),
) -> Dict[str, Any]:
    """Register a new applicant."""
    safe_id = sanitize_applicant_id(applicant.applicant_id)
    if safe_id != applicant.applicant_id:
        applicant = applicant.model_copy(update={"applicant_id": safe_id})
    try:
        saved = save_submitted_application(
            applicant=applicant,
            submission_hash=f"api-{user.user_id}-{applicant.applicant_id}",
            application_status="SUBMITTED",
            submitted_by_user_id=user.user_id,
            submitted_by_username=user.username,
            submitted_by_role=user.role.value,
        )
        logger.info(
            "Applicant '%s' created by user '%s'.",
            applicant.applicant_id,
            user.username,
        )
        return saved
    except Exception as exc:
        logger.error("Failed to create applicant '%s': %s", safe_id, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to register applicant profile.",
        )
