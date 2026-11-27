"""Portfolio Dashboard, Applications Directory, Application Details & Audit History.

Every screen queries actual SQLite records and read-only catalog metadata cleanly,
distinguishing applications from underwriting executions and keeping failed runs separate.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from app.database.applications import list_submitted_applications
from app.database.audit import (
    get_applicant_run_history,
    get_audit_run_by_id,
    get_audit_runs,
    get_latest_runs_per_application,
)
from app.database.reviews import get_human_review_events, get_review_history_for_run
from app.review.service import (
    compute_review_queue_metrics,
    get_case_review_summary,
    list_review_queue,
    record_additional_info_return,
)
from app.schemas.applicant import Applicant
from app.schemas.review import ReviewStatus
from app.ui.components import (
    format_compact_status,
    format_inr,
    format_risk_score_display,
    render_conflicts_panel,
    render_factor_cards,
    render_human_vs_ai_summary_panel,
    render_kpi_row,
    render_kv_grid,
    render_page_header,
    render_section_heading,
    render_status_pill,
)
from app.ui.services import (
    compute_dashboard_metrics,
    format_decision_label,
    get_applicant_record,
    has_physical_document_package,
    load_applicant_catalog,
    mask_extracted_value,
    submit_application_and_underwrite,
)
from app.ui.state import (
    STATE_SELECTED_APP_ID,
    STATE_SELECTED_RUN_ID,
    get_authenticated_ui_user,
    navigate_to,
    queue_existing_applicant_for_intake,
    store_live_result,
)


def _format_utc_short(ts: Optional[str]) -> str:
    """Format ISO-8601 timestamp compactly as YYYY-MM-DD HH:MM."""
    if not ts:
        return "—"
    return str(ts)[:16].replace("T", " ")


def render_dashboard_overview() -> None:
    """Render clean operational overview backed strictly by SQLite and catalog data."""
    auth_user = get_authenticated_ui_user()
    can_create_app = True
    if auth_user is not None:
        from app.auth.permissions import Permission, check_permission

        can_create_app = check_permission(auth_user.role, Permission.APPLICANT_CREATE)

    head_left, head_right = st.columns([3.4, 1.2], vertical_alignment="bottom")
    with head_left:
        render_page_header(
            "Overview",
            "Dashboard",
            "Overview of loan applications and underwriting activity.",
        )
    with head_right:
        if can_create_app and st.button(
            "New Loan Application",
            type="primary",
            key="dash_cta_new_application",
            width="stretch",
        ):
            navigate_to("New Application")
            st.rerun()

    metrics = compute_dashboard_metrics()
    audit_sum = metrics["audit_summary"]
    catalog = load_applicant_catalog()
    catalog_map = {
        rec["applicant_id"]: rec for rec in catalog if rec.get("applicant_id")
    }
    submitted_apps = list_submitted_applications(limit=1000)
    latest_all = get_latest_runs_per_application(exclude_failed=False, limit=1000)
    all_queue = list_review_queue(
        applicant_catalog_by_id=catalog_map, include_finalized=True
    )
    review_metrics = compute_review_queue_metrics(all_queue)

    tracked_ids = {a["applicant_id"] for a in submitted_apps} | {
        r["application_id"] for r in latest_all
    }
    total_tracked = len(tracked_ids)
    pending_human = (
        review_metrics["pending_reviews"]
        + review_metrics["in_progress"]
        + review_metrics["additional_info_requested"]
        + review_metrics["investigation_required"]
    )
    failed_excluded = metrics["failed_latest_applications"]

    render_kpi_row(
        [
            {
                "label": "Total Applications",
                "value": total_tracked,
                "meta": f"{len(submitted_apps)} submitted · {len(catalog)} in catalog",
            },
            {
                "label": "Completed Evaluations",
                "value": metrics["evaluated_completed_applications"],
                "meta": (
                    f"{failed_excluded} failed run(s) excluded"
                    if failed_excluded
                    else "Latest completed run per app"
                ),
            },
            {
                "label": "Pending Human Reviews",
                "value": pending_human,
                "meta": f"{review_metrics['pending_reviews']} pending · {review_metrics['in_progress']} in review",
            },
            {
                "label": "Approved Applications",
                "value": metrics["approved_applications"],
                "meta": f"{review_metrics['approved_by_underwriter']} final human approved",
            },
        ]
    )

    if audit_sum["total_runs"] == 0:
        with st.container(border=True):
            st.info(
                "No underwriting runs are recorded in SQLite yet. Create an application using **New Loan Application** "
                "or run baseline synthetic evaluations to populate the workspace."
            )
            can_seed = True
            if auth_user is not None:
                from app.auth.permissions import Permission, check_permission

                can_seed = check_permission(
                    auth_user.role, Permission.UNDERWRITING_INITIATE
                )
            if can_seed and st.button(
                "Run Sample Baseline Cohort Evaluations (APP0001–APP0010)",
                key="dash_seed_sample",
            ):
                with st.spinner(
                    "Running synthetic baseline evaluations through underwriting pipeline..."
                ):
                    for i in range(1, 11):
                        aid = f"APP{i:04d}"
                        rec = get_applicant_record(aid)
                        if rec:
                            out = submit_application_and_underwrite(
                                applicant=Applicant.model_validate(rec),
                                staged_uploads=[],
                                use_existing_package_if_empty=has_physical_document_package(
                                    aid
                                ),
                                allow_duplicate=True,
                                submitted_by_user_id=(
                                    auth_user.user_id if auth_user else None
                                ),
                                submitted_by_username=(
                                    auth_user.username if auth_user else None
                                ),
                                submitted_by_role=(
                                    auth_user.role.value if auth_user else None
                                ),
                            )
                            store_live_result(aid, out)
                st.rerun()
        return

    latest_by_app = {r["application_id"]: r for r in latest_all}

    col_left, col_right = st.columns([1.75, 1.0], gap="medium")

    with col_left:
        with st.container(border=True):
            l_head, l_cta = st.columns([3, 1.2], vertical_alignment="center")
            with l_head:
                render_section_heading(
                    "Recent Applications",
                    "Latest underwriting recommendation and status per application",
                )
            with l_cta:
                if st.button("View All", key="dash_view_all_apps", width="stretch"):
                    navigate_to("Applications")
                    st.rerun()

            recent_ordered: List[Dict[str, Any]] = []
            seen_recent: set[str] = set()
            for r in latest_all:
                aid = r["application_id"]
                if aid in seen_recent:
                    continue
                seen_recent.add(aid)
                rec = catalog_map.get(aid) or get_applicant_record(aid) or {}
                recent_ordered.append(
                    {
                        "ID": aid,
                        "Applicant": str(rec.get("name", "N/A")),
                        "Loan": format_inr(rec.get("loan_amount")),
                        "AI Rec": format_compact_status(r.get("recommendation")),
                        "Status": format_compact_status(
                            rec.get("application_status")
                            or (
                                "UNDERWRITTEN"
                                if r.get("pipeline_status") == "SUCCESS"
                                else r.get("pipeline_status")
                            )
                        ),
                        "Updated": str(r.get("timestamp", ""))[:10] or "—",
                    }
                )
            for rec in submitted_apps:
                aid = rec["applicant_id"]
                if aid not in seen_recent:
                    seen_recent.add(aid)
                    recent_ordered.append(
                        {
                            "ID": aid,
                            "Applicant": str(rec.get("name", "N/A")),
                            "Loan": format_inr(rec.get("loan_amount")),
                            "AI Rec": "Not Evaluated",
                            "Status": format_compact_status(
                                rec.get("application_status", "SUBMITTED")
                            ),
                            "Updated": str(rec.get("created_at", ""))[:10] or "—",
                        }
                    )

            if recent_ordered:
                st.dataframe(
                    pd.DataFrame(recent_ordered[:8]),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.caption("No application records available yet.")

    with col_right:
        with st.container(border=True):
            render_section_heading(
                "Pending Review Queue",
                f"{pending_human} case(s) requiring underwriter attention",
            )
            action_items = [
                item
                for item in all_queue
                if item.get("human_review_status")
                in {
                    ReviewStatus.PENDING.value,
                    ReviewStatus.IN_REVIEW.value,
                    ReviewStatus.ADDITIONAL_INFO_REQUESTED.value,
                    ReviewStatus.INVESTIGATION_REQUIRED.value,
                }
            ]
            if not action_items:
                st.caption(
                    "All evaluated cases currently have finalized human reviews."
                )
            else:
                for idx, item in enumerate(action_items[:5]):
                    aid = item["applicant_id"]
                    rid = item["source_run_id"]
                    triggers = [
                        format_compact_status(t)
                        for t in (item.get("attention_triggers") or [])
                    ]
                    reason = (
                        " · ".join(triggers)
                        or f"AI: {format_compact_status(item.get('ai_recommendation'))}"
                    )
                    rev_label = format_compact_status(item.get("human_review_status"))
                    pill_html = render_status_pill(rev_label)
                    c_info, c_act = st.columns([3.2, 1.0], vertical_alignment="center")
                    with c_info:
                        st.markdown(
                            f"**{aid}** · {item.get('applicant_name', 'N/A')}  \n"
                            f"{pill_html} &nbsp;<span style='font-size:0.77rem;color:#64748B;'>{reason}</span>",
                            unsafe_allow_html=True,
                        )
                    with c_act:
                        if st.button(
                            "Open",
                            key=f"dash_open_case_{idx}_{aid}",
                            width="stretch",
                        ):
                            navigate_to(
                                "Underwriter Review Queue",
                                applicant_id=aid,
                                run_id=rid,
                            )
                            st.rerun()
                    if idx < min(len(action_items), 5) - 1:
                        st.markdown(
                            "<hr style='margin:0.4rem 0;border-color:#F1F5F9;'>",
                            unsafe_allow_html=True,
                        )

            if st.button(
                "Open Full Review Queue",
                key="dash_goto_queue",
                width="stretch",
            ):
                navigate_to("Underwriter Review Queue")
                st.rerun()

    # Compact Application Status & Risk Summary section
    with st.container(border=True):
        render_section_heading(
            "Underwriting Portfolio Summary",
            "Outcome and risk mix across completed evaluations alongside execution health",
        )
        dec_dist = metrics["completed_decision_distribution"]
        risk_dist = metrics["completed_risk_distribution"]
        p_dist = audit_sum.get("pipeline_status_distribution", {})

        sum_col1, sum_col2 = st.columns([1.3, 1.0], gap="medium")
        with sum_col1:
            dec_df = pd.DataFrame(
                [
                    {
                        "AI Outcome": format_compact_status(k),
                        "Applications": v,
                    }
                    for k, v in dec_dist.items()
                ]
            )
            st.bar_chart(dec_df.set_index("AI Outcome"), height=210, color="#1E3A8A")
        with sum_col2:
            summary_pairs = [
                (
                    "Decision Breakdown",
                    f"{dec_dist.get('APPROVE', 0)} Approve · {dec_dist.get('MANUAL_REVIEW', 0)} Review · {dec_dist.get('REJECT', 0)} Reject",
                    "Latest completed AI evaluation per app",
                ),
                (
                    "Risk Tier Mix",
                    f"{risk_dist.get('LOW', 0)} Low · {risk_dist.get('MEDIUM', 0)} Med · {risk_dist.get('BORDERLINE', 0)} Border · {risk_dist.get('HIGH', 0)} High",
                    "Completed evaluations only",
                ),
                (
                    "Pipeline Runs",
                    f"{audit_sum.get('completed_runs_count', audit_sum['total_runs'])} Valid / {audit_sum['total_runs']} Total",
                    f"{p_dist.get('FAILED', 0)} failed · Avg {audit_sum['avg_latency_ms']:.1f} ms",
                ),
                (
                    "Human Decisions",
                    f"{review_metrics['approved_by_underwriter']} Approved · {review_metrics['rejected_by_underwriter']} Rejected",
                    f"{review_metrics['additional_info_requested'] + review_metrics['investigation_required']} follow-up",
                ),
            ]
            render_kv_grid(summary_pairs, columns=2)
            _ = latest_by_app


def render_applications_directory_view() -> None:
    """Render filterable applications registry backed by SQLite & catalog."""
    render_page_header(
        "Applications",
        "Applications",
        "Search persisted loan applications and synthetic cohorts by status, source, or evaluation outcome.",
    )

    catalog = load_applicant_catalog()
    all_runs = get_audit_runs(limit=1000)
    runs_by_app: Dict[str, List[Dict[str, Any]]] = {}
    for run in all_runs:
        runs_by_app.setdefault(run["application_id"], []).append(run)

    with st.container(border=True):
        f1, f2, f3, f4 = st.columns([1.6, 1, 1.1, 1.1])
        search_ref = (
            f1.text_input("Search Applicant ID / Name", value="", key="apps_search_ref")
            .strip()
            .lower()
        )
        src_filter = f2.selectbox(
            "Source",
            options=["ALL", "submitted", "synthetic"],
            key="apps_source_filter",
        )
        dec_filter = f3.selectbox(
            "Latest Decision",
            options=["ALL", "NOT_EVALUATED", "APPROVE", "REJECT", "MANUAL_REVIEW"],
            key="apps_dec_filter",
        )
        pipe_filter = f4.selectbox(
            "Latest Pipeline Status",
            options=["ALL", "SUCCESS", "PARTIAL_SUCCESS", "FAILED"],
            key="apps_pipe_filter",
        )

        d1, d2, d3, d4 = st.columns([1.3, 1, 1, 1], vertical_alignment="center")
        use_dates = d1.checkbox(
            "Filter by Latest Run Date Range", value=False, key="apps_use_dates"
        )
        start_d = (
            d2.date_input("From Date", value=date(2026, 1, 1), key="apps_start_date")
            if use_dates
            else None
        )
        end_d = (
            d3.date_input("To Date", value=datetime.now().date(), key="apps_end_date")
            if use_dates
            else None
        )
        page_size = d4.selectbox(
            "Rows to Display",
            options=[20, 50, 100, 200],
            index=0,
            key="apps_page_limit",
        )

    rows: List[Dict[str, Any]] = []
    matching_ids: List[str] = []
    for rec in catalog:
        aid = rec["applicant_id"]
        name = str(rec.get("name", "N/A"))
        source = rec.get("source", "synthetic")
        app_runs = runs_by_app.get(aid, [])
        latest = app_runs[0] if app_runs else None

        if src_filter != "ALL" and source != src_filter:
            continue
        if search_ref and (
            search_ref not in aid.lower() and search_ref not in name.lower()
        ):
            continue

        latest_rec = latest["recommendation"] if latest else "NOT_EVALUATED"
        latest_pipe = latest["pipeline_status"] if latest else "PENDING"
        latest_ts = (
            _format_utc_short(latest["timestamp"])
            if latest
            else _format_utc_short(rec.get("created_at"))
        )

        if dec_filter != "ALL" and latest_rec != dec_filter:
            continue
        if pipe_filter != "ALL" and latest_pipe != pipe_filter:
            continue
        if use_dates and start_d and end_d:
            if not latest:
                continue
            run_day = latest["timestamp"][:10]
            if run_day < start_d.isoformat() or run_day > end_d.isoformat():
                continue

        matching_ids.append(aid)
        case_rev = get_case_review_summary(
            aid, run_id=latest["run_id"] if latest else None
        )
        rows.append(
            {
                "ID": aid,
                "Name": name,
                "Source": source.title(),
                "Loan Amount": format_inr(rec.get("loan_amount")),
                "AI Rec": (format_compact_status(latest_rec) if latest else "Pending"),
                "Risk": (
                    format_compact_status(latest["risk_category"]) if latest else "—"
                ),
                "Review": (
                    format_compact_status(case_rev["human_review_status"])
                    if latest
                    else "—"
                ),
                "Human Decision": (
                    format_compact_status(case_rev["human_decision"])
                    if case_rev.get("human_decision")
                    else ("Pending" if latest else "—")
                ),
                "Updated": latest_ts[:10] if latest_ts != "—" else "—",
            }
        )

    if not rows:
        st.info("No applications match your active filters.")
        return

    st.caption(
        f"Showing {min(len(rows), page_size)} of {len(rows)} matching application(s)"
    )
    st.dataframe(pd.DataFrame(rows[:page_size]), width="stretch", hide_index=True)

    with st.container(border=True):
        render_section_heading(
            "Open Selected Case",
            "Jump directly to dossier, results, queue, or documents",
        )
        sel_col, btn_det, btn_res, btn_rev, btn_doc = st.columns(
            [2.2, 1, 1, 1, 1], vertical_alignment="bottom"
        )
        with sel_col:
            target_id = st.selectbox(
                "Application Reference",
                options=matching_ids,
                key="apps_quick_target",
            )
        latest_for_target = runs_by_app.get(target_id, [])
        target_run_id = latest_for_target[0]["run_id"] if latest_for_target else None
        with btn_det:
            if st.button("Application Details", key="apps_go_details", width="stretch"):
                navigate_to(
                    "Application Details", applicant_id=target_id, run_id=target_run_id
                )
                st.rerun()
        with btn_res:
            if st.button(
                "Underwriting Results", key="apps_go_results", width="stretch"
            ):
                navigate_to(
                    "Underwriting Results",
                    applicant_id=target_id,
                    run_id=target_run_id,
                )
                st.rerun()
        with btn_rev:
            if st.button("Review Queue", key="apps_go_review", width="stretch"):
                navigate_to(
                    "Underwriter Review Queue",
                    applicant_id=target_id,
                    run_id=target_run_id,
                )
                st.rerun()
        with btn_doc:
            if st.button("Document Review", key="apps_go_docs", width="stretch"):
                navigate_to(
                    "Document Review", applicant_id=target_id, run_id=target_run_id
                )
                st.rerun()


def render_application_details_view(
    selected_app_id: Optional[str] = None,
    applicant_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Render full authoritative dossier and multi-run history for a selected applicant."""
    render_page_header(
        "Applications",
        "Application Details",
        "Authoritative applicant financials, status separation, and persisted run history.",
    )

    catalog = load_applicant_catalog()
    app_ids = [rec["applicant_id"] for rec in catalog]
    active_id = selected_app_id or st.session_state.get(STATE_SELECTED_APP_ID)
    if app_ids:
        idx = app_ids.index(active_id) if active_id in app_ids else 0
        chosen_id = st.selectbox(
            "Target Application",
            options=app_ids,
            index=idx,
            format_func=lambda aid: next(
                f"{r['applicant_id']} — {r.get('name', 'N/A')} ({r.get('source', 'synthetic')})"
                for r in catalog
                if r["applicant_id"] == aid
            ),
            key="details_app_selector",
        )
        st.session_state[STATE_SELECTED_APP_ID] = chosen_id
        data = get_applicant_record(chosen_id)
    else:
        chosen_id = active_id or "N/A"
        data = applicant_data

    if not data:
        st.info(
            "No application record found. Create an application in **New Application**."
        )
        return

    src_lbl = str(data.get("source", "synthetic")).title()
    st_lbl = format_compact_status(data.get("application_status", "SYNTHETIC_CATALOG"))
    st.markdown(
        f"**Reference:** `{chosen_id}` &nbsp;·&nbsp; "
        f"{render_status_pill(src_lbl, 'neutral')} &nbsp; "
        f"{render_status_pill(st_lbl, 'info')}",
        unsafe_allow_html=True,
    )

    render_section_heading("Authoritative Profile & Loan Request")
    dep = data.get("number_of_dependents")
    render_kv_grid(
        [
            ("Applicant Name", str(data.get("name", "N/A"))),
            ("Age", f"{data.get('age', 'N/A')} yrs"),
            ("Employment Type", str(data.get("employment_type", "N/A"))),
            ("Employment Tenure", f"{data.get('employment_years', 'N/A')} yrs"),
            ("Monthly Income", format_inr(data.get("monthly_income"))),
            ("Existing Monthly EMI", format_inr(data.get("existing_emi"))),
            ("Verifiable Bank Balance", format_inr(data.get("bank_balance"))),
            ("Bureau Credit Score", str(data.get("credit_score", "N/A"))),
            ("Requested Loan Amount", format_inr(data.get("loan_amount"))),
            ("Loan Tenure", f"{data.get('loan_tenure', 'N/A')} months"),
            (
                "Monthly Expenses",
                (
                    format_inr(data.get("monthly_expenses"))
                    if data.get("monthly_expenses") is not None
                    else "Not Provided"
                ),
            ),
            ("Dependents", str(dep) if dep is not None else "Not Provided"),
        ],
        columns=4,
    )

    if data.get("uploaded_files"):
        with st.expander(
            f"Uploaded Document Metadata ({len(data['uploaded_files'])} file(s); ephemeral bytes cleaned)",
            expanded=False,
        ):
            st.dataframe(
                pd.DataFrame(data["uploaded_files"]),
                width="stretch",
                hide_index=True,
            )

    case_summary = get_case_review_summary(chosen_id)
    render_section_heading(
        "Underwriting & Review Status Separation",
        "AI outputs remain advisory and separate from human underwriting decisions",
    )
    render_human_vs_ai_summary_panel(case_summary)

    latest_rev = case_summary.get("latest_review") or {}
    if case_summary["human_review_status"] in {
        ReviewStatus.ADDITIONAL_INFO_REQUESTED.value,
        ReviewStatus.INVESTIGATION_REQUIRED.value,
    }:
        req_text = latest_rev.get("additional_info_request") or latest_rev.get(
            "investigation_instructions"
        )
        st.warning(
            f"**Case Status `{case_summary['human_review_status']}`** (by `{latest_rev.get('reviewer_id', 'reviewer')}`): "
            f"{req_text or 'Follow-up required.'}"
        )
        if case_summary.get("source_run_id"):
            with st.expander(
                "Record Additional Information / Return to Pending Review Queue",
                expanded=False,
            ):
                f_handler = st.text_input(
                    "Handler Identifier *",
                    value="intake_staff_01",
                    key=f"details_ret_handler_{chosen_id}",
                )
                f_notes = st.text_input(
                    "Follow-Up Information Recorded *",
                    value="",
                    key=f"details_ret_notes_{chosen_id}",
                )
                c_ret1, c_ret2 = st.columns(2)
                with c_ret1:
                    if st.button(
                        "Return Case to Pending Review Queue",
                        key=f"details_btn_return_pending_{chosen_id}",
                        width="stretch",
                    ):
                        ret_res = record_additional_info_return(
                            source_run_id=case_summary["source_run_id"],
                            application_id=chosen_id,
                            reviewer_id=f_handler,
                            info_response=f_notes,
                        )
                        if ret_res["saved"]:
                            st.success(
                                "Returned case to PENDING human review queue cleanly (AI history preserved)."
                            )
                            st.rerun()
                        else:
                            st.error(ret_res["error"])
                with c_ret2:
                    if st.button(
                        "Upload Updated Documents in New Application",
                        key=f"details_btn_upload_new_docs_{chosen_id}",
                        width="stretch",
                    ):
                        queue_existing_applicant_for_intake(data)
                        navigate_to("New Application", applicant_id=chosen_id)
                        st.rerun()

    st.markdown("---")
    render_section_heading("Persisted AI Underwriting Run History")
    history = get_applicant_run_history(chosen_id)
    if not history:
        st.info("No underwriting runs recorded yet for this application.")
        if st.button("Run Underwriting Now", key="details_run_now", type="primary"):
            try:
                with st.spinner(
                    f"Running multi-agent underwriting pipeline for {chosen_id}..."
                ):
                    out = submit_application_and_underwrite(
                        applicant=Applicant.model_validate(data),
                        staged_uploads=[],
                        use_existing_package_if_empty=has_physical_document_package(
                            chosen_id
                        ),
                        allow_duplicate=True,
                    )
                store_live_result(chosen_id, out)
                navigate_to(
                    "Underwriting Results",
                    applicant_id=chosen_id,
                    run_id=out.get("run_id"),
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Underwriting execution failed safely: {exc}")
        return

    hist_rows = [
        {
            "#": idx,
            "Run ID": r["run_id"],
            "Timestamp (UTC)": _format_utc_short(r["timestamp"]),
            "AI Rec": format_compact_status(r["recommendation"]),
            "Pipeline": format_compact_status(r["pipeline_status"]),
            "Risk": (
                f"{format_compact_status(r['risk_category'])} ({format_risk_score_display(r.get('risk_score'))})"
                if r.get("risk_score") is not None
                else format_compact_status(r["risk_category"])
            ),
            "Latency": f"{r['execution_time_ms']:.1f} ms",
        }
        for idx, r in enumerate(history, 1)
    ]
    st.dataframe(pd.DataFrame(hist_rows), width="stretch", hide_index=True)

    sel_c, b1, b2, b3 = st.columns([2, 1, 1, 1], vertical_alignment="bottom")
    with sel_c:
        selected_hist_run = st.selectbox(
            "Inspect Historical Run",
            options=[r["run_id"] for r in history],
            key="details_hist_run_select",
        )
    with b1:
        if st.button(
            "Underwriting Results",
            key="details_goto_results",
            width="stretch",
        ):
            navigate_to(
                "Underwriting Results", applicant_id=chosen_id, run_id=selected_hist_run
            )
            st.rerun()
    with b2:
        if st.button(
            "Review Queue",
            key="details_goto_review_queue",
            width="stretch",
        ):
            navigate_to(
                "Underwriter Review Queue",
                applicant_id=chosen_id,
                run_id=selected_hist_run,
            )
            st.rerun()
    with b3:
        if st.button(
            "Audit History",
            key="details_goto_audit",
            width="stretch",
        ):
            navigate_to(
                "Audit History", applicant_id=chosen_id, run_id=selected_hist_run
            )
            st.rerun()

    render_section_heading("Append-Only Human Review History")
    rev_hist = case_summary.get("application_review_history") or []
    if rev_hist:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Review ID": ev["review_id"],
                        "Source Run": ev["source_run_id"],
                        "Timestamp (UTC)": _format_utc_short(ev["review_timestamp"]),
                        "AI Recommendation": format_compact_status(
                            ev["original_ai_recommendation"]
                        ),
                        "Transition": f"{ev['previous_review_status']} -> {ev['new_review_status']}",
                        "Human Decision": (
                            format_compact_status(ev["human_decision"])
                            if ev.get("human_decision")
                            else "Not yet recorded"
                        ),
                        "Reviewer ID": ev["reviewer_id"],
                        "Reason": ev["decision_reason"],
                    }
                    for ev in rev_hist
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption(
            "No human underwriter review events recorded yet for this application."
        )


