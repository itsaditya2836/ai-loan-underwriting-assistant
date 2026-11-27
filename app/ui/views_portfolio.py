"""Portfolio Dashboard, Applications Directory, Application Details & Audit History (Stage 5).

Every screen queries actual SQLite records and read-only catalog metadata cleanly,
distinguishing applications from underwriting executions and keeping failed runs separate.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from app.database.audit import (
    get_applicant_run_history,
    get_audit_run_by_id,
    get_audit_runs,
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
    format_fraud_status_display,
    format_inr,
    format_risk_score_display,
    render_conflicts_panel,
    render_factor_cards,
    render_human_vs_ai_summary_panel,
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
    navigate_to,
    queue_existing_applicant_for_intake,
    store_live_result,
)


def render_dashboard_overview() -> None:
    """Render actual SQLite-backed portfolio metrics, trends, and recent activity."""
    st.subheader("Underwriting Portfolio Dashboard")
    st.caption(
        "Operational metrics computed strictly from SQLite records. Applications and underwriting runs "
        "are tracked independently, and failed pipeline runs are never counted as completed decisions."
    )

    metrics = compute_dashboard_metrics()
    audit_sum = metrics["audit_summary"]

    st.markdown(
        "#### Unique Application Outcomes (Latest Completed Run Per Application)"
    )
    a1, a2, a3, a4, a5, a6 = st.columns(6)
    a1.metric("Submitted Apps (DB)", metrics["submitted_applications_count"])
    a2.metric("Completed Evaluated", metrics["evaluated_completed_applications"])
    a3.metric("Approved", metrics["approved_applications"])
    a4.metric("Rejected", metrics["rejected_applications"])
    a5.metric("Manual Review", metrics["manual_review_applications"])
    a6.metric("Pending / Incomplete", metrics["incomplete_or_pending_applications"])

    st.markdown("#### Pipeline Execution & Audit Run Metrics")
    r1, r2, r3, r4, r5 = st.columns(5)
    r1.metric("Total Underwriting Runs", audit_sum["total_runs"])
    r2.metric(
        "Completed Runs", audit_sum.get("completed_runs_count", audit_sum["total_runs"])
    )
    r3.metric("Failed Pipeline Runs", audit_sum.get("failed_runs_count", 0))
    r4.metric("Avg Confidence (Heuristic)", f"{audit_sum['avg_confidence']:.1f}%")
    r5.metric("Avg Pipeline Latency", f"{audit_sum['avg_latency_ms']:.1f} ms")

    review_metrics = compute_review_queue_metrics(
        list_review_queue(include_finalized=True)
    )
    st.markdown("#### Human Underwriter Review Queue Status (Separate from AI Runs)")
    h1, h2, h3, h4, h5, h6 = st.columns(6)
    h1.metric("Pending Reviews", review_metrics["pending_reviews"])
    h2.metric("In Review", review_metrics["in_progress"])
    h3.metric("Human Approved", review_metrics["approved_by_underwriter"])
    h4.metric("Human Rejected", review_metrics["rejected_by_underwriter"])
    h5.metric("Info Requested", review_metrics["additional_info_requested"])
    h6.metric("Investigation Req.", review_metrics["investigation_required"])

    if audit_sum["total_runs"] == 0:
        st.info(
            "No underwriting runs are persisted in SQLite yet. Submit a new application in **New Application**, "
            "or optionally run baseline evaluations across synthetic test packages below."
        )
        if st.button(
            "Run Sample Baseline Cohort Evaluations (APP0001–APP0010)",
            key="dash_seed_sample",
        ):
            with st.spinner(
                "Executing sample synthetic applications through Stage 4 pipeline..."
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
                        )
                        store_live_result(aid, out)
            st.rerun()
        return

    st.markdown("---")
    c_left, c_right = st.columns(2)
    with c_left:
        st.markdown("#### Completed Application Decision Distribution")
        dec_df = pd.DataFrame(
            [
                {"Decision": k, "Applications": v}
                for k, v in metrics["completed_decision_distribution"].items()
            ]
        )
        st.bar_chart(dec_df.set_index("Decision"))

        st.markdown("#### Daily Underwriting Activity Trend")
        trends = metrics["daily_trends"]
        if trends:
            t_df = pd.DataFrame(trends).set_index("run_date")[
                ["approved", "rejected", "manual_review", "failed"]
            ]
            st.bar_chart(t_df)
        else:
            st.caption("No daily trend records available yet.")

    with c_right:
        st.markdown("#### Risk Category Distribution (Completed Applications)")
        risk_dist = metrics["completed_risk_distribution"]
        risk_df = pd.DataFrame(
            [{"Risk Category": k, "Applications": v} for k, v in risk_dist.items()]
        )
        st.bar_chart(risk_df.set_index("Risk Category"))

        st.markdown("#### Pipeline Lifecycle Status Breakdown")
        p_dist = audit_sum.get("pipeline_status_distribution", {})
        p_df = pd.DataFrame(
            [{"Pipeline Status": k, "Runs": v} for k, v in p_dist.items()]
        )
        st.bar_chart(p_df.set_index("Pipeline Status"))

    # Recent Underwriting Activity Table + Filter
    st.markdown("---")
    st.markdown("#### Recent Underwriting Activity")
    rf1, rf2 = st.columns(2)
    rec_filter = rf1.selectbox(
        "Filter Activity Recommendation",
        options=["ALL", "APPROVE", "REJECT", "MANUAL_REVIEW"],
        key="dash_recent_rec_filter",
    )
    status_filter = rf2.selectbox(
        "Filter Pipeline Status",
        options=["ALL", "SUCCESS", "PARTIAL_SUCCESS", "FAILED"],
        key="dash_recent_status_filter",
    )

    recent_filtered = get_audit_runs(
        recommendation=None if rec_filter == "ALL" else rec_filter,
        pipeline_status=None if status_filter == "ALL" else status_filter,
        limit=25,
    )
    if recent_filtered:
        rows = []
        for r in recent_filtered:
            rows.append(
                {
                    "Run ID": r["run_id"],
                    "Applicant": r["application_id"],
                    "Timestamp (UTC)": r["timestamp"][:19].replace("T", " "),
                    "Decision": format_decision_label(r["recommendation"]),
                    "Pipeline Status": r["pipeline_status"],
                    "Risk Category": r["risk_category"],
                    "Risk Score": format_risk_score_display(r.get("risk_score")),
                    "Fraud Status": format_fraud_status_display(
                        r.get("anomaly_severity")
                    ),
                }
            )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("No underwriting runs match the active filters.")


def render_applications_directory_view() -> None:
    """Render unique applications list backed by SQLite & read-only synthetic catalog."""
    st.subheader("Applications & Application History")
    st.caption(
        "Inspect persisted loan applications alongside their underwriting run counts and latest run state. "
        "Repeated runs are aggregated cleanly without duplicate join rows."
    )

    catalog = load_applicant_catalog()
    all_runs = get_audit_runs(limit=1000)
    runs_by_app: Dict[str, List[Dict[str, Any]]] = {}
    for run in all_runs:
        runs_by_app.setdefault(run["application_id"], []).append(run)

    # Filter bar
    f1, f2, f3, f4 = st.columns(4)
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

    # Date filter row
    d1, d2, d3 = st.columns([1, 1, 2])
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
            latest["timestamp"][:19].replace("T", " ")
            if latest
            else (rec.get("created_at", "")[:19].replace("T", " ") or "—")
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
                "Applicant Ref": aid,
                "Name": name,
                "Source": source,
                "Employment": str(rec.get("employment_type", "N/A")),
                "Loan Request": format_inr(rec.get("loan_amount")),
                "Runs": len(app_runs),
                "Latest Run ID": latest["run_id"] if latest else "—",
                "Timestamp (UTC)": latest_ts,
                "Latest AI Rec": (
                    format_decision_label(latest_rec) if latest else "Not Evaluated"
                ),
                "Pipeline Status": latest_pipe,
                "Human Review Status": (
                    case_rev["human_review_status"] if latest else "N/A"
                ),
                "Final Human Decision": case_rev.get("human_decision")
                or ("Not yet recorded" if latest else "—"),
                "Risk Category": latest["risk_category"] if latest else "—",
            }
        )

    if not rows:
        st.info("No applications match your active filters.")
        return

    page_size = st.selectbox(
        "Rows to Display", options=[20, 50, 100, 200], index=0, key="apps_page_limit"
    )
    st.dataframe(pd.DataFrame(rows[:page_size]), width="stretch", hide_index=True)

    st.markdown("#### Quick Application Navigation")
    sel_col, btn_det, btn_res, btn_rev, btn_doc = st.columns([2.2, 1, 1, 1, 1])
    with sel_col:
        target_id = st.selectbox(
            "Select Application Reference",
            options=matching_ids,
            key="apps_quick_target",
        )
    latest_for_target = runs_by_app.get(target_id, [])
    target_run_id = latest_for_target[0]["run_id"] if latest_for_target else None
    with btn_det:
        st.write("")
        st.write("")
        if st.button("Application Details", key="apps_go_details", width="stretch"):
            navigate_to(
                "Application Details", applicant_id=target_id, run_id=target_run_id
            )
            st.rerun()
    with btn_res:
        st.write("")
        st.write("")
        if st.button("Underwriting Results", key="apps_go_results", width="stretch"):
            navigate_to(
                "Underwriting Results", applicant_id=target_id, run_id=target_run_id
            )
            st.rerun()
    with btn_rev:
        st.write("")
        st.write("")
        if st.button("Review Queue", key="apps_go_review", width="stretch"):
            navigate_to(
                "Underwriter Review Queue", applicant_id=target_id, run_id=target_run_id
            )
            st.rerun()
    with btn_doc:
        st.write("")
        st.write("")
        if st.button("Document Review", key="apps_go_docs", width="stretch"):
            navigate_to("Document Review", applicant_id=target_id, run_id=target_run_id)
            st.rerun()


def render_application_details_view(
    selected_app_id: Optional[str] = None,
    applicant_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Render full authoritative dossier and multi-run history for a selected applicant."""
    st.subheader("Application Details & Run History")

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

    st.markdown(
        f"**Applicant Reference:** `{chosen_id}` | **Source:** `{data.get('source', 'synthetic')}` | "
        f"**Application Status:** `{data.get('application_status', 'SYNTHETIC_CATALOG')}`"
    )

    st.markdown("#### Authoritative Profile & Loan Request")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Applicant Name", data.get("name", "N/A"))
    c2.metric("Age", f"{data.get('age', 'N/A')} yrs")
    c3.metric("Employment Type", str(data.get("employment_type", "N/A")))
    c4.metric("Employment Tenure", f"{data.get('employment_years', 'N/A')} yrs")

    f1, f2, f3, f4 = st.columns(4)
    f1.metric("Monthly Income", format_inr(data.get("monthly_income")))
    f2.metric("Existing Monthly EMI", format_inr(data.get("existing_emi")))
    f3.metric("Verifiable Bank Balance", format_inr(data.get("bank_balance")))
    f4.metric("Credit Score", data.get("credit_score", "N/A"))

    l1, l2, l3, l4 = st.columns(4)
    l1.metric("Requested Loan Amount", format_inr(data.get("loan_amount")))
    l2.metric("Loan Tenure", f"{data.get('loan_tenure', 'N/A')} months")
    l3.metric(
        "Monthly Expenses",
        (
            format_inr(data.get("monthly_expenses"))
            if data.get("monthly_expenses") is not None
            else "Not Provided"
        ),
    )
    dep = data.get("number_of_dependents")
    l4.metric("Dependents", str(dep) if dep is not None else "Not Provided")

    if data.get("uploaded_files"):
        st.markdown(
            "#### Uploaded Document Metadata (Temp Content Cleaned After Execution)"
        )
        st.dataframe(
            pd.DataFrame(data["uploaded_files"]),
            width="stretch",
            hide_index=True,
        )

    st.markdown("---")
    case_summary = get_case_review_summary(chosen_id)
    st.markdown(
        "#### Underwriting Decision Status Separation (AI vs Pipeline vs Human Review)"
    )
    render_human_vs_ai_summary_panel(case_summary)

    # Surface active Additional Information Requested / Investigation Instructions prominently
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
                        "Upload Updated Documents in New Application →",
                        key=f"details_btn_upload_new_docs_{chosen_id}",
                        width="stretch",
                    ):
                        queue_existing_applicant_for_intake(data)
                        navigate_to("New Application", applicant_id=chosen_id)
                        st.rerun()

    st.markdown("---")
    st.markdown("#### Persisted AI Underwriting Run History")
    history = get_applicant_run_history(chosen_id)
    if not history:
        st.info("No underwriting runs recorded yet for this application.")
        if st.button("Run Underwriting Now →", key="details_run_now", type="primary"):
            try:
                with st.spinner(
                    f"Running Stage 4 underwriting pipeline for {chosen_id}..."
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
            "Run #": idx,
            "Run ID": r["run_id"],
            "Timestamp (UTC)": r["timestamp"][:19].replace("T", " "),
            "Decision": format_decision_label(r["recommendation"]),
            "Confidence": f"{r['decision_confidence']:.1f}%",
            "Pipeline Status": r["pipeline_status"],
            "Risk Category": r["risk_category"],
            "Risk Score": format_risk_score_display(r.get("risk_score")),
            "Fraud Severity": format_fraud_status_display(r.get("anomaly_severity")),
            "Latency": f"{r['execution_time_ms']:.1f} ms",
        }
        for idx, r in enumerate(history, 1)
    ]
    st.dataframe(pd.DataFrame(hist_rows), width="stretch", hide_index=True)

    selected_hist_run = st.selectbox(
        "Inspect Historical Run",
        options=[r["run_id"] for r in history],
        key="details_hist_run_select",
    )
    b1, b2, b3 = st.columns(3)
    with b1:
        if st.button(
            "Open in Underwriting Results →",
            key="details_goto_results",
            width="stretch",
        ):
            navigate_to(
                "Underwriting Results", applicant_id=chosen_id, run_id=selected_hist_run
            )
            st.rerun()
    with b2:
        if st.button(
            "Open in Underwriter Review Queue →",
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
            "Open in Audit History →",
            key="details_goto_audit",
            width="stretch",
        ):
            navigate_to(
                "Audit History", applicant_id=chosen_id, run_id=selected_hist_run
            )
            st.rerun()

    st.markdown("#### Append-Only Human Review History")
    rev_hist = case_summary.get("application_review_history") or []
    if rev_hist:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Review ID": ev["review_id"],
                        "Source Run": ev["source_run_id"],
                        "Timestamp (UTC)": str(ev["review_timestamp"])[:19].replace(
                            "T", " "
                        ),
                        "Original AI Rec": ev["original_ai_recommendation"],
                        "Transition": f"{ev['previous_review_status']} → {ev['new_review_status']}",
                        "Human Decision": ev.get("human_decision")
                        or "Not yet recorded",
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
    st.subheader("Immutable Audit History & Human Review Ledger")
    st.caption(
        "Read-only compliance ledger combining AI pipeline executions (`underwriting_runs`) and "
        "append-only human underwriter review events (`human_review_events`). Editing or deleting historical audit records is prohibited."
    )

    view_mode = st.radio(
        "Audit Stream Filter",
        options=["All Audit Events", "AI Underwriting Runs", "Human Review Events"],
        horizontal=True,
        key="audit_event_stream_mode",
    )

    f1, f2, f3, f4, f5, f6 = st.columns(6)
    f_app = f1.text_input(
        "Applicant Ref Filter", value="", key="audit_filter_app"
    ).strip()
    f_rev_id = f2.text_input(
        "Reviewer ID Filter", value="", key="audit_filter_reviewer"
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
        st.markdown(
            "### Human Underwriter Review Events (`HUMAN_REVIEW_EVENT` — Append-Only)"
        )
        hr_events = get_human_review_events(
            application_id_prefix=f_app or None,
            reviewer_id=f_rev_id or None,
            human_decision=None,
            limit=300,
        )
        if f_rec != "ALL":
            hr_events = [
                ev for ev in hr_events if ev.get("original_ai_recommendation") == f_rec
            ]
        if f_pipe != "ALL":
            hr_events = [
                ev for ev in hr_events if ev.get("original_pipeline_status") == f_pipe
            ]

        if hr_events:
            hr_rows = [
                {
                    "Event Type": ev.get("event_type", "HUMAN_REVIEW_EVENT"),
                    "Review ID": ev["review_id"],
                    "Application": ev["application_id"],
                    "Source AI Run": ev["source_run_id"],
                    "Original AI Rec": ev["original_ai_recommendation"],
                    "Status Transition": f"{ev['previous_review_status']} → {ev['new_review_status']}",
                    "Human Decision": ev.get("human_decision") or "Not yet recorded",
                    "Reviewer ID": ev["reviewer_id"],
                    "Correction?": (
                        f"Yes (Parent: {ev.get('parent_review_id')})"
                        if ev.get("is_correction")
                        else "No"
                    ),
                    "Timestamp (UTC)": str(ev["review_timestamp"])[:19].replace(
                        "T", " "
                    ),
                }
                for ev in hr_events
            ]
            st.dataframe(pd.DataFrame(hr_rows), width="stretch", hide_index=True)

            sel_rev_id = st.selectbox(
                "Inspect Human Review Event Details (Read-Only)",
                options=[ev["review_id"] for ev in hr_events],
                key="audit_inspect_human_rev_id",
            )
            ev_obj = next(ev for ev in hr_events if ev["review_id"] == sel_rev_id)
            with st.expander(
                f"Human Review Record Snapshot: `{sel_rev_id}`", expanded=True
            ):
                rc1, rc2, rc3, rc4 = st.columns(4)
                rc1.metric("Reviewer ID", ev_obj["reviewer_id"])
                rc2.metric("Original AI Rec", ev_obj["original_ai_recommendation"])
                rc3.metric("Review Status", ev_obj["new_review_status"])
                rc4.metric(
                    "Human Decision", ev_obj.get("human_decision") or "Not yet recorded"
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
                        f"**Linked Correction Event:** Corrects prior event `{ev_obj.get('parent_review_id')}` — "
                        f"{ev_obj.get('correction_explanation')}"
                    )
        else:
            st.info("No human review events match the active filters.")

    if view_mode == "Human Review Events":
        return

    st.markdown("---")
    st.markdown("### AI Underwriting Pipeline Runs (`UNDERWRITING_RUN`)")

    runs = get_audit_runs(
        application_id_prefix=f_app or None,
        recommendation=None if f_rec == "ALL" else f_rec,
        pipeline_status=None if f_pipe == "ALL" else f_pipe,
        risk_category=None if f_risk == "ALL" else f_risk,
        anomaly_severity=None if f_anom == "ALL" else f_anom,
        limit=250,
    )

    if not runs:
        st.info("No audit records match the active filter criteria.")
        return

    st.write(f"Showing **{len(runs)}** audited runs:")
    table_rows = [
        {
            "Run ID": r["run_id"],
            "Application": r["application_id"],
            "Timestamp (UTC)": r["timestamp"][:19].replace("T", " "),
            "Final Decision": format_decision_label(r["recommendation"]),
            "Pipeline Status": r["pipeline_status"],
            "Risk Category": r["risk_category"],
            "Risk Score": format_risk_score_display(r.get("risk_score")),
            "Fraud Status": format_fraud_status_display(r.get("anomaly_severity")),
            "Conflicts": len(r.get("consistency_conflicts") or []),
            "Persisted": "Yes",
            "Latency": f"{r['execution_time_ms']:.1f} ms",
        }
        for r in runs
    ]
    st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)

    st.markdown("---")
    st.markdown("#### Inspect Individual Audit Run")
    run_ids = [r["run_id"] for r in runs]
    pref_run = st.session_state.get(STATE_SELECTED_RUN_ID)
    idx = run_ids.index(pref_run) if pref_run in run_ids else 0
    inspect_id = st.selectbox(
        "Select Run ID", options=run_ids, index=idx, key="audit_inspect_run_id"
    )
    st.session_state[STATE_SELECTED_RUN_ID] = inspect_id

    run = get_audit_run_by_id(inspect_id)
    if not run:
        st.warning("Selected audit run could not be loaded.")
        return

    render_audit_run_inspection(run)


