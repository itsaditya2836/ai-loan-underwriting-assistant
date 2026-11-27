"""Unit tests for synthetic applicant dataset, financial math, validation, and ML training."""

import json
import os

import pandas as pd

from app.risk.feature_contract import (
    FEATURE_CONTRACT_VERSION,
    RISK_FEATURE_CONTRACT,
    RISK_FEATURE_NAMES,
)
from app.risk.risk_model import MLRiskModel
from scripts.generate_synthetic_dataset import (
    calculate_emi,
    generate_dataset,
    generate_unique_names,
)
from scripts.train_risk_model import DEFAULT_DATASET_PATH, train_risk_model
from scripts.validate_dataset import (
    EXPECTED_APPLICANT_COLUMNS,
    validate_csv_json_feature_parity,
    validate_ml_dataframe,
)

SYNTHETIC_DATA_DIR = "data/synthetic_data"


def test_emi_calculation_formula():
    """Verify amortizing loan EMI mathematical formula with boundary conditions."""
    # Principal 1,000,000, Annual Rate 10.5%, Tenure 60 months
    emi = calculate_emi(1000000.0, 0.105, 60)
    assert 21400.0 < emi < 21600.0  # Approx 21,493.90
    assert isinstance(emi, float)

    # Edge cases
    assert calculate_emi(0.0, 0.105, 60) == 0.0
    assert calculate_emi(100000.0, 0.105, 0) == 0.0


def test_unique_name_generator():
    """Verify generated names are non-empty, unique, and contain first and last name."""
    import random

    rng = random.Random(42)
    names = generate_unique_names(50, rng)
    assert len(names) == 50
    assert len(set(names)) == 50
    for name in names:
        parts = name.split()
        assert len(parts) >= 2


def test_synthetic_dataset_generation_in_memory():
    """Verify in-memory dataset generator outputs expected applicant count and profile balance."""
    applicants, metadata = generate_dataset()
    assert len(applicants) == 100
    assert metadata["number_of_applicants"] == 100
    assert metadata["profile_distribution"]["LOW_RISK"] == 30
    assert metadata["profile_distribution"]["MEDIUM_RISK"] == 30
    assert metadata["profile_distribution"]["HIGH_RISK"] == 20
    assert metadata["profile_distribution"]["BORDERLINE"] == 20


def test_synthetic_data_files_exist_and_match():
    """Verify generated CSV and JSON files exist and have matching content."""
    csv_path = os.path.join(SYNTHETIC_DATA_DIR, "applicants.csv")
    json_path = os.path.join(SYNTHETIC_DATA_DIR, "applicants.json")
    meta_path = os.path.join(SYNTHETIC_DATA_DIR, "dataset_metadata.json")

    assert os.path.exists(csv_path), "applicants.csv should exist"
    assert os.path.exists(json_path), "applicants.json should exist"
    assert os.path.exists(meta_path), "dataset_metadata.json should exist"

    df = pd.read_csv(csv_path)
    with open(json_path, "r", encoding="utf-8") as f:
        json_data = json.load(f)

    assert len(df) == 100
    assert len(json_data) == 100
    assert df["applicant_id"].tolist() == [a["applicant_id"] for a in json_data]


def test_applicant_financial_constraints():
    """Verify mathematical consistency of DTI, EMI, and income ratios across all applicants."""
    df = pd.read_csv(os.path.join(SYNTHETIC_DATA_DIR, "applicants.csv"))

    for _, row in df.iterrows():
        # DTI formula verification
        expected_dti = round(
            ((row["existing_emi"] + row["estimated_new_emi"]) / row["monthly_income"])
            * 100.0,
            2,
        )
        assert abs(row["dti_ratio"] - expected_dti) <= 0.05

        # Loan to income ratio
        expected_lti = round(row["loan_amount"] / (row["monthly_income"] * 12.0), 2)
        assert abs(row["loan_to_income_ratio"] - expected_lti) <= 0.05

        # Valid domains
        assert 18 <= row["age"] <= 100
        assert 300 <= row["credit_score"] <= 850
        assert row["monthly_income"] > 0
        assert row["loan_amount"] > 0


