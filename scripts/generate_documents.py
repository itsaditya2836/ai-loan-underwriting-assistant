"""Realistic Sample Loan Document Generator for AI Loan Underwriting Assistant.

Generates complete 4-document packages for applicants APP0001 through APP0030:
1. Loan Application (loan_application.pdf)
2. Identity Verification (identity_proof.pdf)
3. Salary Slip / Income Statement (salary_slip.pdf / income_statement.pdf)
4. Bank Statement (bank_statement.pdf)

Includes controlled anomaly cohorts (Normal, Income Mismatch, Name Mismatch,
Missing Document, Financial Inconsistency, Borderline Cases) and scanned document format test cases.
Outputs document_manifest.csv and ground_truth.json.

ALL DATA AND DOCUMENTS ARE COMPLETELY SYNTHETIC AND CREATED FOR SOFTWARE TESTING ONLY.
"""

import json
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import pymupdf
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

RANDOM_SEED = 42
DOCUMENTS_DIR = "data/documents"
SYNTHETIC_DATA_DIR = "data/synthetic_data"


def get_styles() -> Dict[str, ParagraphStyle]:
    """Return reusable ReportLab paragraph styles."""
    base_styles = getSampleStyleSheet()
    custom_styles = {
        "Banner": ParagraphStyle(
            "Banner",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=colors.HexColor("#DC2626"),
            alignment=1,  # Centered
            spaceAfter=4,
        ),
        "Title": ParagraphStyle(
            "DocTitle",
            parent=base_styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=15,
            textColor=colors.HexColor("#1E3A8A"),
            alignment=1,
            spaceAfter=4,
        ),
        "SubTitle": ParagraphStyle(
            "DocSubTitle",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            textColor=colors.HexColor("#4B5563"),
            alignment=1,
            spaceAfter=8,
        ),
        "SectionHeader": ParagraphStyle(
            "SectionHeader",
            parent=base_styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=colors.HexColor("#1E3A8A"),
            spaceBefore=6,
            spaceAfter=4,
        ),
        "Body": ParagraphStyle(
            "Body",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            textColor=colors.HexColor("#1F2937"),
            leading=11,
        ),
        "CellBold": ParagraphStyle(
            "CellBold",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=colors.HexColor("#111827"),
            leading=10,
        ),
        "CellNormal": ParagraphStyle(
            "CellNormal",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=colors.HexColor("#374151"),
            leading=10,
        ),
        "Disclaimer": ParagraphStyle(
            "Disclaimer",
            parent=base_styles["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=7,
            textColor=colors.HexColor("#6B7280"),
            alignment=1,
            spaceBefore=10,
        ),
    }
    return custom_styles


def convert_pdf_to_scanned(pdf_path: str) -> None:
    """Rasterize a digital PDF into an image-only (scanned) PDF in-place."""
    src = pymupdf.open(pdf_path)
    dst = pymupdf.open()
    for page in src:
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        img_pdf = pymupdf.open("pdf", pymupdf.open("png", img_bytes).convert_to_pdf())
        dst.insert_pdf(img_pdf)
    src.close()
    dst.save(pdf_path, incremental=False)
    dst.close()


def generate_loan_application_pdf(
    applicant: Dict[str, Any], output_path: str, styles: Dict[str, ParagraphStyle]
) -> None:
    """Generate the synthetic Loan Application document."""
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    story = []

    # Banners and Header
    story.append(
        Paragraph("SYNTHETIC DOCUMENT — FOR SOFTWARE TESTING ONLY", styles["Banner"])
    )
    story.append(Paragraph("AI LOAN UNDERWRITING ASSISTANT", styles["Title"]))
    story.append(
        Paragraph(
            "SYNTHETIC LOAN APPLICATION FORM (PERSONAL / HOME LOAN)",
            styles["SubTitle"],
        )
    )
    story.append(
        HRFlowable(
            width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=8
        )
    )

    # Application Reference Box
    ref_data = [
        [
            Paragraph("Application ID:", styles["CellBold"]),
            Paragraph(
                f"APP-REQ-{applicant['applicant_id']}-2026", styles["CellNormal"]
            ),
            Paragraph("Submission Date:", styles["CellBold"]),
            Paragraph("15-Aug-2026", styles["CellNormal"]),
        ],
        [
            Paragraph("Applicant ID:", styles["CellBold"]),
            Paragraph(applicant["applicant_id"], styles["CellNormal"]),
            Paragraph("Facility Requested:", styles["CellBold"]),
            Paragraph(
                "Home Loan" if applicant["loan_amount"] >= 2500000 else "Personal Loan",
                styles["CellNormal"],
            ),
        ],
    ]
    t_ref = Table(ref_data, colWidths=[90, 180, 95, 175])
    t_ref.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_ref)
    story.append(Spacer(1, 8))

    # Personal Information Section
    story.append(Paragraph("1. Personal Details", styles["SectionHeader"]))
    personal_data = [
        [
            Paragraph("Full Name:", styles["CellBold"]),
            Paragraph(applicant["name"], styles["CellNormal"]),
            Paragraph("Gender / Age:", styles["CellBold"]),
            Paragraph(
                f"{applicant['gender']} / {applicant['age']} Years",
                styles["CellNormal"],
            ),
        ],
        [
            Paragraph("City of Residence:", styles["CellBold"]),
            Paragraph(applicant["city"], styles["CellNormal"]),
            Paragraph("Number of Dependents:", styles["CellBold"]),
            Paragraph(str(applicant["number_of_dependents"]), styles["CellNormal"]),
        ],
    ]
    t_personal = Table(personal_data, colWidths=[90, 180, 95, 175])
    t_personal.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_personal)
    story.append(Spacer(1, 8))

    # Employment & Income Details
    story.append(
        Paragraph("2. Employment & Financial Information", styles["SectionHeader"])
    )
    emp_data = [
        [
            Paragraph("Employment Type:", styles["CellBold"]),
            Paragraph(applicant["employment_type"], styles["CellNormal"]),
            Paragraph("Employer / Business:", styles["CellBold"]),
            Paragraph(applicant["employer_name"], styles["CellNormal"]),
        ],
        [
            Paragraph("Experience / Tenure:", styles["CellBold"]),
            Paragraph(f"{applicant['employment_years']} Years", styles["CellNormal"]),
            Paragraph("Declared Monthly Income:", styles["CellBold"]),
            Paragraph(f"INR {applicant['monthly_income']:,.2f}", styles["CellNormal"]),
        ],
        [
            Paragraph("Existing Monthly EMI:", styles["CellBold"]),
            Paragraph(f"INR {applicant['existing_emi']:,.2f}", styles["CellNormal"]),
            Paragraph("Declared Bank Balance:", styles["CellBold"]),
            Paragraph(f"INR {applicant['bank_balance']:,.2f}", styles["CellNormal"]),
        ],
        [
            Paragraph("Monthly Expenses:", styles["CellBold"]),
            Paragraph(
                f"INR {applicant['monthly_expenses']:,.2f}", styles["CellNormal"]
            ),
            Paragraph("Self-Reported Credit Score:", styles["CellBold"]),
            Paragraph(str(applicant["credit_score"]), styles["CellNormal"]),
        ],
    ]
    t_emp = Table(emp_data, colWidths=[90, 180, 95, 175])
    t_emp.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_emp)
    story.append(Spacer(1, 8))

    # Requested Facility
    story.append(Paragraph("3. Loan Request & Structure", styles["SectionHeader"]))
    loan_data = [
        [
            Paragraph("Requested Amount:", styles["CellBold"]),
            Paragraph(f"INR {applicant['loan_amount']:,.2f}", styles["CellNormal"]),
            Paragraph("Requested Tenure:", styles["CellBold"]),
            Paragraph(
                f"{applicant['loan_tenure']} Months ({round(applicant['loan_tenure']/12, 1)} Yrs)",
                styles["CellNormal"],
            ),
        ],
        [
            Paragraph("Estimated Monthly EMI:", styles["CellBold"]),
            Paragraph(
                f"INR {applicant['estimated_new_emi']:,.2f} (approx)",
                styles["CellNormal"],
            ),
            Paragraph("Loan Purpose:", styles["CellBold"]),
            Paragraph("Debt Consolidation / Asset Enhancement", styles["CellNormal"]),
        ],
    ]
    t_loan = Table(loan_data, colWidths=[90, 180, 95, 175])
    t_loan.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_loan)
    story.append(Spacer(1, 14))

    # Declaration Statement
    declaration_text = (
        "I hereby declare that all particulars stated above are true, complete, and correct. "
        "I authorize the underwriting team and automated underwriting support systems to verify "
        "all information and analyze uploaded documents solely for loan evaluation."
    )
    story.append(Paragraph(declaration_text, styles["Body"]))
    story.append(Spacer(1, 10))

    # Signature Block
    sig_data = [
        [
            Paragraph(
                f"Applicant Signature: <i>{applicant['name']}</i>", styles["Body"]
            ),
            Paragraph("Place: " + applicant["city"], styles["Body"]),
            Paragraph("Date: 15-Aug-2026", styles["Body"]),
        ]
    ]
    t_sig = Table(sig_data, colWidths=[240, 150, 150])
    story.append(t_sig)

    story.append(
        Paragraph(
            "DISCLAIMER: SYNTHETIC SOFTWARE TESTING DOCUMENT ONLY. NOT A REAL LOAN APPLICATION.",
            styles["Disclaimer"],
        )
    )

    doc.build(story)


