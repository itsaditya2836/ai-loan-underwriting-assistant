"""Authentication API routes: login, refresh, logout, me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies import get_auth_service, get_current_user
from app.auth.models import LoginRequest, RefreshRequest, TokenPair, User, UserPublic
from app.auth.service import AuthenticationError, AuthService

router = APIRouter()


@router.post("/login", response_model=TokenPair)
async def login(
    body: LoginRequest,
    request: Request,
    auth: AuthService = Depends(get_auth_service),
) -> TokenPair:
    """Authenticate and return JWT token pair."""
    ip = request.client.host if request.client else None
    try:
        return auth.login(body.username, body.password, ip_address=ip)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )


@router.post("/refresh", response_model=TokenPair)
async def refresh_token(
    body: RefreshRequest,
    auth: AuthService = Depends(get_auth_service),
) -> TokenPair:
    """Exchange a valid refresh token for a new token pair."""
    try:
        return auth.refresh(body.refresh_token)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    user: User = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
) -> None:
    """Revoke all refresh tokens for the authenticated user."""
    auth.logout(user.user_id)


@router.get("/me", response_model=UserPublic)
async def get_me(user: User = Depends(get_current_user)) -> UserPublic:
    """Return the authenticated user's public profile."""
    return user.to_public()
