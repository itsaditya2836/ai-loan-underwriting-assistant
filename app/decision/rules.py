"""Deterministic Decision Rules Engine.

Implements strict safety-first rule precedence, cross-agent conflict gating,
evidence evaluation, non-calibrated confidence scoring, factor extraction, and
explainable recommendation generation.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from app.decision.policy import DecisionPolicy
from app.orchestration.consistency import (
    check_cross_agent_consistency,
    get_agent_status,
)
from app.schemas.anomaly import AnomalyResult, AnomalySeverity
from app.schemas.applicant import (
    DocumentPackageResult,
    EligibilityStatus,
    RiskLevel,
    RiskResult,
)
from app.schemas.decision import DecisionOutcome, DecisionReason
from app.schemas.underwriting import (
    AgentStatus,
    OrchestrationStatus,
    UnderwritingAnalysisResult,
)


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
        """Apply strict precedence and safety safeguards to synthesize a recommendation."""
        reasons: List[DecisionReason] = []
        positive_factors: List[str] = []
        negative_factors: List[str] = []
        blocking_factors: List[str] = []
        supporting_evidence: List[Dict[str, Any]] = []

        # Compute cross-agent conflicts dynamically if caller passed raw analysis
        conflicts = list(analysis.consistency_conflicts)
        if not conflicts:
            auth_sources, computed_conflicts = check_cross_agent_consistency(analysis)
            if not analysis.authoritative_sources:
                analysis.authoritative_sources = auth_sources
            conflicts = computed_conflicts

        doc_res = analysis.document_result
        elig_res = analysis.eligibility_result
        risk_res = analysis.risk_result
        anom_res = analysis.anomaly_result

        self._extract_factors_and_evidence(
            analysis=analysis,
            conflicts=conflicts,
            positive_factors=positive_factors,
            negative_factors=negative_factors,
            blocking_factors=blocking_factors,
            supporting_evidence=supporting_evidence,
        )

        # -------------------------------------------------------------------
        # Strict Safety-First Rule Precedence Evaluation
        # -------------------------------------------------------------------

        # Priority 1 — Overall Pipeline Failure -> MANUAL_REVIEW
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
            confidence = self._compute_confidence(
                analysis, conflicts=conflicts, is_pipeline_failed=True
            )
            return (
                DecisionOutcome.MANUAL_REVIEW,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

        # Priority 2 — Policy-Supported Critical Eligibility Failure -> REJECT
        if elig_res and elig_res.status == EligibilityStatus.INELIGIBLE:
            failed_rules = [r.rule_name for r in elig_res.rule_results if not r.passed]
            failed_reasons = [
                f"{r.rule_name}: {r.reason}"
                for r in elig_res.rule_results
                if not r.passed
            ]
            has_policy_support = bool(
                failed_rules or elig_res.rules_failed or elig_res.reasons
            )
            if not has_policy_support:
                # Never reject without valid policy-supported reason
                reasons.append(
                    DecisionReason(
                        code="DEC-ELIG-004",
                        category="ELIGIBILITY",
                        severity="BLOCKING",
                        description=(
                            "Eligibility status reported INELIGIBLE without specific policy rule evidence; "
                            "escalated for manual review."
                        ),
                        evidence=elig_res.remarks,
                        source_agent="EligibilityAgent",
                    )
                )
                confidence = self._compute_confidence(analysis, conflicts=conflicts)
                return (
                    DecisionOutcome.MANUAL_REVIEW,
                    reasons,
                    positive_factors,
                    negative_factors,
                    blocking_factors,
                    supporting_evidence,
                    confidence,
                )

            rule_summary = (
                "; ".join(failed_rules)
                if failed_rules
                else "; ".join(elig_res.rules_failed or elig_res.reasons)
            )
            evidence_summary = (
                "; ".join(failed_reasons)
                if failed_reasons
                else "; ".join(elig_res.reasons or elig_res.rules_failed)
            )
            reasons.append(
                DecisionReason(
                    code="DEC-ELIG-001",
                    category="ELIGIBILITY",
                    severity="BLOCKING",
                    description=(
                        f"Application is INELIGIBLE due to failure of mandatory underwriting rule(s): "
                        f"{rule_summary}."
                    ),
                    evidence=evidence_summary,
                    source_agent="EligibilityAgent",
                )
            )
            if risk_res and risk_res.risk_category == RiskLevel.HIGH:
                reasons.append(
                    DecisionReason(
                        code="DEC-RISK-002",
                        category="RISK",
                        severity="BLOCKING",
                        description=(
                            f"Assessed credit risk is HIGH (Score: {risk_res.risk_score:.1f}/100), "
                            "compounded by adverse financial/credit profile."
                        ),
                        evidence=self._format_risk_evidence(risk_res),
                        source_agent="RiskAgent",
                    )
                )
            confidence = self._compute_confidence(analysis, conflicts=conflicts)
            return (
                DecisionOutcome.REJECT,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

        # Priority 3 — Document Completeness, Failure, Invalid & Ambiguous Fields -> MANUAL_REVIEW
        missing_docs = self._get_missing_docs(doc_res, anom_res)
        doc_unverified = self._has_unverified_documents(analysis)
        if (self.policy.enforce_complete_documents and missing_docs) or doc_unverified:
            detail_parts: List[str] = []
            if missing_docs:
                detail_parts.append(
                    f"Mandatory document evidence missing: {', '.join(missing_docs)}"
                )
            if doc_unverified:
                detail_parts.append(self._describe_unverified_docs(analysis))
            full_desc = (
                ". ".join(detail_parts).strip(". ") + ". Human verification required."
            )
            reasons.append(
                DecisionReason(
                    code="DEC-DOC-001",
                    category="DOCUMENT",
                    severity="BLOCKING",
                    description=full_desc,
                    evidence=(
                        f"Missing documents: {missing_docs}; "
                        f"Doc status: {doc_res.processing_status if doc_res else 'UNAVAILABLE'}"
                    ),
                    source_agent="DocumentIntakeAgent",
                )
            )
            confidence = self._compute_confidence(analysis, conflicts=conflicts)
            return (
                DecisionOutcome.MANUAL_REVIEW,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

        # Priority 4 — Missing / Failed Fraud Check or Blocking Anomalies -> MANUAL_REVIEW
        fraud_unavailable = self._is_fraud_unavailable(analysis)
        if fraud_unavailable:
            anom_status = get_agent_status(
                analysis.agent_statuses, "anomaly_agent", "FraudAnomalyAgent"
            )
            reasons.append(
                DecisionReason(
                    code="DEC-FRAUD-001",
                    category="ANOMALY",
                    severity="BLOCKING",
                    description=(
                        "Fraud and cross-document consistency verification failed or was unavailable; "
                        "cannot assume clean verification without manual review."
                    ),
                    evidence=(
                        anom_status.error if anom_status else "Missing AnomalyResult"
                    ),
                    source_agent="FraudAnomalyAgent",
                )
            )
            confidence = self._compute_confidence(analysis, conflicts=conflicts)
            return (
                DecisionOutcome.MANUAL_REVIEW,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

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
                            evidence=(
                                f"Expected: {flag.expected_value} | Observed: {flag.observed_value} ({flag.evidence})"
                            ),
                            source_agent="FraudAnomalyAgent",
                        )
                    )
                confidence = self._compute_confidence(analysis, conflicts=conflicts)
                return (
                    DecisionOutcome.MANUAL_REVIEW,
                    reasons,
                    positive_factors,
                    negative_factors,
                    blocking_factors,
                    supporting_evidence,
                    confidence,
                )

        # Priority 5 — Missing/Failed Eligibility or Review Required -> MANUAL_REVIEW
        if self._is_eligibility_unavailable(analysis):
            elig_status = get_agent_status(
                analysis.agent_statuses, "eligibility_agent", "EligibilityAgent"
            )
            reasons.append(
                DecisionReason(
                    code="DEC-ELIG-004",
                    category="ELIGIBILITY",
                    severity="BLOCKING",
                    description=(
                        "Eligibility assessment failed or was unavailable; manual review required."
                    ),
                    evidence=(
                        elig_status.error
                        if elig_status
                        else "Missing EligibilityResult"
                    ),
                    source_agent="EligibilityAgent",
                )
            )
            confidence = self._compute_confidence(analysis, conflicts=conflicts)
            return (
                DecisionOutcome.MANUAL_REVIEW,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

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
            confidence = self._compute_confidence(analysis, conflicts=conflicts)
            return (
                DecisionOutcome.MANUAL_REVIEW,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

        # Priority 6 — Unavailable/Invalid Risk, Borderline Risk, or High Risk
        if self._is_risk_unavailable(analysis):
            risk_status = get_agent_status(
                analysis.agent_statuses, "risk_agent", "RiskAgent"
            )
            reasons.append(
                DecisionReason(
                    code="DEC-RISK-004",
                    category="RISK",
                    severity="BLOCKING",
                    description=(
                        "Credit risk assessment failed, was unavailable, or produced an invalid score; "
                        "manual underwriting review required."
                    ),
                    evidence=(
                        risk_status.error
                        if risk_status
                        else "Missing/invalid RiskResult"
                    ),
                    source_agent="RiskAgent",
                )
            )
            confidence = self._compute_confidence(analysis, conflicts=conflicts)
            return (
                DecisionOutcome.MANUAL_REVIEW,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

        # Priority 7 — Unresolved Cross-Agent Output Contradictions -> MANUAL_REVIEW
        blocking_conflicts = [c for c in conflicts if c.get("severity") == "BLOCKING"]
        if blocking_conflicts:
            for conf_item in blocking_conflicts:
                reasons.append(
                    DecisionReason(
                        code="DEC-CON-001",
                        category="SYSTEM",
                        severity="BLOCKING",
                        description=str(
                            conf_item.get(
                                "description", "Cross-agent conflict detected."
                            )
                        ),
                        evidence=str(conf_item.get("details", "")),
                        source_agent=", ".join(conf_item.get("conflicting_sources", []))
                        or "UnderwritingOrchestrator",
                    )
                )
            confidence = self._compute_confidence(analysis, conflicts=conflicts)
            return (
                DecisionOutcome.MANUAL_REVIEW,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

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
                    evidence=self._format_risk_evidence(risk_res),
                    source_agent="RiskAgent",
                )
            )
            confidence = self._compute_confidence(analysis, conflicts=conflicts)
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
                        f"Assessed credit risk is HIGH (Score: {risk_res.risk_score:.1f}/100) "
                        f"with risk drivers: {'; '.join(risk_res.risk_factors) if risk_res.risk_factors else 'Elevated policy risk profile'}."
                    ),
                    evidence=self._format_risk_evidence(risk_res),
                    source_agent="RiskAgent",
                )
            )
            confidence = self._compute_confidence(analysis, conflicts=conflicts)
            return (
                self.policy.high_risk_action,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

        # Priority 8 — Strict Verified Approval Safeguard -> APPROVE
        confidence = self._compute_confidence(analysis, conflicts=conflicts)
        can_approve = (
            analysis.orchestration_status == OrchestrationStatus.SUCCESS
            and not self._any_required_agent_failed(analysis)
            and elig_res is not None
            and elig_res.status == self.policy.mandatory_eligibility_status_for_approval
            and risk_res is not None
            and risk_res.risk_category in self.policy.permitted_approval_risk_tiers
            and anom_res is not None
            and anom_res.severity
            in self.policy.tolerated_anomaly_severities_for_approval
            and not missing_docs
            and not doc_unverified
            and not blocking_conflicts
            and confidence >= self.policy.min_confidence_for_approval
        )
        if can_approve:
            reasons.append(
                DecisionReason(
                    code="DEC-APP-001",
                    category="SYNTHESIS",
                    severity="INFO",
                    description=(
                        f"Application satisfies all policy requirements: ELIGIBLE status, "
                        f"{risk_res.risk_category.value} risk profile (Score: {risk_res.risk_score:.1f}/100), "
                        "complete document evidence, and zero material anomalies or agent conflicts."
                    ),
                    evidence=(
                        f"Eligibility: {elig_res.status.value}, "
                        f"Risk Tier: {risk_res.risk_category.value} ({risk_res.risk_score:.1f}/100), "
                        f"Anomalies: {anom_res.severity.value}"
                    ),
                    source_agent="DecisionReasoningAgent",
                )
            )
            return (
                DecisionOutcome.APPROVE,
                reasons,
                positive_factors,
                negative_factors,
                blocking_factors,
                supporting_evidence,
                confidence,
            )

        # Fail-Safe Fallback -> MANUAL_REVIEW (never unsafe auto-approval)
        reasons.append(
            DecisionReason(
                code="DEC-SYS-002",
                category="SYSTEM",
                severity="WARNING",
                description=(
                    "Pipeline safeguards prevented automatic approval due to partial execution, "
                    "low evidence confidence, or incomplete verification; routed for manual review."
                ),
                evidence=analysis.error_message or analysis.summary,
                source_agent="DecisionReasoningAgent",
            )
        )
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
    # Helper Extraction & Safety Check Methods
    # -----------------------------------------------------------------------

    @staticmethod
    def _format_risk_evidence(risk_res: RiskResult) -> str:
        factors = (
            "; ".join(risk_res.risk_factors) if risk_res.risk_factors else "None listed"
        )
        return (
            f"Tier={risk_res.risk_category.value}, Score={risk_res.risk_score:.1f}/100, "
            f"Method={risk_res.method}, Key Factors=[{factors}]"
        )

    def _extract_factors_and_evidence(
        self,
        analysis: UnderwritingAnalysisResult,
        conflicts: List[Dict[str, Any]],
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
                msg = f"Missing mandatory document(s): {', '.join(sorted(doc_res.documents_missing))}."
                negative_factors.append(msg)
                blocking_factors.append(msg)
            elif self._has_unverified_documents(analysis):
                msg = self._describe_unverified_docs(analysis)
                negative_factors.append(msg)
                blocking_factors.append(msg)

            supporting_evidence.append(
                {
                    "source": "DocumentIntakeAgent",
                    "documents_found": [
                        d.document_type for d in doc_res.documents_found
                    ],
                    "documents_missing": sorted(doc_res.documents_missing),
                    "ocr_used": doc_res.ocr_used,
                    "processing_status": doc_res.processing_status,
                }
            )
        elif self._has_unverified_documents(analysis):
            msg = "Document intake failed; supporting documents could not be verified."
            negative_factors.append(msg)
            blocking_factors.append(msg)

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
        else:
            msg = "Eligibility evaluation unavailable or failed."
            negative_factors.append(msg)
            blocking_factors.append(msg)

        # Risk Factors
        if risk_res and not self._is_risk_unavailable(analysis):
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
        else:
            msg = "Credit risk assessment unavailable or failed."
            negative_factors.append(msg)
            blocking_factors.append(msg)

        # Anomaly Factors
        if anom_res and not self._is_fraud_unavailable(analysis):
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
        else:
            msg = "Fraud and anomaly detection unavailable or failed."
            negative_factors.append(msg)
            blocking_factors.append(msg)

        # Cross-Agent Conflicts
        for conf_item in conflicts:
            msg = str(conf_item.get("description", ""))
            if msg:
                negative_factors.append(msg)
                if conf_item.get("severity") == "BLOCKING":
                    blocking_factors.append(msg)
            supporting_evidence.append(
                {
                    "source": "CrossAgentConsistency",
                    "conflict_id": conf_item.get("conflict_id"),
                    "conflicting_sources": conf_item.get("conflicting_sources"),
                    "details": conf_item.get("details"),
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
        return sorted(missing)

    @staticmethod
    def _has_unverified_documents(analysis: UnderwritingAnalysisResult) -> bool:
        """Return True when document verification failed or produced invalid/ambiguous/unclassified outputs."""
        doc_res = analysis.document_result
        doc_status = get_agent_status(
            analysis.agent_statuses, "document_agent", "DocumentIntakeAgent"
        )
        if doc_status is not None and doc_status.status in (
            AgentStatus.FAILED,
            AgentStatus.SKIPPED,
        ):
            return True
        if doc_res is None:
            return True
        if doc_res.processing_status in ("failed", "completed_with_errors"):
            return True
        if not doc_res.documents_found:
            return True
        if (
            doc_res.unclassified_documents
            or doc_res.invalid_fields
            or doc_res.ambiguous_fields
            or doc_res.field_conflicts
        ):
            return True
        return False

    @staticmethod
    def _describe_unverified_docs(analysis: UnderwritingAnalysisResult) -> str:
        doc_res = analysis.document_result
        if doc_res is None:
            return "Document verification result is missing"
        issues: List[str] = []
        if doc_res.processing_status in ("failed", "completed_with_errors"):
            issues.append(f"document processing status='{doc_res.processing_status}'")
        if doc_res.unclassified_documents:
            issues.append(f"unclassified files={doc_res.unclassified_documents}")
        if doc_res.invalid_fields:
            issues.append(f"invalid fields in {sorted(doc_res.invalid_fields.keys())}")
        if doc_res.ambiguous_fields:
            issues.append(
                f"ambiguous fields in {sorted(doc_res.ambiguous_fields.keys())}"
            )
        if doc_res.field_conflicts:
            issues.append(
                f"conflicting document fields {sorted(doc_res.field_conflicts.keys())}"
            )
        if not doc_res.documents_found:
            issues.append("no verifiable supporting documents extracted")
        return "Document verification incomplete (" + "; ".join(issues) + ")"

    @staticmethod
    def _is_fraud_unavailable(analysis: UnderwritingAnalysisResult) -> bool:
        anom_status = get_agent_status(
            analysis.agent_statuses, "anomaly_agent", "FraudAnomalyAgent"
        )
        if anom_status is not None and anom_status.status in (
            AgentStatus.FAILED,
            AgentStatus.SKIPPED,
        ):
            return True
        return analysis.anomaly_result is None

    @staticmethod
    def _is_eligibility_unavailable(analysis: UnderwritingAnalysisResult) -> bool:
        elig_status = get_agent_status(
            analysis.agent_statuses, "eligibility_agent", "EligibilityAgent"
        )
        if elig_status is not None and elig_status.status in (
            AgentStatus.FAILED,
            AgentStatus.SKIPPED,
        ):
            return True
        return analysis.eligibility_result is None

    @staticmethod
    def _is_risk_unavailable(analysis: UnderwritingAnalysisResult) -> bool:
        risk_status = get_agent_status(
            analysis.agent_statuses, "risk_agent", "RiskAgent"
        )
        if risk_status is not None and risk_status.status in (
            AgentStatus.FAILED,
            AgentStatus.SKIPPED,
        ):
            return True
        r = analysis.risk_result
        if r is None or r.risk_score is None:
            return True
        return not math.isfinite(float(r.risk_score)) or not (
            0.0 <= float(r.risk_score) <= 100.0
        )

    def _any_required_agent_failed(self, analysis: UnderwritingAnalysisResult) -> bool:
        return (
            self._has_unverified_documents(analysis)
            or self._is_eligibility_unavailable(analysis)
            or self._is_fraud_unavailable(analysis)
            or self._is_risk_unavailable(analysis)
        )

    def _compute_confidence(
        self,
        analysis: UnderwritingAnalysisResult,
        conflicts: Optional[List[Dict[str, Any]]] = None,
        is_pipeline_failed: bool = False,
    ) -> float:
        """Compute non-calibrated evidence completeness & agreement score in [10, 100]."""
        if (
            is_pipeline_failed
            or analysis.orchestration_status == OrchestrationStatus.FAILED
        ):
            return 20.0

        score = 100.0

        if analysis.orchestration_status == OrchestrationStatus.PARTIAL_SUCCESS:
            score -= 20.0

        if self._is_fraud_unavailable(analysis):
            score -= 20.0
        if self._is_risk_unavailable(analysis):
            score -= 20.0
        if self._is_eligibility_unavailable(analysis):
            score -= 20.0

        missing_docs = self._get_missing_docs(
            analysis.document_result, analysis.anomaly_result
        )
        if missing_docs:
            score -= min(len(missing_docs) * 10.0, 25.0)

        if conflicts:
            score -= min(len(conflicts) * 10.0, 25.0)

        if (
            analysis.eligibility_result
            and analysis.eligibility_result.status == EligibilityStatus.REVIEW_REQUIRED
        ):
            score -= 15.0

        if (
            analysis.risk_result
            and analysis.risk_result.risk_category == RiskLevel.BORDERLINE
        ):
            score -= 15.0

        if analysis.anomaly_result and analysis.anomaly_result.has_anomalies:
            if analysis.anomaly_result.severity == AnomalySeverity.HIGH:
                score -= 25.0
            elif analysis.anomaly_result.severity == AnomalySeverity.MEDIUM:
                score -= 15.0
            elif analysis.anomaly_result.severity == AnomalySeverity.LOW:
                score -= 5.0

        return round(min(max(score, 10.0), 100.0), 1)


__all__ = ["DecisionRulesEngine"]
