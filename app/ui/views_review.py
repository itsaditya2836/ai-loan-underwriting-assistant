"""Underwriter Review Queue & Human Decision Workbench (Stage 6).

Provides:
- Filterable queue for cases awaiting human underwriter review or triage
- Strict separation between AI recommendation, pipeline execution, human status & decision
- Full applicant, AI analysis, masked document evidence, and conflict inspection
- Server-validated decision submission (Approve / Reject / Request Additional Info / Investigation)
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
    format_fraud_status_display,
    format_inr,
    format_risk_score_display,
    render_conflicts_panel,
    render_factor_cards,
    render_human_vs_ai_summary_panel,
)
from app.ui.services import (
    format_decision_label,
    get_applicant_record,
    load_applicant_catalog,
    mask_extracted_value,
)
from app.ui.state import (
    STATE_LAST_REVIEW_RECEIPT,
    STATE_SELECTED_APP_ID,
    STATE_SELECTED_RUN_ID,
    navigate_to,
    queue_existing_applicant_for_intake,
)

_ACTION_UI_LABELS: Dict[str, HumanReviewAction] = {
    "Approve": HumanReviewAction.APPROVE,
    "Reject": HumanReviewAction.REJECT,
    "Request Additional Information": HumanReviewAction.REQUEST_ADDITIONAL_INFO,
    "Return for Further Investigation": HumanReviewAction.RETURN_FOR_INVESTIGATION,
}


def _render_review_receipt() -> None:
    """Display confirmation receipt after recording a human review event."""
    receipt = st.session_state.get(STATE_LAST_REVIEW_RECEIPT)
    if not receipt:
        return
    st.success(
        f"Recorded human review event **`{receipt['review_id']}`** for `{receipt['application_id']}` — "
        f"Action: `{receipt['action']}` | Human Review Status: **`{receipt['new_review_status']}`** "
        f"(Human Decision: `{receipt.get('human_decision') or 'Not yet recorded'}`)"
    )
    st.info(
        f"Reviewer: `{receipt['reviewer_id']}` | Timestamp (UTC): `{receipt['review_timestamp'][:19].replace('T', ' ')}` "
        f"| Source AI Run: `{receipt['source_run_id']}`"
    )


def render_underwriter_review_queue_view() -> None:
    """Render the Stage 6 Human Underwriter Review Queue & Detailed Review Workbench."""
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

    st.subheader("Underwriter Review Queue & Human Decision Workbench")
    st.caption(
        "Review AI underwriting recommendations, inspect evidence and conflicts, and record separate "
        "append-only human underwriter decisions. Original AI recommendations and pipeline analyses are never altered."
    )

    _render_review_receipt()

    catalog = load_applicant_catalog()
    catalog_map = {
        rec["applicant_id"]: rec for rec in catalog if rec.get("applicant_id")
    }

    # Compute unbiased portfolio-level queue metrics across all latest application runs
    all_queue_items = list_review_queue(
        applicant_catalog_by_id=catalog_map,
        include_finalized=True,
    )
    metrics = compute_review_queue_metrics(all_queue_items)

    st.markdown("#### Human Review Queue Summary")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Pending Reviews", metrics["pending_reviews"])
    m2.metric("In Progress", metrics["in_progress"])
    m3.metric("Approved (Human)", metrics["approved_by_underwriter"])
    m4.metric("Rejected (Human)", metrics["rejected_by_underwriter"])
    m5.metric("Additional Info Req.", metrics["additional_info_requested"])
    m6.metric("Investigation Req.", metrics["investigation_required"])

    st.caption(
        f"AI Run Integrity Note: **{metrics['completed_ai_decisions']}** completed AI evaluations tracked; "
        f"**{metrics['failed_pipeline_runs']}** failed pipeline execution(s) excluded from completed AI decision counts "
        "and surfaced strictly for triage."
    )

    if not all_queue_items:
        st.info(
            "No underwriting runs exist in SQLite yet. Submit an application in **New Application** "
            "or run an evaluation in **Underwriting Results** to populate the review queue."
        )
        return

    st.markdown("---")
    st.markdown("#### Queue Filters")
    fc1, fc2, fc3, fc4, fc5 = st.columns(5)
    f_app = fc1.text_input(
        "Applicant Ref / Name", value="", key="rq_filter_app"
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

    dc1, dc2, dc3 = st.columns([1, 1, 2])
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

    st.write(f"Displaying **{len(filtered_items)}** case(s):")
    q_rows = []
    for item in filtered_items:
        q_rows.append(
            {
                "Applicant Ref": item["applicant_id"],
                "Applicant Name": item["applicant_name"],
                "Source Run ID": item["source_run_id"],
                "Submitted (UTC)": str(item["submission_timestamp"])[:19].replace(
                    "T", " "
                ),
                "AI Recommendation": format_decision_label(item["ai_recommendation"]),
                "Pipeline Status": item["pipeline_status"],
                "Risk Tier": item["risk_category"],
                "Risk Score": format_risk_score_display(item.get("risk_score")),
                "Attention Triggers": ", ".join(item["attention_triggers"]) or "NONE",
                "Human Review Status": item["human_review_status"],
                "Final Human Decision": item["human_decision"] or "Not yet recorded",
            }
        )
    st.dataframe(pd.DataFrame(q_rows), width="stretch", hide_index=True)

    st.markdown("---")
    st.markdown("### Case Inspection & Underwriter Decision Workbench")

    case_ids = [item["applicant_id"] for item in filtered_items]
    pref_id = st.session_state.get(STATE_SELECTED_APP_ID)
    default_idx = case_ids.index(pref_id) if pref_id in case_ids else 0
    selected_case_id = st.selectbox(
        "Select Application to Review",
        options=case_ids,
        index=default_idx,
        format_func=lambda aid: next(
            f"{it['applicant_id']} — {it['applicant_name']} "
            f"[AI: {it['ai_recommendation']} | Pipeline: {it['pipeline_status']} | Review: {it['human_review_status']}]"
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
            "Claim Case Into Active Review (`PENDING` → `IN_REVIEW`)", expanded=False
        ):
            claim_rev = st.text_input(
                "Reviewer Identifier *",
                value="underwriter_01",
                key=f"rq_claim_reviewer_{run_id}",
            )
            if st.button("Mark Case In Review", key=f"rq_btn_claim_{run_id}"):
                res_claim = submit_human_review_safe(
                    {
                        "source_run_id": run_id,
                        "application_id": selected_case_id,
                        "action": HumanReviewAction.START_REVIEW.value,
                        "reviewer_id": claim_rev,
                        "decision_reason": "Case claimed by underwriter for detailed review.",
                        "confirmed": True,
                    }
                )
                if res_claim["saved"]:
                    ev = res_claim["event"]
                    st.session_state[STATE_LAST_REVIEW_RECEIPT] = ev
                    st.rerun()
                else:
                    st.error(res_claim["error"])

    # Detailed Inspection Tabs (Applicant, AI Analysis, Masked Evidence)
    _render_case_inspection_tabs(selected_case_id, run_row)

    # Additional Information Return Workflow (if currently ADDITIONAL_INFO_REQUESTED / INVESTIGATION_REQUIRED)
    if cur_rev_status in {
        ReviewStatus.ADDITIONAL_INFO_REQUESTED.value,
        ReviewStatus.INVESTIGATION_REQUIRED.value,
    }:
        _render_additional_info_followup_box(selected_case_id, run_id, case_summary)

    st.markdown("---")

    # Structured Human Underwriter Decision Submission Form
    _render_human_decision_form(selected_case_id, run_id, case_summary)

    # Case Append-Only Review History
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
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("Applicant Reference", application_id)
        a2.metric("Applicant Name", str(app_rec.get("name", "N/A")))
        a3.metric("Age", f"{app_rec.get('age', 'N/A')} yrs")
        a4.metric("Employment Type", str(app_rec.get("employment_type", "N/A")))

        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Monthly Income", format_inr(app_rec.get("monthly_income")))
        f2.metric("Existing Monthly EMI", format_inr(app_rec.get("existing_emi")))
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
        f3.metric("Calculated DTI", dti_disp)
        f4.metric("Credit Score", str(app_rec.get("credit_score", "N/A")))

        l1, l2, l3, l4 = st.columns(4)
        l1.metric("Requested Loan", format_inr(app_rec.get("loan_amount")))
        l2.metric("Loan Tenure", f"{app_rec.get('loan_tenure', 'N/A')} months")
        l3.metric("Bank Balance", format_inr(app_rec.get("bank_balance")))
        l4.metric("Employment Tenure", f"{app_rec.get('employment_years', 'N/A')} yrs")

    with t_ai:
        st.info(
            f"**AI Recommendation (`{run_row['recommendation']}`)** — Executive Narrative:\n\n"
            f"{run_row.get('summary_narrative', 'N/A')}"
        )
        ai1, ai2, ai3, ai4 = st.columns(4)
        ai1.metric(
            "Heuristic Confidence",
            f"{float(run_row.get('decision_confidence', 0.0)):.1f}%",
        )
        ai2.metric(
            "Eligibility Status", str(run_row.get("eligibility_status", "UNAVAILABLE"))
        )
        ai3.metric(
            "Risk Assessment",
            str(run_row.get("risk_category", "UNAVAILABLE")),
            delta=f"Score: {format_risk_score_display(run_row.get('risk_score'))}",
            delta_color="off",
        )
        ai4.metric(
            "Fraud / Anomaly Status",
            format_fraud_status_display(
                snap.get("fraud_status") or run_row.get("anomaly_severity")
            ),
        )
        st.caption(
            "Uncalibrated Heuristic Notice: Decision and extraction confidence values indicate internal evidence completeness and agreement — NOT a probability of default or guaranteed accuracy."
        )

        # Document verification diagnostics
        doc_ver = snap.get("document_verification_status") or (
            "INCOMPLETE"
            if int(run_row.get("documents_missing_count") or 0) > 0
            else "RECORDED"
        )
        st.markdown(f"**Document Verification Status:** `{doc_ver}`")
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

        st.markdown("**Cross-Agent Consistency Conflicts:**")
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

        # Agent Execution Statuses
        exec_details = snap.get("agent_execution_details") or {}
        if exec_details:
            st.markdown("**Agent Execution Statuses:**")
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
            st.markdown("**Eligibility Policy Rule Provenance:**")
            st.dataframe(
                pd.DataFrame(elig["rule_results"]), width="stretch", hide_index=True
            )

        if risk:
            st.markdown("**Credit Risk Contributing Factors & Feature Weights:**")
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
            st.markdown("**Cross-Document Anomaly Flags (Privacy-Masked):**")
            st.dataframe(pd.DataFrame(anom["flags"]), width="stretch", hide_index=True)

        docs = doc_pkg.get("documents_found") or []
        if docs:
            st.markdown(
                "**Extracted Document Evidence (Sensitive IDs/Accounts Masked):**"
            )
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
    st.markdown("#### Follow-Up / Return Case to Pending Queue")

    if latest.get("additional_info_request"):
        st.warning(
            f"**Additional Information Requested:** {latest['additional_info_request']}"
        )
    if latest.get("investigation_instructions"):
        st.warning(
            f"**Investigation Instructions:** {latest['investigation_instructions']}"
        )

    st.caption(
        "Returning this case to PENDING appends a status transition without automatically re-running underwriting. "
        "To process newly uploaded documents, use New Application or explicitly re-run underwriting."
    )

    f1, f2 = st.columns([1, 2])
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
            )
            if res["saved"]:
                st.session_state[STATE_LAST_REVIEW_RECEIPT] = res["event"]
                st.rerun()
            else:
                st.error(res["error"])
    with b2:
        if st.button(
            "Open New Application / Upload New Docs →",
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
    """Render validated Human Underwriter Decision Submission form."""
    st.markdown("### Submit Human Underwriter Decision")
    cur_status = case_summary["human_review_status"]
    latest_rev = case_summary.get("latest_review")
    is_terminal = cur_status in {
        ReviewStatus.APPROVED.value,
        ReviewStatus.REJECTED.value,
    }

    if is_terminal and latest_rev:
        st.warning(
            f"A human decision (`{latest_rev.get('human_decision')}` / status `{cur_status}`) is already recorded "
            f"by `{latest_rev.get('reviewer_id')}` (`{latest_rev.get('review_id')}`). "
            "Prior records cannot be modified or deleted. Submitting below records an explicit **linked correction event**."
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
        "I understand this appends an immutable audit event and will NOT overwrite the AI recommendation.",
        value=False,
        key=f"rq_confirm_{source_run_id}",
    )

    if st.button(
        "Submit Human Underwriter Decision",
        type="primary",
        key=f"rq_btn_submit_{source_run_id}",
        width="stretch",
    ):
        payload: Dict[str, Any] = {
            "source_run_id": source_run_id,
            "application_id": application_id,
            "action": selected_action.value,
            "reviewer_id": reviewer_id,
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
    st.markdown("### Append-Only Case Review Audit Timeline")
    history = case_summary.get("application_review_history") or []
    if not history:
        st.info("No human review events have been recorded yet for this application.")
        return

    rows = []
    for ev in history:
        rows.append(
            {
                "Review ID": ev["review_id"],
                "Timestamp (UTC)": str(ev["review_timestamp"])[:19].replace("T", " "),
                "Source Run": ev["source_run_id"],
                "Original AI Rec": ev["original_ai_recommendation"],
                "Transition": f"{ev['previous_review_status']} → {ev['new_review_status']}",
                "Human Decision": ev.get("human_decision") or "Not yet recorded",
                "Reviewer ID": ev["reviewer_id"],
                "Reason": ev["decision_reason"],
                "Correction?": (
                    f"Yes (Parent: {ev.get('parent_review_id')})"
                    if ev.get("is_correction")
                    else "No"
                ),
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
