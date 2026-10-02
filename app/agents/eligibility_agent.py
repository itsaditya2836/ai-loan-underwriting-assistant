"""Eligibility Agent module.

Evaluates structured applicant information and document packages against
predefined underwriting policy rules using the deterministic EligibilityEvaluator.
"""

from typing import Any, Dict, Optional, Union

from app.eligibility.evaluator import EligibilityEvaluator
from app.eligibility.policy import EligibilityPolicy
from app.schemas.applicant import Applicant, DocumentPackageResult, EligibilityResult
from app.utils.helpers import get_logger

logger = get_logger(__name__)


class EligibilityAgent:
    """Agent responsible for evaluating deterministic underwriting eligibility rules.

    Consumes verified, structured output from the Stage 3 Document Intelligence stage
    (or structured Applicant profiles) and returns a transparent EligibilityResult.
    Does not read PDFs, perform OCR, or run ML risk models.
    """

    def __init__(self, policy: Optional[EligibilityPolicy] = None) -> None:
        """Initialize the agent with an underwriting eligibility policy."""
        self.policy = policy or EligibilityPolicy.default_policy()
        self.evaluator = EligibilityEvaluator(policy=self.policy)
        logger.info(
            "EligibilityAgent initialized with policy '%s'.",
            self.policy.policy_version,
        )

    def evaluate(
        self, target: Union[DocumentPackageResult, Applicant, Dict[str, Any]]
    ) -> EligibilityResult:
        """Evaluate applicant profile or document package against underwriting rules.

        Args:
            target: Stage 3 DocumentPackageResult, structured Applicant model, or raw data dict.

        Returns:
            EligibilityResult detailing overall status, individual rule outcomes,
            evidence citations, and transparent explanations.
        """
        logger.info(
            "Evaluating eligibility for target type: %s.", type(target).__name__
        )
        return self.evaluator.evaluate(target)
