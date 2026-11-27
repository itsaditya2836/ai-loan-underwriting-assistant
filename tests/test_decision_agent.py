"""Automated Unit and Integration Tests for Stage 8 Decision & Reasoning Agent.

Verifies:
1. Basic decision outcomes (APPROVE, REJECT, MANUAL_REVIEW)
2. Combinatorial decision matrix (Eligibility x Risk x Anomaly)
3. Rule precedence hierarchy (Priority 1 through 7)
4. Missing document handling (ensuring missing != fraud)
5. Anomaly handling (ensuring anomaly != confirmed fraud)
6. Pipeline failure resilience (graceful degradation to MANUAL_REVIEW)
7. Determinism across repeated evaluations
8. Reason codes, evidence traceability, and factors extraction
9. End-to-end integration with Stage 7 UnderwritingOrchestrator output
"""

import pytest

from app.agents.decision_agent import DecisionAgent
from app.decision.decision_agent import DecisionReasoningAgent
from app.decision.policy import REASON_CODES
from app.orchestration.orchestrator import UnderwritingOrchestrator
from app.schemas.anomaly import (
    AnomalyFlag,
    AnomalyResult,
    AnomalySeverity,
)
from app.schemas.applicant import (
    ClassifiedDocument,
    DocumentPackageResult,
    EligibilityResult,
    EligibilityRuleResult,
    EligibilityStatus,
    RiskLevel,
    RiskResult,
    RuleStatus,
)
from app.schemas.decision import DecisionOutcome, DecisionReasoningResult
from app.schemas.underwriting import (
    AgentExecutionStatus,
    AgentStatus,
    OrchestrationStatus,
    UnderwritingAnalysisResult,
)

# ==============================================================================
# FIXTURES AND FACTORIES
# ==============================================================================


@pytest.fixture
def decision_agent() -> DecisionReasoningAgent:
    """Fixture providing a DecisionReasoningAgent instance."""
    return DecisionReasoningAgent()


@pytest.fixture
def agent_facade() -> DecisionAgent:
    """Fixture providing the legacy / agents facade instance."""
    return DecisionAgent()


@pytest.fixture
def orchestrator() -> UnderwritingOrchestrator:
    """Fixture providing the Stage 7 UnderwritingOrchestrator."""
    return UnderwritingOrchestrator()


