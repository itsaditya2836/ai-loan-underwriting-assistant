"""Honest evaluation benchmark for the ML Risk Model and weighted baseline.

Separates cross-validation on the training split (N=80), in-sample training
fit (N=80, clearly marked as non-generalization), and held-out test evaluation
(N=20) using end-to-end inference via MLRiskModel.

Usage:
    python scripts/evaluate_risk_model.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.risk.feature_contract import (  # noqa: E402
    FEATURE_CONTRACT_VERSION,
    RISK_FEATURE_CONTRACT,
)
from app.risk.risk_model import (  # noqa: E402
    DEFAULT_METADATA_PATH,
    DEFAULT_MODEL_PATH,
    TARGET_MAP,
    MLRiskModel,
)
from app.risk.scoring import RiskScorer  # noqa: E402
from scripts.train_risk_model import (  # noqa: E402
    DEFAULT_DATASET_PATH,
    EXPECTED_CLASSES,
    load_and_validate_training_dataset,
    run_training_cv,
    split_dataset,
)


def _evaluate_ml_predictions(
    ml_model: MLRiskModel,
    records: Sequence[Dict[str, Any]],
    y_true: Sequence[str],
    class_labels: Sequence[str] = EXPECTED_CLASSES,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Run end-to-end MLRiskModel inference row-by-row and compute metrics."""
    y_pred: List[str] = []
    proba_rows: List[List[float]] = []
    misclassified: List[Dict[str, Any]] = []

    for record, true_label in zip(records, y_true):
        risk_score, risk_level, probs = ml_model.predict_risk(record)
        pred_label = risk_level.value
        y_pred.append(pred_label)
        proba_rows.append([float(probs.get(cls, 0.0)) for cls in class_labels])

        if pred_label != true_label:
            misclassified.append(
                {
                    "applicant_id": record.get("applicant_id"),
                    "true_label": true_label,
                    "predicted_label": pred_label,
                    "risk_score": round(float(risk_score), 2),
                    "probabilities": probs,
                }
            )

    y_true_list = list(y_true)
    labels = list(class_labels)
    y_proba = np.array(proba_rows, dtype=float)
    cm = confusion_matrix(y_true_list, y_pred, labels=labels)
    report = classification_report(
        y_true_list, y_pred, labels=labels, output_dict=True, zero_division=0
    )

    roc_auc_macro = None
    roc_auc_weighted = None
    if set(labels).issubset(set(y_true_list)):
        roc_auc_macro = round(
            float(
                roc_auc_score(
                    y_true_list,
                    y_proba,
                    multi_class="ovr",
                    average="macro",
                    labels=labels,
                )
            ),
            4,
        )
        roc_auc_weighted = round(
            float(
                roc_auc_score(
                    y_true_list,
                    y_proba,
                    multi_class="ovr",
                    average="weighted",
                    labels=labels,
                )
            ),
            4,
        )

    metrics = {
        "sample_count": len(y_true_list),
        "accuracy": round(float(accuracy_score(y_true_list, y_pred)), 4),
        "balanced_accuracy": round(
            float(balanced_accuracy_score(y_true_list, y_pred)), 4
        ),
        "precision_macro": round(
            float(
                precision_score(y_true_list, y_pred, average="macro", zero_division=0)
            ),
            4,
        ),
        "recall_macro": round(
            float(recall_score(y_true_list, y_pred, average="macro", zero_division=0)),
            4,
        ),
        "f1_macro": round(
            float(f1_score(y_true_list, y_pred, average="macro", zero_division=0)), 4
        ),
        "precision_weighted": round(
            float(
                precision_score(
                    y_true_list, y_pred, average="weighted", zero_division=0
                )
            ),
            4,
        ),
        "recall_weighted": round(
            float(
                recall_score(y_true_list, y_pred, average="weighted", zero_division=0)
            ),
            4,
        ),
        "f1_weighted": round(
            float(f1_score(y_true_list, y_pred, average="weighted", zero_division=0)), 4
        ),
        "roc_auc_ovr_macro": roc_auc_macro,
        "roc_auc_ovr_weighted": roc_auc_weighted,
        "confusion_matrix_labels": labels,
        "confusion_matrix": cm.tolist(),
        "classification_report": report,
    }
    return metrics, misclassified


