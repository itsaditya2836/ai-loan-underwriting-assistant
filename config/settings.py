"""Application configuration module.

Loads configuration from environment variables and .env file using
Pydantic BaseSettings for type validation and secure defaults.
"""

from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_DEFAULT_JWT_SECRET = "DEV-ONLY-INSECURE-SECRET-CHANGE-IN-PRODUCTION"
DEV_DEFAULT_ADMIN_PASSWORD = "admin-dev-password-change-me"
ALLOWED_JWT_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})


class Settings(BaseSettings):
    """Application settings schema backed by environment variables."""

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./loan_underwriting.db"
    gemini_api_key: Optional[str] = None

    # --- Stage 7/8: JWT / Auth Configuration ---
    # IMPORTANT: Override jwt_secret_key via environment variable in production.
    # The default below is for LOCAL DEVELOPMENT ONLY and is refused in production.
    jwt_secret_key: str = DEV_DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "ai-loan-underwriting-assistant"
    jwt_audience: str = "underwriting-api"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Brute-force rate limiting
    login_rate_limit_max_attempts: int = 5
    login_rate_limit_window_minutes: int = 15
    max_failed_login_attempts: int = 10

    # Default admin password (development/test seed only; never auto-seeded in production)
    default_admin_password: str = DEV_DEFAULT_ADMIN_PASSWORD

    # --- Stage 7/8: Database Pooling, CORS & UI Auth ---
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_echo: bool = False
    streamlit_auth_required: bool = False
    cors_allowed_origins: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def is_production(self) -> bool:
        """Return True when running in production mode."""
        return self.app_env.strip().lower() in {"prod", "production"}

    def is_streamlit_auth_enforced(self) -> bool:
        """Return True when Streamlit must enforce login (always True in production)."""
        return self.is_production() or bool(self.streamlit_auth_required)

    def get_cors_origins(self) -> List[str]:
        """Parse configured CORS origins safely without wildcard+credentials issues."""
        if self.cors_allowed_origins and self.cors_allowed_origins.strip():
            return [
                origin.strip()
                for origin in self.cors_allowed_origins.split(",")
                if origin.strip()
            ]
        if self.is_production():
            return []
        return [
            "http://localhost:8501",
            "http://127.0.0.1:8501",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]

    def validate_production_security(self) -> None:
        """Fail closed if unsafe defaults or disallowed algorithms are configured."""
        if self.jwt_algorithm not in ALLOWED_JWT_ALGORITHMS:
            raise RuntimeError(
                f"Unsupported JWT algorithm '{self.jwt_algorithm}'. "
                f"Allowed: {sorted(ALLOWED_JWT_ALGORITHMS)}"
            )

        if not self.is_production():
            return

        errors: List[str] = []
        secret = (self.jwt_secret_key or "").strip()
        if not secret or secret == DEV_DEFAULT_JWT_SECRET or len(secret) < 32:
            errors.append(
                "JWT_SECRET_KEY must be overridden with a high-entropy secret of at least 32 characters in production."
            )

        if (self.default_admin_password or "").strip() == DEV_DEFAULT_ADMIN_PASSWORD:
            errors.append(
                "DEFAULT_ADMIN_PASSWORD must not retain the insecure development default in production."
            )

        if "*" in self.get_cors_origins():
            errors.append(
                "CORS_ALLOWED_ORIGINS must not contain wildcard '*' in production."
            )

        if errors:
            raise RuntimeError(
                "Production security configuration check failed: " + " ".join(errors)
            )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
