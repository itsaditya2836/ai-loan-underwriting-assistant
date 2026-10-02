"""Controlled Synthetic Anomaly Detection Evaluation Script.

Evaluates Stage 6 Fraud & Anomaly Detection Agent across:
- All 30 ingested applicant document packages (APP0001 - APP0030) using Stage 3 intake.
- Synthetic ground truth annotations from data/synthetic_data/ground_truth.json.

Reports:
- Precision, Recall, and F1-score for controlled synthetic anomaly detection
- Cohort-level detection rates across all 6 synthetic cohorts
- Diagnostic breakdown of detected rule IDs and evidence
- Explicit distinction between Missing Evidence and Anomaly Flags
- Clear research and engineering limitations (no claim of real-world fraud accuracy)
"""

import json
import os
import sys
from typing import Any, Dict, List

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agents.document_agent import DocumentIntakeAgent
from app.agents.fraud_agent import FraudAnomalyAgent
from app.schemas.anomaly import AnomalyResult

DOCUMENTS_DIR = os.path.join("data", "documents")
GROUND_TRUTH_PATH = os.path.join("data", "synthetic_data", "ground_truth.json")
TOTAL_DOCUMENT_PACKAGES = 30


def evaluate_anomalies() -> Dict[str, Any]:
    """Evaluate FraudAnomalyAgent against the 30 controlled synthetic cohorts."""
    if not os.path.exists(GROUND_TRUTH_PATH):
        raise FileNotFoundError(f"Ground truth file not found at {GROUND_TRUTH_PATH}")

    with open(GROUND_TRUTH_PATH, "r", encoding="utf-8") as f:
        ground_truth: Dict[str, Any] = json.load(f)

    intake_agent = DocumentIntakeAgent()
    fraud_agent = FraudAnomalyAgent()

    # Define cohorts
    cohorts: Dict[str, Dict[str, Any]] = {
        "Normal / Consistent (01-05)": {
            "range": range(1, 6),
            "expected_anomalies": False,
            "total": 0,
            "detected": 0,
            "correct": 0,
            "rule_counts": {},
        },
        "Income Mismatch (06-10)": {
            "range": range(6, 11),
            "expected_anomalies": True,
            "total": 0,
            "detected": 0,
            "correct": 0,
            "rule_counts": {},
        },
        "Name Mismatch (11-15)": {
            "range": range(11, 16),
            "expected_anomalies": True,
            "total": 0,
            "detected": 0,
            "correct": 0,
            "rule_counts": {},
        },
        "Missing Documents (16-20)": {
            "range": range(16, 21),
            "expected_anomalies": False,  # Missing docs are incomplete evidence, NOT fraud anomalies
            "total": 0,
            "detected": 0,
            "correct": 0,
            "rule_counts": {},
            "missing_docs_detected": 0,
        },
        "Financial Inconsistency (21-25)": {
            "range": range(21, 26),
            "expected_anomalies": True,
            "total": 0,
            "detected": 0,
            "correct": 0,
            "rule_counts": {},
        },
        "Borderline Risk Profile (26-30)": {
            "range": range(26, 31),
            "expected_anomalies": False,
            "total": 0,
            "detected": 0,
            "correct": 0,
            "rule_counts": {},
        },
    }

    results: List[AnomalyResult] = []
    tp, fp, tn, fn = 0, 0, 0, 0

    for i in range(1, TOTAL_DOCUMENT_PACKAGES + 1):
        app_id = f"APP{i:04d}"
        package_dir = os.path.join(DOCUMENTS_DIR, app_id)
        if not os.path.exists(package_dir):
            continue

        package_result = intake_agent.process_package(
            applicant_id=app_id, package_dir=package_dir
        )
        anomaly_res = fraud_agent.detect(package_result)
        results.append(anomaly_res)
        gt = ground_truth.get(app_id, {})
        gt_missing = [
            "identity_proof" if d == "identity_verification" else d
            for d in gt.get("missing_documents", [])
        ]
        if gt_missing:
            assert all(d in anomaly_res.missing_evidence for d in gt_missing)

        # Note: In ground_truth.json, APP0016-0020 had has_anomalies=True with type=MISSING_DOCUMENT.
        # Under Stage 6 architectural principles, missing documents are tracked under missing_evidence,
        # not as cross-document anomaly/fraud flags.
        expected_anomaly = (6 <= i <= 15) or (21 <= i <= 25)
        observed_anomaly = anomaly_res.has_anomalies

        if expected_anomaly and observed_anomaly:
            tp += 1
        elif not expected_anomaly and observed_anomaly:
            fp += 1
        elif not expected_anomaly and not observed_anomaly:
            tn += 1
        elif expected_anomaly and not observed_anomaly:
            fn += 1

        # Match cohort
        for cohort_name, data in cohorts.items():
            if i in data["range"]:
                data["total"] += 1
                if observed_anomaly:
                    data["detected"] += 1
                if observed_anomaly == data["expected_anomalies"]:
                    data["correct"] += 1
                for flag in anomaly_res.flags:
                    data["rule_counts"][flag.rule_id] = (
                        data["rule_counts"].get(flag.rule_id, 0) + 1
                    )
                if (
                    cohort_name == "Missing Documents (16-20)"
                    and len(anomaly_res.missing_evidence) > 0
                ):
                    data["missing_docs_detected"] += 1
                break

    # Calculate metrics
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) > 0 else 0.0

    # Print Formatted Report
    print("=" * 80)
    print("    STAGE 6 — CONTROLLED SYNTHETIC ANOMALY COHORT EVALUATION REPORT")
    print("=" * 80)
    print(f"Total Evaluated Packages:   {len(results)}")
    print("Evaluation Mode:            Local Deterministic Cross-Document Consistency")
    print(
        f"Detector Version:           {results[0].detector_version if results else 'N/A'}"
    )
    print(
        "Scope Distinction:          Missing Documents recorded as missing_evidence, NOT fraud"
    )
    print("-" * 80)

    print("\n[PART 1: SYNTHETIC ANOMALY DETECTION METRICS (N=30)]")
    print("-" * 80)
    print(f"{'Metric':<36} {'Value':<16} {'Interpretation':<28}")
    print("-" * 80)
    print(
        f"{'Evaluation Accuracy':<36} {accuracy * 100:.1f}%{'':<10} Correct cohort identification"
    )
    print(
        f"{'Anomaly Precision':<36} {precision * 100:.1f}%{'':<10} True anomalies / All flagged"
    )
    print(
        f"{'Anomaly Recall':<36} {recall * 100:.1f}%{'':<10} Detected / All injected anomalies"
    )
    print(f"{'Macro F1-Score':<36} {f1:.4f}{'':<10} Harmonic mean precision/recall")
    print(f"{'True Positives (TP)':<36} {tp:<16} Successfully flagged anomalies")
    print(
        f"{'False Positives (FP)':<36} {fp:<16} Clean applicants flagged as anomalous"
    )
    print(f"{'True Negatives (TN)':<36} {tn:<16} Clean applicants correctly cleared")
    print(f"{'False Negatives (FN)':<36} {fn:<16} Anomalous applicants missed")
    print("-" * 80)

    print("\n[PART 2: COHORT-LEVEL DETECTION BREAKDOWN]")
    print("-" * 80)
    print(
        f"{'Cohort Name':<34} {'Size':<6} {'Flagged':<9} {'Accuracy':<10} {'Primary Detected Rules':<20}"
    )
    print("-" * 80)
    for c_name, c_data in cohorts.items():
        acc = (
            (c_data["correct"] / c_data["total"] * 100) if c_data["total"] > 0 else 0.0
        )
        rules_str = (
            ", ".join(f"{r} ({cnt})" for r, cnt in c_data["rule_counts"].items())
            if c_data["rule_counts"]
            else "None (Clean)"
        )
        if c_name == "Missing Documents (16-20)":
            rules_str += (
                f" [Missing evidence: {c_data.get('missing_docs_detected', 0)}/5]"
            )
        print(
            f"{c_name:<34} {c_data['total']:<6} {c_data['detected']:<9} {acc:.1f}%{'':<4} {rules_str:<20}"
        )
    print("-" * 80)

    print("\n[PART 3: RULE ACTIVATION FREQUENCY]")
    print("-" * 80)
    all_rule_counts: Dict[str, int] = {}
    for r in results:
        for f in r.flags:
            all_rule_counts[f.rule_id] = all_rule_counts.get(f.rule_id, 0) + 1
    for r_id, cnt in sorted(all_rule_counts.items()):
        print(f"  * {r_id:<14}: {cnt} applicant packages flagged")
    print("-" * 80)

    print("\n[PART 4: MISSING EVIDENCE VS ANOMALY VERIFICATION]")
    missing_docs_packages = [r for r in results if r.missing_evidence]
    print(
        f"  * Total packages with missing document evidence: {len(missing_docs_packages)}"
    )
    for r in missing_docs_packages:
        print(
            f"    - {r.applicant_id}: missing={r.missing_evidence} | has_anomalies={r.has_anomalies} (Score: {r.anomaly_score:.1f})"
        )

    print("\n" + "=" * 80)
    print("RESEARCH & METHODOLOGICAL LIMITATIONS:")
    print(
        "1. This evaluation measures deterministic consistency verification on controlled"
    )
    print(
        "   synthetic cohorts. It does NOT measure real-world banking fraud detection."
    )
    print(
        "2. The system flags discrepancies, inconsistencies, and evidence gaps; it does NOT"
    )
    print("   assert or verify criminal intent or confirmed fraud.")
    print(
        "3. Missing documents indicate incomplete verification evidence, NOT fraudulent conduct."
    )
    print(
        "4. Fully local execution: no cloud APIs, external LLMs, or paid third-party services."
    )
    print(
        "5. Architectural boundary: Stage 6 produces AnomalyResult. No final loan approval,"
    )
    print(
        "   rejection, or Stage 7 pipeline orchestration logic is executed in this stage."
    )
    print("=" * 80 + "\n")

    return {
        "total_packages": len(results),
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "cohorts": cohorts,
    }


if __name__ == "__main__":
    evaluate_anomalies()
