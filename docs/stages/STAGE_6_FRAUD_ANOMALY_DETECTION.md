# Stage 6 — Fraud & Anomaly Detection Agent Specification & Report

## 1. Objective

The **Fraud & Anomaly Detection Agent** implements a local, deterministic analytical engine designed to detect suspicious cross-document inconsistencies, identity contradictions, and financial discrepancies across submitted loan application materials.

> **Crucial Distinction & Responsible Terminology Notice:**  
> The system detects **synthetic inconsistencies and anomalies** for software testing and research evaluation. **An anomaly is not proof of fraud.**  
> The system does not claim or assert that an applicant has committed fraud, nor does it label any applicant as a "fraudster" or "fraudulent applicant." In retail banking and research, discrepancies often arise from clerical errors, employer reporting variations, or legitimate documentation lags. Flagged items indicate a need for human underwriter review, not guilt or fraud confirmation.

---

## 2. Architecture & Data Flow

The Fraud & Anomaly Detection Agent operates independently downstream of Document Intelligence (Stage 3), alongside Underwriting Eligibility (Stage 4) and Risk Assessment (Stage 5):

```text
               Stage 3: Document Intelligence
                             │
            ┌────────────────┴────────────────┐
            ▼                                 ▼
Structured Extracted Documents          Missing Document Manifest
(`DocumentPackageResult`)               (`documents_missing`)
            │                                 │
            ├─────────────────┐               │
            ▼                 ▼               │
Stage 4: Eligibility   Stage 5: Risk         │
(Policy Engine)       (Credit Scoring)        │
            │                 │               │
            └────────┬────────┘               │
                     │                        │
                     ▼                        │
          Stage 6: Fraud & Anomaly Agent ◄────┘
          (`CrossDocumentAnomalyDetector`)
                     │
     ┌───────────────┼───────────────┐
     ▼               ▼               ▼
Identity Check  Income Check   Financial Check
(ANOM-ID-001)   (ANOM-INC-001) (ANOM-FIN-001/002)
     │               │               │
     └───────────────┬───────────────┘
                     │
                     ▼
          Anomaly Scoring Engine
          (`AnomalyScorer`: 0–100)
                     │
                     ▼
             `AnomalyResult`
    - `has_anomalies`: bool
    - `anomaly_score`: float (0–100)
    - `severity`: NONE / LOW / MEDIUM / HIGH
    - `flags`: List[AnomalyFlag] (Rule ID, values, excerpts)
    - `missing_evidence`: List[str] (tracked separately from flags)
    - `summary`: Explainable human-readable audit narrative
```

### Module Structure
```text
app/
├── agents/
│   └── fraud_agent.py          # FraudAnomalyAgent facade
├── fraud/
│   ├── __init__.py             # Public exports
│   ├── anomaly_detection.py    # AnomalyDetector legacy adapter
│   ├── detectors.py            # CrossDocumentAnomalyDetector
│   ├── rules.py                # AnomalyRulesConfig, text normalization & similarity
│   └── scoring.py              # AnomalyScorer & narrative synthesizer
└── schemas/
    └── anomaly.py              # AnomalyFlag, AnomalyResult, AnomalySeverity
```

---

## 3. Input Data

The agent consumes structured data without performing redundant PDF parsing, OCR, or text extraction:
1. **Applicant Domain Profile (`Applicant`)**: Declared monthly income, declared existing EMI, declared bank balance, declared employer name, and applicant name.
2. **Stage 3 Document Intelligence (`DocumentPackageResult`)**:
   - `documents_found`: Ingested documents (`loan_application`, `identity_proof`, `salary_slip`, `bank_statement`) containing classified document types and confidence-scored `ExtractedField` entries.
   - `documents_missing`: List of absent expected documents.
   - Traceable evidence excerpts, source document names, and page numbers.

---

## 4. Detection Rules & Identifiers

All detection logic is deterministic, explainable, and centralized in `app/fraud/rules.py` and `app/fraud/detectors.py`.

| Rule ID | Category | Anomaly Type | Severity | Default Weight | Trigger Condition |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`ANOM-ID-001`** | Identity Consistency | `NAME_MISMATCH` | `HIGH` | 40.0 pts | Token similarity between declared applicant name and document name (salary slip, ID proof, bank statement) < 0.85 |
| **`ANOM-INC-001`** | Income Consistency | `INCOME_MISMATCH` | `MEDIUM` / `HIGH` | 35.0 pts | Declared income exceeds verified bank statement recurring salary credit or salary slip net pay by > 15.0% |
| **`ANOM-FIN-001`** | Financial Consistency | `UNDISCLOSED_LIABILITY` | `HIGH` | 35.0 pts | Recurring loan EMI debits observed in bank statement exceed declared EMI by >= INR 2,000.00 |
| **`ANOM-FIN-002`** | Financial Consistency | `BALANCE_SHORTFALL` | `LOW` / `MEDIUM` / `HIGH` | 25.0 pts | Verified bank statement closing balance is lower than declared balance by > 25.0% AND >= INR 10,000.00 |
| **`ANOM-DOC-001`** | Document Consistency | `EMPLOYER_MISMATCH` | `LOW` | 15.0 pts | Token similarity between declared employer and salary slip employer < 0.50 |