def generate_identity_pdf(
    applicant: Dict[str, Any],
    output_path: str,
    styles: Dict[str, ParagraphStyle],
    name_override: Optional[str] = None,
) -> None:
    """Generate synthetic Identity Verification document."""
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=40,
        bottomMargin=40,
    )
    story = []

    display_name = name_override if name_override else applicant["name"]
    doc_hash = abs(hash(applicant["applicant_id"] + display_name)) % 90000 + 10000
    syn_ref = f"SYN-ID-{applicant['applicant_id']}-{doc_hash}"

    story.append(
        Paragraph("SYNTHETIC DOCUMENT — FOR SOFTWARE TESTING ONLY", styles["Banner"])
    )
    story.append(Paragraph("SYNTHETIC IDENTITY VERIFICATION RECORD", styles["Title"]))
    story.append(
        Paragraph(
            "SIMULATED CITIZEN RECORD (NOT A GOVERNMENT IDENTIFICATION DOCUMENT)",
            styles["SubTitle"],
        )
    )
    story.append(
        HRFlowable(
            width="100%", thickness=1.5, color=colors.HexColor("#2563EB"), spaceAfter=12
        )
    )

    # Notice Card
    notice_text = (
        "<b>OFFICIAL NOTICE:</b> This verification certificate is synthetically generated "
        "to evaluate automated OCR and name-matching algorithms. It is not an Aadhaar card, "
        "PAN card, passport, voter ID, or driving license."
    )
    t_notice = Table([[Paragraph(notice_text, styles["Body"])]], colWidths=[530])
    t_notice.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#93C5FD")),
                ("PADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(t_notice)
    story.append(Spacer(1, 14))

    # Identity Details Table with Photo placeholder
    photo_placeholder = Paragraph(
        "<br/><br/>[ SYNTHETIC<br/>APPLICANT PHOTO<br/>PLACEHOLDER ]<br/><br/>",
        styles["CellBold"],
    )

    details_table_data = [
        [
            Paragraph("Synthetic ID Ref:", styles["CellBold"]),
            Paragraph(syn_ref, styles["CellBold"]),
        ],
        [
            Paragraph("Applicant ID:", styles["CellBold"]),
            Paragraph(applicant["applicant_id"], styles["CellNormal"]),
        ],
        [
            Paragraph("Full Legal Name:", styles["CellBold"]),
            Paragraph(display_name, styles["CellNormal"]),
        ],
        [
            Paragraph("Age / Gender:", styles["CellBold"]),
            Paragraph(
                f"{applicant['age']} Years / {applicant['gender']}",
                styles["CellNormal"],
            ),
        ],
        [
            Paragraph("Registered City:", styles["CellBold"]),
            Paragraph(applicant["city"], styles["CellNormal"]),
        ],
        [
            Paragraph("Status:", styles["CellBold"]),
            Paragraph("Active & Verified (Simulation Database)", styles["CellNormal"]),
        ],
        [
            Paragraph("Issue Date:", styles["CellBold"]),
            Paragraph("01-Jan-2022", styles["CellNormal"]),
        ],
    ]
    t_details = Table(details_table_data, colWidths=[120, 260])
    t_details.setStyle(
        TableStyle(
            [
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )

    main_id_table = Table([[photo_placeholder, t_details]], colWidths=[130, 400])
    main_id_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#F1F5F9")),
                ("BOX", (0, 0), (0, 0), 1, colors.HexColor("#94A3B8")),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("PADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(main_id_table)
    story.append(Spacer(1, 20))

    auth_box = [
        [
            Paragraph(
                "Verification Agency: Synthetic Identity Services Authority",
                styles["Body"],
            ),
            Paragraph("Security Hash: SHA256-SYN-0941829", styles["Body"]),
        ]
    ]
    t_auth = Table(auth_box, colWidths=[330, 200])
    story.append(t_auth)

    story.append(
        Paragraph(
            "SYNTHETIC RECORD — NOT A GOVERNMENT ID. CREATED EXCLUSIVELY FOR SOFTWARE TESTING.",
            styles["Disclaimer"],
        )
    )

    doc.build(story)


def generate_salary_slip_pdf(
    applicant: Dict[str, Any],
    output_path: str,
    styles: Dict[str, ParagraphStyle],
    name_override: Optional[str] = None,
    income_override: Optional[float] = None,
) -> None:
    """Generate synthetic Monthly Salary Slip (or Income Statement for self-employed)."""
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    story = []

    display_name = name_override if name_override else applicant["name"]
    net_salary = (
        income_override if income_override is not None else applicant["monthly_income"]
    )

    is_salaried = applicant["employment_type"] == "SALARIED"

    story.append(
        Paragraph("SYNTHETIC DOCUMENT — FOR SOFTWARE TESTING ONLY", styles["Banner"])
    )
    story.append(Paragraph(applicant["employer_name"].upper(), styles["Title"]))
    doc_type_title = (
        "PAYSLIP FOR THE MONTH OF AUGUST 2026"
        if is_salaried
        else "MONTHLY INCOME & REVENUE STATEMENT - AUGUST 2026"
    )
    story.append(Paragraph(doc_type_title, styles["SubTitle"]))
    story.append(
        HRFlowable(
            width="100%", thickness=1, color=colors.HexColor("#0284C7"), spaceAfter=8
        )
    )

    # Employee / Business metadata
    meta_data = [
        [
            Paragraph("Name:", styles["CellBold"]),
            Paragraph(display_name, styles["CellNormal"]),
            Paragraph("Period:", styles["CellBold"]),
            Paragraph("01-Aug-2026 to 31-Aug-2026", styles["CellNormal"]),
        ],
        [
            Paragraph("Identifier:", styles["CellBold"]),
            Paragraph(f"EMP-{applicant['applicant_id']}", styles["CellNormal"]),
            Paragraph("City:", styles["CellBold"]),
            Paragraph(applicant["city"], styles["CellNormal"]),
        ],
        [
            Paragraph("Designation:", styles["CellBold"]),
            Paragraph(
                "Lead Consultant" if is_salaried else "Proprietor / Partner",
                styles["CellNormal"],
            ),
            Paragraph("Days Paid:", styles["CellBold"]),
            Paragraph("30", styles["CellNormal"]),
        ],
    ]
    t_meta = Table(meta_data, colWidths=[80, 185, 80, 195])
    t_meta.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_meta)
    story.append(Spacer(1, 10))

    # Construct balanced Earnings and Deductions
    # Gross = Net + Deductions
    # Let Deductions = approx 12% of Net, ensuring exact arithmetic:
    # basic + allowances - deductions = net
    deductions_total = round(net_salary * 0.12, 2)
    gross_earnings = round(net_salary + deductions_total, 2)

    basic = round(gross_earnings * 0.50, 2)
    hra = round(gross_earnings * 0.25, 2)
    special = round(gross_earnings * 0.15, 2)
    conveyance = round(gross_earnings - (basic + hra + special), 2)

    pf = round(deductions_total * 0.70, 2)
    pt = 200.00
    tds = round(deductions_total - (pf + pt), 2)

    breakdown_data = [
        [
            Paragraph("Earnings Component", styles["CellBold"]),
            Paragraph("Amount (INR)", styles["CellBold"]),
            Paragraph("Deductions Component", styles["CellBold"]),
            Paragraph("Amount (INR)", styles["CellBold"]),
        ],
        [
            Paragraph(
                "Basic Salary" if is_salaried else "Gross Revenue Share",
                styles["CellNormal"],
            ),
            Paragraph(f"{basic:,.2f}", styles["CellNormal"]),
            Paragraph(
                "Provident Fund (PF)" if is_salaried else "Retirement Reserve",
                styles["CellNormal"],
            ),
            Paragraph(f"{pf:,.2f}", styles["CellNormal"]),
        ],
        [
            Paragraph(
                (
                    "House Rent Allowance (HRA)"
                    if is_salaried
                    else "Operational Allocation"
                ),
                styles["CellNormal"],
            ),
            Paragraph(f"{hra:,.2f}", styles["CellNormal"]),
            Paragraph("Professional Tax", styles["CellNormal"]),
            Paragraph(f"{pt:,.2f}", styles["CellNormal"]),
        ],
        [
            Paragraph(
                "Special Allowance" if is_salaried else "Drawings Allowance",
                styles["CellNormal"],
            ),
            Paragraph(f"{special:,.2f}", styles["CellNormal"]),
            Paragraph("Income Tax (TDS)", styles["CellNormal"]),
            Paragraph(f"{tds:,.2f}", styles["CellNormal"]),
        ],
        [
            Paragraph("Conveyance / Other", styles["CellNormal"]),
            Paragraph(f"{conveyance:,.2f}", styles["CellNormal"]),
            Paragraph("-", styles["CellNormal"]),
            Paragraph("-", styles["CellNormal"]),
        ],
        [
            Paragraph("Total Gross Earnings", styles["CellBold"]),
            Paragraph(f"{gross_earnings:,.2f}", styles["CellBold"]),
            Paragraph("Total Deductions", styles["CellBold"]),
            Paragraph(f"{deductions_total:,.2f}", styles["CellBold"]),
        ],
    ]

    t_breakdown = Table(breakdown_data, colWidths=[155, 115, 155, 115])
    t_breakdown.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E0F2FE")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F1F5F9")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#0284C7")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_breakdown)
    story.append(Spacer(1, 10))

    # Net Pay Summary Box
    net_box = [
        [
            Paragraph("<b>NET SALARY PAYABLE:</b>", styles["SectionHeader"]),
            Paragraph(f"<b>INR {net_salary:,.2f}</b>", styles["SectionHeader"]),
        ]
    ]
    t_net = Table(net_box, colWidths=[270, 270])
    t_net.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ECFDF5")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#10B981")),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(t_net)
    story.append(Spacer(1, 12))

    story.append(
        Paragraph(
            "Note: This payslip is electronically generated by the synthetic payroll system. No physical signature required.",
            styles["Body"],
        )
    )
    story.append(
        Paragraph(
            "DISCLAIMER: SYNTHETIC SOFTWARE TESTING DOCUMENT ONLY. NOT REAL FINANCIAL RECORDS.",
            styles["Disclaimer"],
        )
    )

    doc.build(story)


