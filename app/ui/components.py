"""Reusable UI Styling, Banners, Badges, and Safe Formatters for Stage 5."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import streamlit as st

from app.schemas.applicant import EligibilityResult


def apply_fintech_styles() -> None:
    """Inject crisp fintech typography, card boundaries, and high-contrast status pills."""
    st.markdown(
        """
        <style>
        .main-header {
            font-size: 1.95rem;
            font-weight: 700;
            color: #102a43;
            margin-bottom: 0.15rem;
            letter-spacing: -0.02em;
        }
        .sub-header {
            font-size: 0.98rem;
            color: #486581;
            margin-bottom: 1.1rem;
        }
        .recommendation-approve {
            background-color: #e6f4ea;
            border: 2px solid #1e8e3e;
            color: #0d652d;
            border-radius: 8px;
            padding: 10px;
            text-align: center;
            font-size: 1.25rem;
            font-weight: 700;
        }
        .recommendation-reject {
            background-color: #fce8e6;
            border: 2px solid #d93025;
            color: #a50e0e;
            border-radius: 8px;
            padding: 10px;
            text-align: center;
            font-size: 1.25rem;
            font-weight: 700;
        }
        .recommendation-manual {
            background-color: #fef7e0;
            border: 2px solid #f29900;
            color: #b06000;
            border-radius: 8px;
            padding: 10px;
            text-align: center;
            font-size: 1.25rem;
            font-weight: 700;
        }
        .factor-box-positive {
            background-color: #f1f8e9;
            border-left: 4px solid #2e7d32;
            color: #1b5e20;
            padding: 9px 12px;
            border-radius: 4px;
            margin-bottom: 8px;
            font-size: 0.9rem;
        }
        .factor-box-negative {
            background-color: #fffde7;
            border-left: 4px solid #f9a825;
            color: #5d4037;
            padding: 9px 12px;
            border-radius: 4px;
            margin-bottom: 8px;
            font-size: 0.9rem;
        }
        .factor-box-blocking {
            background-color: #ffebee;
            border-left: 4px solid #c62828;
            color: #b71c1c;
            padding: 9px 12px;
            border-radius: 4px;
            margin-bottom: 8px;
            font-size: 0.9rem;
        }
        .hitl-banner {
            background-color: #ebf4ff;
            border: 1px solid #90cdf4;
            color: #1a365d;
            border-radius: 6px;
            padding: 10px 14px;
            margin-bottom: 14px;
            font-size: 0.9rem;
        }
        .disclaimer-banner {
            background-color: #f7fafc;
            border: 1px dashed #cbd5e0;
            color: #4a5568;
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 0.82rem;
            margin-top: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def format_inr(val: Optional[float]) -> str:
    """Format numeric value in INR notation, preserving valid zero (0.0)."""
    if val is None:
        return "N/A"
    return f"₹{float(val):,.2f}"


def format_eligibility_metrics_summary(elig_res: EligibilityResult) -> str:
    """Format max eligible loan amount and DTI summary line for display."""
    dti_str = (
        f"`{elig_res.dti_ratio:.1f}%`" if elig_res.dti_ratio is not None else "`N/A`"
    )
    return (
        f"**Max Permitted Loan:** {format_inr(elig_res.max_eligible_amount)} | "
        f"**Calculated DTI:** {dti_str}"
    )


def render_hitl_banner() -> None:
    """Display mandatory human-in-the-loop governance banner."""
    st.markdown(
        """
        <div class="hitl-banner">
            <strong>HUMAN REVIEW REQUIRED:</strong> This system generates an AI-assisted underwriting
            recommendation for decision support. Final credit approval or rejection remains with an
            authorized human underwriter.
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_recommendation_badge(raw_outcome: Optional[str]) -> None:
    """Render mapped categorical recommendation badge cleanly without fabrication."""
    val = str(raw_outcome or "MANUAL_REVIEW").upper()
    if val == "APPROVE":
        st.markdown(
            '<div class="recommendation-approve">APPROVED (APPROVE)</div>',
            unsafe_allow_html=True,
        )
    elif val == "REJECT":
        st.markdown(
            '<div class="recommendation-reject">REJECTED (REJECT)</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="recommendation-manual">MANUAL REVIEW</div>',
            unsafe_allow_html=True,
        )
    st.caption("AI Recommendation")


def format_risk_score_display(risk_score: Optional[float]) -> str:
    """Never render an unavailable risk score as 0.0."""
    if risk_score is None:
        return "Unavailable"
    return f"{float(risk_score):.1f} / 100"


def format_fraud_status_display(fraud_status: Optional[str]) -> str:
    """Never equate an unavailable fraud assessment to NONE/clean."""
    if not fraud_status or str(fraud_status).upper() == "UNAVAILABLE":
        return "UNAVAILABLE (Inspection Required)"
    return str(fraud_status).upper()


def render_factor_cards(
    positive_factors: List[str],
    negative_factors: List[str],
    blocking_factors: List[str],
) -> None:
    """Render structured three-column factor breakdown cards."""
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("#### Positive Factors")
        if positive_factors:
            for item in positive_factors:
                st.markdown(
                    f'<div class="factor-box-positive">✓ {item}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No positive factors recorded.")
    with c2:
        st.markdown("#### Negative Factors")
        if negative_factors:
            for item in negative_factors:
                st.markdown(
                    f'<div class="factor-box-negative">! {item}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No negative factors recorded.")
    with c3:
        st.markdown("#### Blocking Safeguards")
        if blocking_factors:
            for item in blocking_factors:
                st.markdown(
                    f'<div class="factor-box-blocking">✕ {item}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No blocking conditions triggered.")


def render_conflicts_panel(conflicts: List[Dict[str, Any]]) -> None:
    """Render Stage 4 cross-agent consistency conflicts explicitly."""
    if not conflicts:
        st.success("No cross-agent consistency contradictions detected.")
        return
    st.error(f"{len(conflicts)} Cross-Agent Consistency Conflict(s) Detected:")
    for conflict in conflicts:
        cid = conflict.get("conflict_id", "CONFLICT")
        sev = conflict.get("severity", "BLOCKING")
        desc = conflict.get("description", "")
        sources = ", ".join(conflict.get("conflicting_sources", [])) or "N/A"
        auth = conflict.get("authoritative_source", "N/A")
        st.markdown(
            f"- **`{cid}` ({sev})**: {desc}  \n"
            f"  *Sources:* `{sources}` | *Authoritative:* `{auth}`"
        )


def render_human_vs_ai_summary_panel(case_summary: Dict[str, Any]) -> None:
    """Display AI recommendation, pipeline status, human review status, and human decision separately."""
    ai_rec = case_summary.get("ai_recommendation", "NOT_EVALUATED")
    pipe_st = case_summary.get("pipeline_status", "NOT_RUN")
    rev_st = case_summary.get("human_review_status", "PENDING")
    hum_dec = case_summary.get("human_decision")
    latest_rev = case_summary.get("latest_review")

    hum_dec_disp = hum_dec if hum_dec else "Not yet recorded"
    reviewer_note = (
        f"By {latest_rev['reviewer_id']} ({str(latest_rev.get('review_timestamp', ''))[:19].replace('T', ' ')} UTC)"
        if latest_rev
        else "Awaiting human reviewer action"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "1. AI Recommendation",
        ai_rec,
        delta="Advisory only (never final lending authority)",
        delta_color="off",
    )
    c2.metric("2. Pipeline Execution", pipe_st)
    c3.metric("3. Human Review Status", rev_st)
    c4.metric(
        "4. Final Human Decision",
        hum_dec_disp,
        delta=reviewer_note,
        delta_color="off",
    )
    if latest_rev and latest_rev.get("reviewer_user_id"):
        st.caption(
            f"Verified Reviewer Identity: `{latest_rev.get('reviewer_username') or latest_rev['reviewer_id']}` "
            f"(User ID: `{latest_rev['reviewer_user_id']}`, Role: `{latest_rev.get('reviewer_role') or 'N/A'}`)."
        )
    else:
        st.caption(
            "Unauthenticated prototype attribution displayed for local workflow traceability; "
            "sign in via sidebar or use the FastAPI `/api/v1` backend for verified JWT/RBAC attribution."
        )
