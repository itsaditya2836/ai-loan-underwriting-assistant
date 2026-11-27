# STAGE 8 — PRODUCTION READINESS, SECURITY HARDENING & FINAL VALIDATION

**Project:** AI Loan Underwriting Assistant  
**Stage:** Stage 8 — Production Readiness, Security Hardening & Final Validation  
**Readiness Classification:** **`READY FOR CONTROLLED TESTING`**

---

## 1. Executive Summary

Stage 8 audited the end-to-end underwriting system (Stages 1–7) across authentication, authorization, API hardening, database concurrency/migrations, Streamlit access boundaries, external integration stubs, and ML/document safety. Confirmed security and configuration defects were fixed directly in the codebase and verified with automated regression tests.

### Verification Boundary Summary

- **Verified locally (SQLite + in-process / local HTTP):** Full 300-test `pytest` suite (`300 passed`), `ruff check .`, `black --check .`, Alembic `0001_stage7_initial` -> `0002_stage8_hardening` SQLite migrations, SQLite append-only audit triggers and foreign-key enforcement, FastAPI `/api/v1` endpoints, RBAC + Maker-Checker flows, Streamlit AppTest & headless health check, CLI startup check, and all 5 synthetic dataset/ML/pipeline evaluation scripts.
- **Verified against PostgreSQL:** Offline SQLAlchemy/Alembic DDL generation (`alembic upgrade head --sql` targeting `postgresql+psycopg://...`) compiling valid `CREATE TABLE` statements for all tables (`users`, `refresh_tokens`, `login_attempts`, `submitted_applications`, `underwriting_runs`, `human_review_events`) and SQLAlchemy PostgreSQL engine pooling configuration unit check (`_build_engine_kwargs`).
- **Not verified (PostgreSQL runtime):** Live PostgreSQL runtime execution, runtime FK/concurrency tests on Postgres, and live SQLite-to-PostgreSQL data migration runtime were **NOT RUN** (no running PostgreSQL server on `/tmp:5432`, no `psycopg`/`psycopg2` Python driver installed in `.venv`, and legacy Stage 4–6 modules in `app/database/` still execute SQLite-specific SQL).
- **Requires external infrastructure or provider credentials:** Live PostgreSQL HA/TLS database service, distributed Redis/API-gateway rate limiting across multiple API workers, production TLS reverse proxy, Secrets Manager injection for `JWT_SECRET_KEY`, and genuine external Credit Bureau, KYC, LLM, or webhook providers.

---

## 2. Architecture Overview

- **Multi-Agent Underwriting Pipeline** ([`app/orchestration/orchestrator.py`](../../app/orchestration/orchestrator.py)): Deterministic sequential orchestration (`DocumentIntakeAgent` -> `EligibilityAgent` -> `FraudAnomalyAgent` -> `RiskAgent` -> cross-agent consistency checks -> `DecisionReasoningAgent`) with fail-closed `MANUAL_REVIEW` routing on missing documents, unavailable risk/fraud outputs, or cross-agent conflicts.
- **FastAPI Backend** ([`app/api/main.py`](../../app/api/main.py)): Versioned REST layer under `/api/v1` delegating strictly to backend orchestration, review, application, audit, and auth services.
- **Streamlit Workbench** ([`app/ui/dashboard.py`](../../app/ui/dashboard.py)): 8-page local interactive UI with optional sidebar RBAC authentication in dev/test and mandatory sign-in + fail-closed secret verification when `APP_ENV=production`.
- **Persistence Layer** ([`app/database/`](../../app/database/), [`alembic/`](../../alembic/)): SQLAlchemy Core models (`auth_metadata`, `app_metadata`) + Alembic migrations (`0001`, `0002`), paired with existing SQLite transaction modules protected by `PRAGMA foreign_keys = ON`, `BEGIN IMMEDIATE` review serialization locks, and SQLite append-only triggers.
- **External Integrations** ([`app/integrations/`](../../app/integrations/)): Abstract provider interfaces with local `SANDBOX` / `DISABLED` adapters returning explicit non-verified states (`success=False`, `sandboxed=True`).

---

