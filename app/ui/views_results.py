"""Underwriting Results & Document Verification Views.

Supports both live execution bundles (in session state) and persisted historical
records from SQLite (`underwriting_runs.details_snapshot`), preserving unavailable
statuses honestly and masking sensitive personal/account identifiers.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import streamlit as st

from app.database.audit import get_applicant_run_history, get_audit_run_by_id
from app.review.service import get_case_review_summary
from app.schemas.applicant import Applicant, DocumentPackageResult
from app.schemas.decision import DecisionReasoningResult
from app.schemas.underwriting import UnderwritingAnalysisResult
from app.ui.components import (
    format_compact_status,
    format_eligibility_metrics_summary,
    format_fraud_status_display,
    format_inr,
    format_risk_score_display,
    render_alert_box,
    render_banking_table,
    render_conflicts_panel,
    render_empty_state,
    render_factor_cards,
    render_hitl_banner,
    render_human_vs_ai_summary_panel,
    render_kpi_row,
    render_kv_grid,
    render_page_header,
    render_recommendation_badge,
    render_section_heading,
    render_status_pill,
)
from app.ui.services import (
    expected_documents_for_employment,
    format_decision_label,
    get_applicant_record,
    has_physical_document_package,
    load_applicant_catalog,
    mask_extracted_value,
    submit_application_and_underwrite,
)
from app.ui.state import (
    STATE_DOC_PREVIEW_CACHE,
    STATE_SELECTED_APP_ID,
    STATE_SELECTED_RUN_ID,
    get_live_result,
    navigate_to,
    queue_existing_applicant_for_intake,
    store_live_result,
)


def _normalize_view_context(
    selected_app_id: Optional[str],
    selected_run_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Build unified presentation dictionary from live result or SQLite audit snapshot."""
    live = get_live_result(selected_app_id)
    if live and (
        not selected_run_id
        or live.get("run_id") == selected_run_id
        or not selected_run_id
    ):
        analysis: UnderwritingAnalysisResult = live["analysis"]
        decision: DecisionReasoningResult = live["decision"]
        return _context_from_models(
            analysis=analysis,
            decision=decision,
            run_id=live.get("run_id"),
            duration_ms=live.get("duration_ms", analysis.total_duration_ms or 0.0),
            audit_persisted=live.get("audit_persisted", analysis.audit_persisted),
            audit_error=live.get("audit_error", analysis.audit_persistence_error),
            source_mode="live",
        )

    db_run: Optional[Dict[str, Any]] = None
    if selected_run_id:
        db_run = get_audit_run_by_id(selected_run_id)
    if db_run is None and selected_app_id:
        hist = get_applicant_run_history(selected_app_id)
        if hist:
            db_run = hist[0]

    if db_run is None:
        return None
    return _context_from_db_record(db_run)


