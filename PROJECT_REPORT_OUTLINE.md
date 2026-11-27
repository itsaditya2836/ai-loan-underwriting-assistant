# Academic Project Report Outline — AI Loan Underwriting Assistant

**Purpose:** Structured blueprint mapping the implemented software, synthetic evaluations, diagrams, and limitations directly to standard undergraduate/graduate capstone report chapters.  
*(Strict academic integrity rule: Cite only verified repository metrics and standard foundational literature reviewed in your course/bibliography; never claim real-world banking accuracy or fabricate references.)*

---

## Chapter-by-Chapter Outline & Evidence Mapping

### 1. Abstract
- **Scope:** Concise 200–300 word summary of problem, deterministic multi-agent architecture, hybrid PDF/OCR extraction, ML credit risk model (`risk_model_rf_v2`), explainable fail-closed decision engine, HITL review/audit ledgers, and FastAPI RBAC backend.
- **Evidence to include:** Key headline synthetic benchmark summary (with clear synthetic dataset disclosure) and current readiness state (`READY FOR CONTROLLED TESTING`).

### 2. Introduction
- **Scope:** Context of consumer/personal loan origination delays, manual verification effort, compliance/explainability mandates in automated credit decisioning, and motivation for decision-support (rather than autonomous black-box lending).
- **Evidence to include:** High-level workflow contrast diagram (manual vs AI-assisted HITL review).

### 3. Problem Definition
- **Scope:** Formal statement of document inconsistency, incomplete applicant packets, heterogeneous scanned vs digital PDFs, opaque risk scoring, and lack of immutable human-override auditing.
- **Evidence to include:** Breakdown of the 4 core state dimensions separated by the system (`AI Recommendation`, `Pipeline Execution Status`, `Human Review Status`, `Final Human Decision`).

### 4. Existing System and Limitations
- **Scope:** Limitations of standalone credit-score cutoffs, siloed OCR scripts, or black-box LLM wrappers (hallucinations, non-determinism, absent audit provenance, and missing Maker-Checker separation).

### 5. Proposed System
- **Scope:** Overview of the 9-component modular Python platform featuring deterministic rule agents, supervised Random Forest risk estimation, cross-agent consistency checking, immutable audit storage, FastAPI JWT/RBAC service layer, and Streamlit workbench.
- **Evidence to include:** Summary feature table mapping requirements -> implemented modules.

### 6. Objectives and Scope
- **Scope:** Specific measurable engineering objectives (document classification/extraction, policy checks, anomaly detection, ML scoring, orchestrated execution, fail-closed safety, RBAC, append-only audit) and explicit boundaries (synthetic data, local execution, human final decision).

### 7. Literature Review Topics
- **Guidance on verified topics to survey in your academic bibliography:**
  - Rule-based expert systems and hybrid neuro-symbolic decision support in credit scoring.
  - Ensemble tree methods (`RandomForestClassifier`) and handling missing financial features without data leakage.
  - Optical Character Recognition (Tesseract LSTM OEM 3, binarization/orientation preprocessing) for mixed digital/raster financial PDFs.
  - Explainable AI (XAI) factor attribution and auditability in financial regulation / HITL governance.
  - Modern API security: Argon2id password hashing, JWT rotation/reuse detection, RBAC, and Maker-Checker controls.

### 8. System Requirements
- **Scope:** Hardware/OS specs, Python 3.11+ runtime (`3.14.6` tested), Tesseract OCR binary, library dependencies (`requirements.txt`: Streamlit, FastAPI, Pydantic v2, scikit-learn, PyMuPDF, pytesseract, SQLAlchemy, Alembic, argon2-cffi, python-jose), and security/non-functional requirements.

