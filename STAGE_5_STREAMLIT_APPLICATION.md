# STAGE 5 — COMPLETE STREAMLIT APPLICATION

**Project:** AI Loan Underwriting Assistant  
**Stage:** Stage 5 — Complete Streamlit Application (UI & Application Workflow Completion)  
**Status:** **COMPLETE**  
**Governance Model:** Human-in-the-Loop (HITL) Decision Support (Read-Only Advisory Recommendation)

---

> [!IMPORTANT]
> This Streamlit application is a local research and decision-support workbench. It delegates strictly to the Stage 1–4 deterministic multi-agent backend, never exposes LLM or live banking integrations, never fabricates applicant data or decisions, and preserves final lending authority strictly for authorized human underwriters.

---

## 1. Application Entry Point

- **Primary Entry Point**: [`app/main.py`](app/main.py)
  - Detects `st.runtime.exists()` when launched via `.venv/bin/streamlit run app/main.py` -> calls `configure_page()` once and renders `render_dashboard()` from [`app/ui/dashboard.py`](app/ui/dashboard.py).
  - Supports CLI verification (`DATABASE_URL="sqlite:////tmp/test_audit.db" .venv/bin/python app/main.py`) via `run_cli_verification()` which initializes configuration, logging, `submitted_applications`, and `underwriting_runs` tables cleanly without touching `st.set_page_config`.
- **Legacy Note**: `frontend/streamlit_app.py` is an obsolete Stage 1 static shell and is superseded by [`app/ui/dashboard.py`](app/ui/dashboard.py).

---

## 2. Navigation & Modular UI Architecture

The sidebar (`sidebar_nav_radio` + `sidebar_app_selector` with pending-state transition queuing in [`app/ui/state.py`](app/ui/state.py)) coordinates seven Stage 5 screens (extended in Stage 6 with `Underwriter Review Queue` — see [`STAGE_6_HUMAN_REVIEW_AUDIT.md`](STAGE_6_HUMAN_REVIEW_AUDIT.md)):

| Page | Module | Responsibility |
| :--- | :--- | :--- |
| **Dashboard** | `app/ui/views_portfolio.py` | Actual SQLite KPIs separating submitted/completed applications from underwriting runs, failed-run exclusion, daily trend charts, and recent activity filters |
| **New Application** | `app/ui/views_intake.py` | Authoritative `Applicant` schema intake form, preserved zeros, PDF upload staging & security validation, pre-submission Stage 3 preview, duplicate guard & submission |
| **Applications** | `app/ui/views_portfolio.py` | Searchable directory merging SQLite `submitted_applications` and read-only synthetic catalog (`APP0001`–`APP0100`) without join duplication |
| **Application Details** | `app/ui/views_portfolio.py` | Full applicant profile, uploaded file metadata, validation notices, and chronological multi-run SQLite history |
| **Document Review** | `app/ui/views_results.py` | Per-document telemetry, classification confidence (labeled heuristic), page counts, OCR status, missing/invalid/ambiguous/conflicting fields, and masked extracted values |
| **Underwriting Results** | `app/ui/views_results.py` | Complete decision explainability (`APPROVED (APPROVE)`, `REJECTED (REJECT)`, `MANUAL_REVIEW`), Stage 4 eligibility/risk/fraud/doc evidence, consistency conflicts, and agent statuses |
| **Audit History** | `app/ui/views_portfolio.py` | Immutable read-only SQLite ledger (`underwriting_runs`) with filtering and individual masked run snapshot inspection |

Supporting UI service modules:
- [`app/ui/services.py`](app/ui/services.py): Pure Python backend adapter (`validate_applicant_form_input`, `validate_uploaded_pdf`, `preview_uploaded_documents`, `submit_application_and_underwrite`, `compute_dashboard_metrics`).
- [`app/ui/components.py`](app/ui/components.py): Styling, INR formatting, HITL banner, safe null/unavailable formatters (`format_risk_score_display`, `format_fraud_status_display`), and factor/conflict cards.
- [`app/database/applications.py`](app/database/applications.py): Persisted `submitted_applications` table in SQLite.

---

## 3. Applicant Intake Workflow

Implemented in [`app/ui/views_intake.py`](app/ui/views_intake.py) and `validate_applicant_form_input()` ([`app/ui/services.py`](app/ui/services.py)):
- Collects **strictly the authoritative `Applicant` fields** (`applicant_id`, `name`, `age`, `employment_type`, `employment_years`, `monthly_income`, `existing_emi`, `bank_balance`, `loan_amount`, `loan_tenure`, `credit_score`, optional `monthly_expenses`, optional `number_of_dependents`) — zero unsupported filler fields.
- Preserves valid numeric zeroes (`0` / `0.0`) explicitly (e.g., `existing_emi=0.0`, `bank_balance=0.0`, `monthly_expenses=0.0`, `number_of_dependents=0`) while leaving blank optional fields as `None`.
- Generates collision-free unique references (`APP-YYYYMMDD-XXXX`) via `generate_applicant_reference()`.
- Runs Pydantic schema bounds + Stage 4 `validate_applicant_data()` plausibility checks before enabling submission.

---

## 4. Document Upload Workflow

Implemented in [`app/ui/views_intake.py`](app/ui/views_intake.py) and `validate_uploaded_pdf()` / `temporary_upload_directory()` ([`app/ui/services.py`](app/ui/services.py)):
- Supports canonical Stage 3 document categories: `auto`, `loan_application`, `identity_proof`, `address_proof`, `salary_slip`, `bank_statement`, `income_statement`, and `employment_proof`.
- Validates every uploaded file before staging:
  - Extension must be `.pdf`
  - Size `> 0` bytes and `<= 25 MB` (`DEFAULT_MAX_FILE_SIZE_BYTES`)
  - Signature check requiring `%PDF-` in the opening header
  - Passive scan for `/JavaScript`, `/JS`, `/OpenAction`, `/Launch`, `/AA` active markers
  - SHA-256 deduplication blocking identical uploads
