"""Model Training Script for AI Loan Underwriting Assistant.

Trains a local, reproducible RandomForestClassifier on the synthetic applicant
dataset to perform synthetic risk profile classification across 4 tiers:
- LOW
- MEDIUM
- HIGH
- BORDERLINE

Saves model artifact to models/risk_model.joblib and training metadata to
models/risk_model_metadata.json.
"""

import json
import os
import sys
from typing import Any, Dict

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.risk.features import RISK_FEATURE_NAMES, extract_features
from app.risk.risk_model import TARGET_MAP

DATASET_PATH = os.path.join("data", "synthetic_data", "applicants.csv")
MODEL_DIR = "models"
MODEL_PATH = os.path.join(MODEL_DIR, "risk_model.joblib")
METADATA_PATH = os.path.join(MODEL_DIR, "risk_model_metadata.json")
RANDOM_STATE = 42


def train_risk_model() -> Dict[str, Any]:
    """Train and evaluate Random Forest risk model on synthetic applicants."""
    print("=" * 80)
    print("       STAGE 5 — RISK ASSESSMENT MODEL TRAINING PIPELINE")
    print("=" * 80)

    if not os.path.exists(DATASET_PATH):
        raise FileNotFoundError(f"Training dataset not found at {DATASET_PATH}")

    df = pd.read_csv(DATASET_PATH)
    print(f"Loaded dataset: {DATASET_PATH} (N={len(df)} applicants)")

    # 1. Target Construction & Leakage Check
    y = df["profile_category"].map(TARGET_MAP)
    print("\nTarget Class Distribution:")
    for cls_name, count in y.value_counts().items():
        print(f"  * {cls_name:<12}: {count} ({count / len(y) * 100:.1f}%)")

    # 2. Feature Extraction (No Target Leakage)
    X_rows = [extract_features(row.to_dict()) for _, row in df.iterrows()]
    X = pd.DataFrame(X_rows)[RISK_FEATURE_NAMES]
    print(f"\nEngineered {len(RISK_FEATURE_NAMES)} features:")
    for f in RISK_FEATURE_NAMES:
        print(f"  - {f}")

    # 3. Stratified Train / Test Split (80 / 20)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=RANDOM_STATE, stratify=y
    )
    print(f"\nSplit: Training set = {len(X_train)}, Holdout test set = {len(X_test)}")

    # 4. Model Training
    clf = RandomForestClassifier(
        n_estimators=50,
        max_depth=5,
        min_samples_split=2,
        random_state=RANDOM_STATE,
    )

    # 5. 5-Fold Stratified Cross Validation
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE)
    cv_scores = cross_val_score(clf, X, y, cv=cv, scoring="accuracy")
    cv_f1 = cross_val_score(clf, X, y, cv=cv, scoring="f1_macro")
    print("\n5-Fold Stratified Cross-Validation:")
    print(f"  * Accuracy: {cv_scores.mean():.4f} (+/- {cv_scores.std():.4f})")
    print(f"  * F1 Macro: {cv_f1.mean():.4f} (+/- {cv_f1.std():.4f})")

    # Fit on training split
    clf.fit(X_train, y_train)

    # 6. Evaluation on Test Split
    y_pred = clf.predict(X_test)
    report_dict = classification_report(y_test, y_pred, output_dict=True)
    report_str = classification_report(y_test, y_pred)
    cm = confusion_matrix(y_test, y_pred, labels=sorted(list(set(y))))

    print("\nHoldout Test Evaluation:")
    print(report_str)
    print("Confusion Matrix:")
    print(cm)

    # Fit final model on full dataset for maximum utility and stability
    clf.fit(X, y)

    # 7. Feature Importances
    importances = {
        feat: round(float(imp), 4)
        for feat, imp in zip(RISK_FEATURE_NAMES, clf.feature_importances_)
    }
    sorted_importances = dict(
        sorted(importances.items(), key=lambda item: item[1], reverse=True)
    )

    print("\nTop 5 Most Important Features:")
    for i, (feat, imp) in enumerate(list(sorted_importances.items())[:5], 1):
        print(f"  {i}. {feat:<24}: {imp:.4f} ({imp * 100:.1f}%)")

    # 8. Save Artifacts
    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(clf, MODEL_PATH)

    metadata = {
        "model_version": "risk_model_rf_v1",
        "model_type": "RandomForestClassifier",
        "random_state": RANDOM_STATE,
        "n_estimators": 50,
        "max_depth": 5,
        "dataset": DATASET_PATH,
        "total_samples": len(df),
        "feature_names": RISK_FEATURE_NAMES,
        "cv_accuracy_mean": round(float(cv_scores.mean()), 4),
        "cv_f1_macro_mean": round(float(cv_f1.mean()), 4),
        "test_accuracy": round(float(report_dict["accuracy"]), 4),
        "test_f1_macro": round(float(report_dict["macro avg"]["f1-score"]), 4),
        "feature_importances": sorted_importances,
    }

    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"\nModel artifact saved to:   {MODEL_PATH}")
    print(f"Model metadata saved to:   {METADATA_PATH}")
    print("=" * 80 + "\n")

    return metadata


if __name__ == "__main__":
    train_risk_model()