def _evaluate_baseline(
    scorer: RiskScorer,
    records: Sequence[Dict[str, Any]],
    y_true: Sequence[str],
    class_labels: Sequence[str] = EXPECTED_CLASSES,
) -> Dict[str, Any]:
    """Evaluate deterministic weighted baseline RiskScorer on the same partition."""
    y_pred: List[str] = []
    for record in records:
        feats = RISK_FEATURE_CONTRACT.extract(record)
        _, risk_level, _ = scorer.score_features(feats)
        y_pred.append(risk_level.value)

    y_true_list = list(y_true)
    labels = list(class_labels)
    cm = confusion_matrix(y_true_list, y_pred, labels=labels)
    return {
        "sample_count": len(y_true_list),
        "accuracy": round(float(accuracy_score(y_true_list, y_pred)), 4),
        "balanced_accuracy": round(
            float(balanced_accuracy_score(y_true_list, y_pred)), 4
        ),
        "f1_macro": round(
            float(f1_score(y_true_list, y_pred, average="macro", zero_division=0)), 4
        ),
        "f1_weighted": round(
            float(f1_score(y_true_list, y_pred, average="weighted", zero_division=0)),
            4,
        ),
        "confusion_matrix_labels": labels,
        "confusion_matrix": cm.tolist(),
    }


def _print_confusion_matrix(
    labels: Sequence[str], matrix: Sequence[Sequence[int]]
) -> None:
    """Format confusion matrix neatly for terminal readability."""
    header = "Actual \\ Pred".ljust(14) + " ".join(lbl.rjust(11) for lbl in labels)
    print(f"    {header}")
    for label, row in zip(labels, matrix):
        cells = " ".join(str(val).rjust(11) for val in row)
        print(f"    {label.ljust(14)}{cells}")


