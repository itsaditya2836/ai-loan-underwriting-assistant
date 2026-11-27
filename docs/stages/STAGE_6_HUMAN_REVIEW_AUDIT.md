# STAGE 6 — HUMAN UNDERWRITER REVIEW & AUDIT

**Project:** AI Loan Underwriting Assistant  
**Stage:** Stage 6 — Human Underwriter Review & Audit  
**Status:** **COMPLETE**  
**Governance Model:** Human-in-the-Loop Underwriting with Immutable Append-Only AI & Human Audit Ledgers

---

> [!IMPORTANT]
> **Critical Invariant:** Human underwriter decisions are stored strictly as separate, append-only records in `human_review_events`. A human decision **never** overwrites, edits, or deletes the original AI recommendation, confidence score, or underlying multi-agent analysis persisted in `underwriting_runs`.

---

## 1. Architecture Changes

Stage 6 introduces a dedicated backend human-review service layer, Pydantic review data contracts, an append-only SQLite review table, an 8th Streamlit navigation screen (`Underwriter Review Queue`), and cross-page status separation:

- **Schemas** ([`app/schemas/review.py`](../../app/schemas/review.py), exported via [`app/schemas/__init__.py`](../../app/schemas/__init__.py)):
  - `ReviewStatus` (`PENDING`, `IN_REVIEW`, `APPROVED`, `REJECTED`, `ADDITIONAL_INFO_REQUESTED`, `INVESTIGATION_REQUIRED`)
  - `HumanReviewAction` (`START_REVIEW`, `APPROVE`, `REJECT`, `REQUEST_ADDITIONAL_INFO`, `RETURN_FOR_INVESTIGATION`, `RETURN_TO_PENDING`)
  - `HumanReviewSubmission`, `HumanReviewEvent`, `ACTION_TO_TARGET_STATUS`, `ALLOWED_REVIEW_TRANSITIONS`, `CORRECTION_ALLOWED_TARGETS`
- **Database Layer** ([`app/database/reviews.py`](../../app/database/reviews.py), initialized in [`app/database/db.py`](../../app/database/db.py)):
  - Append-only `human_review_events` table with idempotent `ALTER TABLE` column checks and query/index helpers (`init_reviews_table`, `insert_human_review_event`, `get_latest_review_for_run`, `get_review_history_for_run`, `get_human_review_events`, etc.).
- **Server-Side Review Service** ([`app/review/service.py`](../../app/review/service.py)):
  - Validates inputs, lengths, conditional requirements, confirmation flags, source run existence, explicit status transitions, duplicate submission hashes, privacy masking, and fail-safe DB transactions (`submit_human_review`, `submit_human_review_safe`, `record_additional_info_return`, `list_review_queue`, `compute_review_queue_metrics`, `get_case_review_summary`).
- **Streamlit Workbench & Views**:
  - New [`app/ui/views_review.py`](../../app/ui/views_review.py) implementing **Underwriter Review Queue**.
  - Updated [`app/ui/components.py`](../../app/ui/components.py), [`app/ui/dashboard.py`](../../app/ui/dashboard.py), [`app/ui/state.py`](../../app/ui/state.py), [`app/ui/views_results.py`](../../app/ui/views_results.py), [`app/ui/views_portfolio.py`](../../app/ui/views_portfolio.py), and [`app/ui/views_intake.py`](../../app/ui/views_intake.py) to separate AI Recommendation, Pipeline Execution Status, Human Review Status, and Final Human Decision consistently.

---

## 2. Human Review Workflow & Queue

