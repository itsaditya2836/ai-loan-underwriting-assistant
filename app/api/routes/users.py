"""User management API routes (Administrator only)."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_auth_service, require_permission
from app.auth.models import User, UserCreate, UserPublic, UserUpdate
from app.auth.permissions import Permission
from app.auth.service import AuthService

router = APIRouter()


@router.get("", response_model=List[UserPublic])
async def list_users(
    _user: User = Depends(require_permission(Permission.USER_VIEW)),
    auth: AuthService = Depends(get_auth_service),
) -> List[UserPublic]:
    """List all users (Admin only)."""
    return auth.list_users()


@router.post("", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    _user: User = Depends(require_permission(Permission.USER_CREATE)),
    auth: AuthService = Depends(get_auth_service),
) -> UserPublic:
    """Create a new user (Admin only)."""
    try:
        return auth.create_user(body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/{user_id}", response_model=UserPublic)
async def get_user(
    user_id: str,
    _user: User = Depends(require_permission(Permission.USER_VIEW)),
    auth: AuthService = Depends(get_auth_service),
) -> UserPublic:
    """Get a user by ID (Admin only)."""
    result = auth.get_user_public(user_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
    return result


@router.patch("/{user_id}", response_model=UserPublic)
async def update_user(
    user_id: str,
    body: UserUpdate,
    current_user: User = Depends(require_permission(Permission.USER_UPDATE)),
    auth: AuthService = Depends(get_auth_service),
) -> UserPublic:
    """Update a user (Admin only; blocks self-deactivation or self-role-demotion)."""
    if user_id == current_user.user_id:
        if body.is_active is False or (
            body.role is not None and body.role != current_user.role
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Administrators cannot deactivate or change their own role.",
            )
    result = auth.update_user(user_id, body)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
    return result


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: str,
    current_user: User = Depends(require_permission(Permission.USER_DEACTIVATE)),
    auth: AuthService = Depends(get_auth_service),
) -> None:
    """Deactivate (soft-delete) a user (Admin only)."""
    if user_id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account.",
        )
    result = auth.deactivate_user(user_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )
