# Stage 7 — Multi-Agent Orchestrator Specification & Report

## 1. Objective

The **Multi-Agent Orchestrator** coordinates the specialized, autonomous analytical agents implemented in Stages 3 through 6 into a cohesive, deterministic loan underwriting pipeline.

Its primary responsibility is:
> **COORDINATE → EXECUTE → COLLECT → VALIDATE → AGGREGATE → REPORT**

It aggregates findings from:
1. **Document Intelligence Agent (`DocumentIntakeAgent`)** (Stage 3)
2. **Underwriting Eligibility Agent (`EligibilityAgent`)** (Stage 4)
3. **Risk Assessment Agent (`RiskAgent`)** (Stage 5)
4. **Fraud & Anomaly Detection Agent (`FraudAnomalyAgent`)** (Stage 6)

> **Strict Stage Boundary & Non-Decisioning Notice:**  
> **Stage 7 coordinates existing analytical agents but does NOT make the final loan decision.**  
> The orchestrator returns an `UnderwritingAnalysisResult` containing analytical evidence, policy checks, credit risk tiers, and anomaly flags. It strictly halts before generating `APPROVE`, `REJECT`, or `MANUAL_REVIEW` loan recommendations, which are reserved for the Stage 8 Decision & Reasoning Agent.

---

## 2. Architecture & Data Flow

```text
                           Application ID
                                │
                                ▼
                     ┌──────────────────────┐
                     │     ORCHESTRATOR     │
                     │(UnderwritingOrchestrator)
                     └──────────┬───────────┘
                                │
              Step 1: Load Applicant Domain Model
                                │
                                ▼
                     ┌──────────────────────┐
                     │ Document Intelligence│
                     │        Agent         │
                     └──────────┬───────────┘
                                │
                      DocumentPackageResult
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
          ▼                     ▼                     ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│Eligibility Agent │  │   Risk Agent     │  │  Anomaly Agent   │
│ (Policy Engine)  │  │(ML Random Forest)│  │(Consistency Check│
└─────────┬────────┘  └─────────┬────────┘  └─────────┬────────┘
          │                     │                     │
          ▼                     ▼                     ▼
  EligibilityResult         RiskResult          AnomalyResult
          │                     │                     │
          └─────────────────────┼─────────────────────┘
                                │
                                ▼
                  ┌───────────────────────────┐
                  │UnderwritingAnalysisResult │
                  │  - application_id         │
                  │  - orchestration_status   │
                  │  - document_result        │
                  │  - eligibility_result     │
                  │  - risk_result            │
                  │  - anomaly_result         │
                  │  - agent_statuses (audit) │
                  │  - execution latencies    │
                  │  - executive summary      │
                  └─────────────┬─────────────┘
                                │
                                ▼
                     Stage 8 Decision Agent
                       (NOT IMPLEMENTED)
```

### Module Structure
```text
app/
├── agents/
│   └── orchestrator.py             # OrchestratorAgent facade
├── orchestration/
│   ├── __init__.py                 # Public orchestrator exports
│   ├── orchestrator.py             # UnderwritingOrchestrator engine
│   └── errors.py                   # Orchestration exception hierarchy
└── schemas/
    └── underwriting.py             # OrchestrationStatus, AgentStatus, UnderwritingAnalysisResult
```

---

## 3. Coordinated Agents & Responsibilities

