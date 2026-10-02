"""Machine-Learning Risk Assessment Model Wrapper.

Wraps a local scikit-learn classifier (RandomForestClassifier) for synthetic
risk profile classification. Provides deterministic inference, feature
importance, normalized risk score (0-100), and categorical RiskLevel assignment.
"""

import json
import os
from typing import Any, Dict, List, Optional, Tuple, Union

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from app.risk.features import RISK_FEATURE_NAMES, extract_features
from app.schemas.applicant import Applicant, DocumentPackageResult, RiskLevel
from app.utils.helpers import get_logger

logger = get_logger(__name__)

DEFAULT_MODEL_PATH = "models/risk_model.joblib"
DEFAULT_METADATA_PATH = "models/risk_model_metadata.json"
DATASET_PATH = "data/synthetic_data/applicants.csv"

# Target risk level mapping
TARGET_MAP = {
    "LOW_RISK": RiskLevel.LOW.value,
    "MEDIUM_RISK": RiskLevel.MEDIUM.value,
    "HIGH_RISK": RiskLevel.HIGH.value,
    "BORDERLINE": RiskLevel.BORDERLINE.value,
}

# Continuous severity score assigned to each tier for weighted expectation
TIER_SEVERITY_WEIGHTS = {
    RiskLevel.LOW.value: 15.0,
    RiskLevel.MEDIUM.value: 45.0,
    RiskLevel.BORDERLINE.value: 65.0,
    RiskLevel.HIGH.value: 90.0,
}


class MLRiskModel:
    """Predictive machine-learning model wrapper for synthetic risk profile classification."""

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        metadata_path: str = DEFAULT_METADATA_PATH,
        random_state: int = 42,
    ) -> None:
        """Initialize the ML risk model, loading saved artifact or training if absent."""
        self.model_path = model_path
        self.metadata_path = metadata_path
        self.random_state = random_state
        self.model: Optional[RandomForestClassifier] = None
        self.feature_names: List[str] = list(RISK_FEATURE_NAMES)
        self.feature_importances: Dict[str, float] = {}
        self.model_version: str = "risk_model_rf_v1"

        if os.path.exists(self.model_path):
            self._load_model()
        else:
            logger.info(
                "Model artifact not found at %s. Initializing/training.",
                self.model_path,
            )
            self._train_or_initialize()

    def _load_model(self) -> None:
        """Load trained model and metadata from disk."""
        try:
            self.model = joblib.load(self.model_path)
            logger.info("Loaded ML risk model from %s", self.model_path)

            if os.path.exists(self.metadata_path):
                with open(self.metadata_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    self.model_version = meta.get("model_version", self.model_version)
                    self.feature_names = meta.get("feature_names", self.feature_names)
                    self.feature_importances = meta.get("feature_importances", {})

            if not self.feature_importances and hasattr(
                self.model, "feature_importances_"
            ):
                self.feature_importances = {
                    feat: round(float(imp), 4)
                    for feat, imp in zip(
                        self.feature_names, self.model.feature_importances_
                    )
                }
        except Exception as exc:
            logger.warning(
                "Failed to load model from %s (%s). Re-training.", self.model_path, exc
            )
            self._train_or_initialize()

    def _train_or_initialize(self) -> None:
        """Train model on synthetic dataset if available, or initialize default model."""
        if os.path.exists(DATASET_PATH):
            df = pd.read_csv(DATASET_PATH)
            # Map target
            y = df["profile_category"].map(TARGET_MAP)
            # Engineer features for each row
            X_rows = [extract_features(row.to_dict()) for _, row in df.iterrows()]
            X = pd.DataFrame(X_rows)[self.feature_names]

            self.model = RandomForestClassifier(
                n_estimators=50,
                max_depth=5,
                min_samples_split=2,
                random_state=self.random_state,
            )
            self.model.fit(X, y)

            self.feature_importances = {
                feat: round(float(imp), 4)
                for feat, imp in zip(
                    self.feature_names, self.model.feature_importances_
                )
            }

            # Save artifact if directory is writable
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            try:
                joblib.dump(self.model, self.model_path)
                meta = {
                    "model_version": self.model_version,
                    "model_type": "RandomForestClassifier",
                    "n_estimators": 50,
                    "max_depth": 5,
                    "random_state": self.random_state,
                    "feature_names": self.feature_names,
                    "feature_importances": self.feature_importances,
                }
                with open(self.metadata_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
                logger.info("Trained and saved ML risk model to %s", self.model_path)
            except Exception as e:
                logger.warning("Could not persist model artifact: %s", e)
        else:
            logger.warning(
                "Synthetic dataset %s not found. Model remains uninitialized.",
                DATASET_PATH,
            )

    def predict_risk(
        self, target: Union[Applicant, DocumentPackageResult, Dict[str, Any]]
    ) -> Tuple[float, RiskLevel, Dict[str, float]]:
        """Predict risk score, RiskLevel, and class probabilities for an applicant.

        Args:
            target: Applicant model, DocumentPackageResult, or raw dictionary.

        Returns:
            Tuple of (risk_score, RiskLevel, class_probabilities).
        """
        features = extract_features(target)
        X_vec = pd.DataFrame([features])[self.feature_names]

        if self.model is None:
            # Fallback if model could not be loaded or trained
            score = 50.0
            return score, RiskLevel.MEDIUM, {"MEDIUM": 1.0}

        # Predict class probabilities
        probs = self.model.predict_proba(X_vec)[0]
        classes = list(self.model.classes_)
        prob_dict = {cls_name: float(p) for cls_name, p in zip(classes, probs)}

        # Continuous expected risk score on 0-100 scale
        exp_score = sum(
            prob_dict.get(tier, 0.0) * TIER_SEVERITY_WEIGHTS.get(tier, 50.0)
            for tier in TIER_SEVERITY_WEIGHTS
        )
        risk_score = round(min(max(exp_score, 0.0), 100.0), 2)

        # Categorical prediction (argmax probability)
        predicted_class = str(self.model.predict(X_vec)[0])
        category = RiskLevel(predicted_class)

        return risk_score, category, prob_dict

    def predict_default_probability(
        self, applicant: Union[Applicant, Dict[str, Any]]
    ) -> float:
        """Legacy helper: Predict estimated high-risk likelihood (0.0 to 1.0).

        Note: Represents synthetic modeled risk level, not empirical default rate.
        """
        score, _, _ = self.predict_risk(applicant)
        return round(score / 100.0, 4)

    def explain_prediction(
        self, applicant: Union[Applicant, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Provide feature values, feature importances, and class probabilities for predictions."""
        features = extract_features(applicant)
        score, category, probs = self.predict_risk(applicant)

        # Top 5 most influential features in model
        sorted_importances = sorted(
            self.feature_importances.items(), key=lambda item: item[1], reverse=True
        )

        return {
            "risk_score": score,
            "risk_category": category.value,
            "class_probabilities": probs,
            "features_used": features,
            "feature_importances": dict(sorted_importances),
            "top_features": [f[0] for f in sorted_importances[:5]],
            "model_version": self.model_version,
        }
