"""Decision and Reasoning Agent Implementation.

Synthesizes findings across Document Intelligence, Underwriting Eligibility,
Risk Assessment, and Fraud/Anomaly Detection agents into an explainable,
evidence-backed underwriting recommendation.
"""

from typing import Optional, Union

from app.decision.policy import DecisionPolicy
from app.decision.reasoning import DecisionReasoningSynthesizer
from app.decision.rules import DecisionRulesEngine
from app.schemas.anomaly import AnomalyResult
from app.schemas.applicant import (
    Applicant,
    DocumentPackageResult,
    EligibilityResult,
    RiskResult,
)
from app.schemas.decision import DecisionReasoningResult
from app.schemas.underwriting import OrchestrationStatus, UnderwritingAnalysisResult
from app.utils.helpers import get_logger

logger = get_logger(__name__)

DECISION_POLICY_VERSION = "decision_policy_v1"
REASONING_VERSION = "reasoning_v1"


class DecisionReasoningAgent:
    """Agent responsible for multi-agent evidence synthesis and explainable decisioning.

    Consumes Stage 7 UnderwritingAnalysisResult (or individual agent findings), applies
    deterministic policy precedence rules, computes evidence confidence, and produces
    a structured DecisionReasoningResult.
    """

    def __init__(
        self,
        policy: Optional[DecisionPolicy] = None,
        rules_engine: Optional[DecisionRulesEngine] = None,
        synthesizer: Optional[DecisionReasoningSynthesizer] = None,
    ) -> None:
        """Initialize the DecisionReasoningAgent with policy and reasoning engine."""
        self.policy = policy or DecisionPolicy.default_policy()
        self.rules_engine = rules_engine or DecisionRulesEngine(policy=self.policy)
        self.synthesizer = synthesizer or DecisionReasoningSynthesizer()
        logger.info(
            "DecisionReasoningAgent initialized (Policy: %s, Engine: %s).",
            self.policy.policy_version,
            REASONING_VERSION,
        )

    def decide(
        self,
        target: Union[UnderwritingAnalysisResult, Applicant],
        eligibility: Optional[EligibilityResult] = None,
        risk: Optional[RiskResult] = None,
        anomaly: Optional[AnomalyResult] = None,
        document_result: Optional[DocumentPackageResult] = None,
    ) -> DecisionReasoningResult:
        """Synthesize agent findings into an explainable underwriting recommendation.

        Args:
            target: Stage 7 UnderwritingAnalysisResult or Applicant domain model.
            eligibility: Optional Stage 4 EligibilityResult (if target is Applicant).
            risk: Optional Stage 5 RiskResult (if target is Applicant).
            anomaly: Optional Stage 6 AnomalyResult (if target is Applicant).
            document_result: Optional Stage 3 DocumentPackageResult (if target is Applicant).

        Returns:
            DecisionReasoningResult with recommendation, confidence, reasons, and evidence.
        """
        # 1. Normalize input into UnderwritingAnalysisResult
        analysis = self._normalize_analysis(
            target=target,
            eligibility=eligibility,
            risk=risk,
            anomaly=anomaly,
            document_result=document_result,
        )

        logger.info(
            "Synthesizing decision recommendation for application '%s'.",
            analysis.application_id,
        )

        # 2. Evaluate Rule Precedence & Decision Matrix
        (
            recommendation,
            reasons,
            positive_factors,
            negative_factors,
            blocking_factors,
            supporting_evidence,
            confidence,
        ) = self.rules_engine.evaluate_decision(analysis)

        # 3. Synthesize Human-Readable Narrative Summary
        summary = self.synthesizer.synthesize_summary(
            application_id=analysis.application_id,
            recommendation=recommendation,
            confidence=confidence,
            reasons=reasons,
            positive_factors=positive_factors,
            negative_factors=negative_factors,
            blocking_factors=blocking_factors,
        )

        logger.info(
            "Decision generated for '%s': %s (Confidence: %.1f%%, Reasons: %d).",
            analysis.application_id,
            recommendation.value,
            confidence,
            len(reasons),
        )

        return DecisionReasoningResult(
            application_id=analysis.application_id,
            applicant_id=analysis.applicant_id,
            recommendation=recommendation,
            confidence=confidence,
            human_review_required=True,
            requires_manual_review=True,
            reasons=reasons,
            positive_factors=positive_factors,
            negative_factors=negative_factors,
            blocking_factors=blocking_factors,
            supporting_evidence=supporting_evidence,
            summary=summary,
            policy_version=self.policy.policy_version,
            reasoning_version=REASONING_VERSION,
        )

    def evaluate(
        self,
        target: Union[UnderwritingAnalysisResult, Applicant],
        eligibility: Optional[EligibilityResult] = None,
        risk: Optional[RiskResult] = None,
        anomaly: Optional[AnomalyResult] = None,
        document_result: Optional[DocumentPackageResult] = None,
    ) -> DecisionReasoningResult:
        """Alias for decide() to support evaluation conventions."""
        return self.decide(
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
        """Process an underwriting result or applicant ID into a decision recommendation."""
        if isinstance(target, str):
            from app.orchestration.orchestrator import UnderwritingOrchestrator

            orchestrator = UnderwritingOrchestrator()
            target = orchestrator.process(target)

        return self.decide(
            target=target,
            eligibility=eligibility,
            risk=risk,
            anomaly=anomaly,
            document_result=document_result,
        )

    def _normalize_analysis(
        self,
        target: Union[UnderwritingAnalysisResult, Applicant],
        eligibility: Optional[EligibilityResult] = None,
        risk: Optional[RiskResult] = None,
        anomaly: Optional[AnomalyResult] = None,
        document_result: Optional[DocumentPackageResult] = None,
    ) -> UnderwritingAnalysisResult:
        """Ensure input data is formatted as an UnderwritingAnalysisResult."""
        if isinstance(target, UnderwritingAnalysisResult):
            return target

        if isinstance(target, Applicant):
            app_id = target.applicant_id
            return UnderwritingAnalysisResult(
                application_id=app_id,
                applicant_id=app_id,
                orchestration_status=OrchestrationStatus.SUCCESS,
                document_result=document_result,
                eligibility_result=eligibility,
                risk_result=risk,
                anomaly_result=anomaly,
                pipeline_version="pipeline_v1",
            )

        raise ValueError(
            f"Unsupported target type for DecisionReasoningAgent: {type(target).__name__}"
        )


__all__ = [
    "DecisionReasoningAgent",
    "DECISION_POLICY_VERSION",
    "REASONING_VERSION",
]
