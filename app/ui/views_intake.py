"""New Application / Applicant Intake & Document Upload View.

Provides:
- Cleanly separated form sections matching the authoritative Applicant schema
- Real PDF upload validation (.pdf extension, %PDF- signature, size limit, SHA-256 dedupe)
- File removal before submission & cached document intelligence preview
- Duplicate submission guard & deterministic multi-agent pipeline invocation
"""

from __future__ import annotations

import streamlit as st

from app.review.service import get_case_review_summary
from app.schemas.review import ReviewStatus
from app.ui.components import (
    format_inr,
    render_page_header,
    render_section_heading,
    render_status_pill,
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
    STATE_LAST_SUBMISSION_RECEIPT,
    STATE_STAGED_UPLOADS,
    STATE_SUBMISSION_IN_PROGRESS,
    STATE_SUBMITTED_HASHES,
    STATE_UPLOAD_COUNTER,
    clear_intake_after_submission,
    default_intake_draft,
    get_authenticated_ui_user,
    navigate_to,
    queue_new_applicant_ref,
    store_live_result,
)


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
            f"Submitted `{app_id}` cleanly in {receipt.get('duration_ms', 0.0):.1f} ms — "
            f"AI Recommendation: **{rec}**"
        )
        if persisted and run_id:
            st.caption(f"Audit Record Verified: `{run_id}`")
        else:
            st.warning(
                f"Underwriting completed, but audit database persistence reported an issue: {err or 'Unavailable'}"
            )

        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button(
                "View Underwriting Results",
                key="receipt_goto_results",
                width="stretch",
            ):
                navigate_to(
                    "Underwriting Results", applicant_id=app_id, run_id=run_id
                )
                st.rerun()
        with b2:
            if st.button(
                "Open in Review Queue",
                key="receipt_goto_review_queue",
                width="stretch",
            ):
                navigate_to(
                    "Underwriter Review Queue", applicant_id=app_id, run_id=run_id
                )
                st.rerun()
        with b3:
            if st.button(
                "Review Uploaded Documents",
                key="receipt_goto_docs",
                width="stretch",
            ):
                navigate_to("Document Review", applicant_id=app_id, run_id=run_id)
                st.rerun()


