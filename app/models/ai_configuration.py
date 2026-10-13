"""Domain values for per-user AI credential configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AIProviderType(StrEnum):
    """AI providers supported by the configuration workflow."""

    OPENAI = "openai"

    @property
    def display_name(self) -> str:
        """Return a safe user-facing provider label."""

        return "OpenAI"


@dataclass(frozen=True, slots=True)
class StoredAIConfiguration:
    """Encrypted provider configuration persisted for one Telegram user."""

    telegram_user_id: int
    provider: AIProviderType
    encrypted_api_key: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ResolvedAIConfiguration:
    """Short-lived decrypted configuration used only to construct a provider."""

    provider: AIProviderType
    api_key: str
