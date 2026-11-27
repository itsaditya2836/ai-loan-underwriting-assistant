"""Extraction & Document Intelligence Evaluation Script.

Evaluates Stage 3 Document Intelligence separately across:
1. Ground-truth benchmark on the 30 synthetic applicant packages (APP0001..APP0030):
   - Document classification (precision, recall, accuracy per class & overall via manifest)
   - Required/missing document detection (precision, recall, accuracy)
   - Ground-truth field extraction (precision, recall, accuracy where labeled)
   - Non-ground-truth extracted field coverage counts (never inventing accuracy)
   - OCR success on scanned PDFs
   - Page & field validation inventory (valid, unverified, invalid, missing, ambiguous)
2. Ephemeral synthetic mixed-PDF & edge-case capability benchmark:
   - Multi-page mixed PDF (digital page + scanned OCR page + blank page)
   - Explicit limitation notice distinguishing fixture verification from generalization.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import tempfile
from collections import Counter
from typing import Any, Dict, List

import pymupdf
from PIL import Image, ImageDraw

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.agents.document_agent import DocumentIntakeAgent  # noqa: E402
from app.document_processing.validation import (  # noqa: E402
    VALIDATION_AMBIGUOUS,
    VALIDATION_INVALID,
    VALIDATION_MISSING,
    VALIDATION_UNVERIFIED,
    VALIDATION_VALID,
)
from app.schemas.applicant import DocumentPackageResult  # noqa: E402

GROUND_TRUTH_PATH = os.path.join(
    PROJECT_ROOT, "data", "synthetic_data", "ground_truth.json"
)
MANIFEST_PATH = os.path.join(
    PROJECT_ROOT, "data", "synthetic_data", "document_manifest.csv"
)
DOCUMENTS_DIR = os.path.join(PROJECT_ROOT, "data", "documents")
TOTAL_PACKAGES = 30

COVERAGE_FIELDS = [
    "employment_years",
    "monthly_expenses",
    "number_of_dependents",
    "credit_score",
    "loan_amount",
    "loan_tenure",
    "employer_name",
    "net_salary",
    "gross_earnings",
    "opening_balance",
    "closing_balance",
    "salary_credit",
    "emi_debit",
    "transaction_count",
]


def _normalize_doc_type(doc_type: str) -> str:
    return (
        "identity_proof"
        if doc_type in ("identity_proof", "identity_verification")
        else doc_type
    )


def _load_manifest_by_file() -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    if not os.path.exists(MANIFEST_PATH):
        return mapping
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rel = row.get("file_path", "").replace("\\", "/")
            mapping[rel] = {
                "applicant_id": row.get("applicant_id", ""),
                "document_type": _normalize_doc_type(row.get("document_type", "")),
                "expected_present": str(row.get("expected_present", "")).lower()
                == "true",
                "document_format": row.get("document_format", "text_pdf"),
            }
    return mapping


def _safe_prf(tp: int, fp: int, fn: int) -> Dict[str, float]:
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return {
        "precision": round(prec * 100.0, 2),
        "recall": round(rec * 100.0, 2),
    }


def evaluate_applicant_package(
    applicant_id: str,
    gt_data: Dict[str, Any],
    package_result: DocumentPackageResult,
    manifest_by_file: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Evaluate classification, missing docs, OCR, validation, and GT fields for 1 package."""
    doc_cls_pairs: List[tuple[str, str]] = []
    for doc in package_result.documents_found:
        rel_path = os.path.relpath(doc.file_path, PROJECT_ROOT).replace("\\", "/")
        gt_entry = manifest_by_file.get(rel_path)
        true_type = (
            gt_entry["document_type"]
            if gt_entry
            else _normalize_doc_type(
                os.path.splitext(os.path.basename(doc.file_path))[0]
            )
        )
        doc_cls_pairs.append((true_type, doc.document_type))

    gt_missing = {_normalize_doc_type(t) for t in gt_data.get("missing_documents", [])}
    extracted_missing = set(package_result.documents_missing)

    fields = package_result.all_extracted_fields

    def _check_num(field_key: str, expected_val: Any) -> Dict[str, Any]:
        ef = fields.get(field_key)
        ext_val = ef.value if ef else None
        match = (
            abs(float(expected_val) - float(ext_val)) < 1.0
            if expected_val is not None and ext_val is not None
            else False
        )
        return {"expected": expected_val, "extracted": ext_val, "match": match}

    expected_name = str(gt_data.get("name", "")).strip().lower()
    ef_name = fields.get("applicant_name")
    ext_name = str(ef_name.value).strip().lower() if ef_name else ""

    field_evaluations = {
        "applicant_name": {
            "expected": gt_data.get("name"),
            "extracted": ef_name.value if ef_name else None,
            "match": bool(expected_name and ext_name and expected_name == ext_name),
        },
        "declared_monthly_income": _check_num(
            "monthly_income", gt_data.get("declared_monthly_income")
        ),
        "declared_existing_emi": _check_num(
            "existing_emi", gt_data.get("declared_existing_emi")
        ),
        "declared_bank_balance": _check_num(
            "bank_balance", gt_data.get("declared_bank_balance")
        ),
    }

    # Count validation states across every document
    val_counts: Counter[str] = Counter()
    for doc in package_result.documents_found:
        for entry in doc.field_validations.values():
            val_counts[str(entry.get("validation_status", "valid"))] += 1

    return {
        "applicant_id": applicant_id,
        "doc_cls_pairs": doc_cls_pairs,
        "gt_missing": gt_missing,
        "pred_missing": extracted_missing,
        "missing_docs_exact": extracted_missing == gt_missing,
        "field_evaluations": field_evaluations,
        "validation_counts": val_counts,
        "coverage_present": [k for k in COVERAGE_FIELDS if k in fields],
    }