## 3. Security Controls Implemented (Risk Register & Remediations)

| Finding | Severity | Affected Files | Classification | Remediation Implemented & Verified |
| :--- | :--- | :--- | :--- | :--- |
| Unsafe dev `JWT_SECRET_KEY` / default admin accepted in `production`; dev `admin` auto-seeded unconditionally | **Critical** | [`config/settings.py`](../../config/settings.py), [`app/api/main.py`](../../app/api/main.py), [`app/auth/service.py`](../../app/auth/service.py), [`app/ui/dashboard.py`](../../app/ui/dashboard.py) | Vulnerability | Added `Settings.validate_production_security()` failing closed on startup if `JWT_SECRET_KEY` matches dev default or `< 32` chars, default admin password unchanged, or wildcard `*` CORS in production. Disabled automatic default admin seeding when `is_production()` is True. |
| Missing refresh-token reuse detection; access tokens stayed valid after logout/role change; missing `iss`/`aud` claims & DB `expires_at` enforcement | **High** | [`app/auth/models.py`](../../app/auth/models.py), [`app/auth/security.py`](../../app/auth/security.py), [`app/auth/service.py`](../../app/auth/service.py), [`alembic/versions/0002_stage8_hardening.py`](../../alembic/versions/0002_stage8_hardening.py) | Vulnerability | Added `users.token_version` (incremented on logout, deactivation, lock, or role change) verified on every `get_current_user()` / `refresh()`. Added single-use refresh reuse detection revoking full user session family when a revoked token is replayed; added DB `expires_at`, `iss`, `aud`, `iat`, `nbf`, and `ALLOWED_JWT_ALGORITHMS` enforcement. |
| Timing side-channel & account lock enumeration on login; missing per-IP brute-force limit | **High** | [`app/auth/service.py`](../../app/auth/service.py), [`app/auth/security.py`](../../app/auth/security.py) | Vulnerability | Performed constant-time `DUMMY_PASSWORD_HASH` Argon2id verification on missing/inactive/locked accounts and standardized failed login responses to `"Invalid credentials."`; added per-IP sliding-window limit in `_is_rate_limited()`. |
| CORS wildcard (`*`) paired with `allow_credentials=True`; raw exception strings leaked in HTTP `500`/`400`; missing security headers & upload batch bounds | **High** | [`app/api/main.py`](../../app/api/main.py), [`app/api/routes/applicants.py`](../../app/api/routes/applicants.py), [`app/api/routes/underwriting.py`](../../app/api/routes/underwriting.py), [`app/api/routes/documents.py`](../../app/api/routes/documents.py) | Vulnerability | Replaced wildcard CORS with `get_cors_origins()` (`cors_allowed_origins` env var), disabled OpenAPI docs outside `development`, added `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Cache-Control: no-store` headers, sanitized error messages on `/applicants` and `/underwriting`, and enforced `MAX_FILES_PER_UPLOAD = 10` alongside path-traversal & `%PDF-` checks. |
| Admin self-demotion/deactivation via `PATCH /users/{id}` and unvalidated username/email characters | **Medium** | [`app/api/routes/users.py`](../../app/api/routes/users.py), [`app/auth/models.py`](../../app/auth/models.py) | Vulnerability | Blocked self-deactivation/self-role-change on `PATCH /api/v1/users/{id}` and validated `UserCreate.username` (`^[A-Za-z0-9._-]{3,64}$`) and email format. |
| Raw SQLite connector silently handled non-SQLite URLs as local filenames; audit ledger relied solely on app omission of `UPDATE`/`DELETE` | **Medium** | [`app/database/db.py`](../../app/database/db.py), [`app/database/audit.py`](../../app/database/audit.py), [`app/database/reviews.py`](../../app/database/reviews.py) | Limitation / Hardening | `get_database_connection()` now fails fast on non-SQLite `DATABASE_URL` and sets `PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 5000;`. Added SQLite `BEFORE UPDATE` and `BEFORE DELETE` abort triggers on `underwriting_runs` and `human_review_events`. |
| Streamlit `APP_ENV=production` allowed unauthenticated access unless `STREAMLIT_AUTH_REQUIRED=true` was set separately; stale UI Stage 7 caption | **Medium** | [`app/ui/dashboard.py`](../../app/ui/dashboard.py), [`app/ui/state.py`](../../app/ui/state.py), [`app/ui/components.py`](../../app/ui/components.py), [`app/ui/views_portfolio.py`](../../app/ui/views_portfolio.py) | Vulnerability / Improvement | Enforced `is_streamlit_auth_enforced()` whenever `APP_ENV=production`, cleared both access & refresh tokens on auth errors, enforced RBAC on Dashboard sample-seed action, and corrected attribution caption. |
| `python-jose` (`3.5.0`) + `ecdsa` (`0.19.2`) legacy package risk | **Low/Medium** | [`requirements.txt`](../../requirements.txt), [`app/auth/security.py`](../../app/auth/security.py) | Known Dependency Limitation | Mitigated asymmetric algorithm/ECDSA exposure by strictly pinning `ALLOWED_JWT_ALGORITHMS = {"HS256", "HS384", "HS512"}` in both settings validation and `jwt.decode`. Migrating to `PyJWT` is a recommended future cleanup. |

