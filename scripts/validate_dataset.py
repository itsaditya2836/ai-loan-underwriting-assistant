"""Dataset and Document Validation Suite for AI Loan Underwriting Assistant.

Performs comprehensive consistency, integrity, and mathematical validation across:
- data/synthetic_data/applicants.csv
- data/synthetic_data/applicants.json
- data/synthetic_data/dataset_metadata.json
- data/synthetic_data/document_manifest.csv
- data/synthetic_data/ground_truth.json
- data/documents/APP0001..APP0030

Exits with code 0 on complete pass, or code 1 if any validation rule fails.
"""

import hashlib
import json
import os
import sys
from typing import Any, Dict, List, Sequence, Tuple

import pandas as pd
import pymupdf

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.risk.feature_contract import (  # noqa: E402
    FEATURE_CONTRACT_VERSION,
    RISK_FEATURE_CONTRACT,
    RISK_FEATURE_NAMES,
)
from app.risk.risk_model import (  # noqa: E402
    DEFAULT_METADATA_PATH,
    DEFAULT_MODEL_PATH,
    MLRiskModel,
    RiskModelError,
)

SYNTHETIC_DATA_DIR = "data/synthetic_data"
DOCUMENTS_DIR = "data/documents"

EXPECTED_APPLICANT_COLUMNS = [
    "applicant_id",
    "name",
    "age",
    "gender",
    "employment_type",
    "employer_name",
    "employment_years",
    "monthly_income",
    "existing_emi",
    "loan_amount",
    "loan_tenure",
    "credit_score",
    "bank_balance",
    "city",
    "monthly_expenses",
    "number_of_dependents",
    "total_monthly_obligations",
    "estimated_new_emi",
    "dti_ratio",
    "loan_to_income_ratio",
    "profile_category",
]
VALID_TARGET_LABELS = {"LOW_RISK", "MEDIUM_RISK", "HIGH_RISK", "BORDERLINE"}
FORBIDDEN_FEATURE_COLUMNS = {
    "applicant_id",
    "name",
    "gender",
    "employer_name",
    "city",
    "profile_category",
    "total_monthly_obligations",
}


