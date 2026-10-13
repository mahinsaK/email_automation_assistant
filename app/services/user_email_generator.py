"""Resolve isolated email generators from per-user AI configuration."""

from __future__ import annotations

from typing import Protocol

from app.services.ai.provider_factory import AIProviderFactory
from app.services.ai_configuration import UserAIConfigurationService
from app.services.ai_email_generator import AIEmailGenerator
from app.services.email_generator import DeterministicEmailGenerator, EmailGenerator


class UserEmailGeneratorResolver(Protocol):
    """Application boundary for user-scoped AI generation capability."""

    async def is_available(self, telegram_user_id: int) -> bool:
        """Return whether AI generation is available to this user."""
        ...

    async def resolve(self, telegram_user_id: int) -> EmailGenerator | None:
        """Build an isolated generator for this user when available."""
        ...


class ConfiguredUserEmailGeneratorResolver:
    """Build AI generators from encrypted user configuration on demand."""

    def __init__(
        self,
        *,
        configuration_service: UserAIConfigurationService,
        provider_factory: AIProviderFactory,
        fallback: EmailGenerator | None = None,
        application_generator: EmailGenerator | None = None,
    ) -> None:
        self._configuration_service = configuration_service
        self._provider_factory = provider_factory
        self._fallback = fallback or DeterministicEmailGenerator()
        self._application_generator = application_generator

    async def is_available(self, telegram_user_id: int) -> bool:
        if await self._configuration_service.is_configured(telegram_user_id):
            return True
        return self._application_generator is not None

    async def resolve(self, telegram_user_id: int) -> EmailGenerator | None:
        configuration = await self._configuration_service.resolve(telegram_user_id)
        if configuration is None:
            return self._application_generator
        provider = self._provider_factory.create(
            configuration.provider,
            configuration.api_key,
        )
        return AIEmailGenerator(provider=provider, fallback=self._fallback)
