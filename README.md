# AI Loan Underwriting Assistant

**A Modular Multi-Agent Decision-Support System with Document Intelligence, Machine-Learning Risk Scoring, Explainable Underwriting Decisions, FastAPI RBAC Backend, and Human-in-the-Loop Audit Ledger**

> [!IMPORTANT]
> **Academic & Synthetic Data Disclosure:**  
> All datasets (`APP0001`–`APP0100`), document PDFs (`APP0001`–`APP0030`), credit profiles, and evaluation metrics in this repository are **100% synthetic**. This system is **not** trained or validated on real banking portfolios or production customer data, acts strictly as a decision-support assistant (`human_review_required = True`), and is currently classified as **`READY FOR CONTROLLED TESTING`** ([`docs/stages/STAGE_8_PRODUCTION_READINESS.md`](docs/stages/STAGE_8_PRODUCTION_READINESS.md)).

---

## 1. Project Overview

The **AI Loan Underwriting Assistant** automates the intake, document extraction, policy eligibility verification, cross-document consistency checking, and credit-risk estimation phases of personal loan underwriting while preserving full human authority over final lending decisions.

Instead of delegating approvals to a black-box language model or standalone classifier, the application coordinates five specialized agents (`DocumentIntakeAgent`, `EligibilityAgent`, `FraudAnomalyAgent`, `RiskAgent`, and `DecisionReasoningAgent`) through a fault-tolerant orchestrator backed by an append-only audit database and a role-based FastAPI + Streamlit architecture.

---

## 2. Problem Statement

Manual loan underwriting relies on human analysts opening disparate PDFs (application forms, ID proofs, salary slips, bank statements), manually reconciling declared earnings/EMIs against bank transaction credits, computing debt-to-income ratios, and writing audit justifications. Conversely, naive automation suffers from:
- Opaque model scores lacking verifiable policy or document provenance.
- Silent failures when documents are scanned/image-only, corrupted, or missing.
- Confusing missing documentation with fraudulent behavior.
- Lack of separation between advisory AI scores and accountable human approvals/rejections, and weak access controls when multiple officers and underwriters share a system.

---

## 3. Objectives

1. **Multi-Format Document Intelligence:** Parse digital, scanned (Tesseract OCR), and mixed multi-page PDFs with page-level provenance, security safeguards, and masked PII output.
2. **Deterministic Eligibility & Consistency Verification:** Evaluate lending rules (`credit_score`, `DTI`, income, tenure) and detect cross-document financial anomalies (`ANOM-*`) while keeping missing documents distinct from fraud.
3. **Leakage-Free ML Risk Assessment:** Predict credit-risk categories (`LOW`, `MEDIUM`, `HIGH`, `BORDERLINE`) and scores using a standardized 15-feature contract strictly excluding protected attributes (`gender`).
4. **Fail-Closed Orchestration & Explainable Reasoning:** Synthesize agent outputs into `APPROVE`, `REJECT`, or `MANUAL_REVIEW` via a 7-tier deterministic precedence hierarchy that blocks automatic approval whenever evidence is incomplete, conflicting, or unavailable.
5. **Security, RBAC & Human-in-the-Loop Governance:** Enforce Argon2id/JWT authentication, 4-role RBAC (`ADMINISTRATOR`, `LOAN_OFFICER`, `UNDERWRITER`, `SUPERVISOR`), Maker-Checker self-review prevention, and append-only AI and human review ledgers.

---

## 4. Key Features

