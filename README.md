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
│   ├── risk/                       # Risk modeling and scoring logic
│   │   ├── __init__.py
│   │   ├── rules.py                # Deterministic underwriting rule checks
│   │   ├── scoring.py              # Normalized risk scoring engine
│   │   └── risk_model.py           # Machine-learning default prediction wrapper
│   ├── fraud/                      # Inconsistency and anomaly detection
│   │   ├── __init__.py
│   │   └── anomaly_detection.py    # Cross-document mismatch detector
│   ├── database/                   # Database access layer
│   │   ├── __init__.py
│   │   └── db.py                   # SQLite connection manager and migrations
│   ├── schemas/                    # Pydantic data models and contracts
│   │   ├── __init__.py
│   │   └── applicant.py            # Applicant, Document, and Agent result schemas
│   └── utils/                      # Shared helper utilities
│       ├── __init__.py
│       └── helpers.py              # Centralized logging configuration
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

## Development Roadmap

- **Stage 1 — Project Setup** *(Completed)*: Foundational directory architecture, configuration, Pydantic schemas, database connection abstraction, Streamlit UI shell, and test suite.
- **Stage 2 — Synthetic Applicant Dataset** *(Completed)*: 100 synthetic applicant profiles, 30 complete document packages (120 PDFs), controlled anomaly cohorts, ground-truth metadata, and validation tooling.
- **Stage 3 — Document Processing** *(Completed)*: Implementation of PyMuPDF PDF parsing, local pytesseract OCR pipeline, document classification, traceable key-value entity extraction, missing document detection, and ground-truth evaluation.

- **Stage 4 — Eligibility Engine**: Implementation of deterministic rule evaluation (DTI calculations, minimum income, age limits, credit score thresholds).
- **Stage 5 — Risk Model**: Heuristic risk scoring and Scikit-learn default prediction model training and integration.
- **Stage 6 — Fraud / Anomaly Detection**: Implementation of cross-document consistency checks and discrepancy detection heuristics.
- **Stage 7 — Multi-Agent System**: Google Gemini integration, reasoning prompt chains, multi-agent orchestration, and recommendation synthesis.
- **Stage 8 — Dashboard & Audit**: Interactive Streamlit loan officer dashboard integration with live database audit logging and human decision capture.
- **Stage 9 — Testing & Evaluation**: End-to-end evaluation, benchmark metrics, adversarial anomaly tests, and documentation.
