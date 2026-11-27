"""Streamlit Underwriting Dashboard & Application Controller (Stage 5).

Coordinates the 7-screen fintech interface while preserving backwards-compatible
module exports consumed by `app/main.py` and `tests/test_dashboard_audit.py`.
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
    apply_fintech_styles,
    format_eligibility_metrics_summary,
    format_inr,
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
    STATE_CURRENT_PAGE,
    STATE_SELECTED_APP_ID,
    apply_pending_state_transitions,
    init_session_state,
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
    """Execute Stages 3-8 pipeline and persist run immutably into SQLite audit trail."""
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
        page_icon="🏦",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def render_dashboard() -> None:
    """Render the complete Stage 5 Streamlit application controller."""
    init_db()
    apply_fintech_styles()
    init_session_state(default_applicant_ref_fn=generate_applicant_reference)

    # Top Header
    st.markdown(
        '<div class="main-header">AI Loan Underwriting Assistant</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="sub-header">Deterministic Multi-Agent Underwriting Workbench & Explainable Audit Ledger</div>',
        unsafe_allow_html=True,
    )

    catalog = load_applicant_catalog()
    app_ids = [rec["applicant_id"] for rec in catalog]
    apply_pending_state_transitions(app_ids)

    with st.sidebar:
        st.markdown("### Navigation")
        current_page = st.session_state.get(STATE_CURRENT_PAGE, "Dashboard")
        page_idx = NAV_PAGES.index(current_page) if current_page in NAV_PAGES else 0
        selected_page = st.radio(
            "Workspace",
            options=list(NAV_PAGES),
            index=page_idx,
            key="sidebar_nav_radio",
        )
        if selected_page != current_page:
            st.session_state[STATE_CURRENT_PAGE] = selected_page

        st.markdown("---")
        st.markdown("### Active Application Context")
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
                    f"Source: `{sel_rec.get('source', 'synthetic')}` | "
                    f"Income: {format_inr(sel_rec.get('monthly_income'))} | "
                    f"Loan: {format_inr(sel_rec.get('loan_amount'))}"
                )
        else:
            sel_rec = None
            st.caption("No applications loaded.")

        st.markdown("---")
        st.markdown(
            """
            <div class="disclaimer-banner">
                <strong>Decision-Support & Synthetic Notice:</strong><br>
                AI recommendations assist human underwriters and do not constitute final credit approval.
                Synthetic profiles are isolated from production banking systems.
            </div>
            """,
            unsafe_allow_html=True,
        )

    active_page = st.session_state.get(STATE_CURRENT_PAGE, "Dashboard")
    active_app_id = st.session_state.get(STATE_SELECTED_APP_ID)
    active_app_rec = get_applicant_record(active_app_id)

    if active_page == "Dashboard":
        render_dashboard_overview()
    elif active_page == "Underwriter Review Queue":
        render_underwriter_review_queue_view()
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
