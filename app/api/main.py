"""FastAPI application entry point.

Creates the versioned API application with production-hardened CORS, security
response headers, startup validation, lifespan initialization, and /api/v1 routes.

Launch:
    uvicorn app.api.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.dependencies import get_auth_service
from app.api.routes import (
    applicants,
    audit,
    auth,
    documents,
    integrations,
    reviews,
    underwriting,
    users,
)
from app.database import init_db
from app.utils.helpers import get_logger, setup_logging
from config.settings import get_settings

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle."""
    setup_logging()
    settings = get_settings()
    settings.validate_production_security()
    logger.info("Starting API server in '%s' mode.", settings.app_env)

    # Initialize legacy SQLite tables (underwriting_runs, etc.) when running on SQLite
    if settings.database_url.startswith("sqlite"):
        init_db()

    # Initialize auth tables; auto-seed dev admin ONLY outside production
    auth_svc = get_auth_service()
    seeded = auth_svc.seed_default_admin()
    if seeded:
        logger.info(
            "Default development admin user seeded (username='admin'). "
            "Never deploy with default credentials."
        )

    yield  # Application is running

    logger.info("API server shutting down.")


def create_app() -> FastAPI:
    """Factory function creating the configured FastAPI application."""
    settings = get_settings()
    settings.validate_production_security()
    is_dev = settings.app_env.strip().lower() == "development"

    application = FastAPI(
        title="AI Loan Underwriting Assistant API",
        description="Backend API for the AI Loan Underwriting Assistant with authentication, RBAC, and audit.",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs" if is_dev else None,
        redoc_url="/api/redoc" if is_dev else None,
        openapi_url="/api/openapi.json" if is_dev else None,
    )

    cors_origins = settings.get_cors_origins()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=bool(cors_origins) and "*" not in cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @application.middleware("http")
    async def add_security_headers(request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    # Register versioned route groups
    application.include_router(
        auth.router, prefix="/api/v1/auth", tags=["Authentication"]
    )
    application.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
    application.include_router(
        applicants.router, prefix="/api/v1/applicants", tags=["Applicants"]
    )
    application.include_router(
        documents.router, prefix="/api/v1/applicants", tags=["Documents"]
    )
    application.include_router(
        underwriting.router, prefix="/api/v1/underwriting", tags=["Underwriting"]
    )
    application.include_router(
        reviews.router, prefix="/api/v1/reviews", tags=["Reviews"]
    )
    application.include_router(audit.router, prefix="/api/v1/audit", tags=["Audit"])
    application.include_router(
        integrations.router, prefix="/api/v1/integrations", tags=["Integrations"]
    )

    @application.get("/api/v1/health", tags=["Health"])
    async def health_check() -> dict:
        return {"status": "ok", "version": "1.0.0"}

    return application


app = create_app()