- **8-Page Interactive Streamlit Workbench** ([`app/main.py`](app/main.py)): `Dashboard`, `Underwriter Review Queue`, `New Application`, `Applications`, `Application Details`, `Document Review`, `Underwriting Results`, and `Audit History`.
- **Versioned FastAPI REST Backend (`/api/v1`)** ([`app/api/main.py`](app/api/main.py)): JWT auth with rotating single-use refresh tokens and reuse detection, RBAC enforcement, path-safe PDF upload APIs, underwriting runner, Maker-Checker review submission, and audit queries.
- **Hybrid PDF & OCR Extraction Engine** ([`app/document_processing/`](app/document_processing/)): Page-level routing between PyMuPDF native text extraction and Pillow + Tesseract OCR preprocessing (`300 DPI`), detecting duplicates and field conflicts.
- **Explainable Decision Reasoning Engine** ([`app/decision/`](app/decision/)): Standardized machine-readable reason codes (`DEC-ELIG-*`, `DEC-DOC-*`, `DEC-ANOM-*`, `DEC-RISK-*`, `DEC-CON-*`, `DEC-APP-*`) with Positive, Negative, and Blocking safeguard factors.
- **Immutable Audit Trail & Concurrency Control** ([`app/database/`](app/database/), [`alembic/`](alembic/)): Separate `underwriting_runs` and `human_review_events` tables protected by optimistic concurrency, SQLite `BEGIN IMMEDIATE` serialization, and database triggers preventing updates/deletes.

---

## 5. System Architecture

Full component details and data-flow explanations appear in [`PROJECT_ARCHITECTURE.md`](PROJECT_ARCHITECTURE.md).

```text
  Streamlit Workbench (app/main.py)         FastAPI REST API (/api/v1, app/api/main.py)
                 │                                            │
                 └──────────────┬─────────────────────────────┘
                                ▼
             Auth, Argon2id, JWT & RBAC (app/auth/)
                                │
          ┌─────────────────────┴─────────────────────┐
          ▼                                           ▼
Multi-Agent Orchestrator (app/orchestration/)   Human Review Service (app/review/)
  ├── 1. DocumentIntakeAgent (PyMuPDF + OCR)     └── Maker-Checker + State Machine
  ├── 2. EligibilityAgent (10 Policy Rules)                    │
  ├── 3. FraudAnomalyAgent (Cross-Doc Checks)                  │
  ├── 4. RiskAgent (RandomForest Pipeline)                     │
  └── 5. DecisionReasoningAgent (7-Tier Precedence)            │
          │                                                    │
          └─────────────────────┬──────────────────────────────┘
                                ▼
       SQLite Append-Only Ledgers + Alembic Schema (app/database/)
```

---

## 6. Technology Stack

- **Language & Runtime:** Python 3.11+ (verified on Python 3.14.6 in `.venv`)
- **Presentation UI:** Streamlit (`app/main.py` -> `app/ui/dashboard.py`)
- **Backend API & Auth:** FastAPI, Uvicorn, Starlette, Pydantic v2 (`pydantic-settings`), `argon2-cffi`, `python-jose[cryptography]` (HS256/HS384/HS512)
- **Data & Machine Learning:** pandas, NumPy, scikit-learn (`SimpleImputer` + `RandomForestClassifier`, serialized with `joblib`)
- **Document Processing & OCR:** PyMuPDF (`pymupdf`), Pillow, `pytesseract` (Tesseract OCR system binary), ReportLab
- **Database & Migrations:** SQLite (`sqlite3`, triggers, `BEGIN IMMEDIATE`), SQLAlchemy Core (`sqlalchemy>=2.0`), Alembic (`alembic`) — PostgreSQL dialect/DDL configured for future runtime cutover
- **Testing & Code Quality:** `pytest`, `httpx2`, `black`, `ruff`

---

## 7. Project Directory Structure

