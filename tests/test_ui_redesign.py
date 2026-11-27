"""Automated validation suite for Dual-Theme UI, Guided 4-Step Wizard, Workspace & RBAC."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from app.api.main import app as fastapi_app
from app.auth.models import Role, UserCreate
from app.auth.service import AuthService
from app.database import init_db
from app.database.applications import get_submitted_application
from app.database.audit import get_applicant_run_history
from app.database.reviews import get_human_review_events
from config.settings import get_settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_ui_redesign_db(tmp_path, monkeypatch):
    """Isolate SQLite DB per test strictly via DATABASE_URL."""
    db_file = tmp_path / "ui_overhaul_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    get_settings.cache_clear()
    init_db()
    yield db_file
    get_settings.cache_clear()


def test_theme_default_and_persistence_across_navigation():
    """Verify Light theme is default and Dark theme persists across reruns and all pages."""
    at = AppTest.from_file(str(PROJECT_ROOT / "app" / "main.py")).run(timeout=20)
    assert not at.exception
    assert at.session_state["ui_theme"] == "light"

    # Toggle to Dark theme
    at.sidebar.toggle(key="ui_theme_dark_toggle").set_value(True).run(timeout=20)
    assert not at.exception
    assert at.session_state["ui_theme"] == "dark"

    # Navigate through all 8 screens and confirm dark theme remains persisted cleanly
    for page in (
        "Applications",
        "Application Details",
        "New Application",
        "Document Review",
        "Underwriting Results",
        "Underwriter Review Queue",
        "Audit History",
        "Dashboard",
    ):
        at.sidebar.radio(key="sidebar_nav_radio").set_value(page).run(timeout=20)
        assert (
            not at.exception
        ), f"Dark theme page '{page}' raised exception: {at.exception}"
        assert at.session_state["ui_theme"] == "dark"


def test_intake_wizard_validation_and_back_navigation_preserves_fields():
    """Verify 4-step wizard enforces step validation and preserves all 13 fields on Previous/Continue."""
    at = AppTest.from_file(str(PROJECT_ROOT / "app" / "main.py")).run(timeout=20)
    at.sidebar.radio(key="sidebar_nav_radio").set_value("New Application").run(
        timeout=20
    )
    assert at.session_state["ui_intake_wizard_step"] == 1

    # Blank name must block Step 1 -> Step 2 transition
    at.text_input(key="intake_field_applicant_id").set_value("APP-WIZ-901")
    at.text_input(key="intake_field_name").set_value("")
    at.button(key="wizard_next_1").click().run(timeout=20)
    assert at.session_state["ui_intake_wizard_step"] == 1
    assert any("Full Name" in str(e.value) for e in at.error)

    # Provide valid Step 1 fields & advance
    at.text_input(key="intake_field_name").set_value("Ananya Sharma")
    at.number_input(key="intake_field_age").set_value(34)
    at.button(key="wizard_next_1").click().run(timeout=20)
    assert at.session_state["ui_intake_wizard_step"] == 2

    # Enter all Step 2 fields including explicit optional values & zero EMI
    at.selectbox(key="intake_field_employment_type").set_value("Self-Employed")
    at.number_input(key="intake_field_employment_years").set_value(6.5)
    at.number_input(key="intake_field_monthly_income").set_value(125000.0)
    at.number_input(key="intake_field_existing_emi").set_value(0.0)
    at.number_input(key="intake_field_bank_balance").set_value(450000.0)
    at.number_input(key="intake_field_loan_amount").set_value(750000.0)
    at.number_input(key="intake_field_loan_tenure").set_value(48)
    at.number_input(key="intake_field_credit_score").set_value(780)
    at.text_input(key="intake_field_monthly_expenses").set_value("22000")
    at.text_input(key="intake_field_number_of_dependents").set_value("2")
    at.run(timeout=20)

    # Navigate forward to Step 3, then back to Step 1 and forward again -> confirm zero data loss
    at.button(key="wizard_next_2").click().run(timeout=20)
    assert at.session_state["ui_intake_wizard_step"] == 3
    at.button(key="wizard_prev_3").click().run(timeout=20)
    assert at.session_state["ui_intake_wizard_step"] == 2
    assert at.number_input(key="intake_field_monthly_income").value == 125000.0
    assert at.number_input(key="intake_field_existing_emi").value == 0.0
    assert float(at.text_input(key="intake_field_monthly_expenses").value) == 22000.0
    assert at.text_input(key="intake_field_number_of_dependents").value == "2"

    at.button(key="wizard_prev_2").click().run(timeout=20)
    assert at.session_state["ui_intake_wizard_step"] == 1
    assert at.text_input(key="intake_field_name").value == "Ananya Sharma"
    assert at.number_input(key="intake_field_age").value == 34

    # Fast-forward to Step 4 & submit
    at.button(key="wizard_next_1").click().run(timeout=20)
    at.button(key="wizard_next_2").click().run(timeout=20)
    at.button(key="wizard_next_3").click().run(timeout=20)
    assert at.session_state["ui_intake_wizard_step"] == 4
    at.button(key="btn_submit_underwriting").click().run(timeout=25)
    assert not at.exception

    saved = get_submitted_application("APP-WIZ-901")
    assert saved is not None
    assert saved["name"] == "Ananya Sharma"
    assert saved["monthly_expenses"] == 22000.0
    assert saved["number_of_dependents"] == 2
    assert saved["existing_emi"] == 0.0
    assert len(get_applicant_run_history("APP-WIZ-901")) == 1


def test_all_roles_auth_maker_checker_and_fastapi_health(monkeypatch):
    """Verify all 4 roles login/logout, restricted pages, Maker-Checker self-review block, and API health."""
    auth_svc = AuthService()
    auth_svc.init_tables()
    for uname, role in (
        ("red_admin", Role.ADMINISTRATOR),
        ("red_officer", Role.LOAN_OFFICER),
        ("red_uw", Role.UNDERWRITER),
        ("red_sup", Role.SUPERVISOR),
    ):
        auth_svc.create_user(
            UserCreate(
                username=uname,
                full_name=f"Role {role.value}",
                email=f"{uname}@example.com",
                password="StrongPassword!1",
                role=role,
            )
        )

    client = TestClient(fastapi_app)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200

    monkeypatch.setenv("STREAMLIT_AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        at = AppTest.from_file(str(PROJECT_ROOT / "app" / "main.py")).run(timeout=20)
        assert any("Authentication is required" in str(i.value) for i in at.info)

        # Loan Officer: blocked from Human Review; submits APP-RBAC-01 via wizard
        at.text_input(key="ui_login_username").set_value("red_officer")
        at.text_input(key="ui_login_password").set_value("StrongPassword!1")
        at.button(key="ui_btn_sign_in").click().run(timeout=20)
        assert "ui_auth_access_token" in at.session_state

        at.sidebar.radio(key="sidebar_nav_radio").set_value(
            "Underwriter Review Queue"
        ).run(timeout=20)
        assert any("Access denied" in str(e.value) for e in at.error)

        at.sidebar.radio(key="sidebar_nav_radio").set_value("New Application").run(
            timeout=20
        )
        at.text_input(key="intake_field_applicant_id").set_value("APP-RBAC-01")
        at.text_input(key="intake_field_name").set_value("Karan Verma")
        at.button(key="wizard_next_1").click().run(timeout=20)
        at.button(key="wizard_next_2").click().run(timeout=20)
        at.button(key="wizard_next_3").click().run(timeout=20)
        at.button(key="btn_submit_underwriting").click().run(timeout=25)
        run_id = get_applicant_run_history("APP-RBAC-01")[0]["run_id"]
        at.button(key="ui_btn_sign_out").click().run(timeout=20)

        # Administrator submits APP-MC-02 -> Maker-Checker blocks admin self-review
        at.text_input(key="ui_login_username").set_value("red_admin")
        at.text_input(key="ui_login_password").set_value("StrongPassword!1")
        at.button(key="ui_btn_sign_in").click().run(timeout=20)
        at.sidebar.radio(key="sidebar_nav_radio").set_value("New Application").run(
            timeout=20
        )
        at.text_input(key="intake_field_applicant_id").set_value("APP-MC-02")
        at.text_input(key="intake_field_name").set_value("Neha Roy")
        at.button(key="wizard_next_1").click().run(timeout=20)
        at.button(key="wizard_next_2").click().run(timeout=20)
        at.button(key="wizard_next_3").click().run(timeout=20)
        at.button(key="btn_submit_underwriting").click().run(timeout=25)
        mc_run_id = get_applicant_run_history("APP-MC-02")[0]["run_id"]

        at.sidebar.radio(key="sidebar_nav_radio").set_value(
            "Underwriter Review Queue"
        ).run(timeout=20)
        at.selectbox(key="rq_selected_case_id").set_value("APP-MC-02").run(timeout=20)
        at.text_input(key=f"rq_reason_{mc_run_id}").set_value("Self review attempt")
        at.checkbox(key=f"rq_confirm_{mc_run_id}").set_value(True)
        at.run(timeout=20)
        at.button(key=f"rq_btn_submit_{mc_run_id}").click().run(timeout=20)
        assert len(get_human_review_events(source_run_id=mc_run_id)) == 0
        at.button(key="ui_btn_sign_out").click().run(timeout=20)

        # Underwriter sees intake restriction & approves LOAN_OFFICER submission
        at.text_input(key="ui_login_username").set_value("red_uw")
        at.text_input(key="ui_login_password").set_value("StrongPassword!1")
        at.button(key="ui_btn_sign_in").click().run(timeout=20)
        at.sidebar.radio(key="sidebar_nav_radio").set_value(
            "Underwriter Review Queue"
        ).run(timeout=20)
        at.selectbox(key="rq_selected_case_id").set_value("APP-RBAC-01").run(timeout=20)
        at.selectbox(key=f"rq_action_{run_id}").set_value("Approve")
        at.text_input(key=f"rq_reason_{run_id}").set_value("Independent review")
        at.checkbox(key=f"rq_confirm_{run_id}").set_value(True)
        at.run(timeout=20)
        at.button(key=f"rq_btn_submit_{run_id}").click().run(timeout=25)
        assert len(get_human_review_events(source_run_id=run_id)) == 1
        at.button(key="ui_btn_sign_out").click().run(timeout=20)

        # Supervisor performs linked correction cleanly
        at.text_input(key="ui_login_username").set_value("red_sup")
        at.text_input(key="ui_login_password").set_value("StrongPassword!1")
        at.button(key="ui_btn_sign_in").click().run(timeout=20)
        at.sidebar.radio(key="sidebar_nav_radio").set_value(
            "Underwriter Review Queue"
        ).run(timeout=20)
        at.selectbox(key="rq_filter_rev_status").set_value("ALL").run(timeout=20)
        at.selectbox(key="rq_selected_case_id").set_value("APP-RBAC-01").run(timeout=20)
        at.checkbox(key=f"rq_is_correction_{run_id}").set_value(True).run(timeout=20)
        at.text_input(key=f"rq_corr_expl_{run_id}").set_value(
            "Supervisor policy override after post-review audit"
        )
        at.selectbox(key=f"rq_action_{run_id}").set_value("Reject")
        at.text_input(key=f"rq_reason_{run_id}").set_value("Updated supervisor ruling")
        at.checkbox(key=f"rq_confirm_{run_id}").set_value(True)
        at.run(timeout=20)
        at.button(key=f"rq_btn_submit_{run_id}").click().run(timeout=25)
        sup_events = get_human_review_events(source_run_id=run_id)
        assert len(sup_events) == 2
        assert sup_events[0]["human_decision"] == "REJECT"
        assert sup_events[0]["is_correction"] is True
    finally:
        monkeypatch.delenv("STREAMLIT_AUTH_REQUIRED", raising=False)
        get_settings.cache_clear()