---

## 4. Role-Permission Matrix

| Endpoint / Capability | Unauthenticated | `ADMINISTRATOR` | `LOAN_OFFICER` | `UNDERWRITER` | `SUPERVISOR` |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `GET /api/v1/health` | `200` | `200` | `200` | `200` | `200` |
| `GET/POST/PATCH/DELETE /api/v1/users*` | `401` | `200`/`201`/`204` | `403` | `403` | `403` |
| `GET /api/v1/integrations/status` | `401` | `200` | `403` | `403` | `403` |
| `GET /api/v1/applicants` | `401` | All (`200`) | Own + Synthetic (`200`) | All (`200`) | All (`200`) |
| `POST /api/v1/applicants` | `401` | `201` | `201` | `403` | `403` |
| `POST /api/v1/applicants/{id}/documents` | `401` | `201` | Own (`201`) / Other (`403`) | `403` | `403` |
| `POST /api/v1/underwriting/{id}/run` | `401` | `201` | Own + Synthetic (`201`) | `403` | `403` |
| `GET /api/v1/underwriting/{run_id}` | `401` | `200` | Own (`200`) / Other (`403`) | `200` | `200` |
| `GET /api/v1/reviews/queue` | `401` | All (`200`) | `403` | Open Cases (`200`) | All (`200`) |
| `POST /api/v1/reviews/submit` (standard actions) | `401` | Not Own (`200`) | `403` | Not Own (`200`) | Not Own (`200`) |
| `POST /api/v1/reviews/submit` (`is_correction=true`) | `401` | Not Own (`200`) | `403` | `403` | Not Own (`200`) |
| `POST /api/v1/reviews/submit` (self-submitted/run) | `401` | `403` | `403` | `403` | `403` |
| `GET /api/v1/audit/runs` | `401` | All (`200`) | Own Runs (`200`) | All (`200`) | All (`200`) |
| `GET /api/v1/audit/reviews` | `401` | All (`200`) | `403` | Own Reviews (`200`) | All (`200`) |
| `GET /api/v1/audit/summary` & `/trends` | `401` | `200` | `403` | `403` | `200` |

*Note on Audit Immutability:* SQLite enforces `BEFORE UPDATE` and `BEFORE DELETE` abort triggers (`trg_underwriting_runs_no_*`, `trg_human_reviews_no_*`) alongside append-only SQL in application code. However, OS administrators or DBAs with direct filesystem or superuser access can always drop triggers or alter database files; this is application/DB-trigger protection, **not** cryptographic WORM/tamper-proof storage.

---

## 5. Database and Migration Status

