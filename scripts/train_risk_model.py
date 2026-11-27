"""Reproducible training script for the AI Loan Underwriting ML Risk Model.

Trains a scikit-learn Pipeline (median imputation + RandomForestClassifier) using
the shared RiskFeatureContract, a stratified 80/20 train/test split, and
5-fold stratified cross-validation restricted strictly to the training split.

Usage:
    python scripts/train_risk_model.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import joblib
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
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
from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split
from sklearn.pipeline import Pipeline

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.risk.feature_contract import (  # noqa: E402
    RISK_FEATURE_CONTRACT,
    RiskFeatureContract,
)
from app.risk.risk_model import TARGET_MAP  # noqa: E402

DEFAULT_DATASET_PATH = os.path.join(
    PROJECT_ROOT, "data", "synthetic_data", "applicants.csv"
)
DEFAULT_MODEL_PATH = os.path.join(PROJECT_ROOT, "models", "risk_model.joblib")
DEFAULT_METADATA_PATH = os.path.join(PROJECT_ROOT, "models", "risk_model_metadata.json")

MODEL_VERSION = "risk_model_rf_v2"
RANDOM_STATE = 42
TEST_SIZE = 0.20
CV_FOLDS = 5
EXPECTED_CLASSES = ["BORDERLINE", "HIGH", "LOW", "MEDIUM"]

REQUIRED_DATASET_COLUMNS = [
    "applicant_id",
    "age",
    "employment_type",
    "employment_years",
    "monthly_income",
    "existing_emi",
    "loan_amount",
    "loan_tenure",
    "credit_score",
    "bank_balance",
    "monthly_expenses",
    "number_of_dependents",
    "profile_category",
]

EXCLUDED_FROM_FEATURES = {
    "applicant_id",
    "name",
    "gender",
    "employer_name",
    "city",
    "profile_category",
    "total_monthly_obligations",
}

SYNTHETIC_DATASET_NOTICE = (
    "Trained on a small synthetic dataset of 100 generated applicant profiles "
    "(80 training / 20 held-out test). Metrics reflect consistency on this "
    "synthetic cohort and must not be represented as real-world credit performance."
)


def compute_file_sha256(file_path: str) -> str:
    """Compute the SHA-256 hex digest for a dataset or artifact file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _format_repo_relative_path(path: str) -> str:
    """Return a clean repo-relative path when inside PROJECT_ROOT."""
    abs_path = os.path.abspath(path)
    try:
        rel_path = os.path.relpath(abs_path, PROJECT_ROOT)
    except ValueError:
        return abs_path
    if not rel_path.startswith(".."):
        return rel_path
    return abs_path


def _check_leakage_and_sensitive_exclusions(
    feature_contract: RiskFeatureContract,
) -> None:
    """Verify target labels, IDs, and sensitive attributes are absent from features."""
    forbidden_present = EXCLUDED_FROM_FEATURES.intersection(
        feature_contract.feature_names
    )
    if forbidden_present:
        raise ValueError(
            f"Forbidden or leaky columns present in feature contract: "
            f"{sorted(forbidden_present)}"
        )


