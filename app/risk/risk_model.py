"""Machine-Learning Risk Assessment Model Wrapper.

Loads a trained scikit-learn Pipeline artifact, enforces the authoritative
RiskFeatureContract at inference time, validates artifact/metadata compatibility,
and produces deterministic risk scores, RiskLevel tiers, and class probabilities.
"""

import json
import os
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

import joblib

from app.risk.feature_contract import (
    RISK_FEATURE_CONTRACT,
    FeatureValidationError,
    RiskFeatureContract,
)
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


class RiskModelError(RuntimeError):
    """Base exception for ML risk model loading and inference errors."""


class RiskModelLoadError(FileNotFoundError, RiskModelError):
    """Raised when the ML risk model artifact is missing or cannot be loaded."""


class RiskModelContractError(ValueError, RiskModelError):
    """Raised when a loaded model or metadata does not match the feature contract."""


class MLRiskModel:
    """Predictive machine-learning model wrapper for synthetic risk profile classification."""

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        metadata_path: str = DEFAULT_METADATA_PATH,
        feature_contract: Optional[RiskFeatureContract] = None,
        random_state: int = 42,
    ) -> None:
        """Initialize the ML risk model by loading and validating saved artifacts."""
        self.model_path = model_path
        self.metadata_path = metadata_path
        self.feature_contract = feature_contract or RISK_FEATURE_CONTRACT
        self.random_state = random_state
        self.model: Any = None
        self.feature_names: List[str] = list(self.feature_contract.feature_names)
        self.feature_importances: Dict[str, float] = {}
        self.model_version: str = "risk_model_rf_v2"
        self.metadata: Dict[str, Any] = {}

        self._load_and_validate_model()

    def _load_and_validate_model(self) -> None:
        """Load trained model and metadata from disk, enforcing feature contract."""
        if not os.path.exists(self.model_path):
            raise RiskModelLoadError(
                f"ML risk model artifact not found at '{self.model_path}'. "
                "Run 'python scripts/train_risk_model.py' to generate it."
            )

        try:
            loaded = joblib.load(self.model_path)
        except Exception as exc:
            raise RiskModelLoadError(
                f"Failed to load ML risk model artifact from '{self.model_path}': {exc}"
            ) from exc

        if not (
            hasattr(loaded, "predict")
            and hasattr(loaded, "predict_proba")
            and hasattr(loaded, "classes_")
        ):
            raise RiskModelContractError(
                f"Loaded artifact at '{self.model_path}' does not implement predict/predict_proba/classes_."
            )

        # Verify model's expected feature names & exact order against contract
        model_features = list(getattr(loaded, "feature_names_in_", []))
        if model_features != self.feature_contract.feature_names:
            raise RiskModelContractError(
                f"Model feature contract mismatch for '{self.model_path}': "
                f"model expects {model_features}, contract defines {self.feature_contract.feature_names}."
            )

        # Load and validate metadata if present
        if self.metadata_path and os.path.exists(self.metadata_path):
            try:
                with open(self.metadata_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception as exc:
                raise RiskModelLoadError(
                    f"Failed to read model metadata at '{self.metadata_path}': {exc}"
                ) from exc

            meta_features = meta.get("feature_names")
            if (
                meta_features is not None
                and list(meta_features) != self.feature_contract.feature_names
            ):
                raise RiskModelContractError(
                    f"Metadata feature mismatch in '{self.metadata_path}': "
                    f"{meta_features} != {self.feature_contract.feature_names}."
                )

            meta_contract_ver = meta.get("feature_contract_version")
            if (
                meta_contract_ver is not None
                and meta_contract_ver != self.feature_contract.version
            ):
                raise RiskModelContractError(
                    f"Metadata feature contract version mismatch in '{self.metadata_path}': "
                    f"'{meta_contract_ver}' != '{self.feature_contract.version}'."
                )

            self.metadata = meta
            self.model_version = str(meta.get("model_version", self.model_version))
            self.feature_importances = dict(meta.get("feature_importances", {}))

        self.model = loaded

        # Extract feature importances directly from Pipeline estimator if not cached in metadata
        estimator = (
            loaded.named_steps["classifier"]
            if hasattr(loaded, "named_steps") and "classifier" in loaded.named_steps
            else loaded
        )
        if not self.feature_importances and hasattr(estimator, "feature_importances_"):
            self.feature_importances = {
                feat: round(float(imp), 4)
                for feat, imp in zip(self.feature_names, estimator.feature_importances_)
            }

        logger.info(
            "Loaded ML risk model '%s' (%s) matching contract '%s'.",
            self.model_version,
            self.model_path,
            self.feature_contract.version,
        )

    def predict_risk(
        self, target: Union[Applicant, DocumentPackageResult, Mapping[str, Any]]
    ) -> Tuple[float, RiskLevel, Dict[str, float]]:
        """Predict risk score, RiskLevel, and class probabilities for an applicant."""
        if self.model is None:
            raise RiskModelLoadError("ML risk model is not loaded.")

        features = self.feature_contract.extract(target)
        X_vec = self.feature_contract.to_dataframe([features])

        try:
            probs = self.model.predict_proba(X_vec)[0]
            classes = list(self.model.classes_)
            predicted_class = str(self.model.predict(X_vec)[0])
        except Exception as exc:
            raise RiskModelError(f"ML risk model inference failed: {exc}") from exc

        prob_dict = {str(cls_name): float(p) for cls_name, p in zip(classes, probs)}

        exp_score = sum(
            prob_dict.get(tier, 0.0) * TIER_SEVERITY_WEIGHTS.get(tier, 50.0)
            for tier in TIER_SEVERITY_WEIGHTS
        )
        risk_score = round(min(max(exp_score, 0.0), 100.0), 2)
        category = RiskLevel(predicted_class)

        return risk_score, category, prob_dict

    def predict_default_probability(
        self, applicant: Union[Applicant, Mapping[str, Any]]
    ) -> float:
        """Legacy helper: Predict estimated high-risk likelihood (0.0 to 1.0).

        Note: Represents synthetic modeled risk level, not empirical default rate.
        """
        score, _, _ = self.predict_risk(applicant)
        return round(score / 100.0, 4)

    def explain_prediction(
        self, applicant: Union[Applicant, Mapping[str, Any]]
    ) -> Dict[str, Any]:
        """Provide feature values, feature importances, and class probabilities."""
        features = self.feature_contract.extract(applicant)
        score, category, probs = self.predict_risk(applicant)

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
            "feature_contract_version": self.feature_contract.version,
        }


__all__ = [
    "DATASET_PATH",
    "DEFAULT_METADATA_PATH",
    "DEFAULT_MODEL_PATH",
    "FeatureValidationError",
    "MLRiskModel",
    "RiskModelContractError",
    "RiskModelError",
    "RiskModelLoadError",
    "TARGET_MAP",
    "TIER_SEVERITY_WEIGHTS",
]
