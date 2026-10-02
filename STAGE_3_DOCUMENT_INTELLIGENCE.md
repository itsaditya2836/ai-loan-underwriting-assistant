# Stage 3 — Document Intelligence / Document Intake Agent

## Overview

Stage 3 implements a fully deterministic, local **Document Intelligence & Document Intake Pipeline** for the **AI Loan Underwriting Assistant**. It ingests multi-page loan document packages, automatically identifies whether a document contains selectable digital text or consists of rasterized/scanned images, runs local OCR via Tesseract when required, classifies document categories, extracts structured entity fields, preserves provenance and source evidence with confidence scores, and identifies missing mandatory applicant documents.

> **Scope Notice:**  
> **Stage 3 performs document intelligence only. Eligibility evaluation, credit-risk scoring, anomaly/fraud detection, multi-agent orchestration, and loan approval/rejection decisions are intentionally deferred to later stages.**

---

## Architecture

```text
Applicant Document Package (data/documents/APPXXXX/)
                      │
                      ▼
          Document Package Processor
         (app/document_processing/document_package.py)
                      │
                      ▼
                  PDF Reader
         (app/document_processing/pdf_reader.py)
                      │
                      ▼
               Text Detection
                (Character threshold & image analysis)
                      │
        ┌─────────────┴─────────────┐
        ▼                           ▼
[Digital PDF Text]          [Scanned PDF Detected]
(Direct PyMuPDF)                    │
        │                           ▼
        │                     OCR Processor
        │                 (app/document_processing/ocr.py)
        │                 (Local Tesseract 5.5.2 Engine)
        │                           │
        └─────────────┬─────────────┘
                      ▼
         Document Classification
         (app/document_processing/extractor.py)
         • loan_application
         • identity_proof
         • salary_slip
         • income_statement
         • bank_statement
                      │
                      ▼
             Field Extraction
         (app/document_processing/extractor.py)
         • Applicant ID, Name, Age, Gender
         • Income, EMI, Obligations, Balances
         • Credit Scores, Loan Amounts, Tenure
         • Ledger Transactions, Salary Credits
                      │
                      ▼
           Confidence & Evidence
         (Traceable ExtractedField records)
                      │
                      ▼
        Missing Document Detection
         • Salaried vs Self-Employed Profiles
         • Expected vs Ingested Sets
                      │
                      ▼
         Structured Document Result
         (DocumentPackageResult Pydantic Model)
                      │
                      ▼
            Document Intake Agent
         (app/agents/document_agent.py)
```

---

## Implementation Details

