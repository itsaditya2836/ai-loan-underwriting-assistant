"""Cryptographic primitives for password hashing and JWT token management.

- Password hashing uses Argon2id via argon2-cffi.
- JWT tokens use HS256 via python-jose.
- All secrets are loaded from environment variables via config/settings.py.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from argon2 import PasswordHasher
from argon2 import Type as Argon2Type
from argon2.exceptions import HashingError, VerificationError, VerifyMismatchError
from jose import JWTError, jwt

from config.settings import get_settings

# Argon2id hasher with safe defaults
_ph = PasswordHasher(
    time_cost=2,
    memory_cost=19456,  # ~19 MiB
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Argon2Type.ID,  # Argon2id
)


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id.

    Returns:
        Encoded Argon2id hash string.
    """
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored Argon2id hash.

    Returns:
        True if password matches, False otherwise.
    """
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, HashingError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Check whether the hash parameters are outdated and need rehashing."""
    return _ph.check_needs_rehash(password_hash)


def hash_token(token: str) -> str:
    """SHA-256 hash a refresh token for safe storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a short-lived JWT access token.

    Args:
        data: Claims to encode (must include "sub" for user_id).
        expires_delta: Token lifetime. Defaults to settings.access_token_expire_minutes.

    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    to_encode = dict(data)
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    to_encode["exp"] = datetime.now(timezone.utc) + expires_delta
    to_encode["type"] = "access"
    to_encode["jti"] = uuid.uuid4().hex  # Ensure unique token on every issuance
    return jwt.encode(
        to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a longer-lived JWT refresh token.

    Args:
        data: Claims to encode (must include "sub" for user_id).
        expires_delta: Token lifetime. Defaults to settings.refresh_token_expire_days.

    Returns:
        Encoded JWT string.
    """
    settings = get_settings()
    to_encode = dict(data)
    if expires_delta is None:
        expires_delta = timedelta(days=settings.refresh_token_expire_days)
    to_encode["exp"] = datetime.now(timezone.utc) + expires_delta
    to_encode["type"] = "refresh"
    to_encode["jti"] = uuid.uuid4().hex  # Ensure unique token hash on every issuance
    return jwt.encode(
        to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def verify_token(token: str, expected_type: str = "access") -> Optional[Dict[str, Any]]:
    """Decode and validate a JWT token.

    Args:
        token: Encoded JWT string.
        expected_type: Expected token type ("access" or "refresh").

    Returns:
        Decoded claims dict if valid, None otherwise.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("type") != expected_type:
            return None
        return payload
    except JWTError:
        return None


__all__ = [
    "create_access_token",
    "create_refresh_token",
    "hash_password",
    "hash_token",
    "needs_rehash",
    "verify_password",
    "verify_token",
]
