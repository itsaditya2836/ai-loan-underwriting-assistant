"""Underwriter Review Queue & Human Decision Workbench.

Provides:
- Filterable queue prioritizing cases awaiting human underwriter review or triage
- Strict separation between AI recommendation, pipeline execution, human status & decision
- Full applicant, AI analysis, masked document evidence, and conflict inspection
- Server-validated decision submission with Maker-Checker guards preserved intact
- Append-only linked corrections and additional-info return-to-pending workflow
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from app.review.service import (
    compute_review_queue_metrics,
    get_case_review_summary,
    list_review_queue,
    record_additional_info_return,
    submit_human_review_safe,
)
from app.schemas.review import HumanReviewAction, ReviewStatus
from app.ui.components import (
    format_compact_status,
    format_fraud_status_display,
    format_inr,
    format_risk_score_display,
    render_conflicts_panel,
    render_factor_cards,
    render_human_vs_ai_summary_panel,
    render_kpi_row,
    render_kv_grid,
    render_page_header,
    render_section_heading,
)
from app.ui.services import (
    get_applicant_record,
    load_applicant_catalog,
    mask_extracted_value,
)
from app.ui.state import (
    STATE_LAST_REVIEW_RECEIPT,
    STATE_SELECTED_APP_ID,
    STATE_SELECTED_RUN_ID,
    get_authenticated_ui_user,
    navigate_to,
    queue_existing_applicant_for_intake,
)

_ACTION_UI_LABELS: Dict[str, HumanReviewAction] = {
    "Approve": HumanReviewAction.APPROVE,
    "Reject": HumanReviewAction.REJECT,
    "Request Additional Information": HumanReviewAction.REQUEST_ADDITIONAL_INFO,
    "Return for Further Investigation": HumanReviewAction.RETURN_FOR_INVESTIGATION,
}


def _format_utc_short(ts: Optional[str]) -> str:
    """Format ISO timestamp compactly."""
    if not ts:
        return "—"
    return str(ts)[:16].replace("T", " ")


def _render_review_receipt() -> None:
    """Display confirmation receipt after recording a human review event."""
    receipt = st.session_state.get(STATE_LAST_REVIEW_RECEIPT)
    if not receipt:
        return
    with st.container(border=True):
        st.success(
            f"Recorded human review event **`{receipt['review_id']}`** for `{receipt['application_id']}` — "
            f"Action: `{receipt['action']}` | Review Status: **`{receipt['new_review_status']}`** "
            f"(Human Decision: `{receipt.get('human_decision') or 'Not yet recorded'}`)"
        )
        st.caption(
            f"Reviewer `{receipt['reviewer_id']}` · Timestamp `{_format_utc_short(receipt['review_timestamp'])} UTC` · "
            f"Source AI Run `{receipt['source_run_id']}`"
        )


def render_underwriter_review_queue_view() -> None:
    """Render the Human Underwriter Review Queue & Detailed Review Workbench."""
    if "_ui_pending_clear_review_form" in st.session_state:
        rid_clear = st.session_state.pop("_ui_pending_clear_review_form")
        for prefix in (
            f"rq_confirm_{rid_clear}",
            f"rq_reason_{rid_clear}",
            f"rq_comments_{rid_clear}",
            f"rq_add_info_req_{rid_clear}",
            f"rq_inv_instr_{rid_clear}",
            f"rq_corr_expl_{rid_clear}",
            f"rq_is_correction_{rid_clear}",
        ):
            st.session_state.pop(prefix, None)

    render_page_header(
        "Human Review",
        "Underwriter Review Queue",
        "Triage cases requiring human judgment and record separate, append-only underwriting decisions.",
    )

    auth_user = get_authenticated_ui_user()
    if auth_user is not None:
        from app.auth.permissions import Permission, check_permission

        if not (
            check_permission(auth_user.role, Permission.REVIEW_VIEW_ASSIGNED)
            or check_permission(auth_user.role, Permission.REVIEW_VIEW_ALL)
        ):
            st.error(
                f"Access denied: role '{auth_user.role.value}' is not authorized to access the Underwriter Review Queue."
            )
            return

    _render_review_receipt()

    catalog = load_applicant_catalog()
    catalog_map = {
        rec["applicant_id"]: rec for rec in catalog if rec.get("applicant_id")
    }

    all_queue_items = list_review_queue(
        applicant_catalog_by_id=catalog_map,
        include_finalized=True,
    )
    metrics = compute_review_queue_metrics(all_queue_items)

    action_needed_total = (
        metrics["pending_reviews"]
        + metrics["in_progress"]
        + metrics["additional_info_requested"]
        + metrics["investigation_required"]
    )
    finalized_total = (
        metrics["approved_by_underwriter"] + metrics["rejected_by_underwriter"]
    )

    render_kpi_row(
        [
            {
                "label": "Cases Requiring Action",
                "value": action_needed_total,
                "meta": f"{metrics['completed_ai_decisions']} completed evaluations tracked",
            },
            {
                "label": "Pending Initial Review",
                "value": metrics["pending_reviews"],
                "meta": "Awaiting underwriter claim or decision",
            },
            {
                "label": "In Review / Follow-Up",
                "value": metrics["in_progress"]
                + metrics["additional_info_requested"]
                + metrics["investigation_required"],
                "meta": f"{metrics['additional_info_requested']} info req · {metrics['investigation_required']} investigation",
            },
            {
                "label": "Finalized Decisions",
                "value": finalized_total,
                "meta": f"{metrics['approved_by_underwriter']} approved · {metrics['rejected_by_underwriter']} rejected",
            },
        ]
    )

    if metrics.get("failed_pipeline_runs", 0) > 0:
        st.caption(
            f"Run Integrity Note: {metrics['failed_pipeline_runs']} failed pipeline execution(s) excluded from AI decision counts and surfaced for triage."
        )

    if not all_queue_items:
        st.info(
            "No underwriting runs exist in SQLite yet. Submit an application in **New Application** "
            "or run an evaluation in **Underwriting Results** to populate the review queue."
        )
        return

    with st.container(border=True):
        render_section_heading("Queue Filters")
        fc1, fc2, fc3, fc4, fc5 = st.columns(5)
        f_app = fc1.text_input(
            "Applicant ID / Name", value="", key="rq_filter_app"
        ).strip()
        f_ai_rec = fc2.selectbox(
            "AI Recommendation",
            options=["ALL", "APPROVE", "REJECT", "MANUAL_REVIEW"],
            key="rq_filter_ai_rec",
        )
        f_pipe = fc3.selectbox(
            "Pipeline Execution",
            options=["ALL", "SUCCESS", "PARTIAL_SUCCESS", "FAILED"],
            key="rq_filter_pipe",
        )
        f_risk = fc4.selectbox(
            "Risk Category",
            options=["ALL", "LOW", "MEDIUM", "HIGH", "BORDERLINE", "UNAVAILABLE"],
            key="rq_filter_risk",
        )
        f_rev_status = fc5.selectbox(
            "Human Review Status",
            options=[
                "NEEDS_HUMAN_ACTION",
                "ALL",
                "PENDING",
                "IN_REVIEW",
                "APPROVED",
                "REJECTED",
                "ADDITIONAL_INFO_REQUESTED",
                "INVESTIGATION_REQUIRED",
            ],
            index=0,
            key="rq_filter_rev_status",
        )

        dc1, dc2, dc3 = st.columns([1.3, 1, 1.7])
        use_dates = dc1.checkbox(
            "Filter by Submission Date", value=False, key="rq_use_dates"
        )
        start_d = (
            dc2.date_input("From Date", value=date(2026, 1, 1), key="rq_start_date")
            if use_dates
            else None
        )
        end_d = (
            dc3.date_input("To Date", value=datetime.now().date(), key="rq_end_date")
            if use_dates
            else None
        )

    filtered_items = list_review_queue(
        applicant_catalog_by_id=catalog_map,
        application_id_filter=f_app or None,
        ai_recommendation_filter=None if f_ai_rec == "ALL" else f_ai_rec,
        pipeline_status_filter=None if f_pipe == "ALL" else f_pipe,
        risk_category_filter=None if f_risk == "ALL" else f_risk,
        review_status_filter=f_rev_status,
        start_date=start_d.isoformat() if use_dates and start_d else None,
        end_date=end_d.isoformat() if use_dates and end_d else None,
        include_finalized=True,
    )

    if not filtered_items:
        st.info("No queue cases match the selected filters.")
        return

    st.caption(f"Displaying {len(filtered_items)} prioritized case(s)")
    q_rows = [
        {
            "ID": item["applicant_id"],
            "Name": item["applicant_name"],
            "AI Rec": format_compact_status(item["ai_recommendation"]),
            "Risk": format_compact_status(item["risk_category"]),
            "Triggers": " · ".join(
                format_compact_status(t) for t in item["attention_triggers"]
            )
            or "None",
            "Review Status": format_compact_status(item["human_review_status"]),
            "Decision": (
                format_compact_status(item["human_decision"])
                if item.get("human_decision")
                else "Pending"
            ),
            "Submitted": _format_utc_short(item["submission_timestamp"]),
        }
        for item in filtered_items
    ]
    st.dataframe(pd.DataFrame(q_rows), width="stretch", hide_index=True)

    render_section_heading(
        "Case Workbench",
        "Inspect dossier evidence and record append-only human underwriting actions",
    )

    case_ids = [item["applicant_id"] for item in filtered_items]
    pref_id = st.session_state.get(STATE_SELECTED_APP_ID)
    default_idx = case_ids.index(pref_id) if pref_id in case_ids else 0
    selected_case_id = st.selectbox(
        "Select Application to Review",
        options=case_ids,
        index=default_idx,
        format_func=lambda aid: next(
            f"{it['applicant_id']} — {it['applicant_name']} "
            f"[{format_compact_status(it['ai_recommendation'])} · {format_compact_status(it['human_review_status'])}]"
            for it in filtered_items
            if it["applicant_id"] == aid
        ),
        key="rq_selected_case_id",
    )
    selected_item = next(
        it for it in filtered_items if it["applicant_id"] == selected_case_id
    )
    run_row = selected_item["run_record"]
    run_id = selected_item["source_run_id"]
    st.session_state[STATE_SELECTED_APP_ID] = selected_case_id
    st.session_state[STATE_SELECTED_RUN_ID] = run_id

    case_summary = get_case_review_summary(selected_case_id, run_id=run_id)
    render_human_vs_ai_summary_panel(case_summary)

    cur_rev_status = case_summary["human_review_status"]
    if cur_rev_status == ReviewStatus.PENDING.value:
        with st.expander(
            "Claim Case Into Active Review (Pending -> In Review)", expanded=False
        ):
            if auth_user is not None:
                st.caption(
                    f"Authenticated Reviewer: `{auth_user.username}` (`{auth_user.role.value}`)"
                )
                claim_rev = f"{auth_user.username} ({auth_user.user_id})"
            else:
                claim_rev = st.text_input(
                    "Reviewer Identifier *",
                    value="underwriter_01",
                    key=f"rq_claim_reviewer_{run_id}",
                )
            if st.button("Mark Case In Review", key=f"rq_btn_claim_{run_id}"):
                claim_payload: Dict[str, Any] = {
                    "source_run_id": run_id,
                    "application_id": selected_case_id,
                    "action": HumanReviewAction.START_REVIEW.value,
                    "reviewer_id": claim_rev,
                    "expected_previous_status": cur_rev_status,
                    "decision_reason": "Case claimed by underwriter for detailed review.",
                    "confirmed": True,
                }
                if auth_user is not None:
                    claim_payload["reviewer_user_id"] = auth_user.user_id
                    claim_payload["reviewer_username"] = auth_user.username
                    claim_payload["reviewer_role"] = auth_user.role.value
                res_claim = submit_human_review_safe(claim_payload)
                if res_claim["saved"]:
                    st.session_state[STATE_LAST_REVIEW_RECEIPT] = res_claim["event"]
                    st.rerun()
                else:
                    st.error(res_claim["error"])

    _render_case_inspection_tabs(selected_case_id, run_row)

    if cur_rev_status in {
        ReviewStatus.ADDITIONAL_INFO_REQUESTED.value,
        ReviewStatus.INVESTIGATION_REQUIRED.value,
    }:
        _render_additional_info_followup_box(selected_case_id, run_id, case_summary)

    _render_human_decision_form(selected_case_id, run_id, case_summary)
    _render_case_review_timeline(case_summary)


def _render_case_inspection_tabs(application_id: str, run_row: Dict[str, Any]) -> None:
    """Render Applicant Profile, AI Analysis, and Masked Evidence tabs cleanly."""
    snap = run_row.get("details_snapshot") or {}
    app_rec = get_applicant_record(application_id) or {}
    elig = snap.get("eligibility") or {}
    risk = snap.get("risk") or {}
    anom = snap.get("anomaly") or {}
    doc_pkg = snap.get("document_package") or {}

    t_app, t_ai, t_ev = st.tabs(
        [
            "1. Applicant Profile & Financials",
            "2. AI Analysis & Decision Triggers",
            "3. Supporting Evidence & Masked Extractions",
        ]
    )

    with t_app:
        dti = elig.get("dti_ratio")
        dti_disp = (
            f"{dti:.1f}%"
            if dti is not None
            else (
                f"{app_rec['dti_ratio']:.1f}%"
                if app_rec.get("dti_ratio") is not None
                else "Unavailable"
            )
        )
        render_kv_grid(
            [
                ("Applicant Reference", application_id),
                ("Applicant Name", str(app_rec.get("name", "N/A"))),
                ("Age", f"{app_rec.get('age', 'N/A')} yrs"),
                ("Employment Type", str(app_rec.get("employment_type", "N/A"))),
                ("Monthly Income", format_inr(app_rec.get("monthly_income"))),
                ("Existing Monthly EMI", format_inr(app_rec.get("existing_emi"))),
                ("Calculated DTI", dti_disp),
                ("Credit Score", str(app_rec.get("credit_score", "N/A"))),
                ("Requested Loan", format_inr(app_rec.get("loan_amount"))),
                ("Loan Tenure", f"{app_rec.get('loan_tenure', 'N/A')} months"),
                ("Bank Balance", format_inr(app_rec.get("bank_balance"))),
                ("Employment Tenure", f"{app_rec.get('employment_years', 'N/A')} yrs"),
            ],
            columns=4,
        )

    with t_ai:
        st.info(
            f"**AI Recommendation (`{run_row['recommendation']}`)** — {run_row.get('summary_narrative', 'N/A')}"
        )
        render_kv_grid(
            [
                (
                    "Heuristic Confidence",
                    f"{float(run_row.get('decision_confidence', 0.0)):.1f}%",
                ),
                (
                    "Eligibility Status",
                    str(run_row.get("eligibility_status", "UNAVAILABLE")),
                ),
                (
                    "Risk Assessment",
                    f"{run_row.get('risk_category', 'UNAVAILABLE')} ({format_risk_score_display(run_row.get('risk_score'))})",
                ),
                (
                    "Fraud / Anomaly",
                    format_fraud_status_display(
                        snap.get("fraud_status") or run_row.get("anomaly_severity")
                    ),
                ),
            ],
            columns=4,
        )

        doc_ver = snap.get("document_verification_status") or (
            "INCOMPLETE"
            if int(run_row.get("documents_missing_count") or 0) > 0
            else "RECORDED"
        )
        st.caption(f"Document Verification Status: `{doc_ver}`")
        if doc_pkg.get("documents_missing"):
            st.warning(
                f"**Missing Documents:** {', '.join(doc_pkg['documents_missing'])}"
            )
        if doc_pkg.get("unclassified_documents"):
            st.error(
                f"**Unclassified Documents:** {', '.join(doc_pkg['unclassified_documents'])}"
            )
        if doc_pkg.get("invalid_fields"):
            st.error(f"**Invalid Extracted Fields:** {doc_pkg['invalid_fields']}")
        if doc_pkg.get("ambiguous_fields"):
            st.warning(f"**Ambiguous Fields:** {doc_pkg['ambiguous_fields']}")
        if doc_pkg.get("field_conflicts"):
            st.error(f"**Cross-Document Conflicts:** {doc_pkg['field_conflicts']}")

        render_conflicts_panel(run_row.get("consistency_conflicts") or [])

        if run_row.get("review_reasons"):
            with st.expander(
                f"AI Manual Review Triggers ({len(run_row['review_reasons'])})",
                expanded=True,
            ):
                for rr in run_row["review_reasons"]:
                    st.warning(rr)

        if run_row.get("reasons"):
            with st.expander(
                f"Structured AI Decision Reasons ({len(run_row['reasons'])})",
                expanded=False,
            ):
                for r in run_row["reasons"]:
                    st.write(
                        f"- **`[{r.get('code')}]` ({r.get('category')} / `{r.get('severity')}`)** "
                        f"— {r.get('description')}"
                    )

        render_factor_cards(
            positive_factors=run_row.get("positive_factors") or [],
            negative_factors=run_row.get("negative_factors") or [],
            blocking_factors=run_row.get("blocking_factors") or [],
        )

        exec_details = snap.get("agent_execution_details") or {}
        if exec_details:
            with st.expander("Technical Agent Execution Telemetry", expanded=False):
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Agent": k,
                                "Status": v.get("status"),
                                "Output Available": v.get("output_available"),
                                "Latency (ms)": v.get("duration_ms"),
                                "Error": v.get("error") or "None",
                            }
                            for k, v in sorted(exec_details.items())
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )

    with t_ev:
        if elig.get("rule_results"):
            st.markdown("**Eligibility Policy Rule Provenance**")
            st.dataframe(
                pd.DataFrame(elig["rule_results"]), width="stretch", hide_index=True
            )

        if risk:
            st.markdown("**Credit Risk Contributing Factors**")
            c_r1, c_r2 = st.columns(2)
            c_r1.write(
                "**Protective:** "
                + (", ".join(risk.get("protective_factors", [])) or "None")
            )
            c_r2.write(
                "**Adverse Risk:** "
                + (", ".join(risk.get("risk_factors", [])) or "None")
            )

        if anom.get("flags"):
            st.markdown("**Cross-Document Anomaly Flags (Privacy-Masked)**")
            st.dataframe(pd.DataFrame(anom["flags"]), width="stretch", hide_index=True)

        docs = doc_pkg.get("documents_found") or []
        if docs:
            st.markdown("**Extracted Document Evidence (Masked)**")
            ev_rows: List[Dict[str, Any]] = []
            for d in docs:
                for fn, ef in (d.get("extracted_fields") or {}).items():
                    ev_rows.append(
                        {
                            "Document": d.get("filename"),
                            "Category": d.get("document_type"),
                            "Field": fn,
                            "Value (Masked)": mask_extracted_value(
                                fn, ef.get("value"), ef.get("masked_value")
                            ),
                            "Validation": ef.get("validation_status"),
                            "Page": ef.get("page_number"),
                            "Evidence (Masked)": mask_extracted_value(
                                "evidence", ef.get("evidence")
                            ),
                        }
                    )
            if ev_rows:
                st.dataframe(pd.DataFrame(ev_rows), width="stretch", hide_index=True)
        else:
            st.caption("No processed document artifacts recorded for this run.")


def _render_additional_info_followup_box(
    application_id: str,
    source_run_id: str,
    case_summary: Dict[str, Any],
) -> None:
    """Allow returning an ADDITIONAL_INFO_REQUESTED / INVESTIGATION_REQUIRED case to PENDING."""
    latest = case_summary.get("latest_review") or {}
    cur_status = case_summary["human_review_status"]

    with st.container(border=True):
        render_section_heading("Follow-Up / Return Case to Pending Queue")

        if latest.get("additional_info_request"):
            st.warning(
                f"**Additional Information Requested:** {latest['additional_info_request']}"
            )
        if latest.get("investigation_instructions"):
            st.warning(
                f"**Investigation Instructions:** {latest['investigation_instructions']}"
            )

        st.caption(
            "Returning this case to PENDING appends a status transition without automatically re-running underwriting."
        )

        auth_user = get_authenticated_ui_user()
        f1, f2 = st.columns([1, 2])
        if auth_user is not None:
            f1.text_input(
                "Authenticated Handler",
                value=f"{auth_user.username} ({auth_user.role.value})",
                disabled=True,
                key=f"rq_auth_return_handler_{source_run_id}",
            )
            ret_rev_id = f"{auth_user.username} ({auth_user.user_id})"
        else:
            ret_rev_id = f1.text_input(
                "Attribution Reviewer / Handler ID *",
                value=latest.get("reviewer_id") or "underwriter_01",
                key=f"rq_return_handler_{source_run_id}",
            )
        ret_notes = f2.text_input(
            "Additional Info Received / Follow-Up Notes *",
            value="",
            key=f"rq_return_notes_{source_run_id}",
            placeholder="e.g., Applicant submitted updated 3-month bank statement; ready for re-review.",
        )
        b1, b2 = st.columns(2)
        with b1:
            if st.button(
                "Record Follow-Up & Return to Pending Queue",
                key=f"rq_btn_return_pending_{source_run_id}",
                width="stretch",
            ):
                res = record_additional_info_return(
                    source_run_id=source_run_id,
                    application_id=application_id,
                    reviewer_id=ret_rev_id,
                    info_response=ret_notes,
                    reason=f"Returned from {cur_status} to PENDING queue after follow-up.",
                    reviewer_user_id=auth_user.user_id if auth_user else None,
                    reviewer_username=auth_user.username if auth_user else None,
                    reviewer_role=auth_user.role.value if auth_user else None,
                )
                if res["saved"]:
                    st.session_state[STATE_LAST_REVIEW_RECEIPT] = res["event"]
                    st.rerun()
                else:
                    st.error(res["error"])
        with b2:
            if st.button(
                "Open New Application / Upload New Docs",
                key=f"rq_btn_upload_followup_{source_run_id}",
                width="stretch",
            ):
                rec = get_applicant_record(application_id)
                if rec:
                    queue_existing_applicant_for_intake(rec)
                navigate_to("New Application", applicant_id=application_id)
                st.rerun()


def _render_human_decision_form(
    application_id: str,
    source_run_id: str,
    case_summary: Dict[str, Any],
) -> None:
    """Render validated Human Underwriter Decision Submission form with Maker-Checker guards."""
    cur_status = case_summary["human_review_status"]
    latest_rev = case_summary.get("latest_review")
    is_terminal = cur_status in {
        ReviewStatus.APPROVED.value,
        ReviewStatus.REJECTED.value,
    }

    with st.container(border=True):
        render_section_heading(
            "Submit Human Underwriter Decision",
            "Appends an immutable human review event while keeping the AI recommendation unchanged",
        )

        auth_user = get_authenticated_ui_user()
        if auth_user is not None:
            from app.database.applications import get_submitted_application
            from app.database.audit import get_audit_run_by_id

            run_mc = get_audit_run_by_id(source_run_id)
            app_mc = get_submitted_application(application_id)
            if (run_mc and run_mc.get("initiated_by_user_id") == auth_user.user_id) or (
                app_mc and app_mc.get("submitted_by_user_id") == auth_user.user_id
            ):
                st.warning(
                    "Maker-Checker Notice: This application or evaluation run was initiated by your signed-in account. "
                    "Another authorized underwriter or supervisor must record the decision."
                )

        if is_terminal and latest_rev:
            st.warning(
                f"Decision already recorded (`{latest_rev.get('human_decision')}` · `{cur_status}`) "
                f"by `{latest_rev.get('reviewer_id')}` (`{latest_rev.get('review_id')}`). "
                "Supervisors may record an explicit **linked correction event** below."
            )

        is_correction = False
        correction_explanation: Optional[str] = None
        if is_terminal:
            is_correction = st.checkbox(
                "Submit as a linked decision correction (preserves prior audit event intact)",
                value=False,
                key=f"rq_is_correction_{source_run_id}",
            )
            if is_correction:
                correction_explanation = st.text_input(
                    "Correction Explanation *",
                    value="",
                    max_chars=500,
                    key=f"rq_corr_expl_{source_run_id}",
                    placeholder="Explain why the prior human decision is being corrected...",
                )

        c1, c2 = st.columns(2)
        action_label = c1.selectbox(
            "Human Underwriter Action *",
            options=list(_ACTION_UI_LABELS.keys()),
            key=f"rq_action_{source_run_id}",
        )
        selected_action = _ACTION_UI_LABELS[action_label]
        if auth_user is not None:
            c2.text_input(
                "Authenticated Reviewer",
                value=f"{auth_user.username} ({auth_user.role.value})",
                disabled=True,
                key=f"rq_auth_reviewer_{source_run_id}",
            )
            reviewer_id = f"{auth_user.username} ({auth_user.user_id})"
        else:
            reviewer_id = c2.text_input(
                "Reviewer Identifier (Attribution Only) *",
                value="",
                max_chars=64,
                key=f"rq_reviewer_id_{source_run_id}",
                placeholder="e.g., UW_SHARMA_01",
            )

        decision_reason = st.text_input(
            "Mandatory Decision Reason *",
            value="",
            max_chars=500,
            key=f"rq_reason_{source_run_id}",
            placeholder="Concise policy or risk justification for the recorded human action...",
        )

        add_info_req: Optional[str] = None
        if selected_action == HumanReviewAction.REQUEST_ADDITIONAL_INFO:
            add_info_req = st.text_area(
                "Required Additional Information Details *",
                value="",
                max_chars=1000,
                key=f"rq_add_info_req_{source_run_id}",
                placeholder="Specify exact documents or clarifications required from the applicant...",
            )

        inv_instr: Optional[str] = None
        if selected_action == HumanReviewAction.RETURN_FOR_INVESTIGATION:
            inv_instr = st.text_area(
                "Investigation Instructions *",
                value="",
                max_chars=1000,
                key=f"rq_inv_instr_{source_run_id}",
                placeholder="Specify anomalies, employer verification, or discrepancies to investigate...",
            )

        comments = st.text_area(
            "Optional Reviewer Comments (Max 2,000 characters; sensitive digits auto-masked)",
            value="",
            max_chars=2000,
            key=f"rq_comments_{source_run_id}",
        )

        confirmed = st.checkbox(
            f"I confirm recording `{action_label}` for `{application_id}` (Run `{source_run_id}`). "
            "This appends an immutable audit event and leaves the AI recommendation intact.",
            value=False,
            key=f"rq_confirm_{source_run_id}",
        )

        if st.button(
            "Submit Human Underwriter Decision",
            type="primary",
            key=f"rq_btn_submit_{source_run_id}",
            width="stretch",
        ):
            if auth_user is not None:
                from app.auth.permissions import (
                    MakerCheckerError,
                    Permission,
                    check_permission,
                    enforce_correction_requires_supervisor,
                    enforce_not_self_review,
                )
                from app.database.applications import get_submitted_application
                from app.database.audit import get_audit_run_by_id

                if not check_permission(
                    auth_user.role, Permission.REVIEW_SUBMIT_DECISION
                ):
                    st.error(
                        f"Role '{auth_user.role.value}' is not authorized to submit review decisions."
                    )
                    return
                if is_correction:
                    try:
                        enforce_correction_requires_supervisor(auth_user.role)
                    except MakerCheckerError as exc:
                        st.error(str(exc))
                        return
                run_row_mc = get_audit_run_by_id(source_run_id)
                if run_row_mc:
                    try:
                        enforce_not_self_review(
                            auth_user.user_id,
                            run_row_mc.get("initiated_by_user_id"),
                            operation="review their own underwriting submission",
                        )
                    except MakerCheckerError as exc:
                        st.error(str(exc))
                        return
                app_row_mc = get_submitted_application(application_id)
                if app_row_mc:
                    try:
                        enforce_not_self_review(
                            auth_user.user_id,
                            app_row_mc.get("submitted_by_user_id"),
                            operation="approve or review their own submitted application",
                        )
                    except MakerCheckerError as exc:
                        st.error(str(exc))
                        return

            payload: Dict[str, Any] = {
                "source_run_id": source_run_id,
                "application_id": application_id,
                "action": selected_action.value,
                "reviewer_id": reviewer_id,
                "reviewer_user_id": auth_user.user_id if auth_user else None,
                "reviewer_username": auth_user.username if auth_user else None,
                "reviewer_role": auth_user.role.value if auth_user else None,
                "expected_previous_status": cur_status,
                "decision_reason": decision_reason,
                "comments": comments,
                "additional_info_request": add_info_req,
                "investigation_instructions": inv_instr,
                "is_correction": is_correction,
                "parent_review_id": (
                    latest_rev["review_id"] if (is_correction and latest_rev) else None
                ),
                "correction_explanation": correction_explanation,
                "confirmed": confirmed,
            }
            result = submit_human_review_safe(payload)
            if result["saved"]:
                ev = result["event"]
                st.session_state[STATE_LAST_REVIEW_RECEIPT] = ev
                st.session_state["_ui_pending_clear_review_form"] = source_run_id
                st.rerun()
            elif result.get("duplicate_blocked"):
                st.warning(result["error"])
            else:
                st.error(result["error"])


def _render_case_review_timeline(case_summary: Dict[str, Any]) -> None:
    """Display immutable append-only review events for this run and applicant."""
    render_section_heading("Case Review Audit Timeline")
    history = case_summary.get("application_review_history") or []
    if not history:
        st.caption(
            "No human review events have been recorded yet for this application."
        )
        return

    rows = [
        {
            "Review ID": ev["review_id"],
            "Timestamp (UTC)": _format_utc_short(ev["review_timestamp"]),
            "Source Run": ev["source_run_id"],
            "AI Rec": format_compact_status(ev["original_ai_recommendation"]),
            "Transition": f"{ev['previous_review_status']} -> {ev['new_review_status']}",
            "Human Decision": (
                format_compact_status(ev["human_decision"])
                if ev.get("human_decision")
                else "Not yet recorded"
            ),
            "Reviewer ID": ev["reviewer_id"],
            "Reviewer Role": ev.get("reviewer_role") or "Attribution Only",
            "Reason": ev["decision_reason"],
            "Correction": (
                f"Yes ({ev.get('parent_review_id')})"
                if ev.get("is_correction")
                else "No"
            ),
        }
        for ev in history
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
