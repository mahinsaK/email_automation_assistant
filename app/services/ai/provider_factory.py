"""Factory for provider adapters selected by stored configuration."""

from __future__ import annotations

from app.models.ai_configuration import AIProviderType
from app.services.ai.base import LLMProvider
from app.services.ai.openai_provider import OpenAIProvider


class UnsupportedAIProviderError(ValueError):
    """Raised when no adapter exists for a configured provider type."""


class AIProviderFactory:
    """Construct isolated provider adapters from short-lived credentials."""

    def __init__(self, *, model: str, timeout_seconds: float) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds

    def create(
        self,
        provider_type: AIProviderType,
        api_key: str,
    ) -> LLMProvider:
        if provider_type is AIProviderType.OPENAI:
            return OpenAIProvider(
                api_key=api_key,
                model=self._model,
                timeout_seconds=self._timeout_seconds,
            )
        raise UnsupportedAIProviderError("The configured AI provider is unsupported.")
