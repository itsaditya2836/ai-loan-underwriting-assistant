"""Reusable Banking UI Design System, Status Badges, and Safe Formatters."""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional, Sequence, Tuple

import streamlit as st

from app.schemas.applicant import EligibilityResult


def _esc(val: Any) -> str:
    """Safely HTML-escape any dynamic text rendered inside custom markup."""
    return html.escape("" if val is None else str(val), quote=True)


def apply_fintech_styles() -> None:
    """Inject restrained enterprise banking typography, borders, and semantic tokens."""
    st.markdown(
        """
        <style>
        .stApp {
            background-color: #F8FAFC;
            color: #0F172A;
        }
        [data-testid="stSidebar"] {
            background-color: #FFFFFF;
            border-right: 1px solid #E2E8F0;
        }
        .block-container {
            max-width: 1360px;
            padding-top: 1.5rem;
            padding-bottom: 2.5rem;
        }
        [data-testid="stMetric"] {
            background-color: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 6px;
            padding: 0.75rem 0.9rem;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.78rem;
            color: #475569;
            font-weight: 600;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.35rem;
            color: #0F172A;
            font-weight: 700;
        }
        /* Sidebar branding & separated account card */
        .banking-brand {
            padding-bottom: 0.75rem;
            margin-bottom: 0.75rem;
            border-bottom: 1px solid #E2E8F0;
        }
        .banking-brand-title {
            font-size: 1.05rem;
            font-weight: 700;
            color: #0F172A;
            letter-spacing: -0.01em;
            line-height: 1.25;
        }
        .banking-brand-sub {
            font-size: 0.75rem;
            color: #64748B;
            margin-top: 0.15rem;
        }
        .banking-sidebar-section {
            font-size: 0.7rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #64748B;
            margin: 0.35rem 0 0.4rem 0;
        }
        .banking-session-card {
            background-color: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 6px;
            padding: 0.65rem 0.75rem;
            margin-bottom: 0.5rem;
        }
        .banking-session-name {
            font-size: 0.88rem;
            font-weight: 600;
            color: #0F172A;
        }
        .banking-session-role {
            font-size: 0.76rem;
            color: #475569;
            margin-top: 0.15rem;
        }
        .banking-sidebar-note {
            font-size: 0.74rem;
            color: #64748B;
            line-height: 1.4;
            padding-top: 0.25rem;
        }
        /* Page Header */
        .banking-header {
            margin-bottom: 1rem;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid #E2E8F0;
        }
        .banking-eyebrow {
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            color: #1E3A8A;
            margin-bottom: 0.2rem;
        }
        .banking-title {
            font-size: 1.55rem;
            font-weight: 700;
            color: #0F172A;
            letter-spacing: -0.02em;
            line-height: 1.2;
            margin: 0;
        }
        .banking-subtitle {
            font-size: 0.9rem;
            color: #475569;
            margin-top: 0.25rem;
        }
        .banking-section-title {
            font-size: 1rem;
            font-weight: 600;
            color: #0F172A;
            margin: 0.2rem 0 0.15rem 0;
        }
        .banking-section-sub {
            font-size: 0.82rem;
            color: #64748B;
            margin-bottom: 0.65rem;
        }
        /* KPI Row */
        .banking-kpi-grid {
            display: grid;
            gap: 0.75rem;
            margin-bottom: 1rem;
        }
        .banking-kpi-card {
            background-color: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 6px;
            padding: 0.85rem 1rem;
        }
        .banking-kpi-label {
            font-size: 0.76rem;
            font-weight: 600;
            color: #64748B;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }
        .banking-kpi-value {
            font-size: 1.55rem;
            font-weight: 700;
            color: #0F172A;
            font-variant-numeric: tabular-nums;
            margin: 0.25rem 0 0.15rem 0;
            line-height: 1.15;
        }
        .banking-kpi-meta {
            font-size: 0.76rem;
            color: #475569;
        }
        /* Definition / Key-Value Grid */
        .banking-kv-grid {
            display: grid;
            gap: 0.75rem 1rem;
            background-color: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 6px;
            padding: 0.9rem 1rem;
            margin-bottom: 0.85rem;
        }
        .banking-kv-item {
            min-width: 0;
        }
        .banking-kv-label {
            font-size: 0.74rem;
            font-weight: 600;
            color: #64748B;
            margin-bottom: 0.18rem;
        }
        .banking-kv-val {
            font-size: 0.94rem;
            font-weight: 600;
            color: #0F172A;
            line-height: 1.3;
            word-break: break-word;
            font-variant-numeric: tabular-nums;
        }
        .banking-kv-sub {
            font-size: 0.74rem;
            color: #64748B;
            margin-top: 0.15rem;
        }
        /* Badges / Pills */
        .banking-pill {
            display: inline-block;
            padding: 0.16rem 0.55rem;
            border-radius: 4px;
            font-size: 0.74rem;
            font-weight: 600;
            line-height: 1.35;
            border: 1px solid transparent;
        }
        .pill-success {
            background-color: #ECFDF5;
            border-color: #A7F3D0;
            color: #065F46;
        }
        .pill-warning {
            background-color: #FFFBEB;
            border-color: #FDE68A;
            color: #92400E;
        }
        .pill-danger {
            background-color: #FEF2F2;
            border-color: #FECACA;
            color: #991B1B;
        }
        .pill-info {
            background-color: #EFF6FF;
            border-color: #BFDBFE;
            color: #1E40AF;
        }
        .pill-neutral {
            background-color: #F1F5F9;
            border-color: #CBD5E1;
            color: #334155;
        }
        /* Recommendation Card */
        .banking-rec-card {
            border-radius: 6px;
            padding: 0.8rem 0.9rem;
            border: 1px solid #CBD5E1;
            background-color: #FFFFFF;
        }
        .banking-rec-label {
            font-size: 0.72rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: #64748B;
            margin-bottom: 0.2rem;
        }
        .banking-rec-value {
            font-size: 1.15rem;
            font-weight: 700;
            line-height: 1.25;
        }
        .rec-approve {
            background-color: #ECFDF5;
            border-color: #A7F3D0;
            color: #065F46;
        }
        .rec-reject {
            background-color: #FEF2F2;
            border-color: #FECACA;
            color: #991B1B;
        }
        .rec-manual {
            background-color: #FFFBEB;
            border-color: #FDE68A;
            color: #92400E;
        }
        /* Notice & Advisory Banners */
        .banking-banner {
            border-radius: 6px;
            padding: 0.65rem 0.9rem;
            margin-bottom: 0.9rem;
            font-size: 0.85rem;
            line-height: 1.45;
            border: 1px solid #E2E8F0;
            background-color: #FFFFFF;
        }
        .banner-info {
            background-color: #EFF6FF;
            border-color: #BFDBFE;
            color: #1E3A8A;
        }
        .banner-warning {
            background-color: #FFFBEB;
            border-color: #FDE68A;
            color: #92400E;
        }
        .banner-danger {
            background-color: #FEF2F2;
            border-color: #FECACA;
            color: #991B1B;
        }
        /* Factor Rows */
        .banking-factor {
            background-color: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-left-width: 3px;
            border-radius: 4px;
            padding: 0.5rem 0.75rem;
            margin-bottom: 0.45rem;
            font-size: 0.84rem;
            color: #0F172A;
            line-height: 1.4;
        }
        .factor-positive {
            border-left-color: #15803D;
        }
        .factor-negative {
            border-left-color: #B45309;
        }
        .factor-blocking {
            border-left-color: #B91C1C;
            background-color: #FEF2F2;
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


def format_compact_status(raw: Optional[str]) -> str:
    """Format uppercase domain/review tokens into readable compact title labels."""
    val = str(raw or "").strip().upper()
    mapping = {
        "APPROVE": "Approve",
        "APPROVED": "Approved",
        "REJECT": "Reject",
        "REJECTED": "Rejected",
        "MANUAL_REVIEW": "Manual Review",
        "NOT_EVALUATED": "Not Evaluated",
        "AI_MANUAL_REVIEW": "AI Review",
        "AWAITING_HUMAN_DECISION": "Awaiting Decision",
        "PENDING": "Pending",
        "IN_REVIEW": "In Review",
        "ADDITIONAL_INFO_REQUESTED": "Info Requested",
        "INVESTIGATION_REQUIRED": "Investigation",
        "SUCCESS": "Completed",
        "PARTIAL_SUCCESS": "Partial",
        "FAILED": "Failed",
        "UNDERWRITTEN": "Underwritten",
        "INCOMPLETE": "Incomplete",
        "SYNTHETIC_CATALOG": "Catalog",
        "UNAVAILABLE": "Unavailable",
    }
    if val in mapping:
        return mapping[val]
    return val.replace("_", " ").title() if val else "—"


def status_variant_for(raw: Optional[str]) -> str:
    """Map an underwriting or review status string to a restrained semantic tone."""
    val = str(raw or "").strip().upper()
    if val in {"APPROVE", "APPROVED", "ELIGIBLE", "LOW", "NONE", "VALID", "SUCCESS"}:
        return "success"
    if val in {
        "REJECT",
        "REJECTED",
        "INELIGIBLE",
        "HIGH",
        "FAILED",
        "INVALID",
        "BLOCKING",
    }:
        return "danger"
    if val in {
        "MANUAL_REVIEW",
        "BORDERLINE",
        "MEDIUM",
        "PENDING",
        "ADDITIONAL_INFO_REQUESTED",
        "INVESTIGATION_REQUIRED",
        "PARTIAL_SUCCESS",
        "INCOMPLETE",
        "UNAVAILABLE",
        "REVIEW_REQUIRED",
    }:
        return "warning"
    if val in {"IN_REVIEW", "UNDERWRITTEN"}:
        return "info"
    return "neutral"


def render_status_pill(label: str, variant: Optional[str] = None) -> str:
    """Return safe HTML markup for a restrained status pill."""
    tone = variant or status_variant_for(label)
    return f'<span class="banking-pill pill-{_esc(tone)}">{_esc(label)}</span>'


def render_page_header(
    eyebrow: str,
    title: str,
    subtitle: str = "",
) -> None:
    """Render a consistent enterprise page header with category eyebrow and subtitle."""
    sub_html = (
        f'<div class="banking-subtitle">{_esc(subtitle)}</div>' if subtitle else ""
    )
    st.markdown(
        f"""
        <div class="banking-header">
            <div class="banking-eyebrow">{_esc(eyebrow)}</div>
            <div class="banking-title">{_esc(title)}</div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_heading(title: str, subtitle: str = "") -> None:
    """Render a clean section heading and optional muted descriptor."""
    sub_html = (
        f'<div class="banking-section-sub">{_esc(subtitle)}</div>' if subtitle else ""
    )
    st.markdown(
        f'<div class="banking-section-title">{_esc(title)}</div>{sub_html}',
        unsafe_allow_html=True,
    )


def render_kpi_row(items: Sequence[Dict[str, Any]]) -> None:
    """Render compact, tabular-numeral KPI cards in a balanced horizontal grid."""
    if not items:
        return
    cols = len(items)
    cards = []
    for item in items:
        meta = item.get("meta")
        meta_html = f'<div class="banking-kpi-meta">{_esc(meta)}</div>' if meta else ""
        cards.append(
            f'<div class="banking-kpi-card">'
            f'<div class="banking-kpi-label">{_esc(item.get("label", ""))}</div>'
            f'<div class="banking-kpi-value">{_esc(item.get("value", "—"))}</div>'
            f"{meta_html}"
            f"</div>"
        )
    st.markdown(
        f'<div class="banking-kpi-grid" style="grid-template-columns: repeat({cols}, minmax(0, 1fr));">'
        + "".join(cards)
        + "</div>",
        unsafe_allow_html=True,
    )


def render_kv_grid(
    items: Sequence[Tuple[str, str] | Tuple[str, str, str]],
    columns: int = 4,
) -> None:
    """Render a bordered definition grid without metric truncation."""
    if not items:
        return
    cells: List[str] = []
    for entry in items:
        label = entry[0]
        value = entry[1]
        sub = entry[2] if len(entry) > 2 else ""
        sub_html = f'<div class="banking-kv-sub">{_esc(sub)}</div>' if sub else ""
        cells.append(
            f'<div class="banking-kv-item">'
            f'<div class="banking-kv-label">{_esc(label)}</div>'
            f'<div class="banking-kv-val">{_esc(value)}</div>'
            f"{sub_html}"
            f"</div>"
        )
    st.markdown(
        f'<div class="banking-kv-grid" style="grid-template-columns: repeat({int(columns)}, minmax(0, 1fr));">'
        + "".join(cells)
        + "</div>",
        unsafe_allow_html=True,
    )


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
        <div class="banking-banner banner-info">
            <strong>Human Review Required:</strong> AI underwriting outputs provide advisory
            decision support only. Final credit approval or rejection remains with an authorized human underwriter.
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_recommendation_badge(raw_outcome: Optional[str]) -> None:
    """Render mapped categorical AI recommendation card cleanly without fabrication."""
    val = str(raw_outcome or "MANUAL_REVIEW").upper()
    if val == "APPROVE":
        cls = "rec-approve"
        text = "Approve"
    elif val == "REJECT":
        cls = "rec-reject"
        text = "Reject"
    else:
        cls = "rec-manual"
        text = "Manual Review"
    st.markdown(
        f"""
        <div class="banking-rec-card {_esc(cls)}">
            <div class="banking-rec-label">AI Recommendation</div>
            <div class="banking-rec-value">{_esc(text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


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
        st.markdown("**Positive Factors**")
        if positive_factors:
            for item in positive_factors:
                st.markdown(
                    f'<div class="banking-factor factor-positive">{_esc(item)}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No positive factors recorded.")
    with c2:
        st.markdown("**Negative Factors**")
        if negative_factors:
            for item in negative_factors:
                st.markdown(
                    f'<div class="banking-factor factor-negative">{_esc(item)}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No negative factors recorded.")
    with c3:
        st.markdown("**Blocking Safeguards**")
        if blocking_factors:
            for item in blocking_factors:
                st.markdown(
                    f'<div class="banking-factor factor-blocking">{_esc(item)}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.caption("No blocking conditions triggered.")


def render_conflicts_panel(conflicts: List[Dict[str, Any]]) -> None:
    """Render cross-agent consistency conflicts explicitly."""
    if not conflicts:
        st.success("No cross-agent consistency contradictions detected.")
        return
    st.error(f"{len(conflicts)} cross-agent consistency conflict(s) detected:")
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
    ai_rec = format_compact_status(
        case_summary.get("ai_recommendation", "NOT_EVALUATED")
    )
    pipe_st = format_compact_status(case_summary.get("pipeline_status", "NOT_RUN"))
    rev_st = format_compact_status(case_summary.get("human_review_status", "PENDING"))
    hum_dec = case_summary.get("human_decision")
    latest_rev = case_summary.get("latest_review")

    hum_dec_disp = format_compact_status(hum_dec) if hum_dec else "Not yet recorded"
    reviewer_note = (
        f"By {latest_rev['reviewer_id']} ({str(latest_rev.get('review_timestamp', ''))[:19].replace('T', ' ')} UTC)"
        if latest_rev
        else "Awaiting underwriter action"
    )

    render_kv_grid(
        [
            ("1. AI Recommendation", ai_rec, "Advisory decision support only"),
            ("2. Pipeline Execution", pipe_st, "Automated workflow health"),
            ("3. Human Review Status", rev_st, "Current queue state"),
            ("4. Final Human Decision", hum_dec_disp, reviewer_note),
        ],
        columns=4,
    )

    if latest_rev and latest_rev.get("reviewer_user_id"):
        st.caption(
            f"Verified Reviewer: `{latest_rev.get('reviewer_username') or latest_rev['reviewer_id']}` "
            f"(ID `{latest_rev['reviewer_user_id']}`, Role `{latest_rev.get('reviewer_role') or 'N/A'}`)"
        )
    else:
        st.caption(
            "Local session attribution active. Sign in via the sidebar or use the FastAPI `/api/v1` backend for verified JWT/RBAC attribution."
        )
