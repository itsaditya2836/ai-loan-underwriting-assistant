"""Decision & Reasoning Agent module.

Combines findings from the Document, Eligibility, Risk, and Fraud agents
to synthesize an explainable, audit-ready recommendation for human loan officers.
"""

from typing import Optional, Union

from app.decision.decision_agent import (
    DecisionReasoningAgent as CoreDecisionReasoningAgent,
)
from app.decision.policy import DecisionPolicy
from app.schemas.anomaly import AnomalyResult
from app.schemas.applicant import (
    Applicant,
    DocumentPackageResult,
    EligibilityResult,
    RiskResult,
)
from app.schemas.decision import DecisionReasoningResult
from app.schemas.underwriting import UnderwritingAnalysisResult
from app.utils.helpers import get_logger

logger = get_logger(__name__)


class DecisionReasoningAgent:
    """Agent responsible for multi-criteria underwriting recommendation synthesis.

    Provides a clean facade over the Stage 8 Decision & Reasoning engine.
    """

    def __init__(
        self,
        policy: Optional[DecisionPolicy] = None,
        agent: Optional[CoreDecisionReasoningAgent] = None,
    ) -> None:
        """Initialize the DecisionReasoningAgent facade."""
        self.agent = agent or CoreDecisionReasoningAgent(policy=policy)
        logger.info("DecisionReasoningAgent initialized.")

    def decide(
        self,
        target: Union[UnderwritingAnalysisResult, Applicant],
        eligibility: Optional[EligibilityResult] = None,
        risk: Optional[RiskResult] = None,
        anomaly: Optional[AnomalyResult] = None,
        document_result: Optional[DocumentPackageResult] = None,
    ) -> DecisionReasoningResult:
        """Synthesize agent findings into an explainable recommendation for the loan officer.

        Args:
            target: Stage 7 UnderwritingAnalysisResult or Applicant domain model.
            eligibility: Optional Stage 4 EligibilityResult.
            risk: Optional Stage 5 RiskResult.
            anomaly: Optional Stage 6 AnomalyResult.
            document_result: Optional Stage 3 DocumentPackageResult.

        Returns:
            DecisionReasoningResult containing final recommendation, reasons, and evidence.
        """
        return self.agent.decide(
            target=target,
            eligibility=eligibility,
            risk=risk,
            anomaly=anomaly,
            document_result=document_result,
        )

    def evaluate(
        self,
        target: Union[UnderwritingAnalysisResult, Applicant],
        eligibility: Optional[EligibilityResult] = None,
        risk: Optional[RiskResult] = None,
        anomaly: Optional[AnomalyResult] = None,
        document_result: Optional[DocumentPackageResult] = None,
    ) -> DecisionReasoningResult:
        """Alias for decide()."""
        return self.agent.evaluate(
            target=target,
            eligibility=eligibility,
            risk=risk,
            anomaly=anomaly,
            document_result=document_result,
        )

    def process(
        self,
        target: Union[UnderwritingAnalysisResult, Applicant, str],
        eligibility: Optional[EligibilityResult] = None,
        risk: Optional[RiskResult] = None,
        anomaly: Optional[AnomalyResult] = None,
        document_result: Optional[DocumentPackageResult] = None,
    ) -> DecisionReasoningResult:
        """Process an underwriting analysis result or applicant ID into a decision."""
        return self.agent.process(
            target=target,
            eligibility=eligibility,
            risk=risk,
            anomaly=anomaly,
            document_result=document_result,
        )


DecisionAgent = DecisionReasoningAgent

__all__ = ["DecisionReasoningAgent", "DecisionAgent"]