### 9. Architecture and Design
- **Evidence / Diagrams to include:**
  - Mermaid architecture diagram from [`PROJECT_ARCHITECTURE.md`](PROJECT_ARCHITECTURE.md).
  - Entity-Relationship / Schema summary (`users`, `refresh_tokens`, `login_attempts`, `submitted_applications`, `underwriting_runs`, `human_review_events`) showing explicit foreign keys and unique constraints ([`app/auth/models.py`](app/auth/models.py), [`app/database/schema.py`](app/database/schema.py)).
  - Review Lifecycle state-machine diagram (`PENDING` -> `IN_REVIEW` / `ADDITIONAL_INFO_REQUESTED` / `INVESTIGATION_REQUIRED` -> terminal `APPROVED` / `REJECTED` + supervisor-linked `is_correction`).

### 10. Data Collection and Synthetic Dataset Generation
- **Evidence to include:**
  - Description of [`scripts/generate_synthetic_dataset.py`](scripts/generate_synthetic_dataset.py) and [`scripts/generate_documents.py`](scripts/generate_documents.py) (seed `42`, `N=100` structured profiles, `30` PDF packages / `115` files across `6` controlled cohorts).
  - Profile target distribution (`LOW_RISK: 30`, `MEDIUM_RISK: 30`, `HIGH_RISK: 20`, `BORDERLINE: 20`), watermark notices, zero real PII, and schema rules verified by [`scripts/validate_dataset.py`](scripts/validate_dataset.py).

### 11. Methodology
- **Scope:** Modular dependency-ordered execution DAG inside [`UnderwritingOrchestrator`](app/orchestration/orchestrator.py), [`EligibilityPolicy`](app/eligibility/policy.py) thresholds (`Credit Score >= 650`, `DTI <= 60%`, `Min Income INR 30,000`), and [`check_cross_agent_consistency()`](app/orchestration/consistency.py).
- **Evidence to include:** End-to-end sequence diagram + list of Stage 6 cross-document consistency rules (`ANOM-ID-001`, `ANOM-INC-001`, `ANOM-FIN-001`, `ANOM-FIN-002`, `ANOM-DOC-001`).

### 12. Document Intelligence and OCR
- **Evidence to include:**
  - Page-level hybrid routing flowchart (`PDFReader` -> `native_text` vs Pillow preprocessing + `OCRProcessor` Tesseract 300 DPI).
  - Security validation pipeline (`validate_pdf_file`: 25 MB / 100-page caps, `%PDF-` signature, passive active-content marker detection, PII masking).
  - Screenshot (`docs/screenshots/05_document_review.png`).

### 13. Machine-Learning Risk Assessment
- **Evidence to include:**
  - [`RiskFeatureContract`](app/risk/feature_contract.py) (`15` ordered features, zero-preservation, `gender` exclusion).
  - Disjoint 80/20 stratified split training pipeline ([`scripts/train_risk_model.py`](scripts/train_risk_model.py)), `SimpleImputer(strategy="median") + RandomForestClassifier` serialized as [`models/risk_model.joblib`](models/risk_model.joblib) with fail-fast metadata checks.

### 14. Multi-Agent Orchestration
- **Scope:** Agent fault isolation, `AgentExecutionStatus` timing/provenance capture, `PARTIAL_SUCCESS` vs `FAILED` states, and non-fabrication guarantees (`unavailable != 0.0`).

### 15. Decision Engine
- **Scope:** 7-tier strict rule precedence in [`app/decision/rules.py`](app/decision/rules.py), standardized reason codes (`DEC-ELIG-001`, `DEC-DOC-001`, `DEC-ANOM-001`, `DEC-RISK-001`/`002`/`004`, `DEC-CON-001`, `DEC-APP-001`), heuristic evidence-agreement confidence score, and mandatory `human_review_required = True`.

