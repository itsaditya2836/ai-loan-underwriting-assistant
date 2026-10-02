"""Streamlit Underwriting Dashboard & Audit Trail Module (Stage 9).

Provides an executive decision-support interface for loan officers and auditors:
1. Application selection and profile preview.
2. End-to-end multi-agent pipeline execution (Stages 3-8).
3. Top-level summary cards (Recommendation, Confidence, Eligibility, Risk, Anomaly, Documents).
4. Explainable reasoning synthesis and structured decision reasons.
5. Factor breakdown (Positive, Negative, Blocking factors).
6. Multi-agent execution telemetry and latency tracking.
7. Deep-dive analytical tabs for Stages 3, 4, 5, and 6.
8. Immutable SQLite audit trail with multi-run history and filtering.
9. Population-level aggregate analytics and distribution charts.
10. Strict human-in-the-loop and academic/synthetic data governance notices.
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pandas as pd
import streamlit as st

from app.agents.decision_agent import DecisionReasoningAgent
from app.database.audit import (
    get_applicant_run_history,
    get_audit_analytics_summary,
    get_audit_run_by_id,
    get_audit_runs,
    init_audit_table,
    save_underwriting_run,
)
from app.orchestration.orchestrator import UnderwritingOrchestrator
from app.schemas.decision import DecisionReasoningResult
from app.schemas.underwriting import UnderwritingAnalysisResult

APPLICANTS_DATA_PATH = os.path.join("data", "synthetic_data", "applicants.json")
DOCUMENTS_BASE_DIR = os.path.join("data", "documents")


# ==============================================================================
# DATA LOADING & CACHING HELPERS
# ==============================================================================


@st.cache_data
def load_all_applicants_metadata() -> List[Dict[str, Any]]:
    """Load all applicant records from the synthetic dataset."""
    if not os.path.exists(APPLICANTS_DATA_PATH):
        return []
    with open(APPLICANTS_DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def get_applicant_by_id(app_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve applicant dictionary by ID."""
    applicants = load_all_applicants_metadata()
    for app in applicants:
        if app.get("applicant_id") == app_id:
            return app
    return None


def has_document_package(app_id: str) -> bool:
    """Check if physical document folder exists for the applicant."""
    folder = os.path.join(DOCUMENTS_BASE_DIR, app_id)
    return os.path.isdir(folder) and len(os.listdir(folder)) > 0


# ==============================================================================
# STYLING & COMPONENT HELPERS
# ==============================================================================


