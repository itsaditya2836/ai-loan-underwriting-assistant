"""Application entry point.

Serves as the main launchpad for both:
1. Streamlit Dashboard: `streamlit run app/main.py`
2. CLI verification and database setup: `python app/main.py`
"""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st

from app.database import init_db
from app.ui.dashboard import render_dashboard
from app.utils.helpers import get_logger, setup_logging
from config.settings import get_settings


def run_cli_verification() -> None:
    """Initialize configuration, database, logging, and verify application health."""
    setup_logging()
    settings = get_settings()
    logger = get_logger("app.main")
    logger.info(
        f"AI Loan Underwriting Assistant initialized in '{settings.app_env}' mode."
    )
    init_db()
    logger.info("Database and audit tables initialized successfully.")
    print("AI Loan Underwriting Assistant initialized successfully.")
    print("To launch the Streamlit dashboard, run:")
    print("    .venv/bin/streamlit run app/main.py")


# Streamlit execution detection
if st.runtime.exists():
    render_dashboard()
elif __name__ == "__main__":
    run_cli_verification()
