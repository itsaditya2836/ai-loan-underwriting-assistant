"""Shared SQLAlchemy Engine, Dialect Detection, and Transaction Management.

Supports SQLite (local development and isolated testing) and PostgreSQL
(multi-user production deployments with connection pooling).

Note on PostgreSQL runtime driver:
    Setting DATABASE_URL to postgresql://... or postgresql+psycopg://...
    configures SQLAlchemy connection pooling automatically, provided a
    PostgreSQL DBAPI driver (e.g. psycopg2-binary or psycopg) is installed.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine

from app.utils.helpers import get_logger
from config.settings import get_settings

logger = get_logger(__name__)

_engine: Optional[Engine] = None
_engine_url: Optional[str] = None


def _build_engine_kwargs(url: str) -> Dict[str, Any]:
    """Construct SQLAlchemy create_engine options appropriate for the backend dialect."""
    settings = get_settings()
    kwargs: Dict[str, Any] = {
        "pool_pre_ping": True,
        "echo": settings.db_echo,
    }
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
        kwargs["pool_timeout"] = settings.db_pool_timeout
        kwargs["pool_recycle"] = 1800
    return kwargs


def create_configured_engine(database_url: Optional[str] = None) -> Engine:
    """Create a new SQLAlchemy Engine for the given or configured DATABASE_URL."""
    url = database_url or get_settings().database_url
    kwargs = _build_engine_kwargs(url)
    eng = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.close()

    return eng


def get_engine() -> Engine:
    """Return the cached shared SQLAlchemy Engine (rebuilding if DATABASE_URL changed)."""
    global _engine, _engine_url
    current_url = get_settings().database_url
    if _engine is None or _engine_url != current_url:
        if _engine is not None:
            _engine.dispose()
        _engine = create_configured_engine(current_url)
        _engine_url = current_url
    return _engine


def reset_engine() -> None:
    """Dispose and clear the cached SQLAlchemy Engine (used in test isolation)."""
    global _engine, _engine_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _engine_url = None


def get_dialect_name(engine: Optional[Engine] = None) -> str:
    """Return the SQLAlchemy dialect name (e.g., 'sqlite', 'postgresql')."""
    eng = engine or get_engine()
    return eng.dialect.name


def is_sqlite(engine: Optional[Engine] = None) -> bool:
    """Return True when the active engine targets SQLite."""
    return get_dialect_name(engine) == "sqlite"


def is_postgresql(engine: Optional[Engine] = None) -> bool:
    """Return True when the active engine targets PostgreSQL."""
    return get_dialect_name(engine) == "postgresql"


@contextmanager
def db_transaction(
    engine: Optional[Engine] = None,
) -> Generator[Connection, None, None]:
    """Provide a managed transactional SQLAlchemy Connection with automatic commit/rollback."""
    eng = engine or get_engine()
    with eng.begin() as conn:
        yield conn


__all__ = [
    "create_configured_engine",
    "db_transaction",
    "get_dialect_name",
    "get_engine",
    "is_postgresql",
    "is_sqlite",
    "reset_engine",
]
