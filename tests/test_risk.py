"""Tests for Risk Assessment Agent, ML Model, Rules Engine, and Scoring.

Verifies:
- RiskResult schema validation, field defaults, and legacy syncing
- Financial feature engineering and amortization calculations
- Deterministic explainable factor extraction (adverse and protective)
- Baseline weighted risk scoring
- ML model inference, feature importances, and reproducibility
- RiskAgent evaluation with structured Applicant and Stage 3 DocumentPackageResult
- Explicit absence of loan approval decisions or fraud labeling
"""

import os

import pytest

from app.agents.document_agent import DocumentIntakeAgent
from app.agents.risk_agent import RiskAgent
from app.risk.features import (
    RISK_FEATURE_NAMES,
    calculate_emi,
    extract_features,
)
from app.risk.risk_model import MLRiskModel
from app.risk.rules import RiskRulesEngine
from app.risk.scoring import RiskScorer
from app.schemas.applicant import (
    Applicant,
    DocumentPackageResult,
    ExtractedField,
    RiskLevel,
    RiskResult,
)


@pytest.fixture
def sample_applicant() -> Applicant:
    """Fixture providing a standard valid Applicant instance."""
    return Applicant(
        applicant_id="app_002",
        name="Jordan Lee",
        age=28,
        employment_type="Self-Employed",
        employment_years=3.0,
        monthly_income=90000.0,
        existing_emi=20000.0,
        loan_amount=1000000.0,
        loan_tenure=60,
        credit_score=780,
        bank_balance=250000.0,
    )


@pytest.fixture
def high_risk_applicant() -> Applicant:
    """Applicant with adverse financial indicators."""
    return Applicant(
        applicant_id="app_high",
        name="High Risk User",
        age=24,
        employment_type="Salaried",
        employment_years=1.0,
        monthly_income=35000.0,
        existing_emi=18000.0,
        loan_amount=1500000.0,
        loan_tenure=36,
        credit_score=570,
        bank_balance=15000.0,
    )


# ---------------------------------------------------------------------------
# Schema and Data Contract Tests
# ---------------------------------------------------------------------------


def test_risk_result_schema():
    """Verify RiskResult schema instantiation, defaults, and legacy field sync."""
    result = RiskResult(
        risk_score=24.5,
        risk_level=RiskLevel.LOW,
        risk_factors=["Self-employed profile"],
        model_version="rule_v1",
        remarks="Low probability of default.",
    )
    assert result.risk_score == 24.5
    assert result.risk_level == RiskLevel.LOW
    assert result.risk_category == RiskLevel.LOW
    assert len(result.risk_factors) == 1
    assert result.explanation == "Low probability of default."
    assert result.remarks == "Low probability of default."


def test_risk_level_enum():
    """Verify RiskLevel contains all 4 tiers including BORDERLINE."""
    assert RiskLevel.LOW.value == "LOW"
    assert RiskLevel.MEDIUM.value == "MEDIUM"
    assert RiskLevel.HIGH.value == "HIGH"
    assert RiskLevel.BORDERLINE.value == "BORDERLINE"


# ---------------------------------------------------------------------------
# Feature Engineering and EMI Tests
# ---------------------------------------------------------------------------


def test_calculate_emi_standard():
    """Verify standard monthly amortization formula against known values."""
    # 500,000 INR at 10.5% p.a. for 60 months
    # r = 0.105 / 12 = 0.00875
    # EMI should be approx 10,746.95 INR
    emi = calculate_emi(500000.0, annual_rate=0.105, tenure_months=60)
    assert 10740.0 < emi < 10755.0

    # Zero principal or tenure
    assert calculate_emi(0.0, 0.105, 60) == 0.0
    assert calculate_emi(500000.0, 0.105, 0) == 0.0


