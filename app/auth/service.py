"""User management and authentication service layer.

Handles:
- User CRUD against SQLAlchemy tables (users, refresh_tokens, login_attempts).
- Login with Argon2id verification + JWT token pair issuance.
- Refresh token rotation and revocation.
- Brute-force rate limiting via login_attempts table.
- Database initialization (creates auth tables if missing).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine

from app.auth.models import (
    Role,
    TokenPair,
    User,
    UserCreate,
    UserPublic,
    UserUpdate,
    auth_metadata,
    login_attempts_table,
    refresh_tokens_table,
    users_table,
)
from app.auth.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
    verify_token,
)
from app.database.engine import get_engine as _shared_get_engine
from app.database.engine import reset_engine as _shared_reset_engine
from app.utils.helpers import get_logger
from config.settings import get_settings

logger = get_logger(__name__)


class AuthenticationError(Exception):
    """Generic authentication failure (login, token, etc.)."""


class AuthorizationError(Exception):
    """Authorization / permission failure."""


def _get_engine() -> Engine:
    """Return or create the SQLAlchemy engine from settings."""
    return _shared_get_engine()


def reset_engine() -> None:
    """Reset engine cache (for testing with temporary databases)."""
    _shared_reset_engine()


def init_auth_tables(engine: Optional[Engine] = None) -> None:
    """Create auth tables (users, refresh_tokens, login_attempts) if they don't exist."""
    eng = engine or _get_engine()
    auth_metadata.create_all(eng, checkfirst=True)
    logger.info("Auth tables initialized successfully.")


