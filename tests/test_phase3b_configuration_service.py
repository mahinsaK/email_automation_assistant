"""Phase 3B tests for encrypted, user-scoped AI configuration."""

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.models.ai_configuration import AIProviderType
from app.repositories.ai_configuration import SQLiteAIConfigurationRepository
from app.services.ai.credential_validator import (
    CredentialValidationResult,
    CredentialValidationStatus,
)
from app.services.ai_configuration import (
    AIConfigurationUnavailableError,
    AIValidationUnavailableError,
    InvalidAICredentialError,
    UserAIConfigurationService,
)
from app.services.credential_cipher import FernetCredentialCipher
from app.services.user_email_generator import ConfiguredUserEmailGeneratorResolver


@dataclass
class FakeValidator:
    status: CredentialValidationStatus = CredentialValidationStatus.VALID
    calls: int = 0

    async def validate(self, api_key: str) -> CredentialValidationResult:
        self.calls += 1
        return CredentialValidationResult(self.status)


class FakeProvider:
    async def generate(self, **kwargs: object) -> str:
        return '{"subject":"Subject","body":"Body"}'


class RecordingProviderFactory:
    def __init__(self) -> None:
        self.credentials: list[tuple[AIProviderType, str]] = []

    def create(self, provider_type: AIProviderType, api_key: str) -> FakeProvider:
        self.credentials.append((provider_type, api_key))
        return FakeProvider()


def make_service(
    database_path: Path,
    *,
    validator: FakeValidator | None = None,
    cipher: FernetCredentialCipher | None = None,
) -> tuple[
    UserAIConfigurationService,
    SQLiteAIConfigurationRepository,
    FakeValidator,
    FernetCredentialCipher,
]:
    repository = SQLiteAIConfigurationRepository(database_path)
    asyncio.run(repository.initialize())
    selected_validator = validator or FakeValidator()
    selected_cipher = cipher or FernetCredentialCipher(
        Fernet.generate_key().decode("ascii")
    )
    service = UserAIConfigurationService(
        repository=repository,
        cipher=selected_cipher,
        validators={AIProviderType.OPENAI: selected_validator},
    )
    return service, repository, selected_validator, selected_cipher


def test_fernet_cipher_round_trip_does_not_expose_plaintext() -> None:
    cipher = FernetCredentialCipher(Fernet.generate_key().decode("ascii"))
    plaintext = "sk-test-secret"

    ciphertext = cipher.encrypt(plaintext)

    assert ciphertext != plaintext
    assert plaintext not in ciphertext
    assert cipher.decrypt(ciphertext) == plaintext