---

## 5. Centralized Configuration & Thresholds

Rules and thresholds are centralized in `AnomalyRulesConfig` (`app/fraud/rules.py`):
```python
class AnomalyRulesConfig(BaseModel):
    config_version: str = "anomaly_rules_v1"
    income_discrepancy_threshold_pct: float = 15.0   # 15% tolerance
    undisclosed_emi_threshold_inr: float = 2000.0     # INR 2,000 buffer
    balance_discrepancy_threshold_pct: float = 25.0   # 25% shortfall tolerance
    balance_discrepancy_min_inr: float = 10000.0      # INR 10,000 minimum variance
    name_similarity_threshold: float = 0.85          # Token-level similarity
    rule_weights: Dict[str, float] = {
        "ANOM-ID-001": 40.0,
        "ANOM-INC-001": 35.0,
        "ANOM-FIN-001": 35.0,
        "ANOM-FIN-002": 25.0,
        "ANOM-DOC-001": 15.0,
    }
```

No hardcoded applicant identifiers or thresholds exist in detector code.

---

## 6. Anomaly Scoring Methodology

The composite anomaly score is a bounded metric on a **0 to 100** continuous scale:
$$\text{Raw Score} = \sum_{f \in \text{Flags}} \text{Weight}(f)$$
$$\text{Anomaly Score} = \min(\max(\text{Raw Score}, 0.0), 100.0)$$

- If an individual flag has `HIGH` severity, its score contribution is automatically escalated to at least 35.0 points.
- If multiple anomalies are observed on a single application package, their weights accumulate up to the 100.0 ceiling.
- Clean applications with zero discrepancies yield an anomaly score of **0.0**.

> **Crucial Rule:** The anomaly score is derived entirely from cross-document consistency checks and financial discrepancies. It is **NOT** combined with or used to modify the Stage 5 credit risk score.

---

## 7. Severity Levels

Severity is evaluated at both the individual flag level and the composite result level:

| Tier | Anomaly Score Range | Typical Conditions | Meaning |
| :--- | :--- | :--- | :--- |
| **`NONE`** | `0.0` | No cross-document discrepancies detected | Submitted documents match declarations |
| **`LOW`** | `0.1 – 25.0` | Minor balance discrepancy or employer spelling variation | Minor clerical or timing difference |
| **`MEDIUM`** | `25.1 – 59.9` | Single income mismatch or single financial inconsistency | Material discrepancy requiring verification |
| **`HIGH`** | `60.0 – 100.0` | Identity mismatch, major undisclosed debt, or multiple compounding discrepancies | Significant divergence requiring senior underwriter scrutiny |

---

## 8. Missing Document Handling vs. Anomaly Flags

A fundamental design requirement of Stage 6 is the clean separation between **Missing Evidence** and **Anomalies**:
- **Missing Evidence (`missing_evidence`)**: Recorded when an expected document (e.g., bank statement or salary slip) is absent from the submitted application package.
- **Anomaly (`flags`, `has_anomalies`)**: Recorded only when an affirmative contradiction exists between two pieces of evidence or between declarations and evidence.
- An application with missing documents but no discrepancies receives:
  - `has_anomalies = False`
  - `anomaly_score = 0.0`
  - `severity = NONE`
  - `missing_evidence = ['bank_statement']`
  - Explanatory notice in `summary`

Missing documents are handled as review conditions in Stage 4 Eligibility; they are **never** classified as fraud or anomalies in Stage 6.

---

## 9. Evidence & Explainability

Every generated anomaly flag contains rich contextual evidence:
```json
{
  "rule_id": "ANOM-INC-001",
  "anomaly_type": "INCOME_MISMATCH",
  "severity": "HIGH",
  "description": "Income discrepancy detected: Declared monthly income (INR 85,000.00) materially exceeds verified bank statement recurring salary credit (INR 55,250.00) by 35.0%.",
  "expected_value": "INR 85,000.00",
  "observed_value": "INR 55,250.00",
  "source_documents": ["loan_application", "bank_statement.pdf"],
  "evidence": "Bank statement credit excerpt: 'Salary credit transaction: INR 55250.00'"
}
```

The system provides end-to-end auditability, linking each discrepancy directly back to the physical source document and text excerpt extracted in Stage 3.

---

