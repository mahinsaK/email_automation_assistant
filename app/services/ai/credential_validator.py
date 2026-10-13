"""Provider-credential validation abstractions and OpenAI adapter."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from openai import AsyncOpenAI, AuthenticationError, OpenAIError


LOGGER = logging.getLogger(__name__)


class CredentialValidationStatus(StrEnum):
    """Safe outcomes from a provider credential check."""

    VALID = "valid"
    INVALID = "invalid"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"


@dataclass(frozen=True, slots=True)
class CredentialValidationResult:
    """Provider-neutral credential validation outcome."""

    status: CredentialValidationStatus


class AIProviderCredentialValidator(Protocol):
    """Validate one provider credential without generating an email."""

    async def validate(self, api_key: str) -> CredentialValidationResult:
        """Return a safe outcome without exposing provider exceptions."""
        ...


class OpenAICredentialValidator:
    """Validate OpenAI credentials with a minimal authenticated models request."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory or self._create_client

    async def validate(self, api_key: str) -> CredentialValidationResult:
        try:
            client = self._client_factory(api_key)
            await client.models.list()
        except AuthenticationError:
            LOGGER.warning("AI credential validation failed")
            return CredentialValidationResult(CredentialValidationStatus.INVALID)
        except (OpenAIError, asyncio.TimeoutError):
            LOGGER.warning("AI provider validation unavailable")
            return CredentialValidationResult(
                CredentialValidationStatus.TEMPORARILY_UNAVAILABLE
            )
        LOGGER.info("AI credential validated")
        return CredentialValidationResult(CredentialValidationStatus.VALID)

    def _create_client(self, api_key: str) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=api_key,
            timeout=self._timeout_seconds,
            max_retries=0,
        )
