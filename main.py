"""Application entry point."""

from app.bot.router import build_application
from app.config import ConfigurationError, Settings
from app.logging_config import configure_logging


def main() -> None:
    """Load configuration and run the Telegram polling adapter."""

    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        raise SystemExit(f"Configuration error: {error}") from error

    configure_logging(settings.log_level)
    application = build_application(settings)
    application.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()

