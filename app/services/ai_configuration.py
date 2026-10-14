"""Application service for encrypted per-user AI configuration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from app.models.ai_configuration import (
    AIProviderType,
    ResolvedAIConfiguration,
    StoredAIConfiguration,
)
from app.repositories.ai_configuration import (
    AIConfigurationRepository,
    AIConfigurationRepositoryError,
)
from app.services.ai.credential_validator import (
    AIProviderCredentialValidator,
    CredentialValidationStatus,
)
from app.services.credential_cipher import CredentialCipher, CredentialCipherError


LOGGER = logging.getLogger(__name__)


class AIConfigurationError(RuntimeError):
    """Base safe error for per-user AI configuration operations."""


class AIConfigurationUnavailableError(AIConfigurationError):
    """Raised when encryption or persistence is unavailable."""


class InvalidAICredentialError(AIConfigurationError):
    """Raised when the provider explicitly rejects a credential."""


class AIValidationUnavailableError(AIConfigurationError):
    """Raised when credential validity cannot currently be determined."""


class UnsupportedAIProviderError(AIConfigurationError):
    """Raised when configuration is requested for an unsupported provider."""


@dataclass(frozen=True, slots=True)
class AIConfigurationResult:
    """Successful configuration result without credential material."""

    provider: AIProviderType
    replaced: bool


class UserAIConfigurationService:
    """Coordinate credential validation, encryption, persistence, and removal."""

    def __init__(
        self,
        *,
        repository: AIConfigurationRepository,
        cipher: CredentialCipher | None,
        validators: Mapping[AIProviderType, AIProviderCredentialValidator],
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._validators = dict(validators)

    @property
    def credential_storage_available(self) -> bool:
        """Whether new credentials can be encrypted in this process."""

        return self._cipher is not None

    async def configure(
        self,
        *,
        telegram_user_id: int,
        provider: AIProviderType,
        api_key: str,
    ) -> AIConfigurationResult:
        """Validate and atomically replace one user's encrypted credential."""

        if self._cipher is None:
            raise AIConfigurationUnavailableError(
                "Secure AI credential storage is not configured."
            )
        validator = self._validators.get(provider)
        if validator is None:
            raise UnsupportedAIProviderError("The selected AI provider is unsupported.")
        if not api_key.strip():
            raise InvalidAICredentialError("The AI credential is invalid.")

        validation = await validator.validate(api_key)
        if validation.status is CredentialValidationStatus.INVALID:
            LOGGER.warning("AI credential validation failed")
            raise InvalidAICredentialError("The AI credential is invalid.")
        if validation.status is CredentialValidationStatus.TEMPORARILY_UNAVAILABLE:
            LOGGER.warning("AI provider validation unavailable")
            raise AIValidationUnavailableError(
                "The AI provider could not be reached for validation."
            )

        try:
            existing = await self._repository.get_for_user(telegram_user_id)
            now = datetime.now(UTC)
            encrypted_api_key = self._cipher.encrypt(api_key)
            configuration = StoredAIConfiguration(
                telegram_user_id=telegram_user_id,
                provider=provider,
                encrypted_api_key=encrypted_api_key,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            await self._repository.save(configuration)
        except (AIConfigurationRepositoryError, CredentialCipherError) as error:
            LOGGER.error("AI configuration persistence failed")
            raise AIConfigurationUnavailableError(
                "AI configuration could not be saved."
            ) from error

        LOGGER.info(
            "AI configuration replaced" if existing else "AI configuration saved"
        )
        return AIConfigurationResult(provider=provider, replaced=existing is not None)

    async def get_status(
        self,
        telegram_user_id: int,
    ) -> StoredAIConfiguration | None:
        """Return encrypted metadata for one user without decrypting the key."""

        try:
            return await self._repository.get_for_user(telegram_user_id)
        except AIConfigurationRepositoryError as error:
            LOGGER.error("AI configuration persistence failed")
            raise AIConfigurationUnavailableError(
                "AI configuration status is unavailable."
            ) from error

    async def is_configured(self, telegram_user_id: int) -> bool:
        """Return whether this user has a resolvable personal configuration."""

        if self._cipher is None:
            return False
        return await self.resolve(telegram_user_id) is not None

    async def resolve(
        self,
        telegram_user_id: int,
    ) -> ResolvedAIConfiguration | None:
        """Decrypt one user's credential only for immediate provider creation."""

        stored = await self.get_status(telegram_user_id)
        if stored is None:
            return None
        if self._cipher is None:
            raise AIConfigurationUnavailableError(
                "Secure AI credential storage is unavailable."
            )
        try:
            api_key = self._cipher.decrypt(stored.encrypted_api_key)
        except CredentialCipherError as error:
            LOGGER.error("Stored AI credential decryption failed")
            raise AIConfigurationUnavailableError(
                "Stored AI configuration cannot be resolved."
            ) from error
        return ResolvedAIConfiguration(provider=stored.provider, api_key=api_key)

    async def remove(self, telegram_user_id: int) -> bool:
        """Delete only the requesting user's stored AI configuration."""

        try:
            removed = await self._repository.delete_for_user(telegram_user_id)
        except AIConfigurationRepositoryError as error:
            LOGGER.error("AI configuration persistence failed")
            raise AIConfigurationUnavailableError(
                "AI configuration could not be removed."
            ) from error
        if removed:
            LOGGER.info("AI configuration removed")
        return removed
