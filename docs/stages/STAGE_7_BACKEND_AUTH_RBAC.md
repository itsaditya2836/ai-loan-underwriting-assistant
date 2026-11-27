# STAGE 7 — BACKEND ARCHITECTURE, AUTHENTICATION, RBAC & EXTERNAL INTEGRATIONS

**Project:** AI Loan Underwriting Assistant  
**Stage:** Stage 7 — Backend Architecture, Authentication, RBAC & External Integrations  
**Status:** **COMPLETE**

---

## 1. Architecture Overview

Stage 7 introduces a FastAPI service layer, Argon2id/JWT authentication, Role-Based Access Control (RBAC), Maker-Checker enforcement, SQLAlchemy/Alembic database migration foundations for PostgreSQL readiness, optional Streamlit session authentication, and pluggable external integration interfaces while preserving all Stage 1–6 multi-agent underwriting and append-only audit invariants:

- **FastAPI Backend Layer** ([`app/api/main.py`](../../app/api/main.py)): Versioned `/api/v1` REST API delegating strictly to existing orchestration, review, application, and audit services without duplicating business logic.
- **Authentication & Cryptography** ([`app/auth/`](../../app/auth/)): Argon2id password hashing ([`app/auth/security.py`](../../app/auth/security.py)), short-lived HS256 JWT access tokens with unique `jti` claims, rotating/revocable hashed refresh tokens, account lockout, and sliding-window login rate limiting ([`app/auth/service.py`](../../app/auth/service.py)).
- **RBAC & Maker-Checker** ([`app/auth/permissions.py`](../../app/auth/permissions.py)): Backend permission matrix (`Permission`, `ROLE_PERMISSIONS`) enforced via `require_permission` / `require_any_permission` ([`app/api/dependencies.py`](../../app/api/dependencies.py)) plus server-side Maker-Checker checks (`enforce_not_self_review`, `enforce_correction_requires_supervisor`).
- **Database & Migrations** ([`app/database/engine.py`](../../app/database/engine.py), [`app/database/schema.py`](../../app/database/schema.py), [`alembic/`](../../alembic/)): Shared SQLAlchemy engine with PostgreSQL connection pooling options, explicit foreign keys/indexes/unique constraints, optimistic concurrency protection on human reviews, Alembic migration scripts, and a non-destructive data copy utility ([`app/database/migration.py`](../../app/database/migration.py), [`scripts/migrate_sqlite_to_postgres.py`](../../scripts/migrate_sqlite_to_postgres.py)).
- **External Integration Foundations** ([`app/integrations/`](../../app/integrations/)): Protocol/ABC adapters for credit bureau, KYC verification, LLM reasoning, and audit webhooks with sandboxed local defaults (`IntegrationRegistry`).

---

## 2. Versioned API Endpoints (`/api/v1`)