def load_and_validate_training_dataset(
    dataset_path: str = DEFAULT_DATASET_PATH,
    feature_contract: RiskFeatureContract = RISK_FEATURE_CONTRACT,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, List[str]]:
    """Load and validate CSV applicant data, returning raw df, X, y, and IDs."""
    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"Training dataset not found: {dataset_path}")

    df = pd.read_csv(dataset_path)
    if df.empty:
        raise ValueError(f"Training dataset is empty: {dataset_path}")

    missing_cols = [col for col in REQUIRED_DATASET_COLUMNS if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Training dataset missing required columns: {missing_cols}")

    if df["applicant_id"].isna().any():
        raise ValueError("Training dataset contains null applicant_id values.")
    if df["applicant_id"].duplicated().any():
        dups = df.loc[df["applicant_id"].duplicated(), "applicant_id"].tolist()
        raise ValueError(f"Training dataset contains duplicate applicant_ids: {dups}")

    if df.duplicated().any():
        raise ValueError("Training dataset contains exact duplicate rows.")

    if df["profile_category"].isna().any():
        raise ValueError("Training dataset contains null profile_category targets.")

    invalid_targets = sorted(
        set(df["profile_category"].astype(str).unique()) - set(TARGET_MAP.keys())
    )
    if invalid_targets:
        raise ValueError(
            f"Training dataset contains invalid profile_category labels: "
            f"{invalid_targets}"
        )

    _check_leakage_and_sensitive_exclusions(feature_contract)

    feature_rows: List[Dict[str, Optional[float]]] = []
    for _, row in df.iterrows():
        record = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        feature_rows.append(feature_contract.extract(record))

    X = feature_contract.to_dataframe(feature_rows)
    y = df["profile_category"].astype(str).map(TARGET_MAP)
    applicant_ids = df["applicant_id"].astype(str).tolist()
    return df, X, y, applicant_ids


def split_dataset(
    X: pd.DataFrame,
    y: pd.Series,
    applicant_ids: Sequence[str],
    test_size: float = TEST_SIZE,
    random_state: int = RANDOM_STATE,
) -> Tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.Series,
    pd.Series,
    List[str],
    List[str],
]:
    """Perform a reproducible stratified train/test split preserving IDs."""
    X_train, X_test, y_train, y_test, train_ids, test_ids = train_test_split(
        X,
        y,
        list(applicant_ids),
        test_size=test_size,
        random_state=random_state,
        stratify=y,
    )
    if not set(train_ids).isdisjoint(set(test_ids)):
        raise RuntimeError("Train and test applicant splits overlap.")
    return (
        X_train.reset_index(drop=True),
        X_test.reset_index(drop=True),
        y_train.reset_index(drop=True),
        y_test.reset_index(drop=True),
        list(train_ids),
        list(test_ids),
    )


def build_training_pipeline(random_state: int = RANDOM_STATE) -> Pipeline:
    """Create the imputation + RandomForest training pipeline."""
    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            (
                "classifier",
                RandomForestClassifier(
                    n_estimators=50,
                    max_depth=5,
                    min_samples_split=2,
                    random_state=random_state,
                ),
            ),
        ]
    )


def run_training_cv(
    pipeline: Pipeline,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    cv_folds: int = CV_FOLDS,
    random_state: int = RANDOM_STATE,
) -> Dict[str, Any]:
    """Run stratified cross-validation strictly on the training split."""
    min_class_count = int(y_train.value_counts().min())
    if min_class_count < cv_folds:
        raise ValueError(
            f"Cannot run {cv_folds}-fold stratified CV with minimum training "
            f"class count {min_class_count}."
        )

    cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=random_state)
    scores = cross_validate(
        clone(pipeline),
        X_train,
        y_train,
        cv=cv,
        scoring={
            "accuracy": "accuracy",
            "balanced_accuracy": "balanced_accuracy",
            "f1_macro": "f1_macro",
            "f1_weighted": "f1_weighted",
        },
        return_train_score=False,
    )

    return {
        "cv_folds": cv_folds,
        "sample_count": int(len(X_train)),
        "accuracy_mean": round(float(scores["test_accuracy"].mean()), 4),
        "accuracy_std": round(float(scores["test_accuracy"].std()), 4),
        "balanced_accuracy_mean": round(
            float(scores["test_balanced_accuracy"].mean()), 4
        ),
        "balanced_accuracy_std": round(
            float(scores["test_balanced_accuracy"].std()), 4
        ),
        "f1_macro_mean": round(float(scores["test_f1_macro"].mean()), 4),
        "f1_macro_std": round(float(scores["test_f1_macro"].std()), 4),
        "f1_weighted_mean": round(float(scores["test_f1_weighted"].mean()), 4),
        "f1_weighted_std": round(float(scores["test_f1_weighted"].std()), 4),
        "per_fold_accuracy": [
            round(float(v), 4) for v in scores["test_accuracy"].tolist()
        ],
        "per_fold_f1_macro": [
            round(float(v), 4) for v in scores["test_f1_macro"].tolist()
        ],
    }


