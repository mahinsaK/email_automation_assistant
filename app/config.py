"""Environment-based application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings needed to start the Telegram adapter."""

    telegram_bot_token: str
    allowed_telegram_user_id: int | None = None
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables and an optional local .env file."""

        load_dotenv()
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise ConfigurationError(
                "TELEGRAM_BOT_TOKEN is missing. Copy .env.example to .env and add it."
            )

        allowed_id_value = os.getenv("ALLOWED_TELEGRAM_USER_ID", "").strip()
        allowed_id: int | None = None
        if allowed_id_value:
            try:
                allowed_id = int(allowed_id_value)
            except ValueError as error:
                raise ConfigurationError(
                    "ALLOWED_TELEGRAM_USER_ID must be an integer."
                ) from error

        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
        return cls(
            telegram_bot_token=token,
            allowed_telegram_user_id=allowed_id,
            log_level=log_level,
        )