The **Underwriter Review Queue** (`app/ui/views_review.py`) displays deduplicated cases (`1` latest run row per `application_id`) requiring human attention or oversight:
- **Included Triggers**: AI `MANUAL_REVIEW`, `INCOMPLETE`/`UNVERIFIED`/`FAILED`/`UNAVAILABLE` document state or missing files, `consistency_conflicts`, failed/unavailable agent assessments, and any case with active human status (`PENDING`, `IN_REVIEW`, `ADDITIONAL_INFO_REQUESTED`, `INVESTIGATION_REQUIRED`).
- **Summary Metrics**: Tracks `Pending Reviews`, `In Progress`, `Approved (Human)`, `Rejected (Human)`, `Additional Info Requested`, and `Investigation Required`, while strictly excluding `pipeline_status == "FAILED"` runs from `completed_ai_decisions` counts.
- **Filters**: Applicant reference/name, AI recommendation, pipeline execution status, risk category, human review status (including `NEEDS_HUMAN_ACTION`), and submission date range.
- **Workbench Tabs**:
  1. **Applicant Profile & Financials** (income, EMI, calculated DTI, bank balance, loan request, employment tenure).
  2. **AI Analysis & Decision Triggers** (executive summary, uncalibrated heuristic confidence notice, eligibility, risk, fraud/anomaly, document diagnostics, cross-agent conflicts, review reasons, agent execution statuses).
  3. **Supporting Evidence & Masked Extractions** (rule provenance, anomaly flags, masked extracted document fields).
- **Additional Information Workflow**:
  - `ADDITIONAL_INFO_REQUESTED` / `INVESTIGATION_REQUIRED` instructions appear in the Review Queue, `Application Details`, and `New Application` banner.
  - Staff can record follow-up information and return a case cleanly to `PENDING` (`RETURN_TO_PENDING`) without triggering automatic AI re-execution; if new PDF documents are uploaded via `New Application`, existing Stage 3/Stage 4 pipelines execute explicitly to generate a new run while preserving all prior runs and reviews.

---

## 3. Database Schema & Migrations (`human_review_events`)

Created and migrated idempotently via `init_reviews_table()` in [`app/database/reviews.py`](../../app/database/reviews.py):

| Column | Type | Purpose |
| :--- | :--- | :--- |
| `review_id` | `TEXT PRIMARY KEY` | Unique `REV-<app_id>-<timestamp>-<hex>` identifier |
| `source_run_id` | `TEXT NOT NULL` | Linked AI execution in `underwriting_runs.run_id` |
| `application_id`, `applicant_id` | `TEXT NOT NULL` | Applicant identifier |
| `original_ai_recommendation` | `TEXT NOT NULL` | Immutable copy of AI recommendation at review time |
| `original_pipeline_status` | `TEXT NOT NULL` | Pipeline status of source run (`_REVIEW_EXTRA_COLUMNS` migrated cleanly) |
| `action` | `TEXT NOT NULL` | `HumanReviewAction` value |
| `human_decision` | `TEXT` | Nullable; `'APPROVE'` or `'REJECT'` ONLY for terminal actions, else `NULL` |
| `reviewer_id` | `TEXT NOT NULL` | Mandatory attribution string (2–64 chars) |
| `decision_reason` | `TEXT NOT NULL` | Mandatory justification (5–500 chars) |
| `comments` | `TEXT` | Optional masked comments (<= 2000 chars) |
| `additional_info_request` | `TEXT` | Required when `REQUEST_ADDITIONAL_INFO` (<= 1000 chars) |
| `additional_info_response` | `TEXT` | Recorded follow-up notes when returning to `PENDING` (`_REVIEW_EXTRA_COLUMNS`) |
| `investigation_instructions` | `TEXT` | Required when `RETURN_FOR_INVESTIGATION` (<= 1000 chars) |
| `previous_review_status` | `TEXT NOT NULL` | Authoritative prior `ReviewStatus` before event |
| `new_review_status` | `TEXT NOT NULL` | Resulting `ReviewStatus` after event |
| `is_correction` | `INTEGER NOT NULL` | `1` when event is an explicit linked correction |
| `parent_review_id` | `TEXT` | Linked prior `review_id` for corrections |
| `correction_explanation` | `TEXT` | Mandatory explanation when `is_correction=1` |
| `submission_hash` | `TEXT NOT NULL` | SHA-256 fingerprint preventing duplicate rerun submissions |
| `review_timestamp` | `TEXT NOT NULL` | UTC ISO-8601 timestamp |
| `event_type` | `TEXT NOT NULL` | `'HUMAN_REVIEW_EVENT'` (`_REVIEW_EXTRA_COLUMNS`) |

Indexes: `idx_reviews_app_ts (application_id, review_timestamp DESC)`, `idx_reviews_run_ts (source_run_id, review_timestamp DESC)`, `idx_reviews_hash (submission_hash)`.

---

## 4. Review Status Lifecycle & Allowed Transitions

