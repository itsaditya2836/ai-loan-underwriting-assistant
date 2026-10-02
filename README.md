# AI Loan Underwriting Assistant: A Multi-Agent Agentic AI System for Faster Loan Processing

## Project Description

The **AI Loan Underwriting Assistant** is a multi-agent Agentic AI decision-support prototype designed for personal and home loans. The system assists loan officers and underwriters by streamlining the intake, analysis, and verification of loan applications:

- **Processing applicant documents**: Ingesting PDF files and scanned images (salary slips, bank statements, identification proofs).
- **Extracting relevant information**: Parsing unstructured documents and performing OCR to extract key applicant attributes.
- **Checking eligibility**: Evaluating applications against deterministic underwriting policies and debt-to-income limits.
- **Assessing repayment risk**: Scoring default risk using rule-based metrics and machine-learning models.
- **Detecting inconsistencies and anomalies**: Cross-verifying claims across multiple submitted documents to highlight fraud signals.
- **Generating explainable recommendations**: Synthesizing multi-agent findings into a structured proposal (`APPROVE`, `REJECT`, or `MANUAL_REVIEW`) with clear evidence trails.
- **Supporting human review**: Empowering loan officers with a dedicated review dashboard.
- **Maintaining an audit record**: Recording an immutable, timestamped trail of documents, extractions, findings, and human decisions.

> **Responsible AI & Human-in-the-Loop Notice:**  
> **This prototype provides decision support and does not replace authorized human underwriting decisions.**  
> The system acts strictly as an intelligent assistant. The human loan officer retains ultimate authority and responsibility for all loan approval or rejection decisions.

---

## Architecture

The system coordinates specialized autonomous agents in a structured, observable workflow:

```text
User
  ↓
Loan Application Documents
  ↓
Orchestrator Agent
  ↓
 ┌────────────────────────────────────────┐
 │                                        │
 │  Document Intake Agent                 │
 │  Eligibility Agent                     │
 │  Risk Agent                            │
 │  Fraud / Anomaly Agent                 │
 │                                        │
 └───────────────────┬────────────────────┘
                     │
                     ↓
        Decision & Reasoning Agent
                     │
                     ↓
           Loan Officer Dashboard
                     │
                     ↓
            Final Human Decision
                     │
                     ↓
                Audit Record
```

---

## Technology Stack

- **Programming Language**: Python 3.11+
- **Environment**: Python Virtual Environment (`.venv`)
- **Frontend / Dashboard**: Streamlit
- **Backend / API**: FastAPI & Uvicorn
- **Data Processing**: Pandas, NumPy
- **Machine Learning**: Scikit-learn
- **Document Processing**: PyMuPDF (Fitz), Pillow
- **OCR**: pytesseract
- **LLM / Agents**: Gemini integration (framework-agnostic architecture, implemented in future stages)
- **Database**: SQLite (prototype layer with seamless migration support for PostgreSQL)
- **Configuration**: python-dotenv & Pydantic BaseSettings
- **Testing**: pytest
- **Code Quality**: black, ruff
- **Version Control**: Git

---

## Project Structure