def make_mock_analysis_result(
    application_id: str = "TEST_APP_01",
    eligibility_status: EligibilityStatus = EligibilityStatus.ELIGIBLE,
    risk_category: RiskLevel = RiskLevel.LOW,
    risk_score: float = 20.0,
    anomaly_severity: AnomalySeverity = AnomalySeverity.NONE,
    has_anomalies: bool = False,
    missing_docs: list[str] = None,
    orchestration_status: OrchestrationStatus = OrchestrationStatus.SUCCESS,
    agent_status: AgentStatus = AgentStatus.SUCCESS,
) -> UnderwritingAnalysisResult:
    """Helper factory generating structured Stage 7 analysis results."""
    if missing_docs is None:
        missing_docs = []

    # Real Stage 3 Document Result
    found_docs = [
        ClassifiedDocument(
            document_id=f"{application_id}_{doc_type}",
            file_path=f"data/documents/{application_id}/{doc_type}.pdf",
            document_type=doc_type,
            classification_confidence=0.95,
            classification_evidence=f"Found {doc_type} header",
        )
        for doc_type in ["identity_document", "salary_slip", "bank_statement"]
        if doc_type not in missing_docs
    ]
    mock_doc = DocumentPackageResult(
        applicant_id=application_id,
        package_dir=f"data/documents/{application_id}",
        documents_found=found_docs,
        documents_missing=missing_docs,
        expected_documents=["identity_document", "salary_slip", "bank_statement"],
        is_complete=len(missing_docs) == 0,
        ocr_used=False,
        all_extracted_fields={},
    )

    # Real Stage 4 Eligibility Result
    mock_elig = EligibilityResult(
        applicant_id=application_id,
        status=eligibility_status,
        eligible=(eligibility_status == EligibilityStatus.ELIGIBLE),
        rules_failed=(
            ["MIN_CREDIT_SCORE"]
            if eligibility_status == EligibilityStatus.INELIGIBLE
            else []
        ),
        rules_requiring_review=(
            ["DOCUMENTS_COMPLETE"]
            if eligibility_status == EligibilityStatus.REVIEW_REQUIRED
            else []
        ),
        rule_results=[
            EligibilityRuleResult(
                rule_id="MIN_CREDIT_SCORE",
                rule_name="Minimum Credit Score Threshold",
                status=(
                    RuleStatus.PASS
                    if eligibility_status != EligibilityStatus.INELIGIBLE
                    else RuleStatus.FAIL
                ),
                actual_value=(
                    720 if eligibility_status != EligibilityStatus.INELIGIBLE else 610
                ),
                expected_value=650,
                passed=eligibility_status != EligibilityStatus.INELIGIBLE,
                severity="MANDATORY",
                reason=(
                    "Credit score meets threshold"
                    if eligibility_status != EligibilityStatus.INELIGIBLE
                    else "Credit score 610 below minimum 650"
                ),
                evidence="Credit report score: 720",
            )
        ],
        reasons=(
            ["Credit score below threshold"]
            if eligibility_status == EligibilityStatus.INELIGIBLE
            else []
        ),
        remarks=f"Eligibility status: {eligibility_status.value}",
    )

    # Real Stage 5 Risk Result
    mock_risk = RiskResult(
        applicant_id=application_id,
        risk_category=risk_category,
        risk_score=risk_score,
        protective_factors=["Credit history established"],
        risk_factors=(
            ["Elevated debt ratio"]
            if risk_category in [RiskLevel.HIGH, RiskLevel.BORDERLINE]
            else []
        ),
        method="ML_RANDOM_FOREST",
    )

    # Real Stage 6 Anomaly Result
    mock_anom = AnomalyResult(
        applicant_id=application_id,
        severity=anomaly_severity,
        has_anomalies=has_anomalies,
        anomaly_score=75.0 if has_anomalies else 0.0,
        flags=(
            [
                AnomalyFlag(
                    rule_id="ANOM-INC-001",
                    anomaly_type="INCOME_MISMATCH",
                    severity=anomaly_severity,
                    expected_value="100000",
                    observed_value="60000",
                    description="Declared income does not match bank deposits",
                    source_documents=["salary_slip", "bank_statement"],
                    evidence="Mismatch in recurring credit",
                )
            ]
            if has_anomalies
            else []
        ),
        missing_evidence=[],
    )

    # Agent execution records
    agent_statuses = {
        "DocumentIntakeAgent": AgentExecutionStatus(
            agent_name="DocumentIntakeAgent",
            status=agent_status,
            duration_ms=10.0,
        ),
        "EligibilityAgent": AgentExecutionStatus(
            agent_name="EligibilityAgent",
            status=agent_status,
            duration_ms=12.0,
        ),
        "RiskAgent": AgentExecutionStatus(
            agent_name="RiskAgent",
            status=agent_status,
            duration_ms=8.0,
        ),
        "FraudAnomalyAgent": AgentExecutionStatus(
            agent_name="FraudAnomalyAgent",
            status=agent_status,
            duration_ms=14.0,
        ),
    }

    return UnderwritingAnalysisResult(
        application_id=application_id,
        orchestration_status=orchestration_status,
        agent_statuses=agent_statuses,
        document_result=mock_doc,
        eligibility_result=mock_elig,
        risk_result=mock_risk,
        anomaly_result=mock_anom,
        summary="Test analysis pipeline summary",
        total_duration_ms=44.0,
    )