| Agent | Module | Input Data | Primary Output | Stage |
| :--- | :--- | :--- | :--- | :--- |
| **`DocumentIntakeAgent`** | `app.agents.document_agent` | Physical PDF folder (`data/documents/{id}`) | `DocumentPackageResult`: Ingested documents, classified types, OCR telemetry, extracted key-value fields with confidence and page evidence. | Stage 3 |
| **`EligibilityAgent`** | `app.agents.eligibility_agent` | `DocumentPackageResult` (fallback: `Applicant`) | `EligibilityResult`: 10 deterministic policy rule outcomes (`PASS`, `FAIL`, `REVIEW_REQUIRED`), DTI ratio, and completeness checks. | Stage 4 |
| **`RiskAgent`** | `app.agents.risk_agent` | `Applicant` profile | `RiskResult`: ML Random Forest risk score (0–100), risk tier (`LOW`, `MEDIUM`, `BORDERLINE`, `HIGH`), adverse and protective factors. | Stage 5 |
| **`FraudAnomalyAgent`** | `app.agents.fraud_agent` | `DocumentPackageResult` + `Applicant` | `AnomalyResult`: Deterministic cross-document identity, income, and debt consistency flags (`ANOM-ID-001`, `ANOM-INC-001`, `ANOM-FIN-001/002`). | Stage 6 |

---

## 4. Execution Order & Data Dependencies

The orchestrator enforces a clean, dependency-aware directed acyclic graph (DAG):

```text
Applicant ID
     │
     ├───► Load Applicant Profile (Step 1)
     │          │
     │          ├───► Risk Agent (Step 4: runs on Applicant attributes)
     │          │
     └───► Document Intake Agent (Step 2: processes PDFs/OCR)
                │
                ├───► Eligibility Agent (Step 3: verifies extracted fields against policy)
                │
                └───► Anomaly Agent (Step 5: cross-checks declared vs extracted evidence)
```

- **Prerequisite Ordering**: Document Intelligence must execute before Eligibility and Anomaly agents to supply structured document extractions.
- **Graceful Fallbacks**: If document processing encounters an unexpected I/O failure, downstream agents fall back to the pre-loaded `Applicant` domain model to ensure partial analytical progress.

---

## 5. Error Handling & Partial-Result Preservation

The orchestrator isolates agent failures so that a single error never causes an unhandled crash or aborts independent analytical components.

### Status Tiers (`OrchestrationStatus`)
- **`SUCCESS`**: All four specialized agents executed cleanly without errors.
- **`PARTIAL_SUCCESS`**: At least one agent succeeded and at least one agent encountered an isolated error. The orchestrator preserves all successful analytical results, records the failure in `agent_statuses`, and includes an explanatory warning in `error_message`.
- **`FAILED`**: A catastrophic failure occurred (e.g. applicant record not found in database or all agents failed).

### Failure Isolation Matrix

| Failure Scenario | Document Result | Eligibility Result | Risk Result | Anomaly Result | Pipeline Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Normal Execution** | `SUCCESS` | `SUCCESS` | `SUCCESS` | `SUCCESS` | `SUCCESS` |
| **Simulated Risk Failure** | `SUCCESS` | `SUCCESS` | `FAILED` (`None`) | `SUCCESS` | `PARTIAL_SUCCESS` |
| **Simulated Anomaly Failure**| `SUCCESS` | `SUCCESS` | `SUCCESS` | `FAILED` (`None`) | `PARTIAL_SUCCESS` |
| **Simulated Document Failure**| `FAILED` (`None`)| `SUCCESS` (fallback)| `SUCCESS` | `SUCCESS` (fallback)| `PARTIAL_SUCCESS` |
| **Missing Applicant ID** | `None` | `None` | `None` | `None` | `FAILED` |

---

## 6. Audit Trail & Execution Telemetry

For each agent and the pipeline as a whole, the orchestrator records:
- `agent_name`: Name identifier (`document_agent`, `eligibility_agent`, `risk_agent`, `anomaly_agent`).
- `status`: Lifecycle state (`PENDING`, `RUNNING`, `SUCCESS`, `FAILED`, `SKIPPED`).
- `started_at` & `completed_at`: UTC timestamps.
- `duration_ms`: Wall-clock execution time in milliseconds.
- `error`: Error string and diagnostic details if execution failed.
- `pipeline_version`: Version identifier (`pipeline_v1`).

---

## 7. Determinism & Data Immutability

