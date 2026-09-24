"""Helper utilities and logging configuration."""

import logging
import sys
from typing import Optional

from config.settings import get_settings


def setup_logging(log_level: Optional[str] = None) -> None:
    """Configure standardized application logging.

    Args:
        log_level: Optional log level override. If omitted, uses Settings.log_level.
    """
    if log_level is None:
        settings = get_settings()
        log_level = settings.log_level

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Configure root handler cleanly
    logging.basicConfig(
        level=numeric_level,
        format=log_format,
        datefmt=date_format,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """Obtain a named logger instance for agents and modules.

    Args:
        name: Name of the logger, typically __name__.

    Returns:
        Configured logging.Logger instance.
    """
    return logging.getLogger(name)
