# Stage 3 — Document Intelligence / Document Intake Agent

## Overview

Stage 3 implements a deterministic, local **Document Intelligence & Document Intake Pipeline** for the **AI Loan Underwriting Assistant**. It validates input PDFs, inspects documents page-by-page to separate digital text pages from scanned or blank pages, applies targeted local Pillow preprocessing and Tesseract OCR only where needed, classifies supported underwriting documents via multi-signal scoring, extracts context-grounded fields with domain validation, tracks per-page provenance and heuristic confidence, and surfaces missing/invalid/ambiguous/duplicate evidence without fabricating missing financial values.

> **Scope Notice:**  
> Stage 3 performs document intelligence and evidence verification only. It does **not** alter Stage 4 eligibility thresholds, Stage 5 risk model features, or Stage 8 decisioning rules, and introduces zero external LLMs or cloud OCR APIs.

---

## Architecture

```text
Applicant Document Package (data/documents/APPXXXX/)
                      │
                      ▼
        PDF Security & Integrity Gate
     (app/document_processing/security.py)
     • .pdf extension, %PDF- header, size <= 25 MB
     • Passive /JS /OpenAction check, PII masking
                      │
                      ▼
              Page-Level PDFReader
     (app/document_processing/pdf_reader.py)
     • Per-page digital text & image analysis
     • Mixed-PDF & blank-page detection
     • Encrypted / corrupt / oversized guards
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
[Native Text Pages]         [Pages Needing OCR]
(Direct PyMuPDF)                    │
        │                           ▼
        │                  Local OCRProcessor
        │             (app/document_processing/ocr.py)
        │             • Grayscale, low-res upscale
        │             • OSD orientation correction
        │             • Selective contrast/Otsu/denoise
        │             • Local Tesseract (--oem 3 --psm 3)
        └─────────────┬─────────────┘
                      ▼
       Page-Merged Document Representation
                      │
                      ▼
      Multi-Signal Document Classifier
     (app/document_processing/extractor.py)
     • loan_application, identity_proof, address_proof
     • salary_slip, income_statement, employment_proof
     • bank_statement, or unknown (UNCLASSIFIED / AMBIGUOUS)
                      │
                      ▼
      Contextual Extractor & Field Validator
    (extractor.py + validation.py)
    • Page-aware extraction & date/domain checks
    • Statuses: valid | unverified | invalid | missing | ambiguous
    • Heuristic confidence separated from classification confidence
                      │
                      ▼
        DocumentPackageProcessor & IntakeAgent
   (document_package.py + agents/document_agent.py)
   • Salaried vs Self-Employed required doc policy
   • Duplicate skipping & multi-doc conflict preservation
   • Structured DocumentPackageResult -> Orchestrator
```

---

## Implemented Modules & Responsibilities

### 1. PDF Reading & Reliability ([pdf_reader.py](file:///Users/aditya/Desktop/Stuff/Mini%20Project/app/document_processing/pdf_reader.py))
- Inspects every PDF page independently (`PageContent`) instead of forcing one document-wide OCR decision.
- Classifies each page individually as `native_text`, `ocr_required`, `empty` (blank), or `error`.
- Correctly flags mixed PDFs (`is_mixed = True`, `is_scanned = True`) so scanned pages inside otherwise digital PDFs still receive OCR, while clean digital pages are preserved untouched.
- Tracks document-level counts (`page_count`, `successful_pages`, `native_text_pages`, `empty_pages`, `failed_pages`, `file_size_bytes`, `content_sha256`, `security_warnings`).
- Enforces controlled exceptions (`PDFValidationError`, `PDFEncryptedError`, `PDFCorruptedError`, `PDFSizeLimitError`) under `strict=True` and returns structured `PDFDocumentInfo(error=...)` by default so one broken file does not crash the pipeline.

### 2. Local OCR Workflow ([ocr.py](file:///Users/aditya/Desktop/Stuff/Mini%20Project/app/document_processing/ocr.py))
- Driven cleanly by `OCRConfig` (default `default_dpi = 300`, `tesseract_config = "--oem 3 --psm 3"`, `min_upscale_width = 1200`, `max_image_dimension = 4500`, `min_osd_confidence = 2.0`).
- **Preprocessing (`preprocess_image`)**:
  1. EXIF transpose (`ImageOps.exif_transpose`).
  2. Proportional Lanczos upscaling for low-resolution inputs (`< 1200 px` wide, bounded by `max_image_dimension`).
  3. Grayscale (`L`) conversion.
  4. Orientation correction (`pytesseract.image_to_osd` `--psm 0`) applied when image size >= `300x300` and confidence >= `min_osd_confidence`.
  5. Selective `ImageOps.autocontrast` when contrast range/black-point is compressed.
  6. Selective median denoising (on upscaled noisy images) and Otsu thresholding (when grayscale background contrast is compressed without damaging crisp 300 DPI text).
- Supports targeted `ocr_pages(file_path, page_numbers=...)` for mixed PDFs and bounded in-memory page caching to eliminate duplicate OCR work.

### 3. Document Classification ([extractor.py](file:///Users/aditya/Desktop/Stuff/Mini%20Project/app/document_processing/extractor.py))
Supports seven canonical financial/KYC categories plus explicit `unknown`:
- `loan_application`
- `identity_proof` (normalizing `identity_verification`)
- `address_proof`
- `salary_slip`
- `income_statement`
- `employment_proof`
- `bank_statement`
- `unknown` (`UNCLASSIFIED` or `AMBIGUOUS`)