### 16. Human Review, Security & Audit Trail
- **Evidence to include:**
  - FastAPI RBAC permission table (`ADMINISTRATOR`, `LOAN_OFFICER`, `UNDERWRITER`, `SUPERVISOR`) + Maker-Checker sequence (`POST /api/v1/reviews/submit` rejecting client `reviewer_id` and self-review).
  - SQLite append-only schema + `BEGIN IMMEDIATE` optimistic concurrency + trigger protections ([`docs/stages/STAGE_8_PRODUCTION_READINESS.md`](docs/stages/STAGE_8_PRODUCTION_READINESS.md)).
  - Screenshots (`docs/screenshots/01_login_screen.png`, `07_review_queue.png`, `08_human_review_decision.png`, `09_audit_history.png`).

### 17. Implementation Details
- **Scope:** Module organization, Pydantic v2 schema contracts (`app/schemas/`), Alembic migrations (`0001`, `0002`), and UI state transitions (`app/ui/state.py`).

### 18. Testing and Evaluation
- **Evidence to include (actual verified suite outputs):**
  - Automated `pytest` suite (`300 passed`), `ruff check .`, and `black --check .`.
  - Dataset validator (`100/100` rows, `100/100` feature parity), OCR/extraction benchmark, anomaly cohort script, eligibility benchmark, ML risk evaluation (`N=20` held-out test vs `RiskScorer` baseline), and end-to-end safety probe results.

### 19. Results and Discussion
- **Exact verified repository metrics to tabulate (explicitly labeled synthetic):**
  - Stage 3 Document Intelligence (`N=30` packages / `115` PDFs): `100.0%` classification accuracy (`115/115`), `100.0%` missing-doc set match (`30/30`), `4/4` scanned OCR detections, `30/30` on 4 ground-truth fields, `1,525` valid fields.
  - Stage 6 Synthetic Anomaly Cohort (`N=30`): `100.0%` accuracy / `1.0000` macro-F1 (`15` TP, `15` TN, `0` FP, `0` FN); `5/5` missing-doc packages flagged strictly as incomplete evidence (`has_anomalies=False`).
  - Stage 5 ML Risk Model (`N=100` synthetic: `80` train / `20` held-out test): 5-fold CV accuracy `96.25% +/- 3.06%`; held-out accuracy `95.00%` (`19/20`), macro-F1 `0.9365` vs weighted baseline `RiskScorer` (`60.00%` accuracy, `0.5655` macro-F1).
  - Stage 4 End-to-End Cohort (`APP0001`–`APP0030`): `30/30` `SUCCESS` and deterministic on repeat runs (`4 APPROVE`, `8 REJECT`, `18 MANUAL_REVIEW`), `4/4` simulated failure/conflict probes routed safely to `MANUAL_REVIEW`.
  - UI screenshots (`docs/screenshots/02_dashboard.png`, `06_underwriting_results.png`).

### 20. Limitations
- **Scope:** Small synthetic cohort (`N=100` / `30` PDF templates), heuristic classification/decision confidence (not calibrated default probabilities), SQLite raw queries blocking live PostgreSQL cutover (`PostgreSQL runtime NOT RUN`), local sandbox integration adapters, and no distributed Redis throttling.

### 21. Future Scope
- **Scope:** Converting `app/database/{applications,audit,reviews}.py` to SQLAlchemy Core + running live PostgreSQL integration tests, migrating `python-jose` -> `PyJWT`, empirical bank dataset recalibration & fairness audits, MFA/SSO password recovery, and external KYC/bureau API integration.

### 22. Conclusion
- **Scope:** Summary of how modular deterministic engineering, fail-closed safety guarantees, explainable ML, RBAC/Maker-Checker controls, and HITL governance deliver an auditable prototype ready for controlled testing.

### 23. References
- **Instruction:** Cite only primary technical specifications and peer-reviewed texts directly verified by the project author (e.g., official documentation for FastAPI, Pydantic v2, scikit-learn, PyMuPDF, Tesseract OCR, Argon2 / RFC 9106, JWT / RFC 7519, Alembic, and SQLite/PostgreSQL docs). Do **not** insert unverified citations.