- **SQLite Operational Status (Verified):** `PRAGMA foreign_keys = ON` and `PRAGMA busy_timeout = 5000` active; atomic `BEGIN IMMEDIATE` serialization prevents concurrent review write races (`ConcurrentReviewConflictError` -> HTTP `409`); Alembic `0001_stage7_initial` and `0002_stage8_hardening` upgrade cleanly on both fresh and pre-Stage-7 databases without modifying or dropping historical rows; SQLite-to-SQLite data copy verified idempotent via `migrate_database_data()`.
- **PostgreSQL Schema vs Runtime Status:** SQLAlchemy table definitions ([`app/database/schema.py`](../../app/database/schema.py), [`app/auth/models.py`](../../app/auth/models.py)) and Alembic migrations compile cleanly for PostgreSQL (`alembic upgrade head --sql`), and `AuthService` uses SQLAlchemy Core (`users`, `refresh_tokens`, `login_attempts`) cleanly. **However**, [`app/database/applications.py`](../../app/database/applications.py), [`app/database/audit.py`](../../app/database/audit.py), and [`app/database/reviews.py`](../../app/database/reviews.py) still execute SQLite-specific raw SQL via `get_database_connection()` (which raises `RuntimeError` if configured for non-SQLite). Full SQLAlchemy conversion of those 3 modules + live PostgreSQL integration tests remain mandatory before running against PostgreSQL in staging/production.
- **Original Database Integrity:** Verified `loan_underwriting.db` remained completely unmodified before and after all tests/validations (`SHA-256: c0c4cb6fa86ddce835f299e9fc0ba4e400059719ca7b96fa4aa791a37817a14d`).

---

## 6. Environment-Variable Reference

See [`.env.example`](../../.env.example) (local dev) and [`.env.production.example`](../../.env.production.example) (production template without real secrets):

| Variable | Description | Dev Default | Production Requirement |
| :--- | :--- | :--- | :--- |
| `APP_ENV` | Runtime mode (`development`, `test`, `production`) | `development` | Set to `production` (disables Swagger/CORS `*`/dev seed; enables fail-closed checks) |
| `DATABASE_URL` | SQLAlchemy / SQLite URI | `sqlite:///./loan_underwriting.db` | Set via secrets manager (PostgreSQL requires SQLAlchemy port + `psycopg`) |
| `JWT_SECRET_KEY` | HMAC signing secret | `DEV-ONLY-...` | **Mandatory** 32+ char random secret (refused otherwise) |
| `JWT_ALGORITHM` | Signing algorithm | `HS256` | Restricted to `HS256`, `HS384`, `HS512` |
| `JWT_ISSUER` / `JWT_AUDIENCE` | JWT `iss` and `aud` validation claims | `ai-loan-underwriting-assistant` / `underwriting-api` | Set environment-specific issuer/audience |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Short-lived access token TTL | `30` | Recommended `15`–`30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Rotating refresh token TTL | `7` | Recommended `1`–`7` |
| `LOGIN_RATE_LIMIT_MAX_ATTEMPTS` | Failed logins before sliding-window lockout | `5` | Adjust per policy |
| `LOGIN_RATE_LIMIT_WINDOW_MINUTES` | Rate-limit sliding window (minutes) | `15` | Adjust per policy |
| `MAX_FAILED_LOGIN_ATTEMPTS` | Failures before `users.is_locked = True` | `10` | Admin unlocks via `PATCH /api/v1/users/{id}` |
| `DEFAULT_ADMIN_PASSWORD` | Initial admin seed password (dev/test only) | `admin-dev-...` | **Must not equal dev default** in `production`; auto-seed is disabled in `production` |
| `STREAMLIT_AUTH_REQUIRED` | Force login on Streamlit UI | `false` | Automatically enforced when `APP_ENV=production` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated allowed browser origins | `http://localhost:8501,...` | Explicit `https://...` origins; `*` refused |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` | SQLAlchemy pooling for non-SQLite DBs | `5` / `10` / `30` | Tune per PostgreSQL capacity |
| `GEMINI_API_KEY` | Reserved LLM integration env var (currently disabled) | *(empty)* | Leave unset unless external LLM provider enabled later |

---

## 7. Local Development Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Run database migrations safely on local SQLite DB
.venv/bin/alembic upgrade head

# Start FastAPI backend (Swagger at http://127.0.0.1:8000/api/docs in development)
.venv/bin/uvicorn app.api.main:app --reload --port 8000

