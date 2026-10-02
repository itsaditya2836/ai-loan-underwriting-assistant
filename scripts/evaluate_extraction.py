"""Extraction Evaluation Script for AI Loan Underwriting Assistant.

Evaluates Stage 3 Document Intelligence against Stage 2 ground-truth annotations across
all 30 applicant document packages (APP0001 through APP0030).

Computes and reports:
- Document classification accuracy
- Missing document detection accuracy
- Key financial field extraction accuracy (income, EMI, balance, name)
- OCR success rate on scanned/image-only PDFs
- Summary metrics and error diagnostics
"""

import json
import os
import sys
from typing import Any, Dict

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agents.document_agent import DocumentIntakeAgent
from app.schemas.applicant import DocumentPackageResult

GROUND_TRUTH_PATH = os.path.join("data", "synthetic_data", "ground_truth.json")
DOCUMENTS_DIR = os.path.join("data", "documents")
TOTAL_PACKAGES = 30


def evaluate_applicant_package(
    applicant_id: str,
    gt_data: Dict[str, Any],
    package_result: DocumentPackageResult,
) -> Dict[str, Any]:
    """Evaluate extraction accuracy for a single applicant package against ground truth."""
    metrics: Dict[str, Any] = {
        "applicant_id": applicant_id,
        "classification_correct": 0,
        "classification_total": 0,
        "missing_docs_correct": False,
        "field_evaluations": {},
        "ocr_expected": False,
        "ocr_success": False,
    }

    # 1. Classification check
    expected_doc_types = set(gt_data.get("expected_document_types", []))
    # Normalize identity_verification -> identity_proof for comparison
    expected_doc_types_norm = {
        "identity_proof" if t in ("identity_proof", "identity_verification") else t
        for t in expected_doc_types
    }

    metrics["classification_total"] = len(package_result.documents_found)
    metrics["classification_correct"] = sum(
        1
        for d in package_result.documents_found
        if d.document_type in expected_doc_types_norm
    )

    # 2. Missing documents check
    gt_missing = set(gt_data.get("missing_documents", []))
    gt_missing_norm = {
        "identity_proof" if t in ("identity_proof", "identity_verification") else t
        for t in gt_missing
    }
    extracted_missing = set(package_result.documents_missing)

    metrics["missing_docs_correct"] = extracted_missing == gt_missing_norm

    # 3. OCR check
    known_scanned_ids = {"APP0004", "APP0005", "APP0009", "APP0010"}
    if applicant_id in known_scanned_ids:
        metrics["ocr_expected"] = True
        metrics["ocr_success"] = package_result.ocr_used

    # 4. Field extractions check (from loan application)
    fields = package_result.all_extracted_fields

    # Applicant Name
    expected_name = gt_data.get("name", "").strip().lower()
    extracted_name = str(fields.get("applicant_name", {}).value or "").strip().lower()
    metrics["field_evaluations"]["applicant_name"] = {
        "expected": gt_data.get("name"),
        "extracted": (
            fields.get("applicant_name", {}).value
            if "applicant_name" in fields
            else None
        ),
        "match": (
            (expected_name == extracted_name)
            if expected_name and extracted_name
            else False
        ),
    }

    # Declared Monthly Income
    expected_income = gt_data.get("declared_monthly_income")
    extracted_income = (
        fields.get("monthly_income", {}).value if "monthly_income" in fields else None
    )
    metrics["field_evaluations"]["declared_monthly_income"] = {
        "expected": expected_income,
        "extracted": extracted_income,
        "match": (
            (abs(expected_income - extracted_income) < 1.0)
            if expected_income is not None and extracted_income is not None
            else False
        ),
    }

    # Declared Existing EMI
    expected_emi = gt_data.get("declared_existing_emi")
    extracted_emi = (
        fields.get("existing_emi", {}).value if "existing_emi" in fields else None
    )
    metrics["field_evaluations"]["declared_existing_emi"] = {
        "expected": expected_emi,
        "extracted": extracted_emi,
        "match": (
            (abs(expected_emi - extracted_emi) < 1.0)
            if expected_emi is not None and extracted_emi is not None
            else False
        ),
    }

    # Declared Bank Balance
    expected_bal = gt_data.get("declared_bank_balance")
    extracted_bal = (
        fields.get("bank_balance", {}).value if "bank_balance" in fields else None
    )
    metrics["field_evaluations"]["declared_bank_balance"] = {
        "expected": expected_bal,
        "extracted": extracted_bal,
        "match": (
            (abs(expected_bal - extracted_bal) < 1.0)
            if expected_bal is not None and extracted_bal is not None
            else False
        ),
    }

    return metrics