### 1. PDF Extraction Approach
Implemented in [app/document_processing/pdf_reader.py](file:///Users/aditya/Desktop/Stuff/Mini%20Project/app/document_processing/pdf_reader.py):
- Utilizes **PyMuPDF (`fitz`)** for high-performance, in-memory PDF parsing.
- Extracts text on a page-by-page basis and computes page counts, character counts, and image presence.
- Preserves page-level metadata inside `PageContent` dataclasses, ensuring traceable evidence tracking.
- Features resilient error handling for missing files, encrypted files, and malformed binary headers without process termination.
- Provides `convert_to_images(file_path, dpi=300)` for high-resolution page rasterization to PIL Images for OCR.

### 2. Scanned-Document Detection
- Evaluates total characters extracted per page against a configurable minimum alphanumeric threshold (`min_char_threshold=30`).
- If page character count is below the threshold and image objects are detected, or total document characters fall below the expected threshold for page count, the document is flagged as `is_scanned = True`.
- Generic algorithm: Requires zero hard-coding of applicant IDs or filenames, seamlessly detecting rasterized documents such as `APP0004` (salary slip), `APP0005` (bank statement), `APP0009` (salary slip), and `APP0010` (bank statement).

### 3. Local OCR Pipeline
Implemented in [app/document_processing/ocr.py](file:///Users/aditya/Desktop/Stuff/Mini%20Project/app/document_processing/ocr.py):
- Fully local execution: Wraps `pytesseract` communicating directly with the system's local **Tesseract 5.5.2** executable.
- Discovers Tesseract binaries dynamically across standard directories (`/opt/anaconda3/bin`, `/opt/homebrew/bin`, `/usr/local/bin`, `.venv/bin`).
- Renders PDF pages at 300 DPI into memory buffers, converts to RGB PIL Images, and executes OCR using engine mode 3 with page segmentation mode 6 (`--oem 3 --psm 6`).
- Operates conditionally: OCR is only executed when `is_scanned` is detected, ensuring fast, native PyMuPDF parsing for digital PDFs.

### 4. Document Classification
Implemented in [app/document_processing/extractor.py](file:///Users/aditya/Desktop/Stuff/Mini%20Project/app/document_processing/extractor.py):
- Deterministically identifies document types based on high-priority structural keywords:
  1. `bank_statement`: Account statement headers, account holder, balance columns, transaction tables (`ACCOUNT STATEMENT`, `SYNTHETIC APEX BANK`).
  2. `income_statement`: Business revenue declarations, drawings allowance, gross revenue share (`INCOME & REVENUE STATEMENT`, `GROSS REVENUE SHARE`).
  3. `salary_slip`: Monthly payroll slips, earnings/deductions breakdowns (`PAYSLIP FOR THE MONTH`, `NET SALARY PAYABLE`, `PROVIDENT FUND`).
  4. `loan_application`: Facility requested, requested amount, loan tenure, borrower declaration (`SYNTHETIC LOAN APPLICATION FORM`, `FACILITY REQUESTED`).
  5. `identity_proof`: Simulated citizen records, identity reference numbers (`IDENTITY VERIFICATION RECORD`, `SYNTHETIC ID REF`).
- Returns categorical type, confidence score (0.97–0.99 for clean content matches), and textual evidence. Unknown or uninformative text returns `unknown` with low confidence (< 0.50).

### 5. Field Extraction
Implemented in [app/document_processing/extractor.py](file:///Users/aditya/Desktop/Stuff/Mini%20Project/app/document_processing/extractor.py):
- **Loan Application**: Applicant ID, Full Name, Age, Gender, City, Dependents, Employment Type, Employer, Monthly Income, Existing EMI, Bank Balance, Monthly Expenses, Credit Score, Requested Amount, Loan Tenure, and Loan Purpose.
- **Identity Proof**: Applicant ID, Full Legal Name, Synthetic ID Ref, Age, Gender, Registered City, Verification Status, Issue Date, and Verification Agency.
- **Salary Slip**: Employee Name, Applicant ID, Employer Name, Salary Period, Designation, Total Gross Earnings, Total Deductions, and Net Salary Payable.
- **Income Statement**: Applicant Name, Applicant ID, Business Name, Statement Period, Designation, Total Gross Earnings, Total Deductions, and Net Income.
- **Bank Statement**: Account Holder Name, Account Number, Applicant ID, Statement Period, Opening Balance, Closing Balance, Salary Credits, EMI Debits, Transaction Count, and granular ledger transactions.
- Handles line wrapping, multi-line values, and OCR spacing anomalies via regex and whitespace normalization.

### 6. Confidence & Evidence Tracking
Every extracted attribute is wrapped in the [ExtractedField](file:///Users/aditya/Desktop/Stuff/Mini%20Project/app/schemas/applicant.py) Pydantic model:
- `field_name`: Canonical attribute identifier.
- `value`: Parsed and typed value (float for currency, int for scores/tenure, normalized strings for names/types).
- `confidence`: Deterministic score derived from extraction context:
  - Exact regex match on native digital PDF: `0.97`–`0.99`.
  - Exact regex match on OCR-processed image: `0.92`–`0.94`.
  - Fallback / fuzzy keyword match: `0.70`–`0.85`.
- `source_document`: File name or document type where the field was discovered.
- `page_number`: 1-indexed document page where evidence resides.
- `evidence`: Raw text excerpt or line containing the matched value.

### 7. Missing-Document Detection
Implemented in [app/document_processing/document_package.py](file:///Users/aditya/Desktop/Stuff/Mini%20Project/app/document_processing/document_package.py):
- Evaluates the applicant's profile to establish expected document sets:
  - Salaried: `loan_application`, `identity_proof`, `salary_slip`, `bank_statement`.
  - Self-Employed: `loan_application`, `identity_proof`, `income_statement`, `bank_statement`.
- Compares classified documents against expected sets.
- Genuinely missing files (e.g. `APP0016` missing bank statement, `APP0017` missing salary slip, `APP0018` missing identity proof) are populated in `documents_missing`.
- Emits `is_complete = False` when required documents are absent, without classifying omission as fraud.

---

## Evaluation Benchmark Results

Ran automated extraction benchmark script ([scripts/evaluate_extraction.py](file:///Users/aditya/Desktop/Stuff/Mini%20Project/scripts/evaluate_extraction.py)) across all 30 applicant document packages against [data/synthetic_data/ground_truth.json](file:///Users/aditya/Desktop/Stuff/Mini%20Project/data/synthetic_data/ground_truth.json):

```text
======================================================================
EVALUATION METRICS SUMMARY
======================================================================
Total Applicant Packages Evaluated : 30
Total Physical Documents Ingested : 115
Document Classification Accuracy  : 100.00% (115/115)
Missing Document Detection Accuracy: 100.00% (30/30)
Scanned PDF OCR Success Rate       : 100.00% (4/4)

Field-Level Extraction Accuracies (Loan Application):
  ✓ applicant_name            : 100.00% (30/30)
  ✓ declared_monthly_income   : 100.00% (30/30)
  ✓ declared_existing_emi     : 100.00% (30/30)
  ✓ declared_bank_balance     : 100.00% (30/30)
======================================================================
ALL DOCUMENT INTELLIGENCE EVALUATION BENCHMARKS PASSED SUCCESSFULLY!
======================================================================
```

---

## Test Suite Results

```bash
.venv/bin/pytest
```
- **Passed**: 57 tests
- **Failed**: 0 tests
- **Coverage**:
  - `tests/test_pdf_reader.py`: Digital PDF reading, scanned detection, page counting, image conversion, error handling.
  - `tests/test_ocr.py`: Scanned salary slips, scanned bank statements, PIL direct processing, invalid input guards.
  - `tests/test_extractor.py`: Currency parsing, 5 document classifications, field extractions, unknown doc handling.
  - `tests/test_document_package.py`: Normal applicant intake, scanned applicant intake, missing document cohort (`APP0016`–`APP0020`), missing directory guards.
  - `tests/test_document_agent.py`: Agent package intake, Document list processing, evidence traceability.
  - Existing test suites: Stage 1 schemas, database, config, and Stage 2 synthetic datasets & PDF generation.

---

## Code Quality Verification

- **Ruff**:
  ```bash
  .venv/bin/ruff check .
  # Output: All checks passed!
  ```
- **Black**:
  ```bash
  .venv/bin/black --check .
  # Output: All done! 50 files would be left unchanged.
  ```

---

## Limitations

1. **OCR Performance Dependency**: OCR accuracy depends on rasterization DPI (default 300 DPI) and image contrast. Extreme rotation, heavy skew, or photographic artifacts would require additional pre-processing filters (e.g. adaptive thresholding, deskewing).
2. **Deterministic Template Sensitivity**: Regular expressions are optimized for the structured layouts of the current synthetic banking and underwriting documents. Semi-structured real-world documents with divergent layouts may require adaptive key-value entity models or heuristic table detectors.
3. **Language Scope**: Configured for English language underwriting documents (`lang='eng'`). Multi-lingual documents would require localized language models.