# ==============================================================================
# BASIC DECISION OUTCOMES
# ==============================================================================


def test_decision_outcome_approve(decision_agent: DecisionReasoningAgent):
    """Test 1: Clean applicant with ELIGIBLE status, LOW risk, no anomalies -> APPROVE."""
    analysis = make_mock_analysis_result(
        eligibility_status=EligibilityStatus.ELIGIBLE,
        risk_category=RiskLevel.LOW,
        anomaly_severity=AnomalySeverity.NONE,
        has_anomalies=False,
    )
    result = decision_agent.evaluate(analysis)

    assert isinstance(result, DecisionReasoningResult)
    assert result.recommendation == DecisionOutcome.APPROVE
    assert result.decision == DecisionOutcome.APPROVE
    assert result.human_review_required is True
    assert result.confidence >= 70.0
    assert any(r.code == "DEC-APP-001" for r in result.reasons)
    assert len(result.positive_factors) > 0
    assert len(result.blocking_factors) == 0


def test_decision_outcome_reject(decision_agent: DecisionReasoningAgent):
    """Test 2: Ineligible applicant fails mandatory rule -> REJECT."""
    analysis = make_mock_analysis_result(
        eligibility_status=EligibilityStatus.INELIGIBLE,
        risk_category=RiskLevel.HIGH,
        anomaly_severity=AnomalySeverity.NONE,
        has_anomalies=False,
    )
    result = decision_agent.evaluate(analysis)

    assert result.recommendation == DecisionOutcome.REJECT
    assert result.decision == DecisionOutcome.REJECT
    assert any(r.code == "DEC-ELIG-001" for r in result.reasons)
    assert len(result.blocking_factors) > 0


def test_decision_outcome_manual_review_for_anomaly(
    decision_agent: DecisionReasoningAgent,
):
    """Test 3: Eligible applicant with high-severity anomaly -> MANUAL_REVIEW."""
    analysis = make_mock_analysis_result(
        eligibility_status=EligibilityStatus.ELIGIBLE,
        risk_category=RiskLevel.LOW,
        anomaly_severity=AnomalySeverity.HIGH,
        has_anomalies=True,
    )
    result = decision_agent.evaluate(analysis)

    assert result.recommendation == DecisionOutcome.MANUAL_REVIEW
    assert result.decision == DecisionOutcome.MANUAL_REVIEW
    assert any(r.code == "DEC-ANOM-001" for r in result.reasons)
    # Anomaly must NOT be called confirmed fraud
    assert (
        "fraud" not in result.reasoning_summary.lower()
        or "not confirmed fraud" in result.reasoning_summary.lower()
    )


# ==============================================================================
# COMBINATORIAL DECISION MATRIX
# ==============================================================================