def _evaluate_mixed_pdf_capability() -> Dict[str, Any]:
    """Run an isolated synthetic mixed-PDF benchmark (digital + OCR + blank page)."""
    agent = DocumentIntakeAgent()
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "mixed_salary_slip.pdf")
        doc = pymupdf.open()

        # Page 1: Digital native text
        p1 = doc.new_page()
        p1.insert_text(
            (72, 72),
            "SYNTHETIC DOCUMENT — FOR SOFTWARE TESTING ONLY\n"
            "ACME ROBOTICS PVT LTD\n"
            "PAYSLIP FOR THE MONTH OF AUGUST 2026\n"
            "Name: Riya Deshmukh\n"
            "Identifier: EMP-APP9001\n"
            "Period: 01-Aug-2026 to 31-Aug-2026\n"
            "Designation: Staff Engineer\n",
            fontsize=11,
        )

        # Page 2: Rasterized image-only scanned earnings/net pay section
        img = Image.new("RGB", (1400, 600), color="white")
        draw = ImageDraw.Draw(img)
        draw.text((60, 60), "Basic Salary: 60,000.00", fill="black")
        draw.text((60, 120), "Total Gross Earnings: 85,000.00", fill="black")
        draw.text((60, 180), "Total Deductions: 10,000.00", fill="black")
        draw.text((60, 240), "NET SALARY PAYABLE: INR 75,000.00", fill="black")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        p2 = doc.new_page()
        p2.insert_image(pymupdf.Rect(50, 50, 540, 300), stream=buf.getvalue())

        # Page 3: Completely blank page
        doc.new_page()
        doc.save(pdf_path)
        doc.close()

        res = agent.process_package("APP9001", tmpdir)
        slip_doc = res.documents_found[0] if res.documents_found else None
        net_field = slip_doc.extracted_fields.get("net_salary") if slip_doc else None
        name_field = (
            slip_doc.extracted_fields.get("employee_name") if slip_doc else None
        )

        return {
            "total_pages": res.total_pages,
            "native_text_pages": res.native_text_pages,
            "ocr_pages": res.ocr_pages,
            "empty_pages": res.empty_pages,
            "failed_pages": res.failed_pages,
            "extraction_method": slip_doc.extraction_method if slip_doc else "failed",
            "classified_type": slip_doc.document_type if slip_doc else "none",
            "name_page": name_field.page_number if name_field else None,
            "net_salary_value": net_field.value if net_field else None,
            "net_salary_page": net_field.page_number if net_field else None,
            "mixed_ok": bool(
                res.total_pages == 3
                and res.native_text_pages == 1
                and res.ocr_pages == 1
                and res.empty_pages == 1
                and slip_doc is not None
                and slip_doc.document_type == "salary_slip"
                and name_field is not None
                and name_field.page_number == 1
                and net_field is not None
                and net_field.value == 75000.0
                and net_field.page_number == 2
            ),
        }


