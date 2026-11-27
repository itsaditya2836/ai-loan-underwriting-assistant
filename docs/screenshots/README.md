# Application Screenshots Index

Genuine PNG screenshots captured via headless Chrome from isolated live Streamlit (`app/main.py`) and FastAPI (`app/api/main.py`) runs over **100% synthetic** applicant records (zero real credentials or PII):

| File | Screen / View |
| :--- | :--- |
| [`01_login_screen.png`](01_login_screen.png) | Streamlit RBAC authentication gate (`STREAMLIT_AUTH_REQUIRED=true`) |
| [`02_dashboard.png`](02_dashboard.png) | Underwriting Portfolio Dashboard KPIs & separated review metrics |
| [`03_applicant_intake.png`](03_applicant_intake.png) | New Loan Application schema-validated intake form |
| [`04_applicant_details.png`](04_applicant_details.png) | Application Details profile (`APP0001`) & separated AI vs Human state |
| [`05_document_review.png`](05_document_review.png) | Document Review per-PDF telemetry, page counts & masked extracted fields |
| [`06_underwriting_results.png`](06_underwriting_results.png) | Underwriting Results explainability, decision banner & audit confirmation |
| [`07_review_queue.png`](07_review_queue.png) | Underwriter Review Queue summary metrics, filters & triage table |
| [`08_human_review_decision.png`](08_human_review_decision.png) | Submit Human Underwriter Decision form & inspection tabs |
| [`09_audit_history.png`](09_audit_history.png) | Read-only Audit History & append-only `HUMAN_REVIEW_EVENT` inspection |
| [`10_fastapi_docs.png`](10_fastapi_docs.png) | FastAPI `/api/docs` OpenAPI specification for `/api/v1` routes |