def run_evaluation() -> bool:
    """Run extraction benchmark over all 30 applicant packages."""
    print("=" * 70)
    print("STAGE 3 — DOCUMENT INTELLIGENCE / EXTRACTION EVALUATION")
    print("=" * 70)

    if not os.path.exists(GROUND_TRUTH_PATH):
        print(f"Error: Ground truth file not found at {GROUND_TRUTH_PATH}")
        return False

    with open(GROUND_TRUTH_PATH, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    agent = DocumentIntakeAgent()

    total_docs_processed = 0
    total_classifications_correct = 0
    missing_docs_evaluated = 0
    missing_docs_correct = 0
    ocr_evaluated = 0
    ocr_passed = 0

    field_totals: Dict[str, int] = {}
    field_matches: Dict[str, int] = {}

    print(f"\nProcessing {len(ground_truth)} applicant document packages...")

    for i in range(1, TOTAL_PACKAGES + 1):
        applicant_id = f"APP{i:04d}"
        gt_data = ground_truth.get(applicant_id)
        if not gt_data:
            print(f"Warning: {applicant_id} missing from ground truth.")
            continue

        package_result = agent.process_package(applicant_id)
        eval_res = evaluate_applicant_package(applicant_id, gt_data, package_result)

        total_docs_processed += eval_res["classification_total"]
        total_classifications_correct += eval_res["classification_correct"]

        missing_docs_evaluated += 1
        if eval_res["missing_docs_correct"]:
            missing_docs_correct += 1

        if eval_res["ocr_expected"]:
            ocr_evaluated += 1
            if eval_res["ocr_success"]:
                ocr_passed += 1

        for f_name, f_data in eval_res["field_evaluations"].items():
            field_totals[f_name] = field_totals.get(f_name, 0) + 1
            if f_data["match"]:
                field_matches[f_name] = field_matches.get(f_name, 0) + 1

    # Print Summary Metrics
    classification_acc = (
        (total_classifications_correct / total_docs_processed * 100.0)
        if total_docs_processed
        else 0.0
    )
    missing_acc = (
        (missing_docs_correct / missing_docs_evaluated * 100.0)
        if missing_docs_evaluated
        else 0.0
    )
    ocr_acc = (ocr_passed / ocr_evaluated * 100.0) if ocr_evaluated else 0.0

    print("\n" + "=" * 70)
    print("EVALUATION METRICS SUMMARY")
    print("=" * 70)
    print(f"Total Applicant Packages Evaluated : {TOTAL_PACKAGES}")
    print(f"Total Physical Documents Ingested : {total_docs_processed}")
    print(
        f"Document Classification Accuracy  : {classification_acc:.2f}% "
        f"({total_classifications_correct}/{total_docs_processed})"
    )
    print(
        f"Missing Document Detection Accuracy: {missing_acc:.2f}% "
        f"({missing_docs_correct}/{missing_docs_evaluated})"
    )
    print(
        f"Scanned PDF OCR Success Rate       : {ocr_acc:.2f}% "
        f"({ocr_passed}/{ocr_evaluated})"
    )

    print("\nField-Level Extraction Accuracies (Loan Application):")
    all_fields_passed = True
    for f_name, total in field_totals.items():
        matched = field_matches.get(f_name, 0)
        acc = (matched / total * 100.0) if total else 0.0
        status_icon = "✓" if acc >= 95.0 else "❌"
        print(f"  {status_icon} {f_name:<26}: {acc:6.2f}% ({matched}/{total})")
        if acc < 90.0:
            all_fields_passed = False

    print("=" * 70)

    success = (
        classification_acc >= 95.0
        and missing_acc >= 95.0
        and ocr_acc == 100.0
        and all_fields_passed
    )

    if success:
        print("ALL DOCUMENT INTELLIGENCE EVALUATION BENCHMARKS PASSED SUCCESSFULLY!")
    else:
        print("EVALUATION COMPLETED WITH DEFICIENCIES.")

    print("=" * 70)
    return success


if __name__ == "__main__":
    passed = run_evaluation()
    sys.exit(0 if passed else 1)
