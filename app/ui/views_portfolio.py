"""Dashboard (Overview), Applications Registry, Application Workspace & Audit Trail Views."""

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
    _esc,
    format_compact_status,
    format_inr,
    format_risk_score_display,
    get_theme_tokens,
    render_alert_box,
    render_banking_table,
    render_conflicts_panel,
    render_empty_state,
    render_factor_cards,
    render_human_vs_ai_summary_panel,
    render_kpi_row,
    render_kv_grid,
    render_page_header,
    render_pipeline_visual,
    render_recommendation_badge,
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
    can_role_access_page,
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
    """Render portfolio KPIs, visual application pipeline, priority tasks, and recent cases."""
    auth_user = get_authenticated_ui_user()
    active_role = auth_user.role if auth_user is not None else None
    can_create_app = can_role_access_page(active_role, "New Application")

    greeting = (
        f"Welcome back, {auth_user.full_name or auth_user.username}"
        if auth_user is not None
        else "Portfolio Overview"
    )
    head_left, head_right = st.columns([3.4, 1.2], vertical_alignment="bottom")
    with head_left:
        render_page_header(
            "Workspace",
            greeting,
            "Portfolio health, live underwriting stages, and priority cases requiring attention.",
            breadcrumbs=["Workspace", "Overview"],
        )
    with head_right:
        if can_create_app and st.button(
            "New Application",
            type="primary",
            icon=":material/add:",
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
    latest_by_app = {r["application_id"]: r for r in latest_all}
    all_queue = list_review_queue(
        applicant_catalog_by_id=catalog_map, include_finalized=True
    )
    queue_by_app = {item["applicant_id"]: item for item in all_queue}
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
    human_approved = review_metrics["approved_by_underwriter"]
    ai_approved = metrics["approved_applications"]

    render_kpi_row(
        [
            {
                "label": "Total Applications",
                "value": total_tracked,
                "meta": f"{len(submitted_apps)} submitted · {len(catalog)} in catalog",
                "accent": "indigo",
            },
            {
                "label": "Completed Evaluations",
                "value": metrics["evaluated_completed_applications"],
                "meta": (
                    f"{failed_excluded} failed run(s) excluded"
                    if failed_excluded
                    else "Latest completed run per case"
                ),
                "accent": "teal",
            },
            {
                "label": "Pending Human Reviews",
                "value": pending_human,
                "meta": f"{review_metrics['pending_reviews']} awaiting claim · {review_metrics['in_progress']} active",
                "accent": "amber",
            },
            {
                "label": "Approved Applications",
                "value": human_approved,
                "meta": f"{ai_approved} AI recommended approve",
                "accent": "coral" if failed_excluded > 0 else "teal",
            },
        ]
    )

    if audit_sum["total_runs"] == 0:
        render_empty_state(
            "No Underwriting Activity Yet",
            "Start a new application using the guided wizard or run baseline evaluations on synthetic test packages.",
        )
        can_seed = can_role_access_page(active_role, "New Application")
        if can_seed:
            st.write("")
            if st.button(
                "Run Sample Baseline Cohort Evaluations (APP0001–APP0010)",
                key="dash_seed_sample",
                icon=":material/play_arrow:",
            ):
                with st.spinner("Evaluating synthetic baseline cases..."):
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

    # ------------------------------------------------------------------
    # Application Pipeline Stage Distribution (strictly from tracked SQLite data)
    # ------------------------------------------------------------------
    tokens = get_theme_tokens()
    stage_counts = {
        "awaiting_run": 0,
        "incomplete_or_failed": 0,
        "manual_review": 0,
        "ai_approved": 0,
        "human_finalized": 0,
    }
    priority_tasks: List[Dict[str, str]] = []

    for aid in sorted(tracked_ids):
        sub = next((a for a in submitted_apps if a["applicant_id"] == aid), None)
        run = latest_by_app.get(aid)
        q_item = queue_by_app.get(aid)
        rec = catalog_map.get(aid) or sub or {}
        app_name = str(rec.get("name", "Unknown"))

        if run is None:
            stage_counts["awaiting_run"] += 1
            priority_tasks.append(
                {
                    "applicant_id": aid,
                    "name": app_name,
                    "badge": "Awaiting Evaluation",
                    "reason": "Submitted dossier has not been evaluated yet",
                    "target_page": "Application Details",
                    "run_id": "",
                    "cta": "Open",
                    "priority": "2",
                }
            )
            continue

        hum_status = (
            q_item.get("human_review_status")
            if q_item
            else ReviewStatus.PENDING.value
        )
        is_final = hum_status in {
            ReviewStatus.APPROVED.value,
            ReviewStatus.REJECTED.value,
        }
        pipe_status = str(run.get("pipeline_status", "")).upper()
        docs_missing = int(run.get("documents_missing_count") or 0)
        ai_rec = str(run.get("recommendation", "MANUAL_REVIEW")).upper()

        if is_final:
            stage_counts["human_finalized"] += 1
        elif pipe_status == "FAILED":
            stage_counts["incomplete_or_failed"] += 1
            priority_tasks.append(
                {
                    "applicant_id": aid,
                    "name": app_name,
                    "badge": "Pipeline Failed",
                    "reason": "Automated evaluation interrupted; manual triage required",
                    "target_page": "Application Details",
                    "run_id": run["run_id"],
                    "cta": "Triage",
                    "priority": "0",
                }
            )
        elif docs_missing > 0 or pipe_status == "PARTIAL_SUCCESS":
            stage_counts["incomplete_or_failed"] += 1
            priority_tasks.append(
                {
                    "applicant_id": aid,
                    "name": app_name,
                    "badge": "Incomplete Docs",
                    "reason": f"{docs_missing} required document(s) missing verification",
                    "target_page": "Document Review",
                    "run_id": run["run_id"],
                    "cta": "Verify",
                    "priority": "1",
                }
            )
        elif ai_rec == "APPROVE":
            stage_counts["ai_approved"] += 1
        else:
            stage_counts["manual_review"] += 1

        if not is_final and pipe_status != "FAILED":
            rev_target = (
                "Underwriter Review Queue"
                if can_role_access_page(active_role, "Underwriter Review Queue")
                else "Application Details"
            )
            if docs_missing == 0 and pipe_status == "SUCCESS":
                priority_tasks.append(
                    {
                        "applicant_id": aid,
                        "name": app_name,
                        "badge": format_compact_status(hum_status),
                        "reason": (
                            f"AI recommended {format_compact_status(ai_rec)}; awaiting human review"
                        ),
                        "target_page": rev_target,
                        "run_id": run["run_id"],
                        "cta": "Review",
                        "priority": "3" if ai_rec == "APPROVE" else "2",
                    }
                )

    priority_tasks.sort(key=lambda t: (t["priority"], t["applicant_id"]))

    pipe_col, task_col = st.columns([1.25, 1.0], gap="medium")

    with pipe_col:
        with st.container(border=True):
            render_section_heading(
                "Application Pipeline",
                f"Active distribution across {total_tracked} tracked loan application(s)",
            )
            render_pipeline_visual(
                [
                    {
                        "label": "Awaiting Eval",
                        "count": stage_counts["awaiting_run"],
                        "color": tokens["muted"],
                    },
                    {
                        "label": "Attention",
                        "count": stage_counts["incomplete_or_failed"],
                        "color": tokens["coral"],
                    },
                    {
                        "label": "In Review",
                        "count": stage_counts["manual_review"],
                        "color": tokens["amber"],
                    },
                    {
                        "label": "AI Approve",
                        "count": stage_counts["ai_approved"],
                        "color": tokens["teal"],
                    },
                    {
                        "label": "Finalized",
                        "count": stage_counts["human_finalized"],
                        "color": tokens["primary"],
                    },
                ]
            )
            st.caption(
                f"Human Decisions Recorded: {human_approved} Approved · {review_metrics['rejected_by_underwriter']} Rejected · "
                f"Avg Pipeline Latency: {audit_sum['avg_latency_ms']:.1f} ms"
            )

    with task_col:
        with st.container(border=True):
            render_section_heading(
                "Priority Tasks",
                f"{len(priority_tasks)} item(s) requiring verification, triage, or review",
            )
            if not priority_tasks:
                render_empty_state(
                    "All Clear",
                    "No applications currently await verification, triage, or human review.",
                )
            else:
                for idx, task in enumerate(priority_tasks[:4]):
                    c_info, c_btn = st.columns([3.0, 1.0], vertical_alignment="center")
                    with c_info:
                        pill = render_status_pill(task["badge"])
                        st.markdown(
                            f"**{_esc(task['applicant_id'])}** · {_esc(task['name'])}<br/>"
                            f"{pill} <span style='font-size:0.78rem;color:var(--bank-muted);'>{_esc(task['reason'])}</span>",
                            unsafe_allow_html=True,
                        )
                    with c_btn:
                        if st.button(
                            task["cta"],
                            key=f"dash_task_btn_{idx}_{task['applicant_id']}",
                            width="stretch",
                        ):
                            navigate_to(
                                task["target_page"],
                                applicant_id=task["applicant_id"],
                                run_id=task["run_id"] or None,
                            )
                            st.rerun()
                    if idx < min(len(priority_tasks), 4) - 1:
                        st.markdown(
                            "<hr style='margin:0.35rem 0;'>",
                            unsafe_allow_html=True,
                        )

    # ------------------------------------------------------------------
    # Recent Applications Table + Contextual Open
    # ------------------------------------------------------------------
    with st.container(border=True):
        rec_head, rec_cta = st.columns([3.2, 1.1], vertical_alignment="center")
        with rec_head:
            render_section_heading(
                "Recent Applications",
                "Most recently evaluated or submitted loan cases (distinct AI recommendations vs human status)",
            )
        with rec_cta:
            if st.button(
                "All Applications",
                key="dash_view_all_apps",
                width="stretch",
            ):
                navigate_to("Applications")
                st.rerun()

        recent_rows: List[List[str]] = []
        recent_ids: List[str] = []
        seen_ids: set[str] = set()

        for r in latest_all:
            aid = r["application_id"]
            if aid in seen_ids:
                continue
            seen_ids.add(aid)
            rec = catalog_map.get(aid) or get_applicant_record(aid) or {}
            q_item = queue_by_app.get(aid)
            hum_status = (
                q_item.get("human_review_status")
                if q_item
                else ReviewStatus.PENDING.value
            )
            missing_cnt = int(r.get("documents_missing_count") or 0)
            doc_summary = (
                f"{r.get('documents_found_count', 0)} Verified"
                if missing_cnt == 0
                else f"Missing {missing_cnt}"
            )
            recent_ids.append(aid)
            recent_rows.append(
                [
                    aid,
                    str(rec.get("name", "N/A")),
                    format_inr(rec.get("loan_amount")),
                    doc_summary,
                    format_compact_status(r.get("recommendation")),
                    format_compact_status(hum_status),
                    _format_utc_short(r.get("timestamp")),
                ]
            )
            if len(recent_rows) >= 8:
                break

        for sub in submitted_apps:
            if len(recent_rows) >= 8:
                break
            aid = sub["applicant_id"]
            if aid in seen_ids:
                continue
            seen_ids.add(aid)
            recent_ids.append(aid)
            recent_rows.append(
                [
                    aid,
                    str(sub.get("name", "N/A")),
                    format_inr(sub.get("loan_amount")),
                    "Not Run",
                    "Not Evaluated",
                    "Pending",
                    _format_utc_short(sub.get("created_at")),
                ]
            )

        render_banking_table(
            headers=[
                "Application ID",
                "Applicant",
                "Loan Amount",
                "Documents",
                "AI Recommendation",
                "Human Status",
                "Updated (UTC)",
            ],
            rows=recent_rows,
            pill_columns={4, 5},
            empty_message="No applications have been submitted or evaluated yet.",
        )

        if recent_ids:
            o_sel, o_btn = st.columns([3.0, 1.1], vertical_alignment="bottom")
            with o_sel:
                open_aid = st.selectbox(
                    "Open Application Workspace",
                    options=recent_ids,
                    format_func=lambda a: (
                        f"{a} — {(catalog_map.get(a) or {}).get('name', 'N/A')}"
                    ),
                    key="dash_open_ws_select",
                )
            with o_btn:
                if st.button(
                    "Open Workspace",
                    key="dash_btn_open_ws",
                    width="stretch",
                ):
                    navigate_to("Application Details", applicant_id=open_aid)
                    st.rerun()


def render_applications_directory_view() -> None:
    """Render filterable applications registry backed by SQLite & catalog."""
    render_page_header(
        "Workspace",
        "Applications",
        "Search and filter loan applications across submission sources, risk tiers, and review states.",
        breadcrumbs=["Workspace", "Applications"],
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
            "Rows to Display", options=[20, 50, 100, 200], index=0, key="apps_page_limit"
        )

    rows: List[List[str]] = []
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
            [
                aid,
                name,
                source.title(),
                format_inr(rec.get("loan_amount")),
                format_compact_status(latest_rec) if latest else "Not Evaluated",
                format_compact_status(latest["risk_category"]) if latest else "—",
                format_compact_status(case_rev["human_review_status"])
                if latest
                else "—",
                format_compact_status(case_rev["human_decision"])
                if case_rev.get("human_decision")
                else ("Pending" if latest else "—"),
                latest_ts[:10] if latest_ts != "—" else "—",
            ]
        )

    if not rows:
        render_empty_state(
            "No Matching Applications",
            "No applications match your active search or status filters.",
        )
        return

    st.caption(f"Showing {min(len(rows), page_size)} of {len(rows)} application(s)")
    render_banking_table(
        headers=[
            "ID",
            "Applicant",
            "Source",
            "Loan Amount",
            "AI Rec",
            "Risk",
            "Human Review",
            "Final Decision",
            "Updated",
        ],
        rows=rows[:page_size],
        pill_columns={4, 5, 6, 7},
    )

    with st.container(border=True):
        render_section_heading(
            "Open Application Workspace",
            "Inspect dossier tabs, documents, underwriting analysis, or human review queue",
        )
        sel_col, btn_det, btn_res, btn_rev, btn_doc = st.columns(
            [2.2, 1.1, 1, 1, 1], vertical_alignment="bottom"
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
            if st.button(
                "Workspace", key="apps_go_details", type="primary", width="stretch"
            ):
                navigate_to(
                    "Application Details", applicant_id=target_id, run_id=target_run_id
                )
                st.rerun()
        with btn_res:
            if st.button("Underwriting", key="apps_go_results", width="stretch"):
                navigate_to(
                    "Underwriting Results",
                    applicant_id=target_id,
                    run_id=target_run_id,
                )
                st.rerun()
        with btn_rev:
            if st.button("Human Review", key="apps_go_review", width="stretch"):
                navigate_to(
                    "Underwriter Review Queue",
                    applicant_id=target_id,
                    run_id=target_run_id,
                )
                st.rerun()
        with btn_doc:
            if st.button("Documents", key="apps_go_docs", width="stretch"):
                navigate_to(
                    "Document Review", applicant_id=target_id, run_id=target_run_id
                )
                st.rerun()


def render_application_details_view(
    selected_app_id: Optional[str] = None,
    applicant_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Render coherent 6-tab Application Workspace separating Overview, Profile, Docs, AI, Review & Activity."""
    render_page_header(
        "Workspace",
        "Application Workspace",
        "Coherent per-case workspace separating applicant profile, document evidence, AI recommendation, and human review.",
        breadcrumbs=["Workspace", "Applications", "Application Workspace"],
    )

    catalog = load_applicant_catalog()
    app_ids = [rec["applicant_id"] for rec in catalog]
    active_id = selected_app_id or st.session_state.get(STATE_SELECTED_APP_ID)
    if app_ids:
        idx = app_ids.index(active_id) if active_id in app_ids else 0
        chosen_id = st.selectbox(
            "Select Application Case",
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
        render_empty_state(
            "No Application Found",
            "Create a loan application in New Application to populate the workspace.",
        )
        return

    auth_user = get_authenticated_ui_user()
    active_role = auth_user.role if auth_user is not None else None
    case_summary = get_case_review_summary(chosen_id)
    history = get_applicant_run_history(chosen_id)
    latest_run = history[0] if history else None
    latest_snap = (latest_run.get("details_snapshot") or {}) if latest_run else {}
    latest_doc_pkg = latest_snap.get("document_package") or {}

    app_status_raw = data.get("application_status") or (
        "UNDERWRITTEN"
        if latest_run and latest_run.get("pipeline_status") == "SUCCESS"
        else ("SYNTHETIC_CATALOG" if not latest_run else latest_run.get("pipeline_status"))
    )
    ai_rec_raw = case_summary.get("ai_recommendation", "NOT_EVALUATED")
    rev_status_raw = case_summary.get("human_review_status", "PENDING")

    if latest_doc_pkg:
        found_c = len(latest_doc_pkg.get("documents_found", []))
        miss_c = len(latest_doc_pkg.get("documents_missing", []))
        doc_summary_str = (
            f"{found_c} Verified (Complete)"
            if miss_c == 0
            else f"{found_c} Processed · {miss_c} Missing"
        )
    elif has_physical_document_package(chosen_id):
        doc_summary_str = "Synthetic Package Available"
    else:
        doc_summary_str = "Not Uploaded / Missing"

    # Determine single clear contextual next action
    if latest_run is None:
        next_label = "Run Underwriting"
        next_action = "RUN_PIPELINE"
    elif (
        latest_run.get("pipeline_status") == "FAILED"
        or int(latest_run.get("documents_missing_count") or 0) > 0
    ):
        next_label = "Verify Documents"
        next_action = "GOTO_DOCS"
    elif rev_status_raw in {
        ReviewStatus.PENDING.value,
        ReviewStatus.IN_REVIEW.value,
        ReviewStatus.ADDITIONAL_INFO_REQUESTED.value,
        ReviewStatus.INVESTIGATION_REQUIRED.value,
    } and can_role_access_page(active_role, "Underwriter Review Queue"):
        next_label = "Open Human Review"
        next_action = "GOTO_REVIEW"
    else:
        next_label = "View Underwriting"
        next_action = "GOTO_RESULTS"

    # Top Workspace Summary Card
    with st.container(border=True):
        top_l, top_r = st.columns([3.2, 1.2], vertical_alignment="center")
        with top_l:
            app_pill = render_status_pill(format_compact_status(app_status_raw), "info")
            ai_pill = render_status_pill(
                f"AI: {format_compact_status(ai_rec_raw)}",
                "teal" if ai_rec_raw == "APPROVE" else None,
            )
            rev_pill = render_status_pill(
                f"Review: {format_compact_status(rev_status_raw)}"
            )
            st.markdown(
                f"**{_esc(chosen_id)}** · {_esc(data.get('name', 'N/A'))} &nbsp; "
                f"{app_pill} &nbsp; {ai_pill} &nbsp; {rev_pill}<br/>"
                f"<span style='font-size:0.82rem;color:var(--bank-muted);'>"
                f"Loan {format_inr(data.get('loan_amount'))} · "
                f"Documents: {_esc(doc_summary_str)} · "
                f"Source: {_esc(str(data.get('source', 'synthetic')).title())}</span>",
                unsafe_allow_html=True,
            )
        with top_r:
            if st.button(
                next_label,
                key="ws_contextual_next_action",
                type="primary",
                width="stretch",
            ):
                if next_action == "RUN_PIPELINE":
                    try:
                        with st.spinner(f"Running underwriting pipeline for {chosen_id}..."):
                            out = submit_application_and_underwrite(
                                applicant=Applicant.model_validate(data),
                                staged_uploads=[],
                                use_existing_package_if_empty=has_physical_document_package(
                                    chosen_id
                                ),
                                allow_duplicate=True,
                            )
                        store_live_result(chosen_id, out)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Underwriting execution failed safely: {exc}")
                elif next_action == "GOTO_DOCS":
                    navigate_to(
                        "Document Review",
                        applicant_id=chosen_id,
                        run_id=latest_run["run_id"] if latest_run else None,
                    )
                    st.rerun()
                elif next_action == "GOTO_REVIEW":
                    navigate_to(
                        "Underwriter Review Queue",
                        applicant_id=chosen_id,
                        run_id=latest_run["run_id"] if latest_run else None,
                    )
                    st.rerun()
                else:
                    navigate_to(
                        "Underwriting Results",
                        applicant_id=chosen_id,
                        run_id=latest_run["run_id"] if latest_run else None,
                    )
                    st.rerun()

    # 6 Coherent Workspace Sections
    t_over, t_prof, t_docs, t_uw, t_rev, t_act = st.tabs(
        [
            "Overview",
            "Applicant Profile",
            "Documents",
            "Underwriting",
            "Human Review",
            "Activity",
        ]
    )

    with t_over:
        render_section_heading(
            "Case Status Separation",
            "AI underwriting recommendations remain distinct from final human underwriter decisions",
        )
        render_human_vs_ai_summary_panel(case_summary)

        render_kv_grid(
            [
                ("Application Reference", chosen_id),
                ("Applicant Name", str(data.get("name", "N/A"))),
                ("Requested Loan Facility", format_inr(data.get("loan_amount"))),
                ("Document Package", doc_summary_str),
            ],
            columns=4,
        )
        if latest_run and latest_run.get("summary_narrative"):
            render_alert_box(
                "Latest AI Narrative",
                latest_run["summary_narrative"],
                variant="info",
            )

    with t_prof:
        render_section_heading(
            "Authoritative Applicant Profile & Loan Request",
            "Validated intake attributes persisted in SQLite or synthetic benchmark records",
        )
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
            render_section_heading("Uploaded File Receipts")
            render_banking_table(
                headers=["Filename", "Category", "Size (Bytes)", "SHA-256"],
                rows=[
                    [
                        str(f.get("filename", "doc.pdf")),
                        str(f.get("category", "auto")),
                        str(f.get("size_bytes", 0)),
                        str(f.get("sha256", ""))[:16],
                    ]
                    for f in data["uploaded_files"]
                ],
                pill_columns={1},
            )

    with t_docs:
        render_section_heading(
            "Document Verification Summary",
            "Package completeness and extracted document statuses for this application",
        )
        if latest_doc_pkg:
            render_kv_grid(
                [
                    (
                        "Intake Status",
                        format_compact_status(latest_doc_pkg.get("processing_status")),
                    ),
                    (
                        "Documents Processed",
                        str(len(latest_doc_pkg.get("documents_found", []))),
                    ),
                    (
                        "Missing Required",
                        str(len(latest_doc_pkg.get("documents_missing", []))),
                    ),
                    (
                        "OCR Triggered",
                        "Yes" if latest_doc_pkg.get("ocr_used") else "No",
                    ),
                ],
                columns=4,
            )
            found_docs = latest_doc_pkg.get("documents_found", [])
            if found_docs:
                render_banking_table(
                    headers=[
                        "File",
                        "Detected Category",
                        "Classification Status",
                        "Extraction",
                        "Pages",
                    ],
                    rows=[
                        [
                            str(d.get("filename", "doc.pdf")),
                            str(d.get("document_type", "unknown")),
                            str(d.get("classification_status", "N/A")),
                            str(d.get("extraction_method", "digital")),
                            str(d.get("page_count", 1)),
                        ]
                        for d in found_docs
                    ],
                    pill_columns={1, 2},
                )
            if latest_doc_pkg.get("documents_missing"):
                render_alert_box(
                    "Missing Mandatory Documents",
                    ", ".join(latest_doc_pkg["documents_missing"]),
                    variant="warning",
                )
            if st.button(
                "Open Document Verification Workspace",
                key="ws_open_doc_verification",
            ):
                navigate_to(
                    "Document Review",
                    applicant_id=chosen_id,
                    run_id=latest_run["run_id"] if latest_run else None,
                )
                st.rerun()
        else:
            render_empty_state(
                "No Document Package Processed Yet",
                "Upload documents in New Application or run underwriting on this dossier to verify supporting documents.",
            )

    with t_uw:
        render_section_heading(
            "Underwriting Evaluation Summary",
            "Latest automated pipeline verdict across eligibility, credit risk, and fraud checks",
        )
        if latest_run:
            c_rec, c_det = st.columns([1.2, 3.0], vertical_alignment="top")
            with c_rec:
                render_recommendation_badge(latest_run.get("recommendation"))
                st.caption(
                    f"Confidence (Heuristic): {float(latest_run.get('decision_confidence', 0.0)):.1f}%"
                )
            with c_det:
                render_kv_grid(
                    [
                        (
                            "Eligibility Status",
                            str(latest_run.get("eligibility_status", "UNAVAILABLE")),
                        ),
                        (
                            "Risk Tier",
                            str(latest_run.get("risk_category", "UNAVAILABLE")),
                        ),
                        (
                            "Risk Score",
                            format_risk_score_display(latest_run.get("risk_score")),
                        ),
                        (
                            "Pipeline Health",
                            format_compact_status(latest_run.get("pipeline_status")),
                        ),
                    ],
                    columns=4,
                )
            if latest_run.get("reasons"):
                with st.expander(
                    f"Key Decision Reasons ({len(latest_run['reasons'])})",
                    expanded=True,
                ):
                    for r in latest_run["reasons"]:
                        st.write(
                            f"- **`[{r.get('code')}]` ({r.get('category')})** — {r.get('description')}"
                        )
            b_res, b_rerun = st.columns(2)
            with b_res:
                if st.button(
                    "Open Detailed Underwriting Results",
                    key="ws_open_full_results",
                    width="stretch",
                ):
                    navigate_to(
                        "Underwriting Results",
                        applicant_id=chosen_id,
                        run_id=latest_run["run_id"],
                    )
                    st.rerun()
            with b_rerun:
                if st.button(
                    "Re-run Pipeline Evaluation",
                    key="ws_rerun_pipeline",
                    width="stretch",
                ):
                    try:
                        with st.spinner(f"Re-running pipeline for {chosen_id}..."):
                            out = submit_application_and_underwrite(
                                applicant=Applicant.model_validate(data),
                                staged_uploads=[],
                                use_existing_package_if_empty=has_physical_document_package(
                                    chosen_id
                                ),
                                allow_duplicate=True,
                            )
                        store_live_result(chosen_id, out)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Re-run failed safely: {exc}")
        else:
            render_empty_state(
                "No Underwriting Run Recorded",
                "Run automated underwriting to compute policy eligibility, credit risk, and anomaly checks.",
            )
            if st.button("Run Underwriting Now", key="details_run_now", type="primary"):
                try:
                    with st.spinner(
                        f"Running underwriting pipeline for {chosen_id}..."
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

    with t_rev:
        render_section_heading(
            "Human Review State & Actions",
            "Append-only human decisions recorded independently from automated scoring",
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
            render_alert_box(
                f"Status: {case_summary['human_review_status']}",
                f"Requested by {latest_rev.get('reviewer_id', 'reviewer')}: {req_text or 'Follow-up required.'}",
                variant="warning",
            )
            if case_summary.get("source_run_id"):
                with st.expander(
                    "Record Follow-Up Information / Return Case to Pending Review Queue",
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
                            "Upload Updated Documents in Intake Wizard",
                            key=f"details_btn_upload_new_docs_{chosen_id}",
                            width="stretch",
                        ):
                            queue_existing_applicant_for_intake(data)
                            navigate_to("New Application", applicant_id=chosen_id)
                            st.rerun()

        if can_role_access_page(active_role, "Underwriter Review Queue"):
            if st.button(
                "Open in Human Review Workbench",
                key="details_goto_review_queue",
                type="primary",
            ):
                navigate_to(
                    "Underwriter Review Queue",
                    applicant_id=chosen_id,
                    run_id=latest_run["run_id"] if latest_run else None,
                )
                st.rerun()

        rev_hist = case_summary.get("application_review_history") or []
        render_banking_table(
            headers=[
                "Review ID",
                "Timestamp",
                "AI Rec",
                "Transition",
                "Human Decision",
                "Reviewer",
                "Reason",
            ],
            rows=[
                [
                    ev["review_id"],
                    _format_utc_short(ev["review_timestamp"]),
                    format_compact_status(ev["original_ai_recommendation"]),
                    f"{format_compact_status(ev['previous_review_status'])} -> {format_compact_status(ev['new_review_status'])}",
                    (
                        format_compact_status(ev["human_decision"])
                        if ev.get("human_decision")
                        else "Pending"
                    ),
                    str(ev["reviewer_id"]),
                    str(ev["decision_reason"]),
                ]
                for ev in rev_hist
            ],
            pill_columns={2, 4},
            empty_message="No human underwriter review events recorded yet for this case.",
        )

    with t_act:
        render_section_heading(
            "Underwriting Run & Audit Activity",
            "Immutable log of all pipeline runs and review checkpoints for this application",
        )
        if not history:
            render_empty_state(
                "No Pipeline Runs Recorded",
                "No underwriting runs exist in the audit ledger for this application yet.",
            )
            return

        render_banking_table(
            headers=[
                "#",
                "Run ID",
                "Timestamp (UTC)",
                "AI Recommendation",
                "Pipeline Status",
                "Risk",
                "Latency",
            ],
            rows=[
                [
                    str(idx),
                    r["run_id"],
                    _format_utc_short(r["timestamp"]),
                    format_compact_status(r["recommendation"]),
                    format_compact_status(r["pipeline_status"]),
                    (
                        f"{format_compact_status(r['risk_category'])} ({format_risk_score_display(r.get('risk_score'))})"
                        if r.get("risk_score") is not None
                        else format_compact_status(r["risk_category"])
                    ),
                    f"{r['execution_time_ms']:.1f} ms",
                ]
                for idx, r in enumerate(history, 1)
            ],
            pill_columns={3, 4},
        )

        sel_c, b1, b2 = st.columns([2.2, 1.1, 1.1], vertical_alignment="bottom")
        with sel_c:
            selected_hist_run = st.selectbox(
                "Inspect Run Snapshot",
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
                    "Underwriting Results",
                    applicant_id=chosen_id,
                    run_id=selected_hist_run,
                )
                st.rerun()
        with b2:
            if st.button(
                "Audit Trail",
                key="details_goto_audit",
                width="stretch",
            ):
                navigate_to(
                    "Audit History", applicant_id=chosen_id, run_id=selected_hist_run
                )
                st.rerun()


def render_audit_history_view() -> None:
    """Render immutable, read-only SQLite AI & Human Review Audit Trail."""
    render_page_header(
        "Records",
        "Audit Trail",
        "Append-only compliance ledger separating AI underwriting runs and human review events.",
        breadcrumbs=["Records", "Audit Trail"],
    )

    with st.container(border=True):
        view_mode = st.radio(
            "Audit Event Stream",
            options=["All Audit Events", "AI Underwriting Runs", "Human Review Events"],
            horizontal=True,
            key="audit_event_stream_mode",
        )

        f1, f2, f3, f4, f5, f6 = st.columns(6)
        f_app = f1.text_input(
            "Applicant ID", value="", key="audit_filter_app"
        ).strip()
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
                "Human Review Events",
                "Immutable append-only human decisions and transitions (HUMAN_REVIEW_EVENT)",
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
                render_banking_table(
                    headers=[
                        "Review ID",
                        "Applicant",
                        "AI Rec",
                        "Status",
                        "Decision",
                        "Reviewer",
                        "Correction",
                        "Timestamp (UTC)",
                    ],
                    rows=[
                        [
                            ev["review_id"],
                            ev["application_id"],
                            format_compact_status(ev["original_ai_recommendation"]),
                            format_compact_status(ev["new_review_status"]),
                            (
                                format_compact_status(ev["human_decision"])
                                if ev.get("human_decision")
                                else "Pending"
                            ),
                            str(ev["reviewer_id"]),
                            (
                                f"Yes ({ev.get('parent_review_id')})"
                                if ev.get("is_correction")
                                else "No"
                            ),
                            _format_utc_short(ev["review_timestamp"]),
                        ]
                        for ev in hr_events
                    ],
                    pill_columns={2, 3, 4},
                )
                with st.expander("Interactive Grid View (Human Review Events)", expanded=False):
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
                render_empty_state(
                    "No Human Review Events",
                    "No human underwriter review events match the active filters.",
                )

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
            render_empty_state(
                "No Audited Runs",
                "No AI underwriting runs match the active filters.",
            )
            return

        st.caption(f"Showing {len(runs)} audited pipeline run(s)")
        render_banking_table(
            headers=[
                "Run ID",
                "Applicant",
                "Timestamp (UTC)",
                "AI Rec",
                "Pipeline",
                "Risk",
                "Conflicts",
                "Latency",
            ],
            rows=[
                [
                    r["run_id"],
                    r["application_id"],
                    _format_utc_short(r["timestamp"]),
                    format_compact_status(r["recommendation"]),
                    format_compact_status(r["pipeline_status"]),
                    format_compact_status(r["risk_category"]),
                    str(len(r.get("consistency_conflicts") or [])),
                    f"{r['execution_time_ms']:.1f} ms",
                ]
                for r in runs
            ],
            pill_columns={3, 4, 5},
        )
        with st.expander("Interactive Grid View (AI Pipeline Runs)", expanded=False):
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
            ("Heuristic Confidence", f"{float(run['decision_confidence']):.1f}%"),
            ("Pipeline Status", format_compact_status(run["pipeline_status"])),
            ("Risk Score", format_risk_score_display(run.get("risk_score"))),
            ("Latency", f"{float(run['execution_time_ms']):.1f} ms"),
        ],
        columns=3,
    )

    render_alert_box(
        "Executive Narrative", run.get("summary_narrative", "N/A"), variant="info"
    )

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
        render_banking_table(
            headers=["Review ID", "Transition", "Human Decision", "Reviewer", "Reason"],
            rows=[
                [
                    ev["review_id"],
                    f"{format_compact_status(ev['previous_review_status'])} -> {format_compact_status(ev['new_review_status'])}",
                    (
                        format_compact_status(ev["human_decision"])
                        if ev.get("human_decision")
                        else "Pending"
                    ),
                    ev["reviewer_id"],
                    ev["decision_reason"],
                ]
                for ev in linked_reviews
            ],
            pill_columns={2},
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
