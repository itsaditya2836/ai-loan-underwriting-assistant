"""Unit tests for synthetic applicant dataset and financial calculations."""

import json
import os

import pandas as pd

from scripts.generate_synthetic_dataset import (
    calculate_emi,
    generate_dataset,
    generate_unique_names,
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