def _round_classification_report(report_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Round floating-point entries in sklearn's dict classification report."""
    rounded: Dict[str, Any] = {}
    for label, entry in report_dict.items():
        if isinstance(entry, dict):
            rounded[str(label)] = {
                k: (round(float(v), 4) if isinstance(v, float) else int(v))
                for k, v in entry.items()
            }
        else:
            rounded[str(label)] = round(float(entry), 4)
    return rounded


def evaluate_partition(
    pipeline: Pipeline,
    X_part: pd.DataFrame,
    y_part: pd.Series,
    class_labels: Sequence[str] = EXPECTED_CLASSES,
) -> Dict[str, Any]:
    """Compute honest multi-class classification metrics on a single partition."""
    labels = list(class_labels)
    y_pred = pipeline.predict(X_part)
    y_proba = pipeline.predict_proba(X_part)

    cm = confusion_matrix(y_part, y_pred, labels=labels)
    report = _round_classification_report(
        classification_report(
            y_part,
            y_pred,
            labels=labels,
            output_dict=True,
            zero_division=0,
        )
    )

    roc_auc_macro: Optional[float] = None
    roc_auc_weighted: Optional[float] = None
    pipeline_classes = [str(c) for c in pipeline.classes_]
    if set(pipeline_classes).issubset(set(y_part.astype(str).unique())):
        roc_auc_macro = round(
            float(
                roc_auc_score(
                    y_part,
                    y_proba,
                    multi_class="ovr",
                    average="macro",
                    labels=pipeline_classes,
                )
            ),
            4,
        )
        roc_auc_weighted = round(
            float(
                roc_auc_score(
                    y_part,
                    y_proba,
                    multi_class="ovr",
                    average="weighted",
                    labels=pipeline_classes,
                )
            ),
            4,
        )

    return {
        "sample_count": int(len(X_part)),
        "accuracy": round(float(accuracy_score(y_part, y_pred)), 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(y_part, y_pred)), 4),
        "precision_macro": round(
            float(precision_score(y_part, y_pred, average="macro", zero_division=0)),
            4,
        ),
        "recall_macro": round(
            float(recall_score(y_part, y_pred, average="macro", zero_division=0)),
            4,
        ),
        "f1_macro": round(
            float(f1_score(y_part, y_pred, average="macro", zero_division=0)),
            4,
        ),
        "precision_weighted": round(
            float(precision_score(y_part, y_pred, average="weighted", zero_division=0)),
            4,
        ),
        "recall_weighted": round(
            float(recall_score(y_part, y_pred, average="weighted", zero_division=0)),
            4,
        ),
        "f1_weighted": round(
            float(f1_score(y_part, y_pred, average="weighted", zero_division=0)),
            4,
        ),
        "roc_auc_ovr_macro": roc_auc_macro,
        "roc_auc_ovr_weighted": roc_auc_weighted,
        "confusion_matrix_labels": labels,
        "confusion_matrix": cm.tolist(),
        "classification_report": report,
    }


