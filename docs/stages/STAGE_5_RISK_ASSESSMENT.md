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
- **`app/risk/feature_contract.py`**: Authoritative `RISK_FEATURE_CONTRACT` (`risk_features_v2`) defining the canonical 15 ordered features, strict required-field validation, and missing-value policies (`None` -> `np.nan` for median imputation).
- **`app/risk/features.py`**: Backward-compatible adapter delegating feature extraction cleanly to `RISK_FEATURE_CONTRACT`.
- **`app/risk/risk_model.py`**: Fail-fast loader and inference wrapper for the local Scikit-learn `Pipeline(SimpleImputer(median) + RandomForestClassifier)` artifact, validating feature order and metadata contracts on load.
- **`app/risk/scoring.py`**: Deterministic weighted heuristic baseline scorer (`RiskScorer`, usable directly via `RiskAgent(use_ml=False)`).
- **`app/risk/rules.py`**: Heuristic factor extraction engine producing human-readable risk and protective factors while safely skipping unprovided optional attributes.

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

## 5. Feature Engineering, Contract & Leakage Prevention

### Shared Feature Contract (`risk_features_v2`)
Training, cross-validation, held-out evaluation, and runtime inference (`Applicant` and `DocumentPackageResult`) all read from the single authoritative contract defined in `app/risk/feature_contract.py` (`RISK_FEATURE_CONTRACT`).
To prevent data leakage and protected-attribute misuse, target-derived or sensitive columns (`profile_category`, `risk_category`, `risk_score`, `applicant_id`, `name`, `gender`, `employer_name`, `city`, `total_monthly_obligations`) are strictly excluded from the feature matrix, while explicit zero values (`0`, `0.0`), `monthly_expenses`, and `number_of_dependents` are preserved without falsy coercion:

1. `age`: Applicant age in years (required, `18–100`).
2. `employment_years`: Career stability in years (optional, `>= 0.0`; `None` -> median-imputed in `Pipeline`).
3. `monthly_income`: Net monthly verified income in INR (required, `> 0.0`).
4. `existing_emi`: Ongoing monthly debt obligations in INR (optional, `>= 0.0`; defaults to `0.0`).
5. `loan_amount`: Requested loan principal in INR (required, `> 0.0`).
6. `loan_tenure`: Requested loan duration in months (required, `> 0`).
7. `credit_score`: Bureau credit score (required, `300–900`).
8. `bank_balance`: Liquid bank balance in INR (optional, `>= 0.0`; `None` -> median-imputed in `Pipeline`).
9. `monthly_expenses`: Declared monthly living expenses in INR (optional, `>= 0.0`; preserved on runtime `Applicant`, `None` -> median-imputed in `Pipeline`).
10. `number_of_dependents`: Family dependents (optional, `0–20`; preserved on runtime `Applicant`, `None` -> median-imputed in `Pipeline`).
11. `estimated_new_emi`: Monthly installment for the requested loan calculated via standard amortization.
12. `dti_ratio`: Debt-to-Income / FOIR ratio: `((existing_emi + estimated_new_emi) / monthly_income) * 100`.
13. `loan_to_income_ratio`: Leverage ratio: `loan_amount / (monthly_income * 12)`.
14. `net_disposable_income`: Unallocated monthly cash flow: `monthly_income - existing_emi - estimated_new_emi - monthly_expenses` (`None` if `monthly_expenses` is absent, then median-imputed in `Pipeline`).
15. `is_salaried`: Binary indicator (`1.0` for Salaried, `0.0` for Self-Employed; `None` if omitted).

### Amortization Formula
New EMI estimation uses the standard retail lending amortization formula:
$$\text{EMI} = P \times r \times \frac{(1+r)^n}{(1+r)^n - 1}$$
with $r = 0.105 / 12$ (10.5% annual benchmark interest rate).

---

## 6. Model Selection

### Primary Model: Scikit-learn Imputation + Random Forest Pipeline (`risk_model_rf_v2`)
- **Pipeline**: `Pipeline([("imputer", SimpleImputer(strategy="median")), ("classifier", RandomForestClassifier(n_estimators=50, max_depth=5, min_samples_split=2, random_state=42))])`
- **Training & Split Discipline**: Fitted **strictly on the stratified 80% training split** (`N=80`, `random_state=42`); 5-fold stratified cross-validation runs solely within the 80 training records; the 20 held-out test records remain unseen during both imputer fitting and classifier training.
- **Rationale**:
  - Leakage-free missing optional value imputation (`SimpleImputer(strategy="median")` learned only on `X_train`).
  - Fully local, lightweight, and deterministic under fixed random seed (`random_state=42`).
  - Native handling of non-linear financial ratios (DTI vs. credit score) and well-behaved multi-class probability distributions.
  - Exposes transparent Gini feature importances and validates feature contracts on artifact load (fail-fast `RiskModelLoadError` / `RiskModelContractError` instead of silent auto-training or default fallbacks).

### Baseline Model: Domain-Weighted Heuristic Scorer
A transparent, rule-based baseline weighting credit metrics:
- **Credit Score (40%)**: Prime (10 pts) to Sub-prime (95 pts)
- **DTI Ratio (30%)**: Healthy <= 30% (10 pts) to Elevated > 60% (95 pts)
- **Loan-to-Income (20%)**: <= 1.0x (10 pts) to > 2.5x (85 pts)
- **Liquidity Buffer (10%)**: >= 6 months EMI (10 pts) to < 2 months EMI (80 pts)