| From State | Non-Correction Allowed Targets | Terminal? | Correction Behavior |
| :--- | :--- | :--- | :--- |
| `PENDING` | `IN_REVIEW`, `APPROVED`, `REJECTED`, `ADDITIONAL_INFO_REQUESTED`, `INVESTIGATION_REQUIRED` | No | `is_correction=True` with valid `parent_review_id` + explanation allowed if linking prior event |
| `IN_REVIEW` | `PENDING`, `APPROVED`, `REJECTED`, `ADDITIONAL_INFO_REQUESTED`, `INVESTIGATION_REQUIRED` | No | Same as above |
| `ADDITIONAL_INFO_REQUESTED` | `PENDING`, `IN_REVIEW`, `APPROVED`, `REJECTED`, `INVESTIGATION_REQUIRED` | No | Never counted as approval/rejection |
| `INVESTIGATION_REQUIRED` | `PENDING`, `IN_REVIEW`, `APPROVED`, `REJECTED`, `ADDITIONAL_INFO_REQUESTED` | No | Never counted as final underwriting decision |
| `APPROVED` | **None** (non-correction updates blocked) | Yes | Requires `is_correction=True`, `parent_review_id`, and `correction_explanation` (`>= 5` chars) |
| `REJECTED` | **None** (non-correction updates blocked) | Yes | Requires `is_correction=True`, `parent_review_id`, and `correction_explanation` (`>= 5` chars) |

---

## 5. Audit Implementation & Privacy / Security Safeguards

- **Append-Only Persistence**: No `UPDATE` or `DELETE` SQL statement exists on `human_review_events` or `underwriting_runs`.
- **Audit History Inspection**: `render_audit_history_view()` and `render_audit_run_inspection()` ([`app/ui/views_portfolio.py`](../../app/ui/views_portfolio.py)) allow filtering AI runs (`UNDERWRITING_RUN`), Human Review Events (`HUMAN_REVIEW_EVENT`), reviewer IDs, transitions, comments, and linked corrections in read-only mode.
- **Privacy & Integrity Safeguards**:
  - Server-side validation rejects missing `reviewer_id`, missing `decision_reason`, missing conditional info/investigation fields, unconfirmed submissions, non-existent `source_run_id`, and over-limit strings.
  - Comments, reasons, and notes pass through control-character sanitization and `mask_sensitive_text(...)` from [`app/document_processing/security.py`](../../app/document_processing/security.py).
  - Duplicate SHA-256 `submission_hash` detection blocks duplicate saves caused by Streamlit reruns.
  - `submit_human_review_safe()` isolates SQLite transaction errors and never reports saved success if persistence fails.

---

## 6. Reviewer Attribution Limitations & Stage 7 Dependencies

1. **Attribution Only (No Auth / RBAC)**: `reviewer_id` is a user-entered attribution identifier validated for length and safe characters. The local prototype does not authenticate users, verify credentials, enforce role-based access control (Maker-Checker / Supervisor permissions for corrections), or bind sessions to SSO identities — **deferred to Stage 7**.
2. **Synchronous Local Storage**: All events execute locally against SQLite (`DATABASE_URL`); PostgreSQL and multi-user concurrency locking remain Stage 7+ work.
3. **Synthetic Dataset & Advisory AI Boundaries**: AI confidence/risk/anomaly scores are uncalibrated deterministic/synthetic outputs; Stage 1–4 policy thresholds and ML model features were left strictly unchanged.

---

## 7. Automated Tests (`tests/test_human_review.py`)

Verified via [`tests/test_human_review.py`](../../tests/test_human_review.py) against isolated `tmp_path` SQLite databases:
- `test_review_queue_filtering_and_failed_run_exclusion`
- `test_human_review_actions_and_immutable_ai_preservation`
- `test_validation_rejects_missing_and_invalid_inputs`
- `test_transitions_duplicate_protection_and_linked_corrections`
- `test_human_review_db_failure_and_idempotent_migration`
- `test_streamlit_apptest_human_review_queue_and_audit_separation`

Run command:
```bash
DATABASE_URL="sqlite:////tmp/test_audit.db" .venv/bin/pytest tests/test_human_review.py tests/test_streamlit_app.py tests/test_dashboard_audit.py -v
```