```text
AI-Loan-Underwriting-Assistant/
├── app/
│   ├── __init__.py
│   ├── main.py                     # Main application entry point & startup verification
│   ├── agents/                     # Specialized underwriting agents
│   │   ├── __init__.py
│   │   ├── orchestrator.py         # Multi-agent workflow coordinator
│   │   ├── document_agent.py       # Document intake and OCR pipeline agent
│   │   ├── eligibility_agent.py    # Policy rules and eligibility evaluation agent
│   │   ├── risk_agent.py           # Repayment and credit risk assessment agent
│   │   ├── fraud_agent.py          # Cross-document inconsistency and fraud agent
│   │   └── decision_agent.py       # Synthesis and explainable decision agent
│   ├── document_processing/        # File parsing and OCR utilities
│   │   ├── __init__.py
│   │   ├── pdf_reader.py           # PyMuPDF-based text and image extraction
│   │   ├── ocr.py                  # pytesseract wrapper for image OCR
│   │   └── extractor.py            # Key-value field parser
│   ├── eligibility/                # Centralized underwriting eligibility engine
│   │   ├── __init__.py
│   │   ├── policy.py               # Configurable EligibilityPolicy thresholds
│   │   ├── rules.py                # Deterministic rule evaluations
│   │   └── evaluator.py            # EligibilityEvaluator and aggregation logic
│   ├── risk/                       # Risk modeling and scoring logic
│   │   ├── __init__.py
│   │   ├── features.py             # Feature engineering & amortization math
│   │   ├── rules.py                # Deterministic risk & protective factor rules
│   │   ├── scoring.py              # Baseline weighted risk scoring engine
│   │   └── risk_model.py           # RandomForestClassifier ML risk model wrapper
│   ├── fraud/                      # Cross-document inconsistency and anomaly detection
│   │   ├── __init__.py             # Public exports
│   │   ├── rules.py                # Configurable rule thresholds and weights
│   │   ├── detectors.py            # Deterministic cross-document consistency checks
│   │   ├── scoring.py              # Composite anomaly scoring (0-100) and severity aggregation
│   │   └── anomaly_detection.py    # Backward-compatible AnomalyDetector adapter
│   ├── orchestration/              # Multi-agent underwriting pipeline coordination
│   │   ├── __init__.py             # Public orchestrator exports
│   │   ├── orchestrator.py         # UnderwritingOrchestrator engine
│   │   └── errors.py               # Orchestration exception hierarchy
│   ├── database/                   # Database access layer
│   │   ├── __init__.py
│   │   └── db.py                   # SQLite connection manager and migrations
│   ├── schemas/                    # Pydantic data models and contracts
│   │   ├── __init__.py
│   │   ├── applicant.py            # Applicant, Document, and Agent result schemas
│   │   ├── anomaly.py              # AnomalyFlag, AnomalyResult, AnomalySeverity schemas
│   │   └── underwriting.py         # OrchestrationStatus, AgentStatus, UnderwritingAnalysisResult
│   └── utils/                      # Shared helper utilities
│       ├── __init__.py
│       └── helpers.py              # Centralized logging configuration
├── models/                         # Serialized ML model artifacts & metadata
│   ├── risk_model.joblib           # Trained RandomForestClassifier
│   └── risk_model_metadata.json    # Hyper-parameters & feature importances
├── data/
│   ├── applicants/                 # Applicant JSON/metadata profiles
│   ├── documents/                  # Raw input PDFs and scanned images
│   ├── synthetic_data/             # Generated synthetic loan datasets
│   └── processed/                  # Cached extractions and intermediate outputs
├── models/                         # Serialized ML model artifacts (.pkl)
├── tests/                          # Automated unit and integration test suite
│   ├── __init__.py
│   ├── test_document_processing.py # Document processing foundation tests
│   ├── test_eligibility.py         # Eligibility agent and schema tests
│   ├── test_risk.py                # Risk scoring and schema tests
│   └── test_fraud.py               # Fraud, decision, config, and db tests
├── frontend/
│   └── streamlit_app.py            # Loan Officer decision-support dashboard
├── config/
│   ├── __init__.py
│   └── settings.py                 # Pydantic settings loading from .env
├── .env                            # Local environment configuration (untracked in Git)
├── .env.example                    # Template for environment configuration
├── .gitignore                      # Git exclusion rules
├── requirements.txt                # Python project dependencies
├── README.md                       # Project documentation
└── pyproject.toml                  # Tool configuration for black, ruff, and pytest
```

---

## Setup Instructions

### 1. Create and Activate Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

*(On Windows Command Prompt: `.venv\Scripts\activate`)*

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Environment Variables

Copy `.env.example` to create your local `.env` configuration:

```bash
cp .env.example .env
```

Default configuration variables:

| Variable | Description | Default |
|---|---|---|
| `GEMINI_API_KEY` | Google Gemini API key (integrated in Stage 7) | *(Empty)* |
| `DATABASE_URL` | Database connection URI | `sqlite:///./loan_underwriting.db` |
| `APP_ENV` | Environment identifier (`development`, `test`, `production`) | `development` |
| `LOG_LEVEL` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |

> *Note: Never commit real API keys or credentials to version control.*

---

## Running the Application

### 1. Main Verification Entry Point

Verify the core application packages, configuration, and logging:

```bash
python -m app.main
```

### 2. Loan Officer Streamlit Dashboard

Launch the Streamlit interactive review dashboard:

```bash
streamlit run frontend/streamlit_app.py
```

### 3. FastAPI Backend Service (Future Stage)

When the REST API service is activated in upcoming stages, it will be run via:

```bash
uvicorn app.main:app --reload --port 8000
```

---

## Running Tests and Code Quality

### Automated Unit Tests

Run the test suite using `pytest`:

```bash
pytest
```

### Linting and Code Formatting

Check code style and formatting standards:

```bash
ruff check .
black --check .
```

To auto-format code with `black`:

```bash
black .
```