class AuthService:
    """Stateless authentication and user management service."""

    def __init__(self, engine: Optional[Engine] = None) -> None:
        self.engine = engine or _get_engine()

    def init_tables(self) -> None:
        """Create auth tables if absent."""
        init_auth_tables(self.engine)

    # -------------------------------------------------------------------
    # User CRUD
    # -------------------------------------------------------------------

    def create_user(self, data: UserCreate) -> UserPublic:
        """Create a new user with Argon2id-hashed password."""
        user_id = f"USR-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        pw_hash = hash_password(data.password)

        with self.engine.begin() as conn:
            # Check uniqueness
            existing = conn.execute(
                select(users_table.c.user_id).where(
                    (users_table.c.username == data.username)
                    | (users_table.c.email == data.email)
                )
            ).fetchone()
            if existing:
                raise ValueError(
                    f"A user with username '{data.username}' or email '{data.email}' already exists."
                )

            conn.execute(
                users_table.insert().values(
                    user_id=user_id,
                    username=data.username,
                    full_name=data.full_name,
                    email=data.email,
                    password_hash=pw_hash,
                    role=data.role.value,
                    is_active=True,
                    is_locked=False,
                    failed_login_count=0,
                    created_at=now,
                    updated_at=now,
                )
            )

        logger.info("Created user '%s' (role=%s).", data.username, data.role.value)
        return self.get_user_public(user_id)  # type: ignore[return-value]

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Fetch full internal user record by user_id."""
        with self.engine.connect() as conn:
            row = conn.execute(
                select(users_table).where(users_table.c.user_id == user_id)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_user(row)

    def get_user_by_username(self, username: str) -> Optional[User]:
        """Fetch full internal user record by username."""
        with self.engine.connect() as conn:
            row = conn.execute(
                select(users_table).where(users_table.c.username == username)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_user(row)

    def get_user_public(self, user_id: str) -> Optional[UserPublic]:
        """Fetch public user record by user_id."""
        user = self.get_user_by_id(user_id)
        return user.to_public() if user else None

    def list_users(self, limit: int = 200) -> List[UserPublic]:
        """List all users (public view)."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(users_table)
                .order_by(users_table.c.created_at.desc())
                .limit(limit)
            ).fetchall()
        return [self._row_to_user(r).to_public() for r in rows]

    def update_user(self, user_id: str, data: UserUpdate) -> Optional[UserPublic]:
        """Update user fields (admin operation)."""
        updates: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
        if data.full_name is not None:
            updates["full_name"] = data.full_name
        if data.email is not None:
            updates["email"] = data.email
        if data.role is not None:
            updates["role"] = data.role.value
        if data.is_active is not None:
            updates["is_active"] = data.is_active
        if data.is_locked is not None:
            updates["is_locked"] = data.is_locked
            if not data.is_locked:
                updates["failed_login_count"] = 0

        with self.engine.begin() as conn:
            conn.execute(
                update(users_table)
                .where(users_table.c.user_id == user_id)
                .values(**updates)
            )
        return self.get_user_public(user_id)

    def deactivate_user(self, user_id: str) -> Optional[UserPublic]:
        """Deactivate a user (soft delete)."""
        return self.update_user(user_id, UserUpdate(is_active=False))

    # -------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------

    def login(
        self,
        username: str,
        password: str,
        ip_address: Optional[str] = None,
    ) -> TokenPair:
        """Authenticate user and return JWT token pair.

        Raises:
            AuthenticationError: On invalid credentials, locked account, or rate limit.
        """
        settings = get_settings()

        # Rate limiting check
        if self._is_rate_limited(username):
            # Still increment the per-user lockout counter if the user exists
            user_for_lockout = self.get_user_by_username(username)
            if user_for_lockout and user_for_lockout.is_active:
                self._increment_failed_logins(user_for_lockout.user_id)
            self._record_login_attempt(username, ip_address, success=False)
            raise AuthenticationError(
                "Too many failed login attempts. Please try again later."
            )

        user = self.get_user_by_username(username)

        # Generic failure message to prevent user enumeration
        if user is None:
            self._record_login_attempt(username, ip_address, success=False)
            raise AuthenticationError("Invalid credentials.")

        if not user.is_active:
            self._record_login_attempt(username, ip_address, success=False)
            raise AuthenticationError("Invalid credentials.")

        if user.is_locked:
            self._record_login_attempt(username, ip_address, success=False)
            raise AuthenticationError("Account is locked. Contact an administrator.")

        if not verify_password(password, user.password_hash):
            self._increment_failed_logins(user.user_id)
            self._record_login_attempt(username, ip_address, success=False)
            raise AuthenticationError("Invalid credentials.")

        # Successful login
        self._reset_failed_logins(user.user_id)
        self._record_login_attempt(username, ip_address, success=True)

        # Rehash if Argon2 parameters changed
        if needs_rehash(user.password_hash):
            new_hash = hash_password(password)
            with self.engine.begin() as conn:
                conn.execute(
                    update(users_table)
                    .where(users_table.c.user_id == user.user_id)
                    .values(
                        password_hash=new_hash, updated_at=datetime.now(timezone.utc)
                    )
                )

        # Update last_login_at
        with self.engine.begin() as conn:
            conn.execute(
                update(users_table)
                .where(users_table.c.user_id == user.user_id)
                .values(last_login_at=datetime.now(timezone.utc))
            )

        # Issue token pair
        access_token = create_access_token(
            {
                "sub": user.user_id,
                "username": user.username,
                "role": user.role.value,
            }
        )
        refresh_tok = create_refresh_token({"sub": user.user_id})

        # Store refresh token hash
        self._store_refresh_token(
            user.user_id,
            refresh_tok,
            timedelta(days=settings.refresh_token_expire_days),
        )

        logger.info("User '%s' logged in successfully.", username)
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_tok,
            expires_in=settings.access_token_expire_minutes * 60,
        )

    def refresh(self, refresh_tok: str) -> TokenPair:
        """Exchange a valid refresh token for a new token pair (rotation).

        Raises:
            AuthenticationError: If refresh token is invalid, expired, or revoked.
        """
        settings = get_settings()
        claims = verify_token(refresh_tok, expected_type="refresh")
        if claims is None:
            raise AuthenticationError("Invalid or expired refresh token.")

        user_id = claims.get("sub")
        if not user_id:
            raise AuthenticationError("Invalid refresh token claims.")

        # Check token hash in DB
        tok_hash = hash_token(refresh_tok)
        with self.engine.connect() as conn:
            row = conn.execute(
                select(refresh_tokens_table).where(
                    (refresh_tokens_table.c.token_hash == tok_hash)
                    & (refresh_tokens_table.c.revoked == False)  # noqa: E712
                )
            ).fetchone()

        if row is None:
            raise AuthenticationError("Refresh token not found or revoked.")

        # Revoke old refresh token (rotation)
        with self.engine.begin() as conn:
            conn.execute(
                update(refresh_tokens_table)
                .where(refresh_tokens_table.c.token_hash == tok_hash)
                .values(revoked=True)
            )

        user = self.get_user_by_id(user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("User account not found or deactivated.")

        # Issue new pair
        new_access = create_access_token(
            {
                "sub": user.user_id,
                "username": user.username,
                "role": user.role.value,
            }
        )
        new_refresh = create_refresh_token({"sub": user.user_id})
        self._store_refresh_token(
            user.user_id,
            new_refresh,
            timedelta(days=settings.refresh_token_expire_days),
        )

        return TokenPair(
            access_token=new_access,
            refresh_token=new_refresh,
            expires_in=settings.access_token_expire_minutes * 60,
        )

    def logout(self, user_id: str) -> None:
        """Revoke all refresh tokens for a user."""
        with self.engine.begin() as conn:
            conn.execute(
                update(refresh_tokens_table)
                .where(
                    (refresh_tokens_table.c.user_id == user_id)
                    & (refresh_tokens_table.c.revoked == False)  # noqa: E712
                )
                .values(revoked=True)
            )
        logger.info("All refresh tokens revoked for user '%s'.", user_id)

    def get_current_user(self, token: str) -> User:
        """Validate access token and return the authenticated user.

        Raises:
            AuthenticationError: If token is invalid or user not found.
        """
        claims = verify_token(token, expected_type="access")
        if claims is None:
            raise AuthenticationError("Invalid or expired access token.")

        user_id = claims.get("sub")
        if not user_id:
            raise AuthenticationError("Invalid token claims.")

        user = self.get_user_by_id(user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("User account not found or deactivated.")

        return user

    # -------------------------------------------------------------------
    # Seed Default Admin
    # -------------------------------------------------------------------

    def seed_default_admin(self) -> Optional[UserPublic]:
        """Create default admin user if no users exist (development only).

        Returns the created admin user, or None if users already exist.
        """
        with self.engine.connect() as conn:
            count = conn.execute(select(func.count()).select_from(users_table)).scalar()

        if count and count > 0:
            return None

        settings = get_settings()
        admin = self.create_user(
            UserCreate(
                username="admin",
                full_name="System Administrator",
                email="admin@underwriting.local",
                password=settings.default_admin_password,
                role=Role.ADMINISTRATOR,
            )
        )
        logger.info("Seeded default admin user (username='admin').")
        return admin

    # -------------------------------------------------------------------
    # Internal Helpers
    # -------------------------------------------------------------------

    def _store_refresh_token(
        self,
        user_id: str,
        token: str,
        expires_delta: timedelta,
    ) -> None:
        """Store hashed refresh token in the database."""
        token_id = f"RT-{uuid.uuid4().hex[:12]}"
        tok_hash = hash_token(token)
        expires_at = datetime.now(timezone.utc) + expires_delta

        with self.engine.begin() as conn:
            conn.execute(
                refresh_tokens_table.insert().values(
                    token_id=token_id,
                    user_id=user_id,
                    token_hash=tok_hash,
                    expires_at=expires_at,
                    revoked=False,
                    created_at=datetime.now(timezone.utc),
                )
            )

    def _record_login_attempt(
        self,
        username: str,
        ip_address: Optional[str],
        success: bool,
    ) -> None:
        """Record a login attempt for auditing and rate limiting."""
        with self.engine.begin() as conn:
            conn.execute(
                login_attempts_table.insert().values(
                    username=username,
                    ip_address=ip_address,
                    success=success,
                    attempted_at=datetime.now(timezone.utc),
                )
            )

    def _is_rate_limited(self, username: str) -> bool:
        """Check if login attempts exceed the configured threshold."""
        settings = get_settings()
        window_start = datetime.now(timezone.utc) - timedelta(
            minutes=settings.login_rate_limit_window_minutes
        )

        with self.engine.connect() as conn:
            count = conn.execute(
                select(func.count())
                .select_from(login_attempts_table)
                .where(
                    (login_attempts_table.c.username == username)
                    & (login_attempts_table.c.success == False)  # noqa: E712
                    & (login_attempts_table.c.attempted_at >= window_start)
                )
            ).scalar()

        return (count or 0) >= settings.login_rate_limit_max_attempts

    def _increment_failed_logins(self, user_id: str) -> None:
        """Increment failed login counter and lock if threshold reached."""
        settings = get_settings()
        with self.engine.begin() as conn:
            conn.execute(
                update(users_table)
                .where(users_table.c.user_id == user_id)
                .values(
                    failed_login_count=users_table.c.failed_login_count + 1,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            # Check if should lock
            row = conn.execute(
                select(users_table.c.failed_login_count).where(
                    users_table.c.user_id == user_id
                )
            ).fetchone()
            if row and row[0] >= settings.max_failed_login_attempts:
                conn.execute(
                    update(users_table)
                    .where(users_table.c.user_id == user_id)
                    .values(is_locked=True, updated_at=datetime.now(timezone.utc))
                )
                logger.warning(
                    "User '%s' locked after %d failed attempts.", user_id, row[0]
                )

    def _reset_failed_logins(self, user_id: str) -> None:
        """Reset failed login counter on successful authentication."""
        with self.engine.begin() as conn:
            conn.execute(
                update(users_table)
                .where(users_table.c.user_id == user_id)
                .values(
                    failed_login_count=0,
                    is_locked=False,
                    updated_at=datetime.now(timezone.utc),
                )
            )

    @staticmethod
    def _row_to_user(row: Any) -> User:
        """Convert a SQLAlchemy Row to a User Pydantic model."""
        mapping = row._mapping if hasattr(row, "_mapping") else dict(row)
        return User(
            user_id=str(mapping["user_id"]),
            username=str(mapping["username"]),
            full_name=str(mapping["full_name"]),
            email=str(mapping["email"]),
            password_hash=str(mapping["password_hash"]),
            role=Role(str(mapping["role"])),
            is_active=bool(mapping.get("is_active", True)),
            is_locked=bool(mapping.get("is_locked", False)),
            failed_login_count=int(mapping.get("failed_login_count", 0)),
            last_login_at=mapping.get("last_login_at"),
            created_at=mapping.get("created_at"),
            updated_at=mapping.get("updated_at"),
        )


__all__ = [
    "AuthService",
    "AuthenticationError",
    "AuthorizationError",
    "init_auth_tables",
    "reset_engine",
]
