"""Risk Assessment Agent module.

Evaluates applicant credit and repayment risk using a local machine-learning
model (Random Forest) and deterministic risk heuristics. Generates explainable
risk factors, protective factors, and normalized risk scores.
"""

from typing import Any, Dict, Optional, Union

from app.risk.features import extract_features
from app.risk.risk_model import MLRiskModel
from app.risk.rules import RiskRulesEngine
from app.risk.scoring import RiskScorer
from app.schemas.applicant import (
    Applicant,
    DocumentPackageResult,
    RiskResult,
)
from app.utils.helpers import get_logger

logger = get_logger(__name__)


class RiskAgent:
    """Agent responsible for assessing financial and credit repayment risk.

    Consumes structured applicant data (Applicant domain models or Stage 3
    DocumentPackageResults) and produces an explainable, normalized RiskResult.
    Does not make final loan approval decisions or perform fraud detection.
    """

    def __init__(
        self,
        ml_model: Optional[MLRiskModel] = None,
        rules_engine: Optional[RiskRulesEngine] = None,
        baseline_scorer: Optional[RiskScorer] = None,
        use_ml: bool = True,
    ) -> None:
        """Initialize RiskAgent with underlying models and rule evaluators."""
        self.ml_model = ml_model or MLRiskModel()
        self.rules_engine = rules_engine or RiskRulesEngine()
        self.baseline_scorer = baseline_scorer or RiskScorer()
        self.use_ml = use_ml
        logger.info(
            "RiskAgent initialized (Method: %s, Model: %s).",
            "ML_RANDOM_FOREST" if self.use_ml else "BASELINE_WEIGHTED",
            self.ml_model.model_version,
        )

    def assess(
        self, target: Union[Applicant, DocumentPackageResult, Dict[str, Any]]
    ) -> RiskResult:
        """Assess repayment risk and compute an explainable risk assessment.

        Args:
            target: Structured Applicant model, Stage 3 DocumentPackageResult, or raw dict.

        Returns:
            RiskResult detailing normalized risk score, category, factors, and evidence.
        """
        applicant_id = self._resolve_applicant_id(target)
        features = extract_features(target)

        # 1. Evaluate Risk Score and Category
        if self.use_ml:
            score, category, _ = self.ml_model.predict_risk(target)
            method = "ML_RANDOM_FOREST"
            feature_importance = dict(
                sorted(
                    self.ml_model.feature_importances.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )[:5]
            )
        else:
            score, category, _ = self.baseline_scorer.score_features(features)
            method = "BASELINE_WEIGHTED"
            feature_importance = {
                "credit_score": 0.40,
                "dti_ratio": 0.30,
                "loan_to_income_ratio": 0.20,
                "liquidity_buffer": 0.10,
            }

        # 2. Extract Explainable Risk and Mitigating Factors
        risk_factors, protective_factors = self.rules_engine.evaluate_factors(features)

        # 3. Construct Evidence References
        evidence: list[Dict[str, Any]] = [
            {
                "feature": "credit_score",
                "value": features.get("credit_score"),
                "benchmark": ">= 750 (Prime) / < 650 (Sub-prime)",
            },
            {
                "feature": "dti_ratio",
                "value": f"{features.get('dti_ratio', 0.0):.1f}%",
                "benchmark": "<= 35% (Healthy) / > 60% (Elevated)",
            },
            {
                "feature": "loan_to_income_ratio",
                "value": f"{features.get('loan_to_income_ratio', 0.0):.2f}x",
                "benchmark": "<= 1.0x (Low) / > 2.5x (High)",
            },
            {
                "feature": "monthly_income",
                "value": f"INR {features.get('monthly_income', 0.0):,.2f}",
                "benchmark": "Monthly cash flow capacity",
            },
        ]

        # 4. Synthesize Human-Readable Explanation
        explanation_lines = [
            f"Assessed Risk Tier: {category.value} (Modeled Score: {score:.1f}/100 via {method})."
        ]
        if risk_factors:
            explanation_lines.append(
                f"Key Risk Factors: {'; '.join(risk_factors[:3])}."
            )
        if protective_factors:
            explanation_lines.append(
                f"Mitigating Protective Factors: {'; '.join(protective_factors[:3])}."
            )
        explanation = " ".join(explanation_lines)

        remarks = (
            f"Risk Assessment: {category.value} ({score:.1f}/100). "
            f"Adverse factors: {len(risk_factors)}, Mitigating factors: {len(protective_factors)}. "
            f"Method: {method}."
        )

        return RiskResult(
            applicant_id=applicant_id,
            risk_score=score,
            risk_category=category,
            risk_level=category,
            risk_factors=risk_factors,
            protective_factors=protective_factors,
            features_used=features,
            feature_importance=feature_importance,
            model_version=self.ml_model.model_version,
            method=method,
            explanation=explanation,
            evidence=evidence,
            remarks=remarks,
        )

    def _resolve_applicant_id(
        self, target: Union[Applicant, DocumentPackageResult, Dict[str, Any]]
    ) -> str:
        """Resolve applicant ID string from target input."""
        if isinstance(target, (Applicant, DocumentPackageResult)):
            return target.applicant_id
        if isinstance(target, dict):
            return str(target.get("applicant_id") or "UNKNOWN")
        return "UNKNOWN"