def generate_bank_statement_pdf(
    applicant: Dict[str, Any],
    output_path: str,
    styles: Dict[str, ParagraphStyle],
    salary_credit_override: Optional[float] = None,
    closing_balance_override: Optional[float] = None,
    emi_debit_override: Optional[float] = None,
    rng_seed: int = 100,
) -> None:
    """Generate synthetic Bank Statement with verified transaction arithmetic."""
    _ = rng_seed
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=30,
        rightMargin=30,
        topMargin=30,
        bottomMargin=30,
    )
    story = []

    salary_credit = (
        salary_credit_override
        if salary_credit_override is not None
        else applicant["monthly_income"]
    )
    existing_emi_debit = (
        emi_debit_override
        if emi_debit_override is not None
        else applicant["existing_emi"]
    )

    # Calculate realistic opening and closing balance
    target_closing = (
        closing_balance_override
        if closing_balance_override is not None
        else applicant["bank_balance"]
    )

    story.append(
        Paragraph("SYNTHETIC DOCUMENT — FOR SOFTWARE TESTING ONLY", styles["Banner"])
    )
    story.append(Paragraph("SYNTHETIC APEX BANK OF INDIA", styles["Title"]))
    story.append(
        Paragraph(
            "ACCOUNT STATEMENT FOR SOFTWARE EVALUATION (SIMULATED ENTITY)",
            styles["SubTitle"],
        )
    )
    story.append(
        HRFlowable(
            width="100%", thickness=1, color=colors.HexColor("#047857"), spaceAfter=8
        )
    )

    # Header Account Info
    acc_num = f"SYN-ACC-9041-{applicant['applicant_id']}-82"
    acc_data = [
        [
            Paragraph("Account Holder:", styles["CellBold"]),
            Paragraph(applicant["name"], styles["CellNormal"]),
            Paragraph("Statement Period:", styles["CellBold"]),
            Paragraph("01-Aug-2026 to 31-Aug-2026", styles["CellNormal"]),
        ],
        [
            Paragraph("Account Number:", styles["CellBold"]),
            Paragraph(acc_num, styles["CellNormal"]),
            Paragraph("Account Type / Branch:", styles["CellBold"]),
            Paragraph(f"Savings / {applicant['city']} Main", styles["CellNormal"]),
        ],
    ]
    t_acc = Table(acc_data, colWidths=[90, 190, 100, 160])
    t_acc.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(t_acc)
    story.append(Spacer(1, 8))

    # Generate realistic, arithmetically exact transactions
    # Build 18 transactions
    # We will compute transactions such that opening_balance + sum(credits) - sum(debits) = target_closing
    # Typical credits: Salary credit (on Aug 01), Cashback / Refund (Aug 14)
    # Typical debits: EMI (Aug 05), Rent (Aug 03), Utilities (Aug 08), Groceries, Dining, Transfers
    txn_templates = [
        (
            "01-Aug-2026",
            f"SALARY CREDIT - {applicant['employer_name'][:20]}",
            "CR",
            salary_credit,
        ),
        (
            "03-Aug-2026",
            "RENT PAYMENT - VIA UPI",
            "DR",
            round(applicant["monthly_income"] * 0.22, 2),
        ),
    ]
    if existing_emi_debit > 0:
        txn_templates.append(
            ("05-Aug-2026", "RECURRING LOAN EMI AUTO-DEBIT", "DR", existing_emi_debit)
        )
    txn_templates.extend(
        [
            ("07-Aug-2026", "ELECTRICITY BILL - STATE DISCOM", "DR", 2850.00),
            ("09-Aug-2026", "GROCERY SUPERSTORE - POS", "DR", 4500.00),
            ("12-Aug-2026", "ONLINE SHOPPING - E-COMMERCE", "DR", 3200.00),
            ("14-Aug-2026", "INTEREST CREDIT - Q2", "CR", 850.00),
            ("16-Aug-2026", "ATM CASH WITHDRAWAL", "DR", 5000.00),
            ("18-Aug-2026", "RESTAURANT & DINING - UPI", "DR", 1850.00),
            ("20-Aug-2026", "MOBILE & FIBER BROADBAND", "DR", 1499.00),
            ("22-Aug-2026", "FUEL STATION PAYMENT - POS", "DR", 2500.00),
            ("25-Aug-2026", "PHARMACY HEALTHCARE - POS", "DR", 1250.00),
            ("27-Aug-2026", "DOMESTIC UTILITIES WATER", "DR", 650.00),
            ("29-Aug-2026", "PEER TRANSFER TO FAMILY", "DR", 4000.00),
        ]
    )

    total_credits = sum(amt for _, _, t_type, amt in txn_templates if t_type == "CR")
    total_debits = sum(amt for _, _, t_type, amt in txn_templates if t_type == "DR")
    net_flow = total_credits - total_debits

    # Solve for opening balance: opening_balance + net_flow = target_closing
    opening_balance = round(target_closing - net_flow, 2)
    # If opening balance happens to be negative, adjust with an additional deposit
    if opening_balance < 10000:
        adjustment = round(15000 - opening_balance, 2)
        txn_templates.insert(
            2, ("04-Aug-2026", "MUTUAL FUND REDEMPTION / REFUND", "CR", adjustment)
        )
        total_credits += adjustment
        opening_balance = 15000.00

    # Build running balance
    table_rows = [
        [
            Paragraph("Date", styles["CellBold"]),
            Paragraph("Description", styles["CellBold"]),
            Paragraph("Ref / Chq", styles["CellBold"]),
            Paragraph("Debit (INR)", styles["CellBold"]),
            Paragraph("Credit (INR)", styles["CellBold"]),
            Paragraph("Balance (INR)", styles["CellBold"]),
        ]
    ]

    running_bal = opening_balance
    for idx, (t_date, desc, t_type, amt) in enumerate(txn_templates):
        ref_no = f"TXN{idx + 101:04d}"
        if t_type == "CR":
            running_bal += amt
            dr_str, cr_str = "-", f"{amt:,.2f}"
        else:
            running_bal -= amt
            dr_str, cr_str = f"{amt:,.2f}", "-"
        running_bal = round(running_bal, 2)

        table_rows.append(
            [
                Paragraph(t_date, styles["CellNormal"]),
                Paragraph(desc, styles["CellNormal"]),
                Paragraph(ref_no, styles["CellNormal"]),
                Paragraph(dr_str, styles["CellNormal"]),
                Paragraph(cr_str, styles["CellNormal"]),
                Paragraph(f"{running_bal:,.2f}", styles["CellNormal"]),
            ]
        )

    final_closing_balance = running_bal

    t_txns = Table(table_rows, colWidths=[65, 175, 65, 75, 75, 85])
    t_txns.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D1FAE5")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#059669")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    story.append(t_txns)
    story.append(Spacer(1, 8))

    # Statement Balance Summary
    summary_data = [
        [
            Paragraph(
                f"Opening Balance: <b>INR {opening_balance:,.2f}</b>", styles["Body"]
            ),
            Paragraph(
                f"Total Credits: <b>INR {total_credits:,.2f}</b>", styles["Body"]
            ),
            Paragraph(f"Total Debits: <b>INR {total_debits:,.2f}</b>", styles["Body"]),
            Paragraph(
                f"Closing Balance: <b>INR {final_closing_balance:,.2f}</b>",
                styles["CellBold"],
            ),
        ]
    ]
    t_summary = Table(summary_data, colWidths=[135, 135, 135, 135])
    t_summary.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0FDF4")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#86EFAC")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t_summary)

    story.append(
        Paragraph(
            "DISCLAIMER: SYNTHETIC BANK STATEMENT FOR ALGORITHMIC EVALUATION ONLY. NOT A REAL FINANCIAL DOCUMENT.",
            styles["Disclaimer"],
        )
    )

    doc.build(story)


