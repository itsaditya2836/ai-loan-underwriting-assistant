"""Guided 4-Step Application Intake Wizard (Applicant Details -> Financials -> Documents -> Review & Submit)."""

from __future__ import annotations

import re
from typing import List, Tuple

import streamlit as st

from app.review.service import get_case_review_summary
from app.schemas.review import ReviewStatus
from app.ui.components import (
    format_inr,
    render_alert_box,
    render_banking_table,
    render_kv_grid,
    render_page_header,
    render_section_heading,
    render_wizard_progress,
)
from app.ui.services import (
    CANONICAL_DOCUMENT_CATEGORIES,
    EMPLOYMENT_TYPE_OPTIONS,
    expected_documents_for_employment,
    generate_applicant_reference,
    get_applicant_record,
    mask_extracted_value,
    preview_uploaded_documents,
    submit_application_and_underwrite,
    upload_signature_key,
    validate_applicant_form_input,
    validate_uploaded_pdf,
)
from app.ui.state import (
    STATE_DOC_PREVIEW_CACHE,
    STATE_INTAKE_DRAFT,
    STATE_INTAKE_SEED_REF,
    STATE_INTAKE_WIZARD_STEP,
    STATE_LAST_SUBMISSION_RECEIPT,
    STATE_STAGED_UPLOADS,
    STATE_SUBMISSION_IN_PROGRESS,
    STATE_SUBMITTED_HASHES,
    STATE_UPLOAD_COUNTER,
    can_role_access_page,
    clear_intake_after_submission,
    default_intake_draft,
    get_authenticated_ui_user,
    navigate_to,
    queue_new_applicant_ref,
    queue_wizard_step,
    store_live_result,
)

_WIZARD_STEPS: Tuple[Tuple[int, str, str], ...] = (
    (1, "Applicant Details", "Reference ID and personal applicant particulars"),
    (2, "Financial Information", "Employment, income, liabilities, and loan terms"),
    (3, "Supporting Documents", "Attach PDFs and inspect upload validation"),
    (4, "Review & Submit", "Confirm dossier details and run underwriting"),
)


def _validate_step1_fields(applicant_id: str, name: str, age: int) -> List[str]:
    """Validate Step 1 identity inputs cleanly before advancing."""
    errors: List[str] = []
    clean_id = applicant_id.strip()
    if not clean_id:
        errors.append("Applicant Reference ID is required.")
    elif not re.fullmatch(r"[A-Za-z0-9_-]{3,40}", clean_id):
        errors.append(
            "Applicant Reference ID must be 3–40 alphanumeric, hyphen, or underscore characters."
        )
    if not name.strip():
        errors.append("Applicant Full Name is required.")
    if int(age) < 18 or int(age) > 100:
        errors.append("Applicant age must be between 18 and 100 years.")
    return errors


def _render_intake_receipt() -> None:
    """Display completion confirmation banner cleanly after a successful submission."""
    receipt = st.session_state.get(STATE_LAST_SUBMISSION_RECEIPT)
    if not receipt:
        return

    rec = receipt.get("recommendation", "MANUAL_REVIEW")
    app_id = receipt.get("applicant_id", "")
    run_id = receipt.get("run_id")
    persisted = receipt.get("audit_persisted", False)
    err = receipt.get("audit_error")

    with st.container(border=True):
        st.success(
            f"Submitted `{app_id}` in {receipt.get('duration_ms', 0.0):.1f} ms — "
            f"AI Recommendation: **{rec}**"
        )
        if persisted and run_id:
            st.caption(f"Audit Record Verified: `{run_id}`")
        else:
            st.warning(
                f"Underwriting completed, but audit persistence reported an issue: {err or 'Unavailable'}"
            )

        b1, b2, b3, b4 = st.columns(4)
        with b1:
            if st.button(
                "Open App Workspace",
                key="receipt_goto_workspace",
                type="primary",
                width="stretch",
            ):
                navigate_to(
                    "Application Details", applicant_id=app_id, run_id=run_id
                )
                st.rerun()
        with b2:
            if st.button(
                "Underwriting Results",
                key="receipt_goto_results",
                width="stretch",
            ):
                navigate_to(
                    "Underwriting Results", applicant_id=app_id, run_id=run_id
                )
                st.rerun()
        with b3:
            if st.button(
                "Human Review",
                key="receipt_goto_review_queue",
                width="stretch",
            ):
                navigate_to(
                    "Underwriter Review Queue", applicant_id=app_id, run_id=run_id
                )
                st.rerun()
        with b4:
            if st.button(
                "Document Verification",
                key="receipt_goto_docs",
                width="stretch",
            ):
                navigate_to("Document Review", applicant_id=app_id, run_id=run_id)
                st.rerun()


