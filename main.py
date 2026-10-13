"""Application entry point."""

import asyncio

from telegram.ext import Application

from app.bot.router import build_application
from app.config import ConfigurationError, Settings
from app.logging_config import configure_logging


def run_application(application: Application) -> None:
    """Run polling with an explicit event loop, including on Python 3.14+."""

    # python-telegram-bot 21 expects a current loop. asyncio.Runner owns creation
    # and cleanup without relying on Python 3.14's removed implicit-loop behavior.
    with asyncio.Runner():
        application.run_polling(allowed_updates=None, close_loop=False)


def main() -> None:
    """Load configuration and run the Telegram polling adapter."""

    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        raise SystemExit(f"Configuration error: {error}") from error

    configure_logging(settings.log_level)
    application = build_application(settings)
    run_application(application)


if __name__ == "__main__":
    main()