def _context_from_models(
    analysis: UnderwritingAnalysisResult,
    decision: DecisionReasoningResult,
    run_id: Optional[str],
    duration_ms: float,
    audit_persisted: bool,
    audit_error: Optional[str],
    source_mode: str,
) -> Dict[str, Any]:
    """Extract normalized display payload directly from Pydantic backend objects."""
    doc_dict: Optional[Dict[str, Any]] = None
    doc_res = analysis.document_result
    if doc_res is not None:
        docs_found = []
        for d in doc_res.documents_found:
            ext_fields = {}
            for fn, ef in sorted(d.extracted_fields.items()):
                ext_fields[fn] = {
                    "field_name": ef.field_name,
                    "value": mask_extracted_value(fn, ef.value, ef.masked_value),
                    "confidence": float(ef.confidence),
                    "source_document": ef.source_document,
                    "page_number": int(ef.page_number),
                    "extraction_method": ef.extraction_method,
                    "validation_status": ef.validation_status,
                    "validation_message": ef.validation_message,
                    "evidence": mask_extracted_value("evidence", ef.evidence),
                }
            docs_found.append(
                {
                    "document_id": d.document_id,
                    "filename": (
                        os.path.basename(d.file_path) if d.file_path else d.document_id
                    ),
                    "document_type": d.document_type,
                    "classification_confidence": float(d.classification_confidence),
                    "classification_status": d.classification_status,
                    "classification_evidence": mask_extracted_value(
                        "evidence", d.classification_evidence
                    ),
                    "is_scanned": bool(d.is_scanned),
                    "extraction_method": d.extraction_method,
                    "page_count": int(d.page_count),
                    "native_text_pages": int(d.native_text_pages),
                    "ocr_pages": int(d.ocr_pages),
                    "empty_pages": int(d.empty_pages),
                    "failed_pages": int(d.failed_pages),
                    "extracted_fields": ext_fields,
                }
            )
        doc_dict = {
            "processing_status": doc_res.processing_status,
            "processing_errors": list(doc_res.processing_errors),
            "is_complete": bool(doc_res.is_complete),
            "ocr_used": bool(doc_res.ocr_used),
            "expected_documents": list(doc_res.expected_documents),
            "documents_missing": list(doc_res.documents_missing),
            "unclassified_documents": list(doc_res.unclassified_documents),
            "duplicate_documents": list(doc_res.duplicate_documents),
            "missing_fields": dict(doc_res.missing_fields),
            "invalid_fields": dict(doc_res.invalid_fields),
            "ambiguous_fields": dict(doc_res.ambiguous_fields),
            "field_conflicts": dict(doc_res.field_conflicts),
            "security_warnings": list(doc_res.security_warnings),
            "documents_found": docs_found,
        }

    elig_dict = None
    if analysis.eligibility_result is not None:
        er = analysis.eligibility_result
        elig_dict = {
            "status": er.status.value,
            "policy_version": er.policy_version,
            "max_eligible_amount": er.max_eligible_amount,
            "dti_ratio": er.dti_ratio,
            "summary_line": format_eligibility_metrics_summary(er),
            "rules_passed": list(er.rules_passed),
            "rules_failed": list(er.rules_failed),
            "rules_requiring_review": list(er.rules_requiring_review),
            "reasons": list(er.reasons),
            "rule_results": [
                {
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "status": r.status.value,
                    "passed": r.passed,
                    "actual_value": str(r.actual_value),
                    "expected_value": str(r.expected_value),
                    "reason": r.reason,
                }
                for r in er.rule_results
            ],
        }

    risk_dict = None
    if analysis.risk_result is not None:
        rr = analysis.risk_result
        risk_dict = {
            "risk_category": rr.risk_category.value,
            "risk_score": decision.risk_score,
            "method": rr.method,
            "model_version": rr.model_version,
            "risk_factors": list(rr.risk_factors),
            "protective_factors": list(rr.protective_factors),
            "feature_importance": dict(rr.feature_importance),
        }

    anom_dict = None
    if analysis.anomaly_result is not None:
        ar = analysis.anomaly_result
        anom_dict = {
            "severity": ar.severity.value,
            "anomaly_score": ar.anomaly_score,
            "has_anomalies": bool(ar.has_anomalies),
            "missing_evidence": list(ar.missing_evidence),
            "summary": mask_extracted_value("summary", ar.summary or ""),
            "flags": [
                {
                    "rule_id": f.rule_id,
                    "anomaly_type": f.anomaly_type,
                    "severity": f.severity.value,
                    "expected_value": mask_extracted_value(
                        f.anomaly_type, f.expected_value
                    ),
                    "observed_value": mask_extracted_value(
                        f.anomaly_type, f.observed_value
                    ),
                    "description": mask_extracted_value("description", f.description),
                    "evidence": mask_extracted_value("evidence", f.evidence or ""),
                }
                for f in ar.flags
            ],
        }

    agent_exec_details = {
        k: {
            "status": st.status.value,
            "success": st.success,
            "output_available": st.output_available,
            "duration_ms": st.duration_ms,
            "warnings": list(st.warnings),
            "error": st.error,
        }
        for k, st in sorted(analysis.agent_statuses.items())
    }

    return {
        "source_mode": source_mode,
        "application_id": analysis.application_id,
        "run_id": run_id,
        "timestamp": str(decision.timestamp),
        "pipeline_status": analysis.orchestration_status.value,
        "duration_ms": duration_ms,
        "audit_persisted": audit_persisted,
        "audit_error": audit_error,
        "recommendation": decision.recommendation.value,
        "confidence": float(decision.confidence),
        "summary": decision.summary,
        "eligibility_status": decision.eligibility_status or "UNAVAILABLE",
        "risk_category": decision.risk_category or "UNAVAILABLE",
        "risk_score": decision.risk_score,
        "fraud_status": decision.fraud_status or "UNAVAILABLE",
        "document_verification_status": decision.document_verification_status
        or "UNAVAILABLE",
        "missing_documents": list(decision.missing_documents),
        "validation_warnings": list(decision.validation_warnings),
        "material_anomalies": list(decision.material_anomalies),
        "review_reasons": list(decision.review_reasons),
        "blocking_factors": list(decision.blocking_factors),
        "positive_factors": list(decision.positive_factors),
        "negative_factors": list(decision.negative_factors),
        "reasons": [r.model_dump() for r in decision.reasons],
        "consistency_conflicts": list(decision.consistency_conflicts),
        "agent_statuses": dict(decision.agent_statuses),
        "agent_execution_details": agent_exec_details,
        "document_package": doc_dict,
        "eligibility": elig_dict,
        "risk": risk_dict,
        "anomaly": anom_dict,
    }


