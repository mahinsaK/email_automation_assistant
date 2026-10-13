"""Tests for optional AI generation wiring."""

from unittest.mock import patch

from pydantic import BaseModel

from app.bot.router import build_email_generator
from app.config import Settings
from app.services.ai_email_generator import AIEmailGenerator


class UnusedProvider:
    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> str:
        raise AssertionError("Configuration tests must not call a provider")


def test_no_api_key_reports_ai_as_unavailable() -> None:
    settings = Settings(telegram_bot_token="test", openai_api_key=None)

    generator = build_email_generator(settings)

    assert generator is None


def test_api_key_configured_selects_ai_generation_without_network() -> None:
    settings = Settings(
        telegram_bot_token="test",
        openai_api_key="fake-test-key",
        ai_model="test-model",
    )
    with patch(
        "app.bot.router.OpenAIProvider",
        return_value=UnusedProvider(),
    ) as provider_factory:
        generator = build_email_generator(settings)

    assert isinstance(generator, AIEmailGenerator)
    provider_factory.assert_called_once_with(
        api_key="fake-test-key",
        model="test-model",
        timeout_seconds=30.0,
    )


def test_deterministic_provider_setting_reports_ai_as_unavailable() -> None:
    settings = Settings(
        telegram_bot_token="test",
        ai_provider="deterministic",
        openai_api_key="fake-test-key",
    )

    generator = build_email_generator(settings)

    assert generator is None


def test_settings_ai_enabled_requires_supported_provider_and_key() -> None:
    assert Settings(telegram_bot_token="test").ai_enabled is False
    assert (
        Settings(
            telegram_bot_token="test",
            openai_api_key="fake-test-key",
        ).ai_enabled
        is True
    )
    assert (
        Settings(
            telegram_bot_token="test",
            ai_provider="deterministic",
            openai_api_key="fake-test-key",
        ).ai_enabled
        is False
    )
