"""Resolve isolated AI providers and email generators per user."""

from __future__ import annotations

from typing import Protocol

from app.models.ai_configuration import ResolvedAIConfiguration
from app.services.ai.base import LLMProvider
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


class UserAIProviderResolver(Protocol):
    """Resolve an isolated LLM adapter for the current application user."""

    async def is_available(self, user_id: int) -> bool:
        """Return whether a real AI provider is available to this user."""
        ...

    async def resolve(self, user_id: int) -> LLMProvider | None:
        """Build the user's provider without exposing credential material."""
        ...


class ConfiguredUserAIProviderResolver:
    """Build provider adapters from encrypted per-user or development settings."""

    def __init__(
        self,
        *,
        configuration_service: UserAIConfigurationService,
        provider_factory: AIProviderFactory,
        application_configuration: ResolvedAIConfiguration | None = None,
    ) -> None:
        self._configuration_service = configuration_service
        self._provider_factory = provider_factory
        self._application_configuration = application_configuration

    async def is_available(self, telegram_user_id: int) -> bool:
        if await self._configuration_service.is_configured(telegram_user_id):
            return True
        return self._application_configuration is not None

    async def resolve(self, telegram_user_id: int) -> LLMProvider | None:
        configuration = await self._configuration_service.resolve(telegram_user_id)
        if configuration is None:
            configuration = self._application_configuration
        if configuration is None:
            return None
        return self._provider_factory.create(
            configuration.provider,
            configuration.api_key,
        )


class ConfiguredUserEmailGeneratorResolver:
    """Adapt user-specific LLM providers to the general email strategy."""

    def __init__(
        self,
        *,
        provider_resolver: UserAIProviderResolver | None = None,
        configuration_service: UserAIConfigurationService | None = None,
        provider_factory: AIProviderFactory | None = None,
        application_configuration: ResolvedAIConfiguration | None = None,
        application_generator: EmailGenerator | None = None,
        fallback: EmailGenerator | None = None,
    ) -> None:
        if provider_resolver is None:
            if configuration_service is None or provider_factory is None:
                raise TypeError(
                    "Provide provider_resolver or both configuration_service "
                    "and provider_factory."
                )
            provider_resolver = ConfiguredUserAIProviderResolver(
                configuration_service=configuration_service,
                provider_factory=provider_factory,
                application_configuration=application_configuration,
            )
        self._provider_resolver = provider_resolver
        self._application_generator = application_generator
        self._fallback = fallback or DeterministicEmailGenerator()

    async def is_available(self, telegram_user_id: int) -> bool:
        return (
            await self._provider_resolver.is_available(telegram_user_id)
            or self._application_generator is not None
        )

    async def resolve(self, telegram_user_id: int) -> EmailGenerator | None:
        provider = await self._provider_resolver.resolve(telegram_user_id)
        if provider is None:
            return self._application_generator
        return AIEmailGenerator(provider=provider, fallback=self._fallback)
