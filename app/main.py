"""Application entry point.

Verifies that the application package, configuration, and logging
can be cleanly initialized.
"""

from app.utils.helpers import get_logger, setup_logging
from config.settings import get_settings


def main() -> None:
    """Initialize configuration, logging, and verify application startup."""
    setup_logging()
    settings = get_settings()
    logger = get_logger("app.main")
    logger.info(
        f"AI Loan Underwriting Assistant initialized in '{settings.app_env}' mode."
    )
    print("AI Loan Underwriting Assistant initialized.")


if __name__ == "__main__":
    main()