Key safeguards:
- Scores weighted `heading` (at most the single strongest heading match per category), `keyword`, and `field_pattern` signals via `classify_document_detailed()`.
- Requires >= 2 signals and score >= `0.85` to classify from content alone — a single generic keyword cannot classify a document.
- Surfaces competing strong categories or tight score margins as `AMBIGUOUS` (`document_type = "unknown"`, `is_ambiguous = True`) instead of guessing.
- Keeps `classification_confidence` completely independent from field extraction confidence.

### 4. Structured Field Extraction, Validation & Confidence ([extractor.py](file:///Users/aditya/Desktop/Stuff/Mini%20Project/app/document_processing/extractor.py) & [validation.py](file:///Users/aditya/Desktop/Stuff/Mini%20Project/app/document_processing/validation.py))
- **Page-Aware Contextual Extraction**: Processes page-by-page (`page_number` preserved on every `ExtractedField`), extracting structured fields using explicit contextual labels (never bare number patterns like unlabeled `NN Years` matching `age`). Distinguishes payroll `SALARY CREDIT` deposits from non-salary credits (`other_income`) in bank statements.
- **Additional Extracted Coverage**: Includes `submission_date`, `facility_requested`, `employment_years`, `monthly_expenses`, `number_of_dependents`, `estimated_new_emi`, `issue_date`, `dob`, `address`, `designation`, `days_paid`, `employment_start_date`, `opening_balance`, `total_credits`, `total_debits`, and `masked_value` for sensitive identifiers.
- **Five Validation States**:
  - `valid`: Context-matched value passed format & domain rules (including valid explicit zeros like `existing_emi=0.0`, `number_of_dependents=0`).
  - `unverified`: Plausible value extracted under weaker context or extreme numeric magnitude warning.
  - `invalid`: Rejected values (e.g., negative income/EMI/balance, invalid calendar dates like `32-Feb-2026`, out-of-range `credit_score` or `age`) — excluded from usable downstream values and logged in `field_validations`.
  - `missing`: Expected schema field absent for the classified category.
  - `ambiguous`: Distinct conflicting values extracted across pages/matches within the same document.
- **Heuristic Confidence (`compute_extraction_confidence`)**: Transparent rule-based score in `[0.0, 0.96]` computed from extraction method (`regex_digital`, `table_parser`, `regex_ocr`, `header_positional`, `generic_fallback`), label specificity, text readability quality, and validation state. It is **not** a calibrated probability.

### 5. Package Processing & Cross-Document Consistency ([document_package.py](file:///Users/aditya/Desktop/Stuff/Mini%20Project/app/document_processing/document_package.py) & [detectors.py](file:///Users/aditya/Desktop/Stuff/Mini%20Project/app/fraud/detectors.py))
- **Package Telemetry**: Aggregates `total_pages`, `native_text_pages`, `ocr_pages`, `empty_pages`, `failed_pages`, `unclassified_documents`, `duplicate_documents` (SHA-256 binary & normalized-text deduplication before redundant OCR), `field_conflicts`, `missing_fields`, `invalid_fields`, `ambiguous_fields`, and `security_warnings`.
- **Conflict Preservation**: Preserves conflicting field values across multiple documents (such as two salary slips) in `field_conflicts` and document-scoped keys rather than silently overwriting.
- **Cross-Document Consistency (`CrossDocumentAnomalyDetector`)**: Ignores `invalid` fields, normalizes benign corporate suffixes (`Pvt. Ltd.`, `Ltd`, `LLP`) and honorifics (`Mr.`, `Ms.`), directly compares `salary_slip.net_salary` vs `bank_statement.salary_credit` (within configured tolerance), compares multiple salary slips, verifies `employment_proof` vs `salary_slip` employers, and separates missing evidence from fraud flags.

### 6. Performance & Security Safeguards ([security.py](file:///Users/aditya/Desktop/Stuff/Mini%20Project/app/document_processing/security.py))
- Validates `.pdf` extension, non-empty size, `%PDF-` signature header, configurable max file size (`25 MB`) and max pages (`100`).
- Detects `/JavaScript`, `/JS`, `/OpenAction`, `/Launch`, and `/AA` markers passively without executing embedded actions.
- Masks sensitive identifiers (`mask_identifier`, `mask_sensitive_text`) in logs and diagnostic summaries.
- Releases PyMuPDF documents, pixmaps, and Pillow images cleanly via `finally` blocks and operates primarily in-memory via `BytesIO`.
- *(Note: These safeguards harden local document parsing and do not make the prototype hardened for unauthenticated public web deployment.)*

---

## Verification & Evaluation Commands

```bash
# Run Stage 3 ground-truth, coverage, validation, and mixed-PDF evaluation
.venv/bin/python scripts/evaluate_extraction.py

# Run complete test suite with isolated temporary database
DATABASE_URL="sqlite:////tmp/test_audit.db" .venv/bin/pytest

# Run linter and formatter checks
.venv/bin/ruff check .
.venv/bin/black --check .
```

---

## Known Limitations

1. **Small Synthetic Cohort**: Evaluation covers 30 synthetic applicant packages (`115` single-page PDFs generated from controlled templates) plus an ephemeral mixed-PDF capability fixture. High metrics on these fixtures verify pipeline consistency and must not be extrapolated to arbitrary real-world bank/KYC layouts.
2. **Template & Heuristic Sensitivity**: Extraction relies on deterministic patterns and contextual labels rather than adaptive layout-independent table/key-value ML models. Highly irregular external forms may yield `UNCLASSIFIED`, `unverified`, or `missing` statuses rather than forcing guesses.
3. **OCR Scope & Language**: Configured locally for English (`lang="eng"`). Severely skewed non-90-degree scans, handwritten text, or multi-lingual filings remain out of scope for deterministic Tesseract preprocessing.
4. **In-Sample Fixture Overlap**: Many layout patterns were inspected against the Stage 2 synthetic templates; independent out-of-distribution testing is required prior to production use.