def _context_from_db_record(row: Dict[str, Any]) -> Dict[str, Any]:
    """Build normalized display context from a persisted underwriting_runs SQLite row."""
    snap = row.get("details_snapshot") or {}
    return {
        "source_mode": "database",
        "application_id": row["application_id"],
        "run_id": row["run_id"],
        "timestamp": row.get("timestamp", ""),
        "pipeline_status": row["pipeline_status"],
        "duration_ms": float(row.get("execution_time_ms") or 0.0),
        "audit_persisted": True,
        "audit_error": None,
        "recommendation": row["recommendation"],
        "confidence": float(row.get("decision_confidence") or 0.0),
        "summary": row.get("summary_narrative") or "",
        "eligibility_status": row.get("eligibility_status") or "UNAVAILABLE",
        "risk_category": row.get("risk_category") or "UNAVAILABLE",
        "risk_score": row.get("risk_score"),
        "fraud_status": snap.get("fraud_status")
        or row.get("anomaly_severity")
        or "UNAVAILABLE",
        "document_verification_status": snap.get("document_verification_status")
        or (
            "INCOMPLETE"
            if int(row.get("documents_missing_count") or 0) > 0
            else "RECORDED"
        ),
        "missing_documents": (
            (snap.get("document_package") or {}).get("documents_missing", [])
        ),
        "validation_warnings": list(row.get("validation_warnings") or []),
        "material_anomalies": [],
        "review_reasons": list(row.get("review_reasons") or []),
        "blocking_factors": list(row.get("blocking_factors") or []),
        "positive_factors": list(row.get("positive_factors") or []),
        "negative_factors": list(row.get("negative_factors") or []),
        "reasons": list(row.get("reasons") or []),
        "consistency_conflicts": list(row.get("consistency_conflicts") or []),
        "agent_statuses": dict(row.get("agent_statuses") or {}),
        "agent_execution_details": snap.get("agent_execution_details") or {},
        "document_package": snap.get("document_package"),
        "eligibility": snap.get("eligibility"),
        "risk": snap.get("risk"),
        "anomaly": snap.get("anomaly"),
    }


def _render_run_action_header(selected_app_id: Optional[str]) -> Optional[str]:
    """Allow selecting an application and triggering a pipeline evaluation cleanly."""
    catalog = load_applicant_catalog()
    app_ids = [rec["applicant_id"] for rec in catalog]

    if not app_ids:
        render_empty_state(
            "No Applications Available",
            "Create a new application in the Intake Wizard before running underwriting.",
        )
        if st.button("Go to New Application", key="results_goto_intake"):
            navigate_to("New Application")
            st.rerun()
        return None

    default_idx = app_ids.index(selected_app_id) if selected_app_id in app_ids else 0
    c1, c2, c3 = st.columns([2.8, 1.1, 1.3], vertical_alignment="bottom")
    with c1:
        chosen_id = st.selectbox(
            "Selected Application",
            options=app_ids,
            index=default_idx,
            format_func=lambda aid: next(
                f"{r['applicant_id']} — {r.get('name', 'N/A')} ({r.get('source', 'synthetic')})"
                for r in catalog
                if r["applicant_id"] == aid
            ),
            key="results_app_selector",
        )
        if chosen_id != selected_app_id:
            st.session_state[STATE_SELECTED_APP_ID] = chosen_id
            st.session_state[STATE_SELECTED_RUN_ID] = None
    with c2:
        if st.button(
            "App Workspace",
            key="results_back_workspace",
            width="stretch",
        ):
            navigate_to("Application Details", applicant_id=chosen_id)
            st.rerun()
    with c3:
        if st.button(
            "Run / Re-evaluate",
            type="primary",
            key="btn_run_from_results",
            width="stretch",
        ):
            rec = get_applicant_record(chosen_id)
            if rec:
                try:
                    applicant_model = Applicant.model_validate(rec)
                    use_disk = has_physical_document_package(chosen_id)
                    with st.spinner(
                        f"Executing underwriting pipeline for {chosen_id}..."
                    ):
                        outcome = submit_application_and_underwrite(
                            applicant=applicant_model,
                            staged_uploads=[],
                            use_existing_package_if_empty=use_disk,
                            allow_duplicate=True,
                        )
                    store_live_result(chosen_id, outcome)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Underwriting run failed safely: {exc}")
    return chosen_id