@pytest.mark.parametrize(
    "elig,risk,anom,has_anom,missing,expected_outcome",
    [
        (
            EligibilityStatus.ELIGIBLE,
            RiskLevel.LOW,
            AnomalySeverity.NONE,
            False,
            [],
            DecisionOutcome.APPROVE,
        ),
        (
            EligibilityStatus.ELIGIBLE,
            RiskLevel.MEDIUM,
            AnomalySeverity.NONE,
            False,
            [],
            DecisionOutcome.APPROVE,
        ),
        (
            EligibilityStatus.ELIGIBLE,
            RiskLevel.BORDERLINE,
            AnomalySeverity.NONE,
            False,
            [],
            DecisionOutcome.MANUAL_REVIEW,
        ),
        (
            EligibilityStatus.ELIGIBLE,
            RiskLevel.HIGH,
            AnomalySeverity.NONE,
            False,
            [],
            DecisionOutcome.REJECT,
        ),
        (
            EligibilityStatus.ELIGIBLE,
            RiskLevel.LOW,
            AnomalySeverity.HIGH,
            True,
            [],
            DecisionOutcome.MANUAL_REVIEW,
        ),
        (
            EligibilityStatus.ELIGIBLE,
            RiskLevel.MEDIUM,
            AnomalySeverity.MEDIUM,
            True,
            [],
            DecisionOutcome.MANUAL_REVIEW,
        ),
        (
            EligibilityStatus.REVIEW_REQUIRED,
            RiskLevel.LOW,
            AnomalySeverity.NONE,
            False,
            [],
            DecisionOutcome.MANUAL_REVIEW,
        ),
        (
            EligibilityStatus.INELIGIBLE,
            RiskLevel.LOW,
            AnomalySeverity.NONE,
            False,
            [],
            DecisionOutcome.REJECT,
        ),
        (
            EligibilityStatus.INELIGIBLE,
            RiskLevel.HIGH,
            AnomalySeverity.HIGH,
            True,
            [],
            DecisionOutcome.REJECT,
        ),
        (
            EligibilityStatus.ELIGIBLE,
            RiskLevel.LOW,
            AnomalySeverity.NONE,
            False,
            ["bank_statement"],
            DecisionOutcome.MANUAL_REVIEW,
        ),
    ],
)
def test_decision_matrix_combinations(
    decision_agent: DecisionReasoningAgent,
    elig: EligibilityStatus,
    risk: RiskLevel,
    anom: AnomalySeverity,
    has_anom: bool,
    missing: list[str],
    expected_outcome: DecisionOutcome,
):
    """Test 4: Verify complete combinatorial underwriting decision matrix."""
    analysis = make_mock_analysis_result(
        eligibility_status=elig,
        risk_category=risk,
        anomaly_severity=anom,
        has_anomalies=has_anom,
        missing_docs=missing,
    )
    result = decision_agent.evaluate(analysis)
    assert result.recommendation == expected_outcome


# ==============================================================================
# RULE PRECEDENCE AND PIPELINE RESILIENCE
# ==============================================================================


def test_rule_precedence_pipeline_failure(decision_agent: DecisionReasoningAgent):
    """Priority 1: Failed pipeline execution forces MANUAL_REVIEW."""
    analysis = make_mock_analysis_result(
        orchestration_status=OrchestrationStatus.FAILED,
        agent_status=AgentStatus.FAILED,
    )
    result = decision_agent.evaluate(analysis)

    assert result.recommendation == DecisionOutcome.MANUAL_REVIEW
    assert any(r.code == "DEC-SYS-001" for r in result.reasons)
    assert result.confidence <= 40.0


def test_rule_precedence_ineligible_over_anomaly(
    decision_agent: DecisionReasoningAgent,
):
    """Priority 2: Hard ineligibility produces deterministic REJECT even if anomaly is present."""
    analysis = make_mock_analysis_result(
        eligibility_status=EligibilityStatus.INELIGIBLE,
        risk_category=RiskLevel.HIGH,
        anomaly_severity=AnomalySeverity.HIGH,
        has_anomalies=True,
    )
    result = decision_agent.evaluate(analysis)

    assert result.recommendation == DecisionOutcome.REJECT
    assert any(r.code == "DEC-ELIG-001" for r in result.reasons)


def test_missing_documents_triggers_manual_review_not_fraud(
    decision_agent: DecisionReasoningAgent,
):
    """Missing document must trigger MANUAL_REVIEW and NOT be flagged as fraud."""
    analysis = make_mock_analysis_result(
        eligibility_status=EligibilityStatus.ELIGIBLE,
        risk_category=RiskLevel.LOW,
        anomaly_severity=AnomalySeverity.NONE,
        has_anomalies=False,
        missing_docs=["bank_statement", "identity_document"],
    )
    result = decision_agent.evaluate(analysis)

    assert result.recommendation == DecisionOutcome.MANUAL_REVIEW
    assert any(r.code == "DEC-DOC-001" for r in result.reasons)
    # Check that missing document is recorded in blocking factors
    assert any("missing" in b.lower() for b in result.blocking_factors)
    # Confidence is penalized for incomplete documents
    assert result.confidence <= 80.0


