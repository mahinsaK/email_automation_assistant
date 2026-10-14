"""Central logging setup."""

import logging


QUIET_TRANSPORT_LOGGERS = ("httpx", "httpcore")


def configure_logging(level: str = "INFO") -> None:
    """Configure application logging without exposing message contents or secrets."""

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=numeric_level,
    )
    # httpx logs complete Telegram request URLs at INFO level. Telegram embeds
    # the bot credential in that URL, so transport request logging must remain
    # disabled even when application INFO logs are enabled.
    for logger_name in QUIET_TRANSPORT_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