$$\text{Composite} = 0.40 \times C_{\text{score}} + 0.30 \times DTI + 0.20 \times LTI + 0.10 \times Buffer$$

---

## 7. Model Evaluation & Benchmark Results

All partitions are reported separately to prevent training/test leakage:

### 5-Fold Stratified Cross-Validation on Training Split ONLY (`N=80`)

| Metric | Mean +/- Std |
| :--- | :--- |
| **CV Accuracy** | **0.9625 +/- 0.0306** |
| **CV Balanced Accuracy** | **0.9542 +/- 0.0382** |
| **CV Macro F1-Score** | **0.9530 +/- 0.0392** |
| **CV Weighted F1-Score** | **0.9616 +/- 0.0314** |

> *In-sample Training Fit (`N=80`, NOT for generalization): Accuracy `1.0000`, Balanced Accuracy `1.0000`, Macro F1 `1.0000`.*

### Held-Out Test Split Benchmark (`N=20`, Unseen During Training)

| Metric | Baseline (`RiskScorer`) | ML (`risk_model_rf_v2`) |
| :--- | :--- | :--- |
| **Accuracy** | 0.6000 (`12/20`) | **0.9500** (`19/20`) |
| **Balanced Accuracy** | 0.5833 | **0.9375** |
| **Macro F1-Score** | 0.5655 | **0.9365** |
| **Weighted F1-Score** | 0.5786 | **0.9492** |
| **Multi-Class OVR ROC-AUC (Macro / Weighted)** | N/A | **1.0000 / 1.0000** |

### Per-Class Held-Out Test Report (`risk_model_rf_v2`, `N=20`)

| Risk Tier | Precision | Recall | F1-Score | Support |
| :--- | :--- | :--- | :--- | :--- |
| `BORDERLINE` | 0.8000 | 1.0000 | 0.8889 | 4 |
| `HIGH` | 1.0000 | 0.7500 | 0.8571 | 4 |
| `LOW` | 1.0000 | 1.0000 | 1.0000 | 6 |
| `MEDIUM` | 1.0000 | 1.0000 | 1.0000 | 6 |

*(The single held-out misclassification is `APP0012`: true `HIGH`, predicted `BORDERLINE`, risk score `68.93`.)*

### Confusion Matrices (Held-Out Test Split `N=20`)

#### Baseline Scorer Confusion Matrix (`N=20`):
```text
Actual \ Pred  BORDERLINE        HIGH         LOW      MEDIUM
BORDERLINE              0           0           0           4
HIGH                    0           4           0           0
LOW                     0           0           5           1
MEDIUM                  2           0           1           3
```

#### ML Pipeline Confusion Matrix (`N=20`):
```text
Actual \ Pred  BORDERLINE        HIGH         LOW      MEDIUM
BORDERLINE              4           0           0           0
HIGH                    1           3           0           0
LOW                     0           0           6           0
MEDIUM                  0           0           0           6
```

---

## 8. Feature Importance

Top features identified by the fitted Random Forest on the 80-applicant training split:

| Rank | Feature | Importance | Interpretation |
| :--- | :--- | :--- | :--- |
| 1 | `credit_score` | **27.15%** | Strongest single predictor of credit discipline |
| 2 | `monthly_expenses` | **12.96%** | Discretionary consumption burden on monthly net cash flow |
| 3 | `bank_balance` | **11.52%** | Liquid reserves buffer against unforeseen cash flow shocks |
| 4 | `monthly_income` | **10.95%** | Primary debt-servicing baseline |
| 5 | `net_disposable_income` | **8.74%** | Free cash flow cushion after existing and prospective obligations |
| 6 | `employment_years` | **6.60%** | Career and earning stability tenure |

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
- `models/risk_model.joblib`: Serialized Scikit-learn `Pipeline(SimpleImputer(median) + RandomForestClassifier)` fit strictly on the 80-applicant training split.
- `models/risk_model_metadata.json`: Feature contract schema (`risk_features_v2`), dataset SHA-256 hash, environment versions, disjoint `train_applicant_ids` / `test_applicant_ids`, imputer medians, hyper-parameters, separate CV/train/test metrics, and feature importances.

To validate the dataset and ML artifacts, retrain the model, or run the comparative evaluation:
```bash
.venv/bin/python scripts/validate_dataset.py
.venv/bin/python scripts/train_risk_model.py
.venv/bin/python scripts/evaluate_risk_model.py
```

---

## 12. Testing & Quality Verification

Verify the full test suite (using an isolated temporary SQLite DB path) and formatting/lint checks with:
```bash
DATABASE_URL="sqlite:////tmp/test_audit.db" .venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/black --check .
```

---

## 13. Limitations & Responsible-Use Considerations

1. **Synthetic Nature**: The model is trained on controlled synthetic profiles. Real-world credit underwriting requires regulatory compliance (FCRA, Equal Credit Opportunity Act), demographic parity checks, and empirical default datasets.
2. **Explainability vs. Causality**: Feature importance reflects Gini impurity reduction across tree splits; it does not establish economic causality.
3. **No Autonomous Approvals**: This risk score is purely an input to decision-support pipelines. A human loan officer retains ultimate decisioning authority.
