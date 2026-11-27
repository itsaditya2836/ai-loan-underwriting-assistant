"""Application configuration module.

Loads configuration from environment variables and .env file using
Pydantic BaseSettings for type validation and secure defaults.
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings schema backed by environment variables."""

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./loan_underwriting.db"
    gemini_api_key: Optional[str] = None

    # --- Stage 7: JWT / Auth Configuration ---
    # IMPORTANT: Override jwt_secret_key via environment variable in production.
    # The default below is for LOCAL DEVELOPMENT ONLY and is NOT secure.
    jwt_secret_key: str = "DEV-ONLY-INSECURE-SECRET-CHANGE-IN-PRODUCTION"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Brute-force rate limiting
    login_rate_limit_max_attempts: int = 5
    login_rate_limit_window_minutes: int = 15
    max_failed_login_attempts: int = 10

    # Default admin password (development seed only)
    default_admin_password: str = "admin-dev-password-change-me"

    # --- Stage 7: Database Pooling & Optional UI Auth ---
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_echo: bool = False
    streamlit_auth_required: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
