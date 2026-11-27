"""Deterministic Risk Rules and Factor Extraction Engine.

Identifies explainable adverse risk factors and mitigating protective factors
grounded directly in applicant financial features and credit history.
"""

import math
from typing import Any, Dict, List, Optional, Tuple, Union

from app.risk.features import extract_features
from app.schemas.applicant import Applicant, DocumentPackageResult
from app.utils.helpers import get_logger

logger = get_logger(__name__)


class RiskRulesEngine:
    """Evaluates applicant financial metrics against risk factor heuristics."""

    def __init__(self) -> None:
        """Initialize the deterministic risk rules engine."""
        logger.info("RiskRulesEngine initialized.")

    def evaluate_rules(
        self, target: Union[Applicant, DocumentPackageResult, Dict[str, Any]]
    ) -> Dict[str, List[str]]:
        """Evaluate deterministic risk rules and extract factors.

        Args:
            target: Applicant model, DocumentPackageResult, or raw dictionary.

        Returns:
            Dictionary containing 'risk_factors' and 'protective_factors'.
        """
        features = extract_features(target)
        risk_factors, protective_factors = self.evaluate_factors(features)
        return {
            "risk_factors": risk_factors,
            "protective_factors": protective_factors,
        }

    def evaluate_factors(
        self, features: Dict[str, Optional[float]]
    ) -> Tuple[List[str], List[str]]:
        """Identify adverse risk factors and favorable protective factors from features.

        Args:
            features: Dictionary of extracted applicant features.

        Returns:
            Tuple of (risk_factors, protective_factors).
        """
        risk_factors: List[str] = []
        protective_factors: List[str] = []

        def is_present(val: Optional[float]) -> bool:
            return val is not None and not math.isnan(float(val))

        # 1. Credit Score Evaluation
        cs = features.get("credit_score")
        if is_present(cs):
            assert cs is not None
            if cs < 600:
                risk_factors.append(
                    f"Critically low credit score ({int(cs)}) indicates severe historical delinquency risk."
                )
            elif cs < 650:
                risk_factors.append(
                    f"Sub-prime credit score ({int(cs)}) is below standard underwriting threshold (650)."
                )
            elif cs < 700:
                risk_factors.append(
                    f"Moderate credit score ({int(cs)}) sits near lower underwriting policy boundary."
                )
            elif cs >= 750:
                protective_factors.append(
                    f"Prime credit score ({int(cs)}) demonstrates excellent historical repayment discipline."
                )
            elif cs >= 700:
                protective_factors.append(
                    f"Good credit score ({int(cs)}) reflects reliable debt servicing track record."
                )

        # 2. Debt-to-Income (DTI / FOIR)
        dti = features.get("dti_ratio")
        if is_present(dti):
            assert dti is not None
            if dti > 60.0:
                risk_factors.append(
                    f"High Debt-to-Income ratio ({dti:.1f}%) indicates heavy monthly debt obligation burden."
                )
            elif dti > 45.0:
                risk_factors.append(
                    f"Elevated Debt-to-Income ratio ({dti:.1f}%) reduces discretionary monthly cash flow."
                )
            elif dti <= 30.0:
                protective_factors.append(
                    f"Healthy Debt-to-Income ratio ({dti:.1f}%) provides strong monthly debt-servicing buffer."
                )

        # 3. Loan-to-Annual-Income Ratio (LTI)
        lti = features.get("loan_to_income_ratio")
        if is_present(lti):
            assert lti is not None
            if lti > 2.5:
                risk_factors.append(
                    f"High loan-to-annual-income ratio ({lti:.2f}x) reflects substantial debt leverage relative to earnings."
                )
            elif lti <= 1.0:
                protective_factors.append(
                    f"Conservative loan-to-annual-income exposure ({lti:.2f}x) limits overall financial leverage."
                )

        # 4. Monthly Earnings Capacity
        inc = features.get("monthly_income")
        if is_present(inc):
            assert inc is not None
            if inc < 40000.0:
                risk_factors.append(
                    f"Modest monthly earnings (INR {inc:,.2f}) reduces resilience against unexpected financial shocks."
                )
            elif inc >= 100000.0:
                protective_factors.append(
                    f"High monthly earnings (INR {inc:,.2f}) provides robust disposable cash flow capacity."
                )

        # 5. Liquidity Reserves vs Debt Service
        bal = features.get("bank_balance")
        ex_emi = features.get("existing_emi") or 0.0
        new_emi = features.get("estimated_new_emi") or 0.0
        tot_emi = float(ex_emi) + float(new_emi)
        if is_present(bal) and tot_emi > 0:
            assert bal is not None
            coverage = bal / tot_emi
            if coverage < 2.0:
                risk_factors.append(
                    f"Thin liquid reserves (INR {bal:,.2f}) cover less than 2 months of debt service obligations."
                )
            elif coverage >= 6.0:
                protective_factors.append(
                    f"Robust liquidity cushion (INR {bal:,.2f}) provides over {coverage:.1f} months of debt service coverage."
                )

        # 6. Career and Employment Stability
        exp_years = features.get("employment_years")
        if is_present(exp_years):
            assert exp_years is not None
            if exp_years < 2.0:
                risk_factors.append(
                    f"Short employment tenure ({exp_years:.1f} years) indicates potential employment stability risk."
                )
            elif exp_years >= 5.0:
                protective_factors.append(
                    f"Established career tenure ({exp_years:.1f} years) reflects continuous earning stability."
                )

        # 7. Employment Type Profile
        is_sal = features.get("is_salaried")
        if is_present(is_sal):
            if is_sal == 0.0:
                risk_factors.append(
                    "Self-employed business profile carries potential cash flow volatility."
                )
            else:
                protective_factors.append(
                    "Salaried corporate employment provides predictable recurring monthly cash flows."
                )

        # 8. Net Disposable Income
        disp = features.get("net_disposable_income")
        if is_present(disp):
            assert disp is not None
            if disp < 5000.0:
                risk_factors.append(
                    f"Tight net disposable income (INR {disp:,.2f}) leaves minimal margin for emergency expenses."
                )
            elif disp >= 30000.0:
                protective_factors.append(
                    f"Comfortable net disposable income (INR {disp:,.2f}) after all living expenses and loan installments."
                )

        return risk_factors, protective_factors