# Start Streamlit workbench
.venv/bin/streamlit run app/main.py
```

---

## 8. Production Deployment Configuration

Before deploying beyond controlled testing:
1. Convert `app/database/{applications,audit,reviews}.py` from `sqlite3` SQL to dialect-neutral SQLAlchemy Core and install `psycopg` (`psycopg[binary]`) / `psycopg2-binary`.
2. Start from [`.env.production.example`](../../.env.production.example), inject strong secrets via KMS/Vault/Secrets Manager (`JWT_SECRET_KEY`, `DATABASE_URL`, explicit `CORS_ALLOWED_ORIGINS`), and run behind TLS termination (Nginx/ALB).
3. Run Uvicorn/Gunicorn workers behind an API gateway/WAF enforcing distributed IP rate limiting (current rate limiting uses DB queries rather than in-memory dicts, so multi-worker deployments share DB state across processes, though SQLite write contention and distributed DDoS protection still require PostgreSQL + edge throttling).
4. Treat the FastAPI service (`app/api/main.py`)—never the Streamlit frontend alone—as the security boundary, or keep `APP_ENV=production` so Streamlit also enforces verified `AuthService` tokens.

---

## 9. Backup and Recovery Recommendations

- Enable automated point-in-time recovery (PITR) WAL archiving once deployed on managed PostgreSQL; for local/pilot SQLite, use `sqlite3 ... ".backup ..."` online consistent snapshots rather than plain `cp`.
- Back up database volumes and uploaded document directories (`data/documents/` / object storage) synchronously before every `alembic upgrade` release.
- Regularly test restore + `scripts/migrate_sqlite_to_postgres.py` idempotency against isolated staging copies, and never execute unverified schema changes against production storage.

---

## 10. Known Limitations and Unresolved Risks

1. **PostgreSQL Runtime Gap:** Stage 4–6 modules (`applications.py`, `audit.py`, `reviews.py`) use raw `sqlite3` SQL; runtime execution on PostgreSQL is blocked until converted to SQLAlchemy Core and tested against a live Postgres server.
2. **Legacy JWT Library (`python-jose`):** Retained cleanly with strict `ALLOWED_JWT_ALGORITHMS` enforcement (`HS256`/`HS384`/`HS512`); migrating to `PyJWT` is deferred to post-Stage 8 maintenance.
3. **Single-Host Rate Limit Contention on SQLite:** Per-username and per-IP failed attempts are recorded in SQL (`login_attempts`), avoiding process-local memory silos, but concurrent multi-worker writes against SQLite will contend under heavy brute-force load until PostgreSQL + Redis/WAF throttling is added.
4. **No Native Email/MFA Password Recovery:** Administrator unlocks locked accounts via `PATCH /api/v1/users/{id}`; self-service password reset / MFA is not implemented.
5. **External Providers & Financial Verification:** Credit bureau, KYC verification, LLM reasoning, and webhooks operate strictly in local `SANDBOX`/`DISABLED` mode without outbound connections.
6. **File-System Document Storage:** Uploaded PDFs persist locally under `data/documents/<applicant_id>/`; multi-node production requires shared encrypted object storage (e.g., S3 with KMS).

---

## 11. Test Results & Verification Checks (Exact Counts After Final Code Edit)

| Check / Command | Scope | Result |
| :--- | :--- | :--- |
| `DATABASE_URL="sqlite:////tmp/test_stage8_full.db" .venv/bin/pytest -q` | Complete suite (Stages 1–8) | **`300 passed in 20.19s`** (229 existing Stage 1–6 + 52 Stage 7 + 19 Stage 8 tests) |
| `.venv/bin/ruff check .` | Static lint across repository | **Passed** (`All checks passed!`) |
| `.venv/bin/black --check .` | Code formatting across repository | **Passed** (`133 files would be left unchanged`) |
| `scripts/validate_dataset.py` | 100 synthetic profiles, 30 PDF dirs, feature parity, ML artifact | **Passed** (`ALL DATASET, DOCUMENT, AND ML RELIABILITY CHECKS PASSED`, 1 non-blocking synthetic age plausibility notice on 3 profiles) |
| `scripts/evaluate_extraction.py` | Stage 3 PDF intake/OCR/classification/extraction | **Passed** (`115/115` docs classified; `30/30` exact missing-set; `4/4` OCR scans; `30/30` on 4 labeled fields; `1,525` valid fields; mixed-PDF PASS) |
| `scripts/evaluate_eligibility.py` | Deterministic policy evaluation (`N=30` pkgs & `N=100` profiles) | **Passed** (Pkgs: `18` Eligible / `8` Ineligible / `4` Review; Full: `72` Eligible / `28` Ineligible) |
| `scripts/evaluate_risk_model.py` | `risk_model_rf_v2` vs `RiskScorer` on `80/20` split | **Passed** (CV acc `96.25% +/- 3.06%`; held-out `N=20` acc `95.00%`, macro-F1 `0.9365` vs baseline `60.00%`) |
| `scripts/evaluate_end_to_end.py` | `N=30` doc cohort + `N=70` profile-only + 4 failure/conflict probes | **Passed** (`30/30` `SUCCESS` deterministic, `4 APPROVE` / `8 REJECT` / `18 MANUAL_REVIEW`; `70/70` no unsafe auto-approve; `4/4` probes safe `MANUAL_REVIEW`) |
| `app/main.py` CLI check | Configuration, logging, SQLite init | **Passed** (exit `0`) |
| `alembic -x db_url=sqlite:////tmp/test_st8_alembic.db upgrade head` | Fresh SQLite schema migration `0001` -> `0002` | **Passed** (exit `0`) |
| `uvicorn app.api.main:app` live server check | `GET /api/v1/health` | **Passed** (`200 {'status': 'ok', 'version': '1.0.0'}`) |
| `streamlit run app/main.py --server.headless true` | `GET /_stcore/health` | **Passed** (`200 ok`) |

