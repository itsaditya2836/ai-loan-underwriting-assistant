"""External integration status API routes (Administrator settings view)."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.api.dependencies import require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.integrations.registry import get_integration_statuses

router = APIRouter()


@router.get("/status", response_model=List[Dict[str, Any]])
async def integration_statuses(
    _user: User = Depends(require_permission(Permission.SETTINGS_VIEW)),
) -> List[Dict[str, Any]]:
    """List readiness/configuration status for registered external integration adapters."""
    return get_integration_statuses()