# ==============================================================================
# REASON CODES, FACTORS, AND TRACEABILITY
# ==============================================================================


def test_reason_codes_and_traceability(decision_agent: DecisionReasoningAgent):
    """Verify that every generated reason has valid metadata and source agent."""
    analysis = make_mock_analysis_result(
        eligibility_status=EligibilityStatus.ELIGIBLE,
        risk_category=RiskLevel.MEDIUM,
        anomaly_severity=AnomalySeverity.NONE,
        has_anomalies=False,
    )
    result = decision_agent.evaluate(analysis)

    assert len(result.reasons) > 0
    for reason in result.reasons:
        assert reason.code in REASON_CODES
        assert reason.source_agent in [
            "OrchestratorAgent",
            "DocumentIntakeAgent",
            "EligibilityAgent",
            "RiskAgent",
            "FraudAnomalyAgent",
            "DecisionAgent",
            "DecisionReasoningAgent",
        ]
        assert reason.severity in ["INFO", "WARNING", "BLOCKING"]
        assert len(reason.description) > 0


def test_factor_categorization(decision_agent: DecisionReasoningAgent):
    """Verify positive, negative, and blocking factor extraction."""
    analysis = make_mock_analysis_result(
        eligibility_status=EligibilityStatus.ELIGIBLE,
        risk_category=RiskLevel.BORDERLINE,
        anomaly_severity=AnomalySeverity.NONE,
        has_anomalies=False,
    )
    result = decision_agent.evaluate(analysis)

    assert result.recommendation == DecisionOutcome.MANUAL_REVIEW
    assert len(result.positive_factors) > 0  # e.g., ELIGIBLE, documents present
    assert len(result.blocking_factors) > 0  # BORDERLINE risk blocks auto approval
    assert any("borderline" in f.lower() for f in result.blocking_factors)


# ==============================================================================
# DECISION DETERMINISM
# ==============================================================================


def test_decision_determinism(decision_agent: DecisionReasoningAgent):
    """Verify that DecisionResult(A) == DecisionResult(A) identically across runs."""
    analysis = make_mock_analysis_result(
        application_id="APP_DETERMINISTIC",
        eligibility_status=EligibilityStatus.ELIGIBLE,
        risk_category=RiskLevel.LOW,
        anomaly_severity=AnomalySeverity.NONE,
        has_anomalies=False,
    )

    run_1 = decision_agent.evaluate(analysis)
    run_2 = decision_agent.evaluate(analysis)

    assert run_1.recommendation == run_2.recommendation
    assert run_1.decision == run_2.decision
    assert run_1.confidence == run_2.confidence
    assert run_1.reasons == run_2.reasons
    assert run_1.positive_factors == run_2.positive_factors
    assert run_1.negative_factors == run_2.negative_factors
    assert run_1.blocking_factors == run_2.blocking_factors
    assert run_1.reasoning_summary == run_2.reasoning_summary


# ==============================================================================
# END-TO-END INTEGRATION WITH SYNTHETIC COHORTS
# ==============================================================================


