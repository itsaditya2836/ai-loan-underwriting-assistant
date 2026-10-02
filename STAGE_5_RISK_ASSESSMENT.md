# Stage 5 — Risk Assessment Agent Specification & Report

## 1. Purpose

The **Risk Assessment Agent** evaluates an applicant's financial and credit risk profile based on verified, structured data produced by Stage 3 (Document Intelligence) and Stage 4 (Underwriting Eligibility).

Its objective is to answer:
> *"How risky does this applicant appear based on the available financial and credit indicators?"*

It explicitly does **NOT** answer:
> *"Should this loan be approved?"*

Final loan decisioning (`APPROVE` / `REJECT` / `MANUAL_REVIEW`) is reserved for the future **Decision & Reasoning Agent** (Stage 8).

> **Explicit Scope Boundary & Responsible AI Notice:**  
> The Stage 5 model provides a risk assessment based on synthetic underwriting data. It is not a calibrated empirical probability of default and does not independently approve or reject loans. It does not perform fraud detection, anomaly detection, cross-document inconsistency checks, or multi-agent orchestration.

---

## 2. Architecture & Data Flow

The Risk Assessment Agent is an independent component operating downstream of document intelligence and eligibility verification:

```text
Stage 3: Document Intelligence
       │
       ▼
Structured Applicant Data & Extracted Entities
       │
       ├─────────────────────────────────┐
       ▼                                 ▼
Stage 4: Eligibility Agent         Stage 5: Risk Assessment Agent
(Deterministic Rule Policy)        (Feature Engineering & ML Risk Model)
       │                                 │
       ▼                                 ▼
EligibilityResult                 RiskResult
(ELIGIBLE / INELIGIBLE /          (Normalized Score: 0–100,
 REVIEW_REQUIRED)                  Category: LOW/MED/HIGH/BORDERLINE,
                                   Explainable Factors, Evidence)
```

The `RiskAgent` wraps the underlying components:
- **`app/risk/features.py`**: Extracts 15 continuous and categorical features with zero target leakage.
- **`app/risk/risk_model.py`**: Local `RandomForestClassifier` generating probability-weighted risk scores.
- **`app/risk/scoring.py`**: Deterministic weighted heuristic baseline scorer.
- **`app/risk/rules.py`**: Heuristic factor extraction engine producing human-readable risk and protective factors.

---

## 3. Dataset Characteristics

The model is trained and evaluated on the 100 synthetic applicant profiles generated in Stage 2 (`data/synthetic_data/applicants.csv`).

| Profile Tier | Count | Percentage | Description |
| :--- | :--- | :--- | :--- |
| `LOW` | 30 | 30.0% | High income, low DTI, prime credit score (>= 750), strong liquidity buffer |
| `MEDIUM` | 30 | 30.0% | Moderate earnings, acceptable DTI (30–50%), credit scores between 680–740 |
| `BORDERLINE` | 20 | 20.0% | Boundary debt burdens (DTI 45–65%) or scores sitting near policy thresholds (640–680) |
| `HIGH` | 20 | 20.0% | Subprime credit (< 640), high debt leverage (DTI > 60%), thin liquidity buffer |
| **Total** | **100** | **100.0%** | Balanced distribution representing diverse retail credit segments |

---

## 4. Target Definition (Synthetic Risk Profile)

The classification target is `profile_category` mapped to four tiers:
- `LOW`
- `MEDIUM`
- `HIGH`
- `BORDERLINE`

**Critical Research Note**: The training target is a **synthetic risk-profile classification**, NOT an observed real-world loan default outcome. The dataset reflects synthetic underwriting classifications rather than historical default cohort tracking.

---

## 5. Feature Engineering & Leakage Prevention

### Explicit Feature Vector (15 Features)
To prevent data leakage, target-derived columns (`profile_category`, `risk_category`, `risk_score`) are strictly excluded from the feature matrix:

