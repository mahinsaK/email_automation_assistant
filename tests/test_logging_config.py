"""Security tests for central logging configuration."""

import logging

from app.logging_config import QUIET_TRANSPORT_LOGGERS, configure_logging


def test_transport_request_logs_are_suppressed() -> None:
    original_levels = {
        name: logging.getLogger(name).level for name in QUIET_TRANSPORT_LOGGERS
    }
    try:
        configure_logging("INFO")

        assert all(
            logging.getLogger(name).level == logging.WARNING
            for name in QUIET_TRANSPORT_LOGGERS
        )
    finally:
        for name, level in original_levels.items():
            logging.getLogger(name).setLevel(level)