@pytest.mark.parametrize(
    "app_id,expected_outcome",
    [
        ("APP0001", DecisionOutcome.REJECT),  # Credit score < 650 (INELIGIBLE)
        ("APP0002", DecisionOutcome.APPROVE),  # ELIGIBLE, MEDIUM risk, clean docs
        ("APP0003", DecisionOutcome.APPROVE),  # ELIGIBLE, LOW risk, clean docs
        ("APP0006", DecisionOutcome.MANUAL_REVIEW),  # Income discrepancy anomaly
        ("APP0011", DecisionOutcome.MANUAL_REVIEW),  # Name mismatch anomaly
        ("APP0016", DecisionOutcome.MANUAL_REVIEW),  # Missing bank statement document
        ("APP0026", DecisionOutcome.MANUAL_REVIEW),  # Borderline risk profile
    ],
)
def test_decision_agent_integration_cohorts(
    orchestrator: UnderwritingOrchestrator,
    decision_agent: DecisionReasoningAgent,
    app_id: str,
    expected_outcome: DecisionOutcome,
):
    """End-to-end integration test with live Stage 7 pipeline on actual synthetic cohorts."""
    analysis = orchestrator.process(app_id)
    decision = decision_agent.evaluate(analysis)

    assert decision.application_id == app_id
    assert decision.recommendation == expected_outcome
    assert decision.human_review_required is True
    assert decision.policy_version == "decision_policy_v1"
    assert decision.reasoning_version == "reasoning_v1"
    assert len(decision.reasons) > 0
    assert len(decision.reasoning_summary) > 20


def test_agent_facade_compatibility(
    orchestrator: UnderwritingOrchestrator, agent_facade: DecisionAgent
):
    """Verify that the app.agents.decision_agent facade processes both analysis and applicant_id."""
    analysis = orchestrator.process("APP0002")
    decision = agent_facade.process(analysis)

    assert isinstance(decision, DecisionReasoningResult)
    assert decision.recommendation == DecisionOutcome.APPROVE

    # Also test passing applicant_id string directly
    decision_from_id = agent_facade.process("APP0002")
    assert decision_from_id.recommendation == DecisionOutcome.APPROVE


# ==============================================================================
# STAGE 4: FAIL-CLOSED SAFETY, CROSS-AGENT CONSISTENCY & EXPLAINABILITY TESTS
# ==============================================================================


def test_approval_blocked_when_fraud_agent_failed_or_missing(
    decision_agent: DecisionReasoningAgent,
):
    """Failed or missing FraudAnomalyAgent must strictly block auto-approval."""
    analysis = make_mock_analysis_result(
        eligibility_status=EligibilityStatus.ELIGIBLE,
        risk_category=RiskLevel.LOW,
        risk_score=15.0,
    )
    analysis.anomaly_result = None
    analysis.agent_statuses["FraudAnomalyAgent"].status = AgentStatus.FAILED
    analysis.agent_statuses["FraudAnomalyAgent"].success = False
    analysis.agent_statuses["FraudAnomalyAgent"].output_available = False

    decision = decision_agent.evaluate(analysis)
    assert decision.recommendation == DecisionOutcome.MANUAL_REVIEW
    assert decision.recommendation != DecisionOutcome.APPROVE
    assert decision.human_review_required is True
    assert decision.fraud_status == "UNAVAILABLE"
    assert "DEC-FRAUD-001" in [r.code for r in decision.reasons]
    assert decision.review_reasons


def test_approval_blocked_when_risk_agent_failed_missing_or_nan(
    decision_agent: DecisionReasoningAgent,
):
    """Missing, failed, or NaN risk_score must block auto-approval and mark risk UNAVAILABLE."""
    # Case A: risk_result is None & RiskAgent FAILED
    analysis_missing = make_mock_analysis_result(
        eligibility_status=EligibilityStatus.ELIGIBLE,
        anomaly_severity=AnomalySeverity.NONE,
    )
    analysis_missing.risk_result = None
    analysis_missing.agent_statuses["RiskAgent"].status = AgentStatus.FAILED
    analysis_missing.agent_statuses["RiskAgent"].success = False
    analysis_missing.agent_statuses["RiskAgent"].output_available = False

    dec_missing = decision_agent.evaluate(analysis_missing)
    assert dec_missing.recommendation == DecisionOutcome.MANUAL_REVIEW
    assert dec_missing.risk_score is None
    assert dec_missing.risk_category == "UNAVAILABLE"
    assert "DEC-RISK-004" in [r.code for r in dec_missing.reasons]

    # Case B: Corrupt NaN risk_score
    analysis_nan = make_mock_analysis_result(
        eligibility_status=EligibilityStatus.ELIGIBLE,
        risk_category=RiskLevel.LOW,
        risk_score=18.0,
    )
    analysis_nan.risk_result.risk_score = float("nan")
    dec_nan = decision_agent.evaluate(analysis_nan)
    assert dec_nan.recommendation == DecisionOutcome.MANUAL_REVIEW
    assert dec_nan.risk_score is None
    assert "DEC-RISK-004" in [r.code for r in dec_nan.reasons]


