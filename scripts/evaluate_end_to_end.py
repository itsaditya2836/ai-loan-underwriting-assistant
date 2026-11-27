"""End-to-End Stage 4 Underwriting Pipeline & Decision Reliability Evaluator.

Evaluates:
1. Full Steps 1-7 pipeline execution (`execute_end_to_end`) across all 30 physical
   document packages (`APP0001`–`APP0030`) using an isolated temporary SQLite audit DB.
2. Profile-only baseline summary across `APP0031`–`APP0100` (70 synthetic records without
   physical PDF directories, verifying graceful incomplete-document handling).
3. Repeat-run determinism across all 30 document-backed cohorts.
4. Simulated agent failure & cross-agent conflict safety checks (zero unsafe approvals).
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock

# Ensure repository root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.audit import (  # noqa: E402
    get_audit_analytics_summary,
    get_audit_run_by_id,
)
from app.decision.decision_agent import DecisionReasoningAgent  # noqa: E402
from app.orchestration.consistency import check_cross_agent_consistency  # noqa: E402
from app.orchestration.orchestrator import UnderwritingOrchestrator  # noqa: E402
from app.risk.risk_model import RiskModelLoadError  # noqa: E402
from app.schemas.applicant import RiskLevel, RiskResult  # noqa: E402
from app.schemas.decision import DecisionOutcome  # noqa: E402
from app.schemas.underwriting import AgentStatus  # noqa: E402
from config.settings import get_settings  # noqa: E402


def _deterministic_snapshot(
    orchestrator: UnderwritingOrchestrator,
    dec_agent: DecisionReasoningAgent,
    app_id: str,
) -> str:
    """Capture timestamp-independent canonical JSON snapshot of an end-to-end run."""
    analysis, decision = orchestrator.execute_end_to_end(
        app_id, decision_agent=dec_agent, persist_audit=False
    )
    payload = {
        "orchestration_status": analysis.orchestration_status.value,
        "eligibility": (
            {
                "status": analysis.eligibility_result.status.value,
                "rules_passed": analysis.eligibility_result.rules_passed,
                "rules_failed": analysis.eligibility_result.rules_failed,
                "rules_requiring_review": analysis.eligibility_result.rules_requiring_review,
            }
            if analysis.eligibility_result
            else None
        ),
        "risk": (
            {
                "category": analysis.risk_result.risk_category.value,
                "score": analysis.risk_result.risk_score,
            }
            if analysis.risk_result
            else None
        ),
        "anomaly": (
            {
                "severity": analysis.anomaly_result.severity.value,
                "score": analysis.anomaly_result.anomaly_score,
                "flags": [f.rule_id for f in analysis.anomaly_result.flags],
            }
            if analysis.anomaly_result
            else None
        ),
        "consistency_conflicts": analysis.consistency_conflicts,
        "recommendation": decision.recommendation.value,
        "confidence": decision.confidence,
        "reason_codes": [r.code for r in decision.reasons],
        "review_reasons": decision.review_reasons,
        "material_anomalies": decision.material_anomalies,
    }
    return json.dumps(payload, sort_keys=True)


def run_safety_probes(dec_agent: DecisionReasoningAgent) -> list[dict]:
    """Run controlled failure & conflict probes verifying zero unsafe approvals."""
    probes = []

    # Probe 1: RiskModelLoadError -> MANUAL_REVIEW + UNAVAILABLE risk
    mock_risk_err = MagicMock()
    mock_risk_err.assess.side_effect = RiskModelLoadError("Simulated model load error")
    orch_err = UnderwritingOrchestrator(risk_agent=mock_risk_err)
    a1, d1 = orch_err.execute_end_to_end(
        "APP0002", decision_agent=dec_agent, persist_audit=True
    )
    row1 = get_audit_run_by_id(a1.audit_run_id) if a1.audit_run_id else None
    probes.append(
        {
            "probe": "RiskModelLoadError",
            "safe": (
                d1.recommendation == DecisionOutcome.MANUAL_REVIEW
                and d1.risk_score is None
                and d1.risk_category == "UNAVAILABLE"
                and row1 is not None
                and row1["risk_score"] is None
                and row1["risk_score_available"] in (0, False)
            ),
            "recommendation": d1.recommendation.value,
            "reason_codes": [r.code for r in d1.reasons],
        }
    )

    # Probe 2: FraudAnomalyAgent exception -> MANUAL_REVIEW (no auto-approve)
    mock_fraud_err = MagicMock()
    mock_fraud_err.detect.side_effect = RuntimeError("Simulated detector crash")
    orch_fraud = UnderwritingOrchestrator(fraud_agent=mock_fraud_err)
    _, d2 = orch_fraud.execute_end_to_end(
        "APP0002", decision_agent=dec_agent, persist_audit=False
    )
    probes.append(
        {
            "probe": "FraudAnomalyAgentException",
            "safe": (
                d2.recommendation == DecisionOutcome.MANUAL_REVIEW
                and "DEC-FRAUD-001" in [r.code for r in d2.reasons]
            ),
            "recommendation": d2.recommendation.value,
            "reason_codes": [r.code for r in d2.reasons],
        }
    )

    # Probe 3: NaN RiskScore + EligibilityAgent credit-score contradiction -> MANUAL_REVIEW
    mock_risk_nan = MagicMock()
    mock_risk_nan.assess.return_value = RiskResult.model_construct(
        applicant_id="APP0002",
        risk_score=float("nan"),
        risk_category=RiskLevel.LOW,
        risk_level="LOW",
        risk_factors=[],
        protective_factors=[],
        features_used={"credit_score": 500},
        feature_importance={},
        model_version="probe",
        method="ML_RANDOM_FOREST",
    )
    orch_nan = UnderwritingOrchestrator(risk_agent=mock_risk_nan)
    a3, d3 = orch_nan.execute_end_to_end(
        "APP0002", decision_agent=dec_agent, persist_audit=False
    )
    probes.append(
        {
            "probe": "NaNRiskScoreRejection",
            "safe": (
                a3.risk_result is None
                and d3.recommendation == DecisionOutcome.MANUAL_REVIEW
                and "DEC-RISK-004" in [r.code for r in d3.reasons]
            ),
            "recommendation": d3.recommendation.value,
            "reason_codes": [r.code for r in d3.reasons],
        }
    )

    # Probe 4: Cross-agent credit score contradiction without agent crash
    clean_orch = UnderwritingOrchestrator()
    a4 = clean_orch.process("APP0002")
    a4.risk_result.features_used["credit_score"] = 580
    _, conflicts = check_cross_agent_consistency(a4)
    a4.consistency_conflicts = conflicts
    a4.has_unresolved_conflicts = any(c["severity"] == "BLOCKING" for c in conflicts)
    d4 = dec_agent.evaluate(a4)
    probes.append(
        {
            "probe": "CrossAgentCreditScoreConflict",
            "safe": (
                any(c["conflict_id"] == "CONFLICT-CREDIT-SCORE" for c in conflicts)
                and d4.recommendation == DecisionOutcome.MANUAL_REVIEW
                and "DEC-CON-001" in [r.code for r in d4.reasons]
            ),
            "recommendation": d4.recommendation.value,
            "reason_codes": [r.code for r in d4.reasons],
        }
    )

    return probes


def main() -> int:
    print("=" * 84)
    print("STAGE 4 END-TO-END UNDERWRITING PIPELINE & DECISION RELIABILITY REPORT")
    print("=" * 84)

    orchestrator = UnderwritingOrchestrator()
    decision_agent = DecisionReasoningAgent()
    cohorts_30 = [f"APP{i:04d}" for i in range(1, 31)]

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_db = Path(tmp_dir) / "stage4_eval_audit.db"
        old_db_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db}"
        get_settings.cache_clear()

        try:
            pipeline_statuses = Counter()
            agent_success_counts = Counter()
            recommendations = Counter()
            reason_codes = Counter()
            latencies_ms = []
            review_required_count = 0
            incomplete_evidence_count = 0
            conflict_run_count = 0
            persisted_count = 0
            determinism_matches = 0

            print("\n[1] Document-Backed Cohort Evaluation (APP0001 - APP0030, N=30)")
            print("-" * 84)
            print(
                f"{'App ID':<8} {'Pipeline':<10} {'Elig':<14} {'Risk(Score)':<16} "
                f"{'Fraud':<8} {'Decision':<14} {'Conf':<6} {'Conflicts'}"
            )
            print("-" * 84)

            for app_id in cohorts_30:
                analysis, decision = orchestrator.execute_end_to_end(
                    app_id, decision_agent=decision_agent, persist_audit=True
                )
                pipeline_statuses[analysis.orchestration_status.value] += 1
                recommendations[decision.recommendation.value] += 1
                if decision.human_review_required:
                    review_required_count += 1
                if analysis.total_duration_ms is not None:
                    latencies_ms.append(float(analysis.total_duration_ms))
                if analysis.audit_persisted:
                    persisted_count += 1
                if analysis.consistency_conflicts:
                    conflict_run_count += 1
                if (
                    analysis.document_result is None
                    or not analysis.document_result.is_complete
                ):
                    incomplete_evidence_count += 1

                for ag_name in (
                    "document_agent",
                    "eligibility_agent",
                    "anomaly_agent",
                    "risk_agent",
                ):
                    st = analysis.agent_statuses.get(ag_name)
                    if st and st.status == AgentStatus.SUCCESS:
                        agent_success_counts[ag_name] += 1

                for r in decision.reasons:
                    reason_codes[r.code] += 1

                snap1 = _deterministic_snapshot(orchestrator, decision_agent, app_id)
                snap2 = _deterministic_snapshot(orchestrator, decision_agent, app_id)
                if snap1 == snap2:
                    determinism_matches += 1

                risk_str = (
                    f"{decision.risk_category}({decision.risk_score:.1f})"
                    if decision.risk_score is not None
                    else decision.risk_category
                )
                conflict_str = (
                    ",".join(c["conflict_id"] for c in analysis.consistency_conflicts)
                    or "None"
                )
                print(
                    f"{app_id:<8} {analysis.orchestration_status.value:<10} "
                    f"{decision.eligibility_status:<14} {risk_str:<16} "
                    f"{decision.fraud_status:<8} {decision.recommendation.value:<14} "
                    f"{decision.confidence:<6.1f} {conflict_str}"
                )

            print("-" * 84)
            print(f"Document Cohorts Pipeline Status : {dict(pipeline_statuses)}")
            print(f"Per-Agent Success Rates (N=30)   : {dict(agent_success_counts)}")
            print(f"Decision Distribution (N=30)     : {dict(recommendations)}")
            print(f"Audit Persistence Success (N=30) : {persisted_count}/30")
            print(
                f"Repeat-Run Determinism (N=30)    : {determinism_matches}/30 identical"
            )
            print(f"Human Review Required            : {review_required_count}/30")
            print(f"Incomplete Document Evidence     : {incomplete_evidence_count}/30")
            print(f"Runs With Consistency Conflicts  : {conflict_run_count}/30")
            print(
                f"Decision Reason Counts           : {dict(sorted(reason_codes.items()))}"
            )
            if latencies_ms:
                print(
                    f"Latency (ms)                     : avg={statistics.mean(latencies_ms):.2f}, "
                    f"max={max(latencies_ms):.2f}"
                )

            # Part 2: Remaining 70 synthetic records without physical PDF dirs (APP0031-APP0100)
            profile_only_recs = Counter()
            for idx in range(31, 101):
                app_id = f"APP{idx:04d}"
                a_prof, d_prof = orchestrator.execute_end_to_end(
                    app_id, decision_agent=decision_agent, persist_audit=False
                )
                profile_only_recs[d_prof.recommendation.value] += 1
                assert (
                    d_prof.recommendation != DecisionOutcome.APPROVE
                ), f"Profile-only {app_id} should not auto-APPROVE without physical documents!"
            print(
                f"\n[2] Profile-Only Synthetic Records (APP0031-APP0100, N=70, No PDFs): "
                f"{dict(profile_only_recs)} (0 unsafe auto-approvals)"
            )

            # Part 3: Fault & Conflict Safety Probes (also exercises FAILED audit persistence)
            probes = run_safety_probes(decision_agent)
            print("\n[3] Simulated Failure & Conflict Safety Probes:")
            for p in probes:
                print(
                    f"  - {p['probe']:<32} safe={p['safe']} rec={p['recommendation']} codes={p['reason_codes']}"
                )
                assert p["safe"], f"Safety probe failed: {p}"

            audit_summary = get_audit_analytics_summary()
            print(
                "\n[4] Isolated SQLite Audit Summary (30 Cohort Runs + 1 Partial Failure Probe):"
            )
            print(f"  - Total Persisted Runs        : {audit_summary['total_runs']}")
            print(
                f"  - Pipeline Status Distribution: {audit_summary['pipeline_status_distribution']}"
            )
            print(
                f"  - Failed Runs Recorded        : {audit_summary['failed_runs_count']}"
            )

            print("\n[5] Dataset & Pipeline Scope Note:")
            print(
                "  - Only APP0001-APP0030 have physical synthetic PDF packages; APP0031-APP0100\n"
                "    are profile-only CSV/JSON records where incomplete documentation cleanly\n"
                "    routes qualifying profiles to MANUAL_REVIEW and fails closed on auto-approve."
            )
            print("=" * 84)
        finally:
            if old_db_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old_db_url
            get_settings.cache_clear()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