1. `age`: Applicant age in years.
2. `employment_years`: Career stability in years.
3. `monthly_income`: Net monthly verified income in INR.
4. `existing_emi`: Ongoing monthly debt obligations in INR.
5. `loan_amount`: Requested loan principal in INR.
6. `loan_tenure`: Requested loan duration in months.
7. `credit_score`: Bureau credit score (range: 300–900).
8. `bank_balance`: Liquid bank balance in INR.
9. `monthly_expenses`: Declared or estimated living expenses in INR.
10. `number_of_dependents`: Family dependents.
11. `estimated_new_emi`: Monthly installment for the requested loan calculated via standard amortization.
12. `dti_ratio`: Debt-to-Income / FOIR ratio: `((existing_emi + estimated_new_emi) / monthly_income) * 100`.
13. `loan_to_income_ratio`: Leverage ratio: `loan_amount / (monthly_income * 12)`.
14. `net_disposable_income`: Unallocated monthly cash flow: `monthly_income - existing_emi - estimated_new_emi - monthly_expenses`.
15. `is_salaried`: Binary flag (`1.0` for Salaried, `0.0` for Self-Employed).

### Amortization Formula
New EMI estimation uses the standard retail lending amortization formula:
$$\text{EMI} = P \times r \times \frac{(1+r)^n}{(1+r)^n - 1}$$
with $r = 0.105 / 12$ (10.5% annual benchmark interest rate).

---

## 6. Model Selection

### Primary Model: Random Forest Classifier
- **Algorithm**: `RandomForestClassifier(n_estimators=50, max_depth=5, min_samples_split=2, random_state=42)`
- **Rationale**:
  - Fully local, lightweight, and deterministic under fixed random seed.
  - Native handling of non-linear financial ratios (DTI vs. credit score).
  - Robust against feature scaling variations.
  - Exposes transparent Gini feature importances.
  - Predicts well-behaved class probability distributions.

### Baseline Model: Domain-Weighted Heuristic Scorer
A transparent, rule-based baseline weighting credit metrics:
- **Credit Score (40%)**: Prime (10 pts) to Sub-prime (95 pts)
- **DTI Ratio (30%)**: Healthy <= 30% (10 pts) to Elevated > 60% (95 pts)
- **Loan-to-Income (20%)**: <= 1.0x (10 pts) to > 2.5x (85 pts)
- **Liquidity Buffer (10%)**: >= 6 months EMI (10 pts) to < 2 months EMI (80 pts)

$$\text{Composite} = 0.40 \times C_{\text{score}} + 0.30 \times DTI + 0.20 \times LTI + 0.10 \times Buffer$$

---

## 7. Model Evaluation & Benchmark Results

### Benchmark Comparison (Full Dataset N=100)

| Metric | Baseline (Weighted Heuristic) | ML (Random Forest) |
| :--- | :--- | :--- |
| **Overall Accuracy** | 60.0% | **100.0%** (Full fit) / **95.0%** (Holdout) |
| **Macro F1-Score** | 0.5930 | **1.0000** (Full fit) / **0.9400** (Holdout) |
| **5-Fold Cross-Validation Accuracy** | N/A | **97.00% (+/- 4.00%)** |
| **5-Fold Cross-Validation Macro-F1** | N/A | **97.02% (+/- 3.72%)** |

### Per-Class Performance Breakdown (Full Dataset)

| Risk Tier | Baseline Precision | Baseline Recall | ML Precision | ML Recall |
| :--- | :--- | :--- | :--- | :--- |
| `LOW` | 0.706 | 0.800 | **1.000** | **1.000** |
| `MEDIUM` | 0.400 | 0.333 | **1.000** | **1.000** |
| `BORDERLINE` | 0.444 | 0.400 | **1.000** | **1.000** |
| `HIGH` | 0.783 | 0.900 | **1.000** | **1.000** |

### Confusion Matrices

#### Baseline Scorer Confusion Matrix:
```text
           Pred_LOW  Pred_MED  Pred_BORD  Pred_HIGH
True_LOW         24         6          0          0
True_MED          9        10         10          1
True_BORD         1         7          8          4
True_HIGH         0         2          0         18
```

#### ML Random Forest Confusion Matrix:
```text
           Pred_LOW  Pred_MED  Pred_BORD  Pred_HIGH
True_LOW         30         0          0          0
True_MED          0        30          0          0
True_BORD         0         0         20          0
True_HIGH         0         0          0         20
```

