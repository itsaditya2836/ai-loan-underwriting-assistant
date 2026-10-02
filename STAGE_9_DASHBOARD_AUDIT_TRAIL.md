# STAGE 9 — DASHBOARD & AUDIT TRAIL

**Project Title:** AI Loan Underwriting Assistant: A Multi-Agent Agentic AI System for Faster Loan Processing  
**Stage:** Stage 9 — Dashboard & Audit Trail  
**Status:** **COMPLETE** (Final Application Interface Stage)  
**Governance Model:** Human-in-the-Loop Decision Support  

---

> [!IMPORTANT]
> **RESPONSIBLE AI & HUMAN-IN-THE-LOOP GOVERNANCE:**  
> The AI Loan Underwriting Dashboard is a **decision-support tool**, not an autonomous lending system. The system produces an explainable **AI Recommendation** (`APPROVE`, `REJECT`, `MANUAL_REVIEW`). An authorized human loan officer retains ultimate lending authority and responsibility for all credit decisions.  
> All applicant profiles and documents utilized are synthetic and designed exclusively for academic evaluation and software testing.

---

## 1. Dashboard Architecture

Stage 9 implements a local, interactive **Streamlit Dashboard** and an immutable **SQLite Audit Trail** that serves as the visual presentation and compliance layer for the multi-agent system:

```text
                                USER INTERFACE (Stage 9)
                  Streamlit Underwriting Dashboard & Audit Trail
                                       │
                         [Select Application & Click Run]
                                       │
                                       ▼
                   STAGE 7: MULTI-AGENT ORCHESTRATOR
                                       │
       ┌───────────────────────────────┼───────────────────────────────┐
       ▼                               ▼                               ▼
Stage 3: Document Agent      Stage 4: Eligibility Agent      Stage 5: Risk Agent
(Intake, OCR, Classification) (Policy Rules Engine)           (Random Forest ML)
       │                               │                               │
       └───────────────────────────────┼───────────────────────────────┘
                                       │
                                       ▼
                         Stage 6: Fraud / Anomaly Agent
                         (Cross-Document Consistency)
                                       │
                                       ▼
                      UnderwritingAnalysisResult (Stage 7)
                                       │
                                       ▼
                   STAGE 8: DECISION & REASONING AGENT
                   (Deterministic 7-Tier Precedence Engine)
                                       │
                                       ▼
                      DecisionReasoningResult (Stage 8)
                                       │
                  ┌────────────────────┴────────────────────┐
                  ▼                                         ▼
      IMMUTABLE AUDIT TRAIL                     DECISION-SUPPORT DASHBOARD
  (SQLite: underwriting_runs)               (Streamlit Presentation Views)
  - run_id (UUID/Timestamp)                 - Executive Recommendation
  - Full evidence snapshots                 - Explainable Reasoning
  - Positive/Negative/Blocking Factors      - Granular Agent Evidence
  - Pipeline duration telemetry             - Human Review Required Warning
                  │                                         │
                  └────────────────────┬────────────────────┘
                                       ▼
                            AUTHORIZED HUMAN UNDERWRITER
                            (Final Credit Decision Authority)
```

The dashboard acts strictly as a **window into the system**, consuming existing analytical outputs without recalculating or altering any agent findings.

---

## 2. Navigation Structure

The dashboard interface is structured around a streamlined sidebar navigation menu:

```text
Sidebar Navigation
├── 🚀 Underwriting Pipeline   → Interactive multi-agent pipeline execution & decision analysis
├── 👤 Application Details     → Full applicant dossier and historical multi-run ledger
├── 📜 Audit Trail & History   → Comprehensive historical runs database with dynamic filtering
└── 📊 Aggregate Analytics     → Portfolio-level distributions, KPI metrics, and analytical charts
```

The sidebar also provides:
- **Application Selector**: Dropdown containing all 100 synthetic applicants with status tags (`📁 Docs Ready` for `APP0001`–`APP0030`, `⚠️ Data Only` for `APP0031`–`APP0100`).
- **Quick Applicant Snapshot**: Compact summary displaying declared income, requested loan amount, credit score, and city.
- **Academic Disclaimer**: Non-intrusive notification reminding reviewers of synthetic data constraints.

---

## 3. Main Underwriting Workflow

1. **Selection**: The user selects an applicant ID (e.g. `APP0002`) from the sidebar.
2. **Execution**: The user clicks **`▶ Run Underwriting Analysis`**.
3. **Pipeline Invocation**:
   - The multi-agent pipeline coordinates Document Intake (Stage 3), Underwriting Eligibility (Stage 4), Risk Scoring (Stage 5), and Cross-Document Consistency (Stage 6).
   - The Stage 8 Decision & Reasoning Agent synthesizes the findings.
