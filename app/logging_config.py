"""Central logging setup."""

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure application logging without exposing message contents or secrets."""

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=numeric_level,
    )

