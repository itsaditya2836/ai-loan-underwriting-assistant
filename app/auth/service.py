"""User management and authentication service layer.

Handles:
- User CRUD against SQLAlchemy tables (users, refresh_tokens, login_attempts).
- Login with Argon2id constant-time verification + JWT token pair issuance.
- Refresh token rotation, expiration validation, and reuse detection.
- Logout revocation bumping per-user token_version (invalidates active access tokens too).
- Brute-force sliding-window rate limiting (per-username + per-IP) and account lockout.
- Idempotent auth table initialization and safe non-production default admin seeding.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, inspect, select, text, update
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
    DUMMY_PASSWORD_HASH,
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


def _normalize_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize naive datetimes (e.g., from SQLite) to UTC-aware datetimes."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def init_auth_tables(engine: Optional[Engine] = None) -> None:
    """Create auth tables and apply non-destructive additive auth columns if missing."""
    eng = engine or _get_engine()
    auth_metadata.create_all(eng, checkfirst=True)

    # Additive Stage 8 column migration for pre-existing Stage 7 auth DBs
    inspector = inspect(eng)
    if "users" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("users")}
        if "token_version" not in existing_cols:
            with eng.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"
                    )
                )

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
            existing = conn.execute(
                select(users_table.c.user_id).where(
                    (users_table.c.username == data.username)
                    | (users_table.c.email == data.email)
                )
            ).fetchone()
            if existing:
                raise ValueError("A user with that username or email already exists.")

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
                    token_version=0,
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
        """Update user fields (admin operation); revokes tokens on role change or deactivation."""
        existing_user = self.get_user_by_id(user_id)
        if existing_user is None:
            return None

        updates: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
        revoke_tokens = False

        if data.full_name is not None:
            updates["full_name"] = data.full_name
        if data.email is not None:
            updates["email"] = data.email
        if data.role is not None and data.role != existing_user.role:
            updates["role"] = data.role.value
            revoke_tokens = True
        if data.is_active is not None:
            updates["is_active"] = data.is_active
            if not data.is_active:
                revoke_tokens = True
        if data.is_locked is not None:
            updates["is_locked"] = data.is_locked
            if not data.is_locked:
                updates["failed_login_count"] = 0
            else:
                revoke_tokens = True

        if revoke_tokens:
            updates["token_version"] = existing_user.token_version + 1

        with self.engine.begin() as conn:
            conn.execute(
                update(users_table)
                .where(users_table.c.user_id == user_id)
                .values(**updates)
            )
            if revoke_tokens:
                conn.execute(
                    update(refresh_tokens_table)
                    .where(
                        (refresh_tokens_table.c.user_id == user_id)
                        & (refresh_tokens_table.c.revoked == False)  # noqa: E712
                    )
                    .values(revoked=True)
                )
        return self.get_user_public(user_id)

    def deactivate_user(self, user_id: str) -> Optional[UserPublic]:
        """Deactivate a user (soft delete) and revoke active sessions."""
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
        """Authenticate user and return JWT token pair with generic error messages."""
        settings = get_settings()
        settings.validate_production_security()

        # Rate limiting check (per-username + per-IP)
        if self._is_rate_limited(username, ip_address=ip_address):
            user_for_lockout = self.get_user_by_username(username)
            if user_for_lockout and user_for_lockout.is_active:
                self._increment_failed_logins(user_for_lockout.user_id)
            self._record_login_attempt(username, ip_address, success=False)
            raise AuthenticationError(
                "Too many failed login attempts. Please try again later."
            )

        user = self.get_user_by_username(username)

        # Constant-time guard for missing, inactive, or locked accounts (prevents enumeration)
        if user is None or not user.is_active or user.is_locked:
            verify_password(password, DUMMY_PASSWORD_HASH)
            self._record_login_attempt(username, ip_address, success=False)
            raise AuthenticationError("Invalid credentials.")

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

        # Issue token pair carrying token_version
        access_token = create_access_token(
            {
                "sub": user.user_id,
                "username": user.username,
                "role": user.role.value,
                "ver": user.token_version,
            }
        )
        refresh_tok = create_refresh_token(
            {"sub": user.user_id, "ver": user.token_version}
        )

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
        """Exchange a valid refresh token for a new pair with reuse detection."""
        settings = get_settings()
        settings.validate_production_security()

        claims = verify_token(refresh_tok, expected_type="refresh")
        if claims is None:
            raise AuthenticationError("Invalid or expired refresh token.")

        user_id = claims.get("sub")
        if not user_id:
            raise AuthenticationError("Invalid refresh token claims.")

        tok_hash = hash_token(refresh_tok)
        with self.engine.connect() as conn:
            row = conn.execute(
                select(refresh_tokens_table).where(
                    refresh_tokens_table.c.token_hash == tok_hash
                )
            ).fetchone()

        if row is None:
            raise AuthenticationError("Refresh token not found or revoked.")

        mapping = row._mapping
        # Reuse detection: an already-revoked token was re-presented -> revoke full session family!
        if bool(mapping["revoked"]):
            logger.warning(
                "Refresh token reuse detected for user '%s'; revoking all active sessions.",
                user_id,
            )
            self.logout(str(user_id))
            raise AuthenticationError("Refresh token not found or revoked.")

        expires_at = _normalize_utc(mapping.get("expires_at"))
        if expires_at is not None and expires_at <= datetime.now(timezone.utc):
            with self.engine.begin() as conn:
                conn.execute(
                    update(refresh_tokens_table)
                    .where(refresh_tokens_table.c.token_hash == tok_hash)
                    .values(revoked=True)
                )
            raise AuthenticationError("Invalid or expired refresh token.")

        # Revoke old refresh token (single-use rotation)
        with self.engine.begin() as conn:
            conn.execute(
                update(refresh_tokens_table)
                .where(refresh_tokens_table.c.token_hash == tok_hash)
                .values(revoked=True)
            )

        user = self.get_user_by_id(str(user_id))
        if user is None or not user.is_active or user.is_locked:
            raise AuthenticationError("User account not found or deactivated.")

        token_ver = int(claims.get("ver", 0))
        if token_ver != user.token_version:
            raise AuthenticationError("Session has been revoked.")

        new_access = create_access_token(
            {
                "sub": user.user_id,
                "username": user.username,
                "role": user.role.value,
                "ver": user.token_version,
            }
        )
        new_refresh = create_refresh_token(
            {"sub": user.user_id, "ver": user.token_version}
        )
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
        """Revoke all refresh tokens and increment token_version to invalidate active access tokens."""
        with self.engine.begin() as conn:
            conn.execute(
                update(refresh_tokens_table)
                .where(
                    (refresh_tokens_table.c.user_id == user_id)
                    & (refresh_tokens_table.c.revoked == False)  # noqa: E712
                )
                .values(revoked=True)
            )
            conn.execute(
                update(users_table)
                .where(users_table.c.user_id == user_id)
                .values(
                    token_version=users_table.c.token_version + 1,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        logger.info("Revoked all active sessions/tokens for user '%s'.", user_id)

    def get_current_user(self, token: str) -> User:
        """Validate access token including token_version and return the authenticated user."""
        claims = verify_token(token, expected_type="access")
        if claims is None:
            raise AuthenticationError("Invalid or expired access token.")

        user_id = claims.get("sub")
        if not user_id:
            raise AuthenticationError("Invalid token claims.")

        user = self.get_user_by_id(str(user_id))
        if user is None or not user.is_active or user.is_locked:
            raise AuthenticationError("User account not found or deactivated.")

        token_ver = int(claims.get("ver", 0))
        if token_ver != user.token_version:
            raise AuthenticationError("Access token has been revoked.")

        return user

    # -------------------------------------------------------------------
    # Seed Default Admin (Development / Test Only)
    # -------------------------------------------------------------------

    def seed_default_admin(self) -> Optional[UserPublic]:
        """Create default admin user in development/test only when no users exist."""
        settings = get_settings()
        if settings.is_production():
            logger.info(
                "Production mode detected: skipping automatic default admin seeding."
            )
            return None

        with self.engine.connect() as conn:
            count = conn.execute(select(func.count()).select_from(users_table)).scalar()

        if count and count > 0:
            return None

        admin = self.create_user(
            UserCreate(
                username="admin",
                full_name="System Administrator",
                email="admin@underwriting.local",
                password=settings.default_admin_password,
                role=Role.ADMINISTRATOR,
            )
        )
        logger.info("Seeded default development admin user (username='admin').")
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

    def _is_rate_limited(
        self,
        username: str,
        ip_address: Optional[str] = None,
    ) -> bool:
        """Check if per-username or per-IP failed login attempts exceed threshold."""
        settings = get_settings()
        window_start = datetime.now(timezone.utc) - timedelta(
            minutes=settings.login_rate_limit_window_minutes
        )

        with self.engine.connect() as conn:
            user_count = conn.execute(
                select(func.count())
                .select_from(login_attempts_table)
                .where(
                    (login_attempts_table.c.username == username)
                    & (login_attempts_table.c.success == False)  # noqa: E712
                    & (login_attempts_table.c.attempted_at >= window_start)
                )
            ).scalar()
            if (user_count or 0) >= settings.login_rate_limit_max_attempts:
                return True

            if ip_address:
                ip_cap = max(settings.login_rate_limit_max_attempts * 4, 20)
                ip_count = conn.execute(
                    select(func.count())
                    .select_from(login_attempts_table)
                    .where(
                        (login_attempts_table.c.ip_address == ip_address)
                        & (login_attempts_table.c.success == False)  # noqa: E712
                        & (login_attempts_table.c.attempted_at >= window_start)
                    )
                ).scalar()
                if (ip_count or 0) >= ip_cap:
                    return True

        return False

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
            row = conn.execute(
                select(users_table.c.failed_login_count).where(
                    users_table.c.user_id == user_id
                )
            ).fetchone()
            if row and row[0] >= settings.max_failed_login_attempts:
                conn.execute(
                    update(users_table)
                    .where(users_table.c.user_id == user_id)
                    .values(
                        is_locked=True,
                        token_version=users_table.c.token_version + 1,
                        updated_at=datetime.now(timezone.utc),
                    )
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
            token_version=int(mapping.get("token_version", 0)),
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