def generate_documents() -> None:
    """Generate all document packages and metadata for applicants APP0001 through APP0030."""
    os.makedirs(DOCUMENTS_DIR, exist_ok=True)
    os.makedirs(SYNTHETIC_DATA_DIR, exist_ok=True)

    applicants_path = os.path.join(SYNTHETIC_DATA_DIR, "applicants.json")
    if not os.path.exists(applicants_path):
        raise FileNotFoundError(
            f"Applicants dataset not found at {applicants_path}. Run generate_synthetic_dataset.py first."
        )

    with open(applicants_path, "r", encoding="utf-8") as f:
        all_applicants = json.load(f)

    # Select APP0001 to APP0030
    selected_applicants = [
        a for a in all_applicants if int(a["applicant_id"].replace("APP", "")) <= 30
    ]

    styles = get_styles()
    manifest_rows: List[Dict[str, Any]] = []
    ground_truth: Dict[str, Any] = {}

    # Scanned format targets:
    # 2 salary slips: APP0004, APP0009
    # 2 bank statements: APP0005, APP0010
    scanned_salary_targets = {"APP0004", "APP0009"}
    scanned_bank_targets = {"APP0005", "APP0010"}

    for applicant in selected_applicants:
        app_id = applicant["applicant_id"]
        app_num = int(app_id.replace("APP", ""))
        app_dir = os.path.join(DOCUMENTS_DIR, app_id)
        os.makedirs(app_dir, exist_ok=True)
        # Clean existing PDFs in app_dir for clean regeneration
        for old_f in os.listdir(app_dir):
            if old_f.endswith(".pdf"):
                os.remove(os.path.join(app_dir, old_f))

        expected_docs = [
            "loan_application",
            "identity_verification",
            (
                "salary_slip"
                if applicant["employment_type"] == "SALARIED"
                else "income_statement"
            ),
            "bank_statement",
        ]
        missing_docs = []
        anomalies: List[Dict[str, Any]] = []
        notes: Optional[str] = None

        # -------------------------------------------------------------
        # 1. Loan Application Document (Always Generated)
        # -------------------------------------------------------------
        loan_pdf_name = "loan_application.pdf"
        loan_pdf_path = os.path.join(app_dir, loan_pdf_name)
        generate_loan_application_pdf(applicant, loan_pdf_path, styles)

        manifest_rows.append(
            {
                "document_id": f"DOC-{app_id}-LOAN",
                "applicant_id": app_id,
                "document_type": "loan_application",
                "file_path": loan_pdf_path,
                "expected_present": True,
                "contains_anomaly": False,
                "anomaly_type": "",
                "document_format": "text_pdf",
            }
        )

        # -------------------------------------------------------------
        # 2. Identity Document
        # Missing case for APP0018
        # -------------------------------------------------------------
        id_pdf_name = "identity_proof.pdf"
        id_pdf_path = os.path.join(app_dir, id_pdf_name)

        if app_num == 18:
            missing_docs.append("identity_verification")
            anomalies.append(
                {
                    "type": "MISSING_DOCUMENT",
                    "field": "identity_verification",
                    "details": "Identity verification document is missing from the package.",
                }
            )
            manifest_rows.append(
                {
                    "document_id": f"DOC-{app_id}-ID",
                    "applicant_id": app_id,
                    "document_type": "identity_verification",
                    "file_path": id_pdf_path,
                    "expected_present": False,
                    "contains_anomaly": True,
                    "anomaly_type": "MISSING_DOCUMENT",
                    "document_format": "none",
                }
            )
        else:
            generate_identity_pdf(applicant, id_pdf_path, styles)
            manifest_rows.append(
                {
                    "document_id": f"DOC-{app_id}-ID",
                    "applicant_id": app_id,
                    "document_type": "identity_verification",
                    "file_path": id_pdf_path,
                    "expected_present": True,
                    "contains_anomaly": False,
                    "anomaly_type": "",
                    "document_format": "text_pdf",
                }
            )

        # -------------------------------------------------------------
        # 3. Salary Slip / Income Document
        # Missing case for APP0017 and APP0020
        # Name Mismatch for APP0011..APP0015
        # Scanned format for APP0004 and APP0009
        # -------------------------------------------------------------
        income_doc_type = (
            "salary_slip"
            if applicant["employment_type"] == "SALARIED"
            else "income_statement"
        )
        salary_pdf_name = (
            "salary_slip.pdf"
            if applicant["employment_type"] == "SALARIED"
            else "income_statement.pdf"
        )
        salary_pdf_path = os.path.join(app_dir, salary_pdf_name)

        if app_num in [17, 20]:
            missing_docs.append(income_doc_type)
            anomalies.append(
                {
                    "type": "MISSING_DOCUMENT",
                    "field": income_doc_type,
                    "details": f"{income_doc_type} is missing from the application package.",
                }
            )
            manifest_rows.append(
                {
                    "document_id": f"DOC-{app_id}-SALARY",
                    "applicant_id": app_id,
                    "document_type": income_doc_type,
                    "file_path": salary_pdf_path,
                    "expected_present": False,
                    "contains_anomaly": True,
                    "anomaly_type": "MISSING_DOCUMENT",
                    "document_format": "none",
                }
            )
        else:
            # Check for Name Mismatch (APP0011..APP0015)
            salary_name_override = None
            contains_salary_anomaly = False
            salary_anomaly_type = ""

            if 11 <= app_num <= 15:
                # Deliberate name mismatch on salary slip
                name_parts = applicant["name"].split()
                first_name_mismatches = {
                    11: "Rohan",
                    12: "Pooja",
                    13: "Vikas",
                    14: "Sneha",
                    15: "Varun",
                }
                mismatched_first = first_name_mismatches.get(app_num, "Ramesh")
                salary_name_override = f"{mismatched_first} {name_parts[-1]}"
                contains_salary_anomaly = True
                salary_anomaly_type = "NAME_MISMATCH"

                anomalies.append(
                    {
                        "type": "NAME_MISMATCH",
                        "field": "name",
                        "declared_value": applicant["name"],
                        "documented_value": salary_name_override,
                        "document_affected": income_doc_type,
                        "details": f"{income_doc_type} name does not match declared applicant name.",
                    }
                )

            generate_salary_slip_pdf(
                applicant,
                salary_pdf_path,
                styles,
                name_override=salary_name_override,
            )

            # Check if scanned format target
            doc_format = "text_pdf"
            if app_id in scanned_salary_targets:
                convert_pdf_to_scanned(salary_pdf_path)
                doc_format = "scanned"

            manifest_rows.append(
                {
                    "document_id": f"DOC-{app_id}-SALARY",
                    "applicant_id": app_id,
                    "document_type": income_doc_type,
                    "file_path": salary_pdf_path,
                    "expected_present": True,
                    "contains_anomaly": contains_salary_anomaly,
                    "anomaly_type": salary_anomaly_type,
                    "document_format": doc_format,
                }
            )

        # -------------------------------------------------------------
        # 4. Bank Statement
        # Missing case for APP0016 and APP0019
        # Income Mismatch for APP0006..APP0010
        # Financial Inconsistency for APP0021..APP0025
        # Scanned format for APP0005 and APP0010
        # -------------------------------------------------------------
        bank_pdf_name = "bank_statement.pdf"
        bank_pdf_path = os.path.join(app_dir, bank_pdf_name)

        if app_num in [16, 19]:
            missing_docs.append("bank_statement")
            anomalies.append(
                {
                    "type": "MISSING_DOCUMENT",
                    "field": "bank_statement",
                    "details": "Bank statement document is missing from the package.",
                }
            )
            manifest_rows.append(
                {
                    "document_id": f"DOC-{app_id}-BANK",
                    "applicant_id": app_id,
                    "document_type": "bank_statement",
                    "file_path": bank_pdf_path,
                    "expected_present": False,
                    "contains_anomaly": True,
                    "anomaly_type": "MISSING_DOCUMENT",
                    "document_format": "none",
                }
            )
        else:
            salary_credit_override = None
            closing_balance_override = None
            emi_debit_override = None
            contains_bank_anomaly = False
            bank_anomaly_type = ""

            # Income Mismatch Cohort (APP0006..APP0010)
            if 6 <= app_num <= 10:
                # Bank salary credit is significantly lower (~65% of declared income)
                salary_credit_override = round(applicant["monthly_income"] * 0.65, 2)
                contains_bank_anomaly = True
                bank_anomaly_type = "INCOME_MISMATCH"
                anomalies.append(
                    {
                        "type": "INCOME_MISMATCH",
                        "field": "monthly_income",
                        "declared_value": applicant["monthly_income"],
                        "documented_value": salary_credit_override,
                        "document_affected": "bank_statement",
                        "details": "Bank statement salary credit is substantially lower than declared income.",
                    }
                )

            # Financial Inconsistency Cohort (APP0021..APP0025)
            # Treated strictly as FINANCIAL_INCONSISTENCY / ANOMALY flags per user requirement
            elif 21 <= app_num <= 25:
                contains_bank_anomaly = True
                bank_anomaly_type = "FINANCIAL_INCONSISTENCY"

                if app_num in [21, 23, 25]:
                    # Undisclosed higher existing EMI recurring payments
                    emi_debit_override = round(applicant["existing_emi"] + 15000.0, 2)
                    anomalies.append(
                        {
                            "type": "FINANCIAL_INCONSISTENCY",
                            "field": "existing_emi",
                            "declared_value": applicant["existing_emi"],
                            "documented_value": emi_debit_override,
                            "document_affected": "bank_statement",
                            "details": "Bank statement exhibits undisclosed ongoing recurring loan EMI debits.",
                        }
                    )
                else:  # 22, 24
                    # Large discrepancy in closing bank balance vs declared balance
                    closing_balance_override = round(
                        applicant["bank_balance"] * 0.25, 2
                    )
                    anomalies.append(
                        {
                            "type": "FINANCIAL_INCONSISTENCY",
                            "field": "bank_balance",
                            "declared_value": applicant["bank_balance"],
                            "documented_value": closing_balance_override,
                            "document_affected": "bank_statement",
                            "details": "Verified bank statement closing balance is significantly lower than declared balance.",
                        }
                    )

            # Borderline Cases (APP0026..APP0030)
            elif 26 <= app_num <= 30:
                notes = "Borderline applicant metrics (credit score / DTI near threshold) for manual review evaluation."

            generate_bank_statement_pdf(
                applicant,
                bank_pdf_path,
                styles,
                salary_credit_override=salary_credit_override,
                closing_balance_override=closing_balance_override,
                emi_debit_override=emi_debit_override,
                rng_seed=100 + app_num,
            )

            # Check if scanned format target
            doc_format = "text_pdf"
            if app_id in scanned_bank_targets:
                convert_pdf_to_scanned(bank_pdf_path)
                doc_format = "scanned"

            manifest_rows.append(
                {
                    "document_id": f"DOC-{app_id}-BANK",
                    "applicant_id": app_id,
                    "document_type": "bank_statement",
                    "file_path": bank_pdf_path,
                    "expected_present": True,
                    "contains_anomaly": contains_bank_anomaly,
                    "anomaly_type": bank_anomaly_type,
                    "document_format": doc_format,
                }
            )

        # Assemble ground truth record for this applicant
        ground_truth[app_id] = {
            "applicant_id": app_id,
            "name": applicant["name"],
            "profile_category": applicant["profile_category"],
            "declared_monthly_income": applicant["monthly_income"],
            "declared_existing_emi": applicant["existing_emi"],
            "declared_bank_balance": applicant["bank_balance"],
            "expected_document_types": expected_docs,
            "missing_documents": missing_docs,
            "has_anomalies": len(anomalies) > 0,
            "anomalies": anomalies,
            "notes": notes,
        }

    # Save document manifest CSV
    manifest_df = pd.DataFrame(manifest_rows)
    manifest_path = os.path.join(SYNTHETIC_DATA_DIR, "document_manifest.csv")
    manifest_df.to_csv(manifest_path, index=False)
    print(
        f"Saved document manifest to {manifest_path} with {len(manifest_df)} records."
    )

    # Save ground truth JSON
    gt_path = os.path.join(SYNTHETIC_DATA_DIR, "ground_truth.json")
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump(ground_truth, f, indent=2)
    print(f"Saved ground truth metadata to {gt_path} for {len(ground_truth)} packages.")


def main() -> None:
    """Generate documents, manifest, and ground truth."""
    generate_documents()


if __name__ == "__main__":
    main()