def test_approval_blocked_when_eligibility_agent_failed_or_missing(
    decision_agent: DecisionReasoningAgent,
):
    """Missing or failed EligibilityAgent must route to MANUAL_REVIEW, never APPROVE or REJECT."""
    analysis = make_mock_analysis_result(
        risk_category=RiskLevel.LOW,
        risk_score=18.0,
        anomaly_severity=AnomalySeverity.NONE,
    )
    analysis.eligibility_result = None
    analysis.agent_statuses["EligibilityAgent"].status = AgentStatus.FAILED
    analysis.agent_statuses["EligibilityAgent"].success = False
    analysis.agent_statuses["EligibilityAgent"].output_available = False

    decision = decision_agent.evaluate(analysis)
    assert decision.recommendation == DecisionOutcome.MANUAL_REVIEW
    assert decision.eligibility_status == "UNAVAILABLE"
    assert "DEC-ELIG-004" in [r.code for r in decision.reasons]


def test_policy_supported_rejection_safeguard(
    decision_agent: DecisionReasoningAgent,
):
    """INELIGIBLE status without any supporting failed rules or reasons must NOT auto-REJECT."""
    analysis = make_mock_analysis_result(
        eligibility_status=EligibilityStatus.INELIGIBLE,
        risk_category=RiskLevel.MEDIUM,
        risk_score=40.0,
    )
    analysis.eligibility_result.rules_failed = []
    analysis.eligibility_result.rule_results = []
    analysis.eligibility_result.reasons = []

    decision = decision_agent.evaluate(analysis)
    assert decision.recommendation == DecisionOutcome.MANUAL_REVIEW
    assert "DEC-ELIG-004" in [r.code for r in decision.reasons]


def test_approval_blocked_on_ambiguous_invalid_or_conflicting_documents(
    decision_agent: DecisionReasoningAgent,
):
    """Invalid fields, ambiguous fields, field conflicts, or unclassified docs block approval."""
    for bad_attr in (
        "invalid_fields",
        "ambiguous_fields",
        "field_conflicts",
        "unclassified_documents",
    ):
        analysis = make_mock_analysis_result(
            eligibility_status=EligibilityStatus.ELIGIBLE,
            risk_category=RiskLevel.LOW,
            risk_score=20.0,
            anomaly_severity=AnomalySeverity.NONE,
        )
        if bad_attr == "unclassified_documents":
            analysis.document_result.unclassified_documents = ["unknown_scan.pdf"]
        else:
            setattr(
                analysis.document_result,
                bad_attr,
                {"monthly_income": [{"reason": f"simulated {bad_attr}"}]},
            )

        decision = decision_agent.evaluate(analysis)
        assert decision.recommendation == DecisionOutcome.MANUAL_REVIEW, bad_attr
        assert "DEC-DOC-001" in [r.code for r in decision.reasons], bad_attr
        assert decision.document_verification_status != "VERIFIED"


