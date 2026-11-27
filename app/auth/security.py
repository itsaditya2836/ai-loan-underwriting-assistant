"""Cryptographic primitives for password hashing and JWT token management.

- Password hashing uses Argon2id via argon2-cffi.
- JWT tokens enforce explicit HMAC algorithms (HS256/HS384/HS512), issuer, audience,
  issued-at, not-before, expiration, and unique JTI claims.
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

from config.settings import ALLOWED_JWT_ALGORITHMS, get_settings

# Argon2id hasher with OWASP-recommended baseline parameters
_ph = PasswordHasher(
    time_cost=2,
    memory_cost=19456,  # ~19 MiB
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Argon2Type.ID,  # Argon2id
)

# Precomputed valid Argon2id hash for constant-time verification on missing accounts
DUMMY_PASSWORD_HASH = _ph.hash("constant-time-dummy-guard-never-matches")


def _validated_algorithm(alg: str) -> str:
    """Enforce restricted symmetric HMAC algorithm list (rejects 'none' / confusion)."""
    if alg not in ALLOWED_JWT_ALGORITHMS:
        raise ValueError(f"Unsupported JWT algorithm '{alg}'.")
    return alg


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id."""
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored Argon2id hash."""
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, HashingError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Check whether the hash parameters are outdated and need rehashing."""
    return _ph.check_needs_rehash(password_hash)


def hash_token(token: str) -> str:
    """SHA-256 hash a refresh token for safe database storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _build_token(
    data: Dict[str, Any],
    *,
    token_type: str,
    expires_delta: timedelta,
) -> str:
    """Encode a signed JWT carrying standard issuer, audience, timestamps, and jti claims."""
    settings = get_settings()
    settings.validate_production_security()
    alg = _validated_algorithm(settings.jwt_algorithm)

    now = datetime.now(timezone.utc)
    to_encode = dict(data)
    to_encode["exp"] = now + expires_delta
    to_encode["iat"] = now
    to_encode["nbf"] = now
    to_encode["iss"] = settings.jwt_issuer
    to_encode["aud"] = settings.jwt_audience
    to_encode["type"] = token_type
    to_encode["jti"] = uuid.uuid4().hex
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=alg)


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a short-lived JWT access token."""
    settings = get_settings()
    delta = (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.access_token_expire_minutes)
    )
    return _build_token(data, token_type="access", expires_delta=delta)


def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a longer-lived JWT refresh token."""
    settings = get_settings()
    delta = (
        expires_delta
        if expires_delta is not None
        else timedelta(days=settings.refresh_token_expire_days)
    )
    return _build_token(data, token_type="refresh", expires_delta=delta)


def verify_token(token: str, expected_type: str = "access") -> Optional[Dict[str, Any]]:
    """Decode and validate a JWT token including signature, exp, iss, aud, and type."""
    settings = get_settings()
    try:
        alg = _validated_algorithm(settings.jwt_algorithm)
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[alg],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
        if payload.get("type") != expected_type:
            return None
        if not payload.get("sub"):
            return None
        return payload
    except (JWTError, ValueError):
        return None


__all__ = [
    "DUMMY_PASSWORD_HASH",
    "create_access_token",
    "create_refresh_token",
    "hash_password",
    "hash_token",
    "needs_rehash",
    "verify_password",
    "verify_token",
]