def render_new_application_view() -> None:
    """Render end-to-end New Application intake, PDF upload, validation, and submission."""
    render_page_header(
        "Applications",
        "New Application",
        "Complete the applicant profile, attach supporting PDF documents, and initiate underwriting.",
    )

    auth_user = get_authenticated_ui_user()
    role_blocked = False
    if auth_user is not None:
        from app.auth.permissions import Permission, check_permission

        if not (
            check_permission(auth_user.role, Permission.APPLICANT_CREATE)
            and check_permission(auth_user.role, Permission.UNDERWRITING_INITIATE)
        ):
            role_blocked = True
            st.warning(
                f"Read-only restriction: signed-in role `{auth_user.role.value}` is not authorized to submit new loan applications."
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

    existing_rec = get_applicant_record(str(draft.get("applicant_id", "")).strip())
    if existing_rec:
        case_rev = get_case_review_summary(existing_rec["applicant_id"])
        latest_rev = case_rev.get("latest_review") or {}
        if (
            case_rev.get("human_review_status")
            == ReviewStatus.ADDITIONAL_INFO_REQUESTED.value
        ):
            st.warning(
                f"**Additional Information Requested for `{existing_rec['applicant_id']}`:** "
                f"{latest_rev.get('additional_info_request') or 'See review notes.'}  \n"
                "Submitting updated documents creates a new underwriting run while preserving prior audit history."
            )

    # ------------------------------------------------------------------
    # Section 1: Applicant Identity & Employment
    # ------------------------------------------------------------------
    with st.container(border=True):
        render_section_heading(
            "1. Applicant Identity & Employment",
            "Core applicant reference and employment stability details",
        )
        ref_col1, ref_col2 = st.columns([3.2, 1], vertical_alignment="bottom")
        with ref_col1:
            applicant_id = st.text_input(
                "Applicant Reference ID *",
                value=str(draft.get("applicant_id", "")),
                key="intake_field_applicant_id",
                help="Unique alphanumeric reference (3–40 chars). Automatically generated or user-specified.",
            )
        with ref_col2:
            if st.button(
                "Generate New ID", key="btn_gen_applicant_ref", width="stretch"
            ):
                queue_new_applicant_ref(generate_applicant_reference())
                st.rerun()

        p1, p2, p3, p4 = st.columns([2, 1, 1.3, 1.2])
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
        with p3:
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
        with p4:
            employment_years = st.number_input(
                "Tenure (Years) *",
                min_value=0.0,
                max_value=80.0,
                value=float(draft.get("employment_years", 3.0)),
                step=0.5,
                key="intake_field_employment_years",
            )

    # ------------------------------------------------------------------
    # Section 2: Financials & Loan Request
    # ------------------------------------------------------------------
    with st.container(border=True):
        render_section_heading(
            "2. Financial Profile & Loan Request",
            "Declared income, existing debt obligations, liquidity, and requested credit facility",
        )
        f1, f2, f3 = st.columns(3)
        with f1:
            monthly_income = st.number_input(
                "Monthly Income (INR) *",
                min_value=0.0,
                value=float(draft.get("monthly_income", 75000.0)),
                step=1000.0,
                key="intake_field_monthly_income",
            )
        with f2:
            existing_emi = st.number_input(
                "Existing Monthly EMI (INR)",
                min_value=0.0,
                value=float(draft.get("existing_emi", 0.0)),
                step=500.0,
                key="intake_field_existing_emi",
                help="Valid zero (0.0) values are preserved faithfully.",
            )
        with f3:
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

    parse_errors: list[str] = []
    parsed_expenses = None
    if exp_raw.strip():
        try:
            parsed_expenses = float(exp_raw.strip())
        except ValueError:
            parse_errors.append("Monthly expenses must be a valid non-negative number.")

    parsed_dependents = None
    if dep_raw.strip():
        try:
            parsed_dependents = int(dep_raw.strip())
        except ValueError:
            parse_errors.append("Number of dependents must be a whole integer (0–20).")

    updated_draft = {
        "applicant_id": applicant_id,
        "name": name,
        "age": int(age),
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
    st.session_state[STATE_INTAKE_DRAFT] = updated_draft

    validated_applicant, schema_errors, domain_warnings = validate_applicant_form_input(
        updated_draft
    )
    all_errors = parse_errors + schema_errors

    if all_errors:
        for err in all_errors:
            st.error(err)
    elif validated_applicant is not None:
        st.caption(
            f"Schema Validated: `{validated_applicant.applicant_id}` · "
            f"Income {format_inr(validated_applicant.monthly_income)} · "
            f"Loan {format_inr(validated_applicant.loan_amount)} ({validated_applicant.loan_tenure} mo)"
        )
    for warn in domain_warnings:
        st.warning(f"Profile Plausibility Notice: {warn}")

    # ------------------------------------------------------------------
    # Section 3: Supporting Document Upload (PDF Only)
    # ------------------------------------------------------------------
    with st.container(border=True):
        render_section_heading(
            "3. Supporting Documents (PDF Only)",
            "Attach applicant documents for automated classification, OCR, and cross-document verification",
        )
        expected_docs = expected_documents_for_employment(employment_type)
        st.markdown(
            f"**Required for `{employment_type}` profile:** "
            + " · ".join(f"`{d}`" for d in expected_docs)
        )

        u_col1, u_col2 = st.columns([1.1, 2.2], vertical_alignment="top")
        with u_col1:
            default_upload_cat = st.selectbox(
                "Document Category Tag",
                options=list(CANONICAL_DOCUMENT_CATEGORIES),
                index=0,
                key="intake_upload_category_tag",
                help="Keep 'auto' to rely on automated content classification, or override explicitly.",
            )
        with u_col2:
            upload_counter = int(st.session_state.get(STATE_UPLOAD_COUNTER, 0))
            uploaded_widgets = st.file_uploader(
                "Upload Supporting PDFs (Max 25 MB per file)",
                type=["pdf"],
                accept_multiple_files=True,
                key=f"intake_pdf_uploader_{upload_counter}",
            )

        staged = list(st.session_state.get(STATE_STAGED_UPLOADS, []))
        if uploaded_widgets:
            existing_hashes = {item["sha256"] for item in staged if item.get("sha256")}
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
            st.markdown("**Staged Documents**")
            for idx, item in enumerate(list(staged)):
                row_c1, row_c2, row_c3, row_c4, row_c5 = st.columns(
                    [2.8, 1.8, 1.2, 2.2, 1], vertical_alignment="center"
                )
                with row_c1:
                    st.markdown(
                        f"**`{item['original_filename']}`**  \n"
                        f"<span style='font-size:0.75rem;color:#64748B;'>{item['size_bytes'] / 1024:.1f} KB · {item['sha256'][:10]}</span>",
                        unsafe_allow_html=True,
                    )
                with row_c2:
                    if item["status"] == "VALID":
                        cur_cat = item.get("category", "auto")
                        cat_idx = (
                            CANONICAL_DOCUMENT_CATEGORIES.index(cur_cat)
                            if cur_cat in CANONICAL_DOCUMENT_CATEGORIES
                            else 0
                        )
                        new_cat = st.selectbox(
                            "Category",
                            options=list(CANONICAL_DOCUMENT_CATEGORIES),
                            index=cat_idx,
                            key=f"staged_cat_{idx}_{item['file_id']}",
                            label_visibility="collapsed",
                        )
                        if new_cat != cur_cat:
                            staged[idx]["category"] = new_cat
                            st.session_state[STATE_STAGED_UPLOADS] = staged
                    else:
                        st.caption("—")
                with row_c3:
                    st.markdown(
                        render_status_pill(item["status"]),
                        unsafe_allow_html=True,
                    )
                with row_c4:
                    if item.get("validation_error"):
                        st.caption(item["validation_error"])
                    elif item.get("security_warnings"):
                        st.caption("; ".join(item["security_warnings"]))
                    else:
                        st.caption(f"Hint: `{item.get('detected_hint', 'auto')}`")
                with row_c5:
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
                        "Validate & Extract Document Preview (OCR / Extraction)",
                        key="btn_preview_staged_docs",
                        width="stretch",
                    )
                with clear_btn_col:
                    if st.button(
                        "Clear Staged Uploads",
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
                                applicant_id=applicant_id or "PREVIEW",
                                staged_uploads=staged,
                            )
                            preview_cache[sig] = pkg
                            st.session_state[STATE_DOC_PREVIEW_CACHE] = preview_cache
                    else:
                        st.info(
                            "Loaded cached extraction preview for identical uploaded files."
                        )

                if sig in preview_cache:
                    pkg = preview_cache[sig]
                    st.markdown("**Pre-Submission Extraction Summary**")
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Processing Status", pkg.processing_status)
                    m2.metric("Detected Docs", len(pkg.documents_found))
                    m3.metric("Missing Mandatory", len(pkg.documents_missing))
                    m4.metric("OCR Used", "Yes" if pkg.ocr_used else "No")
                    if pkg.documents_missing:
                        st.warning(
                            f"Missing required categories: {', '.join(pkg.documents_missing)}"
                        )
                    if pkg.unclassified_documents:
                        st.warning(
                            f"Unclassified documents: {', '.join(pkg.unclassified_documents)}"
                        )
                    if pkg.processing_errors:
                        st.error(
                            "Extraction warnings/errors: "
                            + "; ".join(pkg.processing_errors)
                        )
                    if pkg.all_extracted_fields:
                        with st.expander(
                            "Preview Extracted Fields (Sensitive Values Masked)",
                            expanded=False,
                        ):
                            for fn, ef in sorted(pkg.all_extracted_fields.items()):
                                st.write(
                                    f"- `{fn}`: **{mask_extracted_value(fn, ef.value, ef.masked_value)}** "
                                    f"(source=`{ef.source_document}`, page={ef.page_number}, "
                                    f"status=`{ef.validation_status}`)"
                                )
        else:
            st.caption(
                "No PDFs uploaded yet. Applications submitted without required documents fail closed for manual underwriting review."
            )

    # ------------------------------------------------------------------
    # Section 4: Submit Action
    # ------------------------------------------------------------------
    has_invalid_staged = any(u.get("status") == "INVALID" for u in staged)
    with st.container(border=True):
        render_section_heading(
            "4. Submit Application",
            "Persist applicant dossier and execute multi-agent underwriting evaluation",
        )
        sub_c1, sub_c2 = st.columns([2.5, 1], vertical_alignment="center")
        with sub_c1:
            allow_dup = st.checkbox(
                "Allow intentional re-submission of identical applicant & document payload",
                value=False,
                key="intake_allow_resubmit",
            )
        with sub_c2:
            if st.button(
                "Reset Form Draft", key="btn_reset_draft", width="stretch"
            ):
                clear_intake_after_submission(generate_applicant_reference())
                st.session_state[STATE_LAST_SUBMISSION_RECEIPT] = None
                st.rerun()

        submit_disabled = (
            bool(all_errors)
            or has_invalid_staged
            or role_blocked
            or st.session_state.get(STATE_SUBMISSION_IN_PROGRESS, False)
        )

        if st.button(
            "Submit & Run Underwriting Pipeline",
            type="primary",
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
                        submitted_by_user_id=auth_user.user_id if auth_user else None,
                        submitted_by_username=auth_user.username if auth_user else None,
                        submitted_by_role=auth_user.role.value if auth_user else None,
                    )
            except Exception as exc:
                st.session_state[STATE_SUBMISSION_IN_PROGRESS] = False
                st.error(f"Submission failed safely without corrupting state: {exc}")
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
