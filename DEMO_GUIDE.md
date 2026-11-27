# Project Demonstration Guide (10–15 Minutes)

This guide provides a structured walkthrough for demonstrating the **AI Loan Underwriting Assistant** using synthetic applicant data and an isolated local database (never mutating historical reference databases).

---

## Pre-Demo Setup (Run Once Before Presentation)

Run all commands from the repository root with an isolated demo database path:

```bash
export DATABASE_URL="sqlite:////tmp/demo_underwriting.db"
export APP_ENV="development"

# 1. Apply Stage 7/8 Alembic migrations cleanly
.venv/bin/alembic upgrade head

# 2. Provision 4 synthetic demo accounts (passwords provided via shell env only)
ALLOW_DEMO_SEED=true \
DEMO_ADMIN_PASSWORD="<choose-local-admin-password>" \
DEMO_OFFICER_PASSWORD="<choose-local-officer-password>" \
DEMO_UNDERWRITER_PASSWORD="<choose-local-underwriter-password>" \
DEMO_SUPERVISOR_PASSWORD="<choose-local-supervisor-password>" \
.venv/bin/python scripts/seed_demo_users.py --confirm-local-demo

# 3. Start FastAPI backend (Terminal 1)
.venv/bin/uvicorn app.api.main:app --port 8000

# 4. Start Streamlit workbench (Terminal 2; optionally add STREAMLIT_AUTH_REQUIRED=true)
STREAMLIT_AUTH_REQUIRED=true .venv/bin/streamlit run app/main.py --server.port 8501
```

> **Maker-Checker Rule:** During the demo, always submit/initiate cases as **`demo_officer`** and perform human reviews as **`demo_underwriter`** or **`demo_supervisor`**—the backend enforces `MakerCheckerError` (`403 Forbidden`) if a user tries to review their own submission.

---

## 15-Step Live Walkthrough (~12–15 Minutes)

### Step 1 — Introduce Problem & Project Scope (0:30)
- **Say:** Traditional manual loan underwriting requires checking PDFs, calculating DTI, detecting hidden anomalies, and logging compliant audit trails. This prototype combines deterministic policy/anomaly rules, ML risk scoring, hybrid PyMuPDF/Tesseract OCR, and mandatory human-in-the-loop governance.
- **Disclose:** All 100 profiles (`APP0001`–`APP0100`) and 30 PDF packages are **100% synthetic**—zero real PII or bank records.

### Step 2 — Present System Architecture (1:00)
- **Show:** Architecture diagram in [`PROJECT_ARCHITECTURE.md`](PROJECT_ARCHITECTURE.md).
- **Explain:** Multi-agent sequential orchestration flows from Document Intake -> Eligibility -> Fraud/Consistency -> ML Risk -> 7-tier Fail-Closed Decision Engine -> Append-Only SQLite Audit Trail -> Human Underwriter Review, protected by Argon2id/JWT RBAC in FastAPI.

### Step 3 — Launch Services & Confirm Clean Health (0:30)
- **Navigate to:** `http://localhost:8501` in the browser.
- **Should appear:** Header `"AI Loan Underwriting Assistant"` and `"Sign In Required"` sidebar prompt blocking workspace access until authentication.
- **Demonstrates:** Fail-closed authentication gate when `STREAMLIT_AUTH_REQUIRED=true` or `APP_ENV=production`.

### Step 4 — Sign In as Synthetic Loan Officer (0:45)
- **Click/Enter:** Expand `Sign In Required` in the sidebar -> sign in as **`demo_officer`** (`LOAN_OFFICER`).
- **Should appear:** Sidebar updates to `Signed in: demo_officer` / `Role: LOAN_OFFICER`, unlocking the 8-page workspace navigation.
- **Test RBAC briefly (optional):** Clicking `Underwriter Review Queue` in `Workspace` shows `Access denied: role 'LOAN_OFFICER' is not authorized...`.

### Step 5 — Inspect Portfolio Dashboard (1:00)
- **Click:** `Dashboard` in sidebar `Workspace`.
- **Should appear:** Separated application KPIs (`Submitted Apps`, `Completed Evaluated`, `Approved`, `Rejected`, `Manual Review`), pipeline run metrics (failed runs counted separately), and human review queue counters.
- **Seed baseline cohort if empty:** Click `Run Sample Baseline Cohort Evaluations (APP0001–APP0010)` to execute real Stage 3–8 runs across 10 synthetic packages.

### Step 6 — Open Synthetic Clean vs Anomaly Applicants (1:00)
- **Click:** Select `APP0002 — Rohan Sharma` in sidebar `Active Application` -> click `Applications` / `Application Details`.
- **Should appear:** Applicant profile, uploaded/package document metadata, and run history (`APPROVE` with zero anomalies).
- **Explain:** Preserves `submitted_applications` separate from read-only synthetic catalog without join duplicates.