def apply_custom_styles() -> None:
    """Inject clean, professional typography and card styling."""
    st.markdown(
        """
        <style>
        .main-header {
            font-size: 2.1rem;
            font-weight: 700;
            color: #1a237e;
            margin-bottom: 0.2rem;
        }
        .sub-header {
            font-size: 1.05rem;
            color: #455a64;
            margin-bottom: 1.2rem;
        }
        .metric-card {
            background-color: #f8f9fa;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 14px;
            text-align: center;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }
        .recommendation-approve {
            background-color: #e8f5e9;
            border: 2px solid #2e7d32;
            color: #1b5e20;
            border-radius: 8px;
            padding: 12px;
            text-align: center;
            font-size: 1.6rem;
            font-weight: 700;
        }
        .recommendation-reject {
            background-color: #ffebee;
            border: 2px solid #c62828;
            color: #b71c1c;
            border-radius: 8px;
            padding: 12px;
            text-align: center;
            font-size: 1.6rem;
            font-weight: 700;
        }
        .recommendation-manual {
            background-color: #fff8e1;
            border: 2px solid #f57f17;
            color: #e65100;
            border-radius: 8px;
            padding: 12px;
            text-align: center;
            font-size: 1.6rem;
            font-weight: 700;
        }
        .factor-box-positive {
            background-color: #f1f8e9;
            border-left: 4px solid #43a047;
            padding: 10px 14px;
            border-radius: 4px;
            margin-bottom: 8px;
            font-size: 0.92rem;
        }
        .factor-box-negative {
            background-color: #fffde7;
            border-left: 4px solid #fbc02d;
            padding: 10px 14px;
            border-radius: 4px;
            margin-bottom: 8px;
            font-size: 0.92rem;
        }
        .factor-box-blocking {
            background-color: #ffebee;
            border-left: 4px solid #e53935;
            padding: 10px 14px;
            border-radius: 4px;
            margin-bottom: 8px;
            font-size: 0.92rem;
        }
        .hitl-banner {
            background-color: #e3f2fd;
            border: 1px solid #90caf9;
            color: #0d47a1;
            border-radius: 6px;
            padding: 10px 14px;
            margin-bottom: 14px;
            font-size: 0.9rem;
        }
        .disclaimer-banner {
            background-color: #fafafa;
            border: 1px dashed #bdbdbd;
            color: #616161;
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 0.82rem;
            margin-top: 10px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def format_inr(val: Optional[float]) -> str:
    """Format float values in Indian Rupee notation."""
    if val is None:
        return "N/A"
    return f"₹{val:,.2f}"


# ==============================================================================
# PIPELINE EXECUTION WRAPPER
# ==============================================================================


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

    # Persist immutable audit record
    run_id = save_underwriting_run(
        analysis=analysis,
        decision=decision,
        execution_time_ms=round(duration_ms, 2),
    )

    return analysis, decision, run_id, duration_ms


# ==============================================================================
# VIEW 1: MAIN UNDERWRITING SCREEN
# ==============================================================================


def render_underwriting_view(
    selected_app_id: str, applicant_data: Optional[Dict[str, Any]]
) -> None:
    """Render the primary underwriting analysis and decision support screen."""
    st.subheader(f"Underwriting Evaluation: {selected_app_id}")

    # Top Execution & Summary Bar
    col_exec, col_meta = st.columns([1, 2])

    with col_exec:
        run_btn = st.button(
            "▶ Run Underwriting Analysis", type="primary", use_container_width=True
        )

    with col_meta:
        if applicant_data:
            has_docs = has_document_package(selected_app_id)
            doc_badge = (
                "📁 Documents Verified" if has_docs else "⚠️ Data Only (No PDF Package)"
            )
            st.markdown(
                f"**Applicant:** {applicant_data.get('name', 'N/A')} | "
                f"**Loan:** {format_inr(applicant_data.get('loan_amount'))} ({applicant_data.get('loan_tenure', 'N/A')} mo) | "
                f"**Status:** `{doc_badge}`"
            )

    # Check session state or trigger execution
    cache_key = f"latest_run_{selected_app_id}"

    if run_btn:
        with st.spinner(
            "Executing Multi-Agent Pipeline (Intake → Eligibility → Risk → Anomaly → Decision)..."
        ):
            try:
                analysis, decision, run_id, duration_ms = execute_underwriting_pipeline(
                    selected_app_id
                )
                st.session_state[cache_key] = {
                    "analysis": analysis,
                    "decision": decision,
                    "run_id": run_id,
                    "duration_ms": duration_ms,
                }
                st.success(
                    f"Underwriting analysis completed in {duration_ms:.1f} ms. Recorded Run ID: `{run_id}`"
                )
            except Exception as exc:
                st.error(
                    f"Underwriting analysis failed: {str(exc)}. Please review the application manually."
                )
                return

    # Check if we have active results to display
    current_result = st.session_state.get(cache_key)

    if not current_result:
        # Check if an existing historical run exists in the audit database
        existing_runs = get_applicant_run_history(selected_app_id)
        if existing_runs:
            st.info(
                f"Loaded most recent historical run `{existing_runs[0]['run_id']}` from audit database. Click 'Run Underwriting Analysis' to perform a new run."
            )
            render_audit_run_inspection(existing_runs[0])
            return
        else:
            st.info(
                "Click '▶ Run Underwriting Analysis' to evaluate this application across all agents."
            )
            return

    analysis: UnderwritingAnalysisResult = current_result["analysis"]
    decision: DecisionReasoningResult = current_result["decision"]
    run_id: str = current_result["run_id"]
    duration_ms: float = current_result["duration_ms"]

    # --- Governance & HITL Banners ---
    st.markdown(
        """
        <div class="hitl-banner">
            <strong>⚠️ HUMAN REVIEW REQUIRED:</strong> This system provides an AI-generated underwriting recommendation for decision support.
            Final credit authorization and legal lending commitments remain with an authorized human loan officer.
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- Top-Level Summary Cards ---
    st.markdown("### Executive Summary Cards")
    c1, c2, c3, c4, c5, c6 = st.columns(6)

    # Recommendation
    with c1:
        rec_val = decision.recommendation.value
        if rec_val == "APPROVE":
            st.markdown(
                '<div class="recommendation-approve">APPROVE</div>',
                unsafe_allow_html=True,
            )
        elif rec_val == "REJECT":
            st.markdown(
                '<div class="recommendation-reject">REJECT</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="recommendation-manual">MANUAL REVIEW</div>',
                unsafe_allow_html=True,
            )
        st.caption("AI Recommendation")

    # Confidence
    with c2:
        st.metric(
            label="Decision Confidence",
            value=f"{decision.confidence:.1f}%",
            help="Measures completeness and agreement of available analytical evidence. It is not a probability of repayment, default, or fraud.",
        )

    # Eligibility
    with c3:
        elig_val = (
            analysis.eligibility_result.status.value
            if analysis.eligibility_result
            else "UNKNOWN"
        )
        st.metric(label="Stage 4 Eligibility", value=elig_val)

    # Risk
    with c4:
        risk_val = (
            analysis.risk_result.risk_category.value
            if analysis.risk_result
            else "UNKNOWN"
        )
        risk_score = analysis.risk_result.risk_score if analysis.risk_result else 0.0
        st.metric(
            label="Stage 5 Risk Tier",
            value=risk_val,
            delta=f"Score: {risk_score:.1f}/100",
            delta_color="off",
        )

    # Anomaly
    with c5:
        anom_sev = (
            analysis.anomaly_result.severity.value
            if analysis.anomaly_result
            else "NONE"
        )
        anom_count = (
            len(analysis.anomaly_result.flags) if analysis.anomaly_result else 0
        )
        st.metric(
            label="Stage 6 Anomaly",
            value=anom_sev,
            delta=f"{anom_count} flags",
            delta_color="inverse" if anom_count > 0 else "off",
        )

    # Documents
    with c6:
        docs_found = (
            len(analysis.document_result.documents_found)
            if analysis.document_result
            else 0
        )
        docs_miss = (
            len(analysis.document_result.documents_missing)
            if analysis.document_result
            else 0
        )
        st.metric(
            label="Stage 3 Evidence",
            value=f"{docs_found} verified",
            delta=f"{docs_miss} missing" if docs_miss > 0 else "Complete",
            delta_color="inverse" if docs_miss > 0 else "normal",
        )

    st.markdown("---")

    # --- Decision Explanation Section ---
    st.markdown("### Why was this recommendation generated?")
    st.info(f"**Executive Narrative:**\n\n{decision.summary}")

    # Structured Reasons
    with st.expander(
        f"Inspect Structured Decision Reasons ({len(decision.reasons)} reasons generated)",
        expanded=True,
    ):
        for idx, reason in enumerate(decision.reasons, 1):
            severity_badge = f"`{reason.severity}`"
            st.markdown(
                f"**{idx}. [{reason.code}] ({reason.category} / {severity_badge})** — *{reason.source_agent}*\n\n"
                f"{reason.description}"
            )
            if reason.evidence:
                st.caption(f"Evidence Citation: {reason.evidence}")
            st.divider()

    # --- Factor Breakdown (3 Visual Cards) ---
    st.markdown("### Analytical Factor Breakdown")
    f_col1, f_col2, f_col3 = st.columns(3)

    with f_col1:
        st.markdown("#### 🟢 Positive Factors")
        if decision.positive_factors:
            for pf in decision.positive_factors:
                st.markdown(
                    f'<div class="factor-box-positive">✓ {pf}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No significant positive factors identified.")

    with f_col2:
        st.markdown("#### 🟡 Negative Factors")
        if decision.negative_factors:
            for nf in decision.negative_factors:
                st.markdown(
                    f'<div class="factor-box-negative">⚠ {nf}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No negative factors detected.")

    with f_col3:
        st.markdown("#### 🔴 Blocking Factors")
        if decision.blocking_factors:
            for bf in decision.blocking_factors:
                st.markdown(
                    f'<div class="factor-box-blocking">⛔ {bf}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption(
                "No blocking conditions (eligible for automated recommendation)."
            )

    st.markdown("---")

    # --- Multi-Agent Execution Telemetry ---
    with st.expander("⏱ Multi-Agent Pipeline Telemetry & Status", expanded=False):
        t1, t2, t3 = st.columns(3)
        t1.metric("Pipeline Lifecycle Status", analysis.orchestration_status.value)
        t2.metric("Total Execution Wall Time", f"{duration_ms:.1f} ms")
        t3.metric("Immutable Audit Run ID", run_id)

        # Agent execution table
        st.markdown("**Per-Agent Telemetry Breakdown:**")
        agent_records = []
        for name, status in analysis.agent_statuses.items():
            dur_str = (
                f"{status.duration_ms:.2f} ms"
                if status.duration_ms is not None
                else "N/A"
            )
            agent_records.append(
                {
                    "Agent Name": name,
                    "Status": status.status.value,
                    "Execution Time": dur_str,
                    "Error": status.error or "None",
                }
            )
        st.dataframe(
            pd.DataFrame(agent_records), use_container_width=True, hide_index=True
        )

    # --- Deep-Dive Analytical Tabs ---
    st.markdown("### Deep-Dive Analytical Agent Evidence")
    tab_doc, tab_elig, tab_risk, tab_anom = st.tabs(
        [
            "📄 Document Intelligence (Stage 3)",
            "⚖️ Underwriting Eligibility (Stage 4)",
            "📊 Risk Assessment (Stage 5)",
            "🔍 Fraud & Anomaly Detection (Stage 6)",
        ]
    )

    # Tab 1: Document Intelligence
    with tab_doc:
        doc_res = analysis.document_result
        if doc_res:
            st.markdown(
                f"**Document Package Location:** `{doc_res.package_dir}` | **OCR Used:** `{doc_res.ocr_used}`"
            )
            if doc_res.documents_missing:
                st.warning(
                    f"**Missing Required Documents:** {', '.join(doc_res.documents_missing)}\n\n"
                    "*Notice: Missing document evidence does not indicate fraud; it requires follow-up verification.*"
                )

            st.markdown("**Ingested Physical Documents:**")
            doc_rows = []
            for d in doc_res.documents_found:
                doc_rows.append(
                    {
                        "Document ID": d.document_id,
                        "Type": d.document_type,
                        "Pages": d.page_count,
                        "Scanned / OCR": "Yes" if d.is_scanned else "No",
                        "Confidence": f"{d.classification_confidence * 100:.1f}%",
                        "Classification Evidence": d.classification_evidence,
                    }
                )
            st.dataframe(
                pd.DataFrame(doc_rows), use_container_width=True, hide_index=True
            )

            if doc_res.all_extracted_fields:
                st.markdown("**Structured Extracted Key-Value Fields:**")
                field_rows = []
                for fname, fval in doc_res.all_extracted_fields.items():
                    field_rows.append(
                        {
                            "Field": fname,
                            "Extracted Value": str(fval.value),
                            "Source Document": fval.source_document,
                            "Page": fval.page_number,
                            "Confidence": f"{fval.confidence * 100:.1f}%",
                            "Evidence Citation": fval.evidence,
                        }
                    )
                st.dataframe(
                    pd.DataFrame(field_rows), use_container_width=True, hide_index=True
                )
        else:
            st.info("No document intelligence outputs available.")

    # Tab 2: Eligibility
    with tab_elig:
        elig_res = analysis.eligibility_result
        if elig_res:
            st.markdown(
                f"**Eligibility Status:** `{elig_res.status.value}` | **Policy:** `{elig_res.policy_version}`"
            )
            st.markdown(
                f"**Max Permitted Loan:** {format_inr(elig_res.max_eligible_amount)} | **Calculated DTI:** `{elig_res.dti_ratio:.1f}%`"
                if elig_res.dti_ratio
                else ""
            )

            st.markdown("**Deterministic Underwriting Policy Rules Breakdown:**")
            rule_rows = []
            for r in elig_res.rule_results:
                rule_rows.append(
                    {
                        "Rule ID": r.rule_id,
                        "Rule Description": r.rule_name,
                        "Status": r.status.value,
                        "Observed Value": str(r.actual_value),
                        "Threshold / Expected": str(r.expected_value),
                        "Reason / Explanation": r.reason,
                    }
                )
            st.dataframe(
                pd.DataFrame(rule_rows), use_container_width=True, hide_index=True
            )
        else:
            st.info("No eligibility results available.")

    # Tab 3: Risk Assessment
    with tab_risk:
        risk_res = analysis.risk_result
        if risk_res:
            r1, r2, r3 = st.columns(3)
            r1.metric("Risk Category Tier", risk_res.risk_category.value)
            r2.metric("Normalized Risk Score", f"{risk_res.risk_score:.1f} / 100")
            r3.metric("Assessment Methodology", risk_res.method)

            st.caption(
                "Notice: Risk tier represents synthetic profile classification; it is not an empirical probability of loan default."
            )

            col_p, col_r = st.columns(2)
            with col_p:
                st.markdown("**Protective Factors:**")
                if risk_res.protective_factors:
                    for pf in risk_res.protective_factors:
                        st.write(f"- {pf}")
                else:
                    st.caption("None reported.")

            with col_r:
                st.markdown("**Identified Risk Factors:**")
                if risk_res.risk_factors:
                    for rf in risk_res.risk_factors:
                        st.write(f"- {rf}")
                else:
                    st.caption("None reported.")

            if risk_res.feature_importance:
                st.markdown("**Model Feature Importances:**")
                feat_df = pd.DataFrame(
                    [
                        {"Feature": k, "Importance Weight": round(v, 4)}
                        for k, v in risk_res.feature_importance.items()
                    ]
                ).sort_values(by="Importance Weight", ascending=False)
                st.bar_chart(feat_df.set_index("Feature"))
        else:
            st.info("No risk assessment results available.")

    # Tab 4: Anomaly Detection
    with tab_anom:
        anom_res = analysis.anomaly_result
        if anom_res:
            a1, a2, a3 = st.columns(3)
            a1.metric("Anomaly Severity", anom_res.severity.value)
            a2.metric("Composite Anomaly Score", f"{anom_res.anomaly_score:.1f} / 100")
            a3.metric("Total Inconsistency Flags", len(anom_res.flags))

            st.caption(
                "Notice: An anomaly indicates a cross-document inconsistency requiring human verification; it is not confirmed fraud."
            )

            if anom_res.flags:
                st.markdown("**Granular Inconsistency Flags:**")
                anom_rows = []
                for f in anom_res.flags:
                    anom_rows.append(
                        {
                            "Rule ID": f.rule_id,
                            "Anomaly Type": f.anomaly_type,
                            "Severity": f.severity.value,
                            "Declared / Expected": str(f.expected_value),
                            "Observed in Docs": str(f.observed_value),
                            "Description": f.description,
                            "Evidence Citation": f.evidence,
                        }
                    )
                st.dataframe(
                    pd.DataFrame(anom_rows), use_container_width=True, hide_index=True
                )
            else:
                st.success(
                    "No cross-document discrepancies or suspicious anomalies detected."
                )
        else:
            st.info("No anomaly detection results available.")


# ==============================================================================
# VIEW 2: APPLICATION DETAILS
# ==============================================================================


def render_application_details_view(
    selected_app_id: str, applicant_data: Optional[Dict[str, Any]]
) -> None:
    """Render full applicant personal, financial, and loan request details."""
    st.subheader(f"Application Dossier: {selected_app_id}")

    if not applicant_data:
        st.warning(
            f"Applicant profile '{selected_app_id}' could not be located in dataset."
        )
        return

    # Personal Information
    st.markdown("#### 👤 Personal & Employment Profile")
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Applicant Name", applicant_data.get("name", "N/A"))
    p2.metric("Age", f"{applicant_data.get('age', 'N/A')} years")
    p3.metric("Gender", applicant_data.get("gender", "N/A"))
    p4.metric("City / Location", applicant_data.get("city", "N/A"))

    p5, p6, p7, p8 = st.columns(4)
    p5.metric("Employment Type", applicant_data.get("employment_type", "N/A"))
    p6.metric("Employer Name", applicant_data.get("employer_name", "N/A"))
    p7.metric(
        "Employment Tenure", f"{applicant_data.get('employment_years', 'N/A')} yrs"
    )
    p8.metric("Dependents", applicant_data.get("number_of_dependents", 0))

    st.markdown("---")

    # Financial Information
    st.markdown("#### 💰 Financial Ledger & Loan Request")
    f1, f2, f3 = st.columns(3)
    f1.metric(
        "Declared Monthly Income", format_inr(applicant_data.get("monthly_income"))
    )
    f2.metric("Existing Monthly EMI", format_inr(applicant_data.get("existing_emi")))
    f3.metric("Declared Bank Balance", format_inr(applicant_data.get("bank_balance")))

    f4, f5, f6 = st.columns(3)
    f4.metric("Requested Loan Amount", format_inr(applicant_data.get("loan_amount")))
    f5.metric("Loan Tenure", f"{applicant_data.get('loan_tenure', 'N/A')} months")
    f6.metric("Credit Bureau Score", applicant_data.get("credit_score", "N/A"))

    f7, f8, f9 = st.columns(3)
    f7.metric(
        "Declared Monthly Expenses", format_inr(applicant_data.get("monthly_expenses"))
    )
    f8.metric(
        "Total Monthly Obligations",
        format_inr(applicant_data.get("total_monthly_obligations")),
    )
    f9.metric("Debt-to-Income (DTI)", f"{applicant_data.get('dti_ratio', 'N/A')}%")

    st.markdown("---")

    # Application Underwriting History
    st.markdown("#### 📜 Application Underwriting History")
    history_runs = get_applicant_run_history(selected_app_id)

    if not history_runs:
        st.info(
            "No underwriting evaluations recorded yet for this applicant. Run the pipeline in the 'Underwriting' tab."
        )
    else:
        st.write(
            f"Total Recorded Historical Evaluations: **{len(history_runs)}** (Immutable Multi-Run History)"
        )
        hist_rows = []
        for idx, r in enumerate(history_runs, 1):
            hist_rows.append(
                {
                    "Run Number": f"Run {idx}",
                    "Run ID": r["run_id"],
                    "Timestamp (UTC)": r["timestamp"][:19].replace("T", " "),
                    "Recommendation": r["recommendation"],
                    "Confidence": f"{r['decision_confidence']:.1f}%",
                    "Eligibility": r["eligibility_status"],
                    "Risk Tier": r["risk_category"],
                    "Anomaly Severity": r["anomaly_severity"],
                    "Execution Time": f"{r['execution_time_ms']:.1f} ms",
                }
            )
        st.dataframe(pd.DataFrame(hist_rows), use_container_width=True, hide_index=True)


# ==============================================================================
# VIEW 3: AUDIT TRAIL & RUN INSPECTION
# ==============================================================================


def render_audit_trail_view() -> None:
    """Render the centralized, immutable SQLite audit trail screen with filters."""
    st.subheader("📜 Underwriting Audit Trail & Historical Ledger")
    st.caption(
        "Immutable compliance ledger recording all pipeline executions, evidence snapshots, and decision reasons."
    )

    # Filter Controls Bar
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)

    with f_col1:
        f_rec = st.selectbox(
            "Filter Recommendation", ["ALL", "APPROVE", "REJECT", "MANUAL_REVIEW"]
        )
    with f_col2:
        f_status = st.selectbox(
            "Filter Pipeline Status", ["ALL", "SUCCESS", "PARTIAL_SUCCESS", "FAILED"]
        )
    with f_col3:
        f_risk = st.selectbox(
            "Filter Risk Category", ["ALL", "LOW", "MEDIUM", "HIGH", "BORDERLINE"]
        )
    with f_col4:
        f_anom = st.selectbox(
            "Filter Anomaly Severity", ["ALL", "NONE", "LOW", "MEDIUM", "HIGH"]
        )

    # Query filtered runs
    runs = get_audit_runs(
        recommendation=None if f_rec == "ALL" else f_rec,
        pipeline_status=None if f_status == "ALL" else f_status,
        risk_category=None if f_risk == "ALL" else f_risk,
        anomaly_severity=None if f_anom == "ALL" else f_anom,
        limit=250,
    )

    if not runs:
        st.info("No audit records found matching the specified filters.")
        return

    st.write(f"Displaying **{len(runs)}** matching audit runs:")

    table_data = []
    for r in runs:
        table_data.append(
            {
                "Run ID": r["run_id"],
                "Application": r["application_id"],
                "Timestamp": r["timestamp"][:19].replace("T", " "),
                "Recommendation": r["recommendation"],
                "Confidence": f"{r['decision_confidence']:.1f}%",
                "Eligibility": r["eligibility_status"],
                "Risk Tier": r["risk_category"],
                "Anomaly": r["anomaly_severity"],
                "Pipeline Status": r["pipeline_status"],
                "Latency": f"{r['execution_time_ms']:.1f} ms",
            }
        )

    st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)

    # Detailed Run Inspector
    st.markdown("---")
    st.markdown("#### 🔍 Historical Run Snapshot Inspector")

    run_ids = [r["run_id"] for r in runs]
    selected_inspect_id = st.selectbox("Select Run ID to inspect details:", run_ids)

    selected_run = get_audit_run_by_id(selected_inspect_id)
    if selected_run:
        render_audit_run_inspection(selected_run)


def render_audit_run_inspection(run: Dict[str, Any]) -> None:
    """Render a comprehensive read-only snapshot of an audited underwriting run."""
    st.markdown(f"**Inspection Snapshot for Run:** `{run['run_id']}`")

    # Header Metrics
    h1, h2, h3, h4, h5 = st.columns(5)
    h1.metric("Application", run["application_id"])
    h2.metric("Recommendation", run["recommendation"])
    h3.metric("Confidence", f"{run['decision_confidence']:.1f}%")
    h4.metric("Pipeline Status", run["pipeline_status"])
    h5.metric("Latency", f"{run['execution_time_ms']:.1f} ms")

    st.markdown(f"**Executive Narrative:**\n\n{run.get('summary_narrative', 'N/A')}")

    # Factors
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**🟢 Positive Factors:**")
        for f in run.get("positive_factors", []):
            st.markdown(
                f'<div class="factor-box-positive">✓ {f}</div>', unsafe_allow_html=True
            )
    with c2:
        st.markdown("**🟡 Negative Factors:**")
        for f in run.get("negative_factors", []):
            st.markdown(
                f'<div class="factor-box-negative">⚠ {f}</div>', unsafe_allow_html=True
            )
    with c3:
        st.markdown("**🔴 Blocking Factors:**")
        for f in run.get("blocking_factors", []):
            st.markdown(
                f'<div class="factor-box-blocking">⛔ {f}</div>', unsafe_allow_html=True
            )

    # Reasons
    reasons = run.get("reasons", [])
    if reasons:
        with st.expander(f"Audited Decision Reasons ({len(reasons)})", expanded=False):
            for r in reasons:
                st.write(
                    f"- **[{r.get('code')}] ({r.get('category')} / `{r.get('severity')}`)**: {r.get('description')}"
                )
                if r.get("evidence"):
                    st.caption(f"Evidence: {r.get('evidence')}")


# ==============================================================================
# VIEW 4: AGGREGATE ANALYTICS & CHARTS
# ==============================================================================


def render_analytics_view() -> None:
    """Render population-level analytics, KPI metrics, and distribution charts."""
    st.subheader("📊 Aggregate Underwriting Portfolio Analytics")
    st.caption(
        "Distribution insights derived from historical audit runs and synthetic test evaluations."
    )

    # Check for seed option if database is empty
    summary = get_audit_analytics_summary()

    if summary["total_runs"] == 0:
        st.info("No underwriting runs have been recorded in the database yet.")
        if st.button("⚡ Preload Baseline Cohort Runs (APP0001–APP0030)"):
            with st.spinner(
                "Executing and persisting baseline evaluations for APP0001–APP0030..."
            ):
                for i in range(1, 31):
                    app_id = f"APP{i:04d}"
                    execute_underwriting_pipeline(app_id)
                st.success(
                    "Successfully preloaded 30 baseline audit runs! Reloading analytics..."
                )
                st.rerun()
        return

    # Top KPI Metrics Row
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Total Executions", summary["total_runs"])
    m2.metric("Unique Applications", summary["unique_applications"])
    m3.metric("Manual Review Rate", f"{summary['manual_review_rate']}%")
    m4.metric("Avg Confidence", f"{summary['avg_confidence']}%")
    m5.metric("Avg Latency", f"{summary['avg_latency_ms']} ms")

    approve_cnt = summary["recommendation_distribution"].get("APPROVE", 0)
    app_rate = (
        (approve_cnt / summary["total_runs"]) * 100.0
        if summary["total_runs"] > 0
        else 0.0
    )
    m6.metric("Approval Rate", f"{app_rate:.1f}%")

    st.markdown("---")

    # 4 Distribution Charts
    c_left, c_right = st.columns(2)

    with c_left:
        st.markdown("#### 1. Underwriting Recommendation Distribution")
        rec_data = summary["recommendation_distribution"]
        rec_df = pd.DataFrame(
            list(rec_data.items()), columns=["Recommendation", "Count"]
        )
        st.bar_chart(rec_df.set_index("Recommendation"))

        st.markdown("#### 3. Anomaly Severity Distribution")
        anom_data = summary["anomaly_distribution"]
        anom_df = pd.DataFrame(list(anom_data.items()), columns=["Severity", "Count"])
        st.bar_chart(anom_df.set_index("Severity"))

    with c_right:
        st.markdown("#### 2. Repayment Risk Tier Distribution")
        risk_data = summary["risk_distribution"]
        risk_df = pd.DataFrame(
            list(risk_data.items()), columns=["Risk Category", "Count"]
        )
        st.bar_chart(risk_df.set_index("Risk Category"))

        st.markdown("#### 4. Eligibility Policy Status Distribution")
        elig_data = summary["eligibility_distribution"]
        elig_df = pd.DataFrame(
            list(elig_data.items()), columns=["Eligibility Status", "Count"]
        )
        st.bar_chart(elig_df.set_index("Eligibility Status"))


# ==============================================================================
# MAIN APPLICATION CONTROLLER
# ==============================================================================


def render_dashboard() -> None:
    """Primary application entry point invoked by Streamlit."""
    st.set_page_config(
        page_title="AI Loan Underwriting Assistant",
        page_icon="🏦",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    init_audit_table()
    apply_custom_styles()

    # --- Header ---
    st.markdown(
        '<div class="main-header">🏦 AI Loan Underwriting Assistant</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="sub-header">A Multi-Agent Agentic AI System for Faster Loan Processing & Decision Support</div>',
        unsafe_allow_html=True,
    )

    # --- Sidebar Navigation & Application Selection ---
    with st.sidebar:
        st.markdown("### 🧭 Navigation")
        nav_selection = st.radio(
            "Select Interface View:",
            [
                "🚀 Underwriting Pipeline",
                "👤 Application Details",
                "📜 Audit Trail & History",
                "📊 Aggregate Analytics",
            ],
            index=0,
        )

        st.markdown("---")
        st.markdown("### 📋 Application Selection")

        applicants = load_all_applicants_metadata()
        app_options = []
        for a in applicants:
            aid = a["applicant_id"]
            name = a.get("name", "N/A")
            has_docs = has_document_package(aid)
            tag = "📁 Docs Ready" if has_docs else "⚠️ Data Only"
            app_options.append((aid, f"{aid} — {name} ({tag})"))

        selected_app_id = st.selectbox(
            "Target Loan Application:",
            options=[opt[0] for opt in app_options],
            format_func=lambda aid: next(
                opt[1] for opt in app_options if opt[0] == aid
            ),
            index=0,
        )

        # Quick Applicant Snapshot in Sidebar
        sel_applicant = get_applicant_by_id(selected_app_id)
        if sel_applicant:
            st.markdown("---")
            st.markdown("**Quick Applicant Snapshot:**")
            st.write(f"• **Income:** {format_inr(sel_applicant.get('monthly_income'))}")
            st.write(f"• **Loan Req:** {format_inr(sel_applicant.get('loan_amount'))}")
            st.write(f"• **Credit Score:** {sel_applicant.get('credit_score')}")
            st.write(f"• **City:** {sel_applicant.get('city')}")

        st.markdown("---")
        st.markdown(
            """
            <div class="disclaimer-banner">
                <strong>Academic / Synthetic Notice:</strong><br>
                This application uses synthetic applicant and document data for research and software testing.
                It is not connected to real banking systems.
            </div>
            """,
            unsafe_allow_html=True,
        )

    # --- View Routing ---
    if nav_selection == "🚀 Underwriting Pipeline":
        render_underwriting_view(selected_app_id, sel_applicant)
    elif nav_selection == "👤 Application Details":
        render_application_details_view(selected_app_id, sel_applicant)
    elif nav_selection == "📜 Audit Trail & History":
        render_audit_trail_view()
    elif nav_selection == "📊 Aggregate Analytics":
        render_analytics_view()


if __name__ == "__main__":
    render_dashboard()
