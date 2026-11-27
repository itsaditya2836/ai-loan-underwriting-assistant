"""Streamlit Underwriting Dashboard & Application Controller.

Coordinates the multi-page fintech interface, theme switching (Light/Dark),
role-aware sidebar navigation, and backwards-compatible exports.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import streamlit as st

from app.agents.decision_agent import DecisionReasoningAgent
from app.database import init_db
from app.database.audit import save_underwriting_run
from app.orchestration.orchestrator import UnderwritingOrchestrator
from app.schemas.decision import DecisionReasoningResult
from app.schemas.underwriting import UnderwritingAnalysisResult
from app.ui.components import (
    _esc,
    apply_fintech_styles,
    format_eligibility_metrics_summary,
    format_inr,
    get_ui_theme,
    render_banking_table,
    render_page_header,
    render_section_heading,
    render_status_pill,
)
from app.ui.services import (
    APPLICANTS_DATA_PATH,
    DOCUMENTS_BASE_DIR,
    generate_applicant_reference,
    get_applicant_record,
    has_physical_document_package,
    load_applicant_catalog,
    load_synthetic_applicants_raw,
)
from app.ui.state import (
    NAV_PAGES,
    STATE_AUTH_ACCESS_TOKEN,
    STATE_AUTH_REFRESH_TOKEN,
    STATE_CURRENT_PAGE,
    STATE_SELECTED_APP_ID,
    STATE_UI_THEME,
    apply_pending_state_transitions,
    can_role_access_page,
    format_sidebar_nav_option,
    get_authenticated_ui_user,
    init_session_state,
    logout_ui_session,
    navigate_to,
)
from app.ui.views_intake import render_new_application_view
from app.ui.views_portfolio import (
    render_application_details_view,
    render_applications_directory_view,
    render_audit_history_view,
    render_dashboard_overview,
)
from app.ui.views_results import (
    render_document_review_view,
    render_underwriting_results_view,
)
from app.ui.views_review import render_underwriter_review_queue_view
from config.settings import get_settings


@st.cache_data
def load_all_applicants_metadata() -> List[Dict[str, Any]]:
    """Load applicant records from synthetic dataset (preserved helper for tests/callers)."""
    return load_synthetic_applicants_raw()


def get_applicant_by_id(app_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve applicant dictionary by ID from SQLite submissions or synthetic dataset."""
    return get_applicant_record(app_id)


def has_document_package(app_id: str) -> bool:
    """Check whether physical PDF documents or submitted uploads exist for applicant."""
    rec = get_applicant_record(app_id)
    if rec and rec.get("uploaded_files"):
        return True
    return has_physical_document_package(app_id)


def execute_underwriting_pipeline(
    application_id: str,
) -> tuple[UnderwritingAnalysisResult, DecisionReasoningResult, str, float]:
    """Execute pipeline and persist run immutably into SQLite audit trail."""
    start_time = time.perf_counter()

    orchestrator = UnderwritingOrchestrator()
    analysis = orchestrator.process(application_id)

    decision_agent = DecisionReasoningAgent()
    decision = decision_agent.evaluate(analysis)

    duration_ms = (time.perf_counter() - start_time) * 1000.0
    run_id = save_underwriting_run(
        analysis=analysis,
        decision=decision,
        execution_time_ms=round(duration_ms, 2),
    )
    analysis.audit_run_id = run_id
    analysis.audit_persisted = True
    analysis.audit_persistence_error = None
    return analysis, decision, run_id, duration_ms


def _on_sidebar_app_change() -> None:
    """Propagate sidebar application change cleanly to downstream page selectors."""
    chosen = st.session_state.get("sidebar_app_selector")
    if chosen:
        st.session_state[STATE_SELECTED_APP_ID] = chosen
        for wk in (
            "results_app_selector",
            "details_app_selector",
            "doc_review_app_selector",
            "rq_selected_case_id",
        ):
            st.session_state.pop(wk, None)
        st.session_state["ui_selected_run_id"] = None


def _on_theme_toggle() -> None:
    """Persist Light/Dark theme choice cleanly across reruns."""
    is_dark = bool(st.session_state.get("ui_theme_dark_toggle", False))
    st.session_state[STATE_UI_THEME] = "dark" if is_dark else "light"


