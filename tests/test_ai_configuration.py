"""Tests for optional AI generation wiring."""

from unittest.mock import patch

from pydantic import BaseModel

from app.bot.router import build_email_generator
from app.config import Settings
from app.services.ai_email_generator import AIEmailGenerator
from app.services.email_generator import DeterministicEmailGenerator


class UnusedProvider:
    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> str:
        raise AssertionError("Configuration tests must not call a provider")


def test_no_api_key_selects_deterministic_generation() -> None:
    settings = Settings(telegram_bot_token="test", openai_api_key=None)

    generator = build_email_generator(settings)

    assert isinstance(generator, DeterministicEmailGenerator)


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


def test_deterministic_provider_setting_disables_ai_even_with_key() -> None:
    settings = Settings(
        telegram_bot_token="test",
        ai_provider="deterministic",
        openai_api_key="fake-test-key",
    )

    generator = build_email_generator(settings)

    assert isinstance(generator, DeterministicEmailGenerator)