def test_valid_configuration_is_encrypted_and_enables_only_that_user(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "assistant.db"
    service, repository, validator, _ = make_service(database_path)
    plaintext = "sk-user-a-secret"

    result = asyncio.run(
        service.configure(
            telegram_user_id=101,
            provider=AIProviderType.OPENAI,
            api_key=plaintext,
        )
    )
    stored = asyncio.run(repository.get_for_user(101))

    assert result.replaced is False
    assert stored is not None
    assert stored.encrypted_api_key != plaintext
    assert plaintext not in stored.encrypted_api_key
    assert asyncio.run(service.is_configured(101)) is True
    assert asyncio.run(service.is_configured(202)) is False
    assert validator.calls == 1

    with sqlite3.connect(database_path) as connection:
        raw_value = connection.execute(
            "SELECT encrypted_api_key FROM user_ai_configurations "
            "WHERE telegram_user_id = ?",
            (101,),
        ).fetchone()[0]
    assert plaintext not in raw_value


def test_plaintext_credential_is_not_written_to_logs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, _, _, _ = make_service(tmp_path / "assistant.db")
    plaintext = "sk-never-log-this-value"

    with caplog.at_level(logging.INFO):
        asyncio.run(
            service.configure(
                telegram_user_id=101,
                provider=AIProviderType.OPENAI,
                api_key=plaintext,
            )
        )

    assert plaintext not in caplog.text


def test_invalid_replacement_preserves_existing_encrypted_configuration(
    tmp_path: Path,
) -> None:
    validator = FakeValidator()
    service, repository, _, _ = make_service(
        tmp_path / "assistant.db",
        validator=validator,
    )
    asyncio.run(
        service.configure(
            telegram_user_id=101,
            provider=AIProviderType.OPENAI,
            api_key="sk-original",
        )
    )
    original = asyncio.run(repository.get_for_user(101))
    validator.status = CredentialValidationStatus.INVALID

    with pytest.raises(InvalidAICredentialError):
        asyncio.run(
            service.configure(
                telegram_user_id=101,
                provider=AIProviderType.OPENAI,
                api_key="sk-invalid-replacement",
            )
        )

    assert asyncio.run(repository.get_for_user(101)) == original


def test_temporary_validation_failure_does_not_save_or_label_key_invalid(
    tmp_path: Path,
) -> None:
    validator = FakeValidator(CredentialValidationStatus.TEMPORARILY_UNAVAILABLE)
    service, repository, _, _ = make_service(
        tmp_path / "assistant.db",
        validator=validator,
    )

    with pytest.raises(AIValidationUnavailableError):
        asyncio.run(
            service.configure(
                telegram_user_id=101,
                provider=AIProviderType.OPENAI,
                api_key="sk-unverified",
            )
        )

    assert asyncio.run(repository.get_for_user(101)) is None


def test_missing_encryption_key_fails_safely_without_saving(tmp_path: Path) -> None:
    repository = SQLiteAIConfigurationRepository(tmp_path / "assistant.db")
    asyncio.run(repository.initialize())
    service = UserAIConfigurationService(
        repository=repository,
        cipher=None,
        validators={AIProviderType.OPENAI: FakeValidator()},
    )

    with pytest.raises(AIConfigurationUnavailableError):
        asyncio.run(
            service.configure(
                telegram_user_id=101,
                provider=AIProviderType.OPENAI,
                api_key="sk-not-stored",
            )
        )

    assert asyncio.run(service.is_configured(101)) is False
    assert asyncio.run(repository.get_for_user(101)) is None


def test_repository_and_removal_are_isolated_by_user(tmp_path: Path) -> None:
    service, _, _, _ = make_service(tmp_path / "assistant.db")
    for user_id, key in ((101, "sk-user-a"), (202, "sk-user-b")):
        asyncio.run(
            service.configure(
                telegram_user_id=user_id,
                provider=AIProviderType.OPENAI,
                api_key=key,
            )
        )

    assert asyncio.run(service.remove(101)) is True
    assert asyncio.run(service.resolve(101)) is None
    user_b = asyncio.run(service.resolve(202))
    assert user_b is not None
    assert user_b.api_key == "sk-user-b"


def test_encrypted_configuration_survives_repository_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "assistant.db"
    cipher = FernetCredentialCipher(Fernet.generate_key().decode("ascii"))
    service, _, _, _ = make_service(database_path, cipher=cipher)
    asyncio.run(
        service.configure(
            telegram_user_id=101,
            provider=AIProviderType.OPENAI,
            api_key="sk-persistent",
        )
    )

    restarted_repository = SQLiteAIConfigurationRepository(database_path)
    asyncio.run(restarted_repository.initialize())
    restarted_service = UserAIConfigurationService(
        repository=restarted_repository,
        cipher=cipher,
        validators={AIProviderType.OPENAI: FakeValidator()},
    )
    resolved = asyncio.run(restarted_service.resolve(101))

    assert resolved is not None
    assert resolved.api_key == "sk-persistent"


def test_valid_replacement_changes_only_requesting_users_credential(
    tmp_path: Path,
) -> None:
    service, _, _, _ = make_service(tmp_path / "assistant.db")
    asyncio.run(
        service.configure(
            telegram_user_id=101,
            provider=AIProviderType.OPENAI,
            api_key="sk-old-a",
        )
    )
    asyncio.run(
        service.configure(
            telegram_user_id=202,
            provider=AIProviderType.OPENAI,
            api_key="sk-user-b",
        )
    )

    replacement = asyncio.run(
        service.configure(
            telegram_user_id=101,
            provider=AIProviderType.OPENAI,
            api_key="sk-new-a",
        )
    )

    assert replacement.replaced is True
    assert asyncio.run(service.resolve(101)).api_key == "sk-new-a"  # type: ignore[union-attr]
    assert asyncio.run(service.resolve(202)).api_key == "sk-user-b"  # type: ignore[union-attr]


def test_generator_resolution_uses_only_the_requested_users_key(
    tmp_path: Path,
) -> None:
    service, _, _, _ = make_service(tmp_path / "assistant.db")
    asyncio.run(
        service.configure(
            telegram_user_id=101,
            provider=AIProviderType.OPENAI,
            api_key="sk-user-a",
        )
    )
    asyncio.run(
        service.configure(
            telegram_user_id=202,
            provider=AIProviderType.OPENAI,
            api_key="sk-user-b",
        )
    )
    factory = RecordingProviderFactory()
    resolver = ConfiguredUserEmailGeneratorResolver(
        configuration_service=service,
        provider_factory=factory,  # type: ignore[arg-type]
    )

    assert asyncio.run(resolver.resolve(101)) is not None
    assert asyncio.run(resolver.resolve(202)) is not None

    assert factory.credentials == [
        (AIProviderType.OPENAI, "sk-user-a"),
        (AIProviderType.OPENAI, "sk-user-b"),
    ]
