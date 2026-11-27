"""Underwriting Results & Document Review Views for Stage 5.

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
from app.schemas.applicant import Applicant, DocumentPackageResult
from app.schemas.decision import DecisionReasoningResult
from app.schemas.underwriting import UnderwritingAnalysisResult
from app.ui.components import (
    format_eligibility_metrics_summary,
    format_fraud_status_display,
    format_inr,
    format_risk_score_display,
    render_conflicts_panel,
    render_factor_cards,
    render_hitl_banner,
    render_recommendation_badge,
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
    """Allow selecting an application and triggering a real Stage 4 evaluation if desired."""
    catalog = load_applicant_catalog()
    app_ids = [rec["applicant_id"] for rec in catalog]

    if not app_ids:
        st.info("No applications available yet. Create one in 'New Application'.")
        if st.button("Go to New Application →", key="results_goto_intake"):
            navigate_to("New Application")
            st.rerun()
        return None

    default_idx = app_ids.index(selected_app_id) if selected_app_id in app_ids else 0
    c1, c2 = st.columns([3, 1.5])
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
        st.write("")
        st.write("")
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
                        f"Running Stage 4 underwriting pipeline for {chosen_id}..."
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
    """Render comprehensive Stage 4 & Stage 5 explainable Underwriting Results page."""
    st.subheader("Underwriting Results & Decision Explainability")
    chosen_id = _render_run_action_header(st.session_state.get(STATE_SELECTED_APP_ID))
    if not chosen_id:
        return

    hist_runs = get_applicant_run_history(chosen_id)
    selected_run_id = st.session_state.get(STATE_SELECTED_RUN_ID)
    if hist_runs:
        run_opts = [r["run_id"] for r in hist_runs]
        run_idx = run_opts.index(selected_run_id) if selected_run_id in run_opts else 0
        chosen_run = st.selectbox(
            "Inspect Recorded Underwriting Run",
            options=run_opts,
            index=run_idx,
            format_func=lambda rid: next(
                f"{r['run_id']} | {r['timestamp'][:19].replace('T', ' ')} | "
                f"{format_decision_label(r['recommendation'])} | {r['pipeline_status']}"
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
            f"No underwriting run has been recorded yet for `{chosen_id}`. "
            "Click **Run / Re-evaluate Pipeline** above or submit an application with documents in **New Application**."
        )
        return

    render_hitl_banner()

    # Audit Persistence Banner
    if ctx["audit_persisted"] and ctx.get("run_id"):
        st.success(
            f"Audit Record Verified (`{ctx['run_id']}`) | Pipeline Status: `{ctx['pipeline_status']}` | "
            f"Latency: {ctx['duration_ms']:.1f} ms"
        )
    elif ctx.get("run_id"):
        st.info(
            f"Historical Run: `{ctx['run_id']}` | Pipeline Status: `{ctx['pipeline_status']}`"
        )
    else:
        st.warning(
            f"Audit persistence unavailable for this run ({ctx.get('audit_error') or 'not persisted'}). "
            "Analytical findings shown from in-memory execution only."
        )

    # Applicant Summary Strip
    app_rec = get_applicant_record(chosen_id) or {}
    st.markdown("### Applicant Summary")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Applicant Reference", chosen_id)
    s2.metric("Applicant Name", app_rec.get("name", "N/A"))
    s3.metric("Requested Loan", format_inr(app_rec.get("loan_amount")))
    s4.metric("Employment Type", str(app_rec.get("employment_type", "N/A")))

    # Top Recommendation & Agent Summary Metrics
    st.markdown("### Final Decision & Domain Status Summary")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        render_recommendation_badge(ctx["recommendation"])
    with c2:
        st.metric(
            "Decision Confidence",
            f"{ctx['confidence']:.1f}%",
            help="Deterministic evidence agreement & completeness score — NOT a calibrated default probability.",
        )
    with c3:
        st.metric("Eligibility Status", ctx["eligibility_status"])
    with c4:
        score_str = format_risk_score_display(ctx.get("risk_score"))
        st.metric(
            "Risk Assessment",
            ctx["risk_category"],
            delta=f"Score: {score_str}",
            delta_color="off",
        )
    with c5:
        fraud_disp = format_fraud_status_display(ctx.get("fraud_status"))
        anom_data = ctx.get("anomaly") or {}
        anom_cnt = len(anom_data.get("flags", []))
        st.metric(
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
        )
    with c6:
        miss_cnt = len(ctx.get("missing_documents") or [])
        st.metric(
            "Document Verification",
            ctx["document_verification_status"],
            delta=f"{miss_cnt} missing" if miss_cnt > 0 else "No missing required docs",
            delta_color="inverse" if miss_cnt > 0 else "normal",
        )

    st.caption(
        "Important: Confidence scores reflect deterministic evidence completeness and inter-agent agreement; "
        "risk tiers reflect synthetic model profiles rather than empirical default rates."
    )

    st.markdown("---")

    # Executive Reasoning, Manual Review Reasons, Consistency Conflicts & Factors
    st.markdown("### Decision Explanation & Safeguards")
    st.info(f"**Executive Summary:**\n\n{ctx['summary'] or 'No summary recorded.'}")

    if ctx.get("review_reasons"):
        with st.expander(
            f"Manual Review Triggers ({len(ctx['review_reasons'])})", expanded=True
        ):
            for msg in ctx["review_reasons"]:
                st.warning(msg)

    if ctx.get("validation_warnings"):
        with st.expander(
            f"Validation Warnings ({len(ctx['validation_warnings'])})", expanded=False
        ):
            for w in ctx["validation_warnings"]:
                st.write(f"- {w}")

    st.markdown("#### Cross-Agent Consistency Verification")
    render_conflicts_panel(ctx.get("consistency_conflicts") or [])

    if ctx.get("reasons"):
        with st.expander(
            f"Structured Decision Reasons ({len(ctx['reasons'])})", expanded=True
        ):
            for idx, r in enumerate(ctx["reasons"], 1):
                st.markdown(
                    f"**{idx}. `[{r.get('code')}]` ({r.get('category')} / `{r.get('severity')}`)** "
                    f"— *{r.get('source_agent')}*: {r.get('description')}"
                )
                if r.get("evidence"):
                    st.caption(
                        f"Evidence: {mask_extracted_value('evidence', r.get('evidence'))}"
                    )

    render_factor_cards(
        positive_factors=ctx.get("positive_factors") or [],
        negative_factors=ctx.get("negative_factors") or [],
        blocking_factors=ctx.get("blocking_factors") or [],
    )

    st.markdown("---")

    # Detailed Domain Tabs (Eligibility, Risk, Fraud, Documents, Agent Statuses)
    tab_elig, tab_risk, tab_fraud, tab_doc, tab_agents = st.tabs(
        [
            "Eligibility",
            "Risk Assessment",
            "Fraud Assessment",
            "Document Verification",
            "Agent Execution Statuses",
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
            c_p, c_f = st.columns(2)
            c_p.write(
                f"**Passed Rules ({len(elig.get('rules_passed', []))}):** {', '.join(elig.get('rules_passed', [])) or 'None'}"
            )
            c_f.write(
                f"**Failed Rules ({len(elig.get('rules_failed', []))}):** {', '.join(elig.get('rules_failed', [])) or 'None'}"
            )
            if elig.get("reasons"):
                st.markdown("**Eligibility Reasons:**")
                for er_msg in elig["reasons"]:
                    st.write(f"- {er_msg}")
            if elig.get("rule_results"):
                st.dataframe(
                    pd.DataFrame(elig["rule_results"]),
                    width="stretch",
                    hide_index=True,
                )
        else:
            st.error(
                "Eligibility assessment output is UNAVAILABLE for this run (agent failed or skipped)."
            )

    with tab_risk:
        risk = ctx.get("risk")
        if risk:
            model_avail = (
                "Available"
                if ctx.get("risk_score") is not None
                else "UNAVAILABLE (Invalid / Missing Score)"
            )
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Risk Category", risk["risk_category"])
            r2.metric("Risk Score", format_risk_score_display(ctx.get("risk_score")))
            r3.metric("Model Status", model_avail)
            r4.metric(
                "Methodology",
                f"{risk.get('method', 'N/A')} ({risk.get('model_version', 'N/A')})",
            )
            col_pf, col_rf = st.columns(2)
            with col_pf:
                st.markdown("**Protective Factors:**")
                for item in risk.get("protective_factors", []) or ["None"]:
                    st.write(f"- {item}")
            with col_rf:
                st.markdown("**Risk Factors:**")
                for item in risk.get("risk_factors", []) or ["None"]:
                    st.write(f"- {item}")
            if risk.get("feature_importance"):
                st.markdown("**Top Contributing Model Features:**")
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
                "Risk assessment is UNAVAILABLE for this run (RiskAgent failed or model failed to load). "
                "Unavailable risk scores are never displayed as zero and auto-approval is blocked."
            )

    with tab_fraud:
        anom = ctx.get("anomaly")
        if anom:
            a1, a2, a3 = st.columns(3)
            a1.metric(
                "Fraud / Anomaly Status",
                format_fraud_status_display(anom.get("severity")),
            )
            a2.metric(
                "Anomaly Score", f"{float(anom.get('anomaly_score', 0.0)):.1f} / 100"
            )
            a3.metric("Detected Flags", len(anom.get("flags", [])))
            st.caption(
                "Notice: An anomaly flag indicates a cross-document discrepancy requiring review; never confirmed fraud."
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
            st.error(
                "Fraud / anomaly detection is UNAVAILABLE (FraudAnomalyAgent failed). "
                "An unavailable fraud assessment is never treated as clean and auto-approval is blocked."
            )

    with tab_doc:
        doc_pkg = ctx.get("document_package")
        if doc_pkg:
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Status", doc_pkg.get("processing_status", "N/A"))
            d2.metric("Expected Docs", len(doc_pkg.get("expected_documents", [])))
            d3.metric("Submitted Docs", len(doc_pkg.get("documents_found", [])))
            d4.metric("Missing Docs", len(doc_pkg.get("documents_missing", [])))
            st.write(
                f"**Expected Categories:** {', '.join(doc_pkg.get('expected_documents', [])) or 'None'}"
            )
            st.write(
                f"**Submitted Categories:** {', '.join(d.get('document_type', 'unknown') for d in doc_pkg.get('documents_found', [])) or 'None'}"
            )
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
                st.error(
                    f"**Intra-Package Field Conflicts:** {doc_pkg['field_conflicts']}"
                )
            if st.button(
                "Open Full Document Review Page →", key="results_open_doc_review"
            ):
                navigate_to(
                    "Document Review", applicant_id=chosen_id, run_id=ctx.get("run_id")
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
            st.info("No agent execution telemetry recorded.")


def render_document_review_view() -> None:
    """Render Stage 5 Document Review page with privacy masking and heuristic notices."""
    st.subheader("Document Review & Extraction Evidence")
    st.caption(
        "Inspect per-document classification, OCR status, page metrics, extraction validation, and masked fields. "
        "Note: Extraction & classification confidence values are deterministic heuristics, not calibrated probabilities."
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
            key="doc_review_app_selector",
        )
        st.session_state[STATE_SELECTED_APP_ID] = chosen_id

    ctx = _normalize_view_context(chosen_id, selected_run_id)
    doc_pkg = ctx.get("document_package") if ctx else None

    # Fallback to pre-submission upload preview cache if user navigated from New Application before submitting
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
            "Upload documents in **New Application** or run the underwriting pipeline from **Underwriting Results**."
        )
        return

    # Package-Level Summary Metrics
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Intake Status", doc_pkg.get("processing_status", "N/A"))
    m2.metric("Processed Docs", len(doc_pkg.get("documents_found", [])))
    m3.metric("Missing Required", len(doc_pkg.get("documents_missing", [])))
    m4.metric("Unclassified Docs", len(doc_pkg.get("unclassified_documents", [])))
    m5.metric("OCR Triggered", "Yes" if doc_pkg.get("ocr_used") else "No")

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

    st.markdown("### Per-Document Telemetry & Extracted Fields (Masked)")
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

        with st.expander(
            f"{fname} — Category: `{dtype}` | Status: `{doc.get('classification_status', 'N/A')}` "
            f"| Pages: {doc.get('page_count', 1)} ({ocr_status})",
            expanded=True,
        ):
            dc1, dc2, dc3, dc4 = st.columns(4)
            dc1.metric("Detected Category", dtype)
            dc2.metric(
                "Classification Confidence",
                f"{clf_conf:.1f}%",
                help="Heuristic rule/keyword match score — not a calibrated probability.",
            )
            dc3.metric("Extraction Method", doc.get("extraction_method", "digital"))
            dc4.metric(
                "Pages (Native / OCR / Empty / Fail)",
                f"{doc.get('page_count', 1)} ({doc.get('native_text_pages', 0)}/"
                f"{doc.get('ocr_pages', 0)}/{doc.get('empty_pages', 0)}/{doc.get('failed_pages', 0)})",
            )

            doc_miss = missing_fields_map.get(fname, [])
            doc_inv = invalid_fields_map.get(fname, [])
            doc_amb = ambiguous_fields_map.get(fname, [])
            if doc_miss:
                st.warning(f"**Missing Expected Fields:** {', '.join(doc_miss)}")
            if doc_inv:
                st.error(f"**Invalid Fields:** {doc_inv}")
            if doc_amb:
                st.warning(f"**Ambiguous Fields:** {doc_amb}")

            ext_map = doc.get("extracted_fields", {})
            if ext_map:
                rows = []
                for field_key, fdata in ext_map.items():
                    rows.append(
                        {
                            "Field Name": fdata.get("field_name", field_key),
                            "Extracted Value (Masked)": str(fdata.get("value", "N/A")),
                            "Validation Status": fdata.get(
                                "validation_status", "valid"
                            ),
                            "Confidence (Heuristic)": f"{float(fdata.get('confidence', 0.0)) * 100:.1f}%",
                            "Source Page": fdata.get("page_number", 1),
                            "Extraction Method": fdata.get("extraction_method", "N/A"),
                            "Evidence (Masked)": str(fdata.get("evidence", "")),
                        }
                    )
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            else:
                st.caption("No structured fields extracted from this document.")