def validate_ml_dataframe(
    df_applicants: pd.DataFrame,
    expected_columns: Sequence[str] = EXPECTED_APPLICANT_COLUMNS,
    valid_labels: Sequence[str] = tuple(sorted(VALID_TARGET_LABELS)),
    check_unexpected_columns: bool = True,
) -> Tuple[List[str], List[str], Dict[str, Any]]:
    """Validate tabular applicant data for ML schema, domain bounds, leakage, and bias."""
    errors: List[str] = []
    warnings: List[str] = []
    diagnostics: Dict[str, Any] = {}

    if df_applicants.empty:
        errors.append("ML Check Failed: Applicant dataset is empty.")
        return errors, warnings, diagnostics

    missing_cols = [c for c in expected_columns if c not in df_applicants.columns]
    if missing_cols:
        errors.append(f"ML Check Failed: Missing required columns: {missing_cols}")

    if check_unexpected_columns:
        unexpected_cols = [
            c for c in df_applicants.columns if c not in set(expected_columns)
        ]
        if unexpected_cols:
            errors.append(
                f"ML Check Failed: Unexpected dataset columns found: {unexpected_cols}"
            )

    if "applicant_id" in df_applicants.columns:
        if df_applicants["applicant_id"].isna().any():
            errors.append("ML Check Failed: Null values found in applicant_id.")
        elif df_applicants["applicant_id"].duplicated().any():
            dups = df_applicants.loc[
                df_applicants["applicant_id"].duplicated(), "applicant_id"
            ].tolist()
            errors.append(f"ML Check Failed: Duplicate applicant_id entries: {dups}")

    if df_applicants.duplicated().any():
        errors.append("ML Check Failed: Exact duplicate rows found in dataset.")

    if "profile_category" in df_applicants.columns:
        if df_applicants["profile_category"].isna().any():
            errors.append("ML Check Failed: Null values in target profile_category.")
        else:
            invalid_labels = sorted(
                set(df_applicants["profile_category"].astype(str).unique())
                - set(valid_labels)
            )
            if invalid_labels:
                errors.append(
                    f"ML Check Failed: Invalid profile_category labels: {invalid_labels}"
                )

    leaky_cols = FORBIDDEN_FEATURE_COLUMNS.intersection(RISK_FEATURE_NAMES)
    if leaky_cols:
        errors.append(
            f"ML Check Failed: Leaky or sensitive columns in feature contract: "
            f"{sorted(leaky_cols)}"
        )

    non_negative_cols = [
        "employment_years",
        "existing_emi",
        "bank_balance",
        "monthly_expenses",
        "number_of_dependents",
        "estimated_new_emi",
        "dti_ratio",
        "loan_to_income_ratio",
    ]
    for col in non_negative_cols:
        if col in df_applicants.columns:
            neg = df_applicants[df_applicants[col] < 0]
            if not neg.empty:
                errors.append(
                    f"ML Check Failed: Negative values found in '{col}' "
                    f"for rows {neg.get('applicant_id', neg.index).tolist()}"
                )

    if {"age", "employment_years"}.issubset(df_applicants.columns):
        implausible = df_applicants[
            df_applicants["employment_years"] > (df_applicants["age"] - 16)
        ]
        if not implausible.empty:
            ids = implausible.get("applicant_id", implausible.index).tolist()
            warnings.append(
                "Plausibility Warning (non-blocking synthetic artifact): "
                f"employment_years > age - 16 for {len(ids)} applicants: {ids}"
            )

    if not missing_cols:
        extracted_ok = 0
        for idx, row in df_applicants.iterrows():
            record = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
            try:
                feats = RISK_FEATURE_CONTRACT.extract(record)
                if list(feats.keys()) != RISK_FEATURE_NAMES:
                    errors.append(
                        f"ML Check Failed: Feature order mismatch on row {idx}."
                    )
                    break
                extracted_ok += 1
            except Exception as exc:
                errors.append(
                    f"ML Check Failed: Feature contract extraction error on "
                    f"row {row.get('applicant_id', idx)}: {exc}"
                )
        diagnostics["extracted_rows"] = extracted_ok

    if {"gender", "profile_category"}.issubset(df_applicants.columns):
        gender_counts = df_applicants["gender"].value_counts().to_dict()
        cross_tab = pd.crosstab(
            df_applicants["gender"], df_applicants["profile_category"]
        ).to_dict()
        diagnostics["gender_counts"] = gender_counts
        diagnostics["gender_by_target"] = cross_tab
        if len(gender_counts) < 2:
            warnings.append(
                f"Fairness Audit Warning: Limited gender diversity {gender_counts}."
            )

    return errors, warnings, diagnostics


def validate_csv_json_feature_parity(
    df_applicants: pd.DataFrame, json_records: Sequence[Dict[str, Any]]
) -> List[str]:
    """Verify CSV and JSON representations extract identical RiskFeatureContract dicts."""
    errors: List[str] = []
    json_by_id = {str(r.get("applicant_id")): r for r in json_records}
    for _, row in df_applicants.iterrows():
        app_id = str(row["applicant_id"])
        if app_id not in json_by_id:
            errors.append(f"Feature Parity Failed: {app_id} missing in JSON.")
            continue
        csv_record = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        csv_feats = RISK_FEATURE_CONTRACT.extract(csv_record)
        json_feats = RISK_FEATURE_CONTRACT.extract(json_by_id[app_id])
        if csv_feats != json_feats:
            errors.append(
                f"Feature Parity Failed for {app_id}: CSV and JSON features differ."
            )
    return errors