def evaluate_models(
    dataset_path: str = DEFAULT_DATASET_PATH,
    model_path: str = DEFAULT_MODEL_PATH,
    metadata_path: str = DEFAULT_METADATA_PATH,
) -> Dict[str, Any]:
    """Run honest Train / CV / Held-Out Test evaluation against persisted artifacts."""
    if not os.path.exists(metadata_path):
        raise FileNotFoundError(f"Model metadata not found: {metadata_path}")

    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    df, X, y, applicant_ids = load_and_validate_training_dataset(
        dataset_path=dataset_path,
        feature_contract=RISK_FEATURE_CONTRACT,
    )

    split_cfg = metadata.get("split_strategy", {})
    test_size = float(split_cfg.get("test_size", 0.20))
    random_state = int(split_cfg.get("random_state", 42))
    cv_folds = int(metadata.get("cv_folds", 5))

    X_train, X_test, y_train, y_test, train_ids, test_ids = split_dataset(
        X=X,
        y=y,
        applicant_ids=applicant_ids,
        test_size=test_size,
        random_state=random_state,
    )

    expected_train_ids = metadata.get("train_applicant_ids")
    expected_test_ids = metadata.get("test_applicant_ids")
    if expected_train_ids and train_ids != expected_train_ids:
        raise ValueError(
            "Reproduced train_applicant_ids do not match saved model metadata!"
        )
    if expected_test_ids and test_ids != expected_test_ids:
        raise ValueError(
            "Reproduced test_applicant_ids do not match saved model metadata!"
        )

    ml_model = MLRiskModel(
        model_path=model_path,
        metadata_path=metadata_path,
        feature_contract=RISK_FEATURE_CONTRACT,
    )
    scorer = RiskScorer()

    df_by_id = df.set_index("applicant_id")
    train_records = [
        {
            k: (None if pd.isna(v) else v)
            for k, v in {
                **df_by_id.loc[app_id].to_dict(),
                "applicant_id": app_id,
            }.items()
        }
        for app_id in train_ids
    ]
    test_records = [
        {
            k: (None if pd.isna(v) else v)
            for k, v in {
                **df_by_id.loc[app_id].to_dict(),
                "applicant_id": app_id,
            }.items()
        }
        for app_id in test_ids
    ]

    train_y_list = [
        TARGET_MAP[str(df_by_id.loc[i, "profile_category"])] for i in train_ids
    ]
    test_y_list = [
        TARGET_MAP[str(df_by_id.loc[i, "profile_category"])] for i in test_ids
    ]

    cv_recomputed = run_training_cv(
        pipeline=ml_model.model,
        X_train=X_train,
        y_train=y_train,
        cv_folds=cv_folds,
        random_state=random_state,
    )
    train_metrics, _ = _evaluate_ml_predictions(
        ml_model, train_records, train_y_list, EXPECTED_CLASSES
    )
    test_metrics, test_errors = _evaluate_ml_predictions(
        ml_model, test_records, test_y_list, EXPECTED_CLASSES
    )
    baseline_test_metrics = _evaluate_baseline(
        scorer, test_records, test_y_list, EXPECTED_CLASSES
    )

    print("=" * 72)
    print("AI LOAN UNDERWRITING — HONEST RISK MODEL EVALUATION REPORT")
    print("=" * 72)
    print(f"Model Artifact   : {model_path} ({metadata.get('model_version')})")
    print(
        f"Feature Contract : {FEATURE_CONTRACT_VERSION} ({len(RISK_FEATURE_CONTRACT.feature_names)} features)"
    )
    print(f"Dataset          : {dataset_path} (Total N={len(df)})")
    print(
        f"Split Integrity  : Verified disjoint Train={len(train_ids)} / Test={len(test_ids)}"
    )
    print()

    print(
        f"[1] {cv_folds}-Fold Stratified CV on Training Split ONLY (N={len(train_ids)}):"
    )
    print(
        f"    Accuracy          : {cv_recomputed['accuracy_mean']:.4f} +/- {cv_recomputed['accuracy_std']:.4f}"
    )
    print(
        f"    Balanced Accuracy : {cv_recomputed['balanced_accuracy_mean']:.4f} +/- {cv_recomputed['balanced_accuracy_std']:.4f}"
    )
    print(
        f"    Macro F1          : {cv_recomputed['f1_macro_mean']:.4f} +/- {cv_recomputed['f1_macro_std']:.4f}"
    )
    print(
        f"    Weighted F1       : {cv_recomputed['f1_weighted_mean']:.4f} +/- {cv_recomputed['f1_weighted_std']:.4f}"
    )
    print()

    print(f"[2] Training Split In-Sample Fit (N={len(train_ids)}, NOT Generalization):")
    print(
        f"    Accuracy={train_metrics['accuracy']:.4f}, "
        f"Balanced={train_metrics['balanced_accuracy']:.4f}, "
        f"Macro F1={train_metrics['f1_macro']:.4f}"
    )
    print()

    print(
        f"[3] Held-Out Test Split Evaluation via MLRiskModel (N={len(test_ids)}, Unseen):"
    )
    print(f"    Accuracy          : {test_metrics['accuracy']:.4f}")
    print(f"    Balanced Accuracy : {test_metrics['balanced_accuracy']:.4f}")
    print(
        f"    Macro P/R/F1      : {test_metrics['precision_macro']:.4f} / "
        f"{test_metrics['recall_macro']:.4f} / {test_metrics['f1_macro']:.4f}"
    )
    print(
        f"    Weighted P/R/F1   : {test_metrics['precision_weighted']:.4f} / "
        f"{test_metrics['recall_weighted']:.4f} / {test_metrics['f1_weighted']:.4f}"
    )
    print(
        f"    OVR ROC-AUC       : macro={test_metrics['roc_auc_ovr_macro']}, "
        f"weighted={test_metrics['roc_auc_ovr_weighted']}"
    )
    print("    Per-Class Report (Held-Out Test):")
    for cls in EXPECTED_CLASSES:
        row = test_metrics["classification_report"][cls]
        print(
            f"      {cls:<11} P={row['precision']:.4f}  R={row['recall']:.4f}  "
            f"F1={row['f1-score']:.4f}  support={row['support']}"
        )
    print("    Confusion Matrix (Held-Out Test):")
    _print_confusion_matrix(
        test_metrics["confusion_matrix_labels"], test_metrics["confusion_matrix"]
    )
    if test_errors:
        print("    Held-Out Misclassifications:")
        for err in test_errors:
            print(
                f"      - {err['applicant_id']}: true={err['true_label']}, "
                f"pred={err['predicted_label']}, score={err['risk_score']}"
            )
    print()

    print(
        f"[4] Deterministic Baseline (RiskScorer) on Held-Out Test Split (N={len(test_ids)}):"
    )
    print(f"    Accuracy          : {baseline_test_metrics['accuracy']:.4f}")
    print(f"    Balanced Accuracy : {baseline_test_metrics['balanced_accuracy']:.4f}")
    print(f"    Macro F1          : {baseline_test_metrics['f1_macro']:.4f}")
    print(f"    Weighted F1       : {baseline_test_metrics['f1_weighted']:.4f}")
    print("    Confusion Matrix (Baseline on Held-Out Test):")
    _print_confusion_matrix(
        baseline_test_metrics["confusion_matrix_labels"],
        baseline_test_metrics["confusion_matrix"],
    )
    print()
    print(f"Note: {metadata.get('dataset_synthetic_notice', '')}")
    print("=" * 72)

    return {
        "cv_metrics": cv_recomputed,
        "train_metrics": train_metrics,
        "test_metrics": test_metrics,
        "baseline_test_metrics": baseline_test_metrics,
        "test_misclassified": test_errors,
    }


if __name__ == "__main__":
    evaluate_models()