def _print_training_summary(metadata: Dict[str, Any]) -> None:
    """Print an honest human-readable summary of training, CV, and test metrics."""
    print("=" * 72)
    print("AI LOAN UNDERWRITING — ML RISK MODEL TRAINING SUMMARY")
    print("=" * 72)
    print(
        f"Dataset          : {metadata['dataset_path']} (N={metadata['total_sample_count']})"
    )
    print(f"Dataset SHA-256  : {metadata['dataset_sha256']}")
    print(
        f"Feature Contract : {metadata['feature_contract_version']} "
        f"({metadata['num_features']} features)"
    )
    print(
        f"Split Strategy   : Stratified {int((1 - metadata['split_strategy']['test_size']) * 100)}/"
        f"{int(metadata['split_strategy']['test_size'] * 100)} "
        f"(train={metadata['train_sample_count']}, test={metadata['test_sample_count']}, "
        f"seed={metadata['split_strategy']['random_state']})"
    )
    print(f"Train Classes    : {metadata['train_class_distribution']}")
    print(f"Test Classes     : {metadata['test_class_distribution']}")
    print()

    cv = metadata["cv_metrics"]
    print(
        f"[1] {cv['cv_folds']}-Fold Stratified CV on Training Split ONLY "
        f"(N={cv['sample_count']}):"
    )
    print(
        f"    Accuracy         : {cv['accuracy_mean']:.4f} +/- {cv['accuracy_std']:.4f}"
    )
    print(
        f"    Balanced Accuracy: {cv['balanced_accuracy_mean']:.4f} +/- "
        f"{cv['balanced_accuracy_std']:.4f}"
    )
    print(
        f"    Macro F1         : {cv['f1_macro_mean']:.4f} +/- {cv['f1_macro_std']:.4f}"
    )
    print(
        f"    Weighted F1      : {cv['f1_weighted_mean']:.4f} +/- "
        f"{cv['f1_weighted_std']:.4f}"
    )
    print()

    tr = metadata["train_metrics"]
    print(
        f"[2] Training Split In-Sample Fit (N={tr['sample_count']}, "
        "NOT generalization):"
    )
    print(
        f"    Accuracy={tr['accuracy']:.4f}, Balanced={tr['balanced_accuracy']:.4f}, "
        f"Macro F1={tr['f1_macro']:.4f}"
    )
    print()

    te = metadata["test_metrics"]
    print(
        f"[3] Held-Out Test Split Evaluation (N={te['sample_count']}, unseen during fit):"
    )
    print(f"    Accuracy         : {te['accuracy']:.4f}")
    print(f"    Balanced Accuracy: {te['balanced_accuracy']:.4f}")
    print(
        f"    Macro P/R/F1     : {te['precision_macro']:.4f} / "
        f"{te['recall_macro']:.4f} / {te['f1_macro']:.4f}"
    )
    print(f"    Weighted F1      : {te['f1_weighted']:.4f}")
    print(
        f"    OVR ROC-AUC      : macro={te['roc_auc_ovr_macro']}, weighted={te['roc_auc_ovr_weighted']}"
    )
    print(f"    Labels           : {te['confusion_matrix_labels']}")
    print(f"    Confusion Matrix : {te['confusion_matrix']}")
    print()

    print("Top Feature Importances (fitted RandomForest on train split):")
    for idx, (feat, imp) in enumerate(
        list(metadata["feature_importances"].items())[:8], start=1
    ):
        print(f"  {idx:>2}. {feat:<26} {imp:.4f}")
    print()
    print(f"Note: {metadata['dataset_synthetic_notice']}")
    print("=" * 72)