4. **Audit Recording**: The full analysis and decision are immediately persisted as an immutable record in the SQLite `underwriting_runs` table.
5. **Display**: The dashboard updates dynamically to present:
   - AI Recommendation (`APPROVE`, `REJECT`, or `MANUAL_REVIEW`)
   - Decision Confidence score (0.0%–100.0%)
   - Key summary metrics (Eligibility, Risk, Anomaly, Documents)
   - Mandatory Human Review Banner
   - Executive Reasoning Summary and structured decision reasons
   - Visual factor cards (Positive, Negative, Blocking)
   - Multi-agent execution telemetry and duration breakdown
   - Deep-dive accordions for all individual analytical agents

---

## 4. Application Details View

The **Application Details** screen presents the complete applicant profile formatted for underwriting scrutiny:
- **Personal Profile**: Full Name, Age, Gender, City, Employment Type, Employer, Tenure, Dependents.
- **Financial Ledger**: Declared Monthly Income, Existing EMI, Monthly Expenses, Total Monthly Obligations, Calculated Net Disposable Income, and Debt-to-Income (DTI) ratio.
- **Loan Request**: Requested Loan Amount, Repayment Tenure, Bureau Credit Score.
- **Application History**: Chronological table of all recorded underwriting evaluations for this specific applicant, demonstrating multi-run preservation.

---

## 5. Decision Explanation System

Every generated recommendation answers:
1. **What happened?** Clear recommendation badge with semantic colors (Green for `APPROVE`, Red for `REJECT`, Amber for `MANUAL_REVIEW`).
2. **Why was it recommended?** Natural-language executive summary generated by Stage 8.
3. **What specific rules triggered?** Structured decision reasons displaying:
   - Reason Code (e.g. `DEC-ELIG-001`, `DEC-RISK-001`, `DEC-ANOM-001`)
   - Domain Category (`ELIGIBILITY`, `RISK`, `ANOMALY`, `DOCUMENT`, `SYSTEM`, `SYNTHESIS`)
   - Severity Tier (`BLOCKING`, `WARNING`, `INFO`)
   - Originating Agent (e.g. `EligibilityAgent`, `RiskAgent`)
   - Documentary Evidence Citation
4. **What are the key drivers?** Distinct visual cards:
   - **🟢 Positive Factors**: Criteria satisfying policy requirements.
   - **🟡 Negative Factors**: Borderline metrics or minor inconsistencies.
   - **🔴 Blocking Factors**: Hard policy failures or missing documents preventing automated approval.

---

## 6. Document Evidence Presentation

The **Document Intelligence** tab exposes Stage 3 extraction findings with privacy-aware formatting:
- **Physical Ingestion Ledger**: Ingested files, document types, page counts, OCR status, and classification confidence.
- **Structured Key-Value Fields**: Applicant Name, Monthly Income, Account Balance, Existing EMI, and Employer.
- **Source Traceability**: Every extracted field links to its originating filename, page number, extraction confidence, and text excerpt.
- **Missing Document Alert**: Clear warning banner for missing files with the explicit notice:
  > *"Missing document evidence does not indicate fraud; it requires follow-up verification."*

---

## 7. Audit Trail & Immutability

The **Audit Trail** screen provides an immutable compliance ledger backed by SQLite:
- **Immutability Guarantee**: Every pipeline execution creates a new row with a unique `run_id` (e.g. `RUN-APP0001-20261002-123456-789a`). Previous runs are **never** overwritten or deleted.
- **Multi-Run History**: If an application is re-evaluated, both runs remain independently queryable and auditable.
- **Filter Controls**:
  - Filter by Recommendation (`ALL`, `APPROVE`, `REJECT`, `MANUAL_REVIEW`)
  - Filter by Pipeline Status (`ALL`, `SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`)
  - Filter by Risk Category (`ALL`, `LOW`, `MEDIUM`, `HIGH`, `BORDERLINE`)
  - Filter by Anomaly Severity (`ALL`, `NONE`, `LOW`, `MEDIUM`, `HIGH`)
- **Historical Snapshot Inspector**: Selecting any Run ID renders the complete historical state, including executive narrative, reasons, factors, and latency.

---

## 8. Database Schema (`underwriting_runs`)

The audit table is created and managed in `loan_underwriting.db` via `app/database/audit.py`:

