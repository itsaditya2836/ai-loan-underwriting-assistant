"""Cross-Agent Validation, Output Contracts, and Consistency Verification.

Defines:
- Authoritative source hierarchy across analytical domains
- Applicant data validation (detecting NaN/Inf and financial plausibility warnings)
- Contract validators rejecting missing/NaN/out-of-range agent outputs
- Deterministic cross-agent contradiction detection preserving original outputs
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.anomaly import AnomalyResult, AnomalySeverity
from app.schemas.applicant import (
    Applicant,
    DocumentPackageResult,
    EligibilityResult,
    EligibilityStatus,
    RiskLevel,
    RiskResult,
)
from app.schemas.underwriting import (
    AgentExecutionStatus,
    AgentStatus,
    UnderwritingAnalysisResult,
)

AUTHORITATIVE_SOURCES: Dict[str, str] = {
    "identity": "DocumentIntakeAgent (identity_proof) -> Applicant",
    "document_verification": "DocumentIntakeAgent",
    "eligibility": "EligibilityAgent",
    "cross_document_consistency": "FraudAnomalyAgent",
    "credit_risk": "RiskAgent",
}


def get_agent_status(
    agent_statuses: Dict[str, AgentExecutionStatus], *candidate_keys: str
) -> Optional[AgentExecutionStatus]:
    """Resolve AgentExecutionStatus supporting canonical and facade agent key names."""
    for key in candidate_keys:
        if key in agent_statuses:
            return agent_statuses[key]
    return None


def validate_applicant_data(applicant: Applicant) -> List[str]:
    """Validate applicant profile numeric finiteness and emit non-blocking warnings."""
    if not applicant.applicant_id or not applicant.applicant_id.strip():
        raise ValueError("Applicant profile is missing a valid applicant_id.")
    if not applicant.name or not applicant.name.strip():
        raise ValueError("Applicant profile is missing a valid name.")

    numeric_fields = {
        "monthly_income": applicant.monthly_income,
        "existing_emi": applicant.existing_emi,
        "loan_amount": applicant.loan_amount,
        "bank_balance": applicant.bank_balance,
        "employment_years": applicant.employment_years,
    }
    if applicant.monthly_expenses is not None:
        numeric_fields["monthly_expenses"] = applicant.monthly_expenses

    for fname, val in numeric_fields.items():
        if val is None or not math.isfinite(float(val)):
            raise ValueError(
                f"Applicant field '{fname}' is non-finite or invalid: {val}"
            )

    warnings: List[str] = []
    if applicant.monthly_income == 0:
        warnings.append("Applicant monthly_income is 0.0.")
    elif applicant.existing_emi > applicant.monthly_income:
        warnings.append(
            f"Applicant existing_emi ({applicant.existing_emi:.2f}) exceeds "
            f"monthly_income ({applicant.monthly_income:.2f})."
        )
    if (
        applicant.monthly_expenses is not None
        and applicant.monthly_expenses > applicant.monthly_income
    ):
        warnings.append(
            f"Applicant monthly_expenses ({applicant.monthly_expenses:.2f}) exceed "
            f"monthly_income ({applicant.monthly_income:.2f})."
        )
    if applicant.employment_years > max(0.0, float(applicant.age) - 16.0):
        warnings.append(
            f"Applicant employment_years ({applicant.employment_years:.1f}) exceeds "
            f"working horizon (age {applicant.age} - 16)."
        )

    return sorted(warnings)


def validate_document_output(
    result: Any, expected_applicant_id: str
) -> DocumentPackageResult:
    """Validate Stage 3 DocumentIntakeAgent output contract."""
    if not isinstance(result, DocumentPackageResult):
        raise ValueError(
            f"Invalid DocumentIntakeAgent output type: {type(result).__name__}"
        )
    if (
        result.applicant_id
        and expected_applicant_id
        and result.applicant_id != expected_applicant_id
    ):
        raise ValueError(
            f"DocumentPackageResult applicant_id '{result.applicant_id}' does not match '{expected_applicant_id}'."
        )
    return result


def validate_eligibility_output(
    result: Any, expected_applicant_id: str
) -> EligibilityResult:
    """Validate Stage 4 EligibilityAgent output contract."""
    if not isinstance(result, EligibilityResult):
        raise ValueError(
            f"Invalid EligibilityAgent output type: {type(result).__name__}"
        )
    if not isinstance(result.status, EligibilityStatus):
        raise ValueError(f"Invalid eligibility status: {result.status}")
    if (
        result.applicant_id
        and expected_applicant_id
        and result.applicant_id != expected_applicant_id
    ):
        raise ValueError(
            f"EligibilityResult applicant_id '{result.applicant_id}' does not match '{expected_applicant_id}'."
        )
    if result.dti_ratio is not None and not math.isfinite(float(result.dti_ratio)):
        raise ValueError(
            f"Invalid non-finite eligibility dti_ratio: {result.dti_ratio}"
        )
    if result.max_eligible_amount is not None and not math.isfinite(
        float(result.max_eligible_amount)
    ):
        raise ValueError(
            f"Invalid non-finite eligibility max_eligible_amount: {result.max_eligible_amount}"
        )
    return result


def validate_risk_output(result: Any, expected_applicant_id: str) -> RiskResult:
    """Validate Stage 5 RiskAgent output contract (never accepts NaN or out-of-range scores)."""
    if not isinstance(result, RiskResult):
        raise ValueError(f"Invalid RiskAgent output type: {type(result).__name__}")
    if not isinstance(result.risk_category, RiskLevel):
        raise ValueError(f"Invalid risk category: {result.risk_category}")
    if (
        result.risk_score is None
        or not math.isfinite(float(result.risk_score))
        or not (0.0 <= float(result.risk_score) <= 100.0)
    ):
        raise ValueError(
            f"Invalid risk_score '{result.risk_score}'; expected finite float in [0.0, 100.0]."
        )
    if (
        result.applicant_id
        and expected_applicant_id
        and result.applicant_id != expected_applicant_id
    ):
        raise ValueError(
            f"RiskResult applicant_id '{result.applicant_id}' does not match '{expected_applicant_id}'."
        )
    return result


def validate_anomaly_output(result: Any, expected_applicant_id: str) -> AnomalyResult:
    """Validate Stage 6 FraudAnomalyAgent output contract."""
    if not isinstance(result, AnomalyResult):
        raise ValueError(
            f"Invalid FraudAnomalyAgent output type: {type(result).__name__}"
        )
    if not isinstance(result.severity, AnomalySeverity):
        raise ValueError(f"Invalid anomaly severity: {result.severity}")
    if (
        result.anomaly_score is None
        or not math.isfinite(float(result.anomaly_score))
        or not (0.0 <= float(result.anomaly_score) <= 100.0)
    ):
        raise ValueError(
            f"Invalid anomaly_score '{result.anomaly_score}'; expected finite float in [0.0, 100.0]."
        )
    if (
        result.applicant_id
        and expected_applicant_id
        and result.applicant_id != expected_applicant_id
    ):
        raise ValueError(
            f"AnomalyResult applicant_id '{result.applicant_id}' does not match '{expected_applicant_id}'."
        )
    return result


def check_cross_agent_consistency(
    analysis: UnderwritingAnalysisResult,
    applicant: Optional[Applicant] = None,
) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """Detect material cross-agent contradictions without overwriting original outputs."""
    conflicts: List[Dict[str, Any]] = []
    app_id = analysis.applicant_id or analysis.application_id

    doc_res = analysis.document_result
    elig_res = analysis.eligibility_result
    risk_res = analysis.risk_result
    anom_res = analysis.anomaly_result

    doc_status = get_agent_status(
        analysis.agent_statuses, "document_agent", "DocumentIntakeAgent"
    )
    elig_status = get_agent_status(
        analysis.agent_statuses, "eligibility_agent", "EligibilityAgent"
    )
    risk_status = get_agent_status(analysis.agent_statuses, "risk_agent", "RiskAgent")
    anom_status = get_agent_status(
        analysis.agent_statuses, "anomaly_agent", "FraudAnomalyAgent"
    )

    # 1. Applicant ID mismatch across agents
    agent_ids: Dict[str, str] = {}
    if doc_res and doc_res.applicant_id:
        agent_ids["DocumentIntakeAgent"] = doc_res.applicant_id
    if elig_res and elig_res.applicant_id:
        agent_ids["EligibilityAgent"] = elig_res.applicant_id
    if risk_res and risk_res.applicant_id:
        agent_ids["RiskAgent"] = risk_res.applicant_id
    if anom_res and anom_res.applicant_id:
        agent_ids["FraudAnomalyAgent"] = anom_res.applicant_id
    if applicant and applicant.applicant_id:
        agent_ids["Applicant"] = applicant.applicant_id

    mismatched_ids = {
        src: aid for src, aid in agent_ids.items() if app_id and aid != app_id
    }
    if mismatched_ids:
        conflicts.append(
            {
                "conflict_id": "CONFLICT-ID-MISMATCH",
                "domain": "identity",
                "severity": "BLOCKING",
                "authoritative_source": AUTHORITATIVE_SOURCES["identity"],
                "conflicting_sources": sorted(mismatched_ids.keys()),
                "details": mismatched_ids,
                "description": (
                    f"Applicant identifier mismatch across agent outputs: expected '{app_id}', "
                    f"observed {mismatched_ids}."
                ),
            }
        )

    # 2. Eligibility=ELIGIBLE vs incomplete/failed/corrupt document state
    doc_missing = sorted(set((doc_res.documents_missing if doc_res else []) or []))
    doc_has_errors = bool(
        doc_res
        and (
            doc_res.processing_status in ("failed", "completed_with_errors")
            or doc_res.unclassified_documents
            or doc_res.invalid_fields
            or doc_res.ambiguous_fields
            or doc_res.field_conflicts
            or not doc_res.is_complete
        )
    )
    doc_failed = bool(
        (doc_status and doc_status.status == AgentStatus.FAILED)
        or (doc_res and doc_res.processing_status == "failed")
    )
    if (
        elig_res
        and elig_res.status == EligibilityStatus.ELIGIBLE
        and (doc_res is None or doc_failed or doc_missing or doc_has_errors)
    ):
        conflicts.append(
            {
                "conflict_id": "CONFLICT-ELIG-DOC",
                "domain": "document_verification",
                "severity": "BLOCKING",
                "authoritative_source": AUTHORITATIVE_SOURCES["document_verification"],
                "conflicting_sources": ["EligibilityAgent", "DocumentIntakeAgent"],
                "details": {
                    "eligibility_status": elig_res.status.value,
                    "doc_processing_status": (
                        doc_res.processing_status if doc_res else "UNAVAILABLE"
                    ),
                    "documents_missing": doc_missing,
                    "invalid_fields": (
                        sorted(doc_res.invalid_fields.keys())
                        if doc_res and doc_res.invalid_fields
                        else []
                    ),
                    "field_conflicts": (
                        sorted(doc_res.field_conflicts.keys())
                        if doc_res and doc_res.field_conflicts
                        else []
                    ),
                },
                "description": (
                    "EligibilityAgent reported ELIGIBLE, but document verification is failed, "
                    "incomplete, or contains unresolved field conflicts/invalid values."
                ),
            }
        )

    # 3. Profile / Extracted / RiskAgent Income Consistency
    income_sources: Dict[str, float] = {}
    if applicant is not None and applicant.monthly_income > 0:
        income_sources["Applicant"] = float(applicant.monthly_income)

    if doc_res and doc_res.all_extracted_fields:
        ef_inc = doc_res.all_extracted_fields.get(
            "declared_monthly_income"
        ) or doc_res.all_extracted_fields.get("monthly_income")
        if (
            ef_inc is not None
            and ef_inc.value is not None
            and getattr(ef_inc, "validation_status", "valid") != "invalid"
        ):
            try:
                inc_val = float(ef_inc.value)
                if math.isfinite(inc_val) and inc_val > 0:
                    income_sources["DocumentIntakeAgent"] = inc_val
            except (TypeError, ValueError):
                pass

    if risk_res and risk_res.features_used:
        r_inc = risk_res.features_used.get("monthly_income")
        if r_inc is not None:
            try:
                r_val = float(r_inc)
                if math.isfinite(r_val) and r_val > 0:
                    income_sources["RiskAgent"] = r_val
            except (TypeError, ValueError):
                pass

    if len(income_sources) >= 2:
        max_inc = max(income_sources.values())
        min_inc = min(income_sources.values())
        pct_gap = ((max_inc - min_inc) / max_inc) * 100.0 if max_inc > 0 else 0.0
        if pct_gap > 15.0:
            conflicts.append(
                {
                    "conflict_id": "CONFLICT-INCOME-MISMATCH",
                    "domain": "financial_capacity",
                    "severity": "BLOCKING",
                    "authoritative_source": "DocumentIntakeAgent -> Applicant",
                    "conflicting_sources": sorted(income_sources.keys()),
                    "details": {
                        k: round(v, 2) for k, v in sorted(income_sources.items())
                    },
                    "description": (
                        f"Monthly income differs materially ({pct_gap:.1f}%) across sources: "
                        f"{ {k: round(v, 2) for k, v in sorted(income_sources.items())} }."
                    ),
                }
            )

    # 4. RiskAgent Credit Score vs EligibilityAgent Credit Score Consistency
    if elig_res and risk_res and risk_res.features_used:
        r_cs = risk_res.features_used.get("credit_score")
        cs_rule = next(
            (r for r in elig_res.rule_results if r.rule_id == "MIN_CREDIT_SCORE"),
            None,
        )
        if (
            r_cs is not None
            and cs_rule is not None
            and cs_rule.actual_value is not None
        ):
            try:
                if (
                    abs(
                        int(round(float(r_cs)))
                        - int(round(float(cs_rule.actual_value)))
                    )
                    > 0
                ):
                    conflicts.append(
                        {
                            "conflict_id": "CONFLICT-CREDIT-SCORE",
                            "domain": "credit_risk",
                            "severity": "BLOCKING",
                            "authoritative_source": "EligibilityAgent / RiskAgent",
                            "conflicting_sources": ["EligibilityAgent", "RiskAgent"],
                            "details": {
                                "eligibility_credit_score": cs_rule.actual_value,
                                "risk_credit_score": r_cs,
                            },
                            "description": (
                                f"Credit score mismatch between EligibilityAgent ({cs_rule.actual_value}) "
                                f"and RiskAgent ({r_cs})."
                            ),
                        }
                    )
            except (TypeError, ValueError):
                pass

    # 5. Missing or Failed Required Agent Results
    if elig_status and elig_status.status == AgentStatus.FAILED or elig_res is None:
        conflicts.append(
            {
                "conflict_id": "CONFLICT-ELIG-UNAVAILABLE",
                "domain": "eligibility",
                "severity": "BLOCKING",
                "authoritative_source": AUTHORITATIVE_SOURCES["eligibility"],
                "conflicting_sources": ["EligibilityAgent"],
                "details": {
                    "error": (
                        elig_status.error
                        if elig_status
                        else "Missing EligibilityResult"
                    )
                },
                "description": "Eligibility assessment is unavailable or failed; automated approval/rejection cannot proceed cleanly.",
            }
        )

    if (
        (risk_status and risk_status.status == AgentStatus.FAILED)
        or risk_res is None
        or not math.isfinite(float(risk_res.risk_score))
        or not (0.0 <= float(risk_res.risk_score) <= 100.0)
    ):
        conflicts.append(
            {
                "conflict_id": "CONFLICT-RISK-UNAVAILABLE",
                "domain": "credit_risk",
                "severity": "BLOCKING",
                "authoritative_source": AUTHORITATIVE_SOURCES["credit_risk"],
                "conflicting_sources": ["RiskAgent"],
                "details": {
                    "risk_score": risk_res.risk_score if risk_res else None,
                    "error": risk_status.error if risk_status else "Missing RiskResult",
                },
                "description": "Risk assessment failed, was unavailable, or produced an invalid risk score.",
            }
        )

    if (anom_status and anom_status.status == AgentStatus.FAILED) or anom_res is None:
        conflicts.append(
            {
                "conflict_id": "CONFLICT-FRAUD-UNAVAILABLE",
                "domain": "cross_document_consistency",
                "severity": "BLOCKING",
                "authoritative_source": AUTHORITATIVE_SOURCES[
                    "cross_document_consistency"
                ],
                "conflicting_sources": ["FraudAnomalyAgent"],
                "details": {
                    "error": (
                        anom_status.error if anom_status else "Missing AnomalyResult"
                    )
                },
                "description": "Fraud and anomaly detection failed or was unavailable; cannot assume clean verification.",
            }
        )

    # Stable deterministic conflict sorting
    conflicts.sort(key=lambda c: str(c.get("conflict_id", "")))
    return dict(AUTHORITATIVE_SOURCES), conflicts


__all__ = [
    "AUTHORITATIVE_SOURCES",
    "check_cross_agent_consistency",
    "get_agent_status",
    "validate_anomaly_output",
    "validate_applicant_data",
    "validate_document_output",
    "validate_eligibility_output",
    "validate_risk_output",
]
