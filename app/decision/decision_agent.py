"""Decision and Reasoning Agent Implementation.

Synthesizes findings across Document Intelligence, Underwriting Eligibility,
Fraud/Anomaly Detection, and Risk Assessment into an explainable, traceable,
and audit-ready underwriting recommendation.
"""

from __future__ import annotations

import math
from typing import Dict, Optional, Union

from app.decision.policy import DecisionPolicy
from app.decision.reasoning import DecisionReasoningSynthesizer
from app.decision.rules import DecisionRulesEngine
from app.orchestration.consistency import (
    check_cross_agent_consistency,
    get_agent_status,
)
from app.schemas.anomaly import AnomalyResult
from app.schemas.applicant import (
    Applicant,
    DocumentPackageResult,
    EligibilityResult,
    RiskResult,
)
from app.schemas.decision import DecisionOutcome, DecisionReasoningResult
from app.schemas.underwriting import (
    AgentStatus,
    OrchestrationStatus,
    UnderwritingAnalysisResult,
)
from app.utils.helpers import get_logger

logger = get_logger(__name__)

DECISION_POLICY_VERSION = "decision_policy_v1"
REASONING_VERSION = "reasoning_v1"


class DecisionReasoningAgent:
    """Agent responsible for multi-agent evidence synthesis and explainable decisioning."""

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
        """Synthesize agent findings into an explainable underwriting recommendation."""
        analysis = self._normalize_analysis(
            target=target,
            eligibility=eligibility,
            risk=risk,
            anomaly=anomaly,
            document_result=document_result,
        )

        # Ensure consistency check runs even for ad-hoc direct callers
        if not analysis.consistency_conflicts:
            auth_sources, conflicts = check_cross_agent_consistency(
                analysis,
                applicant=target if isinstance(target, Applicant) else None,
            )
            analysis.authoritative_sources = auth_sources
            analysis.consistency_conflicts = conflicts
            analysis.has_unresolved_conflicts = any(
                c.get("severity") == "BLOCKING" for c in conflicts
            )

        logger.info(
            "Synthesizing decision recommendation for application '%s'.",
            analysis.application_id,
        )

        (
            recommendation,
            reasons,
            positive_factors,
            negative_factors,
            blocking_factors,
            supporting_evidence,
            confidence,
        ) = self.rules_engine.evaluate_decision(analysis)

        summary = self.synthesizer.synthesize_summary(
            application_id=analysis.application_id,
            recommendation=recommendation,
            confidence=confidence,
            reasons=reasons,
            positive_factors=positive_factors,
            negative_factors=negative_factors,
            blocking_factors=blocking_factors,
        )

        # Resolve structured Stage 4 explainability fields safely
        doc_res = analysis.document_result
        elig_res = analysis.eligibility_result
        risk_res = analysis.risk_result
        anom_res = analysis.anomaly_result

        elig_status = elig_res.status.value if elig_res else "UNAVAILABLE"
        risk_cat = risk_res.risk_category.value if risk_res else "UNAVAILABLE"
        risk_score: Optional[float] = (
            round(float(risk_res.risk_score), 2)
            if (
                risk_res is not None
                and risk_res.risk_score is not None
                and math.isfinite(float(risk_res.risk_score))
                and 0.0 <= float(risk_res.risk_score) <= 100.0
            )
            else None
        )
        anom_status = anom_res.severity.value if anom_res else "UNAVAILABLE"

        doc_st = get_agent_status(
            analysis.agent_statuses, "document_agent", "DocumentIntakeAgent"
        )
        missing_docs = self.rules_engine._get_missing_docs(doc_res, anom_res)
        if doc_res is None:
            doc_ver_status = (
                "FAILED"
                if doc_st and doc_st.status == AgentStatus.FAILED
                else "UNAVAILABLE"
            )
        elif doc_res.processing_status == "failed" or (
            doc_st and doc_st.status == AgentStatus.FAILED
        ):
            doc_ver_status = "FAILED"
        elif (
            doc_res.processing_status == "completed_with_errors"
            or doc_res.invalid_fields
            or doc_res.ambiguous_fields
            or doc_res.field_conflicts
            or doc_res.unclassified_documents
        ):
            doc_ver_status = "UNVERIFIED"
        elif missing_docs or not doc_res.is_complete:
            doc_ver_status = "INCOMPLETE"
        else:
            doc_ver_status = "VERIFIED"

        val_warnings = list(analysis.validation_warnings)
        for st in analysis.agent_statuses.values():
            for w in st.warnings:
                if w not in val_warnings:
                    val_warnings.append(w)

        mat_anomalies = (
            [f.description for f in anom_res.flags]
            if anom_res and anom_res.has_anomalies
            else []
        )
        review_reasons = (
            [r.description for r in reasons]
            if recommendation == DecisionOutcome.MANUAL_REVIEW
            else []
        )
        agent_status_map: Dict[str, str] = {
            name: st.status.value
            for name, st in sorted(analysis.agent_statuses.items())
        }

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
            eligibility_status=elig_status,
            risk_category=risk_cat,
            risk_score=risk_score,
            fraud_status=anom_status,
            document_verification_status=doc_ver_status,
            missing_documents=missing_docs,
            validation_warnings=val_warnings,
            material_anomalies=mat_anomalies,
            review_reasons=review_reasons,
            agent_statuses=agent_status_map,
            consistency_conflicts=list(analysis.consistency_conflicts),
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