| Domain | Method & Path | Permission / Access | Purpose |
| :--- | :--- | :--- | :--- |
| Health | `GET /api/v1/health` | Public | API readiness check |
| Auth | `POST /api/v1/auth/login` | Public (rate-limited) | Verify credentials, issue JWT pair |
| Auth | `POST /api/v1/auth/refresh` | Valid Refresh Token | Rotate refresh token & issue new JWT pair |
| Auth | `POST /api/v1/auth/logout` | Authenticated | Revoke user's active refresh tokens |
| Auth | `GET /api/v1/auth/me` | Authenticated | Return current user's public profile |
| Users | `GET /api/v1/users` | `USER_VIEW` | List user accounts (Admin only) |
| Users | `POST /api/v1/users` | `USER_CREATE` | Provision user account & assign role |
| Users | `GET /api/v1/users/{user_id}` | `USER_VIEW` | Inspect single user public profile |
| Users | `PATCH /api/v1/users/{user_id}` | `USER_UPDATE` | Update user profile, role, active or lock state |
| Users | `DELETE /api/v1/users/{user_id}` | `USER_DEACTIVATE` | Soft-deactivate user (self-deactivation blocked) |
| Applicants | `GET /api/v1/applicants` | `APPLICANT_VIEW_OWN` / `ALL` | List permitted submitted + synthetic applicants |
| Applicants | `GET /api/v1/applicants/{id}` | `APPLICANT_VIEW_OWN` / `ALL` | Retrieve permitted applicant record |
| Applicants | `POST /api/v1/applicants` | `APPLICANT_CREATE` | Register submitted applicant with owner attribution |
| Documents | `POST /api/v1/applicants/{id}/documents` | `DOCUMENT_UPLOAD` | Upload & Stage-3 validate PDFs (path-traversal safe) |
| Documents | `GET /api/v1/applicants/{id}/documents` | `DOCUMENT_VIEW` | List applicant PDFs |
| Underwriting | `POST /api/v1/underwriting/{id}/run` | `UNDERWRITING_INITIATE` | Execute multi-agent pipeline + persist audit run |
| Underwriting | `GET /api/v1/underwriting/{run_id}` | `UNDERWRITING_VIEW_RESULTS` | Retrieve run result (owner-scoped for Loan Officers) |
| Underwriting | `GET /api/v1/underwriting/{run_id}/status` | `UNDERWRITING_VIEW_RESULTS` | Retrieve run pipeline/recommendation status |
| Reviews | `GET /api/v1/reviews/queue` | `REVIEW_VIEW_ASSIGNED` / `ALL` | Filterable human review queue + metrics |
| Reviews | `GET /api/v1/reviews/case/{id}` | `REVIEW_VIEW_*` / `AUDIT_VIEW_ALL` | Separated AI vs human case summary |
| Reviews | `POST /api/v1/reviews/submit` | `REVIEW_*` + Maker-Checker | Append human decision using token identity |
| Reviews | `GET /api/v1/reviews/history/{run_id}` | `REVIEW_VIEW_*` / `AUDIT_VIEW_ALL` | Append-only review timeline for run |
| Audit | `GET /api/v1/audit/runs` | `AUDIT_VIEW_OWN` / `ALL` | Filtered AI execution audit log |
| Audit | `GET /api/v1/audit/runs/{run_id}` | `AUDIT_VIEW_OWN` / `ALL` | Inspect detailed AI audit run snapshot |
| Audit | `GET /api/v1/audit/reviews` | `AUDIT_VIEW_ALL` / Underwriter | Filtered human review events (Underwriters scoped to own) |
| Audit | `GET /api/v1/audit/summary` | `AUDIT_VIEW_ALL` | Portfolio analytics summary (Admin/Supervisor) |
| Audit | `GET /api/v1/audit/trends` | `AUDIT_VIEW_ALL` | Daily underwriting run trends (Admin/Supervisor) |
| Integrations | `GET /api/v1/integrations/status` | `SETTINGS_VIEW` | Health/readiness status of external adapters |

---

## 3. Role-Based Access Control (RBAC) & Maker-Checker Matrix

| Capability | `ADMINISTRATOR` | `LOAN_OFFICER` | `UNDERWRITER` | `SUPERVISOR` |
| :--- | :---: | :---: | :---: | :---: |
| User CRUD / Role assignment (`USER_*`, `ROLE_ASSIGN`) | Yes | No | No | No |
| Register applicants (`APPLICANT_CREATE`) | Yes | Yes | No | No |
| View applicants (`APPLICANT_VIEW_*`) | All | Own (+ Synthetic) | All | All |
| Upload PDFs / Run underwriting | Yes | Yes (Own) | No | No |
| View Review Queue (`REVIEW_VIEW_*`) | All | No | Open Cases | All |
| Submit review decisions / Request info / Investigate | Yes | No | Yes | Yes |
| Linked decision corrections (`REVIEW_CORRECT_DECISION`) | Yes | No | **No** | Yes |
| Audit history & analytics (`AUDIT_VIEW_*`) | All | Own Runs | Own Reviews + Runs | All |
| System settings & integrations (`SETTINGS_*`) | Yes | No | No | No |

### Maker-Checker & Attribution Guarantees

1. **Authoritative Identity Injection**: `ReviewSubmissionRequest` enforces `ConfigDict(extra="forbid")` so client-supplied `reviewer_id` / `reviewer_user_id` fields are rejected with `422`. Authoritative identity (`reviewer_user_id`, `reviewer_username`, `reviewer_role`) is injected exclusively from the verified JWT/session user.
2. **Self-Review & Self-Approval Prevention**: Both `submitted_applications.submitted_by_user_id` and `underwriting_runs.initiated_by_user_id` are tracked on intake/execution. A user is blocked (`403 Forbidden`) from reviewing or approving any application or underwriting run they submitted or initiated.
3. **Supervisor-Only Corrections**: Linked corrections (`is_correction=True`) after terminal human decisions enforce `Permission.REVIEW_CORRECT_DECISION` server-side (`SUPERVISOR` or `ADMINISTRATOR`).
4. **Backward Compatibility**: Historical Stage 6 rows keep `reviewer_id` intact with nullable `reviewer_user_id`, `reviewer_username`, and `reviewer_role` (`NULL` for legacy events).