def test_cross_agent_consistency_conflicts_and_structured_explainability(
    decision_agent: DecisionReasoningAgent,
    orchestrator: UnderwritingOrchestrator,
):
    """Verify cross-agent conflicts route to MANUAL_REVIEW and DecisionReasoningResult exposes structured fields."""
    from app.orchestration.consistency import check_cross_agent_consistency
    from app.schemas.applicant import Applicant, EligibilityRuleResult, ExtractedField

    # 1. CONFLICT-INCOME-MISMATCH: Applicant profile vs Document extracted income
    analysis_inc = make_mock_analysis_result(
        application_id="APP_CON_01",
        eligibility_status=EligibilityStatus.ELIGIBLE,
        risk_category=RiskLevel.LOW,
        risk_score=20.0,
    )
    analysis_inc.document_result.all_extracted_fields = {
        "declared_monthly_income": ExtractedField(
            field_name="declared_monthly_income",
            value="40000",
            confidence=0.95,
            source_document="application_form",
            validation_status="valid",
            evidence="Application form declared monthly income: INR 40,000",
        )
    }
    applicant_inc = Applicant(
        applicant_id="APP_CON_01",
        name="Conflict Applicant",
        age=32,
        employment_type="salaried",
        employment_years=5.0,
        monthly_income=100000.0,
        existing_emi=0.0,
        loan_amount=200000.0,
        loan_tenure=24,
        credit_score=750,
        bank_balance=100000.0,
    )
    _, conflicts_inc = check_cross_agent_consistency(analysis_inc, applicant_inc)
    assert any(
        c["conflict_id"] == "CONFLICT-INCOME-MISMATCH" and c["severity"] == "BLOCKING"
        for c in conflicts_inc
    )
    analysis_inc.consistency_conflicts = conflicts_inc
    analysis_inc.has_unresolved_conflicts = True
    dec_inc = decision_agent.evaluate(analysis_inc)
    assert dec_inc.recommendation == DecisionOutcome.MANUAL_REVIEW
    assert "DEC-CON-001" in [r.code for r in dec_inc.reasons]

    # 2. CONFLICT-CREDIT-SCORE: Eligibility vs RiskAgent credit_score disagreement
    analysis_cs = make_mock_analysis_result(application_id="APP_CON_02")
    analysis_cs.eligibility_result.rule_results = [
        EligibilityRuleResult(
            rule_id="MIN_CREDIT_SCORE",
            rule_name="Minimum Credit Score",
            status="PASS",
            passed=True,
            severity="MANDATORY",
            actual_value=740,
            expected_value=">= 650",
            reason="Credit score meets minimum threshold",
        )
    ]
    analysis_cs.risk_result.features_used = {"credit_score": 590}
    _, conflicts_cs = check_cross_agent_consistency(analysis_cs)
    assert any(c["conflict_id"] == "CONFLICT-CREDIT-SCORE" for c in conflicts_cs)

    # 3. CONFLICT-ELIG-DOC & CONFLICT-ID-MISMATCH
    analysis_id = make_mock_analysis_result(
        application_id="APP_CON_03", missing_docs=["bank_statement"]
    )
    analysis_id.risk_result.applicant_id = "DIFFERENT_APP"
    _, conflicts_id = check_cross_agent_consistency(analysis_id)
    ids_found = {c["conflict_id"] for c in conflicts_id}
    assert "CONFLICT-ELIG-DOC" in ids_found
    assert "CONFLICT-ID-MISMATCH" in ids_found

    # 4. End-to-end explainability schema completeness on APP0006
    real_analysis = orchestrator.process("APP0006")
    real_decision = decision_agent.evaluate(real_analysis)
    assert real_decision.eligibility_status == "ELIGIBLE"
    assert real_decision.risk_category in ("LOW", "MEDIUM", "BORDERLINE", "HIGH")
    assert isinstance(real_decision.risk_score, float)
    assert real_decision.fraud_status == "MEDIUM"
    assert real_decision.document_verification_status == "VERIFIED"
    assert isinstance(real_decision.missing_documents, list)
    assert isinstance(real_decision.validation_warnings, list)
    assert len(real_decision.material_anomalies) >= 1
    assert len(real_decision.review_reasons) >= 1
    assert isinstance(real_decision.agent_statuses, dict)
    assert isinstance(real_decision.consistency_conflicts, list)