```sql
CREATE TABLE IF NOT EXISTS underwriting_runs (
    run_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    decision_policy_version TEXT NOT NULL,
    orchestrator_version TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    decision_confidence REAL NOT NULL,
    eligibility_status TEXT NOT NULL,
    risk_category TEXT NOT NULL,
    risk_score REAL NOT NULL,
    anomaly_severity TEXT NOT NULL,
    anomaly_score REAL NOT NULL,
    documents_found_count INTEGER NOT NULL,
    documents_missing_count INTEGER NOT NULL,
    human_review_required INTEGER NOT NULL,
    pipeline_status TEXT NOT NULL,
    execution_time_ms REAL NOT NULL,
    reasons_json TEXT NOT NULL,
    positive_factors_json TEXT NOT NULL,
    negative_factors_json TEXT NOT NULL,
    blocking_factors_json TEXT NOT NULL,
    supporting_evidence_json TEXT NOT NULL,
    summary_narrative TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_app_id ON underwriting_runs (application_id);
CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON underwriting_runs (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_runs_recommendation ON underwriting_runs (recommendation);
```

---

## 9. Portfolio Analytics & Charts

The **Aggregate Analytics** tab calculates population-level metrics across all audited runs:
- **Key Performance Indicators**:
  - Total Underwriting Executions
  - Unique Applications Evaluated
  - Manual Review Rate (%)
  - Approval Rate (%)
  - Average Decision Confidence (%)
  - Average Pipeline Latency (ms)
- **Distribution Visualizations**:
  1. **Recommendation Distribution**: Bar chart comparing `APPROVE`, `REJECT`, and `MANUAL_REVIEW`.
  2. **Risk Category Distribution**: Breakdown across `LOW`, `MEDIUM`, `HIGH`, and `BORDERLINE`.
  3. **Anomaly Severity Distribution**: Breakdown across `NONE`, `LOW`, `MEDIUM`, and `HIGH`.
  4. **Eligibility Status Distribution**: Breakdown across `ELIGIBLE`, `INELIGIBLE`, and `REVIEW_REQUIRED`.
- **Cohort Preload Utility**: One-click button (`Preload Baseline Cohort Runs`) allowing reviewers to populate the audit table with all 30 baseline cohorts in seconds.

---

## 10. Human-in-the-Loop Design

The interface strictly upholds ethical AI decision-support principles:
- **No Autonomous Lending**: The dashboard contains no automated loan disbursement or approval trigger.
- **Prominent Labeling**: Labeled as **`AI RECOMMENDATION (Decision Support)`**, never `FINAL BANK DECISION`.
- **Mandatory Review Banner**: Prominently displayed at the top of every analysis.
- **Evidence Presentation**: Equips the human underwriter with all relevant citations to verify or contest the recommendation.

---

## 11. Synthetic Data Disclaimer

All screens feature prominent disclaimers:
> *"Academic / Synthetic Data: This application uses synthetic applicant and document data for research and software testing. It is not connected to real customer records or banking systems."*

---

## 12. Automated Testing Suite

The dashboard and audit trail are verified by `tests/test_dashboard_audit.py` (7 tests) and the broader project test suite:
- `test_audit_table_initialization`: Verifies SQLite schema creation and columns.
- `test_save_and_retrieve_underwriting_run`: Tests full roundtrip audit persistence.
- `test_audit_immutability_multiple_runs`: Verifies multiple evaluations of the same applicant preserve distinct IDs.
- `test_audit_filtering`: Tests querying by recommendation, risk tier, and application ID.
- `test_audit_analytics_summary`: Verifies KPI and distribution calculations.
- `test_execute_underwriting_pipeline_integration`: Tests full multi-agent pipeline execution from the dashboard wrapper.
- `test_applicant_metadata_loading`: Tests dataset parsing and physical document package detection.

**Test Suite Results:**
- **Total Tests:** 167
- **Passed:** 167 (100%)
- **Failed:** 0
- **Duration:** 8.67s

---

## 13. Limitations

1. **Synthetic Data**: Reflects controlled synthetic test cases; not empirical banking default rates or fraud prevalence.
2. **Local Prototype**: Designed for local decision support; does not connect to Core Banking Systems (CBS) or live credit bureau APIs.
3. **Decision Confidence Metric**: Reflects internal analytical evidence completeness and agreement, not a calibrated statistical probability.
4. **Advisory Scope**: The software provides explainable recommendations; authorized human credit underwriters hold final authority.

---

## 14. Future Improvements (Post-Mini-Project)

- Integration with Core Banking System (CBS) APIs via secure OAuth2 / mTLS.
- Real-time underwriter comment recording and audit override sign-off.
- Exportable PDF underwriting credit summary memos for credit committees.
- Multi-user role-based access control (Maker-Checker workflow).