---

## Stage 2 — Synthetic Dataset & Loan Documents

Stage 2 delivers a completely synthetic applicant dataset and multi-page loan document packages for algorithmic testing, OCR evaluation, risk modeling, and multi-agent underwriting demonstration.

### Overview

- **100 Synthetic Applicants**: Structured profiles with realistic Indian names, demographic attributes, and internally consistent financial metrics (income, expenses, debt obligations, requested facility, credit scores, DTI ratios). Available in:
  - `data/synthetic_data/applicants.csv`
  - `data/synthetic_data/applicants.json`
- **30 Document Packages**: Complete multi-page PDF packages (`data/documents/APP0001` through `data/documents/APP0030`) containing up to 4 documents per package:
  1. `loan_application.pdf`: Declared applicant profile, requested loan amount, tenure, and obligations.
  2. `identity_proof.pdf`: Simulated identity verification record with synthetic ID reference (`SYN-ID-APPXXXX-XXXXX`).
  3. `salary_slip.pdf` / `income_statement.pdf`: Monthly payroll earnings and deductions statement.
  4. `bank_statement.pdf`: 15–30 transaction ledger with salary credits, EMI debits, utility payments, and validated arithmetic.
- **Document Formats**: Includes standard selectable text PDFs as well as rasterized image-only scanned PDFs (2 salary slips, 2 bank statements) to test both digital and OCR pipelines in Stage 3.
- **Controlled Anomaly Cohorts (Ground Truth)**:
  - **Normal Baseline (APP0001–APP0005)**: Complete document agreement and arithmetic consistency.
  - **Income Mismatch (APP0006–APP0010)**: Declared income diverges from bank statement salary credits.
  - **Name Mismatch (APP0011–APP0015)**: Discrepancy between salary slip employee name and applicant identity.
  - **Missing Document (APP0016–APP0020)**: One mandatory document is genuinely omitted from the package.
  - **Financial Inconsistency (APP0021–APP0025)**: Undisclosed recurring EMI auto-debits or mismatched closing bank balances (tracked as inconsistency flags, not confirmed fraud).
  - **Borderline Cases (APP0026–APP0030)**: Valid, consistent documents where credit scores and DTI ratios sit right on underwriting policy thresholds for `MANUAL_REVIEW` testing.
- **Ground-Truth Metadata & Manifest**:
  - `data/synthetic_data/ground_truth.json`: Detailed ground-truth expectations, anomaly classifications, and expected field values.
  - `data/synthetic_data/document_manifest.csv`: 120-row index tracking document paths, format, presence, and anomaly flags.
  - `data/synthetic_data/dataset_metadata.json`: Dataset configuration, random seed (42), and distribution statistics.
- **Reproducibility & Safety**:
  - Seed 42 ensures reproducible synthetic applicant values and document contents. PDF metadata/timestamps do not need to be byte-identical.
  - Strictly synthetic: Contains no real Aadhaar, PAN, bank account numbers, or real individuals' data. Every PDF is clearly watermarked: `"SYNTHETIC DOCUMENT — FOR SOFTWARE TESTING ONLY"` and `"SYNTHETIC — NOT A GOVERNMENT ID"`.

### Dataset Generation & Validation Commands

```bash
# 1. Generate 100-applicant synthetic dataset (CSV, JSON, Metadata)
python scripts/generate_synthetic_dataset.py

# 2. Generate 30 document packages, manifest, and ground truth
python scripts/generate_documents.py

# 3. Run automated dataset integrity validator (15 checks)
python scripts/validate_dataset.py

# 4. Run automated test suite
pytest
```

---

## Stage 6 — Fraud & Anomaly Detection Agent

Stage 6 implements a local, deterministic analytical agent (`FraudAnomalyAgent`) that cross-verifies applicant declarations against Stage 3 structured document extraction outputs to identify cross-document inconsistencies and financial anomalies.

### What Was Implemented
- **Deterministic Cross-Document Consistency Engine (`CrossDocumentAnomalyDetector`)**:
  - `ANOM-ID-001` (Identity Consistency): Token-based name comparison across application, identity proof, salary slip, and bank statement.
  - `ANOM-INC-001` (Income Consistency): Flags declared income materially exceeding bank salary credits or salary slip net pay (> 15% tolerance).
  - `ANOM-FIN-001` (Liability Verification): Detects undisclosed ongoing recurring EMI debits in bank statement ledgers (threshold: >= INR 2,000 difference).
  - `ANOM-FIN-002` (Balance Verification): Identifies material shortfalls between declared bank balance and verified closing balance (> 25% and >= INR 10,000).
  - `ANOM-DOC-001` (Employer Verification): Detects employer name mismatches between application and payroll documents.
