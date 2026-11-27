"""Streamlit Underwriting Dashboard & Application Controller.

Coordinates the multi-page fintech interface while preserving backwards-compatible
module exports consumed by `app/main.py` and test suites.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pandas as pd
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
    apply_pending_state_transitions,
    format_sidebar_nav_option,
    get_authenticated_ui_user,
    init_session_state,
    logout_ui_session,
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


def configure_page() -> None:
    """Configure Streamlit page metadata once at the application entry point."""
    st.set_page_config(
        page_title="AI Loan Underwriting Assistant",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def _render_sidebar_brand() -> None:
    """Render concise institutional application identity at top of sidebar."""
    st.markdown(
        """
        <div class="banking-brand">
            <div class="banking-brand-title">Loan Underwriting</div>
            <div class="banking-brand-sub">Credit Operations & Audit Workbench</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar_auth_widget() -> Optional[Any]:
    """Render RBAC session sign-in / signed-in user block visually separate from navigation."""
    auth_user = get_authenticated_ui_user()
    settings = get_settings()
    auth_enforced = settings.is_streamlit_auth_enforced()

    with st.sidebar:
        _render_sidebar_brand()
        st.markdown(
            '<div class="banking-sidebar-section">Session & Identity</div>',
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
            if st.button("Sign Out", key="ui_btn_sign_out", width="stretch"):
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
        st.markdown("---")
    return auth_user


def _render_unauthenticated_landing() -> None:
    """Render clean enterprise sign-in gate when strict authentication is enforced."""
    render_page_header(
        "Access Control",
        "AI Loan Underwriting Assistant",
        "Authenticated workspace for credit intake, multi-agent evaluation, and human review.",
    )
    st.info(
        "Authentication is required (`APP_ENV=production` or `STREAMLIT_AUTH_REQUIRED=true`). "
        "Please sign in using the sidebar Session & Identity panel."
    )
    with st.container(border=True):
        render_section_heading(
            "Role-Based Access Matrix",
            "Server-verified JWT sessions enforce separation of duties across origination and review",
        )
        role_rows = [
            {
                "Role": "LOAN_OFFICER",
                "Workspace Access": "Dashboard, New Application, Applications, Case Details, Document Review, Results, Own Audit",
                "Restricted Actions": "Underwriter Review Queue, decision corrections, user admin",
            },
            {
                "Role": "UNDERWRITER",
                "Workspace Access": "Dashboard, Applications, Case Details, Document Review, Results, Underwriter Review Queue",
                "Restricted Actions": "Creating applications, reviewing own cases (Maker-Checker), post-decision corrections",
            },
            {
                "Role": "SUPERVISOR",
                "Workspace Access": "All operational views, full Audit History, linked post-decision corrections",
                "Restricted Actions": "Creating applications, reviewing own cases, user account management",
            },
            {
                "Role": "ADMINISTRATOR",
                "Workspace Access": "Full workbench visibility, FastAPI /api/v1 user admin & unlock operations",
                "Restricted Actions": "Reviewing applications submitted or evaluated by own account",
            },
        ]
        st.dataframe(pd.DataFrame(role_rows), width="stretch", hide_index=True)


def render_dashboard() -> None:
    """Render the complete Streamlit application controller."""
    apply_fintech_styles()
    settings = get_settings()

    # Fail closed if production configuration lacks secure secrets/CORS rules
    try:
        settings.validate_production_security()
    except RuntimeError as exc:
        st.error(f"Startup Blocked — Security Misconfiguration: {exc}")
        return

    init_db()
    init_session_state(default_applicant_ref_fn=generate_applicant_reference)

    auth_user = _render_sidebar_auth_widget()
    if settings.is_streamlit_auth_enforced() and auth_user is None:
        _render_unauthenticated_landing()
        return

    catalog = load_applicant_catalog()
    app_ids = [rec["applicant_id"] for rec in catalog]
    apply_pending_state_transitions(app_ids)

    active_role = auth_user.role if auth_user is not None else None

    with st.sidebar:
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
            '<div class="banking-sidebar-section">Active Application Context</div>',
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
            )
            if chosen_id != st.session_state.get(STATE_SELECTED_APP_ID):
                st.session_state[STATE_SELECTED_APP_ID] = chosen_id

            sel_rec = get_applicant_record(chosen_id)
            if sel_rec:
                st.caption(
                    f"{sel_rec.get('source', 'synthetic').title()} · "
                    f"Income {format_inr(sel_rec.get('monthly_income'))} · "
                    f"Loan {format_inr(sel_rec.get('loan_amount'))}"
                )
        else:
            st.caption("No applications loaded.")

        st.markdown("---")
        st.markdown(
            """
            <div class="banking-sidebar-note">
                <strong>Advisory Governance:</strong> AI recommendations support underwriting
                triage only. Final lending decisions remain with authorized human underwriters.
                Workspace uses isolated synthetic records.
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