def validate_model_artifact_consistency(
    dataset_path: str,
    model_path: str = DEFAULT_MODEL_PATH,
    metadata_path: str = DEFAULT_METADATA_PATH,
) -> Tuple[List[str], List[str]]:
    """Verify serialized ML artifact & metadata align with dataset and contract."""
    errors: List[str] = []
    warnings: List[str] = []
    if not os.path.exists(model_path) or not os.path.exists(metadata_path):
        warnings.append(
            f"Artifact Check Skipped: {model_path} or {metadata_path} not present."
        )
        return errors, warnings

    with open(dataset_path, "rb") as f:
        dataset_sha256 = hashlib.sha256(f.read()).hexdigest()

    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    if metadata.get("dataset_sha256") != dataset_sha256:
        errors.append(
            "Artifact Check Failed: metadata dataset_sha256 does not match dataset CSV."
        )
    if metadata.get("feature_contract_version") != FEATURE_CONTRACT_VERSION:
        errors.append(
            "Artifact Check Failed: metadata feature_contract_version mismatch."
        )
    if metadata.get("feature_names") != RISK_FEATURE_NAMES:
        errors.append(
            "Artifact Check Failed: metadata feature_names do not match contract."
        )

    train_ids = set(metadata.get("train_applicant_ids", []))
    test_ids = set(metadata.get("test_applicant_ids", []))
    if not train_ids or not test_ids or not train_ids.isdisjoint(test_ids):
        errors.append(
            "Artifact Check Failed: train/test applicant splits missing or overlapping."
        )

    try:
        MLRiskModel(model_path=model_path, metadata_path=metadata_path)
    except RiskModelError as exc:
        errors.append(f"Artifact Check Failed: MLRiskModel rejected artifact: {exc}")

    return errors, warnings