- **Explainable Anomaly Scoring (`AnomalyScorer`)**:
  - Bounded 0–100 composite anomaly score based on centralized rule weights.
  - Severity classification: `NONE` (0.0), `LOW` (0.1–25.0), `MEDIUM` (25.1–59.9), `HIGH` (60.0–100.0).
  - Traceable evidence excerpts, observed values, and expected values for every flag.
- **Strict Separation of Missing Evidence vs. Fraud Anomalies**:
  - Missing documents are captured under `missing_evidence` as incomplete verification.
  - Missing documents alone **never** trigger anomaly flags or fraud classifications.
- **Architectural Isolation**:
  - Operates 100% locally with zero external APIs, LLMs, or cloud dependencies.
  - Strictly separated from credit risk scoring (Stage 5) and loan decisioning (Stage 8).

### Evaluation & Verification Commands

```bash
# Run the controlled synthetic anomaly evaluation across all 30 applicant packages
python scripts/evaluate_anomaly_detection.py

# Run unit and integration tests
pytest tests/test_fraud.py
```

### Example Output

```text
APP0006: has_anomalies=True, score=35.0, sev=MEDIUM, flags=['ANOM-INC-001'], missing=[]
Evidence: "Income discrepancy detected: Declared monthly income (INR 85,000.00) materially exceeds verified bank statement recurring salary credit (INR 55,250.00) by 35.0%."

APP0016: has_anomalies=False, score=0.0, sev=NONE, flags=[], missing=['bank_statement']
Summary: "Notice: Missing document evidence (bank_statement). Incomplete documentation requires verification follow-up but does not constitute an anomaly flag."
```

### Limitations & Ethical AI Notice
- **Controlled Synthetic Cohorts**: Evaluation reflects deterministic consistency checking on controlled synthetic cohorts; it does not represent empirical real-world banking fraud rates.
- **Anomaly ≠ Confirmed Fraud**: Discrepancies may indicate clerical error, employer reporting variance, or document lag. The system flags items for human review and never asserts criminal guilt.

---

## Stage 7 — Multi-Agent Orchestrator

Stage 7 implements the `UnderwritingOrchestrator` engine and `OrchestratorAgent` facade coordinating the four specialized analytical agents (Document Intelligence, Eligibility, Risk Assessment, and Fraud/Anomaly Detection) into an end-to-end deterministic analysis pipeline.

### What Was Implemented
- **Deterministic Pipeline Coordination (`UnderwritingOrchestrator`)**:
  - Ingests applicant identifier (`APP0001`–`APP0030`) or pre-loaded `Applicant` domain models.
  - Enforces dependency-aware execution DAG: Document Intake runs before extracted-field consumers (Eligibility and Anomaly agents).
  - Collects analytical outputs into a single unified `UnderwritingAnalysisResult`.
- **Fault-Tolerant Execution & Partial-Result Preservation**:
  - Captures per-agent lifecycle status (`PENDING`, `RUNNING`, `SUCCESS`, `FAILED`, `SKIPPED`).
  - Implements failure isolation: If an individual agent fails, other successful analytical findings are preserved in a `PARTIAL_SUCCESS` state without unhandled crashes.
- **Audit Telemetry & Execution Tracking**:
  - Records wall-clock execution time in milliseconds (`duration_ms`) and UTC timestamps for each agent and the total pipeline.
  - Operates 100% locally and deterministically with zero LLMs or cloud API dependencies.
- **Strict Architectural Separation (No Stage 8 Decisioning)**:
  - Aggregates findings and synthesizes an executive analytical summary.
  - Strictly halts before generating `APPROVE` / `REJECT` / `MANUAL_REVIEW` recommendations (reserved for Stage 8).

### Evaluation & Verification Commands

```bash
# Run the 30-package pipeline evaluation
python scripts/evaluate_orchestrator.py

# Run orchestrator tests (including failure injection and determinism checks)
pytest tests/test_orchestrator.py
```

---

## Stage 8 — Decision & Reasoning Agent

Stage 8 implements the `DecisionReasoningAgent` (`DecisionAgent` facade) that synthesizes multi-agent analytical outputs collected by the Stage 7 Multi-Agent Orchestrator into one of three public categorical underwriting recommendations:

```text
APPROVE
REJECT
MANUAL_REVIEW
```

