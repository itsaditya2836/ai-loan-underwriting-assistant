"""Risk Assessment Evaluation Script for AI Loan Underwriting Assistant.

Compares:
1. Baseline Weighted Risk Scorer (Deterministic Heuristic)
2. Machine-Learning Risk Model (RandomForestClassifier)

Reports:
- Dataset characteristics and target distribution
- Model architecture, version, and training methodology
- Baseline vs ML Accuracy, Precision, Recall, and Macro-F1
- Multi-class Confusion Matrices
- Top feature importances
- Explicit synthetic data limitations
"""

import os
import sys
from typing import Any, Dict

import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.risk.features import extract_features
from app.risk.risk_model import TARGET_MAP, MLRiskModel
from app.risk.scoring import RiskScorer
from app.schemas.applicant import RiskLevel

DATASET_PATH = os.path.join("data", "synthetic_data", "applicants.csv")
METADATA_PATH = os.path.join("models", "risk_model_metadata.json")


def evaluate_models() -> Dict[str, Any]:
    """Evaluate and compare ML Risk Model vs Baseline Weighted Scorer."""
    if not os.path.exists(DATASET_PATH):
        raise FileNotFoundError(f"Dataset not found at {DATASET_PATH}")

    df = pd.read_csv(DATASET_PATH)
    y_true = df["profile_category"].map(TARGET_MAP)
    classes = [
        RiskLevel.LOW.value,
        RiskLevel.MEDIUM.value,
        RiskLevel.BORDERLINE.value,
        RiskLevel.HIGH.value,
    ]

    # Initialize models
    ml_model = MLRiskModel()
    baseline = RiskScorer()

    # Inference across full dataset
    ml_preds = []
    ml_scores = []
    base_preds = []
    base_scores = []

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        feats = extract_features(row_dict)

        # ML model
        m_score, m_cat, _ = ml_model.predict_risk(row_dict)
        ml_preds.append(m_cat.value)
        ml_scores.append(m_score)

        # Baseline model
        b_score, b_cat, _ = baseline.score_features(feats)
        base_preds.append(b_cat.value)
        base_scores.append(b_score)

    # 1. Metrics Computation
    ml_acc = accuracy_score(y_true, ml_preds)
    ml_f1 = f1_score(y_true, ml_preds, average="macro")
    ml_rep = classification_report(y_true, ml_preds, labels=classes, output_dict=True)
    ml_cm = confusion_matrix(y_true, ml_preds, labels=classes)

    base_acc = accuracy_score(y_true, base_preds)
    base_f1 = f1_score(y_true, base_preds, average="macro")
    base_rep = classification_report(
        y_true, base_preds, labels=classes, output_dict=True
    )
    base_cm = confusion_matrix(y_true, base_preds, labels=classes)

    # Print Formatted Report
    print("=" * 80)
    print("       STAGE 5 — RISK ASSESSMENT EVALUATION & BENCHMARK REPORT")
    print("=" * 80)
    print(f"Dataset:                    {DATASET_PATH} (N={len(df)})")
    print(
        "Target Attribute:           profile_category (Synthetic Risk Profile Classification)"
    )
    print(
        "Model Architecture:         RandomForestClassifier (n_estimators=50, max_depth=5)"
    )
    print(f"Model Version:              {ml_model.model_version}")
    print(
        "Baseline Architecture:      Heuristic Weighted Scorer (Credit: 40%, DTI: 30%, LTI: 20%, Buffer: 10%)"
    )
    print("-" * 80)

    print("\n[PART 1: TARGET CLASS DISTRIBUTION (N=100)]")
    for cls_name, count in y_true.value_counts().items():
        print(f"  * {cls_name:<14}: {count} ({count / len(y_true) * 100:.1f}%)")

    print("\n[PART 2: BENCHMARK COMPARISON (FULL DATASET N=100)]")
    print("-" * 80)
    print(f"{'Metric':<28} {'Baseline (Weighted)':<24} {'ML (Random Forest)':<24}")
    print("-" * 80)
    print(f"{'Overall Accuracy':<28} {base_acc * 100:.1f}%{'':<18} {ml_acc * 100:.1f}%")
    print(f"{'Macro-Average F1 Score':<28} {base_f1:.4f}{'':<18} {ml_f1:.4f}")
    print("-" * 80)

    print("\n[PART 3: PER-CLASS PERFORMANCE BREAKDOWN]")
    print("-" * 80)
    print(
        f"{'Tier':<14} {'Base Precision':<16} {'Base Recall':<14} {'ML Precision':<16} {'ML Recall':<14}"
    )
    print("-" * 80)
    for c in classes:
        bp = base_rep.get(c, {}).get("precision", 0.0)
        br = base_rep.get(c, {}).get("recall", 0.0)
        mp = ml_rep.get(c, {}).get("precision", 0.0)
        mr = ml_rep.get(c, {}).get("recall", 0.0)
        print(f"{c:<14} {bp:.3f}{'':<11} {br:.3f}{'':<9} {mp:.3f}{'':<11} {mr:.3f}")
    print("-" * 80)

    print("\n[PART 4: CONFUSION MATRICES (Classes: LOW, MEDIUM, BORDERLINE, HIGH)]")
    print("Baseline Scorer Confusion Matrix:")
    print(base_cm)
    print("\nML Random Forest Confusion Matrix:")
    print(ml_cm)

    print("\n[PART 5: TOP 5 ML FEATURE IMPORTANCE]")
    print("-" * 80)
    sorted_importances = sorted(
        ml_model.feature_importances.items(), key=lambda item: item[1], reverse=True
    )
    for i, (feat, imp) in enumerate(sorted_importances[:5], 1):
        print(f"  {i}. {feat:<24}: {imp:.4f} ({imp * 100:.1f}%)")

    print("\n" + "=" * 80)
    print("EVALUATION CONCLUSION & SCOPE VERIFICATION:")
    print(
        "1. Target represents synthetic risk profiles, not empirical default probabilities."
    )
    print(
        "2. Both ML and Baseline models operate fully locally without external APIs or LLMs."
    )
    print("3. No target leakage: target profile_category excluded from features.")
    print(
        "4. Stage 6 (Fraud / Anomaly) and Stage 8 (Loan Approval Decision) were NOT invoked."
    )
    print("=" * 80 + "\n")

    return {
        "dataset_size": len(df),
        "baseline_accuracy": base_acc,
        "baseline_f1_macro": base_f1,
        "ml_accuracy": ml_acc,
        "ml_f1_macro": ml_f1,
        "top_features": [f[0] for f in sorted_importances[:5]],
    }


if __name__ == "__main__":
    evaluate_models()
