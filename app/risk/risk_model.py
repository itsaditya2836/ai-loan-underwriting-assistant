"""Machine-learning based risk and default prediction model wrapper.

Abstracts predictive model inference, enabling model updates (e.g. Scikit-learn
classifiers, XGBoost) without breaking consuming agents.
"""

from typing import Any, Dict

from app.schemas.applicant import Applicant
from app.utils.helpers import get_logger

logger = get_logger(__name__)


class MLRiskModel:
    """Predictive machine-learning model wrapper for loan default risk."""

    def __init__(self, model_path: str = "models/risk_model.pkl") -> None:
        self.model_path = model_path
        logger.info("MLRiskModel initialized (Placeholder).")

    def predict_default_probability(self, applicant: Applicant) -> float:
        """Predict the likelihood of loan default for an applicant.

        TODO: Implement feature engineering and ML inference in Stage 5.
        """
        raise NotImplementedError("MLRiskModel will be implemented in Stage 5.")

    def explain_prediction(self, applicant: Applicant) -> Dict[str, Any]:
        """Provide feature importance or SHAP-style explanation for predictions.

        TODO: Implement model explainability in Stage 5.
        """
        raise NotImplementedError(
            "Model explainability will be implemented in Stage 5."
        )