### What Was Implemented
- **Deterministic Policy & Reasoning Engine (`DecisionRulesEngine`)**:
  - Implements a 7-tier strict rule precedence hierarchy:
    1. Pipeline Integrity Check (`FAILED` → `MANUAL_REVIEW`)
    2. Critical Eligibility Failure Check (`INELIGIBLE` → `REJECT`)
    3. Mandatory Evidence Completeness Check (Missing Required Docs → `MANUAL_REVIEW`)
    4. Material Cross-Document Discrepancy Check (`HIGH`/`MEDIUM` Anomaly → `MANUAL_REVIEW`)
    5. Eligibility Review Required Check (`REVIEW_REQUIRED` → `MANUAL_REVIEW`)
    6. Repayment Risk Assessment Check (`HIGH` Risk → `REJECT`; `BORDERLINE` Risk → `MANUAL_REVIEW`)
    7. Clean Approval Synthesis (Eligible + Acceptable Risk + Complete Docs → `APPROVE`)
- **Zero LLM / No Retraining Constraint**:
  - Operates 100% locally and deterministically using explicit policy rules without external cloud APIs, OpenAI, Gemini, LangChain, or AutoGen.
  - Consumes Stage 5 ML risk scores without retraining or altering features.
- **Evidence Traceability & Factor Categorization**:
  - Standardized machine-readable reason codes (`DEC-ELIG-001`, `DEC-RISK-001`, `DEC-ANOM-001`, `DEC-DOC-001`, `DEC-SYS-001`, `DEC-APP-001`).
  - Categorizes findings into `positive_factors`, `negative_factors`, `blocking_factors`, and `supporting_evidence`.
- **Decision Confidence Score**:
  - Bounded 0.0–100.0% evidence completeness and analytical agreement score.
  - Penalizes missing documents, borderline risk profiles, and cross-document anomalies.
  - Strictly defined as a measure of evidence consistency, **not** an empirical probability of default or fraud.
- **Human-in-the-Loop Governance**:
  - All recommendations enforce `human_review_required = True`.
  - The AI assistant advises human loan officers; it does not replace authorized banking decisions.

### Evaluation & Verification Commands

```bash
# Run the 30-applicant Stage 8 underwriting decision evaluation
python scripts/evaluate_decisions.py

# Run unit and integration tests
pytest tests/test_decision_agent.py
```

### Example Reasoning Outputs

```text
--- Clean Applicant (APP0002) ---
Recommendation:        APPROVE (Confidence: 100.0%)
Human Review Required: True
Primary Reason:        [DEC-APP-001] Application satisfies all policy requirements: ELIGIBLE status,
                       MEDIUM risk profile (Score: 45.9/100), complete document evidence, zero anomalies.

--- Ineligible Applicant (APP0001) ---
Recommendation:        REJECT (Confidence: 100.0%)
Human Review Required: True
Primary Reason:        [DEC-ELIG-001] Application is INELIGIBLE due to failure of mandatory rule(s):
                       Minimum Credit Score Threshold (Credit score 612 < 650).

--- Discrepancy Applicant (APP0006) ---
Recommendation:        MANUAL_REVIEW (Confidence: 85.0%)
Human Review Required: True
Primary Reason:        [DEC-ANOM-001] Cross-document discrepancy detected (ANOM-INC-001): Declared income
                       materially exceeds bank statement salary credits by 35.0%.
```

### Limitations & Stage Boundary Notice
- **Synthetic Data**: Evaluated on controlled synthetic cohorts; does not represent empirical real-world default or fraud rates.
- **Anomaly ≠ Confirmed Fraud**: Discrepancies warrant human review; they are never equated to confirmed fraud.
- **Stage Boundary**: Stage 8 is COMPLETE. Stage 9 (Dashboard & Audit Trail) is NOT implemented.

---

## Development Roadmap

- **Stage 0 — Project Synopsis**: COMPLETE
- **Stage 1 — Core Project Foundation**: COMPLETE
- **Stage 2 — Synthetic Dataset & Test Documents**: COMPLETE
- **Stage 3 — Document Intelligence / Document Intake**: COMPLETE
- **Stage 4 — Eligibility Agent**: COMPLETE
- **Stage 5 — Risk Assessment Agent**: COMPLETE
- **Stage 6 — Fraud & Anomaly Detection Agent**: COMPLETE
- **Stage 7 — Multi-Agent Orchestrator**: COMPLETE
- **Stage 8 — Decision & Reasoning Agent**: COMPLETE
- **Stage 9 — Dashboard & Audit Trail**: NEXT