def test_extract_features_from_applicant(sample_applicant: Applicant):
    """Verify feature vector extraction and derived ratio computation."""
    feats = extract_features(sample_applicant)

    assert set(RISK_FEATURE_NAMES).issubset(set(feats.keys()))
    assert feats["credit_score"] == 780.0
    assert feats["monthly_income"] == 90000.0
    assert feats["existing_emi"] == 20000.0
    assert feats["loan_amount"] == 1000000.0
    assert feats["dti_ratio"] > 0.0
    assert feats["loan_to_income_ratio"] > 0.0
    assert feats["is_salaried"] == 0.0  # Self-employed


def test_extract_features_from_document_package():
    """Verify feature extraction from Stage 3 DocumentPackageResult."""
    package = DocumentPackageResult(
        applicant_id="APP_TEST",
        package_dir="/dummy",
        documents_found=[],
        all_extracted_fields={
            "age": ExtractedField(
                field_name="age",
                value=42,
                confidence=0.95,
                source_document="app.pdf",
                evidence="42",
            ),
            "declared_monthly_income": ExtractedField(
                field_name="declared_monthly_income",
                value=80000.0,
                confidence=0.95,
                source_document="app.pdf",
                evidence="80000",
            ),
            "credit_score": ExtractedField(
                field_name="credit_score",
                value=720,
                confidence=0.95,
                source_document="app.pdf",
                evidence="720",
            ),
            "loan_amount": ExtractedField(
                field_name="loan_amount",
                value=600000.0,
                confidence=0.95,
                source_document="app.pdf",
                evidence="600000",
            ),
            "loan_tenure": ExtractedField(
                field_name="loan_tenure",
                value=48,
                confidence=0.95,
                source_document="app.pdf",
                evidence="48",
            ),
        },
    )
    feats = extract_features(package)
    assert feats["age"] == 42.0
    assert feats["monthly_income"] == 80000.0
    assert feats["credit_score"] == 720.0
    assert feats["loan_amount"] == 600000.0


# ---------------------------------------------------------------------------
# Deterministic Rules and Factor Extraction Tests
# ---------------------------------------------------------------------------


def test_risk_rules_engine(sample_applicant: Applicant, high_risk_applicant: Applicant):
    """Verify explainable factor generation from applicant features."""
    engine = RiskRulesEngine()

    res_sample = engine.evaluate_rules(sample_applicant)
    assert "risk_factors" in res_sample
    assert "protective_factors" in res_sample
    # Prime credit score (780) should generate protective factor
    assert any("credit score" in f.lower() for f in res_sample["protective_factors"])

    res_high = engine.evaluate_rules(high_risk_applicant)
    # Low score (570) and high DTI should generate risk factors
    assert any("credit score" in f.lower() for f in res_high["risk_factors"])
    assert any("debt-to-income" in f.lower() for f in res_high["risk_factors"])


# ---------------------------------------------------------------------------
# Baseline Scorer Tests
# ---------------------------------------------------------------------------


def test_baseline_risk_scorer(
    sample_applicant: Applicant, high_risk_applicant: Applicant
):
    """Verify Baseline Weighted Scorer outputs bounded score and relative ordering."""
    scorer = RiskScorer()

    score_sample, level_sample = scorer.calculate_score(sample_applicant)
    assert 0.0 <= score_sample <= 100.0
    assert isinstance(level_sample, RiskLevel)

    score_high, level_high = scorer.calculate_score(high_risk_applicant)
    assert 0.0 <= score_high <= 100.0

    # High risk applicant must receive higher numerical risk score than prime applicant
    assert score_high > score_sample
    assert level_high in (RiskLevel.HIGH, RiskLevel.BORDERLINE)


# ---------------------------------------------------------------------------
# ML Risk Model Tests
# ---------------------------------------------------------------------------


def test_ml_risk_model_inference(sample_applicant: Applicant):
    """Verify ML Risk Model inference, probability outputs, and score boundaries."""
    model = MLRiskModel()
    score, category, probs = model.predict_risk(sample_applicant)

    assert 0.0 <= score <= 100.0
    assert isinstance(category, RiskLevel)
    assert sum(probs.values()) == pytest.approx(1.0, abs=1e-3)

    # Legacy probability method
    prob = model.predict_default_probability(sample_applicant)
    assert 0.0 <= prob <= 1.0


