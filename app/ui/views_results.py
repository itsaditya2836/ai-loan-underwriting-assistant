"""Underwriting Results & Document Review Views.

Supports both live execution bundles (in session state) and persisted historical
records from SQLite (`underwriting_runs.details_snapshot`), preserving unavailable
statuses honestly and masking sensitive personal/account identifiers.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import pandas as pd
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
    render_conflicts_panel,
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
        st.info("No applications available yet. Create one in New Application.")
        if st.button("Go to New Application", key="results_goto_intake"):
            navigate_to("New Application")
            st.rerun()
        return None

    default_idx = app_ids.index(selected_app_id) if selected_app_id in app_ids else 0
    c1, c2 = st.columns([3.2, 1.3], vertical_alignment="bottom")
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
            "Run / Re-evaluate Pipeline",
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
    """Render explainable Underwriting Results clearly separating AI output from human decision."""
    render_page_header(
        "Underwriting",
        "Underwriting Results",
        "AI decision-support outcome, primary reason codes, and clear separation from final human decisions.",
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
        st.info(
            f"No underwriting run is recorded yet for `{chosen_id}`. "
            "Use **Run / Re-evaluate Pipeline** above or submit an application in **New Application**."
        )
        return

    render_hitl_banner()

    # ------------------------------------------------------------------
    # 1. Decision Separation: AI Recommendation vs Final Human Decision
    # ------------------------------------------------------------------
    case_summary = get_case_review_summary(chosen_id, run_id=ctx.get("run_id"))
    sep_head, sep_cta = st.columns([3.2, 1.3], vertical_alignment="bottom")
    with sep_head:
        render_section_heading(
            "Decision Separation (AI Recommendation vs Final Human Decision)",
            "Automated outputs never serve as final lending approval without authorized human sign-off",
        )
    with sep_cta:
        if st.button(
            "Open in Review Queue",
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

    # ------------------------------------------------------------------
    # 2. Primary Decision, Reasons & Key Domain Indicators First
    # ------------------------------------------------------------------
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

    render_section_heading(
        "AI Underwriting Recommendation & Domain Summary",
        "Primary domain verdicts alongside deterministic evidence-agreement confidence (not a default probability)",
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

    # Primary Narrative & Reason Codes Immediately Visible
    with st.container(border=True):
        render_section_heading("Decision Rationale & Key Safeguards")
        st.info(f"**Executive Summary:** {ctx['summary'] or 'No summary recorded.'}")

        if ctx.get("review_reasons"):
            st.markdown("**Manual Review Triggers:**")
            for msg in ctx["review_reasons"]:
                st.warning(msg)

        if ctx.get("reasons"):
            st.markdown("**Primary Decision Reason Codes:**")
            for idx, r in enumerate(ctx["reasons"], 1):
                st.markdown(
                    f"{idx}. **`[{r.get('code')}]` ({r.get('category')} · {r.get('severity')})** — "
                    f"{r.get('description')}  \n"
                    f"<span style='font-size:0.8rem;color:#64748B;'>Source: {r.get('source_agent')} · "
                    f"Evidence: {mask_extracted_value('evidence', r.get('evidence')) if r.get('evidence') else 'N/A'}</span>",
                    unsafe_allow_html=True,
                )

        render_conflicts_panel(ctx.get("consistency_conflicts") or [])
        render_factor_cards(
            positive_factors=ctx.get("positive_factors") or [],
            negative_factors=ctx.get("negative_factors") or [],
            blocking_factors=ctx.get("blocking_factors") or [],
        )

    # Audit status quiet confirmation strip
    if ctx["audit_persisted"] and ctx.get("run_id"):
        st.caption(
            f"Audit Record Verified: `{ctx['run_id']}` · Pipeline Status `{ctx['pipeline_status']}` · Latency {ctx['duration_ms']:.1f} ms"
        )
    elif ctx.get("run_id"):
        st.caption(
            f"Historical Run `{ctx['run_id']}` · Pipeline Status `{ctx['pipeline_status']}`"
        )
    else:
        st.warning(
            f"Audit persistence unavailable for this run ({ctx.get('audit_error') or 'not persisted'})."
        )

    # ------------------------------------------------------------------
    # 3. Expandable Detailed Evidence & Technical Agent Telemetry
    # ------------------------------------------------------------------
    with st.expander(
        "Detailed Domain Breakdown & Technical Agent Telemetry", expanded=False
    ):
        if ctx.get("validation_warnings"):
            st.markdown("**Input Validation Warnings**")
            for w in ctx["validation_warnings"]:
                st.write(f"- {w}")

        tab_elig, tab_risk, tab_fraud, tab_doc, tab_agents = st.tabs(
            [
                "Eligibility",
                "Risk Assessment",
                "Fraud Assessment",
                "Document Verification",
                "Agent Telemetry",
            ]
        )

        with tab_elig:
            elig = ctx.get("eligibility")
            if elig:
                st.markdown(
                    f"**Status:** `{elig['status']}` | **Policy:** `{elig.get('policy_version', 'N/A')}`"
                )
                dti = elig.get("dti_ratio")
                dti_txt = f"{dti:.1f}%" if dti is not None else "N/A"
                st.markdown(
                    f"**Max Permitted Loan:** {format_inr(elig.get('max_eligible_amount'))} | **DTI Ratio:** `{dti_txt}`"
                )
                if elig.get("rule_results"):
                    st.dataframe(
                        pd.DataFrame(elig["rule_results"]),
                        width="stretch",
                        hide_index=True,
                    )
            else:
                st.error("Eligibility assessment output is UNAVAILABLE for this run.")

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
                    fi_df = pd.DataFrame(
                        [
                            {"Feature": k, "Importance": round(float(v), 4)}
                            for k, v in sorted(
                                risk["feature_importance"].items(),
                                key=lambda kv: kv[1],
                                reverse=True,
                            )
                        ]
                    )
                    st.dataframe(fi_df, width="stretch", hide_index=True)
            else:
                st.error(
                    "Risk assessment is UNAVAILABLE (RiskAgent failed or model failed to load)."
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
                        "Unverified due to missing documents (not flagged as fraud): "
                        + ", ".join(anom["missing_evidence"])
                    )
                if anom.get("flags"):
                    st.dataframe(
                        pd.DataFrame(anom["flags"]),
                        width="stretch",
                        hide_index=True,
                    )
                else:
                    st.success(
                        "No cross-document anomalies detected among available documents."
                    )
            else:
                st.error("Fraud / anomaly detection is UNAVAILABLE for this run.")

        with tab_doc:
            doc_pkg = ctx.get("document_package")
            if doc_pkg:
                render_kv_grid(
                    [
                        ("Status", str(doc_pkg.get("processing_status", "N/A"))),
                        (
                            "Expected Docs",
                            str(len(doc_pkg.get("expected_documents", []))),
                        ),
                        (
                            "Submitted Docs",
                            str(len(doc_pkg.get("documents_found", []))),
                        ),
                        (
                            "Missing Docs",
                            str(len(doc_pkg.get("documents_missing", []))),
                        ),
                    ],
                    columns=4,
                )
                if doc_pkg.get("documents_missing"):
                    st.warning(
                        f"**Missing Documents:** {', '.join(doc_pkg['documents_missing'])}"
                    )
                if doc_pkg.get("unclassified_documents"):
                    st.error(
                        f"**Unclassified Documents:** {', '.join(doc_pkg['unclassified_documents'])}"
                    )
                if st.button("Open Document Review", key="results_open_doc_review"):
                    navigate_to(
                        "Document Review",
                        applicant_id=chosen_id,
                        run_id=ctx.get("run_id"),
                    )
                    st.rerun()
            else:
                st.warning(
                    "No detailed document verification snapshot is available for this record."
                )

        with tab_agents:
            exec_details = ctx.get("agent_execution_details") or {}
            if exec_details:
                rows = [
                    {
                        "Agent": name,
                        "Status": det.get("status"),
                        "Output Available": det.get("output_available"),
                        "Latency (ms)": det.get("duration_ms"),
                        "Warnings": "; ".join(det.get("warnings", [])) or "None",
                        "Error": det.get("error") or "None",
                    }
                    for name, det in sorted(exec_details.items())
                ]
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            elif ctx.get("agent_statuses"):
                rows = [
                    {"Agent": k, "Status": v}
                    for k, v in sorted(ctx["agent_statuses"].items())
                ]
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            else:
                st.caption("No agent execution telemetry recorded.")


def render_document_review_view() -> None:
    """Render Document Review page highlighting verification states with technical details secondary."""
    render_page_header(
        "Underwriting",
        "Document Review",
        "Document classification, field completeness, validation status, and masked extracted evidence.",
    )

    chosen_id = st.session_state.get(STATE_SELECTED_APP_ID)
    selected_run_id = st.session_state.get(STATE_SELECTED_RUN_ID)

    catalog = load_applicant_catalog()
    app_ids = [rec["applicant_id"] for rec in catalog]
    if app_ids:
        idx = app_ids.index(chosen_id) if chosen_id in app_ids else 0
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
            st.info("Showing staged pre-submission document extraction preview.")

    if not doc_pkg:
        st.info(
            "No processed document package found for the selected application. "
            "Upload documents in **New Application** or run the pipeline from **Underwriting Results**."
        )
        return

    render_kpi_row(
        [
            {
                "label": "Intake Status",
                "value": format_compact_status(doc_pkg.get("processing_status")),
            },
            {
                "label": "Processed Docs",
                "value": len(doc_pkg.get("documents_found", [])),
            },
            {
                "label": "Missing Required",
                "value": len(doc_pkg.get("documents_missing", [])),
            },
            {
                "label": "Unclassified Docs",
                "value": len(doc_pkg.get("unclassified_documents", [])),
            },
            {
                "label": "OCR Triggered",
                "value": "Yes" if doc_pkg.get("ocr_used") else "No",
            },
        ]
    )

    if doc_pkg.get("documents_missing"):
        st.warning(
            f"**Missing Required Documents:** {', '.join(doc_pkg['documents_missing'])}"
        )
    if doc_pkg.get("unclassified_documents"):
        st.error(
            f"**Unclassified Documents:** {', '.join(doc_pkg['unclassified_documents'])}"
        )
    if doc_pkg.get("security_warnings"):
        st.warning("**Security Warnings:** " + "; ".join(doc_pkg["security_warnings"]))
    if doc_pkg.get("duplicate_documents"):
        st.info(
            f"**Duplicate Documents Detected:** {len(doc_pkg['duplicate_documents'])}"
        )
    if doc_pkg.get("processing_errors"):
        st.error(
            "**Processing / Extraction Errors:** "
            + "; ".join(doc_pkg["processing_errors"])
        )
    if doc_pkg.get("field_conflicts"):
        st.error(f"**Cross-Document Field Conflicts:** {doc_pkg['field_conflicts']}")

    docs_found = doc_pkg.get("documents_found", [])
    if not docs_found:
        st.warning("Zero readable classified documents found in this package.")
        return

    render_section_heading(
        "Submitted Documents & Field Verification",
        "Verified, missing, invalid, and ambiguous field counts are separated clearly per document",
    )
    missing_fields_map = doc_pkg.get("missing_fields", {})
    invalid_fields_map = doc_pkg.get("invalid_fields", {})
    ambiguous_fields_map = doc_pkg.get("ambiguous_fields", {})

    for doc in docs_found:
        fname = doc.get("filename", doc.get("document_id", "Document"))
        dtype = doc.get("document_type", "unknown")
        clf_conf = float(doc.get("classification_confidence", 0.0)) * 100.0
        ocr_status = (
            "OCR Used"
            if doc.get("is_scanned") or doc.get("ocr_pages", 0) > 0
            else "Native Digital"
        )
        ext_map = doc.get("extracted_fields", {})
        verified_cnt = sum(
            1
            for f in ext_map.values()
            if str(f.get("validation_status", "valid")).lower() == "valid"
        )
        unverified_cnt = len(ext_map) - verified_cnt
        doc_miss = missing_fields_map.get(fname, [])
        doc_inv = invalid_fields_map.get(fname, [])
        doc_amb = ambiguous_fields_map.get(fname, [])

        with st.container(border=True):
            top_l, top_r = st.columns([3, 1.5], vertical_alignment="center")
            with top_l:
                st.markdown(
                    f"**{fname}** &nbsp; "
                    f"{render_status_pill(dtype, 'info')} &nbsp; "
                    f"{render_status_pill(str(doc.get('classification_status', 'N/A')))}",
                    unsafe_allow_html=True,
                )
            with top_r:
                st.markdown(
                    f"<div style='text-align:right;font-size:0.8rem;color:#475569;'>"
                    f"Pages: {doc.get('page_count', 1)} ({ocr_status}) · Conf {clf_conf:.0f}%</div>",
                    unsafe_allow_html=True,
                )

            render_kv_grid(
                [
                    ("Verified Fields", str(verified_cnt)),
                    ("Unverified Fields", str(unverified_cnt)),
                    ("Missing Fields", str(len(doc_miss))),
                    (
                        "Invalid / Ambiguous",
                        f"{len(doc_inv)} invalid · {len(doc_amb)} ambiguous",
                    ),
                ],
                columns=4,
            )

            if doc_miss:
                st.warning(f"**Missing Expected Fields:** {', '.join(doc_miss)}")
            if doc_inv:
                st.error(f"**Invalid Fields:** {doc_inv}")
            if doc_amb:
                st.warning(f"**Ambiguous Fields:** {doc_amb}")

            if ext_map:
                primary_rows = []
                tech_rows = []
                for field_key, fdata in ext_map.items():
                    vstat = str(fdata.get("validation_status", "valid")).lower()
                    primary_rows.append(
                        {
                            "Field": fdata.get("field_name", field_key),
                            "Extracted Value (Masked)": str(fdata.get("value", "N/A")),
                            "Validation": format_compact_status(vstat),
                            "Page": fdata.get("page_number", 1),
                        }
                    )
                    tech_rows.append(
                        {
                            "Field": fdata.get("field_name", field_key),
                            "Method": fdata.get("extraction_method", "N/A"),
                            "Heuristic Confidence": f"{float(fdata.get('confidence', 0.0)) * 100:.1f}%",
                            "Validation Message": fdata.get("validation_message")
                            or "—",
                            "Evidence Snippet (Masked)": str(fdata.get("evidence", "")),
                        }
                    )
                st.dataframe(
                    pd.DataFrame(primary_rows), width="stretch", hide_index=True
                )
                with st.expander(
                    "Technical Extraction Telemetry & Evidence", expanded=False
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
                    st.dataframe(
                        pd.DataFrame(tech_rows), width="stretch", hide_index=True
                    )
            else:
                st.caption("No structured fields extracted from this document.")
