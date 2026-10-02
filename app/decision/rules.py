"""Deterministic Decision Rules Engine.

Implements rule precedence, evidence evaluation, confidence scoring,
factor extraction, and recommendation generation.
"""

from typing import Any, Dict, List, Optional, Tuple

from app.decision.policy import DecisionPolicy
from app.schemas.anomaly import AnomalyResult, AnomalySeverity
from app.schemas.applicant import (
    DocumentPackageResult,
    EligibilityStatus,
    RiskLevel,
)
from app.schemas.decision import DecisionOutcome, DecisionReason
from app.schemas.underwriting import OrchestrationStatus, UnderwritingAnalysisResult


class DecisionRulesEngine:
    """Evaluates multi-agent analytical outputs against centralized decision policies."""

    def __init__(self, policy: Optional[DecisionPolicy] = None) -> None:
        """Initialize the decision rules engine with a decision policy."""
        self.policy = policy or DecisionPolicy.default_policy()

    def evaluate_decision(
        self,
        analysis: UnderwritingAnalysisResult,
    ) -> Tuple[
        DecisionOutcome,
        List[DecisionReason],
        List[str],
        List[str],
        List[str],
        List[Dict[str, Any]],
        float,
    ]:
        """Apply rule precedence to synthesize a final recommendation.

        Returns:
            Tuple of:
            (recommendation, reasons, positive_factors, negative_factors,
             blocking_factors, supporting_evidence, confidence)
        """
        reasons: List[DecisionReason] = []
        positive_factors: List[str] = []
        negative_factors: List[str] = []
        blocking_factors: List[str] = []
        supporting_evidence: List[Dict[str, Any]] = []

        doc_res = analysis.document_result
        elig_res = analysis.eligibility_result
        risk_res = analysis.risk_result
        anom_res = analysis.anomaly_result

        # Collect Evidence and Factors across all available agents
        self._extract_factors_and_evidence(
            analysis=analysis,
            positive_factors=positive_factors,
            negative_factors=negative_factors,
            blocking_factors=blocking_factors,
            supporting_evidence=supporting_evidence,
        )

        # -------------------------------------------------------------------
        # Rule Precedence Evaluation
        # -------------------------------------------------------------------

        # Priority 1 — Pipeline validity
        if analysis.orchestration_status == OrchestrationStatus.FAILED:
            reasons.append(
                DecisionReason(
                    code="DEC-SYS-001",
                    category="SYSTEM",
                    severity="BLOCKING",
                    description=(
                        f"Pipeline execution failed: {analysis.error_message or 'System failure'}. "
                        "Manual review required."
                    ),
                    evidence=analysis.error_message,
                    source_agent="UnderwritingOrchestrator",
                )
            )
            confidence = self._compute_confidence(analysis, is_pipeline_failed=True)
            return (
                DecisionOutcome.MANUAL_REVIEW,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

        # Priority 2 — Critical eligibility failure (Hard Ineligibility -> REJECT)
        if elig_res and elig_res.status == EligibilityStatus.INELIGIBLE:
            failed_rules = [r.rule_name for r in elig_res.rule_results if not r.passed]
            failed_reasons = [
                f"{r.rule_name}: {r.reason}"
                for r in elig_res.rule_results
                if not r.passed
            ]
            reasons.append(
                DecisionReason(
                    code="DEC-ELIG-001",
                    category="ELIGIBILITY",
                    severity="BLOCKING",
                    description=(
                        f"Application is INELIGIBLE due to failure of mandatory underwriting rule(s): "
                        f"{'; '.join(failed_rules)}."
                    ),
                    evidence="; ".join(failed_reasons),
                    source_agent="EligibilityAgent",
                )
            )
            # Check if high risk also compounds rejection
            if risk_res and risk_res.risk_category == RiskLevel.HIGH:
                reasons.append(
                    DecisionReason(
                        code="DEC-RISK-002",
                        category="RISK",
                        severity="BLOCKING",
                        description=(
                            f"Assessed credit risk is HIGH (Score: {risk_res.risk_score:.1f}/100), "
                            "exceeding acceptable policy risk limits."
                        ),
                        evidence=f"Risk Score: {risk_res.risk_score:.1f}, Category: HIGH",
                        source_agent="RiskAgent",
                    )
                )
            confidence = self._compute_confidence(analysis)
            return (
                DecisionOutcome.REJECT,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

        # Priority 3 — Critical missing evidence (Missing docs -> MANUAL_REVIEW)
        missing_docs = self._get_missing_docs(doc_res, anom_res)
        if self.policy.enforce_complete_documents and missing_docs:
            reasons.append(
                DecisionReason(
                    code="DEC-DOC-001",
                    category="DOCUMENT",
                    severity="BLOCKING",
                    description=(
                        f"Mandatory document evidence missing: {', '.join(missing_docs)}. "
                        "Complete financial verification cannot be performed without human intervention."
                    ),
                    evidence=f"Missing document types: {missing_docs}",
                    source_agent="DocumentIntakeAgent",
                )
            )
            confidence = self._compute_confidence(analysis)
            return (
                DecisionOutcome.MANUAL_REVIEW,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

        # Priority 4 — Severe or material unresolved anomalies (Anomalies -> MANUAL_REVIEW)
        if anom_res and anom_res.has_anomalies:
            blocking_flags = [
                f
                for f in anom_res.flags
                if f.severity in self.policy.blocking_anomaly_severities
            ]
            if blocking_flags:
                for flag in blocking_flags:
                    code = (
                        "DEC-ANOM-001"
                        if flag.severity == AnomalySeverity.HIGH
                        else "DEC-ANOM-002"
                    )
                    reasons.append(
                        DecisionReason(
                            code=code,
                            category="ANOMALY",
                            severity="BLOCKING",
                            description=(
                                f"Cross-document discrepancy detected ({flag.rule_id}): {flag.description} "
                                "Human verification required to resolve discrepancy."
                            ),
                            evidence=f"Expected: {flag.expected_value} | Observed: {flag.observed_value} ({flag.evidence})",
                            source_agent="FraudAnomalyAgent",
                        )
                    )
                confidence = self._compute_confidence(analysis)
                return (
                    DecisionOutcome.MANUAL_REVIEW,
                    reasons,
                    positive_factors,
                    negative_factors,
                    blocking_factors,
                    supporting_evidence,
                    confidence,
                )

        # Priority 5 — Eligibility review required
        if elig_res and elig_res.status == EligibilityStatus.REVIEW_REQUIRED:
            review_rules = [
                r.rule_name
                for r in elig_res.rule_results
                if r.status.value == "REVIEW_REQUIRED"
            ]
            reasons.append(
                DecisionReason(
                    code="DEC-ELIG-002",
                    category="ELIGIBILITY",
                    severity="WARNING",
                    description=(
                        f"Underwriting eligibility criteria requires manual review: "
                        f"{'; '.join(review_rules) if review_rules else 'Policy flags requiring review'}."
                    ),
                    evidence=elig_res.remarks
                    or "Eligibility requires manual verification",
                    source_agent="EligibilityAgent",
                )
            )
            confidence = self._compute_confidence(analysis)
            return (
                DecisionOutcome.MANUAL_REVIEW,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

        # Priority 6 — Borderline or High Risk
        if risk_res and risk_res.risk_category == RiskLevel.BORDERLINE:
            reasons.append(
                DecisionReason(
                    code="DEC-RISK-001",
                    category="RISK",
                    severity="WARNING",
                    description=(
                        f"Assessed credit risk is BORDERLINE (Score: {risk_res.risk_score:.1f}/100). "
                        "Debt leverage or credit score sits near underwriting threshold, warranting human underwriter assessment."
                    ),
                    evidence=risk_res.explanation,
                    source_agent="RiskAgent",
                )
            )
            confidence = self._compute_confidence(analysis)
            return (
                self.policy.borderline_risk_action,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

        if risk_res and risk_res.risk_category == RiskLevel.HIGH:
            reasons.append(
                DecisionReason(
                    code="DEC-RISK-002",
                    category="RISK",
                    severity="BLOCKING",
                    description=(
                        f"Assessed credit risk is HIGH (Score: {risk_res.risk_score:.1f}/100), "
                        "exceeding acceptable policy limits."
                    ),
                    evidence=risk_res.explanation,
                    source_agent="RiskAgent",
                )
            )
            confidence = self._compute_confidence(analysis)
            return (
                self.policy.high_risk_action,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

        # Priority 7 — Acceptable application -> APPROVE
        if (
            elig_res
            and elig_res.status == self.policy.mandatory_eligibility_status_for_approval
            and risk_res
            and risk_res.risk_category in self.policy.permitted_approval_risk_tiers
            and (
                not anom_res
                or anom_res.severity
                in self.policy.tolerated_anomaly_severities_for_approval
            )
            and not missing_docs
        ):
            reasons.append(
                DecisionReason(
                    code="DEC-APP-001",
                    category="SYNTHESIS",
                    severity="INFO",
                    description=(
                        f"Application satisfies all policy requirements: ELIGIBLE status, "
                        f"{risk_res.risk_category.value} risk profile (Score: {risk_res.risk_score:.1f}/100), "
                        "complete document evidence, and zero high-severity anomalies."
                    ),
                    evidence=(
                        f"Eligibility: {elig_res.status.value}, "
                        f"Risk Tier: {risk_res.risk_category.value} ({risk_res.risk_score:.1f}/100), "
                        f"Anomalies: {anom_res.severity.value if anom_res else 'NONE'}"
                    ),
                    source_agent="DecisionReasoningAgent",
                )
            )
            confidence = self._compute_confidence(analysis)
            return (
                DecisionOutcome.APPROVE,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

        # Fallback for unexpected state -> MANUAL_REVIEW
        reasons.append(
            DecisionReason(
                code="DEC-SYS-002",
                category="SYSTEM",
                severity="WARNING",
                description="Application exhibits complex or unclassified analytical criteria; routed for manual review.",
                evidence=analysis.summary,
                source_agent="DecisionReasoningAgent",
            )
        )
        confidence = self._compute_confidence(analysis)
        return (
            DecisionOutcome.MANUAL_REVIEW,
            reasons,
            positive_factors,
            negative_factors,
            blocking_factors,
            supporting_evidence,
            confidence,
        )

    # -----------------------------------------------------------------------
    # Helper Extraction Methods
    # -----------------------------------------------------------------------

    def _extract_factors_and_evidence(
        self,
        analysis: UnderwritingAnalysisResult,
        positive_factors: List[str],
        negative_factors: List[str],
        blocking_factors: List[str],
        supporting_evidence: List[Dict[str, Any]],
    ) -> None:
        """Extract traceable positive, negative, and blocking factors from agents."""
        doc_res = analysis.document_result
        elig_res = analysis.eligibility_result
        risk_res = analysis.risk_result
        anom_res = analysis.anomaly_result

        # Document Factors
        if doc_res:
            if doc_res.documents_found:
                positive_factors.append(
                    f"{len(doc_res.documents_found)} mandatory supporting document(s) verified."
                )
            if doc_res.documents_missing:
                msg = f"Missing mandatory document(s): {', '.join(doc_res.documents_missing)}."
                negative_factors.append(msg)
                blocking_factors.append(msg)
            supporting_evidence.append(
                {
                    "source": "DocumentIntakeAgent",
                    "documents_found": [
                        d.document_type for d in doc_res.documents_found
                    ],
                    "documents_missing": doc_res.documents_missing,
                    "ocr_used": doc_res.ocr_used,
                }
            )

        # Eligibility Factors
        if elig_res:
            if elig_res.status == EligibilityStatus.ELIGIBLE:
                positive_factors.append(
                    "All underwriting eligibility criteria satisfied."
                )
            elif elig_res.status == EligibilityStatus.INELIGIBLE:
                msg = f"Ineligible under policy rules: {', '.join(elig_res.rules_failed)}."
                negative_factors.append(msg)
                blocking_factors.append(msg)
            elif elig_res.status == EligibilityStatus.REVIEW_REQUIRED:
                msg = f"Eligibility requires review for rules: {', '.join(elig_res.rules_requiring_review)}."
                negative_factors.append(msg)
                blocking_factors.append(msg)

            for r in elig_res.rule_results:
                if not r.passed:
                    supporting_evidence.append(
                        {
                            "source": "EligibilityAgent",
                            "rule_name": r.rule_name,
                            "reason": r.reason,
                            "actual_value": r.actual_value,
                            "expected_value": r.expected_value,
                        }
                    )

        # Risk Factors
        if risk_res:
            if risk_res.risk_category in [RiskLevel.LOW, RiskLevel.MEDIUM]:
                positive_factors.append(
                    f"Repayment risk tier assessed as {risk_res.risk_category.value} (Score: {risk_res.risk_score:.1f}/100)."
                )
            elif risk_res.risk_category == RiskLevel.BORDERLINE:
                msg = f"Borderline credit risk profile (Score: {risk_res.risk_score:.1f}/100)."
                negative_factors.append(msg)
                blocking_factors.append(msg)
            elif risk_res.risk_category == RiskLevel.HIGH:
                msg = (
                    f"High credit risk profile (Score: {risk_res.risk_score:.1f}/100)."
                )
                negative_factors.append(msg)
                blocking_factors.append(msg)

            for pf in risk_res.protective_factors:
                positive_factors.append(f"Protective: {pf}")
            for rf in risk_res.risk_factors:
                negative_factors.append(f"Risk factor: {rf}")

            supporting_evidence.append(
                {
                    "source": "RiskAgent",
                    "risk_score": risk_res.risk_score,
                    "risk_category": risk_res.risk_category.value,
                    "method": risk_res.method,
                }
            )

        # Anomaly Factors
        if anom_res:
            if not anom_res.has_anomalies:
                positive_factors.append(
                    "No cross-document inconsistencies or suspicious anomalies detected."
                )
            else:
                for flag in anom_res.flags:
                    msg = f"Cross-document discrepancy ({flag.rule_id}): {flag.description}"
                    negative_factors.append(msg)
                    if flag.severity in self.policy.blocking_anomaly_severities:
                        blocking_factors.append(msg)
                    supporting_evidence.append(
                        {
                            "source": "FraudAnomalyAgent",
                            "rule_id": flag.rule_id,
                            "anomaly_type": flag.anomaly_type,
                            "expected_value": flag.expected_value,
                            "observed_value": flag.observed_value,
                            "evidence": flag.evidence,
                        }
                    )

    def _get_missing_docs(
        self,
        doc_res: Optional[DocumentPackageResult],
        anom_res: Optional[AnomalyResult],
    ) -> List[str]:
        """Combine missing documents reported by document intake or anomaly detection."""
        missing: List[str] = []
        if doc_res and doc_res.documents_missing:
            missing.extend(doc_res.documents_missing)
        if anom_res and anom_res.missing_evidence:
            for d in anom_res.missing_evidence:
                if d not in missing:
                    missing.append(d)
        return missing

    def _compute_confidence(
        self,
        analysis: UnderwritingAnalysisResult,
        is_pipeline_failed: bool = False,
    ) -> float:
        """Compute decision confidence based on evidence completeness and analytical agreement.

        NOTE: This score (0-100) measures analytical certainty and data completeness.
        It is NOT a probability of default, repayment, or fraud.
        """
        if (
            is_pipeline_failed
            or analysis.orchestration_status == OrchestrationStatus.FAILED
        ):
            return 20.0

        score = 100.0

        # Pipeline penalty
        if analysis.orchestration_status == OrchestrationStatus.PARTIAL_SUCCESS:
            score -= 20.0

        # Missing documents penalty
        missing_docs = self._get_missing_docs(
            analysis.document_result, analysis.anomaly_result
        )
        if missing_docs:
            score -= min(len(missing_docs) * 10.0, 25.0)

        # Eligibility review penalty
        if (
            analysis.eligibility_result
            and analysis.eligibility_result.status == EligibilityStatus.REVIEW_REQUIRED
        ):
            score -= 15.0

        # Borderline risk uncertainty penalty
        if (
            analysis.risk_result
            and analysis.risk_result.risk_category == RiskLevel.BORDERLINE
        ):
            score -= 15.0

        # Anomaly severity penalty
        if analysis.anomaly_result and analysis.anomaly_result.has_anomalies:
            if analysis.anomaly_result.severity == AnomalySeverity.HIGH:
                score -= 25.0
            elif analysis.anomaly_result.severity == AnomalySeverity.MEDIUM:
                score -= 15.0
            elif analysis.anomaly_result.severity == AnomalySeverity.LOW:
                score -= 5.0

        return round(min(max(score, 10.0), 100.0), 1)


__all__ = ["DecisionRulesEngine"]
