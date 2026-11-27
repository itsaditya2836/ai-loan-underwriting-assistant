"""FastAPI application and dependency injection.

Provides:
- get_auth_service: Returns singleton AuthService.
- get_current_user: Extracts authenticated User from Bearer token.
- require_permission: Factory dependency enforcing RBAC permission checks.
"""

from __future__ import annotations

import re
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import User
from app.auth.permissions import Permission, check_permission
from app.auth.service import AuthenticationError, AuthService

_SAFE_APPLICANT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_bearer_scheme = HTTPBearer(auto_error=False)
_auth_service: AuthService | None = None


def get_auth_service() -> AuthService:
    """Return the shared AuthService singleton."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
        _auth_service.init_tables()
    return _auth_service


def reset_auth_service() -> None:
    """Reset the cached AuthService (for testing)."""
    global _auth_service
    _auth_service = None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    auth: AuthService = Depends(get_auth_service),
) -> User:
    """Extract the authenticated user from the Authorization header.

    Raises:
        HTTPException 401: If token is missing, invalid, or user not found.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user = auth.get_current_user(credentials.credentials)
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_permission(
    permission: Permission,
) -> Callable[..., User]:
    """FastAPI dependency factory enforcing a specific RBAC permission.

    Usage:
        @router.get("/protected")
        async def endpoint(user: User = Depends(require_permission(Permission.APPLICANT_VIEW_ALL))):
            ...
    """

    async def _check(user: User = Depends(get_current_user)) -> User:
        if not check_permission(user.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission.value}' required. Your role '{user.role.value}' does not have this permission.",
            )
        return user

    return _check


def require_any_permission(
    *permissions: Permission,
) -> Callable[..., User]:
    """FastAPI dependency factory requiring at least one of the listed permissions."""

    async def _check_any(user: User = Depends(get_current_user)) -> User:
        if any(check_permission(user.role, p) for p in permissions):
            return user
        required_names = ", ".join(p.value for p in permissions)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"One of permissions [{required_names}] required. "
                f"Your role '{user.role.value}' is not authorized."
            ),
        )

    return _check_any


def sanitize_applicant_id(applicant_id: str) -> str:
    """Validate and return a path-safe applicant identifier or raise 400 Bad Request."""
    cleaned = (applicant_id or "").strip()
    if (
        not cleaned
        or ".." in cleaned
        or "/" in cleaned
        or "\\" in cleaned
        or not _SAFE_APPLICANT_ID_RE.fullmatch(cleaned)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid applicant identifier format.",
        )
    return cleaned


__all__ = [
    "get_auth_service",
    "get_current_user",
    "require_any_permission",
    "require_permission",
    "reset_auth_service",
    "sanitize_applicant_id",
]
