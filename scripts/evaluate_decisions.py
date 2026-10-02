"""Underwriting Decision & Reasoning Evaluation Script.

Evaluates Stage 8 Decision & Reasoning Agent across:
- All 30 ingested applicant document packages (APP0001 - APP0030) via Stage 7 Orchestrator.
- Evaluates decision synthesis, rule precedence, reason code distributions, and confidence.

Reports:
- Per-applicant table of Eligibility, Risk Tier, Anomaly Severity, Final Recommendation, and Reason Codes
- Aggregate recommendation distribution (APPROVE, REJECT, MANUAL_REVIEW)
- Manual review rate and reason code frequency distribution
- Evidence completeness statistics
- Cohort-level decision breakdown across all 6 synthetic cohorts
- Sample decision inspection views with positive, negative, and blocking factors
- Explicit research notice: descriptive policy evaluation, not calibrated default/fraud accuracy
"""

import os
import sys
from typing import Any, Dict, List

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agents.decision_agent import DecisionReasoningAgent
from app.orchestration.orchestrator import UnderwritingOrchestrator
from app.schemas.decision import DecisionOutcome, DecisionReasoningResult

TOTAL_APPLICANTS = 30


def evaluate_decisions() -> Dict[str, Any]:
    """Execute and evaluate DecisionReasoningAgent across APP0001 to APP0030."""
    orchestrator = UnderwritingOrchestrator()
    decision_agent = DecisionReasoningAgent()

    results: List[DecisionReasoningResult] = []
    cohorts: Dict[str, Dict[str, Any]] = {
        "Normal / Consistent (01-05)": {
            "range": range(1, 6),
            "total": 0,
            "APPROVE": 0,
            "REJECT": 0,
            "MANUAL_REVIEW": 0,
            "reasons": {},
        },
        "Income Mismatch (06-10)": {
            "range": range(6, 11),
            "total": 0,
            "APPROVE": 0,
            "REJECT": 0,
            "MANUAL_REVIEW": 0,
            "reasons": {},
        },
        "Name Mismatch (11-15)": {
            "range": range(11, 16),
            "total": 0,
            "APPROVE": 0,
            "REJECT": 0,
            "MANUAL_REVIEW": 0,
            "reasons": {},
        },
        "Missing Documents (16-20)": {
            "range": range(16, 21),
            "total": 0,
            "APPROVE": 0,
            "REJECT": 0,
            "MANUAL_REVIEW": 0,
            "reasons": {},
        },
        "Financial Inconsistency (21-25)": {
            "range": range(21, 26),
            "total": 0,
            "APPROVE": 0,
            "REJECT": 0,
            "MANUAL_REVIEW": 0,
            "reasons": {},
        },
        "Borderline Risk Profile (26-30)": {
            "range": range(26, 31),
            "total": 0,
            "APPROVE": 0,
            "REJECT": 0,
            "MANUAL_REVIEW": 0,
            "reasons": {},
        },
    }

    reason_code_counts: Dict[str, int] = {}
    recommendation_counts = {
        DecisionOutcome.APPROVE.value: 0,
        DecisionOutcome.REJECT.value: 0,
        DecisionOutcome.MANUAL_REVIEW.value: 0,
    }

    complete_evidence_count = 0
    missing_evidence_count = 0
    partial_pipeline_count = 0

    print("=" * 80)
    print("    STAGE 8 — DECISION & REASONING AGENT UNDERWRITING EVALUATION REPORT")
    print("=" * 80)
    print(f"Total Evaluated Applications: {TOTAL_APPLICANTS}")
    print(f"Decision Policy Version:      {decision_agent.agent.policy.policy_version}")
    print("Architecture:                 Deterministic Multi-Agent Evidence Synthesis")
    print(
        "Governance Notice:            AI recommendation only; human underwriter holds final authority"
    )
    print("-" * 80)

    print("\n[PART 1: PER-APPLICANT UNDERWRITING DECISION LEDGER]")
    print("-" * 80)
    print(
        f"{'App ID':<9} {'Eligibility':<12} {'Risk Tier':<12} {'Anomaly':<10} "
        f"{'Recommendation':<15} {'Conf (%)':<10} {'Primary Reason Code'}"
    )
    print("-" * 80)

    for i in range(1, TOTAL_APPLICANTS + 1):
        app_id = f"APP{i:04d}"
        analysis = orchestrator.process(app_id)
        decision = decision_agent.decide(analysis)
        results.append(decision)

        # Track evidence completeness
        has_missing = bool(
            (analysis.document_result and analysis.document_result.documents_missing)
            or (analysis.anomaly_result and analysis.anomaly_result.missing_evidence)
        )
        if has_missing:
            missing_evidence_count += 1
        else:
            complete_evidence_count += 1

        if analysis.orchestration_status.value != "SUCCESS":
            partial_pipeline_count += 1

        # Track aggregates
        rec_val = decision.recommendation.value
        recommendation_counts[rec_val] += 1

        for r in decision.reasons:
            reason_code_counts[r.code] = reason_code_counts.get(r.code, 0) + 1

        # Match cohort
        for cohort_data in cohorts.values():
            if i in cohort_data["range"]:
                cohort_data["total"] += 1
                cohort_data[rec_val] += 1
                for r in decision.reasons:
                    cohort_data["reasons"][r.code] = (
                        cohort_data["reasons"].get(r.code, 0) + 1
                    )
                break

        el_str = (
            analysis.eligibility_result.status.value
            if analysis.eligibility_result
            else "N/A"
        )
        rk_str = (
            analysis.risk_result.risk_category.value if analysis.risk_result else "N/A"
        )
        an_str = (
            analysis.anomaly_result.severity.value if analysis.anomaly_result else "N/A"
        )
        primary_reason = decision.reasons[0].code if decision.reasons else "NONE"

        print(
            f"{app_id:<9} {el_str:<12} {rk_str:<12} {an_str:<10} "
            f"{rec_val:<15} {decision.confidence:<10.1f} {primary_reason}"
        )

    print("-" * 80)

    # Summary Statistics
    total_decisions = len(results)
    manual_review_rate = (
        recommendation_counts[DecisionOutcome.MANUAL_REVIEW.value] / total_decisions
        if total_decisions > 0
        else 0.0
    )

    print("\n[PART 2: AGGREGATE RECOMMENDATION DISTRIBUTION (N=30)]")
    print("-" * 80)
    print(f"{'Recommendation':<20} {'Count':<8} {'Percentage':<14} {'Interpretation'}")
    print("-" * 80)
    for rec_type in [
        DecisionOutcome.APPROVE,
        DecisionOutcome.REJECT,
        DecisionOutcome.MANUAL_REVIEW,
    ]:
        cnt = recommendation_counts[rec_type.value]
        pct = (cnt / total_decisions) * 100.0 if total_decisions > 0 else 0.0
        interp = {
            DecisionOutcome.APPROVE: "Eligible, acceptable risk, complete verified evidence",
            DecisionOutcome.REJECT: "Blocking policy failure (e.g. credit score < 650)",
            DecisionOutcome.MANUAL_REVIEW: "Discrepancy, missing evidence, or borderline risk uncertainty",
        }[rec_type]
        print(f"{rec_type.value:<20} {cnt:<8} {pct:.1f}%{'':<8} {interp}")
    print("-" * 80)
    print(
        f"{'Manual Review Rate':<20} {manual_review_rate * 100:.1f}% (Applications requiring human judgment)"
    )
    print("-" * 80)

    print("\n[PART 3: DECISION REASON CODE FREQUENCY]")
    print("-" * 80)
    print(f"{'Reason Code':<16} {'Count':<8} {'Category':<14} {'Description'}")
    print("-" * 80)
    for code, count in sorted(
        reason_code_counts.items(), key=lambda item: item[1], reverse=True
    ):
        cat = code.split("-")[1] if "-" in code else "GEN"
        desc = next(
            (r.description for res in results for r in res.reasons if r.code == code),
            "",
        )
        truncated_desc = (desc[:45] + "...") if len(desc) > 48 else desc
        print(f"{code:<16} {count:<8} {cat:<14} {truncated_desc}")
    print("-" * 80)

    print("\n[PART 4: EVIDENCE COMPLETENESS AUDIT]")
    print("-" * 80)
    print(
        f"  * Complete verified documentation: {complete_evidence_count} / {total_decisions} ({complete_evidence_count / total_decisions * 100:.1f}%)"
    )
    print(
        f"  * Incomplete / Missing evidence:   {missing_evidence_count} / {total_decisions} ({missing_evidence_count / total_decisions * 100:.1f}%)"
    )
    print(
        f"  * Pipeline partial executions:     {partial_pipeline_count} / {total_decisions} ({partial_pipeline_count / total_decisions * 100:.1f}%)"
    )
    print("-" * 80)

    print("\n[PART 5: COHORT-LEVEL SYNTHESIS BREAKDOWN]")
    print("-" * 80)
    print(
        f"{'Cohort Description':<32} {'Size':<6} {'APPROVE':<9} {'REJECT':<8} {'MANUAL_REV':<12} {'Primary Reasons'}"
    )
    print("-" * 80)
    for c_name, c_data in cohorts.items():
        top_reasons = ", ".join(
            f"{k}({v})" for k, v in list(c_data["reasons"].items())[:2]
        )
        print(
            f"{c_name:<32} {c_data['total']:<6} {c_data['APPROVE']:<9} {c_data['REJECT']:<8} "
            f"{c_data['MANUAL_REVIEW']:<12} {top_reasons}"
        )
    print("-" * 80)

    print("\n[PART 6: SAMPLE DECISION INSPECTIONS]")
    sample_ids = ["APP0001", "APP0002", "APP0006", "APP0011", "APP0016", "APP0026"]
    for sid in sample_ids:
        s_dec = next((r for r in results if r.application_id == sid), None)
        if not s_dec:
            continue
        print(f"\n--- Decision Inspection: {s_dec.application_id} ---")
        print(f"Final Recommendation:   {s_dec.recommendation.value}")
        print(f"Decision Confidence:    {s_dec.confidence:.1f}%")
        print(f"Human Review Required:  {s_dec.human_review_required}")
        print("Primary Reason(s):")
        for r in s_dec.reasons:
            print(f"  * [{r.code}] ({r.category}/{r.severity}): {r.description}")
        if s_dec.blocking_factors:
            print(f"Blocking Factor(s):     {'; '.join(s_dec.blocking_factors)}")
        print(f"Executive Narrative:    {s_dec.summary}")

    print("\n" + "=" * 80)
    print("RESEARCH & METHODOLOGICAL NOTICE:")
    print(
        "1. Decision recommendations are generated deterministically via centralized policy rules."
    )
    print(
        "2. No machine-learning models, LLMs, or cloud APIs were used for final decisioning."
    )
    print(
        "3. Anomaly flags warrant human verification; they are NOT treated as confirmed fraud."
    )
    print(
        "4. This evaluation reports policy behavior on synthetic cohorts; it does not measure real banking defaults."
    )
    print(
        "5. Stage 8 COMPLETE: Final decision engine implemented; Stage 9 dashboard NOT implemented."
    )
    print("=" * 80 + "\n")

    return {
        "total_applications": total_decisions,
        "recommendation_counts": recommendation_counts,
        "manual_review_rate": manual_review_rate,
        "reason_code_counts": reason_code_counts,
        "cohorts": cohorts,
    }


if __name__ == "__main__":
    evaluate_decisions()