def train_risk_model(
    dataset_path: str = DEFAULT_DATASET_PATH,
    model_path: str = DEFAULT_MODEL_PATH,
    metadata_path: str = DEFAULT_METADATA_PATH,
    test_size: float = TEST_SIZE,
    cv_folds: int = CV_FOLDS,
    random_state: int = RANDOM_STATE,
    feature_contract: RiskFeatureContract = RISK_FEATURE_CONTRACT,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Train, cross-validate, evaluate on held-out split, and save model artifacts."""
    _, X, y, applicant_ids = load_and_validate_training_dataset(
        dataset_path=dataset_path,
        feature_contract=feature_contract,
    )

    X_train, X_test, y_train, y_test, train_ids, test_ids = split_dataset(
        X=X,
        y=y,
        applicant_ids=applicant_ids,
        test_size=test_size,
        random_state=random_state,
    )

    pipeline = build_training_pipeline(random_state=random_state)
    cv_metrics = run_training_cv(
        pipeline=pipeline,
        X_train=X_train,
        y_train=y_train,
        cv_folds=cv_folds,
        random_state=random_state,
    )

    # Fit ONLY on training partition so held-out test records remain strictly unseen.
    pipeline.fit(X_train, y_train)

    class_labels = [str(c) for c in pipeline.classes_]
    train_metrics = evaluate_partition(pipeline, X_train, y_train, class_labels)
    train_metrics["note"] = (
        "In-sample fit on training split; do not use as a generalization estimate."
    )
    test_metrics = evaluate_partition(pipeline, X_test, y_test, class_labels)

    imputer = pipeline.named_steps["imputer"]
    classifier = pipeline.named_steps["classifier"]

    feature_names = list(feature_contract.feature_names)
    importances = dict(
        sorted(
            (
                (feat, round(float(imp), 4))
                for feat, imp in zip(feature_names, classifier.feature_importances_)
            ),
            key=lambda item: item[1],
            reverse=True,
        )
    )
    imputer_medians = {
        feat: round(float(val), 4)
        for feat, val in zip(feature_names, imputer.statistics_)
    }

    metadata: Dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "model_type": "Pipeline(SimpleImputer(median) + RandomForestClassifier)",
        "estimator_type": "RandomForestClassifier",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "scikit_learn_version": sklearn.__version__,
        "dataset_path": _format_repo_relative_path(dataset_path),
        "dataset_sha256": compute_file_sha256(dataset_path),
        "dataset_synthetic_notice": SYNTHETIC_DATASET_NOTICE,
        "feature_contract_version": feature_contract.version,
        "feature_contract": feature_contract.to_dict(),
        "feature_names": feature_names,
        "num_features": len(feature_names),
        "classes": class_labels,
        "target_mapping": dict(TARGET_MAP),
        "split_strategy": {
            "method": "stratified_train_test_split",
            "test_size": test_size,
            "random_state": random_state,
        },
        "total_sample_count": int(len(X)),
        "train_sample_count": int(len(X_train)),
        "test_sample_count": int(len(X_test)),
        "train_applicant_ids": train_ids,
        "test_applicant_ids": test_ids,
        "train_class_distribution": {
            str(k): int(v) for k, v in y_train.value_counts().sort_index().items()
        },
        "test_class_distribution": {
            str(k): int(v) for k, v in y_test.value_counts().sort_index().items()
        },
        "hyperparameters": {
            "n_estimators": int(classifier.n_estimators),
            "max_depth": int(classifier.max_depth),
            "min_samples_split": int(classifier.min_samples_split),
            "random_state": random_state,
            "imputer_strategy": "median",
        },
        "imputer_medians": imputer_medians,
        "cv_folds": cv_folds,
        "cv_metrics": cv_metrics,
        "train_metrics": train_metrics,
        "test_metrics": test_metrics,
        "feature_importances": importances,
    }

    model_dir = os.path.dirname(os.path.abspath(model_path))
    metadata_dir = os.path.dirname(os.path.abspath(metadata_path))
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(metadata_dir, exist_ok=True)

    joblib.dump(pipeline, model_path)
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    if verbose:
        _print_training_summary(metadata)
        print(f"Saved model artifact : {model_path}")
        print(f"Saved model metadata : {metadata_path}")

    return metadata


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train and validate the AI Loan Underwriting ML Risk Model."
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET_PATH)
    parser.add_argument("--model-out", default=DEFAULT_MODEL_PATH)
    parser.add_argument("--metadata-out", default=DEFAULT_METADATA_PATH)
    parser.add_argument("--test-size", type=float, default=TEST_SIZE)
    parser.add_argument("--cv-folds", type=int, default=CV_FOLDS)
    parser.add_argument("--random-state", type=int, default=RANDOM_STATE)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    train_risk_model(
        dataset_path=args.dataset,
        model_path=args.model_out,
        metadata_path=args.metadata_out,
        test_size=args.test_size,
        cv_folds=args.cv_folds,
        random_state=args.random_state,
    )