def test_ml_dataframe_validator_passes_real_data_and_catches_regressions():
    """ML data validator accepts real synthetic dataset and detects schema/label/duplicate defects."""
    df = pd.read_csv(os.path.join(SYNTHETIC_DATA_DIR, "applicants.csv"))
    with open(
        os.path.join(SYNTHETIC_DATA_DIR, "applicants.json"), "r", encoding="utf-8"
    ) as f:
        json_records = json.load(f)

    errors, warnings, diag = validate_ml_dataframe(df)
    assert errors == []
    assert diag["extracted_rows"] == 100
    assert "gender" not in RISK_FEATURE_NAMES
    assert "profile_category" not in RISK_FEATURE_NAMES
    assert validate_csv_json_feature_parity(df, json_records) == []
    assert any("employment_years > age - 16" in w for w in warnings)

    # 1. Missing required column
    df_missing_col = df.drop(columns=["monthly_expenses"])
    errs, _, _ = validate_ml_dataframe(
        df_missing_col, expected_columns=EXPECTED_APPLICANT_COLUMNS
    )
    assert any("Missing required columns" in e for e in errs)

    # 2. Invalid target label
    df_bad_label = df.copy()
    df_bad_label.loc[0, "profile_category"] = "UNKNOWN_RISK"
    errs, _, _ = validate_ml_dataframe(df_bad_label)
    assert any("Invalid profile_category labels" in e for e in errs)

    # 3. Duplicate applicant_id
    df_dup_id = df.copy()
    df_dup_id.loc[1, "applicant_id"] = df_dup_id.loc[0, "applicant_id"]
    errs, _, _ = validate_ml_dataframe(df_dup_id)
    assert any("Duplicate applicant_id" in e for e in errs)


def test_reproducible_training_split_cv_and_metadata(tmp_path):
    """Training pipeline is deterministic, isolates held-out test records, and emits valid metadata."""
    model_1 = tmp_path / "run1" / "risk_model.joblib"
    meta_1 = tmp_path / "run1" / "risk_model_metadata.json"
    model_2 = tmp_path / "run2" / "risk_model.joblib"
    meta_2 = tmp_path / "run2" / "risk_model_metadata.json"

    res1 = train_risk_model(
        dataset_path=DEFAULT_DATASET_PATH,
        model_path=str(model_1),
        metadata_path=str(meta_1),
        verbose=False,
    )
    res2 = train_risk_model(
        dataset_path=DEFAULT_DATASET_PATH,
        model_path=str(model_2),
        metadata_path=str(meta_2),
        verbose=False,
    )

    assert res1["total_sample_count"] == 100
    assert res1["train_sample_count"] == 80
    assert res1["test_sample_count"] == 20
    assert set(res1["train_applicant_ids"]).isdisjoint(set(res1["test_applicant_ids"]))
    assert (
        len(set(res1["train_applicant_ids"]) | set(res1["test_applicant_ids"])) == 100
    )

    # Reproducibility across runs
    assert res1["train_applicant_ids"] == res2["train_applicant_ids"]
    assert res1["test_applicant_ids"] == res2["test_applicant_ids"]
    assert res1["cv_metrics"] == res2["cv_metrics"]
    assert res1["test_metrics"] == res2["test_metrics"]
    assert res1["feature_importances"] == res2["feature_importances"]
    assert res1["dataset_sha256"] == res2["dataset_sha256"]

    # Contract & artifact checks
    assert res1["feature_contract_version"] == FEATURE_CONTRACT_VERSION
    assert res1["feature_names"] == RISK_FEATURE_NAMES
    assert res1["cv_metrics"]["sample_count"] == 80
    assert res1["cv_metrics"]["accuracy_mean"] < 1.0  # Not overfit 100% CV leakage

    # Trained artifact loads safely through MLRiskModel and handles held-out prediction
    loaded = MLRiskModel(
        model_path=str(model_1),
        metadata_path=str(meta_1),
        feature_contract=RISK_FEATURE_CONTRACT,
    )
    df = pd.read_csv(DEFAULT_DATASET_PATH).set_index("applicant_id")
    first_test_id = res1["test_applicant_ids"][0]
    row = df.loc[first_test_id].to_dict()
    score, level, probs = loaded.predict_risk(row)
    assert 0.0 <= score <= 100.0
    assert abs(sum(probs.values()) - 1.0) < 1e-4
