"""Unit tests for generated loan documents, manifest, and ground truth."""

import json
import os

import pandas as pd
import pymupdf
import pytest

DOCUMENTS_DIR = "data/documents"
SYNTHETIC_DATA_DIR = "data/synthetic_data"


@pytest.fixture(scope="module")
def manifest_df():
    """Load document manifest dataframe."""
    manifest_path = os.path.join(SYNTHETIC_DATA_DIR, "document_manifest.csv")
    assert os.path.exists(manifest_path), "document_manifest.csv must exist"
    return pd.read_csv(manifest_path)


@pytest.fixture(scope="module")
def ground_truth_data():
    """Load ground truth JSON."""
    gt_path = os.path.join(SYNTHETIC_DATA_DIR, "ground_truth.json")
    assert os.path.exists(gt_path), "ground_truth.json must exist"
    with open(gt_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_document_packages_existence():
    """Verify document folders exist for APP0001 through APP0030."""
    for i in range(1, 31):
        app_dir = os.path.join(DOCUMENTS_DIR, f"APP{i:04d}")
        assert os.path.isdir(app_dir), f"Directory {app_dir} should exist"


def test_manifest_record_count(manifest_df):
    """Verify document manifest contains 120 document slots (30 applicants x 4 documents)."""
    assert len(manifest_df) == 120
    assert set(manifest_df["applicant_id"].unique()) == {
        f"APP{i:04d}" for i in range(1, 31)
    }


def test_missing_document_cases(ground_truth_data):
    """Verify missing document cases (APP0016..APP0020) are genuinely absent on disk."""
    expected_missing = {
        "APP0016": "bank_statement.pdf",
        "APP0017": "salary_slip.pdf",
        "APP0018": "identity_proof.pdf",
        "APP0019": "bank_statement.pdf",
        "APP0020": "salary_slip.pdf",
    }

    for app_id, doc_filename in expected_missing.items():
        doc_path = os.path.join(DOCUMENTS_DIR, app_id, doc_filename)
        assert not os.path.exists(doc_path), f"File {doc_path} should be missing"
        assert len(ground_truth_data[app_id]["missing_documents"]) > 0


def test_normal_baseline_packages(ground_truth_data):
    """Verify normal baseline packages (APP0001..APP0005) have all 4 documents and no anomalies."""
    for i in range(1, 6):
        app_id = f"APP{i:04d}"
        assert ground_truth_data[app_id]["has_anomalies"] is False
        assert len(ground_truth_data[app_id]["anomalies"]) == 0
        assert len(ground_truth_data[app_id]["missing_documents"]) == 0

        # Check all 4 files exist
        app_dir = os.path.join(DOCUMENTS_DIR, app_id)
        pdf_files = [f for f in os.listdir(app_dir) if f.endswith(".pdf")]
        assert len(pdf_files) == 4


def test_income_mismatch_cohort(ground_truth_data):
    """Verify income mismatch cohort (APP0006..APP0010) records proper anomaly metadata."""
    for i in range(6, 11):
        app_id = f"APP{i:04d}"
        gt = ground_truth_data[app_id]
        assert gt["has_anomalies"] is True
        types = [a["type"] for a in gt["anomalies"]]
        assert "INCOME_MISMATCH" in types


def test_name_mismatch_cohort(ground_truth_data):
    """Verify name mismatch cohort (APP0011..APP0015) records proper anomaly metadata."""
    for i in range(11, 16):
        app_id = f"APP{i:04d}"
        gt = ground_truth_data[app_id]
        assert gt["has_anomalies"] is True
        types = [a["type"] for a in gt["anomalies"]]
        assert "NAME_MISMATCH" in types


def test_financial_inconsistency_cohort(ground_truth_data):
    """Verify financial inconsistency cohort (APP0021..APP0025) records FINANCIAL_INCONSISTENCY."""
    for i in range(21, 26):
        app_id = f"APP{i:04d}"
        gt = ground_truth_data[app_id]
        assert gt["has_anomalies"] is True
        types = [a["type"] for a in gt["anomalies"]]
        assert "FINANCIAL_INCONSISTENCY" in types


def test_borderline_cases(ground_truth_data):
    """Verify borderline cases (APP0026..APP0030) are structured for manual review without corruptions."""
    for i in range(26, 31):
        app_id = f"APP{i:04d}"
        gt = ground_truth_data[app_id]
        assert gt["has_anomalies"] is False
        assert gt["notes"] is not None


def test_scanned_format_rasterization(manifest_df):
    """Verify that scanned format documents contain no extractable vector text."""
    scanned_docs = manifest_df[manifest_df["document_format"] == "scanned"]
    assert len(scanned_docs) == 4

    for _, row in scanned_docs.iterrows():
        doc = pymupdf.open(row["file_path"])
        text = doc[0].get_text().strip()
        assert (
            len(text) == 0
        ), f"Scanned doc {row['file_path']} should have no extractable text"
        doc.close()


def test_text_pdf_extractability(manifest_df):
    """Verify that regular text PDFs contain extractable text and synthetic disclaimer."""
    text_docs = manifest_df[
        (manifest_df["document_format"] == "text_pdf") & manifest_df["expected_present"]
    ]
    # Check sample of text documents
    sample_docs = text_docs.head(10)
    for _, row in sample_docs.iterrows():
        doc = pymupdf.open(row["file_path"])
        text = doc[0].get_text()
        assert "SYNTHETIC" in text
        assert len(text.strip()) > 50
        doc.close()
