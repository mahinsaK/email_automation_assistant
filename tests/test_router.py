"""Smoke test for dependency composition and Telegram handler registration."""

from app.bot.router import build_application
from app.config import Settings


def test_application_composes_with_phase2_dependencies() -> None:
    application = build_application(Settings(telegram_bot_token="123456:TEST_TOKEN"))

    assert application.handlers