def render_underwriting_results_view() -> None:
    """Render two-level Underwriting Results (Accessible Summary first, Technical Detail expandable)."""
    render_page_header(
        "Processing",
        "Underwriting Results",
        "Two-level decision report: executive underwriting summary up front and detailed technical telemetry on demand.",
        breadcrumbs=["Processing", "Underwriting"],
    )

    chosen_id = _render_run_action_header(st.session_state.get(STATE_SELECTED_APP_ID))
    if not chosen_id:
        return

    hist_runs = get_applicant_run_history(chosen_id)
    selected_run_id = st.session_state.get(STATE_SELECTED_RUN_ID)
    if hist_runs:
        run_opts = [r["run_id"] for r in hist_runs]
        run_idx = run_opts.index(selected_run_id) if selected_run_id in run_opts else 0
        chosen_run = st.selectbox(
            "Recorded Underwriting Run",
            options=run_opts,
            index=run_idx,
            format_func=lambda rid: next(
                f"{r['run_id']} · {r['timestamp'][:16].replace('T', ' ')} UTC · "
                f"{format_decision_label(r['recommendation'])} · {r['pipeline_status']}"
                for r in hist_runs
                if r["run_id"] == rid
            ),
            key="results_run_selector",
        )
        st.session_state[STATE_SELECTED_RUN_ID] = chosen_run
        selected_run_id = chosen_run

    ctx = _normalize_view_context(chosen_id, selected_run_id)
    if ctx is None:
        render_empty_state(
            "No Underwriting Run Recorded",
            f"Run the pipeline above for {chosen_id} or submit an application with documents in New Application.",
        )
        return

    render_hitl_banner()
    if ctx["pipeline_status"] == "FAILED":
        render_alert_box(
            "Pipeline Execution Interrupted",
            "This automated evaluation failed and never implies a valid approval or numeric zero risk score. Human triage is mandatory.",
            variant="danger",
        )

    # ------------------------------------------------------------------
    # LEVEL 1 — EXECUTIVE SUMMARY
    # ------------------------------------------------------------------
    case_summary = get_case_review_summary(chosen_id, run_id=ctx.get("run_id"))
    sep_head, sep_cta = st.columns([3.2, 1.3], vertical_alignment="bottom")
    with sep_head:
        render_section_heading(
            "Summary Level — Recommendation & Human Separation",
            "Clear separation between advisory AI verdicts and final human underwriter decisions",
        )
    with sep_cta:
        if st.button(
            "Open Human Review",
            key=f"results_goto_review_queue_{chosen_id}",
            width="stretch",
        ):
            navigate_to(
                "Underwriter Review Queue",
                applicant_id=chosen_id,
                run_id=ctx.get("run_id"),
            )
            st.rerun()

    render_human_vs_ai_summary_panel(case_summary)

    app_rec = get_applicant_record(chosen_id) or {}
    render_kv_grid(
        [
            ("Applicant ID", chosen_id),
            ("Applicant Name", str(app_rec.get("name", "N/A"))),
            ("Requested Loan", format_inr(app_rec.get("loan_amount"))),
            ("Employment Type", str(app_rec.get("employment_type", "N/A"))),
        ],
        columns=4,
    )

    score_str = format_risk_score_display(ctx.get("risk_score"))
    fraud_disp = format_fraud_status_display(ctx.get("fraud_status"))
    anom_data = ctx.get("anomaly") or {}
    anom_cnt = len(anom_data.get("flags", []))
    miss_cnt = len(ctx.get("missing_documents") or [])

    r_col, d1, d2, d3, d4 = st.columns([1.25, 1, 1.15, 1.1, 1.1])
    with r_col:
        render_recommendation_badge(ctx["recommendation"])
        st.caption(f"Confidence (Heuristic): {ctx['confidence']:.1f}%")
    with d1:
        d1.metric("Eligibility Status", ctx["eligibility_status"])
    with d2:
        d2.metric(
            "Risk Assessment",
            ctx["risk_category"],
            delta=f"Score: {score_str}",
            delta_color="off",
            delta_arrow="off",
        )
    with d3:
        d3.metric(
            "Fraud / Anomaly",
            fraud_disp.split(" ")[0],
            delta=(
                "Unavailable"
                if ctx.get("fraud_status") == "UNAVAILABLE"
                else f"{anom_cnt} flag(s)"
            ),
            delta_color=(
                "inverse"
                if anom_cnt > 0 or ctx.get("fraud_status") == "UNAVAILABLE"
                else "off"
            ),
            delta_arrow="off",
        )
    with d4:
        d4.metric(
            "Document Verification",
            ctx["document_verification_status"],
            delta=f"{miss_cnt} missing" if miss_cnt > 0 else "Complete package",
            delta_color="inverse" if miss_cnt > 0 else "normal",
            delta_arrow="off",
        )

    with st.container(border=True):
        render_section_heading(
            "Key Findings & Recommendation Rationale",
            "Non-technical summary of primary decision drivers and human review triggers",
        )
        render_alert_box(
            "Executive Summary",
            ctx["summary"] or "No summary recorded.",
            variant="info",
        )

        if ctx.get("review_reasons"):
            st.markdown("**Why Human Review Is Required**")
            for msg in ctx["review_reasons"]:
                st.warning(msg)

        if ctx.get("reasons"):
            st.markdown("**Primary Reason Codes**")
            render_banking_table(
                headers=["Code", "Category", "Severity", "Source", "Summary"],
                rows=[
                    [
                        str(r.get("code", "")),
                        str(r.get("category", "")),
                        str(r.get("severity", "")),
                        str(r.get("source_agent", "")),
                        str(r.get("description", "")),
                    ]
                    for r in ctx["reasons"]
                ],
                pill_columns={2},
            )

        render_factor_cards(
            positive_factors=ctx.get("positive_factors") or [],
            negative_factors=ctx.get("negative_factors") or [],
            blocking_factors=ctx.get("blocking_factors") or [],
        )

    if ctx["audit_persisted"] and ctx.get("run_id"):
        st.caption(
            f"Audit Record Verified: `{ctx['run_id']}` · Pipeline `{ctx['pipeline_status']}` · Latency {ctx['duration_ms']:.1f} ms"
        )
    elif ctx.get("run_id"):
        st.caption(
            f"Historical Run `{ctx['run_id']}` · Pipeline `{ctx['pipeline_status']}`"
        )
    else:
        st.warning(
            f"Audit persistence unavailable ({ctx.get('audit_error') or 'not persisted'})."
        )

    # ------------------------------------------------------------------
    # LEVEL 2 — DETAILED TECHNICAL ANALYSIS
    # ------------------------------------------------------------------
    with st.expander(
        "Detailed Analysis — Agent Outputs, Feature Explanations, Consistency & Execution Telemetry",
        expanded=False,
    ):
        tab_elig, tab_risk, tab_fraud, tab_cons, tab_agents = st.tabs(
            [
                "Eligibility Rules",
                "Credit Risk & Features",
                "Fraud & Anomaly Flags",
                "Consistency Checks",
                "Execution Telemetry",
            ]
        )

        with tab_elig:
            elig = ctx.get("eligibility")
            if elig:
                dti = elig.get("dti_ratio")
                dti_txt = f"{dti:.1f}%" if dti is not None else "Unavailable"
                render_kv_grid(
                    [
                        ("Eligibility Status", str(elig["status"])),
                        ("Policy Version", str(elig.get("policy_version", "N/A"))),
                        (
                            "Max Permitted Loan",
                            format_inr(elig.get("max_eligible_amount")),
                        ),
                        ("DTI Ratio", dti_txt),
                    ],
                    columns=4,
                )
                if elig.get("rule_results"):
                    render_banking_table(
                        headers=["Rule", "Status", "Actual", "Expected", "Reason"],
                        rows=[
                            [
                                str(r.get("rule_name", r.get("rule_id"))),
                                str(r.get("status", "")),
                                str(r.get("actual_value", "")),
                                str(r.get("expected_value", "")),
                                str(r.get("reason", "")),
                            ]
                            for r in elig["rule_results"]
                        ],
                        pill_columns={1},
                    )
            else:
                render_alert_box(
                    "Eligibility Unavailable",
                    "Eligibility agent output is unavailable for this run.",
                    variant="danger",
                )

        with tab_risk:
            risk = ctx.get("risk")
            if risk:
                model_avail = (
                    "Available"
                    if ctx.get("risk_score") is not None
                    else "UNAVAILABLE (Invalid / Missing Score)"
                )
                render_kv_grid(
                    [
                        ("Risk Category", str(risk["risk_category"])),
                        (
                            "Risk Score",
                            format_risk_score_display(ctx.get("risk_score")),
                        ),
                        ("Model Status", model_avail),
                        (
                            "Methodology",
                            f"{risk.get('method', 'N/A')} ({risk.get('model_version', 'N/A')})",
                        ),
                    ],
                    columns=4,
                )
                col_pf, col_rf = st.columns(2)
                with col_pf:
                    st.markdown("**Protective Factors**")
                    for item in risk.get("protective_factors", []) or ["None"]:
                        st.write(f"- {item}")
                with col_rf:
                    st.markdown("**Risk Factors**")
                    for item in risk.get("risk_factors", []) or ["None"]:
                        st.write(f"- {item}")
                if risk.get("feature_importance"):
                    st.markdown("**Feature Contributions**")
                    render_banking_table(
                        headers=["Feature", "Relative Importance"],
                        rows=[
                            [k, f"{float(v):.4f}"]
                            for k, v in sorted(
                                risk["feature_importance"].items(),
                                key=lambda kv: kv[1],
                                reverse=True,
                            )
                        ],
                    )
            else:
                render_alert_box(
                    "Risk Assessment Unavailable",
                    "RiskAgent failed or model could not load. Unavailable scores never default to zero.",
                    variant="danger",
                )

        with tab_fraud:
            anom = ctx.get("anomaly")
            if anom:
                render_kv_grid(
                    [
                        (
                            "Anomaly Severity",
                            format_fraud_status_display(anom.get("severity")),
                        ),
                        (
                            "Anomaly Score",
                            f"{float(anom.get('anomaly_score', 0.0)):.1f} / 100",
                        ),
                        ("Detected Flags", str(len(anom.get("flags", [])))),
                    ],
                    columns=3,
                )
                if anom.get("missing_evidence"):
                    st.info(
                        "Unverified due to missing documents (not treated as fraud): "
                        + ", ".join(anom["missing_evidence"])
                    )
                if anom.get("flags"):
                    render_banking_table(
                        headers=[
                            "Rule",
                            "Type",
                            "Severity",
                            "Observed",
                            "Expected",
                            "Description",
                        ],
                        rows=[
                            [
                                str(f.get("rule_id", "")),
                                str(f.get("anomaly_type", "")),
                                str(f.get("severity", "")),
                                str(f.get("observed_value", "")),
                                str(f.get("expected_value", "")),
                                str(f.get("description", "")),
                            ]
                            for f in anom["flags"]
                        ],
                        pill_columns={2},
                    )
                else:
                    st.success(
                        "No cross-document anomalies detected among available documents."
                    )
            else:
                render_alert_box(
                    "Fraud Assessment Unavailable",
                    "FraudAnomalyAgent output is unavailable; never treated as clean.",
                    variant="danger",
                )

        with tab_cons:
            render_conflicts_panel(ctx.get("consistency_conflicts") or [])
            if ctx.get("validation_warnings"):
                st.markdown("**Input Validation Warnings**")
                for w in ctx["validation_warnings"]:
                    st.write(f"- {w}")

        with tab_agents:
            exec_details = ctx.get("agent_execution_details") or {}
            if exec_details:
                render_banking_table(
                    headers=["Agent", "Status", "Output", "Latency (ms)", "Error"],
                    rows=[
                        [
                            name,
                            str(det.get("status", "")),
                            "Available" if det.get("output_available") else "Missing",
                            str(det.get("duration_ms", "—")),
                            str(det.get("error") or "None"),
                        ]
                        for name, det in sorted(exec_details.items())
                    ],
                    pill_columns={1},
                )
            elif ctx.get("agent_statuses"):
                render_banking_table(
                    headers=["Agent", "Status"],
                    rows=[
                        [k, str(v)] for k, v in sorted(ctx["agent_statuses"].items())
                    ],
                    pill_columns={1},
                )
            else:
                st.caption("No agent execution telemetry recorded.")