```text
AI-Loan-Underwriting-Assistant/
├── app/
│   ├── main.py                         # Active Streamlit & CLI verification entry point
│   ├── agents/                         # Thin agent wrappers (Document, Eligibility, Fraud, Risk, Orchestrator, Decision)
│   ├── api/                            # FastAPI /api/v1 application, dependencies & route modules
│   │   ├── main.py                     # API app factory, lifespan, CORS & security headers
│   │   ├── dependencies.py             # Token extraction, RBAC checks, path-safe ID validation
│   │   └── routes/                     # auth, users, applicants, documents, underwriting, reviews, audit, integrations
│   ├── auth/                           # Argon2id hashing, JWT lifecycle, RBAC matrix & AuthService
│   ├── database/                       # SQLite persistence, SQLAlchemy Core schema, pooling & migration utilities
│   ├── decision/                       # 7-tier DecisionReasoningAgent policy, rules & narrative synthesis
│   ├── document_processing/            # Stage 3 PDF reader, Tesseract OCR, classifier, validation & security
│   ├── eligibility/                    # Centralized EligibilityPolicy & deterministic rule evaluations
│   ├── fraud/                          # Cross-document consistency checks & bounded anomaly scoring
│   ├── integrations/                   # Pluggable sandbox/disabled provider interfaces (bureau, KYC, LLM, webhooks)
│   ├── orchestration/                  # Dependency-ordered pipeline coordinator & consistency verifier
│   ├── review/                         # Server-side human review state machine & Maker-Checker submission service
│   ├── risk/                           # 15-feature RiskFeatureContract, baseline scorer & ML risk wrapper
│   ├── schemas/                        # Pydantic v2 domain models & API/audit contracts
│   ├── ui/                             # Active 8-page Streamlit workbench & session state management
│   └── utils/                          # Centralized logging helpers
├── alembic/                            # Database migration environment & versioned scripts (0001, 0002)
├── config/settings.py                  # Pydantic BaseSettings & production security fail-closed validator
├── data/
│   ├── synthetic_data/                 # applicants.csv, applicants.json, ground_truth.json, manifest, metadata
│   └── documents/                      # 30 synthetic PDF packages (APP0001–APP0030)
├── docs/
│   ├── screenshots/                    # Captured screenshots from live Streamlit workbench & Swagger docs
│   └── stages/                         # Stage-by-stage technical reports & production readiness audit
├── models/                             # risk_model.joblib & risk_model_metadata.json (SHA-256 verified)
├── scripts/                            # Dataset generation, validation, training, evaluation, demo seed & PG migration
├── tests/                              # 300 automated unit, integration, security & Streamlit AppTest tests
├── .env.example                        # Local development environment template
├── .env.production.example             # Production configuration template (no real secrets)
├── PROJECT_ARCHITECTURE.md             # Detailed architecture & Mermaid diagram
├── DEMO_GUIDE.md                       # 10–15 minute academic presentation walkthrough
├── PROJECT_REPORT_OUTLINE.md           # 23-chapter academic capstone report outline
└── requirements.txt                    # Python dependencies
```

*(Note: `frontend/streamlit_app.py` is retained only as an obsolete Stage 1 static mockup shell and is superseded by `app/main.py`.)*

---

## 8. Installation Instructions

### Prerequisites
- Python **3.11+**
- **Tesseract OCR** binary installed on `PATH` for rasterized PDF OCR (`brew install tesseract` on macOS, `sudo apt-get install tesseract-ocr` on Ubuntu/Debian)

### Setup Steps

```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Copy environment configuration template
cp .env.example .env

# 4. Initialize / migrate a local database cleanly
DATABASE_URL="sqlite:///./local_dev.db" .venv/bin/alembic upgrade head
```

---

## 9. Environment Configuration

Configuration is managed in [`config/settings.py`](config/settings.py) via `.env` or environment variables:

| Variable | Description | Local Default | Production Note |
| :--- | :--- | :--- | :--- |
| `APP_ENV` | `development`, `test`, or `production` | `development` | `production` enables fail-closed startup checks & hides Swagger docs |
| `DATABASE_URL` | SQLite or PostgreSQL connection string | `sqlite:///./loan_underwriting.db` | Use an isolated path (`sqlite:////tmp/test.db`) for testing/demos |
| `JWT_SECRET_KEY` | HMAC secret for signing JWT tokens | `DEV-ONLY-...` | **Mandatory** 32+ char high-entropy secret in `production` |
| `JWT_ALGORITHM` | Token algorithm (`HS256`, `HS384`, `HS512`) | `HS256` | Asymmetric/`none` algorithms rejected |
| `STREAMLIT_AUTH_REQUIRED` | Require login gate in Streamlit UI | `false` | Automatically `true` whenever `APP_ENV=production` |
| `DEFAULT_ADMIN_PASSWORD` | Initial admin seed password (dev/test only) | `admin-dev-...` | Auto-seeding is disabled in `production` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated CORS allowlist | `http://localhost:8501,...` | Wildcard `*` refused in `production` |