def render_audit_history_view() -> None:
    """Render immutable, read-only SQLite AI & Human Review Audit Ledger."""
    render_page_header(
        "Records",
        "Audit History",
        "Append-only compliance ledger separating AI pipeline runs and human underwriter review events.",
    )

    with st.container(border=True):
        view_mode = st.radio(
            "Audit Event Stream",
            options=["All Audit Events", "AI Underwriting Runs", "Human Review Events"],
            horizontal=True,
            key="audit_event_stream_mode",
        )

        f1, f2, f3, f4, f5, f6 = st.columns(6)
        f_app = f1.text_input("Applicant ID", value="", key="audit_filter_app").strip()
        f_rev_id = f2.text_input(
            "Reviewer ID", value="", key="audit_filter_reviewer"
        ).strip()
        f_rec = f3.selectbox(
            "AI Recommendation",
            options=["ALL", "APPROVE", "REJECT", "MANUAL_REVIEW"],
            key="audit_filter_rec",
        )
        f_pipe = f4.selectbox(
            "Pipeline Status",
            options=["ALL", "SUCCESS", "PARTIAL_SUCCESS", "FAILED"],
            key="audit_filter_pipe",
        )
        f_risk = f5.selectbox(
            "Risk Category",
            options=["ALL", "LOW", "MEDIUM", "HIGH", "BORDERLINE", "UNAVAILABLE"],
            key="audit_filter_risk",
        )
        f_anom = f6.selectbox(
            "Anomaly Severity",
            options=["ALL", "NONE", "LOW", "MEDIUM", "HIGH", "UNAVAILABLE"],
            key="audit_filter_anom",
        )

    if view_mode in ("All Audit Events", "Human Review Events"):
        with st.container(border=True):
            render_section_heading(
                "Human Underwriter Review Events",
                "Immutable append-only human decisions and status transitions (HUMAN_REVIEW_EVENT)",
            )
            hr_events = get_human_review_events(
                application_id_prefix=f_app or None,
                reviewer_id=f_rev_id or None,
                human_decision=None,
                limit=300,
            )
            if f_rec != "ALL":
                hr_events = [
                    ev
                    for ev in hr_events
                    if ev.get("original_ai_recommendation") == f_rec
                ]
            if f_pipe != "ALL":
                hr_events = [
                    ev
                    for ev in hr_events
                    if ev.get("original_pipeline_status") == f_pipe
                ]

            if hr_events:
                hr_rows = [
                    {
                        "Review ID": ev["review_id"],
                        "Applicant": ev["application_id"],
                        "AI Rec": format_compact_status(
                            ev["original_ai_recommendation"]
                        ),
                        "Status": format_compact_status(ev["new_review_status"]),
                        "Decision": (
                            format_compact_status(ev["human_decision"])
                            if ev.get("human_decision")
                            else "Pending"
                        ),
                        "Reviewer": ev["reviewer_id"],
                        "Correction": (
                            f"Yes ({ev.get('parent_review_id')})"
                            if ev.get("is_correction")
                            else "No"
                        ),
                        "Timestamp (UTC)": _format_utc_short(ev["review_timestamp"]),
                    }
                    for ev in hr_events
                ]
                st.dataframe(pd.DataFrame(hr_rows), width="stretch", hide_index=True)

                sel_rev_id = st.selectbox(
                    "Inspect Human Review Event",
                    options=[ev["review_id"] for ev in hr_events],
                    key="audit_inspect_human_rev_id",
                )
                ev_obj = next(ev for ev in hr_events if ev["review_id"] == sel_rev_id)
                with st.expander(f"Event Details: {sel_rev_id}", expanded=False):
                    render_kv_grid(
                        [
                            ("Reviewer ID", str(ev_obj["reviewer_id"])),
                            (
                                "Original AI Recommendation",
                                format_compact_status(
                                    ev_obj["original_ai_recommendation"]
                                ),
                            ),
                            (
                                "Review Status",
                                format_compact_status(ev_obj["new_review_status"]),
                            ),
                            (
                                "Final Human Decision",
                                (
                                    format_compact_status(ev_obj["human_decision"])
                                    if ev_obj.get("human_decision")
                                    else "Not yet recorded"
                                ),
                            ),
                        ],
                        columns=4,
                    )
                    st.write(f"**Decision Reason:** {ev_obj['decision_reason']}")
                    if ev_obj.get("comments"):
                        st.write(f"**Comments (Masked):** {ev_obj['comments']}")
                    if ev_obj.get("additional_info_request"):
                        st.write(
                            f"**Additional Info Requested:** {ev_obj['additional_info_request']}"
                        )
                    if ev_obj.get("additional_info_response"):
                        st.write(
                            f"**Additional Info Follow-Up:** {ev_obj['additional_info_response']}"
                        )
                    if ev_obj.get("investigation_instructions"):
                        st.write(
                            f"**Investigation Instructions:** {ev_obj['investigation_instructions']}"
                        )
                    if ev_obj.get("is_correction"):
                        st.info(
                            f"**Linked Correction Event:** Corrects `{ev_obj.get('parent_review_id')}` — "
                            f"{ev_obj.get('correction_explanation')}"
                        )
            else:
                st.caption("No human review events match the active filters.")

    if view_mode == "Human Review Events":
        return

    with st.container(border=True):
        render_section_heading(
            "AI Underwriting Pipeline Runs",
            "Append-only automated pipeline evaluations (UNDERWRITING_RUN)",
        )

        runs = get_audit_runs(
            application_id_prefix=f_app or None,
            recommendation=None if f_rec == "ALL" else f_rec,
            pipeline_status=None if f_pipe == "ALL" else f_pipe,
            risk_category=None if f_risk == "ALL" else f_risk,
            anomaly_severity=None if f_anom == "ALL" else f_anom,
            limit=250,
        )

        if not runs:
            st.caption("No AI underwriting runs match the active filters.")
            return

        st.caption(f"Showing {len(runs)} audited pipeline run(s)")
        table_rows = [
            {
                "Run ID": r["run_id"],
                "Applicant": r["application_id"],
                "Timestamp": _format_utc_short(r["timestamp"]),
                "AI Rec": format_compact_status(r["recommendation"]),
                "Pipeline": format_compact_status(r["pipeline_status"]),
                "Risk": format_compact_status(r["risk_category"]),
                "Conflicts": len(r.get("consistency_conflicts") or []),
                "Latency": f"{r['execution_time_ms']:.1f} ms",
            }
            for r in runs
        ]
        st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)

        run_ids = [r["run_id"] for r in runs]
        pref_run = st.session_state.get(STATE_SELECTED_RUN_ID)
        idx = run_ids.index(pref_run) if pref_run in run_ids else 0
        inspect_id = st.selectbox(
            "Inspect AI Underwriting Run Snapshot",
            options=run_ids,
            index=idx,
            key="audit_inspect_run_id",
        )
        st.session_state[STATE_SELECTED_RUN_ID] = inspect_id

        run = get_audit_run_by_id(inspect_id)
        if not run:
            st.warning("Selected audit run could not be loaded.")
            return

        render_audit_run_inspection(run)