- **Zero LLM Non-Determinism**: The pipeline is 100% deterministic and contains zero probabilistic LLM calls, random seeds, or cloud API dependencies.
- **Ordered Flag Sorting**: Anomaly flags in `AnomalyResult.flags` are sorted by `rule_id` to guarantee identical comparison across runs.
- **Immutability Principle**: The orchestrator strictly aggregates outputs without modifying or combining scores:
  - Does NOT alter `risk_result.risk_score` or `risk_category`.
  - Does NOT combine `anomaly_score` with `risk_score`.
  - Does NOT change `eligibility_result.status`.

---

## 8. Synthetic Cohort Evaluation (N=30 Document Packages)

Evaluated via [`scripts/evaluate_orchestrator.py`](file:///Users/aditya/Desktop/Stuff/Mini%20Project/scripts/evaluate_orchestrator.py):

### Benchmark Summary

| Metric | Value | Meaning |
| :--- | :--- | :--- |
| **Total Evaluated Packages** | **30** | Complete set of applicant document packages (`APP0001`–`APP0030`) |
| **Pipeline Success Rate** | **100.0% (30/30)** | Zero unhandled failures across all cohorts |
| **Partial Pipelines** | **0 (0.0%)** | All 4 agents executed cleanly across all 30 packages |
| **Failed Pipelines** | **0 (0.0%)** | Zero pipeline abortions |
| **Average Pipeline Latency** | **118.80 ms** | Fast, local multi-agent processing |

### Per-Agent Latency & Reliability

| Agent Name | Success Rate | Avg Latency (ms) | Architectural Role |
| :--- | :--- | :--- | :--- |
| `document_agent` | **30/30 (100.0%)** | 115.35 ms | PDF parsing, OCR fallback, field extraction |
| `eligibility_agent` | **30/30 (100.0%)** | 0.12 ms | Deterministic policy evaluation |
| `risk_agent` | **30/30 (100.0%)** | 3.25 ms | Feature extraction & ML Random Forest inference |
| `anomaly_agent` | **30/30 (100.0%)** | 0.04 ms | Cross-document consistency verification |

### Cohort Breakdown

| Cohort Description | Size | Status | Eligibility Outcomes | Assessed Risk Tiers | Detected Anomalies |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Normal / Consistent (01–05)** | 5 | 5/5 OK | ELIGIBLE: 4, INELIGIBLE: 1 | HIGH: 1, MEDIUM: 3, LOW: 1 | 0/5 flagged (Clean) |
| **Income Mismatch (06–10)** | 5 | 5/5 OK | ELIGIBLE: 5 | LOW: 3, BORDERLINE: 1, MEDIUM: 1 | 5/5 flagged (`ANOM-INC-001`) |
| **Name Mismatch (11–15)** | 5 | 5/5 OK | ELIGIBLE: 3, INELIGIBLE: 2 | LOW: 1, HIGH: 2, MEDIUM: 2 | 5/5 flagged (`ANOM-ID-001`) |
| **Missing Documents (16–20)** | 5 | 5/5 OK | REVIEW_REQUIRED: 4, INELIGIBLE: 1 | BORDERLINE: 2, MEDIUM: 2, LOW: 1 | 0/5 flagged (No false fraud) |
| **Financial Inconsistency (21–25)**| 5 | 5/5 OK | INELIGIBLE: 3, ELIGIBLE: 2 | HIGH: 1, LOW: 1, BORDERLINE: 3 | 5/5 flagged (`ANOM-FIN-001/002`) |
| **Borderline Risk Profile (26–30)**| 5 | 5/5 OK | ELIGIBLE: 4, INELIGIBLE: 1 | BORDERLINE: 5 | 0/5 flagged (Clean) |

---

## 9. Sample Pipeline Output Inspection

### Application APP0001 (Clean Baseline)
```text
Application: APP0001
Pipeline Status:        SUCCESS
Total Pipeline Latency: 17.62 ms
Document Agent:         SUCCESS (4 docs found, 0 missing)
Eligibility Agent:      INELIGIBLE (Passed: 9/10 — Credit score 584 < policy min 650)
Risk Agent:             Tier: HIGH (Score: 84.6/100, Method: ML_RANDOM_FOREST)
Anomaly Agent:          Severity: NONE (Score: 0.0/100, Flags: None)
Final Loan Decision:    NOT GENERATED — Stage 8 (Decision & Reasoning Agent)
Executive Summary:      Underwriting Pipeline Analysis for APP0001 (Status: SUCCESS). Documents: 4 verified, 0 missing. Eligibility: INELIGIBLE. Risk Assessment: HIGH (Score: 84.6/100). Anomaly Detection: NONE (Score: 0.0/100, Flags: 0). Notice: Final loan recommendation (APPROVE/REJECT/MANUAL_REVIEW) pending Stage 8 Decision & Reasoning Agent.
```

### Application APP0006 (Income Mismatch)
```text
Application: APP0006
Pipeline Status:        SUCCESS
Total Pipeline Latency: 12.04 ms
Document Agent:         SUCCESS (4 docs found, 0 missing)
Eligibility Agent:      ELIGIBLE (Passed: 10/10)
Risk Agent:             Tier: LOW (Score: 16.5/100, Method: ML_RANDOM_FOREST)
Anomaly Agent:          Severity: MEDIUM (Score: 35.0/100, Flags: ANOM-INC-001)
Final Loan Decision:    NOT GENERATED — Stage 8 (Decision & Reasoning Agent)
Executive Summary:      Underwriting Pipeline Analysis for APP0006 (Status: SUCCESS). Documents: 4 verified, 0 missing. Eligibility: ELIGIBLE. Risk Assessment: LOW (Score: 16.5/100). Anomaly Detection: MEDIUM (Score: 35.0/100, Flags: 1). Notice: Final loan recommendation (APPROVE/REJECT/MANUAL_REVIEW) pending Stage 8 Decision & Reasoning Agent.
```

### Application APP0016 (Missing Evidence)
```text
Application: APP0016
Pipeline Status:        SUCCESS
Total Pipeline Latency: 8.01 ms
Document Agent:         SUCCESS (3 docs found, 1 missing: bank_statement)
Eligibility Agent:      REVIEW_REQUIRED (Passed: 9/10 — Incomplete mandatory documentation)
Risk Agent:             Tier: BORDERLINE (Score: 60.0/100, Method: ML_RANDOM_FOREST)
Anomaly Agent:          Severity: NONE (Score: 0.0/100, Flags: None, missing_evidence: ['bank_statement'])
Final Loan Decision:    NOT GENERATED — Stage 8 (Decision & Reasoning Agent)
Executive Summary:      Underwriting Pipeline Analysis for APP0016 (Status: SUCCESS). Documents: 3 verified, 1 missing. Eligibility: REVIEW_REQUIRED. Risk Assessment: BORDERLINE (Score: 60.0/100). Anomaly Detection: NONE (Score: 0.0/100, Flags: 0). Notice: Final loan recommendation (APPROVE/REJECT/MANUAL_REVIEW) pending Stage 8 Decision & Reasoning Agent.
```

---

## 10. Limitations

1. **Orchestration Scope**: Stage 7 coordinates existing components. It does not perform OCR, evaluate credit risk, check policy rules, or detect discrepancies independently.
2. **Decision Non-Execution**: The pipeline purposefully halts before determining loan approval or rejection. Decision synthesis requires Stage 8.
3. **Local In-Memory Execution**: The pipeline is executed synchronously in-memory within the local Python runtime. No distributed message queues (e.g. Celery, Kafka) or background workers are utilized, keeping the architecture simple and inspectable for college mini-project research.

---

## 11. Verification Commands

```bash
# Run orchestrator unit and failure injection tests
pytest tests/test_orchestrator.py

# Run full project test suite (133 tests)
pytest

# Run the 30-package pipeline evaluation script
python scripts/evaluate_orchestrator.py

# Verify code style and formatting
ruff check .
black --check .
```
