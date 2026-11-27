"""Document Classification and Structured Information Extraction module.

Provides:
- Multi-signal weighted document classification with ambiguity and UNKNOWN detection
- Page-aware contextual field extraction across digital, OCR, and mixed PDFs
- Domain validation distinguishing valid, unverified, invalid, missing, and ambiguous values
- Transparent heuristic extraction confidence kept separate from classification confidence
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.document_processing.pdf_reader import PageContent
from app.document_processing.security import mask_identifier
from app.document_processing.validation import (
    EXPECTED_SCHEMA_FIELDS_BY_DOC_TYPE,
    VALIDATION_AMBIGUOUS,
    VALIDATION_INVALID,
    VALIDATION_MISSING,
    VALIDATION_UNVERIFIED,
    VALIDATION_VALID,
    compute_extraction_confidence,
    validate_field_value,
)
from app.schemas.applicant import ExtractedField
from app.utils.helpers import get_logger

logger = get_logger(__name__)

SENSITIVE_MASKED_FIELDS = {"account_number", "id_ref"}


@dataclass
class ClassificationSignal:
    """Single weighted signal rule for document classification."""

    name: str
    pattern: str
    weight: float
    kind: str = "keyword"  # heading | keyword | field_pattern


@dataclass
class ClassificationResult:
    """Rich document classification outcome decoupled from field extraction confidence."""

    document_type: str
    confidence: float
    status: str  # CLASSIFIED | AMBIGUOUS | UNCLASSIFIED
    evidence: str
    signals: List[str] = field(default_factory=list)
    candidate_scores: Dict[str, float] = field(default_factory=dict)
    is_ambiguous: bool = False


_CLASSIFICATION_RULES: Dict[str, List[ClassificationSignal]] = {
    "bank_statement": [
        ClassificationSignal(
            "hdr_account_stmt", r"ACCOUNT\s+STATEMENT", 0.65, "heading"
        ),
        ClassificationSignal("hdr_bank_stmt", r"BANK\s+STATEMENT", 0.60, "heading"),
        ClassificationSignal(
            "hdr_apex_bank", r"SYNTHETIC\s+APEX\s+BANK", 0.50, "heading"
        ),
        ClassificationSignal(
            "fld_acc_holder", r"ACCOUNT\s+HOLDER\s*:", 0.35, "field_pattern"
        ),
        ClassificationSignal(
            "fld_stmt_period", r"STATEMENT\s+PERIOD\s*:", 0.35, "field_pattern"
        ),
        ClassificationSignal(
            "fld_acc_num", r"ACCOUNT\s+NUMBER\s*:", 0.35, "field_pattern"
        ),
        ClassificationSignal(
            "fld_ledger_cols",
            r"DEBIT\s*\(INR\).*?CREDIT\s*\(INR\)",
            0.45,
            "field_pattern",
        ),
        ClassificationSignal(
            "fld_open_close",
            r"(?:OPENING|CLOSING)\s+BALANCE\s*:",
            0.30,
            "field_pattern",
        ),
    ],
    "income_statement": [
        ClassificationSignal(
            "hdr_monthly_rev",
            r"MONTHLY\s+INCOME\s*&\s*REVENUE\s+STATEMENT",
            0.80,
            "heading",
        ),
        ClassificationSignal(
            "hdr_inc_rev", r"INCOME\s*&\s*REVENUE\s+STATEMENT", 0.70, "heading"
        ),
        ClassificationSignal("hdr_inc_stmt", r"INCOME\s+STATEMENT", 0.50, "heading"),
        ClassificationSignal(
            "kw_gross_rev", r"GROSS\s+REVENUE\s+SHARE", 0.55, "keyword"
        ),
        ClassificationSignal("kw_drawings", r"DRAWINGS\s+ALLOWANCE", 0.55, "keyword"),
        ClassificationSignal(
            "kw_op_alloc", r"OPERATIONAL\s+ALLOCATION", 0.45, "keyword"
        ),
        ClassificationSignal(
            "kw_ret_reserve", r"RETIREMENT\s+RESERVE", 0.45, "keyword"
        ),
        ClassificationSignal(
            "fld_gross_earn", r"TOTAL\s+GROSS\s+EARNINGS", 0.25, "field_pattern"
        ),
    ],
    "salary_slip": [
        ClassificationSignal(
            "hdr_payslip_mo", r"PAYSLIP\s+FOR\s+THE\s+MONTH", 0.75, "heading"
        ),
        ClassificationSignal("hdr_salary_slip", r"SALARY\s+SLIP", 0.60, "heading"),
        ClassificationSignal("kw_payslip", r"\bPAYSLIP\b", 0.25, "keyword"),
        ClassificationSignal(
            "kw_earnings_comp", r"EARNINGS\s+COMPONENT", 0.40, "keyword"
        ),
        ClassificationSignal(
            "kw_deductions_comp", r"DEDUCTIONS\s+COMPONENT", 0.40, "keyword"
        ),
        ClassificationSignal(
            "kw_basic_salary", r"BASIC\s+SALARY", 0.45, "field_pattern"
        ),
        ClassificationSignal(
            "kw_hra", r"HOUSE\s+RENT\s+ALLOWANCE", 0.40, "field_pattern"
        ),
        ClassificationSignal("kw_pf", r"PROVIDENT\s+FUND", 0.40, "field_pattern"),
        ClassificationSignal(
            "fld_net_sal", r"NET\s+SALARY\s+PAYABLE", 0.30, "field_pattern"
        ),
        ClassificationSignal(
            "fld_days_paid", r"DAYS\s+PAID\s*:", 0.25, "field_pattern"
        ),
    ],
    "loan_application": [
        ClassificationSignal(
            "hdr_syn_loan_app",
            r"SYNTHETIC\s+LOAN\s+APPLICATION\s+FORM",
            0.75,
            "heading",
        ),
        ClassificationSignal(
            "hdr_loan_app", r"LOAN\s+APPLICATION\s+FORM", 0.65, "heading"
        ),
        ClassificationSignal(
            "fld_facility", r"FACILITY\s+REQUESTED\s*:", 0.45, "field_pattern"
        ),
        ClassificationSignal(
            "fld_req_amt", r"REQUESTED\s+AMOUNT\s*:", 0.45, "field_pattern"
        ),
        ClassificationSignal(
            "fld_req_ten", r"REQUESTED\s+TENURE\s*:", 0.45, "field_pattern"
        ),
        ClassificationSignal(
            "fld_decl_inc", r"DECLARED\s+MONTHLY\s+INCOME", 0.35, "field_pattern"
        ),
        ClassificationSignal(
            "fld_credit_sc", r"SELF-REPORTED\s+CREDIT\s+SCORE", 0.35, "field_pattern"
        ),
        ClassificationSignal(
            "fld_est_emi", r"ESTIMATED\s+MONTHLY\s+EMI", 0.35, "field_pattern"
        ),
    ],
    "identity_proof": [
        ClassificationSignal(
            "hdr_id_rec", r"IDENTITY\s+VERIFICATION\s+RECORD", 0.75, "heading"
        ),
        ClassificationSignal(
            "hdr_citizen", r"SIMULATED\s+CITIZEN\s+RECORD", 0.65, "heading"
        ),
        ClassificationSignal(
            "hdr_id_card", r"IDENTITY\s+(?:PROOF|DOCUMENT|CARD)", 0.50, "heading"
        ),
        ClassificationSignal(
            "fld_id_ref", r"SYNTHETIC\s+ID\s+REF\s*:", 0.50, "field_pattern"
        ),
        ClassificationSignal(
            "fld_legal_name", r"FULL\s+LEGAL\s+NAME\s*:", 0.40, "field_pattern"
        ),
        ClassificationSignal(
            "fld_reg_city", r"REGISTERED\s+CITY\s*:", 0.35, "field_pattern"
        ),
        ClassificationSignal(
            "fld_ver_agency", r"VERIFICATION\s+AGENCY\s*:", 0.40, "field_pattern"
        ),
    ],
    "address_proof": [
        ClassificationSignal(
            "hdr_addr_proof",
            r"(?:PROOF\s+OF\s+ADDRESS|ADDRESS\s+VERIFICATION|RESIDENCE\s+CERTIFICATE|UTILITY\s+BILL)",
            0.70,
            "heading",
        ),
        ClassificationSignal(
            "fld_res_addr",
            r"(?:RESIDENTIAL|PERMANENT|CURRENT)\s+ADDRESS\s*:",
            0.45,
            "field_pattern",
        ),
        ClassificationSignal(
            "fld_pin", r"(?:PIN|POSTAL)\s+CODE\s*:", 0.40, "field_pattern"
        ),
        ClassificationSignal(
            "fld_meter",
            r"(?:CONSUMER|METER)\s+(?:ID|NO|NUMBER)\s*:",
            0.35,
            "field_pattern",
        ),
        ClassificationSignal(
            "fld_bill_period", r"BILLING\s+PERIOD\s*:", 0.35, "field_pattern"
        ),
    ],
    "employment_proof": [
        ClassificationSignal(
            "hdr_emp_proof",
            r"(?:EMPLOYMENT\s+VERIFICATION|CERTIFICATE\s+OF\s+EMPLOYMENT|EXPERIENCE\s+CERTIFICATE|BONAFIDE\s+EMPLOYMENT)",
            0.70,
            "heading",
        ),
        ClassificationSignal(
            "fld_doj",
            r"(?:DATE\s+OF\s+JOINING|EMPLOYMENT\s+START\s+DATE)\s*:",
            0.45,
            "field_pattern",
        ),
        ClassificationSignal(
            "fld_emp_code", r"EMPLOYEE\s+(?:ID|CODE)\s*:", 0.35, "field_pattern"
        ),
        ClassificationSignal(
            "kw_hr_dept", r"(?:HUMAN\s+RESOURCES|HR\s+DEPARTMENT)", 0.35, "keyword"
        ),
        ClassificationSignal(
            "fld_designation", r"DESIGNATION\s*:", 0.25, "field_pattern"
        ),
    ],
}

_FILENAME_TYPE_HINTS = {
    "bank_statement": "bank_statement",
    "salary_slip": "salary_slip",
    "payslip": "salary_slip",
    "income_statement": "income_statement",
    "loan_application": "loan_application",
    "loan_app": "loan_application",
    "identity_proof": "identity_proof",
    "id_proof": "identity_proof",
    "address_proof": "address_proof",
    "employment_proof": "employment_proof",
}


def parse_currency(value_str: Optional[str]) -> Optional[float]:
    """Parse monetary strings (including negative numbers, currency symbols, commas)."""
    if not value_str:
        return None
    s = re.sub(r"^(?:INR|RS\.?|₹|\$)\s*", "", value_str.strip(), flags=re.IGNORECASE)
    # Match optional sign attached to a digit so lone '-' placeholders return None
    m = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", s)
    if not m:
        return None
    cleaned = m.group(0).replace(",", "")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def clean_label_value(value: str, stop_keywords: Optional[List[str]] = None) -> str:
    """Trim stop keywords and trailing separators from extracted label values."""
    if not value:
        return ""
    v = value
    if stop_keywords:
        for kw in stop_keywords:
            pattern = re.compile(re.escape(kw), re.IGNORECASE)
            match = pattern.search(v)
            if match:
                v = v[: match.start()]
    return v.strip(" :-\t\r\n")


def find_label_value(
    text: str,
    label_patterns: List[str],
    stop_keywords: Optional[List[str]] = None,
) -> Tuple[Optional[str], str, str]:
    """Search for inline ('Label: Val') or multiline ('Label:\\nVal') values.

    Returns:
        Tuple of (extracted_value, evidence_excerpt, label_specificity).
    """
    for pat in label_patterns:
        m_inline = re.search(pat + r"[:\s]+([^\n]+)", text, re.IGNORECASE)
        if m_inline:
            candidate = clean_label_value(m_inline.group(1), stop_keywords)
            if candidate:
                return candidate, m_inline.group(0).strip(), "exact_label"

        m_multiline = re.search(pat + r"[:\s]*\n\s*([^\n]+)", text, re.IGNORECASE)
        if m_multiline:
            candidate = clean_label_value(m_multiline.group(1), stop_keywords)
            if candidate:
                ev = f"{m_multiline.group(0).strip().replace(chr(10), ' ')}"
                return candidate, ev, "multiline_label"

    return None, "", "weak_context"


def _compute_text_quality(text: str) -> float:
    """Estimate normalized text readability quality in [0.4, 1.0]."""
    stripped = text.strip()
    if not stripped:
        return 0.4
    alnum = sum(1 for c in stripped if c.isalnum())
    ratio = alnum / max(len(stripped), 1)
    # Typical clean English financial text has ~65-80% alphanumeric characters
    return round(min(max(0.4 + ratio * 0.75, 0.4), 1.0), 3)


class _FieldCollector:
    """Tracks usable validated fields alongside full validation/conflict diagnostics."""

    def __init__(
        self,
        src: str,
        default_page: int,
        is_scanned: bool,
        text_quality: float,
    ) -> None:
        self.src = src
        self.default_page = default_page
        self.is_scanned = is_scanned
        self.text_quality = text_quality
        self.usable: Dict[str, ExtractedField] = {}
        self.validations: Dict[str, Dict[str, Any]] = {}
        self._candidates_by_field: Dict[str, List[Tuple[Any, str]]] = {}

    def record(
        self,
        field_name: str,
        raw_value: Any,
        evidence: str,
        *,
        page_number: Optional[int] = None,
        extraction_method: Optional[str] = None,
        label_specificity: str = "exact_label",
        aliases: Sequence[str] = (),
        allow_multipage_update: bool = False,
    ) -> None:
        page_num = page_number or self.default_page
        method = extraction_method or (
            "regex_ocr" if self.is_scanned else "regex_digital"
        )
        masked = (
            mask_identifier(str(raw_value))
            if field_name in SENSITIVE_MASKED_FIELDS and raw_value is not None
            else None
        )

        # Preliminary heuristic confidence before validation status clamping
        prelim_conf = compute_extraction_confidence(
            extraction_method=method,
            label_specificity=label_specificity,
            text_quality=self.text_quality,
            validation_status=VALIDATION_VALID,
        )
        status, sanitized, val_msg = validate_field_value(
            field_name, raw_value, contextual_confidence=prelim_conf
        )
        final_conf = compute_extraction_confidence(
            extraction_method=method,
            label_specificity=label_specificity,
            text_quality=self.text_quality,
            validation_status=status,
        )

        # Track conflicting distinct valid candidates on multi-page scans for ambiguity
        if not allow_multipage_update and status in (
            VALIDATION_VALID,
            VALIDATION_UNVERIFIED,
        ):
            prev = self._candidates_by_field.get(field_name, [])
            if prev and all(p_val != sanitized for p_val, _ in prev):
                # Distinct conflicting values for same field across pages/matches
                status = VALIDATION_AMBIGUOUS
                final_conf = compute_extraction_confidence(
                    extraction_method=method,
                    label_specificity=label_specificity,
                    text_quality=self.text_quality,
                    validation_status=VALIDATION_AMBIGUOUS,
                )
                prev.append((sanitized, evidence))
                self.validations[field_name] = {
                    "field_name": field_name,
                    "validation_status": VALIDATION_AMBIGUOUS,
                    "raw_value": [v for v, _ in prev],
                    "value": None,
                    "confidence": final_conf,
                    "source_document": self.src,
                    "page_number": page_num,
                    "extraction_method": method,
                    "evidence": evidence,
                    "validation_message": f"Conflicting values detected for '{field_name}': {[v for v, _ in prev]}",
                }
                self.usable.pop(field_name, None)
                for alias in aliases:
                    self.usable.pop(alias, None)
                    self.validations[alias] = dict(self.validations[field_name])
                    self.validations[alias]["field_name"] = alias
                return
            self._candidates_by_field.setdefault(field_name, []).append(
                (sanitized, evidence)
            )

        diag_entry = {
            "field_name": field_name,
            "validation_status": status,
            "raw_value": raw_value,
            "value": sanitized,
            "confidence": final_conf,
            "source_document": self.src,
            "page_number": page_num,
            "extraction_method": method,
            "evidence": (
                masked or evidence
                if field_name in SENSITIVE_MASKED_FIELDS
                else evidence
            ),
            "validation_message": val_msg,
            "masked_value": masked,
        }
        self.validations[field_name] = diag_entry

        if status == VALIDATION_INVALID:
            # Invalid values are explicitly rejected and excluded from usable fields
            return

        if sanitized is not None:
            ef = ExtractedField(
                field_name=field_name,
                value=sanitized,
                confidence=final_conf,
                source_document=self.src,
                page_number=page_num,
                evidence=evidence,
                extraction_method=method,
                validation_status=status,
                validation_message=val_msg,
                masked_value=masked,
            )
            self.usable[field_name] = ef
            for alias in aliases:
                alias_ef = ef.model_copy(update={"field_name": alias})
                self.usable[alias] = alias_ef
                alias_diag = dict(diag_entry)
                alias_diag["field_name"] = alias
                self.validations[alias] = alias_diag

    def finalize_missing(self, document_type: str) -> None:
        """Populate explicit 'missing' entries for absent expected schema fields."""
        expected = EXPECTED_SCHEMA_FIELDS_BY_DOC_TYPE.get(document_type, [])
        for fname in expected:
            if fname not in self.validations:
                self.validations[fname] = {
                    "field_name": fname,
                    "validation_status": VALIDATION_MISSING,
                    "raw_value": None,
                    "value": None,
                    "confidence": 0.0,
                    "source_document": self.src,
                    "page_number": self.default_page,
                    "extraction_method": "none",
                    "evidence": "",
                    "validation_message": f"Expected field '{fname}' not found in {document_type}",
                    "masked_value": None,
                }


class DocumentExtractor:
    """Multi-signal classifier and page-aware validated key-value extractor."""

    def __init__(self) -> None:
        logger.info("DocumentExtractor initialized.")

    # -------------------------------------------------------------------------
    # Multi-Signal Document Classification
    # -------------------------------------------------------------------------

    def classify_document_detailed(
        self, raw_text: str, filename: str = ""
    ) -> ClassificationResult:
        """Score all supported document types using multi-signal structural evidence.

        Never relies on a single generic keyword alone, surfaces ambiguous matches,
        and preserves 'unknown' (UNCLASSIFIED) when evidence is weak or conflicting.
        """
        upper_text = (raw_text or "").upper()
        scores: Dict[str, float] = {}
        matched_signals: Dict[str, List[str]] = {}
        signal_kinds: Dict[str, set[str]] = {}

        for doc_type, rules in _CLASSIFICATION_RULES.items():
            total = 0.0
            hits: List[str] = []
            kinds: set[str] = set()
            best_heading: Optional[ClassificationSignal] = None
            for rule in rules:
                if re.search(rule.pattern, upper_text, re.DOTALL):
                    if rule.kind == "heading":
                        if best_heading is None or rule.weight > best_heading.weight:
                            best_heading = rule
                    else:
                        total += rule.weight
                        hits.append(f"{rule.name}({rule.weight:.2f})")
                        kinds.add(rule.kind)
            if best_heading is not None:
                total += best_heading.weight
                hits.insert(0, f"{best_heading.name}({best_heading.weight:.2f})")
                kinds.add("heading")
            scores[doc_type] = round(total, 4)
            matched_signals[doc_type] = hits
            signal_kinds[doc_type] = kinds

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_type, top_score = ranked[0]
        second_type, second_score = ranked[1] if len(ranked) > 1 else ("unknown", 0.0)
        top_hits = matched_signals.get(top_type, [])

        # Require >= 2 independent signals and minimum cumulative score (>= 0.85)
        strong_enough = top_score >= 0.85 and len(top_hits) >= 2

        if strong_enough:
            # Disambiguate cases where two types are both strongly triggered with tight margin
            # or carry competing primary document headings with field support
            margin = top_score - second_score
            competing_headings = (
                "heading" in signal_kinds.get(top_type, set())
                and "heading" in signal_kinds.get(second_type, set())
                and second_score >= max(0.90, 0.50 * top_score)
                and len(matched_signals.get(second_type, [])) >= 2
            )
            is_close_conflict = (
                second_score >= 0.85
                and len(matched_signals.get(second_type, [])) >= 2
                and ((margin / max(top_score, 1e-6)) < 0.25 or competing_headings)
            )
            if is_close_conflict:
                conf = round(min(0.48, 0.35 + margin * 0.5), 3)
                ev = (
                    f"Ambiguous classification between '{top_type}' ({top_score:.2f}) "
                    f"and '{second_type}' ({second_score:.2f}); manual classification advised"
                )
                return ClassificationResult(
                    document_type="unknown",
                    confidence=conf,
                    status="AMBIGUOUS",
                    evidence=ev,
                    signals=top_hits + matched_signals.get(second_type, []),
                    candidate_scores=scores,
                    is_ambiguous=True,
                )

            # Heuristic classification confidence scaled smoothly by score & separation
            separation = max(top_score - second_score, 0.0)
            conf = min(
                0.75 + 0.10 * min(top_score, 2.0) + 0.05 * min(separation, 1.0), 0.98
            )
            conf = round(conf, 3)
            ev = (
                f"Matched {len(top_hits)} signals for {top_type} "
                f"(score={top_score:.2f}, margin={separation:.2f}): {', '.join(top_hits[:5])}"
            )
            return ClassificationResult(
                document_type=top_type,
                confidence=conf,
                status="CLASSIFIED",
                evidence=ev,
                signals=top_hits,
                candidate_scores=scores,
                is_ambiguous=False,
            )

        # Single weak signal cannot force classification on non-trivial unrelated text
        # Filename hint is used only if document type aligns with weak keyword corroboration
        fn_lower = os.path.basename(filename).lower() if filename else ""
        fn_hint: Optional[str] = None
        for key, mapped_type in _FILENAME_TYPE_HINTS.items():
            if key in fn_lower:
                fn_hint = mapped_type
                break

        if (
            fn_hint
            and len(matched_signals.get(fn_hint, [])) >= 1
            and top_type == fn_hint
        ):
            hint_score = scores.get(fn_hint, 0.0)
            conf = round(min(0.45 + 0.20 * hint_score, 0.62), 3)
            return ClassificationResult(
                document_type=fn_hint,
                confidence=conf,
                status="CLASSIFIED",
                evidence=(
                    f"Weak classification corroborated by filename '{os.path.basename(filename)}' "
                    f"and signal {matched_signals[fn_hint]}"
                ),
                signals=matched_signals[fn_hint] + [f"filename:{fn_hint}"],
                candidate_scores=scores,
                is_ambiguous=False,
            )

        reason = (
            f"Insufficient classification signals (top={top_type}:{top_score:.2f}, "
            f"hits={len(top_hits)})"
            if top_score > 0
            else "No recognized document markers found"
        )
        return ClassificationResult(
            document_type="unknown",
            confidence=round(min(0.40, 0.15 + 0.25 * top_score), 3),
            status="UNCLASSIFIED",
            evidence=reason,
            signals=top_hits,
            candidate_scores=scores,
            is_ambiguous=False,
        )

    def classify_document(
        self, raw_text: str, filename: str = ""
    ) -> Tuple[str, float, str]:
        """Classify document type returning backward-compatible (type, confidence, evidence)."""
        res = self.classify_document_detailed(raw_text, filename=filename)
        return res.document_type, res.confidence, res.evidence

    # -------------------------------------------------------------------------
    # Structured Field Extraction (Single Text or Multi-Page Aware)
    # -------------------------------------------------------------------------

    def extract_fields_with_diagnostics(
        self,
        raw_text: str,
        document_type: str,
        filename: str = "",
        is_scanned: bool = False,
        pages: Optional[Sequence[PageContent]] = None,
    ) -> Tuple[Dict[str, ExtractedField], Dict[str, Dict[str, Any]]]:
        """Extract validated fields with per-page provenance and complete validation statuses."""
        src = filename or document_type
        doc_pages: List[PageContent] = (
            list(pages)
            if pages
            else [
                PageContent(
                    page_number=1,
                    text=raw_text or "",
                    char_count=len((raw_text or "").strip()),
                    is_scanned=is_scanned,
                    has_images=is_scanned,
                    extraction_method="ocr" if is_scanned else "native_text",
                )
            ]
        )

        # Merge collector across pages so page-level provenance & cross-page conflicts persist
        overall_text = "\n".join(p.text for p in doc_pages if p.text).strip() or (
            raw_text or ""
        )
        collector = _FieldCollector(
            src=src,
            default_page=1,
            is_scanned=is_scanned,
            text_quality=_compute_text_quality(overall_text),
        )

        for page in doc_pages:
            page_text = page.text or ""
            if not page_text.strip():
                continue
            page_scanned = is_scanned or page.extraction_method == "ocr"
            collector.text_quality = _compute_text_quality(page_text)
            collector.is_scanned = page_scanned
            self._dispatch_page_extraction(
                collector=collector,
                text=page_text,
                document_type=document_type,
                page_number=page.page_number,
                page_scanned=page_scanned,
            )

        collector.finalize_missing(document_type)
        return collector.usable, collector.validations

    def extract_fields(
        self,
        raw_text: str,
        document_type: str,
        filename: str = "",
        is_scanned: bool = False,
        pages: Optional[Sequence[PageContent]] = None,
    ) -> Dict[str, ExtractedField]:
        """Extract usable validated structured fields preserving backward compatibility."""
        usable, _ = self.extract_fields_with_diagnostics(
            raw_text=raw_text,
            document_type=document_type,
            filename=filename,
            is_scanned=is_scanned,
            pages=pages,
        )
        return usable

    def _dispatch_page_extraction(
        self,
        collector: _FieldCollector,
        text: str,
        document_type: str,
        page_number: int,
        page_scanned: bool,
    ) -> None:
        method = "regex_ocr" if page_scanned else "regex_digital"
        if document_type == "loan_application":
            self._extract_loan_application(collector, text, page_number, method)
        elif document_type in ("identity_proof", "identity_verification"):
            self._extract_identity_proof(collector, text, page_number, method)
        elif document_type == "address_proof":
            self._extract_address_proof(collector, text, page_number, method)
        elif document_type == "salary_slip":
            self._extract_salary_slip(collector, text, page_number, method)
        elif document_type == "income_statement":
            self._extract_income_statement(collector, text, page_number, method)
        elif document_type == "employment_proof":
            self._extract_employment_proof(collector, text, page_number, method)
        elif document_type == "bank_statement":
            self._extract_bank_statement(
                collector, text, page_number, method, page_scanned
            )
        else:
            self._extract_generic(collector, text, page_number)

    # -------------------------------------------------------------------------
    # Document Specific Extractors
    # -------------------------------------------------------------------------

    def _extract_loan_application(
        self, collector: _FieldCollector, text: str, page_num: int, method: str
    ) -> None:
        m_id = re.search(r"Applicant ID[:\s]+(APP\d{4})", text, re.IGNORECASE)
        if not m_id:
            m_id = re.search(r"APP-REQ-(APP\d{4})-", text)
        if m_id:
            collector.record(
                "applicant_id",
                m_id.group(1).upper(),
                m_id.group(0).strip(),
                page_number=page_num,
                extraction_method=method,
            )

        val, ev, spec = find_label_value(
            text, [r"Full Name", r"Applicant Name"], ["Gender", "Age", "City"]
        )
        if val:
            collector.record(
                "applicant_name",
                val,
                ev,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec,
            )

        # Submission Date & Facility
        val_sub, ev_sub, spec_sub = find_label_value(
            text, [r"Submission Date"], ["Applicant ID", "Facility Requested"]
        )
        if val_sub:
            collector.record(
                "submission_date",
                val_sub,
                ev_sub,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_sub,
            )

        val_fac, ev_fac, spec_fac = find_label_value(
            text, [r"Facility Requested"], ["1. Personal", "Full Name"]
        )
        if val_fac:
            collector.record(
                "facility_requested",
                val_fac,
                ev_fac,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_fac,
            )

        # Gender / Age (strict contextual label only; never match bare 'N Years' tenure)
        m_ag = re.search(
            r"Gender\s*/\s*Age[:\s]+(Male|Female|Other)\s*/\s*(-?\d+)\s*Years?",
            text,
            re.IGNORECASE,
        )
        if m_ag:
            collector.record(
                "gender",
                m_ag.group(1).capitalize(),
                m_ag.group(0).strip(),
                page_number=page_num,
                extraction_method=method,
            )
            collector.record(
                "age",
                int(m_ag.group(2)),
                m_ag.group(0).strip(),
                page_number=page_num,
                extraction_method=method,
            )
        else:
            m_age_lbl = re.search(
                r"(?:Applicant\s+)?Age[:\s]+(-?\d+)\s*(?:Years?)?", text, re.IGNORECASE
            )
            if m_age_lbl:
                collector.record(
                    "age",
                    int(m_age_lbl.group(1)),
                    m_age_lbl.group(0).strip(),
                    page_number=page_num,
                    extraction_method=method,
                )

        # Number of Dependents
        val_dep, ev_dep, spec_dep = find_label_value(
            text,
            [r"Number of[\s\n]+Dependents", r"Dependents"],
            ["2. Employment", "Employment Type"],
        )
        if val_dep:
            m_dep = re.search(r"-?\d+", val_dep)
            if m_dep:
                collector.record(
                    "number_of_dependents",
                    int(m_dep.group(0)),
                    ev_dep,
                    page_number=page_num,
                    extraction_method=method,
                    label_specificity=spec_dep,
                )

        # Employment Type
        val, ev, spec = find_label_value(
            text,
            [r"Employment Type"],
            ["Employer", "Business", "Experience", "Tenure"],
        )
        if val:
            val_norm = val.title()
            if "Salaried" in val_norm:
                val_norm = "Salaried"
            elif "Self-Employed" in val_norm or "Self Employed" in val_norm:
                val_norm = "Self-Employed"
            elif "Business" in val_norm:
                val_norm = "Business Owner"
            collector.record(
                "employment_type",
                val_norm,
                ev,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec,
            )

        # Employer / Business Name
        val, ev, spec = find_label_value(
            text,
            [r"Employer\s*/\s*Business", r"Employer Name", r"Business Name"],
            ["Experience", "Tenure", "Declared Monthly", "Income"],
        )
        if val:
            collector.record(
                "employer_name",
                val,
                ev,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec,
            )

        # Experience / Employment Years
        val_exp, ev_exp, spec_exp = find_label_value(
            text,
            [r"Experience\s*/[\s\n]*Tenure", r"Employment Years", r"Work Experience"],
            ["Declared Monthly", "Monthly Income"],
        )
        if val_exp:
            m_exp = re.search(r"-?\d+(?:\.\d+)?", val_exp)
            if m_exp:
                collector.record(
                    "employment_years",
                    float(m_exp.group(0)),
                    ev_exp,
                    page_number=page_num,
                    extraction_method=method,
                    label_specificity=spec_exp,
                )

        # Monetary & application parameters helper
        self._extract_monetary_field(
            collector,
            text,
            field_name="monthly_income",
            aliases=("declared_monthly_income",),
            multiline_pattern=r"Declared Monthly[\s\n]+Income:?[\s\n]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)",
            inline_labels=[r"Declared Monthly Income", r"Monthly Income"],
            stop_keywords=["Existing Monthly", "EMI", "Declared Bank"],
            page_num=page_num,
            method=method,
        )
        self._extract_monetary_field(
            collector,
            text,
            field_name="existing_emi",
            aliases=("declared_existing_emi",),
            multiline_pattern=r"Existing Monthly[\s\n]+EMI:?[\s\n]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)",
            inline_labels=[r"Existing Monthly EMI", r"Existing EMI"],
            stop_keywords=["Declared Bank Balance", "Monthly Expenses"],
            page_num=page_num,
            method=method,
        )
        self._extract_monetary_field(
            collector,
            text,
            field_name="bank_balance",
            aliases=("declared_bank_balance",),
            multiline_pattern=r"Declared Bank[\s\n]+Balance:?[\s\n]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)",
            inline_labels=[r"Declared Bank Balance", r"Bank Balance"],
            stop_keywords=["Monthly Expenses", "Self-Reported"],
            page_num=page_num,
            method=method,
        )
        self._extract_monetary_field(
            collector,
            text,
            field_name="monthly_expenses",
            aliases=(),
            multiline_pattern=r"Monthly[\s\n]+Expenses:?[\s\n]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)",
            inline_labels=[r"Monthly Expenses"],
            stop_keywords=["Self-Reported Credit", "Credit Score", "3. Loan"],
            page_num=page_num,
            method=method,
        )

        # Credit Score
        m_cs = re.search(
            r"(?:Self-Reported Credit[\s\n]*Score|Credit Score)[:\s]+(-?\d{2,4})",
            text,
            re.IGNORECASE,
        )
        if m_cs:
            collector.record(
                "credit_score",
                int(m_cs.group(1)),
                m_cs.group(0).strip().replace("\n", " "),
                page_number=page_num,
                extraction_method=method,
            )

        # Requested Loan Amount & Tenure & Estimated EMI
        self._extract_monetary_field(
            collector,
            text,
            field_name="loan_amount",
            aliases=(),
            multiline_pattern=r"Requested Amount:?[\s\n]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)",
            inline_labels=[r"Requested Amount", r"Loan Amount"],
            stop_keywords=["Requested Tenure", "Estimated Monthly"],
            page_num=page_num,
            method=method,
        )

        m_lt = re.search(
            r"(?:Requested Tenure|Loan Tenure)[:\s]+(-?\d+)\s*Months?",
            text,
            re.IGNORECASE,
        )
        if m_lt:
            collector.record(
                "loan_tenure",
                int(m_lt.group(1)),
                m_lt.group(0).strip(),
                page_number=page_num,
                extraction_method=method,
            )

        self._extract_monetary_field(
            collector,
            text,
            field_name="estimated_new_emi",
            aliases=(),
            multiline_pattern=r"Estimated Monthly[\s\n]+EMI:?[\s\n]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)",
            inline_labels=[r"Estimated Monthly EMI"],
            stop_keywords=["Loan Purpose", "approx"],
            page_num=page_num,
            method=method,
        )

        val_city, ev_city, spec_city = find_label_value(
            text, [r"City of Residence", r"City"], ["Number of Dependents"]
        )
        if val_city:
            collector.record(
                "city",
                val_city,
                ev_city,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_city,
            )

        val_purp, ev_purp, spec_purp = find_label_value(
            text, [r"Loan Purpose"], ["I hereby declare", "Applicant Signature"]
        )
        if val_purp:
            collector.record(
                "loan_purpose",
                val_purp,
                ev_purp,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_purp,
            )

    def _extract_monetary_field(
        self,
        collector: _FieldCollector,
        text: str,
        *,
        field_name: str,
        aliases: Sequence[str],
        multiline_pattern: str,
        inline_labels: List[str],
        stop_keywords: List[str],
        page_num: int,
        method: str,
    ) -> None:
        m = re.search(multiline_pattern, text, re.IGNORECASE)
        if m:
            num_val = parse_currency(m.group(1))
            if num_val is not None:
                spec = "multiline_label" if "\n" in m.group(0) else "exact_label"
                collector.record(
                    field_name,
                    num_val,
                    m.group(0).strip().replace("\n", " "),
                    page_number=page_num,
                    extraction_method=method,
                    label_specificity=spec,
                    aliases=aliases,
                )
                return

        val, ev, spec = find_label_value(text, inline_labels, stop_keywords)
        num_val = parse_currency(val)
        if num_val is not None:
            collector.record(
                field_name,
                num_val,
                ev,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec,
                aliases=aliases,
            )

    def _extract_identity_proof(
        self, collector: _FieldCollector, text: str, page_num: int, method: str
    ) -> None:
        m_id = re.search(r"Applicant ID[:\s]+(APP\d{4})", text, re.IGNORECASE)
        if not m_id:
            m_id = re.search(r"SYN-ID-(APP\d{4})-", text)
        if m_id:
            collector.record(
                "applicant_id",
                m_id.group(1).upper(),
                m_id.group(0).strip(),
                page_number=page_num,
                extraction_method=method,
            )

        val, ev, spec = find_label_value(
            text,
            [r"Full Legal Name", r"Legal Name", r"Full Name"],
            ["Age / Gender", "Registered City", "Status", "Date of Birth"],
        )
        if val:
            collector.record(
                "applicant_name",
                val,
                ev,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec,
            )

        val_ref, ev_ref, spec_ref = find_label_value(
            text, [r"Synthetic ID Ref", r"ID Ref"], ["Applicant ID"]
        )
        if val_ref:
            collector.record(
                "id_ref",
                val_ref,
                ev_ref,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_ref,
            )

        m_ag = re.search(
            r"Age\s*/\s*Gender[:\s]+(-?\d+)\s*Years?\s*/\s*(Male|Female|Other)",
            text,
            re.IGNORECASE,
        )
        if m_ag:
            collector.record(
                "age",
                int(m_ag.group(1)),
                m_ag.group(0).strip(),
                page_number=page_num,
                extraction_method=method,
            )
            collector.record(
                "gender",
                m_ag.group(2).capitalize(),
                m_ag.group(0).strip(),
                page_number=page_num,
                extraction_method=method,
            )

        val_dob, ev_dob, spec_dob = find_label_value(
            text,
            [r"Date of Birth", r"\bDOB\b"],
            ["Registered City", "Address", "Status"],
        )
        if val_dob:
            collector.record(
                "dob",
                val_dob,
                ev_dob,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_dob,
            )

        val_city, ev_city, spec_city = find_label_value(
            text, [r"Registered City", r"City"], ["Status", "Issue Date"]
        )
        if val_city:
            collector.record(
                "registered_city",
                val_city,
                ev_city,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_city,
            )

        val_addr, ev_addr, spec_addr = find_label_value(
            text,
            [r"Residential Address", r"Permanent Address", r"Address"],
            ["Status", "Issue Date"],
        )
        if val_addr:
            collector.record(
                "address",
                val_addr,
                ev_addr,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_addr,
            )

        val_issue, ev_issue, spec_issue = find_label_value(
            text, [r"Issue Date"], ["Verification Agency", "Security Hash"]
        )
        if val_issue:
            collector.record(
                "issue_date",
                val_issue,
                ev_issue,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_issue,
            )

        val_st, ev_st, spec_st = find_label_value(
            text, [r"Status"], ["Issue Date", "Verification Agency"]
        )
        if val_st:
            collector.record(
                "status",
                val_st,
                ev_st,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_st,
            )

    def _extract_address_proof(
        self, collector: _FieldCollector, text: str, page_num: int, method: str
    ) -> None:
        m_id = re.search(r"Applicant ID[:\s]+(APP\d{4})", text, re.IGNORECASE)
        if m_id:
            collector.record(
                "applicant_id",
                m_id.group(1).upper(),
                m_id.group(0).strip(),
                page_number=page_num,
                extraction_method=method,
            )

        val_name, ev_name, spec_name = find_label_value(
            text,
            [r"Full Name", r"Applicant Name", r"Account Holder", r"Consumer Name"],
            ["Address", "City", "PIN", "Period"],
        )
        if val_name:
            collector.record(
                "applicant_name",
                val_name,
                ev_name,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_name,
            )

        val_addr, ev_addr, spec_addr = find_label_value(
            text,
            [
                r"Residential Address",
                r"Permanent Address",
                r"Current Address",
                r"Address",
            ],
            ["Issue Date", "Billing Period", "PIN Code"],
        )
        if val_addr:
            collector.record(
                "address",
                val_addr,
                ev_addr,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_addr,
            )

        val_issue, ev_issue, spec_issue = find_label_value(
            text, [r"Issue Date", r"Bill Date"], ["Billing Period", "Due Date"]
        )
        if val_issue:
            collector.record(
                "issue_date",
                val_issue,
                ev_issue,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_issue,
            )

    def _extract_salary_slip(
        self, collector: _FieldCollector, text: str, page_num: int, method: str
    ) -> None:
        val, ev, spec = find_label_value(
            text, [r"Name"], ["Period", "Identifier", "City", "Designation"]
        )
        if val:
            collector.record(
                "employee_name",
                val,
                ev,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec,
            )

        m_id = re.search(r"Identifier[:\s]+(?:EMP-)?(APP\d{4})", text, re.IGNORECASE)
        if m_id:
            collector.record(
                "applicant_id",
                m_id.group(1).upper(),
                m_id.group(0).strip(),
                page_number=page_num,
                extraction_method=method,
            )

        # Employer Name: explicit label OR line immediately preceding PAYSLIP header
        val_emp, ev_emp, spec_emp = find_label_value(
            text,
            [r"Employer Name", r"Organization", r"Company Name"],
            ["Period", "Name"],
        )
        if val_emp:
            collector.record(
                "employer_name",
                val_emp,
                ev_emp,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_emp,
            )
        else:
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            for idx, line in enumerate(lines[:10]):
                if (
                    "PAYSLIP FOR THE MONTH" in line.upper()
                    or "MONTHLY INCOME" in line.upper()
                ):
                    if idx > 0 and "SYNTHETIC DOCUMENT" not in lines[idx - 1].upper():
                        collector.record(
                            "employer_name",
                            lines[idx - 1],
                            lines[idx - 1],
                            page_number=page_num,
                            extraction_method="header_positional",
                            label_specificity="positional",
                        )
                    break

        val_des, ev_des, spec_des = find_label_value(
            text, [r"Designation"], ["Days Paid", "Earnings Component"]
        )
        if val_des:
            collector.record(
                "designation",
                val_des,
                ev_des,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_des,
            )

        m_days = re.search(r"Days Paid[:\s]+(-?\d+)", text, re.IGNORECASE)
        if m_days:
            collector.record(
                "days_paid",
                int(m_days.group(1)),
                m_days.group(0).strip(),
                page_number=page_num,
                extraction_method=method,
            )

        # Income & deduction monetary components
        for fname, pat in [
            ("net_salary", r"NET SALARY PAYABLE[:\s]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)"),
            (
                "gross_earnings",
                r"Total Gross Earnings[:\s]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)",
            ),
            (
                "total_deductions",
                r"Total Deductions[:\s]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)",
            ),
            ("basic_salary", r"Basic Salary[:\s]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)"),
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                parsed = parse_currency(m.group(1))
                if parsed is not None:
                    collector.record(
                        fname,
                        parsed,
                        m.group(0).strip().replace("\n", " "),
                        page_number=page_num,
                        extraction_method=method,
                    )

        val_per, ev_per, spec_per = find_label_value(
            text, [r"Period"], ["Identifier", "City", "Designation"]
        )
        if val_per:
            collector.record(
                "salary_period",
                val_per,
                ev_per,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_per,
            )

    def _extract_income_statement(
        self, collector: _FieldCollector, text: str, page_num: int, method: str
    ) -> None:
        val, ev, spec = find_label_value(
            text, [r"Name"], ["Period", "Identifier", "City", "Designation"]
        )
        if val:
            collector.record(
                "applicant_name",
                val,
                ev,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec,
            )

        m_id = re.search(r"Identifier[:\s]+(?:EMP-)?(APP\d{4})", text, re.IGNORECASE)
        if m_id:
            collector.record(
                "applicant_id",
                m_id.group(1).upper(),
                m_id.group(0).strip(),
                page_number=page_num,
                extraction_method=method,
            )

        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        for idx, line in enumerate(lines[:10]):
            if "MONTHLY INCOME & REVENUE STATEMENT" in line.upper():
                if idx > 0 and "SYNTHETIC DOCUMENT" not in lines[idx - 1].upper():
                    collector.record(
                        "business_name",
                        lines[idx - 1],
                        lines[idx - 1],
                        page_number=page_num,
                        extraction_method="header_positional",
                        label_specificity="positional",
                    )
                break

        val_des, ev_des, spec_des = find_label_value(
            text, [r"Designation"], ["Days Paid", "Earnings Component"]
        )
        if val_des:
            collector.record(
                "designation",
                val_des,
                ev_des,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_des,
            )

        for fname, pat in [
            (
                "net_income",
                r"NET (?:SALARY PAYABLE|INCOME|REVENUE)[:\s]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)",
            ),
            (
                "gross_earnings",
                r"Total Gross Earnings[:\s]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)",
            ),
            (
                "total_deductions",
                r"Total Deductions[:\s]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)",
            ),
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                parsed = parse_currency(m.group(1))
                if parsed is not None:
                    collector.record(
                        fname,
                        parsed,
                        m.group(0).strip().replace("\n", " "),
                        page_number=page_num,
                        extraction_method=method,
                    )

        val_per, ev_per, spec_per = find_label_value(
            text, [r"Period"], ["Identifier", "City", "Designation"]
        )
        if val_per:
            collector.record(
                "statement_period",
                val_per,
                ev_per,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_per,
            )

    def _extract_employment_proof(
        self, collector: _FieldCollector, text: str, page_num: int, method: str
    ) -> None:
        m_id = re.search(r"Applicant ID[:\s]+(APP\d{4})", text, re.IGNORECASE)
        if not m_id:
            m_id = re.search(
                r"Employee (?:ID|Code)[:\s]+(?:EMP-)?(APP\d{4})", text, re.IGNORECASE
            )
        if m_id:
            collector.record(
                "applicant_id",
                m_id.group(1).upper(),
                m_id.group(0).strip(),
                page_number=page_num,
                extraction_method=method,
            )

        val_name, ev_name, spec_name = find_label_value(
            text,
            [r"Employee Name", r"Full Name", r"Name"],
            ["Employee ID", "Designation", "Department", "Date of Joining"],
        )
        if val_name:
            collector.record(
                "applicant_name",
                val_name,
                ev_name,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_name,
            )

        val_emp, ev_emp, spec_emp = find_label_value(
            text,
            [r"Employer Name", r"Organization Name", r"Company Name", r"Employer"],
            ["Designation", "Date of Joining", "Employee"],
        )
        if val_emp:
            collector.record(
                "employer_name",
                val_emp,
                ev_emp,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_emp,
            )

        val_des, ev_des, spec_des = find_label_value(
            text, [r"Designation", r"Role", r"Title"], ["Date of Joining", "Department"]
        )
        if val_des:
            collector.record(
                "designation",
                val_des,
                ev_des,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_des,
            )

        val_doj, ev_doj, spec_doj = find_label_value(
            text,
            [r"Date of Joining", r"Employment Start Date", r"Joining Date"],
            ["Employment Status", "Tenure", "Duration"],
        )
        if val_doj:
            collector.record(
                "employment_start_date",
                val_doj,
                ev_doj,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_doj,
            )

    def _extract_bank_statement(
        self,
        collector: _FieldCollector,
        text: str,
        page_num: int,
        method: str,
        page_scanned: bool,
    ) -> None:
        val, ev, spec = find_label_value(
            text,
            [r"Account Holder"],
            ["Statement Period", "Account Number", "Account Type", "Branch"],
        )
        if val:
            collector.record(
                "account_holder",
                val,
                ev,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec,
            )

        m_acc = re.search(r"(SYN-ACC-\d+-(APP\d{4})-\d+)", text, re.IGNORECASE)
        if m_acc:
            collector.record(
                "account_number",
                m_acc.group(1),
                f"Account Number: {mask_identifier(m_acc.group(1))}",
                page_number=page_num,
                extraction_method=method,
            )
            collector.record(
                "applicant_id",
                m_acc.group(2).upper(),
                m_acc.group(2).upper(),
                page_number=page_num,
                extraction_method=method,
            )
        else:
            m_gen_acc = re.search(
                r"Account Number[:\s]+([A-Z0-9*-]{6,24})", text, re.IGNORECASE
            )
            if m_gen_acc:
                raw_acc = m_gen_acc.group(1).strip()
                collector.record(
                    "account_number",
                    raw_acc,
                    f"Account Number: {mask_identifier(raw_acc)}",
                    page_number=page_num,
                    extraction_method=method,
                )

        val_per, ev_per, spec_per = find_label_value(
            text,
            [r"Statement Period"],
            ["Account Number", "Account Type", "Branch"],
        )
        if val_per:
            collector.record(
                "statement_period",
                val_per,
                ev_per,
                page_number=page_num,
                extraction_method=method,
                label_specificity=spec_per,
            )

        # Summary balances explicitly labeled on statement footer/header
        for fname, pat in [
            (
                "opening_balance",
                r"Opening Balance[:\s]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)",
            ),
            ("total_credits", r"Total Credits[:\s]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)"),
            ("total_debits", r"Total Debits[:\s]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)"),
        ]:
            m_sum = re.search(pat, text, re.IGNORECASE)
            if m_sum:
                parsed = parse_currency(m_sum.group(1))
                if parsed is not None:
                    collector.record(
                        fname,
                        parsed,
                        m_sum.group(0).strip().replace("\n", " "),
                        page_number=page_num,
                        extraction_method=method,
                    )

        txn_pattern = re.compile(
            r"(\d{2}-[A-Za-z]{3}-\d{4})\s+(.+?)\s+(TXN[O0-9]+|\w+)\s+([\d,.-]+|-)\s+([\d,.-]+|-)\s+([\d,.]+)"
        )
        txns: List[Dict[str, Any]] = []
        salary_credits: List[float] = []
        other_credits: List[float] = []
        emi_debits: List[float] = []

        for match in txn_pattern.finditer(text):
            date_str, desc, ref, debit_str, credit_str, bal_str = match.groups()
            debit_val = parse_currency(debit_str) if debit_str != "-" else None
            credit_val = parse_currency(credit_str) if credit_str != "-" else None
            bal_val = parse_currency(bal_str) or 0.0

            txns.append(
                {
                    "date": date_str,
                    "description": desc.strip(),
                    "ref": ref,
                    "debit": debit_val,
                    "credit": credit_val,
                    "balance": bal_val,
                }
            )

            desc_upper = desc.upper()
            if "SALARY CREDIT" in desc_upper and credit_val is not None:
                salary_credits.append(credit_val)
            elif credit_val is not None and credit_val > 0:
                # Explicitly track non-salary credits separately; never treat arbitrary deposits as salary
                other_credits.append(credit_val)

            if "EMI AUTO-DEBIT" in desc_upper and debit_val is not None:
                emi_debits.append(debit_val)

        table_method = "regex_ocr" if page_scanned else "table_parser"
        if txns:
            prev_count = (
                int(collector.usable["transaction_count"].value)
                if "transaction_count" in collector.usable
                else 0
            )
            total_count = prev_count + len(txns)
            collector.record(
                "transaction_count",
                total_count,
                f"Parsed {total_count} transactions from ledger table",
                page_number=page_num,
                extraction_method=table_method,
                label_specificity="table_column",
                allow_multipage_update=True,
            )
            collector.record(
                "closing_balance",
                txns[-1]["balance"],
                f"Final transaction on {txns[-1]['date']}: Balance INR {txns[-1]['balance']:.2f}",
                page_number=page_num,
                extraction_method=table_method,
                label_specificity="table_column",
                allow_multipage_update=True,
            )
        else:
            m_close = re.search(
                r"Closing Balance[:\s]+(?:INR|RS\.?|₹)?\s*(-?[0-9,.]+)",
                text,
                re.IGNORECASE,
            )
            if m_close:
                parsed_close = parse_currency(m_close.group(1))
                if parsed_close is not None:
                    collector.record(
                        "closing_balance",
                        parsed_close,
                        m_close.group(0).strip().replace("\n", " "),
                        page_number=page_num,
                        extraction_method=method,
                        allow_multipage_update=True,
                    )

        if salary_credits:
            collector.record(
                "salary_credit",
                salary_credits[0],
                f"Salary credit transaction: INR {salary_credits[0]:.2f}",
                page_number=page_num,
                extraction_method=table_method,
                label_specificity="table_column",
            )

        if other_credits:
            prev_other = (
                float(collector.usable["other_income"].value)
                if "other_income" in collector.usable
                else 0.0
            )
            total_other = round(prev_other + sum(other_credits), 2)
            collector.record(
                "other_income",
                total_other,
                f"Non-salary bank credits sum: INR {total_other:.2f}",
                page_number=page_num,
                extraction_method=table_method,
                label_specificity="table_column",
                allow_multipage_update=True,
            )

        if emi_debits:
            collector.record(
                "emi_debit",
                emi_debits[0],
                f"EMI auto-debit transaction: INR {emi_debits[0]:.2f}",
                page_number=page_num,
                extraction_method=table_method,
                label_specificity="table_column",
            )

    def _extract_generic(
        self, collector: _FieldCollector, text: str, page_num: int
    ) -> None:
        m_id = re.search(r"\b(APP\d{4})\b", text)
        if m_id:
            collector.record(
                "applicant_id",
                m_id.group(1),
                m_id.group(0),
                page_number=page_num,
                extraction_method="generic_fallback",
                label_specificity="weak_context",
            )


__all__ = [
    "ClassificationResult",
    "ClassificationSignal",
    "DocumentExtractor",
    "clean_label_value",
    "find_label_value",
    "parse_currency",
]