def render_new_application_view() -> None:
    """Render the guided 4-step Application Intake Wizard preserving all 13 Applicant fields."""
    render_page_header(
        "Workspace",
        "New Application Wizard",
        "Follow the guided 4-step workflow to capture applicant details, financial profile, supporting PDFs, and initiate underwriting.",
        breadcrumbs=["Workspace", "Applications", "New Application"],
    )

    auth_user = get_authenticated_ui_user()
    active_role = auth_user.role if auth_user is not None else None
    role_blocked = not can_role_access_page(active_role, "New Application")
    if role_blocked and auth_user is not None:
        render_alert_box(
            "Read-Only Role Restriction",
            f"Signed-in role '{auth_user.role.value}' is not authorized to submit new loan applications.",
            variant="warning",
        )

    _render_intake_receipt()

    draft = dict(st.session_state.get(STATE_INTAKE_DRAFT) or default_intake_draft())
    if not draft.get("applicant_id"):
        seed_ref = (
            st.session_state.get(STATE_INTAKE_SEED_REF)
            or generate_applicant_reference()
        )
        st.session_state[STATE_INTAKE_SEED_REF] = seed_ref
        draft["applicant_id"] = seed_ref
        st.session_state[STATE_INTAKE_DRAFT] = draft

    current_step = int(st.session_state.get(STATE_INTAKE_WIZARD_STEP, 1))
    current_step = max(1, min(4, current_step))
    render_wizard_progress(current_step, _WIZARD_STEPS)

    # Surface active human-requested additional-info instructions if revisiting an existing case
    existing_rec = get_applicant_record(str(draft.get("applicant_id", "")).strip())
    if existing_rec:
        case_rev = get_case_review_summary(existing_rec["applicant_id"])
        latest_rev = case_rev.get("latest_review") or {}
        if (
            case_rev.get("human_review_status")
            == ReviewStatus.ADDITIONAL_INFO_REQUESTED.value
        ):
            render_alert_box(
                f"Additional Information Requested ({existing_rec['applicant_id']})",
                f"{latest_rev.get('additional_info_request') or 'See review notes.'} "
                "Submitting updated documents creates a new underwriting run while keeping prior audit history intact.",
                variant="warning",
            )

    # ==================================================================
    # STEP 1 — Applicant Details
    # ==================================================================
    if current_step == 1:
        with st.container(border=True):
            render_section_heading(
                "Step 1 of 4 — Applicant Details",
                "Assign an application reference ID and enter core personal particulars",
            )
            ref_col1, ref_col2 = st.columns([3.2, 1.1], vertical_alignment="bottom")
            with ref_col1:
                applicant_id = st.text_input(
                    "Applicant Reference ID *",
                    value=str(draft.get("applicant_id", "")),
                    key="intake_field_applicant_id",
                    help="Unique alphanumeric reference (3–40 chars). Automatically generated or user-specified.",
                )
            with ref_col2:
                if st.button(
                    "Generate New ID",
                    key="btn_gen_applicant_ref",
                    width="stretch",
                ):
                    queue_new_applicant_ref(generate_applicant_reference())
                    st.rerun()

            p1, p2 = st.columns([2.2, 1])
            with p1:
                name = st.text_input(
                    "Applicant Full Name *",
                    value=str(draft.get("name", "")),
                    key="intake_field_name",
                    placeholder="e.g., Ananya Sharma",
                )
            with p2:
                age = st.number_input(
                    "Age (Years) *",
                    min_value=18,
                    max_value=100,
                    value=int(draft.get("age", 30)),
                    step=1,
                    key="intake_field_age",
                )

            draft["applicant_id"] = applicant_id
            draft["name"] = name
            draft["age"] = int(age)
            st.session_state[STATE_INTAKE_DRAFT] = draft

            step1_errors = _validate_step1_fields(applicant_id, name, int(age))
            if st.session_state.get("_intake_step1_tried") and step1_errors:
                for err in step1_errors:
                    st.error(err)

            st.caption(
                "Next: Capture employment details, income, existing obligations, and requested loan facility."
            )

        nav_l, nav_c, nav_r = st.columns([1.1, 2.2, 1.3], vertical_alignment="center")
        with nav_l:
            if st.button("Reset Draft", key="btn_reset_draft", width="stretch"):
                st.session_state.pop("_intake_step1_tried", None)
                clear_intake_after_submission(generate_applicant_reference())
                st.session_state[STATE_LAST_SUBMISSION_RECEIPT] = None
                st.rerun()
        with nav_r:
            if st.button(
                "Continue to Financials",
                type="primary",
                icon=":material/arrow_forward:",
                key="wizard_next_1",
                width="stretch",
            ):
                if step1_errors:
                    st.session_state["_intake_step1_tried"] = True
                    st.rerun()
                st.session_state.pop("_intake_step1_tried", None)
                queue_wizard_step(2)
                st.rerun()

    # ==================================================================
    # STEP 2 — Financial Information
    # ==================================================================
    elif current_step == 2:
        with st.container(border=True):
            render_section_heading(
                "Step 2 of 4 — Financial Information",
                f"Applicant {draft.get('applicant_id')} ({draft.get('name') or 'Draft'}) — employment, income, liabilities, and credit terms",
            )

            e1, e2, e3 = st.columns([1.2, 1, 1.2])
            with e1:
                emp_default = str(draft.get("employment_type", "Salaried"))
                emp_idx = (
                    EMPLOYMENT_TYPE_OPTIONS.index(emp_default)
                    if emp_default in EMPLOYMENT_TYPE_OPTIONS
                    else 0
                )
                employment_type = st.selectbox(
                    "Employment Type *",
                    options=list(EMPLOYMENT_TYPE_OPTIONS),
                    index=emp_idx,
                    key="intake_field_employment_type",
                )
            with e2:
                employment_years = st.number_input(
                    "Employment / Business Years *",
                    min_value=0.0,
                    max_value=80.0,
                    value=float(draft.get("employment_years", 3.0)),
                    step=0.5,
                    key="intake_field_employment_years",
                )
            with e3:
                monthly_income = st.number_input(
                    "Monthly Income (INR) *",
                    min_value=0.0,
                    value=float(draft.get("monthly_income", 75000.0)),
                    step=1000.0,
                    key="intake_field_monthly_income",
                )

            f1, f2 = st.columns(2)
            with f1:
                existing_emi = st.number_input(
                    "Existing Monthly EMI (INR)",
                    min_value=0.0,
                    value=float(draft.get("existing_emi", 0.0)),
                    step=500.0,
                    key="intake_field_existing_emi",
                    help="Valid zero (0.0) values are preserved faithfully.",
                )
            with f2:
                bank_balance = st.number_input(
                    "Verifiable Bank Balance (INR)",
                    min_value=0.0,
                    value=float(draft.get("bank_balance", 100000.0)),
                    step=5000.0,
                    key="intake_field_bank_balance",
                )

            l1, l2, l3 = st.columns(3)
            with l1:
                loan_amount = st.number_input(
                    "Requested Loan Amount (INR) *",
                    min_value=1.0,
                    value=float(draft.get("loan_amount", 300000.0)),
                    step=10000.0,
                    key="intake_field_loan_amount",
                )
            with l2:
                loan_tenure = st.number_input(
                    "Loan Tenure (Months) *",
                    min_value=1,
                    max_value=360,
                    value=int(draft.get("loan_tenure", 36)),
                    step=6,
                    key="intake_field_loan_tenure",
                )
            with l3:
                credit_score = st.number_input(
                    "Bureau Credit Score (300–900) *",
                    min_value=300,
                    max_value=900,
                    value=int(draft.get("credit_score", 720)),
                    step=5,
                    key="intake_field_credit_score",
                )

            o1, o2 = st.columns(2)
            with o1:
                exp_raw = st.text_input(
                    "Declared Monthly Expenses (INR, optional)",
                    value=(
                        ""
                        if draft.get("monthly_expenses") is None
                        else str(draft.get("monthly_expenses"))
                    ),
                    key="intake_field_monthly_expenses",
                    placeholder="Leave blank if unknown (or enter 0+)",
                )
            with o2:
                dep_raw = st.text_input(
                    "Number of Dependents (0–20, optional)",
                    value=(
                        ""
                        if draft.get("number_of_dependents") is None
                        else str(draft.get("number_of_dependents"))
                    ),
                    key="intake_field_number_of_dependents",
                    placeholder="Leave blank if unknown (or enter 0–20)",
                )

        parse_errors: List[str] = []
        parsed_expenses = None
        if exp_raw.strip():
            try:
                parsed_expenses = float(exp_raw.strip())
            except ValueError:
                parse_errors.append(
                    "Monthly expenses must be a valid non-negative number."
                )

        parsed_dependents = None
        if dep_raw.strip():
            try:
                parsed_dependents = int(dep_raw.strip())
            except ValueError:
                parse_errors.append(
                    "Number of dependents must be a whole integer (0–20)."
                )

        draft.update(
            {
                "employment_type": employment_type,
                "employment_years": float(employment_years),
                "monthly_income": float(monthly_income),
                "existing_emi": float(existing_emi),
                "bank_balance": float(bank_balance),
                "loan_amount": float(loan_amount),
                "loan_tenure": int(loan_tenure),
                "credit_score": int(credit_score),
                "monthly_expenses": parsed_expenses,
                "number_of_dependents": parsed_dependents,
            }
        )
        st.session_state[STATE_INTAKE_DRAFT] = draft

        _, schema_errors, domain_warnings = validate_applicant_form_input(draft)
        all_step2_errors = parse_errors + schema_errors
        if all_step2_errors:
            for err in all_step2_errors:
                st.error(err)
        for warn in domain_warnings:
            st.warning(f"Profile Plausibility Notice: {warn}")

        nav_l, nav_c, nav_r = st.columns([1.2, 2.0, 1.4], vertical_alignment="center")
        with nav_l:
            if st.button(
                "Previous",
                icon=":material/arrow_back:",
                key="wizard_prev_2",
                width="stretch",
            ):
                queue_wizard_step(1)
                st.rerun()
        with nav_r:
            if st.button(
                "Continue to Documents",
                type="primary",
                icon=":material/arrow_forward:",
                key="wizard_next_2",
                disabled=bool(all_step2_errors),
                width="stretch",
            ):
                queue_wizard_step(3)
                st.rerun()

    # ==================================================================
    # STEP 3 — Supporting Documents
    # ==================================================================
    elif current_step == 3:
        staged = list(st.session_state.get(STATE_STAGED_UPLOADS, []))
        employment_type = str(draft.get("employment_type", "Salaried"))
        expected_docs = expected_documents_for_employment(employment_type)

        with st.container(border=True):
            render_section_heading(
                "Step 3 of 4 — Supporting Documents (PDF Only)",
                f"Upload required evidence for {employment_type} profile verification",
            )
            st.markdown(
                "**Required Categories:** "
                + " · ".join(f"`{d}`" for d in expected_docs)
            )

            u_col1, u_col2 = st.columns([1.1, 2.2], vertical_alignment="top")
            with u_col1:
                default_upload_cat = st.selectbox(
                    "Document Category Tag",
                    options=list(CANONICAL_DOCUMENT_CATEGORIES),
                    index=0,
                    key="intake_upload_category_tag",
                    help="Keep 'auto' to rely on automated content classification, or tag an explicit category.",
                )
            with u_col2:
                upload_counter = int(st.session_state.get(STATE_UPLOAD_COUNTER, 0))
                uploaded_widgets = st.file_uploader(
                    "Upload Supporting PDFs (Max 25 MB per file)",
                    type=["pdf"],
                    accept_multiple_files=True,
                    key=f"intake_pdf_uploader_{upload_counter}",
                )

            if uploaded_widgets:
                existing_hashes = {
                    item["sha256"] for item in staged if item.get("sha256")
                }
                existing_file_ids = {item["file_id"] for item in staged}
                added_any = False
                for uf in uploaded_widgets:
                    raw_bytes = uf.getvalue()
                    res = validate_uploaded_pdf(
                        filename=uf.name,
                        file_bytes=raw_bytes,
                        existing_hashes=existing_hashes,
                        declared_category=default_upload_cat,
                    )
                    if res["file_id"] not in existing_file_ids:
                        staged.append(res)
                        existing_file_ids.add(res["file_id"])
                        if res["status"] == "VALID":
                            existing_hashes.add(res["sha256"])
                        added_any = True
                if added_any:
                    st.session_state[STATE_STAGED_UPLOADS] = staged

            if staged:
                st.markdown("**Uploaded & Validated Files**")
                render_banking_table(
                    headers=["Filename", "Category", "Size", "Validation Status", "Details"],
                    rows=[
                        [
                            str(u["original_filename"]),
                            str(u.get("category", "auto")),
                            f"{u['size_bytes'] / 1024:.1f} KB",
                            str(u["status"]),
                            u.get("validation_error")
                            or (
                                "; ".join(u["security_warnings"])
                                if u.get("security_warnings")
                                else f"Detected hint: {u.get('detected_hint', 'auto')}"
                            ),
                        ]
                        for u in staged
                    ],
                    pill_columns={3},
                )

                # Category override & file removal row controls
                for idx, item in enumerate(list(staged)):
                    rc1, rc2, rc3 = st.columns(
                        [2.5, 1.5, 0.9], vertical_alignment="center"
                    )
                    with rc1:
                        st.caption(
                            f"`{item['original_filename']}` ({item['sha256'][:10]})"
                        )
                    with rc2:
                        if item["status"] == "VALID":
                            cur_cat = item.get("category", "auto")
                            cat_idx = (
                                CANONICAL_DOCUMENT_CATEGORIES.index(cur_cat)
                                if cur_cat in CANONICAL_DOCUMENT_CATEGORIES
                                else 0
                            )
                            new_cat = st.selectbox(
                                f"Category for {item['original_filename']}",
                                options=list(CANONICAL_DOCUMENT_CATEGORIES),
                                index=cat_idx,
                                key=f"staged_cat_{idx}_{item['file_id']}",
                                label_visibility="collapsed",
                            )
                            if new_cat != cur_cat:
                                staged[idx]["category"] = new_cat
                                st.session_state[STATE_STAGED_UPLOADS] = staged
                    with rc3:
                        if st.button(
                            "Remove",
                            key=f"remove_staged_{idx}_{item['file_id']}",
                            width="stretch",
                        ):
                            staged.pop(idx)
                            st.session_state[STATE_STAGED_UPLOADS] = staged
                            st.rerun()

                valid_items = [u for u in staged if u.get("status") == "VALID"]
                if valid_items:
                    p_btn_col, clear_btn_col = st.columns([2, 1])
                    with p_btn_col:
                        run_preview_btn = st.button(
                            "Validate & Extract Document Preview (OCR)",
                            key="btn_preview_staged_docs",
                            width="stretch",
                        )
                    with clear_btn_col:
                        if st.button(
                            "Clear All Uploads",
                            key="btn_clear_uploads",
                            width="stretch",
                        ):
                            st.session_state[STATE_STAGED_UPLOADS] = []
                            st.session_state[STATE_DOC_PREVIEW_CACHE] = {}
                            st.session_state[STATE_UPLOAD_COUNTER] = upload_counter + 1
                            st.rerun()

                    sig = upload_signature_key(staged)
                    preview_cache = st.session_state.get(STATE_DOC_PREVIEW_CACHE, {})
                    if run_preview_btn:
                        if sig not in preview_cache:
                            with st.spinner(
                                "Validating and extracting uploaded PDFs..."
                            ):
                                pkg = preview_uploaded_documents(
                                    applicant_id=str(
                                        draft.get("applicant_id") or "PREVIEW"
                                    ),
                                    staged_uploads=staged,
                                )
                                preview_cache[sig] = pkg
                                st.session_state[STATE_DOC_PREVIEW_CACHE] = (
                                    preview_cache
                                )
                        else:
                            st.info(
                                "Loaded cached extraction preview for identical uploaded files."
                            )

                    if sig in preview_cache:
                        pkg = preview_cache[sig]
                        render_kv_grid(
                            [
                                ("Processing Status", pkg.processing_status),
                                ("Detected Docs", str(len(pkg.documents_found))),
                                ("Missing Mandatory", str(len(pkg.documents_missing))),
                                ("OCR Used", "Yes" if pkg.ocr_used else "No"),
                            ],
                            columns=4,
                        )
                        if pkg.all_extracted_fields:
                            with st.expander(
                                "Preview Masked Extracted Fields", expanded=False
                            ):
                                for fn, ef in sorted(pkg.all_extracted_fields.items()):
                                    st.write(
                                        f"- `{fn}`: **{mask_extracted_value(fn, ef.value, ef.masked_value)}** "
                                        f"(source=`{ef.source_document}`, page={ef.page_number})"
                                    )
            else:
                render_alert_box(
                    "Optional Document Skip",
                    "You may proceed without uploading PDFs; applications missing mandatory documents fail closed to Manual Review.",
                    variant="info",
                )

        has_invalid_staged = any(u.get("status") == "INVALID" for u in staged)
        if has_invalid_staged:
            st.error(
                "Remove INVALID files before continuing to Review & Submit."
            )

        nav_l, nav_c, nav_r = st.columns([1.2, 2.0, 1.4], vertical_alignment="center")
        with nav_l:
            if st.button(
                "Previous",
                icon=":material/arrow_back:",
                key="wizard_prev_3",
                width="stretch",
            ):
                queue_wizard_step(2)
                st.rerun()
        with nav_r:
            if st.button(
                "Continue to Review",
                type="primary",
                icon=":material/arrow_forward:",
                key="wizard_next_3",
                disabled=has_invalid_staged,
                width="stretch",
            ):
                queue_wizard_step(4)
                st.rerun()

    # ==================================================================
    # STEP 4 — Review & Submit
    # ==================================================================
    else:
        staged = list(st.session_state.get(STATE_STAGED_UPLOADS, []))
        valid_uploads = [u for u in staged if u.get("status") == "VALID"]
        has_invalid_staged = any(u.get("status") == "INVALID" for u in staged)
        validated_applicant, schema_errors, domain_warnings = (
            validate_applicant_form_input(draft)
        )

        with st.container(border=True):
            render_section_heading(
                "Step 4 of 4 — Review & Submit",
                "Verify all applicant fields and uploaded PDFs before initiating multi-agent underwriting",
            )

            h1_l, h1_r = st.columns([3.2, 1], vertical_alignment="center")
            with h1_l:
                st.markdown("**Applicant & Financial Summary**")
            with h1_r:
                if st.button("Edit Details", key="wizard_edit_1", width="stretch"):
                    queue_wizard_step(1)
                    st.rerun()

            dep = draft.get("number_of_dependents")
            m_exp = draft.get("monthly_expenses")
            render_kv_grid(
                [
                    ("Applicant Reference ID", str(draft.get("applicant_id", ""))),
                    ("Full Name", str(draft.get("name", ""))),
                    ("Age", f"{draft.get('age', '')} yrs"),
                    ("Employment Type", str(draft.get("employment_type", ""))),
                    ("Tenure", f"{draft.get('employment_years', '')} yrs"),
                    ("Monthly Income", format_inr(draft.get("monthly_income"))),
                    ("Existing Monthly EMI", format_inr(draft.get("existing_emi"))),
                    ("Bank Balance", format_inr(draft.get("bank_balance"))),
                    ("Requested Loan Amount", format_inr(draft.get("loan_amount"))),
                    ("Loan Tenure", f"{draft.get('loan_tenure', '')} months"),
                    ("Bureau Credit Score", str(draft.get("credit_score", ""))),
                    (
                        "Monthly Expenses",
                        format_inr(m_exp) if m_exp is not None else "Not Provided",
                    ),
                    ("Dependents", str(dep) if dep is not None else "Not Provided"),
                ],
                columns=4,
            )

            h2_l, h2_r = st.columns([3.2, 1], vertical_alignment="center")
            with h2_l:
                st.markdown(f"**Supporting Documents ({len(valid_uploads)} valid file(s))**")
            with h2_r:
                if st.button("Edit Documents", key="wizard_edit_3", width="stretch"):
                    queue_wizard_step(3)
                    st.rerun()

            if valid_uploads:
                render_banking_table(
                    headers=["Filename", "Category", "Size", "Status"],
                    rows=[
                        [
                            str(u["original_filename"]),
                            str(u.get("category", "auto")),
                            f"{u['size_bytes'] / 1024:.1f} KB",
                            str(u["status"]),
                        ]
                        for u in valid_uploads
                    ],
                    pill_columns={3},
                )
            else:
                render_alert_box(
                    "No PDFs Attached",
                    "Proceeding without documents preserves incomplete-package state and routes to Manual Review.",
                    variant="warning",
                )

            if schema_errors:
                for err in schema_errors:
                    st.error(err)
            for warn in domain_warnings:
                st.warning(f"Profile Plausibility Notice: {warn}")

            allow_dup = st.checkbox(
                "Allow intentional re-submission of identical applicant & document payload",
                value=False,
                key="intake_allow_resubmit",
            )
            confirmed_submit = st.checkbox(
                "I confirm the applicant details and attached documents are ready for automated underwriting.",
                value=True,
                key="intake_confirm_submit",
            )

        submit_disabled = (
            bool(schema_errors)
            or has_invalid_staged
            or role_blocked
            or not confirmed_submit
            or st.session_state.get(STATE_SUBMISSION_IN_PROGRESS, False)
        )

        nav_l, nav_mid, nav_r = st.columns([1.0, 1.0, 1.8], vertical_alignment="center")
        with nav_l:
            if st.button(
                "Previous",
                icon=":material/arrow_back:",
                key="wizard_prev_4",
                width="stretch",
            ):
                queue_wizard_step(3)
                st.rerun()
        with nav_mid:
            if st.button(
                "Reset Draft",
                key="btn_reset_draft",
                width="stretch",
            ):
                clear_intake_after_submission(generate_applicant_reference())
                st.session_state[STATE_LAST_SUBMISSION_RECEIPT] = None
                st.rerun()
        with nav_r:
            if st.button(
                "Submit & Run Underwriting",
                type="primary",
                icon=":material/send:",
                disabled=submit_disabled,
                width="stretch",
                key="btn_submit_underwriting",
            ):
                if validated_applicant is None:
                    st.error("Fix validation errors before submitting.")
                    return

                if role_blocked and auth_user is not None:
                    st.error(
                        f"Role '{auth_user.role.value}' is not authorized to submit and run underwriting applications."
                    )
                    return

                st.session_state[STATE_SUBMISSION_IN_PROGRESS] = True
                try:
                    with st.spinner(
                        "Executing underwriting pipeline (Documents -> Eligibility -> Fraud -> Risk -> Decision)..."
                    ):
                        outcome = submit_application_and_underwrite(
                            applicant=validated_applicant,
                            staged_uploads=staged,
                            use_existing_package_if_empty=False,
                            allow_duplicate=allow_dup,
                            submitted_by_user_id=(
                                auth_user.user_id if auth_user else None
                            ),
                            submitted_by_username=(
                                auth_user.username if auth_user else None
                            ),
                            submitted_by_role=(
                                auth_user.role.value if auth_user else None
                            ),
                        )
                except Exception as exc:
                    st.session_state[STATE_SUBMISSION_IN_PROGRESS] = False
                    st.error(
                        f"Submission failed safely without corrupting state: {exc}"
                    )
                    return
                st.session_state[STATE_SUBMISSION_IN_PROGRESS] = False

                if outcome.get("duplicate_blocked"):
                    dup_app = outcome.get("existing_application", {})
                    st.warning(
                        f"Duplicate submission blocked cleanly: identical profile & uploaded documents were "
                        f"already submitted under `{dup_app.get('applicant_id')}` "
                        f"(Latest Run ID: `{dup_app.get('latest_run_id')}`)."
                    )
                    return

                store_live_result(validated_applicant.applicant_id, outcome)
                submitted_hashes = st.session_state.get(STATE_SUBMITTED_HASHES, {})
                submitted_hashes[outcome["submission_hash"]] = outcome.get("run_id")
                st.session_state[STATE_SUBMITTED_HASHES] = submitted_hashes

                decision = outcome["decision"]
                st.session_state[STATE_LAST_SUBMISSION_RECEIPT] = {
                    "applicant_id": validated_applicant.applicant_id,
                    "run_id": outcome.get("run_id"),
                    "recommendation": decision.recommendation.value,
                    "audit_persisted": outcome.get("audit_persisted", False),
                    "audit_error": outcome.get("audit_error"),
                    "duration_ms": outcome.get("duration_ms", 0.0),
                }
                clear_intake_after_submission(generate_applicant_reference())
                st.rerun()