def configure_page() -> None:
    """Configure Streamlit page metadata once at the application entry point."""
    st.set_page_config(
        page_title="AI Loan Underwriting Assistant",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def _render_sidebar_brand() -> None:
    """Render compact banking brand mark at top of sidebar."""
    st.markdown(
        """
        <div class="banking-brand">
            <div class="banking-brand-mark">LU</div>
            <div>
                <div class="banking-brand-title">Loan Underwriting</div>
                <div class="banking-brand-sub">Credit Operations Platform</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar_theme_toggle() -> None:
    """Render Light/Dark theme switch cleanly inside sidebar preferences."""
    current = get_ui_theme()
    st.toggle(
        "Dark theme",
        value=(current == "dark"),
        key="ui_theme_dark_toggle",
        on_change=_on_theme_toggle,
    )


def _render_sidebar_auth_widget() -> Optional[Any]:
    """Render compact RBAC session sign-in / signed-in card separately from navigation."""
    auth_user = get_authenticated_ui_user()
    settings = get_settings()
    auth_enforced = settings.is_streamlit_auth_enforced()

    with st.sidebar:
        _render_sidebar_brand()
        st.markdown(
            '<div class="banking-sidebar-section">Session & Role</div>',
            unsafe_allow_html=True,
        )
        if auth_user is not None:
            display_name = _esc(auth_user.full_name or auth_user.username)
            uname_esc = _esc(auth_user.username)
            role_pill = render_status_pill(auth_user.role.value, "info")
            st.markdown(
                f"""
                <div class="banking-session-card">
                    <div class="banking-session-name">{display_name}</div>
                    <div class="banking-session-role">@{uname_esc} &nbsp;{role_pill}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(
                "Sign Out",
                key="ui_btn_sign_out",
                icon=":material/logout:",
                width="stretch",
            ):
                logout_ui_session()
                st.rerun()
        else:
            mode_label = (
                "Sign In Required" if auth_enforced else "Sign In (Optional RBAC)"
            )
            with st.expander(mode_label, expanded=auth_enforced):
                uname = st.text_input("Username", key="ui_login_username")
                pwd = st.text_input(
                    "Password", type="password", key="ui_login_password"
                )
                if st.button(
                    "Sign In",
                    key="ui_btn_sign_in",
                    type="primary",
                    width="stretch",
                ):
                    try:
                        from app.auth.service import AuthenticationError, AuthService

                        auth_svc = AuthService()
                        auth_svc.init_tables()
                        if not settings.is_production():
                            auth_svc.seed_default_admin()
                        tokens = auth_svc.login(uname, pwd)
                        st.session_state[STATE_AUTH_ACCESS_TOKEN] = tokens.access_token
                        st.session_state[STATE_AUTH_REFRESH_TOKEN] = (
                            tokens.refresh_token
                        )
                        st.rerun()
                    except AuthenticationError as exc:
                        st.error(str(exc))
    return auth_user


def _render_unauthenticated_landing() -> None:
    """Render clean enterprise sign-in gate when strict authentication is enforced."""
    with st.sidebar:
        st.markdown("---")
        st.markdown(
            '<div class="banking-sidebar-section">Appearance</div>',
            unsafe_allow_html=True,
        )
        _render_sidebar_theme_toggle()

    render_page_header(
        "Access Control",
        "AI Loan Underwriting Assistant",
        "Sign in to access loan origination, multi-agent underwriting, and audit workflows.",
        breadcrumbs=["Platform", "Sign In"],
    )
    st.info(
        "Authentication is required (`APP_ENV=production` or `STREAMLIT_AUTH_REQUIRED=true`). "
        "Please sign in using the sidebar Session & Role panel."
    )
    render_section_heading(
        "Role-Based Access Overview",
        "Authenticated sessions enforce separation of duties across intake, evaluation, and approval",
    )
    render_banking_table(
        headers=["Role", "Permitted Workspaces", "Restricted Controls"],
        rows=[
            [
                "LOAN_OFFICER",
                "Overview, New Intake, Applications, App Workspace, Document Verification, Underwriting, Own Audit",
                "Human Review decisions, corrections, user admin",
            ],
            [
                "UNDERWRITER",
                "Overview, Applications, App Workspace, Document Verification, Underwriting, Human Review",
                "New application intake, Maker-Checker self-reviews, corrections",
            ],
            [
                "SUPERVISOR",
                "All operational workspaces, full Audit Trail, linked post-decision corrections",
                "New application intake, Maker-Checker self-reviews, user management",
            ],
            [
                "ADMINISTRATOR",
                "Full workbench access plus FastAPI /api/v1 user management & account unlock",
                "Self-reviewing applications submitted or evaluated by own account",
            ],
        ],
        pill_columns={0},
    )


def render_dashboard() -> None:
    """Render the complete Streamlit application controller with dual-theme styling."""
    settings = get_settings()
    init_db()
    init_session_state(default_applicant_ref_fn=generate_applicant_reference)

    # Apply chosen Light or Dark theme tokens cleanly on every rerun
    apply_fintech_styles(get_ui_theme())

    # Fail closed if production configuration lacks secure secrets/CORS rules
    try:
        settings.validate_production_security()
    except RuntimeError as exc:
        st.error(f"Startup Blocked — Security Misconfiguration: {exc}")
        return

    auth_user = _render_sidebar_auth_widget()
    if settings.is_streamlit_auth_enforced() and auth_user is None:
        _render_unauthenticated_landing()
        return

    catalog = load_applicant_catalog()
    app_ids = [rec["applicant_id"] for rec in catalog]
    apply_pending_state_transitions(app_ids)

    active_role = auth_user.role if auth_user is not None else None
    can_create = can_role_access_page(active_role, "New Application")

    with st.sidebar:
        st.markdown("---")
        if can_create and st.button(
            "New Application",
            key="sidebar_cta_new_application",
            type="primary",
            icon=":material/add:",
            width="stretch",
        ):
            navigate_to("New Application")
            st.rerun()

        st.markdown(
            '<div class="banking-sidebar-section">Navigation</div>',
            unsafe_allow_html=True,
        )
        current_page = st.session_state.get(STATE_CURRENT_PAGE, "Dashboard")
        page_idx = NAV_PAGES.index(current_page) if current_page in NAV_PAGES else 0
        selected_page = st.radio(
            "Workspace",
            options=list(NAV_PAGES),
            index=page_idx,
            format_func=lambda p: format_sidebar_nav_option(p, active_role),
            key="sidebar_nav_radio",
            label_visibility="collapsed",
        )
        if selected_page != current_page:
            st.session_state[STATE_CURRENT_PAGE] = selected_page

        st.markdown("---")
        st.markdown(
            '<div class="banking-sidebar-section">Active Case</div>',
            unsafe_allow_html=True,
        )
        if app_ids:
            active_id = st.session_state.get(STATE_SELECTED_APP_ID)
            if active_id not in app_ids:
                active_id = app_ids[0]
                st.session_state[STATE_SELECTED_APP_ID] = active_id
            sel_idx = app_ids.index(active_id)
            chosen_id = st.selectbox(
                "Active Application",
                options=app_ids,
                index=sel_idx,
                format_func=lambda aid: next(
                    f"{r['applicant_id']} — {r.get('name', 'N/A')}"
                    for r in catalog
                    if r["applicant_id"] == aid
                ),
                key="sidebar_app_selector",
                on_change=_on_sidebar_app_change,
                label_visibility="collapsed",
            )
            if chosen_id != st.session_state.get(STATE_SELECTED_APP_ID):
                st.session_state[STATE_SELECTED_APP_ID] = chosen_id

            sel_rec = get_applicant_record(chosen_id)
            if sel_rec:
                st.caption(
                    f"{sel_rec.get('source', 'synthetic').title()} · "
                    f"Loan {format_inr(sel_rec.get('loan_amount'))}"
                )
        else:
            st.caption("No applications loaded.")

        st.markdown("---")
        st.markdown(
            '<div class="banking-sidebar-section">Preferences</div>',
            unsafe_allow_html=True,
        )
        _render_sidebar_theme_toggle()

        st.markdown(
            """
            <div class="banking-sidebar-note">
                Advisory AI outputs require authorized human underwriting sign-off.
                Workspace uses isolated synthetic cohorts.
            </div>
            """,
            unsafe_allow_html=True,
        )

    active_page = st.session_state.get(STATE_CURRENT_PAGE, "Dashboard")
    active_app_id = st.session_state.get(STATE_SELECTED_APP_ID)
    active_app_rec = get_applicant_record(active_app_id)

    if active_page == "Dashboard":
        render_dashboard_overview()
    elif active_page == "New Application":
        render_new_application_view()
    elif active_page == "Applications":
        render_applications_directory_view()
    elif active_page == "Application Details":
        render_application_details_view(active_app_id, active_app_rec)
    elif active_page == "Document Review":
        render_document_review_view()
    elif active_page == "Underwriting Results":
        render_underwriting_results_view()
    elif active_page == "Underwriter Review Queue":
        render_underwriter_review_queue_view()
    elif active_page == "Audit History":
        render_audit_history_view()


__all__ = [
    "APPLICANTS_DATA_PATH",
    "DOCUMENTS_BASE_DIR",
    "configure_page",
    "execute_underwriting_pipeline",
    "format_eligibility_metrics_summary",
    "format_inr",
    "get_applicant_by_id",
    "has_document_package",
    "load_all_applicants_metadata",
    "render_dashboard",
]


if __name__ == "__main__":
    configure_page()
    render_dashboard()