---

## 4. Database Architecture, Concurrency & Migration Strategy

- **SQLite + PostgreSQL Engine Abstraction** ([`app/database/engine.py`](../../app/database/engine.py)): Uses `DATABASE_URL` via `config/settings.py`. SQLite enables `check_same_thread=False` and `PRAGMA foreign_keys=ON`; PostgreSQL URLs configure `pool_size`, `max_overflow`, `pool_timeout`, `pool_pre_ping=True`, and `pool_recycle=1800`. *(PostgreSQL runtime requires installing a PostgreSQL DBAPI driver such as `psycopg2-binary` or `psycopg`; local testing verified SQLite execution.)*
- **Explicit FKs, Unique Constraints & Indexes** ([`app/auth/models.py`](../../app/auth/models.py), [`app/database/schema.py`](../../app/database/schema.py)):
  - `refresh_tokens.user_id -> users.user_id` (`ON DELETE CASCADE`), `users.username` & `users.email` unique, `refresh_tokens.token_hash` unique.
  - `human_review_events.source_run_id -> underwriting_runs.run_id` (`ON DELETE RESTRICT`), `human_review_events.submission_hash` unique.
- **Optimistic Concurrency & Safe Concurrent Review Writes**:
  - API submissions and Streamlit UI pass `expected_previous_status`, returning `409 Conflict` if review status changed concurrently.
  - [`insert_human_review_event()`](../../app/database/reviews.py) acquires a SQLite `BEGIN IMMEDIATE` write lock and re-verifies inside the transaction that the latest `new_review_status` still equals `previous_review_status`, raising `ConcurrentReviewConflictError` if another writer committed first.
- **Non-Destructive Alembic & Data Migration**:
  - [`alembic/versions/0001_stage7_initial_schema.py`](../../alembic/versions/0001_stage7_initial_schema.py) creates new auth tables idempotently and inspects existing tables to apply additive nullable attribution columns without altering or discarding historical underwriting runs or human reviews.
  - [`scripts/migrate_sqlite_to_postgres.py`](../../scripts/migrate_sqlite_to_postgres.py) / [`migrate_database_data()`](../../app/database/migration.py) reads source SQLite tables safely (handling pre-Stage-7 schemas via table reflection) and inserts missing primary keys into the target DB in FK order without mutating the source DB.

---

## 5. Secrets & Configuration Notes

- **Never use default secrets in production**: Override `JWT_SECRET_KEY` and `DEFAULT_ADMIN_PASSWORD` via environment variables / `.env` (`.env` is gitignored).
- `APP_ENV != "development"` disables FastAPI Swagger/ReDoc docs (`/api/docs`, `/api/redoc`) and restricts permissive wildcard CORS.
- `STREAMLIT_AUTH_REQUIRED` defaults to `false` so local development and existing Stage 5/6 Streamlit tests launch directly; when set to `true` (or when an operator signs in via the sidebar `Access & Identity` panel), Streamlit verifies sessions against `AuthService`, enforces RBAC & Maker-Checker checks, and populates authenticated reviewer attribution automatically.

---

## 6. External Integration Foundations (`app/integrations/`)

- **Credit Bureau** (`CreditBureauProvider` / `LocalSyntheticCreditBureauAdapter`)
- **KYC Verification** (`KYCVerificationProvider` / `LocalSyntheticKYCAdapter`)
- **LLM Narrative Reasoning** (`LLMReasoningProvider` / `DisabledLocalLLMProvider`)
- **Audit Webhooks** (`AuditWebhookPublisher` / `NoOpWebhookPublisher`)

All default adapters operate strictly locally in sandbox/disabled mode with zero outbound network requests or hardcoded credentials. Readiness is inspectable by Administrators via `GET /api/v1/integrations/status`.