def render_document_review_view() -> None:
    """Render Document Verification as an evidence-review workspace with collapsible technical OCR."""
    render_page_header(
        "Processing",
        "Document Verification",
        "Evidence-review workspace showing required checklist, verified fields, missing paperwork, and conflicts.",
        breadcrumbs=["Processing", "Document Verification"],
    )

    chosen_id = st.session_state.get(STATE_SELECTED_APP_ID)
    selected_run_id = st.session_state.get(STATE_SELECTED_RUN_ID)

    catalog = load_applicant_catalog()
    app_ids = [rec["applicant_id"] for rec in catalog]
    if app_ids:
        idx = app_ids.index(chosen_id) if chosen_id in app_ids else 0
        c_sel, c_ws, c_up = st.columns([2.8, 1.1, 1.1], vertical_alignment="bottom")
        with c_sel:
            chosen_id = st.selectbox(
                "Application Document Package",
                options=app_ids,
                index=idx,
                format_func=lambda aid: next(
                    f"{r['applicant_id']} — {r.get('name', 'N/A')} ({r.get('source', 'synthetic')})"
                    for r in catalog
                    if r["applicant_id"] == aid
                ),
                key="doc_review_app_selector",
            )
            st.session_state[STATE_SELECTED_APP_ID] = chosen_id
        with c_ws:
            if st.button("App Workspace", key="docs_back_ws", width="stretch"):
                navigate_to("Application Details", applicant_id=chosen_id)
                st.rerun()
        with c_up:
            if st.button("Upload Docs", key="docs_goto_upload", width="stretch"):
                rec = get_applicant_record(chosen_id)
                if rec:
                    queue_existing_applicant_for_intake(rec)
                navigate_to("New Application", applicant_id=chosen_id)
                st.rerun()

    ctx = _normalize_view_context(chosen_id, selected_run_id)
    doc_pkg = ctx.get("document_package") if ctx else None

    if doc_pkg is None:
        preview_cache = st.session_state.get(STATE_DOC_PREVIEW_CACHE, {})
        if preview_cache:
            latest_pkg: DocumentPackageResult = list(preview_cache.values())[-1]
            doc_pkg = {
                "processing_status": latest_pkg.processing_status,
                "processing_errors": list(latest_pkg.processing_errors),
                "is_complete": latest_pkg.is_complete,
                "ocr_used": latest_pkg.ocr_used,
                "expected_documents": list(latest_pkg.expected_documents),
                "documents_missing": list(latest_pkg.documents_missing),
                "unclassified_documents": list(latest_pkg.unclassified_documents),
                "duplicate_documents": list(latest_pkg.duplicate_documents),
                "missing_fields": dict(latest_pkg.missing_fields),
                "invalid_fields": dict(latest_pkg.invalid_fields),
                "ambiguous_fields": dict(latest_pkg.ambiguous_fields),
                "field_conflicts": dict(latest_pkg.field_conflicts),
                "security_warnings": list(latest_pkg.security_warnings),
                "documents_found": [
                    {
                        "document_id": d.document_id,
                        "filename": (
                            os.path.basename(d.file_path)
                            if d.file_path
                            else d.document_id
                        ),
                        "document_type": d.document_type,
                        "classification_confidence": float(d.classification_confidence),
                        "classification_status": d.classification_status,
                        "classification_evidence": mask_extracted_value(
                            "evidence", d.classification_evidence
                        ),
                        "is_scanned": d.is_scanned,
                        "extraction_method": d.extraction_method,
                        "page_count": d.page_count,
                        "native_text_pages": d.native_text_pages,
                        "ocr_pages": d.ocr_pages,
                        "empty_pages": d.empty_pages,
                        "failed_pages": d.failed_pages,
                        "extracted_fields": {
                            fn: {
                                "field_name": ef.field_name,
                                "value": mask_extracted_value(
                                    fn, ef.value, ef.masked_value
                                ),
                                "confidence": float(ef.confidence),
                                "source_document": ef.source_document,
                                "page_number": int(ef.page_number),
                                "extraction_method": ef.extraction_method,
                                "validation_status": ef.validation_status,
                                "validation_message": ef.validation_message,
                                "evidence": mask_extracted_value(
                                    "evidence", ef.evidence
                                ),
                            }
                            for fn, ef in sorted(d.extracted_fields.items())
                        },
                    }
                    for d in latest_pkg.documents_found
                ],
            }
            st.info("Showing staged pre-submission document verification preview.")

    if not doc_pkg:
        render_empty_state(
            "No Document Package Processed Yet",
            "Upload supporting PDFs via the Intake Wizard or evaluate this case in Underwriting Results.",
        )
        return

    render_kpi_row(
        [
            {
                "label": "Verification Status",
                "value": format_compact_status(doc_pkg.get("processing_status")),
                "accent": "teal" if not doc_pkg.get("documents_missing") else "amber",
            },
            {
                "label": "Uploaded Docs",
                "value": len(doc_pkg.get("documents_found", [])),
                "accent": "indigo",
            },
            {
                "label": "Missing Required",
                "value": len(doc_pkg.get("documents_missing", [])),
                "accent": "coral" if doc_pkg.get("documents_missing") else "teal",
            },
            {
                "label": "Unclassified Docs",
                "value": len(doc_pkg.get("unclassified_documents", [])),
                "accent": (
                    "amber" if doc_pkg.get("unclassified_documents") else "indigo"
                ),
            },
        ]
    )

    # Required Document Checklist
    app_rec = get_applicant_record(chosen_id) or {}
    expected_cats = doc_pkg.get(
        "expected_documents"
    ) or expected_documents_for_employment(
        str(app_rec.get("employment_type", "Salaried"))
    )
    docs_found = doc_pkg.get("documents_found", [])
    found_by_type: Dict[str, List[Dict[str, Any]]] = {}
    for d in docs_found:
        found_by_type.setdefault(str(d.get("document_type", "unknown")), []).append(d)

    with st.container(border=True):
        render_section_heading(
            "Required Document Checklist",
            "Verification status across mandatory applicant document categories",
        )
        checklist_rows: List[List[str]] = []
        for cat in expected_cats:
            matched = found_by_type.get(cat, [])
            if matched:
                filenames = ", ".join(
                    str(m.get("filename", "doc.pdf")) for m in matched
                )
                status = "Verified"
            else:
                filenames = "—"
                status = "Missing"
            checklist_rows.append([cat, "Mandatory", status, filenames])
        render_banking_table(
            headers=["Document Category", "Requirement", "Status", "Matched File(s)"],
            rows=checklist_rows,
            pill_columns={2},
        )

    # Alerts & Conflicts requiring human attention
    if doc_pkg.get("documents_missing"):
        render_alert_box(
            "Missing Required Documents",
            ", ".join(doc_pkg["documents_missing"]),
            variant="warning",
        )
    if doc_pkg.get("unclassified_documents"):
        render_alert_box(
            "Unclassified Files",
            ", ".join(doc_pkg["unclassified_documents"]),
            variant="danger",
        )
    if doc_pkg.get("security_warnings"):
        render_alert_box(
            "PDF Security Warnings",
            "; ".join(doc_pkg["security_warnings"]),
            variant="warning",
        )
    if doc_pkg.get("field_conflicts"):
        render_alert_box(
            "Conflicting Extracted Information",
            str(doc_pkg["field_conflicts"]),
            variant="danger",
        )
    if doc_pkg.get("processing_errors"):
        render_alert_box(
            "Extraction Warnings / Errors",
            "; ".join(doc_pkg["processing_errors"]),
            variant="danger",
        )

    if not docs_found:
        render_empty_state(
            "Zero Classified Documents Found",
            "Upload missing PDF documents to verify applicant income, identity, and bank balances.",
        )
        return

    render_section_heading(
        "Extracted Evidence & Field Verification",
        "Extracted applicant fields (PII masked); technical OCR telemetry resides in expanders below",
    )
    missing_fields_map = doc_pkg.get("missing_fields", {})
    invalid_fields_map = doc_pkg.get("invalid_fields", {})
    ambiguous_fields_map = doc_pkg.get("ambiguous_fields", {})

    for doc in docs_found:
        fname = str(doc.get("filename", doc.get("document_id", "Document")))
        dtype = str(doc.get("document_type", "unknown"))
        clf_conf = float(doc.get("classification_confidence", 0.0)) * 100.0
        ext_map = doc.get("extracted_fields", {})
        verified_cnt = sum(
            1
            for f in ext_map.values()
            if str(f.get("validation_status", "valid")).lower() == "valid"
        )
        doc_miss = missing_fields_map.get(fname, [])
        doc_inv = invalid_fields_map.get(fname, [])
        doc_amb = ambiguous_fields_map.get(fname, [])

        with st.container(border=True):
            top_l, top_r = st.columns([3.0, 1.4], vertical_alignment="center")
            with top_l:
                st.markdown(
                    f"**{fname}** &nbsp; {render_status_pill(dtype, 'teal')} &nbsp; "
                    f"{render_status_pill(str(doc.get('classification_status', 'N/A')))}",
                    unsafe_allow_html=True,
                )
            with top_r:
                st.caption(
                    f"Verified: {verified_cnt} · Missing: {len(doc_miss)} · Invalid: {len(doc_inv)}"
                )

            if doc_miss:
                st.warning(f"Missing Expected Fields: {', '.join(doc_miss)}")
            if doc_inv:
                st.error(f"Invalid Fields: {doc_inv}")
            if doc_amb:
                st.warning(f"Ambiguous Fields: {doc_amb}")

            if ext_map:
                primary_rows: List[List[str]] = []
                tech_rows: List[List[str]] = []
                for field_key, fdata in ext_map.items():
                    vstat = str(fdata.get("validation_status", "valid")).lower()
                    primary_rows.append(
                        [
                            str(fdata.get("field_name", field_key)),
                            str(fdata.get("value", "N/A")),
                            format_compact_status(vstat),
                            str(fdata.get("page_number", 1)),
                        ]
                    )
                    tech_rows.append(
                        [
                            str(fdata.get("field_name", field_key)),
                            str(fdata.get("extraction_method", "N/A")),
                            f"{float(fdata.get('confidence', 0.0)) * 100:.1f}%",
                            str(fdata.get("validation_message") or "—"),
                            str(fdata.get("evidence", "")),
                        ]
                    )
                render_banking_table(
                    headers=["Field", "Extracted Value (Masked)", "Validation", "Page"],
                    rows=primary_rows,
                    pill_columns={2},
                )
                with st.expander(
                    "Technical OCR & Extraction Diagnostics", expanded=False
                ):
                    render_kv_grid(
                        [
                            ("Detected Category", dtype),
                            ("Heuristic Confidence", f"{clf_conf:.1f}%"),
                            (
                                "Extraction Method",
                                str(doc.get("extraction_method", "digital")),
                            ),
                            (
                                "Pages (Native / OCR / Empty / Fail)",
                                f"{doc.get('native_text_pages', 0)} / {doc.get('ocr_pages', 0)} / "
                                f"{doc.get('empty_pages', 0)} / {doc.get('failed_pages', 0)}",
                            ),
                        ],
                        columns=4,
                    )
                    render_banking_table(
                        headers=[
                            "Field",
                            "Method",
                            "Heuristic Conf",
                            "Message",
                            "Masked Evidence",
                        ],
                        rows=tech_rows,
                    )
            else:
                st.caption("No structured fields extracted from this document.")