def test_ml_risk_model_reproducibility(sample_applicant: Applicant):
    """Verify ML Risk Model produces deterministic, identical outputs for identical inputs."""
    model = MLRiskModel()
    score1, cat1, probs1 = model.predict_risk(sample_applicant)
    score2, cat2, probs2 = model.predict_risk(sample_applicant)

    assert score1 == score2
    assert cat1 == cat2
    assert probs1 == probs2


def test_ml_risk_model_explain_prediction(sample_applicant: Applicant):
    """Verify feature importances and top features are populated."""
    model = MLRiskModel()
    explanation = model.explain_prediction(sample_applicant)

    assert "risk_score" in explanation
    assert "feature_importances" in explanation
    assert len(explanation["feature_importances"]) > 0
    assert "credit_score" in explanation["top_features"]


# ---------------------------------------------------------------------------
# Risk Agent End-to-End Tests
# ---------------------------------------------------------------------------


def test_risk_agent_assess_applicant(sample_applicant: Applicant):
    """Verify RiskAgent assess method returns complete, valid RiskResult."""
    agent = RiskAgent()
    result = agent.assess(sample_applicant)

    assert isinstance(result, RiskResult)
    assert result.applicant_id == "app_002"
    assert 0.0 <= result.risk_score <= 100.0
    assert result.risk_category in (
        RiskLevel.LOW,
        RiskLevel.MEDIUM,
        RiskLevel.BORDERLINE,
        RiskLevel.HIGH,
    )
    assert len(result.features_used) == len(RISK_FEATURE_NAMES)
    assert len(result.feature_importance) > 0
    assert len(result.evidence) > 0
    assert result.explanation is not None
    assert result.model_version is not None


def test_risk_agent_no_loan_decision(sample_applicant: Applicant):
    """Verify that RiskAgent produces risk categorization only, not loan approval decisions."""
    agent = RiskAgent()
    result = agent.assess(sample_applicant)

    # Risk result must not contain approval decisions
    res_dict = result.model_dump()
    assert "recommendation" not in res_dict
    assert result.risk_category.value in ["LOW", "MEDIUM", "HIGH", "BORDERLINE"]
    assert result.risk_category.value not in ["APPROVE", "REJECT", "MANUAL_REVIEW"]


def test_risk_agent_with_synthetic_documents():
    """Verify RiskAgent integrates with Stage 3 Document Intake on synthetic packages."""
    doc_dir = "data/documents/APP0003"
    if not os.path.exists(doc_dir):
        pytest.skip(f"Document directory {doc_dir} not found.")

    intake = DocumentIntakeAgent()
    package = intake.process_package(applicant_id="APP0003", package_dir=doc_dir)

    agent = RiskAgent()
    result = agent.assess(package)

    assert result.applicant_id == "APP0003"
    assert 0.0 <= result.risk_score <= 100.0
    assert result.risk_category in (
        RiskLevel.LOW,
        RiskLevel.MEDIUM,
        RiskLevel.BORDERLINE,
        RiskLevel.HIGH,
    )
    assert len(result.features_used) > 0


def test_risk_agent_with_missing_document_package():
    """Verify that an applicant with missing documents is assessed on available financials without fraud flags."""
    doc_dir = "data/documents/APP0016"
    if not os.path.exists(doc_dir):
        pytest.skip(f"Document directory {doc_dir} not found.")

    intake = DocumentIntakeAgent()
    package = intake.process_package(applicant_id="APP0016", package_dir=doc_dir)

    agent = RiskAgent()
    result = agent.assess(package)

    assert result.applicant_id == "APP0016"
    assert 0.0 <= result.risk_score <= 100.0
    # No fraud or anomaly terms in risk explanation
    assert "fraud" not in result.explanation.lower()