## 10. Synthetic Cohort Evaluation

The detector was evaluated on all 30 controlled document packages (`APP0001`–`APP0030`) using `scripts/evaluate_anomaly_detection.py`.

### Benchmark Results (N=30)

| Metric | Value | Interpretation |
| :--- | :--- | :--- |
| **Evaluation Accuracy** | **100.0%** | Correct anomaly vs clean cohort classification |
| **Anomaly Precision** | **100.0%** | All flagged applicants possess genuine injected anomalies |
| **Anomaly Recall** | **100.0%** | All 15 injected anomaly packages successfully detected |
| **Macro F1-Score** | **1.0000** | Perfect harmonic balance on controlled cohorts |
| **True Positives (TP)** | **15** | Cohorts 06–10 (Income), 11–15 (Name), 21–25 (Financial) |
| **False Positives (FP)** | **0** | Zero clean or borderline applicants incorrectly flagged |
| **True Negatives (TN)** | **15** | Cohorts 01–05 (Normal), 16–20 (Missing docs), 26–30 (Borderline) |
| **False Negatives (FN)** | **0** | Zero injected anomalies missed |

### Cohort Breakdown

| Cohort Name | Package IDs | Size | Flagged | Detection Rate | Primary Detected Rules | Missing Evidence Tracking |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Normal / Consistent** | APP0001–APP0005 | 5 | 0 | 100.0% (Clean) | None | 0 / 5 |
| **Income Mismatch** | APP0006–APP0010 | 5 | 5 | 100.0% (Flagged) | `ANOM-INC-001` (5) | 0 / 5 |
| **Name Mismatch** | APP0011–APP0015 | 5 | 5 | 100.0% (Flagged) | `ANOM-ID-001` (5) | 0 / 5 |
| **Missing Documents** | APP0016–APP0020 | 5 | 0 | 100.0% (Clean) | None | **5 / 5 correctly identified** |
| **Financial Inconsistency** | APP0021–APP0025 | 5 | 5 | 100.0% (Flagged) | `ANOM-FIN-001` (3), `ANOM-FIN-002` (2) | 0 / 5 |
| **Borderline Risk Profile** | APP0026–APP0030 | 5 | 0 | 100.0% (Clean) | None | 0 / 5 |

---

## 11. Limitations

1. **Synthetic Data Nature**: The evaluation reflects performance against synthetic, controlled anomaly cohorts generated for research. It does not reflect empirical performance against real-world retail banking fraud syndicates.
2. **Discrepancy vs. Criminal Intent**: Anomaly detection identifies contradictions, variance, and evidence gaps. It cannot establish criminal intent or confirm fraud.
3. **Document Quality Dependency**: Rule evaluation relies on Stage 3 extraction accuracy. While Stage 3 achieves 99.8% field accuracy, OCR artifacts on degraded scans could hypothetically induce false positive name or number mismatches in production environments.
4. **No Unsupervised Override**: As required by project safety constraints, no uncalibrated ML or unsupervised black-box model overrides deterministic rule findings.

---

## 12. Ethical & Responsible AI Considerations

- **Adverse Action Protections**: Under fair lending regulations (e.g., ECOA, FCRA), an applicant cannot be denied credit based on unverified "fraud suspicion" from an automated agent. Discrepancies generate actionable evidence packages for human underwriting review.
- **Fair Name Matching**: Token normalization and order invariance prevent false penalties against individuals with diverse naming conventions, patronymics, or reversed order formats.
- **Decoupled Risk and Fraud**: High credit risk (e.g., borderline applicants in APP0026–APP0030) is strictly decoupled from fraud suspicion, preventing bias against economically vulnerable applicants.

---

## 13. What Stage 6 Does NOT Do

To maintain strict architectural boundaries:
- **Does NOT make loan decisions**: No `APPROVE`, `REJECT`, or final decisioning logic is executed (reserved for Stage 8).
- **Does NOT calculate policy eligibility**: Handled exclusively by Stage 4.
- **Does NOT compute credit risk**: Handled exclusively by Stage 5.
- **Does NOT modify risk scores**: The risk score is never adjusted by anomaly scores.
- **Does NOT orchestrate the multi-agent pipeline**: Pipeline coordination is reserved for Stage 7.
- **Does NOT perform redundant OCR or parsing**: Consumes structured Stage 3 outputs.
- **Does NOT use external cloud APIs or LLMs**: Operates 100% locally and deterministically.

---

## 14. Verification Commands

To reproduce the Stage 6 evaluation and test suite:

```bash
# Run unit and integration tests (121 tests total)
pytest tests/test_fraud.py

# Run full project test suite
pytest

# Run the controlled synthetic anomaly evaluation
python scripts/evaluate_anomaly_detection.py

# Code quality checks
ruff check .
black --check .
```