### Step 7 — Demonstrate New Application & PDF Intake (1:30)
- **Click:** `New Application` in sidebar `Workspace`.
- **Action:** Enter synthetic test profile (keep or generate `APP-YYYYMMDD-XXXX` ID) and optionally upload PDFs from `data/documents/APP0002/`. Click `Preview Extracted Document Intelligence`, then `Submit & Run Underwriting Pipeline`.
- **Should appear:** Live PDF validation (`%PDF-`, size check, active-content scan), execution latency banner, and newly generated immutable `RUN-...` ID. Submitting without required PDFs demonstrates fail-closed `MANUAL_REVIEW` (never auto-approves unverified profiles!).

### Step 8 — Inspect Document Extraction & OCR Telemetry (1:00)
- **Action:** Select `APP0006` (or inspect scanned OCR sample `APP0002` / `APP0004`) in `Active Application` -> click `Document Review`.
- **Should appear:** Per-document classification confidence (explicitly labeled heuristic), page telemetry (`Native Text` vs `OCR` page counts), masked account/ID values, and field validation status (`valid`).

### Step 9 — Run / Inspect Underwriting Results (1:00)
- **Click:** `Underwriting Results` for **`APP0006`** (Income Mismatch cohort) and **`APP0016`** (Missing Document cohort).
- **Should appear:**
  - `APP0006`: `MANUAL REVIEW`, Eligibility `ELIGIBLE`, Risk `LOW` (`15.1 / 100`), Anomaly `MEDIUM` (`ANOM-INC-001`).
  - `APP0016`: `MANUAL REVIEW`, `documents_missing: ['bank_statement']`, Anomaly `NONE` (`0.0 / 100`).
- **Demonstrates:** Explainable reason codes, unavailable-vs-zero separation, and strict rule that missing documents trigger `MANUAL_REVIEW` (`DEC-DOC-001`) rather than false fraud flags.

### Step 10 — Explain Eligibility, Fraud & Risk Together (1:00)
- **Scroll through:** `Three-Column Decision Factors` (Positive, Negative, Blocking Safeguards) + `Per-Agent Execution Telemetry`.
- **Explain:** Decision engine runs zero LLMs and synthesizes rules in fixed precedence; failed or missing agents force `MANUAL_REVIEW`.

### Step 11 — Show Conflict / Missing-Evidence Routing to Queue (0:45)
- **Click:** `Open Case in Underwriter Review Queue →` (or navigate to `Applications` showing `APP0001` = `REJECT` from low credit score `584`, `APP0006` = `MANUAL_REVIEW`, `APP0026` = `BORDERLINE`).
- **Demonstrates:** Why clean ineligible profiles fail deterministically (`REJECT`), while discrepancies and missing files require human judgment (`MANUAL_REVIEW`).

### Step 12 — Switch Role & Open Underwriter Review Queue (0:45)
- **Action:** Click `Sign Out` in sidebar -> sign in as **`demo_underwriter`** (`UNDERWRITER`).
- **Click:** `Underwriter Review Queue` in sidebar.
- **Should appear:** Filterable queue (`Pending Reviews`, `Additional Info Req.`, etc.), 4 separate status metrics (`1. AI Recommendation`, `2. Pipeline Execution`, `3. Human Review Status`, `4. Final Human Decision`), and 3 evidence inspection tabs. Note that `Authenticated Reviewer (Verified Session)` displays `demo_underwriter (UNDERWRITER)` disabled/read-only (cannot be spoofed!).

### Step 13 — Record an Append-Only Human Decision (1:30)
- **Action:** Select `APP0006`, choose Action `Approve` (or `Request Additional Information`), enter a mandatory 5+ char reason (e.g., `"Verified offline payroll records match declared net income."`), check confirmation checkbox, and click `Submit Human Underwriter Decision`.
- **Should appear:** Receipt banner recording new `REV-...` event. Look at the 4-card panel: **`1. AI Recommendation` stays `MANUAL_REVIEW` unchanged**, while **`3. Human Review Status`** becomes `APPROVED` (`4. Final Human Decision: APPROVE`).

### Step 14 — Show Audit History & Supervisor Correction Concept (1:00)
- **Click:** `Audit History` in sidebar.
- **Should appear:** Both immutable SQLite ledgers—`underwriting_runs` (AI evaluations) and `human_review_events` (human adjudication transitions)—strictly read-only with zero edit/delete actions and SQLite trigger protection. Mention that linked decision corrections require **`demo_supervisor`** (`REVIEW_CORRECT_DECISION`).

### Step 15 — Inspect FastAPI Health & OpenAPI Docs (1:00)
- **Open:** `http://127.0.0.1:8000/api/v1/health` and `http://127.0.0.1:8000/api/docs`.
- **Explain / Demo:** `/api/v1/health` returns `{"status": "ok", "version": "1.0.0"}`; `/api/docs` shows versioned endpoints (`/api/v1/auth/*`, `/api/v1/applicants`, `/api/v1/underwriting`, `/api/v1/reviews`, `/api/v1/audit`, `/api/v1/integrations/status`). Briefly note `POST /api/v1/reviews/submit` rejects any client-supplied `reviewer_id` (`422`) and blocks Maker-Checker self-review (`403`).
