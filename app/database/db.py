"""Database abstraction module for the Loan Underwriting Assistant.

Provides clean connection management to the underlying database (SQLite for
the prototype phase). Modular design allows seamless replacement with PostgreSQL
or other relational backends in production.
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Generator
from urllib.parse import urlparse

from app.utils.helpers import get_logger
from config.settings import get_settings

logger = get_logger(__name__)


def _get_sqlite_path_from_url(database_url: str) -> str:
    """Extract filesystem path from a sqlite URL.

    Handles sqlite:///relative/path.db and sqlite:////absolute/path.db.
    """
    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "", 1)
    if database_url.startswith("sqlite://"):
        parsed = urlparse(database_url)
        return parsed.path
    return database_url


@contextmanager
def get_database_connection() -> Generator[sqlite3.Connection, None, None]:
    """Context manager providing a managed SQLite connection.

    Fails fast if configured with a non-SQLite DATABASE_URL rather than
    misinterpreting PostgreSQL URIs as filesystem paths.
    """
    settings = get_settings()
    if not settings.database_url.startswith("sqlite"):
        raise RuntimeError(
            "SQLite connection manager invoked while DATABASE_URL targets a non-SQLite backend "
            f"('{settings.database_url.split('://', 1)[0]}'). Historical underwriting/review "
            "SQLite helpers require SQLite or SQLAlchemy dialect migration before runtime cutover."
        )
    db_path = _get_sqlite_path_from_url(settings.database_url)

    # Ensure parent directory exists if a path is present
    parent_dir = os.path.dirname(db_path)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        yield conn
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error(f"Database transaction rollback due to error: {exc}")
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Initialize database connection, verify accessibility, and create tables."""
    logger.info("Verifying database connectivity...")
    with get_database_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1;")
        logger.info("Database connection established successfully.")

    from app.database.applications import init_applications_table
    from app.database.audit import init_audit_table
    from app.database.reviews import init_reviews_table

    init_applications_table()
    init_audit_table()
    init_reviews_table()