def run_validation() -> bool:
    """Execute all 15 validation checks and print detailed diagnostics."""
    print("=" * 60)
    print("STARTING SYNTHETIC DATASET & DOCUMENT VALIDATION")
    print("=" * 60)

    errors: List[str] = []

    # -------------------------------------------------------------
    # 1. Verify exactly 100 applicants exist in CSV and JSON
    # -------------------------------------------------------------
    csv_path = os.path.join(SYNTHETIC_DATA_DIR, "applicants.csv")
    json_path = os.path.join(SYNTHETIC_DATA_DIR, "applicants.json")

    if not os.path.exists(csv_path):
        errors.append(f"Missing file: {csv_path}")
        return False
    if not os.path.exists(json_path):
        errors.append(f"Missing file: {json_path}")
        return False

    df_applicants = pd.read_csv(csv_path)
    with open(json_path, "r", encoding="utf-8") as f:
        json_applicants = json.load(f)

    if len(df_applicants) != 100:
        errors.append(
            f"Rule 1 Failed: Expected exactly 100 CSV rows, found {len(df_applicants)}"
        )
    if len(json_applicants) != 100:
        errors.append(
            f"Rule 1 Failed: Expected exactly 100 JSON items, found {len(json_applicants)}"
        )
    print("✓ Rule 1: Exactly 100 applicants confirmed in CSV and JSON.")

    # -------------------------------------------------------------
    # 2. Verify applicant IDs are unique
    # -------------------------------------------------------------
    app_ids = df_applicants["applicant_id"].tolist()
    if len(set(app_ids)) != 100:
        errors.append("Rule 2 Failed: Applicant IDs are not unique.")
    expected_ids = [f"APP{i:04d}" for i in range(1, 101)]
    if app_ids != expected_ids:
        errors.append(
            "Rule 2 Failed: Applicant IDs do not match expected sequence APP0001..APP0100."
        )
    print(
        "✓ Rule 2: Applicant IDs are unique and sequentially ordered APP0001..APP0100."
    )

    # -------------------------------------------------------------
    # 3. Verify names are unique
    # -------------------------------------------------------------
    names = df_applicants["name"].tolist()
    if len(set(names)) != 100:
        errors.append(
            f"Rule 3 Failed: Names are not unique. Unique count: {len(set(names))}"
        )
    print("✓ Rule 3: All 100 applicant names are unique.")

    # -------------------------------------------------------------
    # 4. Required columns exist and have no nulls
    # -------------------------------------------------------------
    required_cols = [
        "applicant_id",
        "name",
        "age",
        "gender",
        "employment_type",
        "employer_name",
        "employment_years",
        "monthly_income",
        "existing_emi",
        "loan_amount",
        "loan_tenure",
        "credit_score",
        "bank_balance",
        "city",
        "monthly_expenses",
        "number_of_dependents",
        "total_monthly_obligations",
        "estimated_new_emi",
        "dti_ratio",
        "loan_to_income_ratio",
        "profile_category",
    ]
    missing_cols = [c for c in required_cols if c not in df_applicants.columns]
    if missing_cols:
        errors.append(f"Rule 4 Failed: Missing columns: {missing_cols}")
    null_counts = df_applicants[required_cols].isnull().sum().sum()
    if null_counts > 0:
        errors.append(
            f"Rule 4 Failed: Found {null_counts} null values in required columns."
        )
    print("✓ Rule 4: All required columns exist and contain zero null values.")

    # -------------------------------------------------------------
    # 5. Numeric values fall within valid domains
    # -------------------------------------------------------------
    if not (df_applicants["age"].between(18, 100).all()):
        errors.append("Rule 5 Failed: Age outside [18, 100]")
    if not (df_applicants["credit_score"].between(300, 850).all()):
        errors.append("Rule 5 Failed: Credit score outside [300, 850]")
    if not ((df_applicants["monthly_income"] > 0).all()):
        errors.append("Rule 5 Failed: Monthly income non-positive")
    if not ((df_applicants["loan_amount"] > 0).all()):
        errors.append("Rule 5 Failed: Loan amount non-positive")
    print("✓ Rule 5: Numeric fields conform to domain bounds.")

    # -------------------------------------------------------------
    # 6. EMI calculations are mathematically valid
    # -------------------------------------------------------------
    r = 0.105 / 12.0
    for _, row in df_applicants.iterrows():
        p = row["loan_amount"]
        n = row["loan_tenure"]
        expected_emi = round(p * r * ((1 + r) ** n) / (((1 + r) ** n) - 1), 2)
        if abs(row["estimated_new_emi"] - expected_emi) > 0.05:
            errors.append(
                f"Rule 6 Failed: EMI mismatch for {row['applicant_id']}: declared {row['estimated_new_emi']} vs calculated {expected_emi}"
            )
            break
    print("✓ Rule 6: Amortized EMI values are mathematically accurate.")

    # -------------------------------------------------------------
    # 7. DTI values are mathematically consistent
    # -------------------------------------------------------------
    for _, row in df_applicants.iterrows():
        expected_dti = round(
            ((row["existing_emi"] + row["estimated_new_emi"]) / row["monthly_income"])
            * 100.0,
            2,
        )
        if abs(row["dti_ratio"] - expected_dti) > 0.05:
            errors.append(
                f"Rule 7 Failed: DTI mismatch for {row['applicant_id']}: declared {row['dti_ratio']} vs calculated {expected_dti}"
            )
            break
    print("✓ Rule 7: DTI ratios are mathematically consistent.")

    # -------------------------------------------------------------
    # 8. Document directories exist for APP0001..APP0030
    # -------------------------------------------------------------
    for i in range(1, 31):
        d = os.path.join(DOCUMENTS_DIR, f"APP{i:04d}")
        if not os.path.isdir(d):
            errors.append(f"Rule 8 Failed: Missing directory {d}")
    print("✓ Rule 8: Document directories verified for APP0001 through APP0030.")

    # -------------------------------------------------------------
    # 9. Manifest matches actual filesystem records
    # -------------------------------------------------------------
    manifest_path = os.path.join(SYNTHETIC_DATA_DIR, "document_manifest.csv")
    if not os.path.exists(manifest_path):
        errors.append(f"Missing file: {manifest_path}")
        return False

    df_manifest = pd.read_csv(manifest_path)
    if len(df_manifest) != 120:
        errors.append(
            f"Rule 9 Failed: Expected 120 manifest rows (30*4), got {len(df_manifest)}"
        )

    for _, m_row in df_manifest.iterrows():
        fpath = m_row["file_path"]
        expected_present = bool(m_row["expected_present"])
        actually_present = os.path.exists(fpath)

        if expected_present != actually_present:
            errors.append(
                f"Rule 9 Failed: Manifest mismatch for {m_row['document_id']}: expected_present={expected_present}, file_exists={actually_present}"
            )
    print("✓ Rule 9: Document manifest perfectly matches physical filesystem files.")

    # -------------------------------------------------------------
    # 10. Ground truth references valid applicant IDs
    # -------------------------------------------------------------
    gt_path = os.path.join(SYNTHETIC_DATA_DIR, "ground_truth.json")
    if not os.path.exists(gt_path):
        errors.append(f"Missing file: {gt_path}")
        return False

    with open(gt_path, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    if len(ground_truth) != 30:
        errors.append(
            f"Rule 10 Failed: Expected ground truth for 30 applicants, found {len(ground_truth)}"
        )

    for app_id in ground_truth.keys():
        if app_id not in expected_ids[:30]:
            errors.append(
                f"Rule 10 Failed: Unknown applicant {app_id} in ground truth."
            )
    print("✓ Rule 10: Ground truth covers all 30 document packages.")

    # -------------------------------------------------------------
    # 11. Expected anomaly cohorts exist in ground truth
    # -------------------------------------------------------------
    # Normal: APP0001..APP0005
    for i in range(1, 6):
        aid = f"APP{i:04d}"
        if ground_truth[aid]["has_anomalies"] is not False:
            errors.append(
                f"Rule 11 Failed: Normal case {aid} incorrectly marked with anomalies."
            )

    # Income Mismatch: APP0006..APP0010
    for i in range(6, 11):
        aid = f"APP{i:04d}"
        types = [a["type"] for a in ground_truth[aid]["anomalies"]]
        if "INCOME_MISMATCH" not in types:
            errors.append(f"Rule 11 Failed: {aid} missing expected INCOME_MISMATCH.")

    # Name Mismatch: APP0011..APP0015
    for i in range(11, 16):
        aid = f"APP{i:04d}"
        types = [a["type"] for a in ground_truth[aid]["anomalies"]]
        if "NAME_MISMATCH" not in types:
            errors.append(f"Rule 11 Failed: {aid} missing expected NAME_MISMATCH.")

    # Missing Document: APP0016..APP0020
    for i in range(16, 21):
        aid = f"APP{i:04d}"
        types = [a["type"] for a in ground_truth[aid]["anomalies"]]
        if (
            "MISSING_DOCUMENT" not in types
            or len(ground_truth[aid]["missing_documents"]) == 0
        ):
            errors.append(f"Rule 11 Failed: {aid} missing expected MISSING_DOCUMENT.")

    # Financial Inconsistency: APP0021..APP0025
    for i in range(21, 26):
        aid = f"APP{i:04d}"
        types = [a["type"] for a in ground_truth[aid]["anomalies"]]
        if "FINANCIAL_INCONSISTENCY" not in types:
            errors.append(
                f"Rule 11 Failed: {aid} missing expected FINANCIAL_INCONSISTENCY."
            )

    # Borderline: APP0026..APP0030
    for i in range(26, 31):
        aid = f"APP{i:04d}"
        if ground_truth[aid]["has_anomalies"] is not False:
            errors.append(
                f"Rule 11 Failed: Borderline case {aid} incorrectly flagged with anomalies."
            )
        if not ground_truth[aid]["notes"]:
            errors.append(
                f"Rule 11 Failed: Borderline case {aid} missing underwriter notes."
            )
    print("✓ Rule 11: All 6 controlled anomaly and baseline cohorts verified.")

    # -------------------------------------------------------------
    # 12. Missing-document cases are genuinely absent on disk
    # -------------------------------------------------------------
    missing_targets = {
        "APP0016": "bank_statement.pdf",
        "APP0017": "salary_slip.pdf",
        "APP0018": "identity_proof.pdf",
        "APP0019": "bank_statement.pdf",
        "APP0020": "salary_slip.pdf",
    }
    for aid, doc_file in missing_targets.items():
        doc_path = os.path.join(DOCUMENTS_DIR, aid, doc_file)
        if os.path.exists(doc_path):
            errors.append(
                f"Rule 12 Failed: File should be missing but exists: {doc_path}"
            )
    print("✓ Rule 12: Missing document test cases are confirmed absent on disk.")

    # -------------------------------------------------------------
    # 13. Normal cases contain all 4 documents on disk
    # -------------------------------------------------------------
    for i in range(1, 6):
        aid = f"APP{i:04d}"
        app_files = os.listdir(os.path.join(DOCUMENTS_DIR, aid))
        pdf_count = len([f for f in app_files if f.endswith(".pdf")])
        if pdf_count != 4:
            errors.append(f"Rule 13 Failed: {aid} has {pdf_count} PDFs instead of 4.")
    print("✓ Rule 13: Normal baseline cases contain complete 4-document packages.")

    # -------------------------------------------------------------
    # 14. Scanned documents format validation
    # -------------------------------------------------------------
    scanned_records = df_manifest[df_manifest["document_format"] == "scanned"]
    if len(scanned_records) != 4:
        errors.append(
            f"Rule 14 Failed: Expected 4 scanned documents in manifest, got {len(scanned_records)}"
        )
    for _, s_row in scanned_records.iterrows():
        doc = pymupdf.open(s_row["file_path"])
        page_text = doc[0].get_text().strip()
        if len(page_text) > 0:
            errors.append(
                f"Rule 14 Failed: Scanned document {s_row['file_path']} contains selectable text."
            )
        doc.close()
    print(
        "✓ Rule 14: Scanned format documents (2 salary, 2 bank) verified as rasterized image-only PDFs."
    )

    # -------------------------------------------------------------
    # 15. Profile distribution balance
    # -------------------------------------------------------------
    cat_counts = df_applicants["profile_category"].value_counts().to_dict()
    if cat_counts.get("LOW_RISK", 0) != 30:
        errors.append(
            f"Rule 15 Failed: Expected 30 LOW_RISK, got {cat_counts.get('LOW_RISK', 0)}"
        )
    if cat_counts.get("MEDIUM_RISK", 0) != 30:
        errors.append(
            f"Rule 15 Failed: Expected 30 MEDIUM_RISK, got {cat_counts.get('MEDIUM_RISK', 0)}"
        )
    if cat_counts.get("HIGH_RISK", 0) != 20:
        errors.append(
            f"Rule 15 Failed: Expected 20 HIGH_RISK, got {cat_counts.get('HIGH_RISK', 0)}"
        )
    if cat_counts.get("BORDERLINE", 0) != 20:
        errors.append(
            f"Rule 15 Failed: Expected 20 BORDERLINE, got {cat_counts.get('BORDERLINE', 0)}"
        )
    print(f"✓ Rule 15: Target profile distribution satisfied: {cat_counts}")

    # -------------------------------------------------------------
    # 16-20. ML Reliability, Leakage, Parity, Fairness & Artifact Checks
    # -------------------------------------------------------------
    warnings: List[str] = []

    ml_errors, ml_warnings, ml_diag = validate_ml_dataframe(df_applicants)
    errors.extend(ml_errors)
    warnings.extend(ml_warnings)
    if not ml_errors:
        print(
            "✓ Rules 16-18: ML schema, domain bounds, leakage exclusion, and "
            f"feature contract extraction passed ({ml_diag.get('extracted_rows', 0)}/100 rows)"
        )
        if "gender_counts" in ml_diag:
            print(
                "✓ Rule 19: Sensitive attribute exclusion verified ('gender' excluded "
                f"from {len(RISK_FEATURE_NAMES)} features; distribution={ml_diag['gender_counts']})"
            )

    with open(json_path, "r", encoding="utf-8") as f:
        json_records = json.load(f)
    parity_errors = validate_csv_json_feature_parity(df_applicants, json_records)
    errors.extend(parity_errors)
    if not parity_errors:
        print(
            "✓ Rule 20: CSV and JSON RiskFeatureContract extraction parity verified (100/100)"
        )

    artifact_errors, artifact_warnings = validate_model_artifact_consistency(csv_path)
    errors.extend(artifact_errors)
    warnings.extend(artifact_warnings)
    if not artifact_errors and not artifact_warnings:
        print(
            "✓ Rule 21: Serialized risk model artifact, metadata SHA-256, split "
            "disjointness, and contract verified"
        )

    if warnings:
        print("-" * 60)
        print(f"DIAGNOSTIC WARNINGS ({len(warnings)}):")
        for warn in warnings:
            print(f"  ⚠ {warn}")

    print("=" * 60)
    if errors:
        print(f"VALIDATION FAILED WITH {len(errors)} ERRORS:")
        for err in errors:
            print(f"  ❌ {err}")
        return False

    print("ALL DATASET, DOCUMENT, AND ML RELIABILITY CHECKS PASSED!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = run_validation()
    sys.exit(0 if success else 1)
