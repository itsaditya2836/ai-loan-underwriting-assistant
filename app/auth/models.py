"""User, role, and token Pydantic models and SQLAlchemy table definitions.

Provides:
- Role enum with four initial roles.
- Pydantic models for user creation, update, and public display.
- SQLAlchemy table definitions for users, refresh_tokens, and login_attempts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

auth_metadata = MetaData()


class Role(str, Enum):
    """System roles for RBAC."""

    ADMINISTRATOR = "ADMINISTRATOR"
    LOAN_OFFICER = "LOAN_OFFICER"
    UNDERWRITER = "UNDERWRITER"
    SUPERVISOR = "SUPERVISOR"


# ---------------------------------------------------------------------------
# SQLAlchemy Table Definitions
# ---------------------------------------------------------------------------

users_table = Table(
    "users",
    auth_metadata,
    Column("user_id", String(64), primary_key=True),
    Column("username", String(64), unique=True, nullable=False, index=True),
    Column("full_name", String(128), nullable=False),
    Column("email", String(256), unique=True, nullable=False, index=True),
    Column("password_hash", Text, nullable=False),
    Column("role", String(32), nullable=False, default=Role.LOAN_OFFICER.value),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("is_locked", Boolean, nullable=False, default=False),
    Column("failed_login_count", Integer, nullable=False, default=0),
    Column("last_login_at", DateTime(timezone=True), nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    ),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    ),
)

refresh_tokens_table = Table(
    "refresh_tokens",
    auth_metadata,
    Column("token_id", String(64), primary_key=True),
    Column(
        "user_id",
        String(64),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("token_hash", String(128), nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked", Boolean, nullable=False, default=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    ),
)

login_attempts_table = Table(
    "login_attempts",
    auth_metadata,
    Column("attempt_id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(64), nullable=False, index=True),
    Column("ip_address", String(64), nullable=True),
    Column("success", Boolean, nullable=False),
    Column(
        "attempted_at",
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    ),
    Index("idx_login_attempts_user_time", "username", "attempted_at"),
)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    """Request schema for creating a new user."""

    username: str = Field(..., min_length=3, max_length=64)
    full_name: str = Field(..., min_length=2, max_length=128)
    email: str = Field(..., min_length=5, max_length=256)
    password: str = Field(..., min_length=8, max_length=128)
    role: Role = Field(default=Role.LOAN_OFFICER)


class UserUpdate(BaseModel):
    """Request schema for updating an existing user."""

    full_name: Optional[str] = Field(default=None, max_length=128)
    email: Optional[str] = Field(default=None, max_length=256)
    role: Optional[Role] = None
    is_active: Optional[bool] = None
    is_locked: Optional[bool] = None


class UserPublic(BaseModel):
    """Public (safe) representation of a user—no password hash."""

    user_id: str
    username: str
    full_name: str
    email: str
    role: Role
    is_active: bool
    is_locked: bool = False
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class User(BaseModel):
    """Internal representation including password hash—never serialize to API."""

    user_id: str
    username: str
    full_name: str
    email: str
    password_hash: str
    role: Role
    is_active: bool = True
    is_locked: bool = False
    failed_login_count: int = 0
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_public(self) -> UserPublic:
        """Strip sensitive fields for external display."""
        return UserPublic(
            user_id=self.user_id,
            username=self.username,
            full_name=self.full_name,
            email=self.email,
            role=self.role,
            is_active=self.is_active,
            is_locked=self.is_locked,
            last_login_at=self.last_login_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class TokenPair(BaseModel):
    """Access + refresh token pair returned on login."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token lifetime in seconds")


class LoginRequest(BaseModel):
    """Login credentials."""

    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class RefreshRequest(BaseModel):
    """Refresh token exchange."""

    refresh_token: str = Field(..., min_length=1)


__all__ = [
    "LoginRequest",
    "RefreshRequest",
    "Role",
    "TokenPair",
    "User",
    "UserCreate",
    "UserPublic",
    "UserUpdate",
    "auth_metadata",
    "login_attempts_table",
    "refresh_tokens_table",
    "users_table",
]
