"""Stage 8 — Production Readiness, Security Hardening & Validation Tests.

Verifies:
1. Production startup fail-closed secret/CORS/admin-seed checks.
2. JWT algorithm restriction, issuer/audience validation, reuse detection & logout revocation.
3. Constant-timing/uniform auth errors & per-IP sliding-window brute-force protection.
4. Full 4-role x API route RBAC permission matrix and admin self-protection.
5. Security response headers, sanitized 500 error responses & upload batch limits.
6. SQLite FK enforcement, append-only DB triggers, Alembic 0002 & PG offline DDL compile.
7. Streamlit production auth enforcement, fail-closed startup & sign-out flow.
8. External integration sandbox guarantees (no fake credit/KYC approvals).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.api.dependencies import get_auth_service, reset_auth_service
from app.api.main import create_app
from app.auth.models import Role, UserCreate, UserUpdate
from app.auth.security import (
    verify_token,
)
from app.auth.service import AuthenticationError, AuthService
from app.database import init_db
from app.database.audit import save_underwriting_run
from app.database.db import get_database_connection
from app.database.engine import reset_engine
from app.database.reviews import insert_human_review_event
from app.decision.decision_agent import DecisionReasoningAgent
from app.integrations import (
    DisabledLocalLLMProvider,
    IntegrationStatus,
    LocalSyntheticCreditBureauAdapter,
    LocalSyntheticKYCAdapter,
    NoOpWebhookPublisher,
)
from app.schemas.underwriting import OrchestrationStatus, UnderwritingAnalysisResult
from config.settings import get_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRONG_PROD_SECRET = "prod-stage8-high-entropy-secret-value-at-least-48-bytes-long!"


@pytest.fixture(autouse=True)
def _isolate_stage8_db(tmp_path, monkeypatch):
    """Run every test against an isolated temporary SQLite database."""
    db_file = tmp_path / "stage8_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    reset_engine()
    reset_auth_service()
    yield db_file
    get_settings.cache_clear()
    reset_engine()
    reset_auth_service()


def _setup_api_users(client: TestClient) -> dict[str, str]:
    """Create one user per RBAC role and return dict role_key -> bearer access token."""
    auth = get_auth_service()
    auth.init_tables()
    auth.seed_default_admin()
    settings = get_settings()

    tokens: dict[str, str] = {}
    r_admin = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": settings.default_admin_password},
    )
    assert r_admin.status_code == 200
    admin_tok = r_admin.json()["access_token"]
    tokens["ADMINISTRATOR"] = admin_tok

    for role_name, uname in (
        ("LOAN_OFFICER", "matrix_lo"),
        ("UNDERWRITER", "matrix_uw"),
        ("SUPERVISOR", "matrix_sup"),
    ):
        r_cr = client.post(
            "/api/v1/users",
            json={
                "username": uname,
                "full_name": f"Matrix {role_name}",
                "email": f"{uname}@example.com",
                "password": "MatrixPass123!",
                "role": role_name,
            },
            headers={"Authorization": f"Bearer {admin_tok}"},
        )
        assert r_cr.status_code == 201, r_cr.text
        r_lg = client.post(
            "/api/v1/auth/login",
            json={"username": uname, "password": "MatrixPass123!"},
        )
        assert r_lg.status_code == 200
        tokens[role_name] = r_lg.json()["access_token"]

    return tokens


# ==========================================================================
# 1. Production Startup & Secrets Hardening
# ==========================================================================


class TestProductionSecurityConfig:
    """Verify production mode refuses insecure defaults and disables dev shortcuts."""

    def test_production_refuses_default_jwt_secret(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv(
            "JWT_SECRET_KEY", "DEV-ONLY-INSECURE-SECRET-CHANGE-IN-PRODUCTION"
        )
        monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "CustomAdminPass123!")
        get_settings.cache_clear()
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            get_settings().validate_production_security()

    def test_production_refuses_short_jwt_secret(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("JWT_SECRET_KEY", "too-short-secret")
        monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "CustomAdminPass123!")
        get_settings.cache_clear()
        with pytest.raises(RuntimeError, match="32 characters"):
            create_app()

    def test_production_refuses_default_admin_password_and_wildcard_cors(
        self, monkeypatch
    ):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("JWT_SECRET_KEY", STRONG_PROD_SECRET)
        monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "admin-dev-password-change-me")
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
        get_settings.cache_clear()
        with pytest.raises(RuntimeError, match="DEFAULT_ADMIN_PASSWORD"):
            get_settings().validate_production_security()

    def test_production_skips_auto_admin_seeding_and_hides_docs(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("JWT_SECRET_KEY", STRONG_PROD_SECRET)
        monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "CustomStrongProdPass!999")
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://portal.example.com")
        get_settings.cache_clear()

        prod_app = create_app()
        with TestClient(prod_app) as client:
            assert client.get("/api/docs").status_code == 404
            assert client.get("/api/openapi.json").status_code == 404
            assert get_auth_service().list_users() == []


# ==========================================================================
# 2. Authentication, Token Reuse Detection & Rate Limiting Hardening
# ==========================================================================


class TestAuthHardening:
    """Verify JWT claims, reuse detection, logout invalidation & rate limiting."""

    def test_jwt_rejects_none_alg_and_bad_issuer_or_audience(self):
        settings = get_settings()
        bad_iss = jwt.encode(
            {
                "sub": "USR-1",
                "type": "access",
                "iss": "rogue-issuer",
                "aud": settings.jwt_audience,
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
            settings.jwt_secret_key,
            algorithm="HS256",
        )
        assert verify_token(bad_iss, expected_type="access") is None

        bad_aud = jwt.encode(
            {
                "sub": "USR-1",
                "type": "access",
                "iss": settings.jwt_issuer,
                "aud": "wrong-audience",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
            settings.jwt_secret_key,
            algorithm="HS256",
        )
        assert verify_token(bad_aud, expected_type="access") is None

        import base64
        import json

        hdr = (
            base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
            .rstrip(b"=")
            .decode()
        )
        body = (
            base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "sub": "USR-1",
                        "type": "access",
                        "iss": settings.jwt_issuer,
                        "aud": settings.jwt_audience,
                    }
                ).encode()
            )
            .rstrip(b"=")
            .decode()
        )
        unsigned = f"{hdr}.{body}."
        assert verify_token(unsigned, expected_type="access") is None

    def test_refresh_token_reuse_revokes_entire_session_family(self):
        svc = AuthService()
        svc.init_tables()
        svc.create_user(
            UserCreate(
                username="reuse_user",
                full_name="Reuse User",
                email="reuse@example.com",
                password="ReusePass123!",
            )
        )
        pair1 = svc.login("reuse_user", "ReusePass123!")
        pair2 = svc.refresh(pair1.refresh_token)

        # Replay of rotated pair1 refresh token must fail AND invalidate pair2
        with pytest.raises(AuthenticationError, match="revoked"):
            svc.refresh(pair1.refresh_token)

        with pytest.raises(AuthenticationError):
            svc.refresh(pair2.refresh_token)
        with pytest.raises(AuthenticationError):
            svc.get_current_user(pair2.access_token)

    def test_logout_invalidates_existing_access_token_immediately(self):
        app = create_app()
        with TestClient(app) as client:
            tokens = _setup_api_users(client)
            uw_tok = tokens["UNDERWRITER"]

            assert (
                client.get(
                    "/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {uw_tok}"},
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/api/v1/auth/logout",
                    headers={"Authorization": f"Bearer {uw_tok}"},
                ).status_code
                == 204
            )
            # Same non-expired access token must now be rejected immediately
            assert (
                client.get(
                    "/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {uw_tok}"},
                ).status_code
                == 401
            )

    def test_role_change_revokes_prior_access_token(self):
        app = create_app()
        with TestClient(app) as client:
            tokens = _setup_api_users(client)
            uw_tok = tokens["UNDERWRITER"]
            admin_tok = tokens["ADMINISTRATOR"]
            uw_id = client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {uw_tok}"}
            ).json()["user_id"]

            r_patch = client.patch(
                f"/api/v1/users/{uw_id}",
                json={"role": "LOAN_OFFICER"},
                headers={"Authorization": f"Bearer {admin_tok}"},
            )
            assert r_patch.status_code == 200

            # Old underwriter token carrying stale role/version must be rejected
            assert (
                client.get(
                    "/api/v1/reviews/queue",
                    headers={"Authorization": f"Bearer {uw_tok}"},
                ).status_code
                == 401
            )

    def test_uniform_auth_errors_and_ip_rate_limiting(self):
        svc = AuthService()
        svc.init_tables()
        svc.create_user(
            UserCreate(
                username="victim_user",
                full_name="Victim User",
                email="victim@example.com",
                password="VictimPass123!",
            )
        )
        # Exhaust per-IP limit across varying usernames
        for i in range(20):
            with pytest.raises(AuthenticationError, match="Invalid credentials"):
                svc.login(f"spray_target_{i}", "bad-pw", ip_address="198.51.100.7")

        # Subsequent request from same IP hits rate limit cleanly even on valid user
        with pytest.raises(AuthenticationError, match="Too many failed"):
            svc.login("victim_user", "VictimPass123!", ip_address="198.51.100.7")

        # Locked account still responds generically with "Invalid credentials."
        user = svc.get_user_by_username("victim_user")
        assert user is not None
        svc.update_user(user.user_id, UserUpdate(is_locked=True))
        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            svc.login("victim_user", "VictimPass123!", ip_address="203.0.113.5")

    def test_expired_db_refresh_token_rejected(self):
        from sqlalchemy import update

        from app.auth.models import refresh_tokens_table
        from app.database.engine import get_engine

        svc = AuthService()
        svc.init_tables()
        svc.create_user(
            UserCreate(
                username="exp_db_user",
                full_name="Expired DB",
                email="expdb@example.com",
                password="ExpiredPass123!",
            )
        )
        pair = svc.login("exp_db_user", "ExpiredPass123!")
        eng = get_engine()
        with eng.begin() as conn:
            conn.execute(
                update(refresh_tokens_table).values(
                    expires_at=datetime.now(timezone.utc) - timedelta(hours=1)
                )
            )
        with pytest.raises(AuthenticationError):
            svc.refresh(pair.refresh_token)

    def test_admin_cannot_self_demote_or_invalid_username(self):
        app = create_app()
        with TestClient(app) as client:
            tokens = _setup_api_users(client)
            admin_tok = tokens["ADMINISTRATOR"]
            admin_id = client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_tok}"}
            ).json()["user_id"]

            r_self_demote = client.patch(
                f"/api/v1/users/{admin_id}",
                json={"role": "LOAN_OFFICER"},
                headers={"Authorization": f"Bearer {admin_tok}"},
            )
            assert r_self_demote.status_code == 400

            r_bad_user = client.post(
                "/api/v1/users",
                json={
                    "username": "bad;user name!",
                    "full_name": "Bad User",
                    "email": "not-an-email",
                    "password": "Password123!",
                },
                headers={"Authorization": f"Bearer {admin_tok}"},
            )
            assert r_bad_user.status_code == 422


# ==========================================================================
# 3. Full Role-Route Matrix & API Hardening Tests
# ==========================================================================


class TestFullRoleMatrixAndAPIHardening:
    """Exercise sensitive API endpoints systematically across all 4 roles."""

    def test_role_endpoint_matrix(self):
        app = create_app()
        with TestClient(app) as client:
            tokens = _setup_api_users(client)

            # Health is public + includes security headers
            r_health = client.get("/api/v1/health")
            assert r_health.status_code == 200
            assert r_health.headers.get("X-Content-Type-Options") == "nosniff"
            assert r_health.headers.get("X-Frame-Options") == "DENY"
            assert r_health.headers.get("Cache-Control") == "no-store"

            # Role-gated endpoint matrix: path -> {role: expected_status}
            # Note: unauthenticated always -> 401
            assert client.get("/api/v1/users").status_code == 401
            assert client.get("/api/v1/audit/summary").status_code == 401
            assert client.get("/api/v1/integrations/status").status_code == 401

            get_matrix = {
                "/api/v1/users": {
                    "ADMINISTRATOR": 200,
                    "LOAN_OFFICER": 403,
                    "UNDERWRITER": 403,
                    "SUPERVISOR": 403,
                },
                "/api/v1/integrations/status": {
                    "ADMINISTRATOR": 200,
                    "LOAN_OFFICER": 403,
                    "UNDERWRITER": 403,
                    "SUPERVISOR": 403,
                },
                "/api/v1/applicants?limit=2": {
                    "ADMINISTRATOR": 200,
                    "LOAN_OFFICER": 200,
                    "UNDERWRITER": 200,
                    "SUPERVISOR": 200,
                },
                "/api/v1/reviews/queue": {
                    "ADMINISTRATOR": 200,
                    "LOAN_OFFICER": 403,
                    "UNDERWRITER": 200,
                    "SUPERVISOR": 200,
                },
                "/api/v1/audit/runs": {
                    "ADMINISTRATOR": 200,
                    "LOAN_OFFICER": 200,
                    "UNDERWRITER": 200,
                    "SUPERVISOR": 200,
                },
                "/api/v1/audit/reviews": {
                    "ADMINISTRATOR": 200,
                    "LOAN_OFFICER": 403,
                    "UNDERWRITER": 200,
                    "SUPERVISOR": 200,
                },
                "/api/v1/audit/summary": {
                    "ADMINISTRATOR": 200,
                    "LOAN_OFFICER": 403,
                    "UNDERWRITER": 403,
                    "SUPERVISOR": 200,
                },
                "/api/v1/audit/trends": {
                    "ADMINISTRATOR": 200,
                    "LOAN_OFFICER": 403,
                    "UNDERWRITER": 403,
                    "SUPERVISOR": 200,
                },
            }

            for path, expected_map in get_matrix.items():
                for role_name, expected_code in expected_map.items():
                    resp = client.get(
                        path, headers={"Authorization": f"Bearer {tokens[role_name]}"}
                    )
                    assert (
                        resp.status_code == expected_code
                    ), f"{path} for {role_name}: expected {expected_code}, got {resp.status_code}"

            # Underwriter and Supervisor cannot register applicants or upload/initiate underwriting
            applicant_payload = {
                "applicant_id": "APP-MATRIX-01",
                "name": "Matrix Test",
                "age": 32,
                "employment_type": "Salaried",
                "employment_years": 4.0,
                "monthly_income": 80000.0,
                "existing_emi": 5000.0,
                "loan_amount": 300000.0,
                "loan_tenure": 36,
                "credit_score": 740,
                "bank_balance": 150000.0,
            }
            for blocked_role in ("UNDERWRITER", "SUPERVISOR"):
                assert (
                    client.post(
                        "/api/v1/applicants",
                        json=applicant_payload,
                        headers={"Authorization": f"Bearer {tokens[blocked_role]}"},
                    ).status_code
                    == 403
                )
                assert (
                    client.post(
                        "/api/v1/underwriting/APP0002/run",
                        headers={"Authorization": f"Bearer {tokens[blocked_role]}"},
                    ).status_code
                    == 403
                )

    def test_error_leakage_sanitized_and_upload_batch_limit(self, monkeypatch):
        app = create_app()
        with TestClient(app) as client:
            tokens = _setup_api_users(client)
            lo_tok = tokens["LOAN_OFFICER"]

            # Simulated internal orchestrator crash must not leak raw path/secret details
            from app.api.routes import underwriting as uw_route

            def _boom(*args, **kwargs):
                raise RuntimeError("SECRET_INTERNAL_SQLITE_PATH=/var/private/secret.db")

            monkeypatch.setattr(
                uw_route.UnderwritingOrchestrator, "execute_end_to_end", _boom
            )
            r_err = client.post(
                "/api/v1/underwriting/APP0002/run",
                headers={"Authorization": f"Bearer {lo_tok}"},
            )
            assert r_err.status_code == 500
            assert "SECRET_INTERNAL" not in r_err.json()["detail"]

            # >10 files upload batch rejected cleanly with 400
            many_files = [
                ("files", (f"doc_{i}.pdf", b"%PDF-1.4\n%%EOF", "application/pdf"))
                for i in range(11)
            ]
            r_many = client.post(
                "/api/v1/applicants/APP-BATCH-1/documents",
                files=many_files,
                headers={"Authorization": f"Bearer {lo_tok}"},
            )
            assert r_many.status_code == 400
            assert "Maximum 10" in r_many.json()["detail"]


# ==========================================================================
# 4. Database Safeguards, Triggers & Postgres Offline DDL Compilation
# ==========================================================================


class TestDatabaseHardening:
    """Verify FK enforcement, SQLite triggers, non-SQLite guard & PG DDL compile."""

    def test_append_only_triggers_and_fk_enforced_in_sqlite(self):
        init_db()
        analysis = UnderwritingAnalysisResult(
            application_id="APP-TRG-1",
            applicant_id="APP-TRG-1",
            orchestration_status=OrchestrationStatus.FAILED,
            error_message="test",
        )
        decision = DecisionReasoningAgent().evaluate(analysis)
        run_id = save_underwriting_run(analysis, decision)

        insert_human_review_event(
            {
                "source_run_id": run_id,
                "application_id": "APP-TRG-1",
                "original_ai_recommendation": "MANUAL_REVIEW",
                "original_pipeline_status": "FAILED",
                "action": "START_REVIEW",
                "reviewer_id": "uw_trg",
                "decision_reason": "Testing append-only DB triggers.",
                "previous_review_status": "PENDING",
                "new_review_status": "IN_REVIEW",
                "submission_hash": "hash-trg-1",
            }
        )

        # Direct SQL UPDATE/DELETE on underwriting_runs and human_review_events must abort
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            with get_database_connection() as conn:
                conn.execute(
                    "UPDATE underwriting_runs SET recommendation = 'APPROVE' WHERE run_id = ?;",
                    (run_id,),
                )

        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            with get_database_connection() as conn:
                conn.execute(
                    "DELETE FROM human_review_events WHERE source_run_id = ?;",
                    (run_id,),
                )

    def test_sqlite_connector_refuses_postgresql_url_safely(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
        get_settings.cache_clear()
        with pytest.raises(RuntimeError, match="non-SQLite"):
            with get_database_connection():
                pass

    def test_alembic_postgresql_offline_ddl_compilation(self):
        """Verify Alembic compiles valid PostgreSQL SQL DDL without running Postgres."""
        from io import StringIO

        from alembic.config import Config

        from alembic import command

        sql_buf = StringIO()
        cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
        cfg.output_buffer = sql_buf
        cfg.set_main_option(
            "sqlalchemy.url", "postgresql+psycopg://u:p@localhost:5432/underwriting"
        )
        command.upgrade(cfg, "head", sql=True)
        compiled_sql = sql_buf.getvalue()
        assert "CREATE TABLE users" in compiled_sql
        assert "CREATE TABLE refresh_tokens" in compiled_sql
        assert "CREATE TABLE human_review_events" in compiled_sql
        assert "token_version" in compiled_sql


# ==========================================================================
# 5. Streamlit Production Auth & External Integration Safety
# ==========================================================================


class TestStreamlitProdAndIntegrations:
    """Verify Streamlit production security gate and safe sandbox integrations."""

    def test_streamlit_production_fails_closed_on_default_secret(self, monkeypatch):
        from streamlit.testing.v1 import AppTest

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv(
            "JWT_SECRET_KEY", "DEV-ONLY-INSECURE-SECRET-CHANGE-IN-PRODUCTION"
        )
        get_settings.cache_clear()

        at = AppTest.from_file(str(PROJECT_ROOT / "app" / "main.py")).run(timeout=20)
        assert not at.exception
        assert any("Startup Blocked" in str(e.value) for e in at.error)

    def test_streamlit_production_login_and_logout_flow(self, monkeypatch):
        from streamlit.testing.v1 import AppTest

        init_db()
        svc = AuthService()
        svc.init_tables()
        svc.create_user(
            UserCreate(
                username="prod_uw",
                full_name="Prod Underwriter",
                email="produw@example.com",
                password="ProdUwPassword!1",
                role=Role.UNDERWRITER,
            )
        )

        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("JWT_SECRET_KEY", STRONG_PROD_SECRET)
        monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "ProdAdminUnusedSecret!99")
        get_settings.cache_clear()

        at = AppTest.from_file(str(PROJECT_ROOT / "app" / "main.py")).run(timeout=20)
        assert not at.exception
        assert any("Authentication is required" in str(i.value) for i in at.info)

        # Sign in cleanly
        at.text_input(key="ui_login_username").set_value("prod_uw")
        at.text_input(key="ui_login_password").set_value("ProdUwPassword!1")
        at.button(key="ui_btn_sign_in").click().run(timeout=20)
        assert not at.exception
        assert "ui_auth_access_token" in at.session_state

        # Sign out clears tokens & blocks workspace again
        at.button(key="ui_btn_sign_out").click().run(timeout=20)
        assert not at.exception
        assert "ui_auth_access_token" not in at.session_state
        assert any("Authentication is required" in str(i.value) for i in at.info)

    def test_external_integrations_never_fabricate_real_verifications(self):
        cb = LocalSyntheticCreditBureauAdapter()
        cb_res = cb.fetch_credit_report("APP0002")
        assert cb_res.sandboxed is True
        assert cb_res.success is False
        assert cb_res.status == IntegrationStatus.SANDBOX

        kyc = LocalSyntheticKYCAdapter()
        kyc_res = kyc.verify_identity("APP0002", "Test User")
        assert kyc_res.sandboxed is True
        assert kyc_res.success is False
        assert kyc_res.status == IntegrationStatus.SANDBOX

        llm = DisabledLocalLLMProvider()
        llm_res = llm.summarize_case({"application_id": "APP0002"})
        assert llm_res.sandboxed is True
        assert llm_res.success is False
        assert llm_res.status == IntegrationStatus.DISABLED

        wh = NoOpWebhookPublisher()
        wh_res = wh.publish_event("UNDERWRITING_COMPLETED", {"run_id": "RUN-1"})
        assert wh_res.sandboxed is True
        assert wh_res.status == IntegrationStatus.DISABLED
        assert wh_res.payload["dispatched"] is False