def run_evaluation() -> bool:
    """Run full Stage 3 evaluation and print detailed honest metrics."""
    print("=" * 74)
    print("STAGE 3 — DOCUMENT INTELLIGENCE / EXTRACTION EVALUATION")
    print("=" * 74)

    if not os.path.exists(GROUND_TRUTH_PATH):
        print(f"Error: Ground truth file not found at {GROUND_TRUTH_PATH}")
        return False

    with open(GROUND_TRUTH_PATH, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)
    manifest_by_file = _load_manifest_by_file()

    agent = DocumentIntakeAgent()

    all_cls_pairs: List[tuple[str, str]] = []
    missing_exact_matches = 0
    missing_tp = 0
    missing_fp = 0
    missing_fn = 0

    gt_field_stats: Dict[str, Dict[str, int]] = {}
    coverage_counts: Counter[str] = Counter()
    validation_totals: Counter[str] = Counter()

    total_docs_ingested = 0
    total_docs_succeeded = 0
    total_docs_failed = 0
    total_pages = 0
    native_text_pages = 0
    ocr_pages = 0
    empty_pages = 0
    failed_pages = 0

    scanned_manifest_files = [
        path
        for path, meta in manifest_by_file.items()
        if meta.get("document_format") == "scanned"
    ]
    scanned_ocr_ok = 0

    for i in range(1, TOTAL_PACKAGES + 1):
        applicant_id = f"APP{i:04d}"
        gt_data = ground_truth.get(applicant_id)
        if not gt_data:
            continue

        pkg_dir = os.path.join(DOCUMENTS_DIR, applicant_id)
        pkg_res = agent.process_package(applicant_id, pkg_dir)
        eval_res = evaluate_applicant_package(
            applicant_id, gt_data, pkg_res, manifest_by_file
        )

        # Document & page inventory
        total_docs_ingested += len(pkg_res.documents_found) + len(
            pkg_res.processing_errors
        )
        succeeded_here = sum(
            1 for d in pkg_res.documents_found if d.document_type != "unknown"
        )
        total_docs_succeeded += succeeded_here
        total_docs_failed += len(pkg_res.processing_errors)
        total_pages += pkg_res.total_pages
        native_text_pages += pkg_res.native_text_pages
        ocr_pages += pkg_res.ocr_pages
        empty_pages += pkg_res.empty_pages
        failed_pages += pkg_res.failed_pages

        # Scanned PDF verification
        for d in pkg_res.documents_found:
            rel_path = os.path.relpath(d.file_path, PROJECT_ROOT).replace("\\", "/")
            if (
                rel_path in scanned_manifest_files
                and d.ocr_pages >= 1
                and d.extracted_fields
            ):
                scanned_ocr_ok += 1

        # Classification & missing-doc metrics
        all_cls_pairs.extend(eval_res["doc_cls_pairs"])
        if eval_res["missing_docs_exact"]:
            missing_exact_matches += 1
        gt_m = eval_res["gt_missing"]
        pr_m = eval_res["pred_missing"]
        missing_tp += len(gt_m & pr_m)
        missing_fp += len(pr_m - gt_m)
        missing_fn += len(gt_m - pr_m)

        # Ground-truth field precision/recall/accuracy
        for f_name, f_data in eval_res["field_evaluations"].items():
            stats = gt_field_stats.setdefault(
                f_name, {"expected": 0, "predicted": 0, "correct": 0}
            )
            if f_data["expected"] is not None:
                stats["expected"] += 1
            if f_data["extracted"] is not None:
                stats["predicted"] += 1
            if f_data["match"]:
                stats["correct"] += 1

        for cov_field in eval_res["coverage_present"]:
            coverage_counts[cov_field] += 1
        validation_totals.update(eval_res["validation_counts"])

    # Compute Classification accuracy, precision, recall
    cls_correct = sum(1 for t, p in all_cls_pairs if t == p)
    cls_total = len(all_cls_pairs)
    cls_acc = (cls_correct / cls_total * 100.0) if cls_total else 0.0
    cls_labels = sorted({t for t, _ in all_cls_pairs})

    print("\n[1] PACKAGE & PAGE PROCESSING INVENTORY (GROUND-TRUTH COHORT)")
    print("-" * 74)
    print(f"Applicants Evaluated            : {TOTAL_PACKAGES}")
    print(f"Documents Processed             : {total_docs_ingested}")
    print(f"Successfully Processed Docs     : {total_docs_succeeded}")
    print(f"Failed Documents                : {total_docs_failed}")
    print(f"Total Pages Processed           : {total_pages}")
    print(f"  - Native Text Pages           : {native_text_pages}")
    print(f"  - OCR-Processed Pages         : {ocr_pages}")
    print(f"  - Empty/Blank Pages           : {empty_pages}")
    print(f"  - Failed Pages                : {failed_pages}")

    print("\n[2] DOCUMENT CLASSIFICATION PERFORMANCE (AGAINST MANIFEST LABELS)")
    print("-" * 74)
    print(
        f"Overall Classification Accuracy : {cls_acc:.2f}% ({cls_correct}/{cls_total})"
    )
    for lbl in cls_labels:
        tp = sum(1 for t, p in all_cls_pairs if t == lbl and p == lbl)
        fp = sum(1 for t, p in all_cls_pairs if t != lbl and p == lbl)
        fn = sum(1 for t, p in all_cls_pairs if t == lbl and p != lbl)
        prf = _safe_prf(tp, fp, fn)
        print(
            f"  - {lbl:<20}: Precision={prf['precision']:6.2f}%  "
            f"Recall={prf['recall']:6.2f}%  (TP={tp}, FP={fp}, FN={fn})"
        )

    print("\n[3] REQUIRED / MISSING DOCUMENT DETECTION")
    print("-" * 74)
    missing_exact_acc = missing_exact_matches / TOTAL_PACKAGES * 100.0
    missing_prf = _safe_prf(missing_tp, missing_fp, missing_fn)
    print(
        f"Exact Package Missing-Set Match : {missing_exact_acc:.2f}% ({missing_exact_matches}/{TOTAL_PACKAGES})"
    )
    print(
        f"Missing-Doc Precision / Recall  : {missing_prf['precision']:.2f}% / "
        f"{missing_prf['recall']:.2f}% (TP={missing_tp}, FP={missing_fp}, FN={missing_fn})"
    )

    print("\n[4] OCR PERFORMANCE ON SCANNED MANIFEST PDFs")
    print("-" * 74)
    ocr_rate = (
        (scanned_ocr_ok / len(scanned_manifest_files) * 100.0)
        if scanned_manifest_files
        else 0.0
    )
    print(
        f"Scanned PDFs Detected & OCR'd   : {ocr_rate:.2f}% "
        f"({scanned_ocr_ok}/{len(scanned_manifest_files)})"
    )

    print("\n[5] FIELD EXTRACTION — GROUND-TRUTH LABELED FIELDS")
    print("-" * 74)
    all_gt_fields_ok = True
    for fname, st in gt_field_stats.items():
        acc = (st["correct"] / st["expected"] * 100.0) if st["expected"] else 0.0
        prec = (st["correct"] / st["predicted"] * 100.0) if st["predicted"] else 0.0
        rec = acc
        print(
            f"  ✓ {fname:<25}: Acc={acc:6.2f}%  Prec={prec:6.2f}%  "
            f"Rec={rec:6.2f}% ({st['correct']}/{st['expected']})"
        )
        if acc < 95.0:
            all_gt_fields_ok = False

    print("\n[6] FIELD EXTRACTION — UNLABELED FIELDS (COVERAGE COUNTS ONLY)")
    print("-" * 74)
    print(
        "(No independent ground truth in ground_truth.json; reporting sample coverage only)"
    )
    for cov_field in COVERAGE_FIELDS:
        cnt = coverage_counts.get(cov_field, 0)
        print(f"  - {cov_field:<25}: extracted in {cnt}/{TOTAL_PACKAGES} packages")

    print("\n[7] FIELD VALIDATION OUTCOME BREAKDOWN")
    print("-" * 74)
    for status_name in (
        VALIDATION_VALID,
        VALIDATION_UNVERIFIED,
        VALIDATION_INVALID,
        VALIDATION_MISSING,
        VALIDATION_AMBIGUOUS,
    ):
        print(f"  - {status_name:<12}: {validation_totals.get(status_name, 0)}")

    print("\n[8] MIXED-PDF CAPABILITY BENCHMARK (EPHEMERAL SYNTHETIC FIXTURE)")
    print("-" * 74)
    mixed = _evaluate_mixed_pdf_capability()
    print(
        f"Pages={mixed['total_pages']} (Native={mixed['native_text_pages']}, "
        f"OCR={mixed['ocr_pages']}, Empty={mixed['empty_pages']}, "
        f"Failed={mixed['failed_pages']}) | Method={mixed['extraction_method']} | "
        f"Type={mixed['classified_type']}"
    )
    print(
        f"Provenance Check: Page {mixed['name_page']} Name -> Page {mixed['net_salary_page']} "
        f"Net Salary ({mixed['net_salary_value']}) | Status={'PASS' if mixed['mixed_ok'] else 'FAIL'}"
    )

    print("\n" + "=" * 74)
    print("METHODOLOGICAL LIMITATIONS:")
    print(
        "  1. Small synthetic dataset (N=30 packages / 115 single-page template PDFs)."
    )
    print("  2. Same synthetic layout fixtures informed pattern design; results verify")
    print(
        "     deterministic consistency rather than unseen real-world generalization."
    )
    print(
        "  3. Part [8] mixed-PDF check uses an ephemeral synthetic fixture because the"
    )
    print("     30 static disk packages contain single-page PDFs only.")
    print("=" * 74)

    success = (
        cls_acc >= 95.0
        and missing_exact_acc >= 95.0
        and ocr_rate == 100.0
        and all_gt_fields_ok
        and mixed["mixed_ok"]
    )
    print(
        "ALL STAGE 3 EVALUATION BENCHMARKS PASSED SUCCESSFULLY!"
        if success
        else "EVALUATION COMPLETED WITH DEFICIENCIES."
    )
    return success


if __name__ == "__main__":
    passed = run_evaluation()
    sys.exit(0 if passed else 1)