See [`.env.example`](.env.example) and [`.env.production.example`](.env.production.example) for the complete list (including rate limiting, lockout thresholds, `JWT_ISSUER`, `JWT_AUDIENCE`, and `DB_POOL_*`).

---

## 10. Dataset Description (100% Synthetic)

All data under `data/` was deterministically generated with `random_seed = 42` by [`scripts/generate_synthetic_dataset.py`](scripts/generate_synthetic_dataset.py) and [`scripts/generate_documents.py`](scripts/generate_documents.py):
- **Structured Applicant Dataset (`N = 100`):** [`data/synthetic_data/applicants.csv`](data/synthetic_data/applicants.csv) and [`applicants.json`](data/synthetic_data/applicants.json) containing balanced synthetic risk cohorts (`LOW_RISK: 30`, `MEDIUM_RISK: 30`, `HIGH_RISK: 20`, `BORDERLINE: 20`).
- **Document Packages (`N = 30`, `115` PDFs):** `data/documents/APP0001` through `APP0030` across 6 controlled cohorts:
  - `APP0001`–`APP0005`: Normal consistent packages
  - `APP0006`–`APP0010`: Income mismatch (`ANOM-INC-001`)
  - `APP0011`–`APP0015`: Identity/name mismatch (`ANOM-ID-001`)
  - `APP0016`–`APP0020`: Missing mandatory document (`missing_evidence`)
  - `APP0021`–`APP0025`: Financial inconsistency (`ANOM-FIN-001`, `ANOM-FIN-002`)
  - `APP0026`–`APP0030`: Borderline credit/DTI policy cases (`MANUAL_REVIEW`)
- Every generated document is explicitly watermarked `SYNTHETIC DOCUMENT — FOR SOFTWARE TESTING ONLY` and uses synthetic identifiers (`SYN-ID-...`) with zero real individuals or accounts.

---

## 11. Running the Applications

### CLI Health & Schema Verification
```bash
DATABASE_URL="sqlite:////tmp/demo_underwriting.db" .venv/bin/python app/main.py
```

### Streamlit Underwriting Workbench
```bash
# Unauthenticated local exploration mode (default in development)
DATABASE_URL="sqlite:////tmp/demo_underwriting.db" .venv/bin/streamlit run app/main.py

# Authenticated RBAC mode (recommended for live demo)
DATABASE_URL="sqlite:////tmp/demo_underwriting.db" STREAMLIT_AUTH_REQUIRED=true \
  .venv/bin/streamlit run app/main.py --server.port 8501
```

### FastAPI REST Backend (`/api/v1`)
```bash
DATABASE_URL="sqlite:////tmp/demo_underwriting.db" \
  .venv/bin/uvicorn app.api.main:app --reload --port 8000
```
- **Health Endpoint:** `http://127.0.0.1:8000/api/v1/health`
- **Swagger / OpenAPI Docs (`APP_ENV=development`):** `http://127.0.0.1:8000/api/docs`

---

## 12. Demo Accounts Setup & Walkthrough

Synthetic demo accounts are provisioned on demand via [`scripts/seed_demo_users.py`](scripts/seed_demo_users.py) using passwords supplied purely from environment variables (never hardcoded or committed to Git; strictly blocked when `APP_ENV=production`):

```bash
export DATABASE_URL="sqlite:////tmp/demo_underwriting.db"
.venv/bin/alembic upgrade head

ALLOW_DEMO_SEED=true \
DEMO_ADMIN_PASSWORD="<set-local-password>" \
DEMO_OFFICER_PASSWORD="<set-local-password>" \
DEMO_UNDERWRITER_PASSWORD="<set-local-password>" \
DEMO_SUPERVISOR_PASSWORD="<set-local-password>" \
.venv/bin/python scripts/seed_demo_users.py --confirm-local-demo
```