def render_audit_run_inspection(run: Dict[str, Any]) -> None:
    """Render structured read-only snapshot of a persisted underwriting audit record."""
    st.caption(f"Audit Record Verified in SQLite · `{run['run_id']}`")

    render_kv_grid(
        [
            ("Applicant ID", str(run["application_id"])),
            ("AI Recommendation", format_decision_label(run["recommendation"])),
            (
                "Heuristic Confidence",
                f"{float(run['decision_confidence']):.1f}%",
            ),
            ("Pipeline Status", format_compact_status(run["pipeline_status"])),
            ("Risk Score", format_risk_score_display(run.get("risk_score"))),
            ("Latency", f"{float(run['execution_time_ms']):.1f} ms"),
        ],
        columns=3,
    )

    st.info(f"**Executive Narrative:** {run.get('summary_narrative', 'N/A')}")

    reasons = run.get("reasons") or []
    if reasons:
        with st.expander(f"Decision Reasons ({len(reasons)})", expanded=True):
            for r in reasons:
                st.write(
                    f"- **`[{r.get('code')}]` ({r.get('category')} / `{r.get('severity')}`)** "
                    f"— {r.get('description')}"
                )
                if r.get("evidence"):
                    st.caption(
                        f"Evidence: {mask_extracted_value('evidence', r.get('evidence'))}"
                    )

    if run.get("review_reasons"):
        with st.expander(
            f"Manual Review Triggers ({len(run['review_reasons'])})", expanded=False
        ):
            for rr in run["review_reasons"]:
                st.write(f"- {rr}")

    render_factor_cards(
        positive_factors=run.get("positive_factors") or [],
        negative_factors=run.get("negative_factors") or [],
        blocking_factors=run.get("blocking_factors") or [],
    )

    st.markdown("**Cross-Agent Consistency Verification**")
    render_conflicts_panel(run.get("consistency_conflicts") or [])

    linked_reviews = get_review_history_for_run(run["run_id"])
    st.markdown("**Linked Human Review Events**")
    if linked_reviews:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Review ID": ev["review_id"],
                        "Transition": f"{ev['previous_review_status']} -> {ev['new_review_status']}",
                        "Human Decision": (
                            format_compact_status(ev["human_decision"])
                            if ev.get("human_decision")
                            else "Not yet recorded"
                        ),
                        "Reviewer ID": ev["reviewer_id"],
                        "Reason": ev["decision_reason"],
                        "Correction": (
                            f"Yes ({ev.get('parent_review_id')})"
                            if ev.get("is_correction")
                            else "No"
                        ),
                        "Timestamp (UTC)": _format_utc_short(ev["review_timestamp"]),
                    }
                    for ev in linked_reviews
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No human review events linked to this run yet (Pending).")

    snap = run.get("details_snapshot") or {}
    exec_details = snap.get("agent_execution_details") or {}
    with st.expander(
        "Technical Telemetry & Persisted Agent Snapshots (Masked)", expanded=False
    ):
        if exec_details:
            agent_rows = [
                {
                    "Agent": k,
                    "Status": v.get("status"),
                    "Success": v.get("success"),
                    "Output Available": v.get("output_available"),
                    "Latency (ms)": v.get("duration_ms"),
                    "Error": v.get("error") or "None",
                }
                for k, v in sorted(exec_details.items())
            ]
            st.dataframe(pd.DataFrame(agent_rows), width="stretch", hide_index=True)
        elif run.get("agent_statuses"):
            agent_rows = [
                {"Agent": k, "Status": v}
                for k, v in sorted(run["agent_statuses"].items())
            ]
            st.dataframe(pd.DataFrame(agent_rows), width="stretch", hide_index=True)

        if snap:
            t1, t2, t3, t4 = st.tabs(
                ["Eligibility", "Risk", "Fraud", "Document Summary"]
            )
            with t1:
                st.json(snap.get("eligibility") or {"status": "UNAVAILABLE"})
            with t2:
                st.json(snap.get("risk") or {"status": "UNAVAILABLE"})
            with t3:
                st.json(snap.get("anomaly") or {"status": "UNAVAILABLE"})
            with t4:
                st.json(snap.get("document_package") or {"status": "UNAVAILABLE"})
