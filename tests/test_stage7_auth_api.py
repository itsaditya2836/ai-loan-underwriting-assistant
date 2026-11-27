"""Stage 7 — Authentication, RBAC, and API Tests.

Tests:
1. Password hashing (Argon2id) and JWT token lifecycle.
2. User CRUD and default admin seeding.
3. Login, refresh, logout, and rate limiting.
4. RBAC permission matrix coverage.
5. Maker-Checker constraints.
6. FastAPI endpoint integration tests (TestClient).
7. Authenticated reviewer identity in human review submissions.
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Dict

import pytest
from fastapi.testclient import TestClient

# --- Ensure isolated test database ---
_TEST_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "test_stage7.db")
_TEST_DB_URL = f"sqlite:///{os.path.abspath(_TEST_DB_PATH)}"
os.environ["DATABASE_URL"] = _TEST_DB_URL

# Clear settings cache to pick up test DATABASE_URL
from config.settings import get_settings  # noqa: E402

get_settings.cache_clear()

from app.auth.models import Role, UserCreate, UserUpdate  # noqa: E402
from app.auth.permissions import (  # noqa: E402
    MakerCheckerError,
    Permission,
    check_permission,
    enforce_correction_requires_supervisor,
    enforce_not_self_review,
    get_role_permissions,
)
from app.auth.security import (  # noqa: E402
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    verify_password,
    verify_token,
)
from app.auth.service import (  # noqa: E402
    AuthenticationError,
    AuthService,
    reset_engine,
)


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path):
    """Create a fresh isolated database for each test."""
    db_path = str(tmp_path / "test.db")
    db_url = f"sqlite:///{db_path}"
    os.environ["DATABASE_URL"] = db_url
    get_settings.cache_clear()
    reset_engine()

    # Reset API service cache
    from app.api.dependencies import reset_auth_service

    reset_auth_service()

    yield

    # Cleanup
    get_settings.cache_clear()
    reset_engine()
    if os.path.exists(db_path):
        os.remove(db_path)


def _make_auth_service(tmp_path=None) -> AuthService:
    """Create an AuthService connected to the test database."""
    svc = AuthService()
    svc.init_tables()
    return svc


# ==========================================================================
# 1. Password Hashing Tests
# ==========================================================================


class TestPasswordHashing:
    """Argon2id password hashing and verification."""

    def test_hash_and_verify(self):
        pw = "SecurePass123!"
        hashed = hash_password(pw)
        assert hashed != pw
        assert "$argon2id$" in hashed
        assert verify_password(pw, hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("correct-password")
        assert not verify_password("wrong-password", hashed)

    def test_different_hashes_for_same_password(self):
        """Salt randomization ensures different hashes."""
        h1 = hash_password("SamePassword")
        h2 = hash_password("SamePassword")
        assert h1 != h2
        assert verify_password("SamePassword", h1)
        assert verify_password("SamePassword", h2)


# ==========================================================================
# 2. JWT Token Tests
# ==========================================================================


class TestJWTTokens:
    """JWT creation and verification."""

    def test_create_and_verify_access_token(self):
        token = create_access_token({"sub": "user-123", "role": "UNDERWRITER"})
        claims = verify_token(token, expected_type="access")
        assert claims is not None
        assert claims["sub"] == "user-123"
        assert claims["role"] == "UNDERWRITER"
        assert claims["type"] == "access"

    def test_create_and_verify_refresh_token(self):
        token = create_refresh_token({"sub": "user-456"})
        claims = verify_token(token, expected_type="refresh")
        assert claims is not None
        assert claims["sub"] == "user-456"
        assert claims["type"] == "refresh"

    def test_access_token_rejected_as_refresh(self):
        token = create_access_token({"sub": "user-789"})
        claims = verify_token(token, expected_type="refresh")
        assert claims is None

    def test_expired_token_rejected(self):
        token = create_access_token(
            {"sub": "user-exp"},
            expires_delta=timedelta(seconds=-1),
        )
        claims = verify_token(token)
        assert claims is None

    def test_invalid_token_string(self):
        claims = verify_token("not-a-valid-jwt-token")
        assert claims is None

    def test_hash_token_deterministic(self):
        h1 = hash_token("some-refresh-token")
        h2 = hash_token("some-refresh-token")
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex


# ==========================================================================
# 3. RBAC Permission Matrix Tests
# ==========================================================================


class TestRBACPermissions:
    """Role-based access control permission matrix."""

    def test_administrator_has_all_permissions(self):
        perms = get_role_permissions(Role.ADMINISTRATOR)
        for p in Permission:
            assert p in perms, f"Admin missing {p.value}"

    def test_loan_officer_permissions(self):
        perms = get_role_permissions(Role.LOAN_OFFICER)
        assert Permission.APPLICANT_CREATE in perms
        assert Permission.DOCUMENT_UPLOAD in perms
        assert Permission.UNDERWRITING_INITIATE in perms
        assert Permission.REVIEW_SUBMIT_DECISION not in perms
        assert Permission.USER_CREATE not in perms
        assert Permission.REVIEW_CORRECT_DECISION not in perms

    def test_underwriter_permissions(self):
        perms = get_role_permissions(Role.UNDERWRITER)
        assert Permission.REVIEW_SUBMIT_DECISION in perms
        assert Permission.REVIEW_REQUEST_INFO in perms
        assert Permission.REVIEW_RETURN_INVESTIGATION in perms
        assert Permission.REVIEW_CORRECT_DECISION not in perms
        assert Permission.APPLICANT_CREATE not in perms
        assert Permission.USER_CREATE not in perms

    def test_supervisor_permissions(self):
        perms = get_role_permissions(Role.SUPERVISOR)
        assert Permission.REVIEW_CORRECT_DECISION in perms
        assert Permission.REVIEW_VIEW_ALL in perms
        assert Permission.AUDIT_VIEW_ALL in perms
        assert Permission.USER_CREATE not in perms

    def test_check_permission_function(self):
        assert check_permission(Role.ADMINISTRATOR, Permission.USER_CREATE)
        assert not check_permission(Role.LOAN_OFFICER, Permission.USER_CREATE)
        assert check_permission(Role.UNDERWRITER, Permission.REVIEW_SUBMIT_DECISION)
        assert not check_permission(
            Role.UNDERWRITER, Permission.REVIEW_CORRECT_DECISION
        )


# ==========================================================================
# 4. Maker-Checker Tests
# ==========================================================================


class TestMakerChecker:
    """Maker-Checker constraint enforcement."""

    def test_self_review_blocked(self):
        with pytest.raises(MakerCheckerError, match="cannot review"):
            enforce_not_self_review("USR-abc", "USR-abc", operation="review")

    def test_different_users_allowed(self):
        # Should not raise
        enforce_not_self_review("USR-abc", "USR-xyz", operation="review")

    def test_none_submitter_allowed(self):
        # Should not raise when submitter is unknown
        enforce_not_self_review("USR-abc", None, operation="review")

    def test_correction_requires_supervisor(self):
        with pytest.raises(MakerCheckerError, match="Supervisor"):
            enforce_correction_requires_supervisor(Role.UNDERWRITER)

        with pytest.raises(MakerCheckerError, match="Supervisor"):
            enforce_correction_requires_supervisor(Role.LOAN_OFFICER)

    def test_correction_allowed_for_supervisor(self):
        # Should not raise
        enforce_correction_requires_supervisor(Role.SUPERVISOR)
        enforce_correction_requires_supervisor(Role.ADMINISTRATOR)


# ==========================================================================
# 5. AuthService Tests
# ==========================================================================


class TestAuthService:
    """User management and authentication service."""

    def test_create_user(self, tmp_path):
        svc = _make_auth_service(tmp_path)
        user = svc.create_user(
            UserCreate(
                username="testuser",
                full_name="Test User",
                email="test@example.com",
                password="SecurePass123!",
                role=Role.LOAN_OFFICER,
            )
        )
        assert user.username == "testuser"
        assert user.role == Role.LOAN_OFFICER
        assert user.is_active is True

    def test_duplicate_username_rejected(self, tmp_path):
        svc = _make_auth_service(tmp_path)
        svc.create_user(
            UserCreate(
                username="dupuser",
                full_name="User One",
                email="one@example.com",
                password="Password123!",
            )
        )
        with pytest.raises(ValueError, match="already exists"):
            svc.create_user(
                UserCreate(
                    username="dupuser",
                    full_name="User Two",
                    email="two@example.com",
                    password="Password123!",
                )
            )

    def test_login_success(self, tmp_path):
        svc = _make_auth_service(tmp_path)
        svc.create_user(
            UserCreate(
                username="loginuser",
                full_name="Login User",
                email="login@example.com",
                password="MyPassword1!",
                role=Role.UNDERWRITER,
            )
        )
        tokens = svc.login("loginuser", "MyPassword1!")
        assert tokens.access_token
        assert tokens.refresh_token
        assert tokens.token_type == "bearer"
        assert tokens.expires_in > 0

    def test_login_wrong_password(self, tmp_path):
        svc = _make_auth_service(tmp_path)
        svc.create_user(
            UserCreate(
                username="wrongpw",
                full_name="Wrong PW",
                email="wrong@example.com",
                password="CorrectPassword1!",
            )
        )
        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            svc.login("wrongpw", "WrongPassword!")

    def test_login_nonexistent_user(self, tmp_path):
        svc = _make_auth_service(tmp_path)
        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            svc.login("nobody", "password")

    def test_refresh_token_rotation(self, tmp_path):
        svc = _make_auth_service(tmp_path)
        svc.create_user(
            UserCreate(
                username="refreshuser",
                full_name="Refresh User",
                email="refresh@example.com",
                password="RefreshPass1!",
            )
        )
        tokens1 = svc.login("refreshuser", "RefreshPass1!")
        tokens2 = svc.refresh(tokens1.refresh_token)
        assert tokens2.access_token != tokens1.access_token
        assert tokens2.refresh_token != tokens1.refresh_token

        # Old refresh token should be revoked
        with pytest.raises(AuthenticationError, match="not found or revoked"):
            svc.refresh(tokens1.refresh_token)

    def test_logout_revokes_tokens(self, tmp_path):
        svc = _make_auth_service(tmp_path)
        svc.create_user(
            UserCreate(
                username="logoutuser",
                full_name="Logout User",
                email="logout@example.com",
                password="LogoutPass1!",
            )
        )
        tokens = svc.login("logoutuser", "LogoutPass1!")
        user = svc.get_current_user(tokens.access_token)
        svc.logout(user.user_id)

        # Refresh should fail after logout
        with pytest.raises(AuthenticationError):
            svc.refresh(tokens.refresh_token)

    def test_get_current_user_from_token(self, tmp_path):
        svc = _make_auth_service(tmp_path)
        svc.create_user(
            UserCreate(
                username="currentuser",
                full_name="Current User",
                email="current@example.com",
                password="CurrentPass1!",
                role=Role.SUPERVISOR,
            )
        )
        tokens = svc.login("currentuser", "CurrentPass1!")
        user = svc.get_current_user(tokens.access_token)
        assert user.username == "currentuser"
        assert user.role == Role.SUPERVISOR

    def test_seed_default_admin(self, tmp_path):
        svc = _make_auth_service(tmp_path)
        admin = svc.seed_default_admin()
        assert admin is not None
        assert admin.username == "admin"
        assert admin.role == Role.ADMINISTRATOR

        # Second call should return None (users already exist)
        admin2 = svc.seed_default_admin()
        assert admin2 is None

    def test_update_user(self, tmp_path):
        svc = _make_auth_service(tmp_path)
        created = svc.create_user(
            UserCreate(
                username="updateuser",
                full_name="Before Update",
                email="before@example.com",
                password="UpdatePass1!",
                role=Role.LOAN_OFFICER,
            )
        )
        updated = svc.update_user(
            created.user_id,
            UserUpdate(full_name="After Update", role=Role.UNDERWRITER),
        )
        assert updated is not None
        assert updated.full_name == "After Update"
        assert updated.role == Role.UNDERWRITER

    def test_deactivate_user(self, tmp_path):
        svc = _make_auth_service(tmp_path)
        created = svc.create_user(
            UserCreate(
                username="deactivateuser",
                full_name="Deactivate Me",
                email="deactivate@example.com",
                password="DeactivatePass1!",
            )
        )
        result = svc.deactivate_user(created.user_id)
        assert result is not None
        assert result.is_active is False

        # Login should fail for deactivated user
        with pytest.raises(AuthenticationError, match="Invalid credentials"):
            svc.login("deactivateuser", "DeactivatePass1!")

    def test_account_lockout_after_max_attempts(self, tmp_path):
        svc = _make_auth_service(tmp_path)
        svc.create_user(
            UserCreate(
                username="lockuser",
                full_name="Lock User",
                email="lock@example.com",
                password="LockPass1!",
            )
        )
        # Attempt wrong password many times (default max=10)
        for _ in range(10):
            with pytest.raises(AuthenticationError):
                svc.login("lockuser", "wrong")

        # Account should now be locked
        user = svc.get_user_by_username("lockuser")
        assert user is not None
        assert user.is_locked is True


# ==========================================================================
# 6. FastAPI Endpoint Integration Tests
# ==========================================================================


class TestAPIEndpoints:
    """FastAPI endpoint tests via TestClient."""

    def _get_client(self) -> TestClient:
        from app.api.dependencies import reset_auth_service

        reset_auth_service()

        from app.api.main import create_app

        test_app = create_app()
        return TestClient(test_app)

    def _login_admin(self, client: TestClient) -> str:
        """Create admin and log in, return access token."""
        from app.api.dependencies import get_auth_service

        auth = get_auth_service()
        auth.seed_default_admin()

        settings = get_settings()
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": settings.default_admin_password},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["access_token"]

    def _auth_header(self, token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_health_check(self):
        client = self._get_client()
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_login_endpoint(self):
        client = self._get_client()
        token = self._login_admin(client)
        assert token

    def test_me_endpoint(self):
        client = self._get_client()
        token = self._login_admin(client)
        resp = client.get("/api/v1/auth/me", headers=self._auth_header(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "admin"
        assert data["role"] == "ADMINISTRATOR"
        assert "password_hash" not in data

    def test_unauthenticated_request_rejected(self):
        client = self._get_client()
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    def test_create_user_endpoint(self):
        client = self._get_client()
        admin_token = self._login_admin(client)

        resp = client.post(
            "/api/v1/users",
            json={
                "username": "newuser",
                "full_name": "New User",
                "email": "new@example.com",
                "password": "NewPass123!",
                "role": "UNDERWRITER",
            },
            headers=self._auth_header(admin_token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["role"] == "UNDERWRITER"

    def test_non_admin_cannot_create_user(self):
        client = self._get_client()
        admin_token = self._login_admin(client)

        # Create a loan officer
        client.post(
            "/api/v1/users",
            json={
                "username": "officer",
                "full_name": "Officer",
                "email": "officer@example.com",
                "password": "OfficerPass1!",
                "role": "LOAN_OFFICER",
            },
            headers=self._auth_header(admin_token),
        )

        # Login as loan officer
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "officer", "password": "OfficerPass1!"},
        )
        officer_token = resp.json()["access_token"]

        # Attempt user creation - should fail
        resp = client.post(
            "/api/v1/users",
            json={
                "username": "hacker",
                "full_name": "Hacker",
                "email": "hack@example.com",
                "password": "HackPass1!",
            },
            headers=self._auth_header(officer_token),
        )
        assert resp.status_code == 403

    def test_list_users_endpoint(self):
        client = self._get_client()
        admin_token = self._login_admin(client)
        resp = client.get("/api/v1/users", headers=self._auth_header(admin_token))
        assert resp.status_code == 200
        users = resp.json()
        assert len(users) >= 1
        assert users[0]["username"] == "admin"

    def test_refresh_endpoint(self):
        client = self._get_client()
        from app.api.dependencies import get_auth_service

        auth = get_auth_service()
        auth.seed_default_admin()

        settings = get_settings()
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": settings.default_admin_password},
        )
        refresh_tok = login_resp.json()["refresh_token"]

        refresh_resp = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_tok},
        )
        assert refresh_resp.status_code == 200
        new_tokens = refresh_resp.json()
        assert new_tokens["access_token"]
        assert new_tokens["refresh_token"] != refresh_tok

    def test_logout_endpoint(self):
        client = self._get_client()
        admin_token = self._login_admin(client)

        # Logout
        resp = client.post(
            "/api/v1/auth/logout",
            headers=self._auth_header(admin_token),
        )
        assert resp.status_code == 204

    def test_applicants_list_endpoint(self):
        client = self._get_client()
        admin_token = self._login_admin(client)
        resp = client.get(
            "/api/v1/applicants?limit=5",
            headers=self._auth_header(admin_token),
        )
        assert resp.status_code == 200

    def test_audit_runs_endpoint(self):
        client = self._get_client()
        admin_token = self._login_admin(client)
        resp = client.get(
            "/api/v1/audit/runs?limit=5",
            headers=self._auth_header(admin_token),
        )
        assert resp.status_code == 200

    def test_review_queue_rbac(self):
        """Loan officers should not access the review queue."""
        client = self._get_client()
        admin_token = self._login_admin(client)

        # Create loan officer
        client.post(
            "/api/v1/users",
            json={
                "username": "loanofficer",
                "full_name": "Loan Officer",
                "email": "lo@example.com",
                "password": "LOPass123!",
                "role": "LOAN_OFFICER",
            },
            headers=self._auth_header(admin_token),
        )
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "loanofficer", "password": "LOPass123!"},
        )
        lo_token = resp.json()["access_token"]

        # Loan officer cannot view review queue
        resp = client.get(
            "/api/v1/reviews/queue",
            headers=self._auth_header(lo_token),
        )
        assert resp.status_code == 403

    def test_review_submit_uses_authenticated_identity(self):
        """Verify that the reviewer_id comes from the token, not the request body."""
        client = self._get_client()
        admin_token = self._login_admin(client)

        # Create underwriter
        client.post(
            "/api/v1/users",
            json={
                "username": "reviewer1",
                "full_name": "Reviewer One",
                "email": "rev1@example.com",
                "password": "RevPass123!",
                "role": "UNDERWRITER",
            },
            headers=self._auth_header(admin_token),
        )
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "reviewer1", "password": "RevPass123!"},
        )
        rev_token = resp.json()["access_token"]

        # Attempt review submission (will fail because no run exists, but
        # validates that the endpoint is wired correctly)
        resp = client.post(
            "/api/v1/reviews/submit",
            json={
                "source_run_id": "RUN-NONEXISTENT-123",
                "application_id": "APP0001",
                "action": "START_REVIEW",
                "decision_reason": "Starting review of this application",
                "confirmed": True,
            },
            headers=self._auth_header(rev_token),
        )
        # Should fail with 400 because run doesn't exist, NOT 403
        assert resp.status_code == 400
        assert "does not exist" in resp.json()["detail"]

    def _create_user_and_login(
        self,
        client: TestClient,
        admin_token: str,
        username: str,
        role: str,
        password: str = "StrongPass123!",
    ) -> tuple[str, str]:
        """Helper to create a role-specific user and return (user_id, access_token)."""
        create_resp = client.post(
            "/api/v1/users",
            json={
                "username": username,
                "full_name": f"{username} Display",
                "email": f"{username}@example.com",
                "password": password,
                "role": role,
            },
            headers=self._auth_header(admin_token),
        )
        assert create_resp.status_code == 201, create_resp.text
        user_id = create_resp.json()["user_id"]

        login_resp = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        assert login_resp.status_code == 200, login_resp.text
        return user_id, login_resp.json()["access_token"]

    def test_end_to_end_rbac_maker_checker_and_authoritative_attribution(
        self, tmp_path, monkeypatch
    ):
        """Exercise full API lifecycle across Officer, Underwriter, Supervisor with Maker-Checker."""
        from pathlib import Path

        from app.api.routes import documents as docs_route

        monkeypatch.setattr(
            docs_route, "DOCUMENTS_BASE_DIR", str(tmp_path / "uploaded_docs")
        )
        client = self._get_client()
        admin_token = self._login_admin(client)

        lo_id, lo_token = self._create_user_and_login(
            client, admin_token, "officer_a", "LOAN_OFFICER"
        )
        _lo2_id, lo2_token = self._create_user_and_login(
            client, admin_token, "officer_b", "LOAN_OFFICER"
        )
        uw_id, uw_token = self._create_user_and_login(
            client, admin_token, "uw_a", "UNDERWRITER"
        )
        sup_id, sup_token = self._create_user_and_login(
            client, admin_token, "sup_a", "SUPERVISOR"
        )

        # 1. Loan Officer creates an applicant (ownership recorded)
        app_id = "APP-API-MC-001"
        app_payload = {
            "applicant_id": app_id,
            "name": "Meera Nair",
            "age": 34,
            "employment_type": "Salaried",
            "employment_years": 6.0,
            "monthly_income": 95000.0,
            "existing_emi": 10000.0,
            "loan_amount": 350000.0,
            "loan_tenure": 36,
            "credit_score": 760,
            "bank_balance": 200000.0,
        }
        r_create = client.post(
            "/api/v1/applicants",
            json=app_payload,
            headers=self._auth_header(lo_token),
        )
        assert r_create.status_code == 201, r_create.text
        assert r_create.json()["submitted_by_user_id"] == lo_id

        # 2. Officer B cannot access Officer A's private application (403)
        r_other = client.get(
            f"/api/v1/applicants/{app_id}",
            headers=self._auth_header(lo2_token),
        )
        assert r_other.status_code == 403

        # 3. Document upload rejects path traversal & fake non-PDF, accepts genuine PDF
        r_bad_pdf = client.post(
            f"/api/v1/applicants/{app_id}/documents",
            files=[("files", ("not_a_pdf.txt", b"hello", "text/plain"))],
            headers=self._auth_header(lo_token),
        )
        assert r_bad_pdf.status_code == 400

        r_trav = client.post(
            f"/api/v1/applicants/{app_id}/documents",
            files=[("files", ("../../evil.pdf", b"%PDF-1.4\n%", "application/pdf"))],
            headers=self._auth_header(lo_token),
        )
        assert r_trav.status_code == 400

        sample_pdf = (
            Path(__file__).resolve().parent.parent
            / "data"
            / "documents"
            / "APP0002"
            / "loan_application.pdf"
        ).read_bytes()
        r_good_pdf = client.post(
            f"/api/v1/applicants/{app_id}/documents",
            files=[("files", ("loan_application.pdf", sample_pdf, "application/pdf"))],
            headers=self._auth_header(lo_token),
        )
        assert r_good_pdf.status_code == 201, r_good_pdf.text
        assert r_good_pdf.json()["uploaded"] == 1

        # 4. Loan Officer initiates underwriting -> records initiated_by_user_id
        r_run = client.post(
            f"/api/v1/underwriting/{app_id}/run",
            headers=self._auth_header(lo_token),
        )
        assert r_run.status_code == 201, r_run.text
        run_id = r_run.json()["run_id"]
        assert r_run.json()["initiated_by"] == lo_id
        assert r_run.json()["initiated_by_username"] == "officer_a"

        # Officer B cannot inspect Officer A's underwriting run
        r_run_other = client.get(
            f"/api/v1/underwriting/{run_id}",
            headers=self._auth_header(lo2_token),
        )
        assert r_run_other.status_code == 403

        # 5. Client attempting to spoof reviewer_id in request body is rejected (422)
        r_spoof = client.post(
            "/api/v1/reviews/submit",
            json={
                "source_run_id": run_id,
                "application_id": app_id,
                "action": "APPROVE",
                "reviewer_id": "FAKE_ADMIN",
                "decision_reason": "Attempting reviewer spoofing attack",
                "confirmed": True,
            },
            headers=self._auth_header(uw_token),
        )
        assert r_spoof.status_code == 422

        # 6. Admin self-submitted application cannot be approved by same admin (Maker-Checker!)
        admin_app_id = "APP-API-MC-ADMIN"
        client.post(
            "/api/v1/applicants",
            json={**app_payload, "applicant_id": admin_app_id},
            headers=self._auth_header(admin_token),
        )
        r_admin_run = client.post(
            f"/api/v1/underwriting/{admin_app_id}/run",
            headers=self._auth_header(admin_token),
        )
        admin_run_id = r_admin_run.json()["run_id"]
        r_self_review = client.post(
            "/api/v1/reviews/submit",
            json={
                "source_run_id": admin_run_id,
                "application_id": admin_app_id,
                "action": "APPROVE",
                "decision_reason": "Trying to self-approve my own submission",
                "confirmed": True,
            },
            headers=self._auth_header(admin_token),
        )
        assert r_self_review.status_code == 403
        assert "Maker-Checker violation" in r_self_review.json()["detail"]

        # 7. Underwriter reviews Officer A's run -> optimistic concurrency check works
        r_stale = client.post(
            "/api/v1/reviews/submit",
            json={
                "source_run_id": run_id,
                "application_id": app_id,
                "action": "APPROVE",
                "expected_previous_status": "IN_REVIEW",  # actual is PENDING
                "decision_reason": "Approving with stale expected state",
                "confirmed": True,
            },
            headers=self._auth_header(uw_token),
        )
        assert r_stale.status_code == 409

        # Valid underwriter approval records full authenticated identity + role
        r_uw = client.post(
            "/api/v1/reviews/submit",
            json={
                "source_run_id": run_id,
                "application_id": app_id,
                "action": "APPROVE",
                "expected_previous_status": "PENDING",
                "decision_reason": "All policy and risk metrics verified cleanly.",
                "confirmed": True,
            },
            headers=self._auth_header(uw_token),
        )
        assert r_uw.status_code == 200, r_uw.text
        ev = r_uw.json()["event"]
        assert ev["reviewer_user_id"] == uw_id
        assert ev["reviewer_username"] == "uw_a"
        assert ev["reviewer_role"] == "UNDERWRITER"

        # 8. Underwriter cannot submit linked correction (Supervisor only)
        r_uw_corr = client.post(
            "/api/v1/reviews/submit",
            json={
                "source_run_id": run_id,
                "application_id": app_id,
                "action": "REJECT",
                "is_correction": True,
                "parent_review_id": ev["review_id"],
                "correction_explanation": "Trying unauthorized correction.",
                "decision_reason": "Unauthorized correction attempt.",
                "confirmed": True,
            },
            headers=self._auth_header(uw_token),
        )
        assert r_uw_corr.status_code == 403

        # 9. Supervisor performs linked correction cleanly
        r_sup_corr = client.post(
            "/api/v1/reviews/submit",
            json={
                "source_run_id": run_id,
                "application_id": app_id,
                "action": "REJECT",
                "is_correction": True,
                "parent_review_id": ev["review_id"],
                "correction_explanation": "Supervisor audit found undisclosed obligation.",
                "decision_reason": "Supervisor override correction documented.",
                "expected_previous_status": "APPROVED",
                "confirmed": True,
            },
            headers=self._auth_header(sup_token),
        )
        assert r_sup_corr.status_code == 200, r_sup_corr.text
        corr_ev = r_sup_corr.json()["event"]
        assert corr_ev["reviewer_user_id"] == sup_id
        assert corr_ev["reviewer_role"] == "SUPERVISOR"
        assert corr_ev["parent_review_id"] == ev["review_id"]

    def test_integrations_status_and_admin_unlock(self):
        """Verify admin-only integration status endpoint and user account unlock."""
        client = self._get_client()
        admin_token = self._login_admin(client)
        _uw_id, uw_token = self._create_user_and_login(
            client, admin_token, "uw_int", "UNDERWRITER"
        )
        locked_id, _ = self._create_user_and_login(
            client, admin_token, "locked_target", "LOAN_OFFICER"
        )

        # Non-admin denied access to integrations status
        assert (
            client.get(
                "/api/v1/integrations/status", headers=self._auth_header(uw_token)
            ).status_code
            == 403
        )
        r_int = client.get(
            "/api/v1/integrations/status", headers=self._auth_header(admin_token)
        )
        assert r_int.status_code == 200
        names = {item["service_name"] for item in r_int.json()}
        assert {
            "credit_bureau",
            "kyc_provider",
            "llm_reasoning",
            "audit_webhook",
        } <= names

        # Admin unlocks account cleanly
        for _ in range(10):
            client.post(
                "/api/v1/auth/login",
                json={"username": "locked_target", "password": "wrong"},
            )
        r_unlock = client.patch(
            f"/api/v1/users/{locked_id}",
            json={"is_locked": False},
            headers=self._auth_header(admin_token),
        )
        assert r_unlock.status_code == 200
        assert r_unlock.json()["is_locked"] is False


# ==========================================================================
# 7. Database Architecture, Alembic & Non-Destructive Migration Tests
# ==========================================================================


class TestDatabaseArchitectureAndMigrations:
    """Verify pooling config, concurrency lock, non-destructive migration & UI auth."""

    def test_postgresql_pooling_configuration(self):
        from app.database.engine import _build_engine_kwargs

        pg_kwargs = _build_engine_kwargs("postgresql+psycopg://user:pw@db:5432/app")
        assert pg_kwargs["pool_pre_ping"] is True
        assert pg_kwargs["pool_size"] >= 1
        assert pg_kwargs["max_overflow"] >= 0

        sqlite_kwargs = _build_engine_kwargs("sqlite:///./local.db")
        assert sqlite_kwargs["connect_args"]["check_same_thread"] is False

    def test_concurrent_review_insert_blocked_atomically(self, tmp_path):
        from app.database.audit import save_underwriting_run
        from app.database.db import init_db
        from app.database.reviews import (
            ConcurrentReviewConflictError,
            insert_human_review_event,
        )
        from app.decision.decision_agent import DecisionReasoningAgent
        from app.schemas.underwriting import (
            OrchestrationStatus,
            UnderwritingAnalysisResult,
        )

        init_db()
        analysis = UnderwritingAnalysisResult(
            application_id="APP-CONC-1",
            applicant_id="APP-CONC-1",
            orchestration_status=OrchestrationStatus.FAILED,
            error_message="test",
        )
        dec = DecisionReasoningAgent().evaluate(analysis)
        run_id = save_underwriting_run(analysis, dec)

        ev1 = {
            "source_run_id": run_id,
            "application_id": "APP-CONC-1",
            "original_ai_recommendation": "MANUAL_REVIEW",
            "original_pipeline_status": "FAILED",
            "action": "START_REVIEW",
            "reviewer_id": "uw_1",
            "decision_reason": "First concurrent claim",
            "previous_review_status": "PENDING",
            "new_review_status": "IN_REVIEW",
            "submission_hash": "hash-conc-1",
        }
        ev2 = {
            "source_run_id": run_id,
            "application_id": "APP-CONC-1",
            "original_ai_recommendation": "MANUAL_REVIEW",
            "original_pipeline_status": "FAILED",
            "action": "APPROVE",
            "human_decision": "APPROVE",
            "reviewer_id": "uw_2",
            "decision_reason": "Stale second concurrent approve",
            "previous_review_status": "PENDING",
            "new_review_status": "APPROVED",
            "submission_hash": "hash-conc-2",
        }
        insert_human_review_event(ev1)
        with pytest.raises(ConcurrentReviewConflictError):
            insert_human_review_event(ev2)

    def test_alembic_and_non_destructive_data_migration(self, tmp_path):
        import sqlite3

        from alembic.config import Config

        from alembic import command
        from app.database.migration import migrate_database_data

        # 1. Create a legacy pre-Stage-7 SQLite DB with historical run & review
        src_path = tmp_path / "legacy_src.db"
        conn = sqlite3.connect(src_path)
        conn.execute("""
            CREATE TABLE underwriting_runs (
                run_id TEXT PRIMARY KEY,
                application_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                pipeline_version TEXT NOT NULL,
                decision_policy_version TEXT NOT NULL,
                orchestrator_version TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                decision_confidence REAL NOT NULL,
                eligibility_status TEXT NOT NULL,
                risk_category TEXT NOT NULL,
                risk_score REAL NOT NULL,
                anomaly_severity TEXT NOT NULL,
                anomaly_score REAL NOT NULL,
                documents_found_count INTEGER NOT NULL,
                documents_missing_count INTEGER NOT NULL,
                human_review_required INTEGER NOT NULL,
                pipeline_status TEXT NOT NULL,
                execution_time_ms REAL NOT NULL,
                reasons_json TEXT NOT NULL,
                positive_factors_json TEXT NOT NULL,
                negative_factors_json TEXT NOT NULL,
                blocking_factors_json TEXT NOT NULL,
                supporting_evidence_json TEXT NOT NULL,
                summary_narrative TEXT NOT NULL
            );
            """)
        conn.execute("""
            INSERT INTO underwriting_runs VALUES (
                'RUN-LEGACY-1', 'APP0001', '2026-01-01T00:00:00+00:00',
                'v1', 'v1', 'v1', 'MANUAL_REVIEW', 80.0, 'ELIGIBLE', 'MEDIUM',
                42.0, 'NONE', 0.0, 4, 0, 1, 'SUCCESS', 12.0,
                '[]', '[]', '[]', '[]', '[]', 'Legacy narrative'
            );
            """)
        conn.commit()
        conn.close()

        # 2. Migrate into fresh target DB cleanly without mutating source
        dst_path = tmp_path / "target_dst.db"
        counts = migrate_database_data(f"sqlite:///{src_path}", f"sqlite:///{dst_path}")
        assert counts["underwriting_runs"] == 1

        # Re-running migration is strictly idempotent
        counts2 = migrate_database_data(
            f"sqlite:///{src_path}", f"sqlite:///{dst_path}"
        )
        assert counts2["underwriting_runs"] == 0

        # 3. Alembic upgrade on existing pre-Stage-7 DB preserves row and adds new columns
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{src_path}")
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(src_path)
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(underwriting_runs);").fetchall()
        }
        row = conn.execute(
            "SELECT run_id FROM underwriting_runs WHERE run_id='RUN-LEGACY-1';"
        ).fetchone()
        conn.close()
        assert row is not None
        assert "initiated_by_user_id" in cols

    def test_streamlit_optional_auth_mode_enforced(self, monkeypatch):
        from pathlib import Path

        from streamlit.testing.v1 import AppTest

        from app.database.db import init_db

        init_db()
        svc = AuthService()
        svc.init_tables()
        svc.seed_default_admin()
        svc.create_user(
            UserCreate(
                username="st_officer",
                full_name="Streamlit Officer",
                email="st_officer@example.com",
                password="OfficerPass123!",
                role=Role.LOAN_OFFICER,
            )
        )

        monkeypatch.setenv("STREAMLIT_AUTH_REQUIRED", "true")
        get_settings.cache_clear()
        try:
            project_root = Path(__file__).resolve().parent.parent
            at = AppTest.from_file(str(project_root / "app" / "main.py")).run(
                timeout=20
            )
            assert not at.exception
            # Unauthenticated user sees auth gate prompt and no sidebar navigation radio
            assert any("Authentication is required" in str(i.value) for i in at.info)

            # Sign in as Loan Officer
            at.text_input(key="ui_login_username").set_value("st_officer")
            at.text_input(key="ui_login_password").set_value("OfficerPass123!")
            at.button(key="ui_btn_sign_in").click().run(timeout=20)
            assert not at.exception

            # Loan officer cannot view Underwriter Review Queue
            at.sidebar.radio(key="sidebar_nav_radio").set_value(
                "Underwriter Review Queue"
            ).run(timeout=20)
            assert not at.exception
            assert any("Access denied" in str(e.value) for e in at.error)
        finally:
            monkeypatch.delenv("STREAMLIT_AUTH_REQUIRED", raising=False)
            get_settings.cache_clear()


# ==========================================================================
# 8. Existing Test Suite Compatibility
# ==========================================================================


class TestExistingTestsUnbroken:
    """Verify that Stage 7 changes don't break existing settings loading."""

    def test_settings_load_with_new_fields(self):
        settings = get_settings()
        assert settings.jwt_secret_key
        assert settings.access_token_expire_minutes > 0
        assert settings.refresh_token_expire_days > 0
        assert settings.login_rate_limit_max_attempts > 0

    def test_database_url_still_works(self):
        settings = get_settings()
        assert "sqlite" in settings.database_url