Follow the complete 15-step 10–15 minute presentation sequence in [`DEMO_GUIDE.md`](DEMO_GUIDE.md). Real UI screenshots live in [`docs/screenshots/`](docs/screenshots/).

---

## 13. Authentication, Roles & Workflows

### Role-Based Access Control (RBAC)
- **`ADMINISTRATOR`:** User CRUD, role assignment, account unlock, integration status, full portfolio/audit read access.
- **`LOAN_OFFICER`:** Register applicants, upload validated PDFs, initiate underwriting runs, view own submitted applications/runs and read-only synthetic catalog (blocked from review queue and other officers' private applications).
- **`UNDERWRITER`:** Inspect assigned/open review cases, evidence, and AI reasoning; submit `START_REVIEW`, `APPROVE`, `REJECT`, `REQUEST_ADDITIONAL_INFO`, `RETURN_FOR_INVESTIGATION`, `RETURN_TO_PENDING` decisions (blocked from decision corrections and self-reviews).
- **`SUPERVISOR`:** All review inspection plus full portfolio audit analytics and authorized linked corrections (`is_correction=True`) after terminal human decisions.

### Underwriting & Human Review Workflows
1. **Underwriting Execution:** `DocumentIntakeAgent` extracts & validates PDF fields -> `EligibilityAgent` evaluates 10 policy rules -> `FraudAnomalyAgent` cross-checks income/EMIs/balance/names -> `RiskAgent` scores 15 features via `risk_model_rf_v2` -> `check_cross_agent_consistency` flags cross-agent conflicts -> `DecisionReasoningAgent` emits `APPROVE`, `REJECT`, or `MANUAL_REVIEW` and persists an immutable row in `underwriting_runs`.
2. **Human Review & Audit:** Reviewers adjudicate cases via `Underwriter Review Queue` or `POST /api/v1/reviews/submit` (derived exclusively from authenticated identity, enforcing Maker-Checker self-review checks and optimistic concurrency). Every action appends a new `human_review_events` row while preserving `original_ai_recommendation` untouched.

---

## 14. Evaluation Results & Verification Commands

*(All benchmarks below measure deterministic behavior on the **synthetic** cohort; commands were verified against isolated temporary SQLite databases while leaving the reference `loan_underwriting.db` unmodified.)*

| Suite / Benchmark | Command | Verified Result |
| :--- | :--- | :--- |
| Full Automated Test Suite | `DATABASE_URL="sqlite:////tmp/test_audit.db" .venv/bin/pytest -q` | **`300 passed`** (Stages 1–8 unit, API, security, DB, AppTest) |
| Lint & Format | `.venv/bin/ruff check . && .venv/bin/black --check .` | Passed (`133 files` clean) |
| Dataset & Artifact Integrity | `DATABASE_URL="sqlite:////tmp/test.db" .venv/bin/python scripts/validate_dataset.py` | Passed (`100/100` profiles, `30/30` doc dirs, feature parity) |
| Stage 3 PDF & OCR Evaluation | `DATABASE_URL="sqlite:////tmp/test.db" .venv/bin/python scripts/evaluate_extraction.py` | `115/115` doc classification, `30/30` missing-set, `4/4` OCR scans, `1,525` valid fields |
| Stage 4 Eligibility Evaluation | `DATABASE_URL="sqlite:////tmp/test.db" .venv/bin/python scripts/evaluate_eligibility.py` | Docs: `18` Eligible / `8` Ineligible / `4` Review; Full `N=100`: `72`/`28`/`0` |
| Stage 5 ML Risk Evaluation | `DATABASE_URL="sqlite:////tmp/test.db" .venv/bin/python scripts/evaluate_risk_model.py` | 5-fold CV `96.25% +/- 3.06%`; Held-out `N=20` acc `95.00%` (F1 `0.9365`) vs baseline `60.00%` *(synthetic only)* |
| Stage 6 Anomaly Cohort | `DATABASE_URL="sqlite:////tmp/test.db" .venv/bin/python scripts/evaluate_anomaly_detection.py` | `30/30` cohort detection (`15` TP / `15` TN / `0` FP), `5/5` missing docs separated from fraud |
| Stage 4 End-to-End & Probes | `DATABASE_URL="sqlite:////tmp/test.db" .venv/bin/python scripts/evaluate_end_to_end.py` | `30/30` deterministic `SUCCESS` (`4 APPROVE`, `8 REJECT`, `18 MANUAL_REVIEW`); `4/4` failure/conflict probes safe |

---

## 15. Known Limitations & Future Enhancements

- **PostgreSQL Runtime (`NOT RUN`):** SQLAlchemy schemas (`app/database/schema.py`, `app/auth/models.py`), connection pooling config, and Alembic DDL compilation for PostgreSQL are implemented, and a non-destructive copy tool (`scripts/migrate_sqlite_to_postgres.py`) exists. However, Stage 4–6 persistence helpers (`applications.py`, `audit.py`, `reviews.py`) still use raw `sqlite3` SQL (`get_database_connection()` explicitly rejects non-SQLite URLs), no Postgres Python driver is installed in `.venv`, and live PostgreSQL execution has not yet been tested.
- **Synthetic Training & Heuristic Scores:** Model performance reflects `N=100` synthetic records (`80` train / `20` test), not empirical bank defaults; classification/decision confidences are heuristic agreement scores rather than calibrated probabilities.
- **External Integrations:** Credit bureau, KYC, LLM reasoning, and webhook adapters (`app/integrations/`) operate strictly as local sandbox/no-op stubs.
- **Future Enhancements:**
  1. Convert Stage 4–6 raw `sqlite3` queries to SQLAlchemy Core and verify full integration tests against a live PostgreSQL instance.
  2. Replace `python-jose` with `PyJWT` for modern cryptographic token maintenance.
  3. Add Redis/API-gateway distributed rate limiting, email/MFA self-service recovery, shared encrypted object storage for PDFs, and re-calibration/fairness validation on empirical lending datasets.

---

## 16. Stage Documentation Index

- [`PROJECT_ARCHITECTURE.md`](PROJECT_ARCHITECTURE.md) | [`DEMO_GUIDE.md`](DEMO_GUIDE.md) | [`PROJECT_REPORT_OUTLINE.md`](PROJECT_REPORT_OUTLINE.md) | [`docs/stages/`](docs/stages/README.md) | [`docs/screenshots/`](docs/screenshots/README.md)
- [`STAGE_3_DOCUMENT_INTELLIGENCE.md`](docs/stages/STAGE_3_DOCUMENT_INTELLIGENCE.md) | [`STAGE_4_ELIGIBILITY.md`](docs/stages/STAGE_4_ELIGIBILITY.md) | [`STAGE_5_RISK_ASSESSMENT.md`](docs/stages/STAGE_5_RISK_ASSESSMENT.md)
- [`STAGE_6_FRAUD_ANOMALY_DETECTION.md`](docs/stages/STAGE_6_FRAUD_ANOMALY_DETECTION.md) | [`STAGE_7_MULTI_AGENT_ORCHESTRATOR.md`](docs/stages/STAGE_7_MULTI_AGENT_ORCHESTRATOR.md) | [`STAGE_8_DECISION_REASONING.md`](docs/stages/STAGE_8_DECISION_REASONING.md)
- [`STAGE_5_STREAMLIT_APPLICATION.md`](docs/stages/STAGE_5_STREAMLIT_APPLICATION.md) | [`STAGE_6_HUMAN_REVIEW_AUDIT.md`](docs/stages/STAGE_6_HUMAN_REVIEW_AUDIT.md) | [`STAGE_7_BACKEND_AUTH_RBAC.md`](docs/stages/STAGE_7_BACKEND_AUTH_RBAC.md) | [`STAGE_8_PRODUCTION_READINESS.md`](docs/stages/STAGE_8_PRODUCTION_READINESS.md) | [`STAGE_9_DASHBOARD_AUDIT_TRAIL.md`](docs/stages/STAGE_9_DASHBOARD_AUDIT_TRAIL.md)
