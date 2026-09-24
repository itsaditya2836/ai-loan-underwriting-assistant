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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