- Supports file removal cleanly before submission and caches pre-submission `DocumentPackageResult` previews by SHA-256 signature so Streamlit reruns do not re-OCR unchanged documents.
- Writes temporary PDFs only into ephemeral `tempfile.TemporaryDirectory()` scopes during execution and deletes them automatically in `try/finally` blocks.

---

## 5. Underwriting Submission Workflow

Handled by `submit_application_and_underwrite()` ([`app/ui/services.py`](app/ui/services.py)):
1. Re-validates applicant inputs and ensures zero invalid staged files remain.
2. Computes a canonical SHA-256 submission fingerprint (`compute_submission_fingerprint`); blocks accidental identical resubmission unless the user explicitly enables intentional re-submission.
3. Delegates execution to `UnderwritingOrchestrator.run_pipeline(applicant, package_dir=...)` -> `DecisionReasoningAgent().evaluate(analysis)` -> `save_underwriting_run_safe(...)`.
4. Preserves partial results and fail-closed `MANUAL_REVIEW` outcomes whenever individual agents fail, documents are missing/corrupt, or DB persistence fails (surfacing `audit_persisted` and `audit_error` cleanly).
5. Records application state in `submitted_applications` without modifying `data/synthetic_data/applicants.json`.
6. Clears draft inputs and staged upload buffers on successful submission so subsequent entries never inherit prior applicant state.

---

## 6. Underwriting Results & Document Review

- **Results Display** ([`app/ui/views_results.py`](app/ui/views_results.py)):
  - Displays mapped categorical recommendation (`APPROVED (APPROVE)`, `REJECTED (REJECT)`, `MANUAL_REVIEW`) plus applicant summary, Stage 4 eligibility status/rules/DTI, ML risk tier/score/model availability, fraud severity/anomalies, document verification status/missing/unclassified/invalid/ambiguous/conflicting fields, consistency conflicts, decision/review reasons, and agent statuses.
  - **Honest Unavailable Representation**: Missing or invalid risk scores render as `Unavailable` (never `0.0`); unavailable fraud assessments render as `UNAVAILABLE (Inspection Required)` (never `NONE` or clean).
- **Document Review** ([`app/ui/views_results.py`](app/ui/views_results.py)):
  - Shows per-document classification, confidence (explicitly documented as heuristic, not calibrated probability), OCR mode, page counts, missing expected fields, invalid/ambiguous/conflicting fields, and masked extracted values/evidence (`mask_extracted_value` using Stage 3 masking utilities).

---

## 7. Application History & Audit History

- **Applications & Application Details** ([`app/ui/views_portfolio.py`](app/ui/views_portfolio.py)):
  - Displays unique applicant rows paired with run counts and latest run state, searchable by ID/name, source (`submitted` vs `synthetic`), latest decision, pipeline status, and date range (`ORDER BY` / grouped without join duplication).
  - Application Details displays full chronological run history per applicant.
- **Audit History** ([`app/ui/views_portfolio.py`](app/ui/views_portfolio.py)):
  - Queries SQLite `underwriting_runs` (including additive `details_snapshot_json` storing masked Stage 3–8 evidence) and Stage 6 append-only `human_review_events` with filters for applicant ref, recommendation, pipeline status, risk category, anomaly severity, and reviewer ID.
  - Strictly read-only (no edit or delete actions). Human underwriter review, follow-up queues, and linked corrections are implemented in Stage 6 ([`STAGE_6_HUMAN_REVIEW_AUDIT.md`](STAGE_6_HUMAN_REVIEW_AUDIT.md)).

---

## 8. Environment Configuration & Startup Instructions

Environment variables (`.env` / shell exports via `config/settings.py`):
- `DATABASE_URL`: SQLite URI (default `sqlite:///./loan_underwriting.db`; set `DATABASE_URL="sqlite:////tmp/test_audit.db"` for isolated testing)
- `APP_ENV`: Runtime environment label (`development`, `test`, `production`)
- `LOG_LEVEL`: Logging level (`INFO`, `DEBUG`, etc.)
- `GEMINI_API_KEY`: Unused in Stages 1–5 (zero LLM calls)

Startup commands:

```bash
# Verify configuration and SQLite tables (isolated test DB recommended)
DATABASE_URL="sqlite:////tmp/test_audit.db" .venv/bin/python app/main.py

# Launch the Streamlit application
.venv/bin/streamlit run app/main.py

# Run Stage 5 Streamlit & audit integration tests
DATABASE_URL="sqlite:////tmp/test_audit.db" .venv/bin/pytest tests/test_streamlit_app.py tests/test_dashboard_audit.py -v
```

---

## 9. Known Limitations & Stage 6 Readiness

1. **Human Officer Override Workflow Deferred (Stage 6)**: Audit records and AI recommendations are strictly read-only in Stage 5; officer sign-off, rationale capture, and override controls belong to Stage 6.
2. **Synchronous In-Process Execution**: OCR, ML inference, and pipeline coordination run synchronously in Python rather than behind a FastAPI microservice or background task queue.
3. **Synthetic Training & Advisory Scope**: ML risk tiers and heuristic confidence/classification scores are grounded in the project's controlled synthetic cohort and do not constitute production credit bureau scoring or regulated banking commitments.
4. **No Authentication / RBAC**: Local prototype interface runs without user authentication or multi-tenant access controls.
