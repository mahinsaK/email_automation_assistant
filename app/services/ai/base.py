"""Vendor-neutral language-model provider boundary."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class AIProviderError(RuntimeError):
    """Expected failure while communicating with an external AI provider."""


class AIResponseValidationError(ValueError):
    """Raised when provider output cannot safely become a domain object."""


class LLMProvider(Protocol):
    """Port that adapts a vendor SDK to structured text generation."""

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> str:
        """Return JSON representing the requested response model."""
        ...
