"""Credit and Repayment Risk Scoring Engine (Baseline Model).

Calculates a normalized, deterministic composite risk score (0-100) using
domain-weighted financial factors:
- Credit Score (40% weight)
- Debt-to-Income / FOIR Ratio (30% weight)
- Loan-to-Annual-Income Ratio (20% weight)
- Liquidity Reserve Buffer (10% weight)
"""

from typing import Any, Dict, Tuple, Union

from app.risk.features import extract_features
from app.schemas.applicant import Applicant, DocumentPackageResult, RiskLevel
from app.utils.helpers import get_logger

logger = get_logger(__name__)


class RiskScorer:
    """Calculates weighted baseline risk scores and assigns categorical RiskLevels."""

    def __init__(self) -> None:
        """Initialize the baseline heuristic risk scorer."""
        logger.info("RiskScorer (Baseline) initialized.")

    def calculate_score(
        self, target: Union[Applicant, DocumentPackageResult, Dict[str, Any]]
    ) -> Tuple[float, RiskLevel]:
        """Calculate normalized risk score (0-100) and assign a RiskLevel.

        Args:
            target: Applicant model, DocumentPackageResult, or raw dictionary.

        Returns:
            Tuple of (risk_score, RiskLevel).
        """
        features = extract_features(target)
        score, category, _ = self.score_features(features)
        return score, category

    def score_features(
        self, features: Dict[str, float]
    ) -> Tuple[float, RiskLevel, Dict[str, float]]:
        """Compute composite risk score and component breakdowns from features.

        Args:
            features: Dictionary of extracted applicant features.

        Returns:
            Tuple of (overall_risk_score, RiskLevel, component_breakdown).
        """
        # 1. Credit Score Component (40% weight)
        cs = features.get("credit_score", 700.0)
        if cs >= 750:
            cs_comp = 10.0
        elif cs >= 700:
            cs_comp = 30.0
        elif cs >= 650:
            cs_comp = 50.0
        elif cs >= 600:
            cs_comp = 75.0
        else:
            cs_comp = 95.0

        # 2. DTI / FOIR Ratio Component (30% weight)
        dti = features.get("dti_ratio", 40.0)
        if dti <= 30.0:
            dti_comp = 10.0
        elif dti <= 45.0:
            dti_comp = 35.0
        elif dti <= 60.0:
            dti_comp = 70.0
        else:
            dti_comp = 95.0

        # 3. Loan-to-Income Component (20% weight)
        lti = features.get("loan_to_income_ratio", 1.5)
        if lti <= 1.0:
            lti_comp = 10.0
        elif lti <= 2.5:
            lti_comp = 45.0
        else:
            lti_comp = 85.0

        # 4. Liquidity Reserve Buffer Component (10% weight)
        bal = features.get("bank_balance", 50000.0)
        tot_emi = features.get("existing_emi", 0.0) + features.get(
            "estimated_new_emi", 0.0
        )
        if tot_emi > 0:
            coverage = bal / tot_emi
            if coverage >= 6.0:
                buf_comp = 10.0
            elif coverage >= 2.0:
                buf_comp = 40.0
            else:
                buf_comp = 80.0
        else:
            buf_comp = 20.0

        # Weighted composite score on 0-100 scale
        composite = (
            (0.40 * cs_comp) + (0.30 * dti_comp) + (0.20 * lti_comp) + (0.10 * buf_comp)
        )
        composite = round(min(max(composite, 0.0), 100.0), 2)

        # Categorize into RiskLevel
        if composite < 35.0:
            category = RiskLevel.LOW
        elif composite < 55.0:
            category = RiskLevel.MEDIUM
        elif composite < 72.0:
            category = RiskLevel.BORDERLINE
        else:
            category = RiskLevel.HIGH

        breakdown = {
            "credit_score_risk": cs_comp,
            "dti_ratio_risk": dti_comp,
            "loan_to_income_risk": lti_comp,
            "liquidity_risk": buf_comp,
        }

        return composite, category, breakdown