---

## 12. PostgreSQL Validation Status

- **DDL Compilation Check (`test_alembic_postgresql_offline_ddl_compilation`):** **PASSED** (`alembic upgrade head --sql` targeting `postgresql+psycopg://...` emitted clean Postgres DDL for `users`, `refresh_tokens`, `login_attempts`, `submitted_applications`, `underwriting_runs`, `human_review_events`).
- **Live PostgreSQL Server Runtime, Integration Tests, Concurrency & Live Data Migration:** **`NOT RUN`** — No PostgreSQL DBAPI driver (`psycopg` / `psycopg2`) is installed in `.venv` and `pg_isready` reported no running Postgres instance (`/tmp:5432 - no response`). SQLite tests were **not** substituted as PostgreSQL runtime validation.

---

## 13. Synthetic-Data and Model-Performance Limitations

- All evaluation metrics (`100.0%` Stage 3 classification on 115 template PDFs; `95.0%` held-out ML risk accuracy on `N=20`) measure deterministic pipeline consistency on synthetic template fixtures (`N=100` applicants, `N=30` PDF packages), **not** empirical banking default, OCR accuracy on arbitrary third-party scanned forms, or real-world fraud rates.
- `gender` is strictly excluded from `RiskFeatureContract` (`15` features) and protected demographic fairness must be re-validated on empirical cohorts before production credit scoring.
- All automated outputs enforce `human_review_required = True` and act strictly as decision support to authorized underwriters.

---

## 14. Final Readiness Assessment

### Classification: **`READY FOR CONTROLLED TESTING`**

**Rationale:** Application-layer authentication, authorization, Maker-Checker isolation, fail-closed production startup guards, path-safe PDF validation, SQLite concurrency/trigger protections, and deterministic fail-closed AI underwriting safeguards are thoroughly implemented and pass all `300` local automated tests cleanly. However, live PostgreSQL runtime validation was `NOT RUN` (Stage 4–6 raw SQLite modules still require SQLAlchemy Core refactoring and live Postgres testing), external financial/identity providers are sandbox stubs only, and the ML model is trained on a small synthetic cohort. The system is therefore ready for controlled pilot/QA evaluation and UAT, **not** yet ready for unattended production or live PostgreSQL staging without completing those infrastructure prerequisites.