---

## 8. Feature Importance

Top features identified by the Random Forest model:

| Rank | Feature | Importance | Interpretation |
| :--- | :--- | :--- | :--- |
| 1 | `credit_score` | **30.91%** | Strongest single predictor of credit discipline |
| 2 | `bank_balance` | **11.55%** | Liquid reserves buffer against unforeseen cash flow shocks |
| 3 | `monthly_expenses` | **10.89%** | Discretionary consumption burden on monthly net cash flow |
| 4 | `monthly_income` | **10.12%** | Primary debt-servicing baseline |
| 5 | `net_disposable_income` | **8.61%** | Free cash flow cushion after existing and prospective obligations |
| 6 | `dti_ratio` | **7.44%** | Total debt obligation burden relative to gross income |

---

## 9. Risk Score & Category Methodology

### Continuous Risk Score (0–100)
The normalized continuous score represents the expected risk severity under the model's predicted class probability distribution:

$$\text{Risk Score} = \sum_{c \in \text{Tiers}} P(c) \times W_c$$

where tier weights are:
- $W_{\text{LOW}} = 15.0$
- $W_{\text{MEDIUM}} = 45.0$
- $W_{\text{BORDERLINE}} = 65.0$
- $W_{\text{HIGH}} = 90.0$

Interpretation:
- `0–34`: Low modeled risk.
- `35–54`: Moderate modeled risk.
- `55–74`: Borderline / elevated risk requiring closer underwriting attention.
- `75–100`: High modeled risk.

### Categorical Risk Tier
Assigned via model probability `argmax` corresponding to `LOW`, `MEDIUM`, `HIGH`, or `BORDERLINE`.

---

## 10. Explainability & Factor Extraction

The `RiskRulesEngine` extracts qualitative explanations grounded in applicant numerical features:

### Risk Factors (Adverse Indicators)
- Credit score $< 600$ (Critical) or $< 650$ (Sub-prime).
- DTI ratio $> 60.0\%$ (High) or $> 45.0\%$ (Elevated).
- Loan-to-annual-income ratio $> 2.5\times$ (High leverage).
- Modest monthly earnings $< \text{INR } 40,000$.
- Thin liquid reserves covering $< 2$ months of debt obligations.
- Short employment tenure $< 2.0$ years.
- Self-employed income volatility.

### Protective Factors (Mitigating Indicators)
- Prime credit score $\ge 750$ or Good credit score $\ge 700$.
- Healthy DTI ratio $\le 35.0\%$.
- Conservative loan-to-annual-income $\le 1.0\times$.
- Substantial monthly cash flow $\ge \text{INR } 100,000$.
- Robust liquidity reserve $\ge 6$ months of debt obligations.
- Established career tenure $\ge 5.0$ years.
- Predictable salaried employment profile.

---

## 11. Artifacts & Reproducibility

Trained model artifacts are deterministically created and saved via `scripts/train_risk_model.py`:
- `models/risk_model.joblib`: Serialized Scikit-learn Random Forest model.
- `models/risk_model_metadata.json`: Feature list, hyper-parameters, cross-validation metrics, and feature importances.

To retrain the model from scratch:
```bash
python scripts/train_risk_model.py
```

To run the comparative evaluation:
```bash
python scripts/evaluate_risk_model.py
```

---

## 12. Testing & Quality Verification

All 87 tests in the project test suite pass cleanly:
```bash
$ .venv/bin/pytest tests/
============================== 87 passed in 4.45s ==============================

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/black --check .
All done! ✨ 🍰 ✨
58 files would be left unchanged.
```

---

## 13. Limitations & Responsible-Use Considerations

1. **Synthetic Nature**: The model is trained on controlled synthetic profiles. Real-world credit underwriting requires regulatory compliance (FCRA, Equal Credit Opportunity Act), demographic parity checks, and empirical default datasets.
2. **Explainability vs. Causality**: Feature importance reflects Gini impurity reduction across tree splits; it does not establish economic causality.
3. **No Autonomous Approvals**: This risk score is purely an input to decision-support pipelines. A human loan officer retains ultimate decisioning authority.