def render_audit_run_inspection(run: Dict[str, Any]) -> None:
    """Render comprehensive read-only snapshot of a persisted underwriting audit record."""
    st.markdown(
        f"**Audit Run Snapshot:** `{run['run_id']}` (Audit Persistence: Verified in SQLite)"
    )

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Application", run["application_id"])
    m2.metric("Final Decision", format_decision_label(run["recommendation"]))
    m3.metric("Confidence (Heuristic)", f"{float(run['decision_confidence']):.1f}%")
    m4.metric("Pipeline Status", run["pipeline_status"])
    m5.metric("Risk Score", format_risk_score_display(run.get("risk_score")))
    m6.metric("Latency", f"{float(run['execution_time_ms']):.1f} ms")

    st.info(f"**Executive Narrative:**\n\n{run.get('summary_narrative', 'N/A')}")

    st.markdown("**Agent Execution Statuses:**")
    snap = run.get("details_snapshot") or {}
    exec_details = snap.get("agent_execution_details") or {}
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
            {"Agent": k, "Status": v} for k, v in sorted(run["agent_statuses"].items())
        ]
        st.dataframe(pd.DataFrame(agent_rows), width="stretch", hide_index=True)
    else:
        st.caption("No per-agent statuses captured in legacy record.")

    st.markdown("**Consistency Conflicts:**")
    render_conflicts_panel(run.get("consistency_conflicts") or [])

    if run.get("review_reasons"):
        with st.expander(
            f"Review Reasons ({len(run['review_reasons'])})", expanded=False
        ):
            for rr in run["review_reasons"]:
                st.write(f"- {rr}")

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

    render_factor_cards(
        positive_factors=run.get("positive_factors") or [],
        negative_factors=run.get("negative_factors") or [],
        blocking_factors=run.get("blocking_factors") or [],
    )

    linked_reviews = get_review_history_for_run(run["run_id"])
    st.markdown("**Linked Human Underwriter Review Events:**")
    if linked_reviews:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Review ID": ev["review_id"],
                        "Transition": f"{ev['previous_review_status']} → {ev['new_review_status']}",
                        "Human Decision": ev.get("human_decision")
                        or "Not yet recorded",
                        "Reviewer ID": ev["reviewer_id"],
                        "Reason": ev["decision_reason"],
                        "Correction?": (
                            f"Yes (Parent: {ev.get('parent_review_id')})"
                            if ev.get("is_correction")
                            else "No"
                        ),
                        "Timestamp (UTC)": str(ev["review_timestamp"])[:19].replace(
                            "T", " "
                        ),
                    }
                    for ev in linked_reviews
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No human review events linked to this run yet (Status: PENDING).")

    if snap:
        with st.expander(
            "Inspect Individual Persisted Agent Outputs (Masked)", expanded=False
        ):
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
