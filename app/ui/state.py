"""Session-State Management Helpers for the Stage 5 Streamlit Application.

Centralizes navigation routing, draft preservation across reruns, upload staging
buffers, result caching keyed by applicant/run ID, and duplicate-submission guards.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

NAV_PAGES: tuple[str, ...] = (
    "Dashboard",
    "Underwriter Review Queue",
    "New Application",
    "Applications",
    "Application Details",
    "Document Review",
    "Underwriting Results",
    "Audit History",
)

STATE_CURRENT_PAGE = "ui_current_page"
STATE_SELECTED_APP_ID = "ui_selected_app_id"
STATE_SELECTED_RUN_ID = "ui_selected_run_id"
STATE_INTAKE_DRAFT = "ui_intake_draft"
STATE_STAGED_UPLOADS = "ui_staged_uploads"
STATE_DOC_PREVIEW_CACHE = "ui_doc_preview_cache"
STATE_LIVE_ANALYSES = "ui_live_analyses"
STATE_SUBMITTED_HASHES = "ui_submitted_hashes"
STATE_INTAKE_SEED_REF = "ui_intake_seed_ref"
STATE_LAST_SUBMISSION_RECEIPT = "ui_last_submission_receipt"
STATE_SUBMISSION_IN_PROGRESS = "ui_submission_in_progress"
STATE_UPLOAD_COUNTER = "ui_upload_counter"
STATE_PENDING_NAV_PAGE = "_ui_pending_nav_page"
STATE_PENDING_NAV_APP_ID = "_ui_pending_nav_app_id"
STATE_PENDING_NAV_RUN_ID = "_ui_pending_nav_run_id"
STATE_PENDING_CLEAR_INTAKE = "_ui_pending_clear_intake"
STATE_PENDING_GEN_APP_ID = "_ui_pending_gen_app_id"
STATE_PENDING_LOAD_INTAKE = "_ui_pending_load_intake"
STATE_LAST_REVIEW_RECEIPT = "ui_last_review_receipt"
STATE_AUTH_ACCESS_TOKEN = "ui_auth_access_token"
STATE_AUTH_REFRESH_TOKEN = "ui_auth_refresh_token"


def default_intake_draft(applicant_id: str = "") -> Dict[str, Any]:
    """Return a clean initial applicant draft matching the authoritative Applicant schema."""
    return {
        "applicant_id": applicant_id,
        "name": "",
        "age": 30,
        "employment_type": "Salaried",
        "employment_years": 3.0,
        "monthly_income": 75000.0,
        "monthly_expenses": None,
        "existing_emi": 0.0,
        "number_of_dependents": None,
        "credit_score": 720,
        "bank_balance": 100000.0,
        "loan_amount": 300000.0,
        "loan_tenure": 36,
    }


def init_session_state(default_applicant_ref_fn: Optional[Any] = None) -> None:
    """Initialize all required session-state containers safely once per session."""
    if STATE_CURRENT_PAGE not in st.session_state:
        st.session_state[STATE_CURRENT_PAGE] = "Dashboard"

    if STATE_SELECTED_APP_ID not in st.session_state:
        st.session_state[STATE_SELECTED_APP_ID] = None

    if STATE_SELECTED_RUN_ID not in st.session_state:
        st.session_state[STATE_SELECTED_RUN_ID] = None

    if STATE_INTAKE_SEED_REF not in st.session_state:
        seed = default_applicant_ref_fn() if callable(default_applicant_ref_fn) else ""
        st.session_state[STATE_INTAKE_SEED_REF] = seed

    if STATE_INTAKE_DRAFT not in st.session_state:
        st.session_state[STATE_INTAKE_DRAFT] = default_intake_draft(
            st.session_state[STATE_INTAKE_SEED_REF]
        )

    if STATE_STAGED_UPLOADS not in st.session_state:
        st.session_state[STATE_STAGED_UPLOADS] = []

    if STATE_DOC_PREVIEW_CACHE not in st.session_state:
        st.session_state[STATE_DOC_PREVIEW_CACHE] = {}

    if STATE_LIVE_ANALYSES not in st.session_state:
        st.session_state[STATE_LIVE_ANALYSES] = {}

    if STATE_SUBMITTED_HASHES not in st.session_state:
        st.session_state[STATE_SUBMITTED_HASHES] = {}

    if STATE_LAST_SUBMISSION_RECEIPT not in st.session_state:
        st.session_state[STATE_LAST_SUBMISSION_RECEIPT] = None

    if STATE_SUBMISSION_IN_PROGRESS not in st.session_state:
        st.session_state[STATE_SUBMISSION_IN_PROGRESS] = False

    if STATE_UPLOAD_COUNTER not in st.session_state:
        st.session_state[STATE_UPLOAD_COUNTER] = 0


def navigate_to(
    page: str,
    applicant_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> None:
    """Queue navigation state atomically to apply safely before widgets instantiate on rerun."""
    if page in NAV_PAGES:
        st.session_state[STATE_CURRENT_PAGE] = page
        st.session_state[STATE_PENDING_NAV_PAGE] = page
    if applicant_id is not None:
        st.session_state[STATE_SELECTED_APP_ID] = applicant_id
        st.session_state[STATE_PENDING_NAV_APP_ID] = applicant_id
    if run_id is not None:
        st.session_state[STATE_SELECTED_RUN_ID] = run_id
        st.session_state[STATE_PENDING_NAV_RUN_ID] = run_id


def apply_pending_state_transitions(available_app_ids: List[str]) -> None:
    """Apply queued navigation/reset transitions before Streamlit renders widgets."""
    if STATE_PENDING_NAV_PAGE in st.session_state:
        page = st.session_state.pop(STATE_PENDING_NAV_PAGE)
        st.session_state[STATE_CURRENT_PAGE] = page
        st.session_state["sidebar_nav_radio"] = page

    if STATE_PENDING_NAV_APP_ID in st.session_state:
        aid = st.session_state.pop(STATE_PENDING_NAV_APP_ID)
        st.session_state[STATE_SELECTED_APP_ID] = aid
        if aid in available_app_ids:
            for wk in (
                "sidebar_app_selector",
                "results_app_selector",
                "details_app_selector",
                "doc_review_app_selector",
                "rq_selected_case_id",
            ):
                st.session_state[wk] = aid

    if STATE_PENDING_LOAD_INTAKE in st.session_state:
        draft_payload = st.session_state.pop(STATE_PENDING_LOAD_INTAKE)
        st.session_state[STATE_INTAKE_SEED_REF] = draft_payload.get("applicant_id", "")
        st.session_state[STATE_INTAKE_DRAFT] = draft_payload
        st.session_state[STATE_STAGED_UPLOADS] = []
        st.session_state[STATE_DOC_PREVIEW_CACHE] = {}
        st.session_state[STATE_UPLOAD_COUNTER] = (
            int(st.session_state.get(STATE_UPLOAD_COUNTER, 0)) + 1
        )
        for key in list(st.session_state.keys()):
            if isinstance(key, str) and key.startswith("intake_field_"):
                del st.session_state[key]

    if STATE_PENDING_NAV_RUN_ID in st.session_state:
        rid = st.session_state.pop(STATE_PENDING_NAV_RUN_ID)
        st.session_state[STATE_SELECTED_RUN_ID] = rid

    if STATE_PENDING_CLEAR_INTAKE in st.session_state:
        new_ref = st.session_state.pop(STATE_PENDING_CLEAR_INTAKE)
        st.session_state[STATE_INTAKE_SEED_REF] = new_ref
        st.session_state[STATE_INTAKE_DRAFT] = default_intake_draft(new_ref)
        st.session_state[STATE_STAGED_UPLOADS] = []
        st.session_state[STATE_DOC_PREVIEW_CACHE] = {}
        st.session_state[STATE_UPLOAD_COUNTER] = (
            int(st.session_state.get(STATE_UPLOAD_COUNTER, 0)) + 1
        )
        for key in list(st.session_state.keys()):
            if isinstance(key, str) and key.startswith("intake_field_"):
                del st.session_state[key]

    if STATE_PENDING_GEN_APP_ID in st.session_state:
        fresh_id = st.session_state.pop(STATE_PENDING_GEN_APP_ID)
        draft = dict(st.session_state.get(STATE_INTAKE_DRAFT) or default_intake_draft())
        draft["applicant_id"] = fresh_id
        st.session_state[STATE_INTAKE_SEED_REF] = fresh_id
        st.session_state[STATE_INTAKE_DRAFT] = draft
        st.session_state["intake_field_applicant_id"] = fresh_id


def clear_intake_after_submission(new_applicant_ref: str) -> None:
    """Queue draft & upload buffer reset safely without mutating post-render widget keys."""
    st.session_state[STATE_PENDING_CLEAR_INTAKE] = new_applicant_ref


def queue_new_applicant_ref(fresh_id: str) -> None:
    """Queue applicant ID widget update before next rerun renders widgets."""
    st.session_state[STATE_PENDING_GEN_APP_ID] = fresh_id


def queue_existing_applicant_for_intake(app_record: Dict[str, Any]) -> None:
    """Queue preloading an existing applicant record cleanly into New Application intake."""
    draft = default_intake_draft(str(app_record.get("applicant_id", "")))
    for k in draft:
        if k in app_record:
            draft[k] = app_record[k]
    st.session_state[STATE_PENDING_LOAD_INTAKE] = draft


def store_live_result(
    applicant_id: str,
    result_bundle: Dict[str, Any],
) -> None:
    """Cache latest execution bundle scoped cleanly per applicant_id."""
    live_map: Dict[str, Dict[str, Any]] = st.session_state.setdefault(
        STATE_LIVE_ANALYSES, {}
    )
    live_map[applicant_id] = result_bundle
    st.session_state[STATE_SELECTED_APP_ID] = applicant_id
    if result_bundle.get("run_id"):
        st.session_state[STATE_SELECTED_RUN_ID] = result_bundle["run_id"]


def get_live_result(applicant_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return cached live result strictly for the requested applicant_id (never cross-leaked)."""
    if not applicant_id:
        return None
    live_map: Dict[str, Dict[str, Any]] = st.session_state.get(STATE_LIVE_ANALYSES, {})
    return live_map.get(applicant_id)


def get_staged_uploads() -> List[Dict[str, Any]]:
    """Return current session staged upload entries."""
    return list(st.session_state.get(STATE_STAGED_UPLOADS, []))


def get_authenticated_ui_user() -> Optional[Any]:
    """Verify the session access token via AuthService and return the active User or None."""
    token = st.session_state.get(STATE_AUTH_ACCESS_TOKEN)
    if not token:
        return None
    try:
        from app.auth.service import AuthenticationError, AuthService

        auth = AuthService()
        return auth.get_current_user(str(token))
    except AuthenticationError:
        st.session_state.pop(STATE_AUTH_ACCESS_TOKEN, None)
        st.session_state.pop(STATE_AUTH_REFRESH_TOKEN, None)
        return None
    except Exception:
        return None


def logout_ui_session() -> None:
    """Revoke refresh tokens and clear UI session authentication tokens."""
    user = get_authenticated_ui_user()
    if user is not None:
        try:
            from app.auth.service import AuthService

            AuthService().logout(user.user_id)
        except Exception:
            pass
    st.session_state.pop(STATE_AUTH_ACCESS_TOKEN, None)
    st.session_state.pop(STATE_AUTH_REFRESH_TOKEN, None)
