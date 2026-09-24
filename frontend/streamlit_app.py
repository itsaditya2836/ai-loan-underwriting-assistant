"""Streamlit UI Shell for AI Loan Underwriting Assistant.

Serves as the decision-support dashboard for loan officers.
Stage 1: Displays UI layout skeleton with clear placeholders for future stages.
"""

import streamlit as st

# Page Configuration
st.set_page_config(
    page_title="AI Loan Underwriting Assistant",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E3A8A;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #4B5563;
        margin-bottom: 1.5rem;
    }
    .notice-card {
        background-color: #EFF6FF;
        border-left: 4px solid #3B82F6;
        padding: 1rem;
        border-radius: 4px;
        margin-bottom: 1.5rem;
    }
    .placeholder-box {
        background-color: #F9FAFB;
        border: 1px dashed #D1D5DB;
        border-radius: 8px;
        padding: 1.25rem;
        text-align: center;
        color: #6B7280;
        margin-bottom: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Header Section
st.markdown(
    '<div class="main-title">🏦 AI Loan Underwriting Assistant</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="sub-title">A Multi-Agent Agentic AI System for Faster Loan Processing</div>',
    unsafe_allow_html=True,
)

# Responsible AI & Decision-Support Notice
st.markdown(
    """
    <div class="notice-card">
        <strong>⚠️ Decision-Support Prototype Notice:</strong>
        This system is designed exclusively to assist human loan officers with automated document extraction,
        eligibility verification, risk calculation, and anomaly detection.
        <strong>It does not replace authorized human underwriting decisions.</strong>
        The loan officer retains final decision-making authority and responsibility.
    </div>
    """,
    unsafe_allow_html=True,
)

# Sidebar Navigation / Application Selector
with st.sidebar:
    st.header("📋 Underwriting Workspace")
    st.caption("Stage 1: Architecture Foundation")

    loan_type = st.selectbox(
        "Loan Category",
        ["Personal Loan", "Home Loan"],
        disabled=True,
        help="Category selection will be active in Stage 2.",
    )

    st.markdown("---")
    st.subheader("System Status")
    st.info("Environment: Development\n\nDatabase: SQLite (Connected)")

    st.markdown("---")
    st.caption("AI Loan Underwriting Assistant v0.1.0\nStage 1: Project Setup")

# Dashboard Layout: Tabs for organized view of the 10 core sections
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    [
        "1-3. Intake & Documents",
        "4-5. Applicant & Eligibility",
        "6-7. Risk & Anomaly",
        "8-9. Recommendation & Review",
        "10. Audit Record",
    ]
)

# Tab 1: Intake & Documents
with tab1:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("1. Loan Application")
        st.markdown(
            """
            <div class="placeholder-box">
                <p><strong>Loan Application Intake</strong></p>
                <p>Applicant identifier assignment, loan amount, requested tenure, and applicant profile creation.</p>
                <em>Implementation coming in subsequent stages (Stage 2).</em>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.subheader("2. Document Upload")
        st.markdown(
            """
            <div class="placeholder-box">
                <p><strong>Document Upload & Intake</strong></p>
                <p>Upload PDF/image files (Salary slips, Bank statements, ID proofs).</p>
                <em>Implementation coming in subsequent stages (Stage 3).</em>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.subheader("3. Processing Status")
    st.markdown(
        """
        <div class="placeholder-box">
            <p><strong>Multi-Agent Pipeline Progression</strong></p>
            <p>Live progress tracking: Document OCR → Field Extraction → Eligibility → Risk → Anomaly Detection.</p>
            <em>Implementation coming in subsequent stages (Stage 7).</em>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Tab 2: Applicant & Eligibility
with tab2:
    col3, col4 = st.columns(2)

    with col3:
        st.subheader("4. Applicant Information")
        st.markdown(
            """
            <div class="placeholder-box">
                <p><strong>Extracted Applicant Profile</strong></p>
                <p>Verified income, employer, age, employment years, existing obligations, and bank balance.</p>
                <em>Implementation coming in subsequent stages (Stage 3).</em>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col4:
        st.subheader("5. Eligibility")
        st.markdown(
            """
            <div class="placeholder-box">
                <p><strong>Policy Eligibility Verification</strong></p>
                <p>Rule-based checks: Debt-to-Income (DTI), minimum income, credit score thresholds, maximum eligible amount.</p>
                <em>Implementation coming in subsequent stages (Stage 4).</em>
            </div>
            """,
            unsafe_allow_html=True,
        )

# Tab 3: Risk & Anomaly
with tab3:
    col5, col6 = st.columns(2)

    with col5:
        st.subheader("6. Risk Assessment")
        st.markdown(
            """
            <div class="placeholder-box">
                <p><strong>Credit & Repayment Risk</strong></p>
                <p>Risk scoring model output, risk tier (LOW/MEDIUM/HIGH), and key contributing risk factors.</p>
                <em>Implementation coming in subsequent stages (Stage 5).</em>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col6:
        st.subheader("7. Fraud / Anomaly Detection")
        st.markdown(
            """
            <div class="placeholder-box">
                <p><strong>Cross-Document Anomaly Flags</strong></p>
                <p>Consistency checks across documents (income discrepancies, altered dates, suspicious edits).</p>
                <em>Implementation coming in subsequent stages (Stage 6).</em>
            </div>
            """,
            unsafe_allow_html=True,
        )

# Tab 4: Recommendation & Review
with tab4:
    col7, col8 = st.columns(2)

    with col7:
        st.subheader("8. AI Recommendation")
        st.markdown(
            """
            <div class="placeholder-box">
                <p><strong>Explainable Recommendation</strong></p>
                <p>Synthesis output: APPROVE, REJECT, or MANUAL_REVIEW with supporting reasoning and evidence trail.</p>
                <em>Implementation coming in subsequent stages (Stage 7).</em>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col8:
        st.subheader("9. Loan Officer Review")
        st.markdown(
            """
            <div class="placeholder-box">
                <p><strong>Human Review & Final Decision</strong></p>
                <p>Officer overrides, final decision recording, condition notes, and underwriter sign-off.</p>
                <em>Implementation coming in subsequent stages (Stage 8).</em>
            </div>
            """,
            unsafe_allow_html=True,
        )

# Tab 5: Audit Record
with tab5:
    st.subheader("10. Audit Record")
    st.markdown(
        """
        <div class="placeholder-box">
            <p><strong>Immutable Audit Trail</strong></p>
            <p>Chronological timestamped log: document versions, agent findings, AI recommendation, and officer decision.</p>
            <em>Implementation coming in subsequent stages (Stage 8).</em>
        </div>
        """,
        unsafe_allow_html=True,
    )
