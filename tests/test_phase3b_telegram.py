"""Telegram adapter and smoke tests for per-user AI configuration."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cryptography.fernet import Fernet
from telegram.ext import ConversationHandler

from app.bot.handlers.ai_configuration_handler import (
    build_ai_configuration_callbacks,
)
from app.bot.handlers.general_email_handler import build_general_email_callbacks
from app.bot.keyboards import (
    AI_CONFIG_OPENAI,
    AI_ENTER_MANUAL,
    AI_REMOVE_CONFIRM,
    AI_REMOVE_KEEP,
    CONFIRM,
    DRAFT_AI,
    TONE_CALLBACK_PREFIX,
)
from app.bot.states import GeneralEmailState, JobApplicationState
from app.models.ai_configuration import AIProviderType
from app.models.email import EmailDraft, SendResult
from app.repositories.ai_configuration import SQLiteAIConfigurationRepository
from app.services.ai.credential_validator import (
    CredentialValidationResult,
    CredentialValidationStatus,
)
from app.services.ai_configuration import UserAIConfigurationService
from app.services.credential_cipher import FernetCredentialCipher
from app.services.email_generator import DeterministicEmailGenerator
from app.services.user_email_generator import ConfiguredUserEmailGeneratorResolver
from app.workflows.general_email import GeneralEmailWorkflow


class FakeValidator:
    def __init__(
        self,
        status: CredentialValidationStatus = CredentialValidationStatus.VALID,
    ) -> None:
        self.status = status

    async def validate(self, api_key: str) -> CredentialValidationResult:
        return CredentialValidationResult(self.status)


class KeyAwareProvider:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.calls = 0

    async def generate(self, **kwargs: object) -> str:
        self.calls += 1
        return (
            '{"subject":"Draft for '
            + self.api_key[-1]
            + '","body":"User-specific AI body"}'
        )


class RecordingProviderFactory:
    def __init__(self) -> None:
        self.providers: list[KeyAwareProvider] = []

    def create(
        self,
        provider_type: AIProviderType,
        api_key: str,
    ) -> KeyAwareProvider:
        provider = KeyAwareProvider(api_key)
        self.providers.append(provider)
        return provider


class RecordingSender:
    def __init__(self) -> None:
        self.calls: list[EmailDraft] = []

    async def send(self, draft: EmailDraft) -> SendResult:
        self.calls.append(draft)
        return SendResult(success=True, message_id="phase3b-smoke")


def make_service(
    tmp_path: Path,
    validator: FakeValidator | None = None,
) -> tuple[UserAIConfigurationService, SQLiteAIConfigurationRepository]:
    repository = SQLiteAIConfigurationRepository(tmp_path / "assistant.db")
    asyncio.run(repository.initialize())
    service = UserAIConfigurationService(
        repository=repository,
        cipher=FernetCredentialCipher(Fernet.generate_key().decode("ascii")),
        validators={AIProviderType.OPENAI: validator or FakeValidator()},
    )
    return service, repository


def make_message(text: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        reply_text=AsyncMock(),
        delete=AsyncMock(),
    )


def make_text_update(text: str, user_id: int) -> SimpleNamespace:
    message = make_message(text)
    return SimpleNamespace(
        callback_query=None,
        effective_message=message,
        effective_user=SimpleNamespace(id=user_id),
    )


def make_callback_update(data: str, user_id: int) -> SimpleNamespace:
    message = make_message()
    query = SimpleNamespace(
        data=data,
        message=message,
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    return SimpleNamespace(
        callback_query=query,
        effective_message=message,
        effective_user=SimpleNamespace(id=user_id),
    )


def reply_texts(message: SimpleNamespace) -> list[str]:
    return [str(call.args[0]) for call in message.reply_text.await_args_list]


def configure_user(
    callbacks: object,
    context: SimpleNamespace,
    *,
    user_id: int,
    api_key: str,
) -> int:
    asyncio.run(callbacks.begin(make_text_update("/configure_ai", user_id), context))
    asyncio.run(
        callbacks.handle_provider(
            make_callback_update(AI_CONFIG_OPENAI, user_id),
            context,
        )
    )
    key_update = make_text_update(api_key, user_id)
    state = asyncio.run(callbacks.receive_api_key(key_update, context))
    key_update.effective_message.delete.assert_awaited_once()
    assert api_key not in " ".join(reply_texts(key_update.effective_message))
    return state


def test_configuration_success_deletes_message_and_status_never_exposes_key(
    tmp_path: Path,
) -> None:
    service, repository = make_service(tmp_path)
    callbacks = build_ai_configuration_callbacks(service)
    context = SimpleNamespace(user_data={})
    api_key = "sk-super-secret-value"

    state = configure_user(
        callbacks,
        context,
        user_id=101,
        api_key=api_key,
    )
    status_update = make_text_update("/ai_status", 101)
    asyncio.run(callbacks.status(status_update, context))
    stored = asyncio.run(repository.get_for_user(101))

    assert state == ConversationHandler.END
    assert "ai_configuration" not in context.user_data
    assert stored is not None
    assert api_key not in stored.encrypted_api_key
    status_text = " ".join(reply_texts(status_update.effective_message))
    assert "Provider: OpenAI" in status_text
    assert "Stored securely" in status_text
    assert api_key not in status_text


def test_unconfigured_status_does_not_require_or_expose_a_credential(
    tmp_path: Path,
) -> None:
    service, _ = make_service(tmp_path)
    callbacks = build_ai_configuration_callbacks(service)
    context = SimpleNamespace(user_data={})
    update = make_text_update("/ai_status", 404)

    asyncio.run(callbacks.status(update, context))

    status_text = " ".join(reply_texts(update.effective_message))
    assert "Not configured" in status_text
    assert "/configure_ai" in status_text


def test_missing_encryption_key_explains_unavailability_and_manual_mode(
    tmp_path: Path,
) -> None:
    repository = SQLiteAIConfigurationRepository(tmp_path / "assistant.db")
    asyncio.run(repository.initialize())
    service = UserAIConfigurationService(
        repository=repository,
        cipher=None,
        validators={AIProviderType.OPENAI: FakeValidator()},
    )
    callbacks = build_ai_configuration_callbacks(service)
    context = SimpleNamespace(user_data={})
    update = make_text_update("/configure_ai", 101)

    state = asyncio.run(callbacks.begin(update, context))

    text = " ".join(reply_texts(update.effective_message))
    assert state == ConversationHandler.END
    assert "CREDENTIAL_ENCRYPTION_KEY" in text
    assert "Manual email drafting" in text


def test_configuration_from_send_preserves_recipient_and_returns_to_method(
    tmp_path: Path,
) -> None:
    service, _ = make_service(tmp_path)
    callbacks = build_ai_configuration_callbacks(service)
    context = SimpleNamespace(
        user_data={"general_email": {"recipient": "person@example.com"}}
    )
    user_id = 101

    begin_state = asyncio.run(
        callbacks.begin_from_email(
            make_callback_update("email:ai:configure", user_id),
            context,
        )
    )
    asyncio.run(
        callbacks.handle_provider(
            make_callback_update(AI_CONFIG_OPENAI, user_id),
            context,
        )
    )
    success_update = make_text_update("sk-user-a", user_id)
    final_state = asyncio.run(callbacks.receive_api_key(success_update, context))

    assert begin_state is GeneralEmailState.AI_CONFIG_PROVIDER
    assert final_state is GeneralEmailState.WAITING_DRAFT_METHOD
    assert context.user_data["general_email"]["recipient"] == "person@example.com"


def test_configuration_from_apply_preserves_job_data_and_returns_to_method(
    tmp_path: Path,
) -> None:
    service, _ = make_service(tmp_path)
    callbacks = build_ai_configuration_callbacks(service)
    context = SimpleNamespace(
        user_data={
            "job_application": {
                "company_email": "jobs@example.com",
                "company_name": "Example Co",
                "role": "Engineer",
                "job_description": "Python required",
            }
        }
    )

    begin_state = asyncio.run(
        callbacks.begin_from_job(
            make_callback_update("job:ai:configure", 101),
            context,
        )
    )
    asyncio.run(
        callbacks.handle_provider(
            make_callback_update(AI_CONFIG_OPENAI, 101),
            context,
        )
    )
    final_state = asyncio.run(
        callbacks.receive_api_key(make_text_update("sk-job-user", 101), context)
    )

    assert begin_state is GeneralEmailState.AI_CONFIG_PROVIDER
    assert final_state is JobApplicationState.WAITING_DRAFT_METHOD
    assert context.user_data["job_application"]["role"] == "Engineer"


def test_invalid_and_temporary_validation_messages_are_distinct(tmp_path: Path) -> None:
    validator = FakeValidator(CredentialValidationStatus.INVALID)
    service, _ = make_service(tmp_path, validator)
    callbacks = build_ai_configuration_callbacks(service)

    invalid_context = SimpleNamespace(user_data={})
    asyncio.run(callbacks.begin(make_text_update("/configure_ai", 101), invalid_context))
    asyncio.run(
        callbacks.handle_provider(
            make_callback_update(AI_CONFIG_OPENAI, 101),
            invalid_context,
        )
    )
    invalid_update = make_text_update("sk-invalid", 101)
    invalid_state = asyncio.run(
        callbacks.receive_api_key(invalid_update, invalid_context)
    )

    validator.status = CredentialValidationStatus.TEMPORARILY_UNAVAILABLE
    temporary_context = SimpleNamespace(user_data={})
    asyncio.run(callbacks.begin(make_text_update("/configure_ai", 202), temporary_context))
    asyncio.run(
        callbacks.handle_provider(
            make_callback_update(AI_CONFIG_OPENAI, 202),
            temporary_context,
        )
    )
    temporary_update = make_text_update("sk-unverified", 202)
    temporary_state = asyncio.run(
        callbacks.receive_api_key(temporary_update, temporary_context)
    )

    assert invalid_state is GeneralEmailState.AI_CONFIG_RETRY
    assert "could not be validated" in " ".join(
        reply_texts(invalid_update.effective_message)
    )
    assert temporary_state is GeneralEmailState.AI_CONFIG_RETRY
    temporary_text = " ".join(reply_texts(temporary_update.effective_message))
    assert "could not be reached" in temporary_text
    assert "invalid" not in temporary_text.lower()


def test_remove_confirmation_and_cancel_are_user_scoped(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)
    callbacks = build_ai_configuration_callbacks(service)
    for user_id in (101, 202):
        configure_user(
            callbacks,
            SimpleNamespace(user_data={}),
            user_id=user_id,
            api_key=f"sk-user-{user_id}",
        )

    cancel_context = SimpleNamespace(user_data={})
    asyncio.run(callbacks.begin_remove(make_text_update("/remove_ai", 101), cancel_context))
    cancel_state = asyncio.run(
        callbacks.handle_remove(
            make_callback_update(AI_REMOVE_KEEP, 101),
            cancel_context,
        )
    )
    assert cancel_state == ConversationHandler.END
    assert asyncio.run(service.is_configured(101)) is True

    remove_context = SimpleNamespace(user_data={})
    asyncio.run(callbacks.begin_remove(make_text_update("/remove_ai", 101), remove_context))
    remove_state = asyncio.run(
        callbacks.handle_remove(
            make_callback_update(AI_REMOVE_CONFIRM, 101),
            remove_context,
        )
    )

    assert remove_state == ConversationHandler.END
    assert asyncio.run(service.is_configured(101)) is False
    assert asyncio.run(service.is_configured(202)) is True


def test_user_a_configured_ai_smoke_sends_exactly_once(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)
    asyncio.run(
        service.configure(
            telegram_user_id=101,
            provider=AIProviderType.OPENAI,
            api_key="sk-user-a",
        )
    )
    factory = RecordingProviderFactory()
    resolver = ConfiguredUserEmailGeneratorResolver(
        configuration_service=service,
        provider_factory=factory,  # type: ignore[arg-type]
        fallback=DeterministicEmailGenerator(),
    )
    sender = RecordingSender()
    callbacks = build_general_email_callbacks(
        GeneralEmailWorkflow(None, sender),
        generator_resolver=resolver,
    )
    context = SimpleNamespace(user_data={})
    user_id = 101

    assert asyncio.run(resolver.is_available(101)) is True
    assert asyncio.run(resolver.is_available(202)) is False

    asyncio.run(
        callbacks.receive_recipient(
            make_text_update("recipient@example.com", user_id),
            context,
        )
    )
    method_state = asyncio.run(
        callbacks.handle_draft_method(make_callback_update(DRAFT_AI, user_id), context)
    )
    asyncio.run(
        callbacks.receive_purpose(make_text_update("Purpose", user_id), context)
    )
    asyncio.run(
        callbacks.receive_context(make_text_update("Context", user_id), context)
    )
    preview_state = asyncio.run(
        callbacks.handle_tone(
            make_callback_update(f"{TONE_CALLBACK_PREFIX}professional", user_id),
            context,
        )
    )
    confirm_state = asyncio.run(
        callbacks.handle_action(make_callback_update(CONFIRM, user_id), context)
    )

    assert method_state is GeneralEmailState.WAITING_PURPOSE
    assert preview_state is GeneralEmailState.WAITING_FOR_ACTION
    assert confirm_state == ConversationHandler.END
    assert [provider.api_key for provider in factory.providers] == ["sk-user-a"]
    assert len(sender.calls) == 1


def test_user_b_unconfigured_manual_fallback_smoke_sends_once(
    tmp_path: Path,
) -> None:
    service, _ = make_service(tmp_path)
    factory = RecordingProviderFactory()
    resolver = ConfiguredUserEmailGeneratorResolver(
        configuration_service=service,
        provider_factory=factory,  # type: ignore[arg-type]
    )
    sender = RecordingSender()
    callbacks = build_general_email_callbacks(
        GeneralEmailWorkflow(None, sender),
        generator_resolver=resolver,
    )
    context = SimpleNamespace(user_data={})
    user_id = 202

    asyncio.run(
        callbacks.receive_recipient(
            make_text_update("recipient@example.com", user_id),
            context,
        )
    )
    unavailable_state = asyncio.run(
        callbacks.handle_draft_method(make_callback_update(DRAFT_AI, user_id), context)
    )
    manual_state = asyncio.run(
        callbacks.handle_ai_unavailable(
            make_callback_update(AI_ENTER_MANUAL, user_id),
            context,
        )
    )
    asyncio.run(
        callbacks.receive_manual_subject(
            make_text_update("Manual subject", user_id),
            context,
        )
    )
    preview_state = asyncio.run(
        callbacks.receive_manual_body(
            make_text_update("Manual body", user_id),
            context,
        )
    )
    confirm_state = asyncio.run(
        callbacks.handle_action(make_callback_update(CONFIRM, user_id), context)
    )

    assert unavailable_state is GeneralEmailState.WAITING_AI_UNAVAILABLE_ACTION
    assert manual_state is GeneralEmailState.MANUAL_WAITING_SUBJECT
    assert preview_state is GeneralEmailState.WAITING_FOR_ACTION
    assert confirm_state == ConversationHandler.END
    assert factory.providers == []
    assert len(sender.calls) == 1
