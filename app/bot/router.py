"""Telegram handler composition root."""

from __future__ import annotations

import logging
import warnings

from telegram import Update
from telegram.warnings import PTBUserWarning
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.bot.access import owner_only
from app.bot.handlers.ai_configuration_handler import (
    build_ai_configuration_callbacks,
)
from app.bot.handlers.common_handler import cancel, help_command, start, unknown_command
from app.bot.handlers.general_email_handler import build_general_email_callbacks
from app.bot.handlers.job_application_handler import (
    build_job_application_callbacks,
)
from app.bot.keyboards import (
    ACTION_PATTERN,
    AI_CONFIG_CALLBACK_PATTERN,
    AI_CONFIG_PROVIDER_PATTERN,
    AI_CONFIG_REPLACE_PATTERN,
    AI_CONFIG_RETRY_PATTERN,
    AI_REMOVE_PATTERN,
    AI_REMOVE_CALLBACK_PATTERN,
    AI_UNAVAILABLE_PATTERN,
    DRAFT_METHOD_PATTERN,
    EDIT_PATTERN,
    EMAIL_CALLBACK_PATTERN,
    JOB_ACTION_PATTERN,
    JOB_AI_UNAVAILABLE_PATTERN,
    JOB_CALLBACK_PATTERN,
    JOB_DRAFT_METHOD_PATTERN,
    JOB_EDIT_PATTERN,
    JOB_TONE_PATTERN,
    TONE_PATTERN,
)
from app.bot.states import GeneralEmailState, JobApplicationState
from app.config import Settings
from app.models.ai_configuration import AIProviderType, ResolvedAIConfiguration
from app.repositories.ai_configuration import (
    AIConfigurationRepositoryError,
    SQLiteAIConfigurationRepository,
)
from app.services.ai.credential_validator import OpenAICredentialValidator
from app.services.ai.openai_provider import OpenAIProvider
from app.services.ai.provider_factory import AIProviderFactory
from app.services.ai_configuration import UserAIConfigurationService
from app.services.ai_email_generator import AIEmailGenerator
from app.services.attachment import CVAttachmentService
from app.services.candidate_profile import CandidateProfileService
from app.services.credential_cipher import CredentialCipherError, FernetCredentialCipher
from app.services.email_generator import DeterministicEmailGenerator, EmailGenerator
from app.services.email_sender import MockEmailSender
from app.services.job_application_generator import (
    ConfiguredUserJobApplicationGeneratorResolver,
)
from app.services.job_requirements import (
    CandidateRequirementMatcher,
    DeterministicJobRequirementExtractor,
)
from app.services.user_email_generator import (
    ConfiguredUserAIProviderResolver,
    ConfiguredUserEmailGeneratorResolver,
)
from app.workflows.general_email import GeneralEmailWorkflow
from app.workflows.job_application import JobApplicationWorkflow


LOGGER = logging.getLogger(__name__)


def build_email_generator(settings: Settings) -> EmailGenerator | None:
    """Build the optional real-AI strategy; never label offline fallback as AI."""

    deterministic = DeterministicEmailGenerator()
    if settings.ai_enabled:
        provider = OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.ai_model,
            timeout_seconds=settings.ai_timeout_seconds,
        )
        LOGGER.info("AI email generation enabled with OpenAI")
        return AIEmailGenerator(provider=provider, fallback=deterministic)

    LOGGER.info("AI generation unavailable; manual draft mode remains enabled")
    return None


async def handle_error(update: object, context: object) -> None:
    """Log unexpected Telegram errors without leaking user input or secrets."""

    error = getattr(context, "error", None)
    LOGGER.error(
        "Unhandled Telegram update error",
        exc_info=(type(error), error, error.__traceback__) if error else None,
    )


def build_application(settings: Settings) -> Application:
    """Wire concrete dependencies and return the configured Telegram app."""

    repository = SQLiteAIConfigurationRepository(settings.database_path)
    cipher = None
    if settings.credential_encryption_key:
        try:
            cipher = FernetCredentialCipher(settings.credential_encryption_key)
        except CredentialCipherError:
            LOGGER.error(
                "Credential encryption is unavailable because its key is invalid"
            )
    else:
        LOGGER.warning(
            "Credential encryption key missing; per-user AI configuration disabled"
        )

    configuration_service = UserAIConfigurationService(
        repository=repository,
        cipher=cipher,
        validators={
            AIProviderType.OPENAI: OpenAICredentialValidator(
                timeout_seconds=settings.ai_timeout_seconds,
            )
        },
    )
    provider_factory = AIProviderFactory(
        model=settings.ai_model,
        timeout_seconds=settings.ai_timeout_seconds,
    )
    application_configuration = (
        ResolvedAIConfiguration(
            provider=AIProviderType.OPENAI,
            api_key=settings.openai_api_key,
        )
        if settings.ai_enabled and settings.openai_api_key
        else None
    )
    provider_resolver = ConfiguredUserAIProviderResolver(
        configuration_service=configuration_service,
        provider_factory=provider_factory,
        application_configuration=application_configuration,
    )
    generator_resolver = ConfiguredUserEmailGeneratorResolver(
        provider_resolver=provider_resolver,
    )
    job_generator_resolver = ConfiguredUserJobApplicationGeneratorResolver(
        provider_resolver=provider_resolver,
    )
    workflow = GeneralEmailWorkflow(
        generator=None,
        sender=MockEmailSender(),
    )
    job_workflow = JobApplicationWorkflow(
        profile_service=CandidateProfileService(settings.candidate_profile_path),
        attachment_service=CVAttachmentService(settings.cv_file_path),
        requirement_extractor=DeterministicJobRequirementExtractor(),
        matcher=CandidateRequirementMatcher(),
        approval_workflow=workflow,
    )
    ai_callbacks = build_ai_configuration_callbacks(
        configuration_service,
        application_ai_available=application_configuration is not None,
    )
    callbacks = build_general_email_callbacks(
        workflow,
        generator_resolver=generator_resolver,
        start_ai_configuration=ai_callbacks.begin_from_email,
    )
    job_callbacks = build_job_application_callbacks(
        job_workflow,
        generator_resolver=job_generator_resolver,
        start_ai_configuration=ai_callbacks.begin_from_job,
    )
    protect = owner_only(settings.allowed_telegram_user_id)

    async def initialize_services(application: Application) -> None:
        try:
            await repository.initialize()
        except AIConfigurationRepositoryError:
            LOGGER.error("AI configuration database initialization failed")

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(initialize_services)
        .build()
    )
    application.add_handler(CommandHandler("start", protect(start)))
    application.add_handler(CommandHandler("help", protect(help_command)))
    application.add_handler(CommandHandler("ai_status", protect(ai_callbacks.status)))
    # This conversation intentionally spans multiple text and callback messages,
    # so it must be keyed per user/chat rather than per Telegram message. PTB emits
    # a generic warning for that valid mixed-handler design; suppress only that
    # exact warning while constructing this handler.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="If 'per_message=False'.*",
            category=PTBUserWarning,
        )
        conversation_handler = ConversationHandler(
            entry_points=[
                CommandHandler("send", protect(callbacks.begin)),
                CommandHandler("apply", protect(job_callbacks.begin)),
                CommandHandler("configure_ai", protect(ai_callbacks.begin)),
                CommandHandler("remove_ai", protect(ai_callbacks.begin_remove)),
            ],
            states={
                GeneralEmailState.WAITING_RECIPIENT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(callbacks.receive_recipient),
                    )
                ],
                GeneralEmailState.WAITING_DRAFT_METHOD: [
                    CallbackQueryHandler(
                        protect(callbacks.handle_draft_method),
                        pattern=DRAFT_METHOD_PATTERN,
                    )
                ],
                GeneralEmailState.MANUAL_WAITING_SUBJECT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(callbacks.receive_manual_subject),
                    )
                ],
                GeneralEmailState.MANUAL_WAITING_BODY: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(callbacks.receive_manual_body),
                    )
                ],
                GeneralEmailState.WAITING_AI_UNAVAILABLE_ACTION: [
                    CallbackQueryHandler(
                        protect(callbacks.handle_ai_unavailable),
                        pattern=AI_UNAVAILABLE_PATTERN,
                    )
                ],
                GeneralEmailState.WAITING_PURPOSE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(callbacks.receive_purpose),
                    )
                ],
                GeneralEmailState.WAITING_CONTEXT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(callbacks.receive_context),
                    )
                ],
                GeneralEmailState.WAITING_TONE: [
                    CallbackQueryHandler(
                        protect(callbacks.handle_tone),
                        pattern=TONE_PATTERN,
                    )
                ],
                GeneralEmailState.WAITING_FOR_ACTION: [
                    CallbackQueryHandler(
                        protect(callbacks.handle_action),
                        pattern=ACTION_PATTERN,
                    )
                ],
                GeneralEmailState.EDIT_MENU: [
                    CallbackQueryHandler(
                        protect(callbacks.handle_edit_choice),
                        pattern=EDIT_PATTERN,
                    )
                ],
                GeneralEmailState.EDIT_RECIPIENT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(callbacks.receive_edited_recipient),
                    )
                ],
                GeneralEmailState.EDIT_SUBJECT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(callbacks.receive_edited_subject),
                    )
                ],
                GeneralEmailState.EDIT_BODY: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(callbacks.receive_edited_body),
                    )
                ],
                GeneralEmailState.EDIT_CONTEXT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(callbacks.receive_edited_context),
                    )
                ],
                GeneralEmailState.AI_CONFIG_REPLACE_CONFIRM: [
                    CallbackQueryHandler(
                        protect(ai_callbacks.handle_replace),
                        pattern=AI_CONFIG_REPLACE_PATTERN,
                    )
                ],
                GeneralEmailState.AI_CONFIG_PROVIDER: [
                    CallbackQueryHandler(
                        protect(ai_callbacks.handle_provider),
                        pattern=AI_CONFIG_PROVIDER_PATTERN,
                    )
                ],
                GeneralEmailState.AI_CONFIG_API_KEY: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(ai_callbacks.receive_api_key),
                    )
                ],
                GeneralEmailState.AI_CONFIG_RETRY: [
                    CallbackQueryHandler(
                        protect(ai_callbacks.handle_retry),
                        pattern=AI_CONFIG_RETRY_PATTERN,
                    )
                ],
                GeneralEmailState.AI_REMOVE_CONFIRM: [
                    CallbackQueryHandler(
                        protect(ai_callbacks.handle_remove),
                        pattern=AI_REMOVE_PATTERN,
                    )
                ],
                JobApplicationState.WAITING_COMPANY_EMAIL: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(job_callbacks.receive_company_email),
                    )
                ],
                JobApplicationState.WAITING_COMPANY_NAME: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(job_callbacks.receive_company_name),
                    )
                ],
                JobApplicationState.WAITING_ROLE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(job_callbacks.receive_role),
                    )
                ],
                JobApplicationState.WAITING_JOB_DESCRIPTION: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(job_callbacks.receive_job_description),
                    )
                ],
                JobApplicationState.WAITING_DRAFT_METHOD: [
                    CallbackQueryHandler(
                        protect(job_callbacks.handle_draft_method),
                        pattern=JOB_DRAFT_METHOD_PATTERN,
                    )
                ],
                JobApplicationState.MANUAL_WAITING_SUBJECT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(job_callbacks.receive_manual_subject),
                    )
                ],
                JobApplicationState.MANUAL_WAITING_BODY: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(job_callbacks.receive_manual_body),
                    )
                ],
                JobApplicationState.WAITING_AI_UNAVAILABLE_ACTION: [
                    CallbackQueryHandler(
                        protect(job_callbacks.handle_ai_unavailable),
                        pattern=JOB_AI_UNAVAILABLE_PATTERN,
                    )
                ],
                JobApplicationState.WAITING_TONE: [
                    CallbackQueryHandler(
                        protect(job_callbacks.handle_tone),
                        pattern=JOB_TONE_PATTERN,
                    )
                ],
                JobApplicationState.WAITING_FOR_ACTION: [
                    CallbackQueryHandler(
                        protect(job_callbacks.handle_action),
                        pattern=JOB_ACTION_PATTERN,
                    )
                ],
                JobApplicationState.EDIT_MENU: [
                    CallbackQueryHandler(
                        protect(job_callbacks.handle_edit_choice),
                        pattern=JOB_EDIT_PATTERN,
                    )
                ],
                JobApplicationState.EDIT_RECIPIENT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(job_callbacks.receive_edited_recipient),
                    )
                ],
                JobApplicationState.EDIT_COMPANY: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(job_callbacks.receive_edited_company),
                    )
                ],
                JobApplicationState.EDIT_ROLE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(job_callbacks.receive_edited_role),
                    )
                ],
                JobApplicationState.EDIT_JOB_DESCRIPTION: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(job_callbacks.receive_edited_job_description),
                    )
                ],
                JobApplicationState.EDIT_SUBJECT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(job_callbacks.receive_edited_subject),
                    )
                ],
                JobApplicationState.EDIT_BODY: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(job_callbacks.receive_edited_body),
                    )
                ],
            },
            fallbacks=[
                CommandHandler("cancel", protect(cancel)),
                CallbackQueryHandler(
                    protect(ai_callbacks.handle_invalid_callback),
                    pattern=AI_CONFIG_CALLBACK_PATTERN,
                ),
                CallbackQueryHandler(
                    protect(ai_callbacks.handle_invalid_callback),
                    pattern=AI_REMOVE_CALLBACK_PATTERN,
                ),
                CallbackQueryHandler(
                    protect(callbacks.handle_invalid_callback),
                    pattern=EMAIL_CALLBACK_PATTERN,
                ),
                CallbackQueryHandler(
                    protect(job_callbacks.handle_invalid_callback),
                    pattern=JOB_CALLBACK_PATTERN,
                ),
            ],
            allow_reentry=True,
        )
    application.add_handler(conversation_handler)
    application.add_handler(CommandHandler("cancel", protect(cancel)))
    application.add_handler(
        CallbackQueryHandler(
            protect(ai_callbacks.handle_invalid_callback),
            pattern=AI_CONFIG_CALLBACK_PATTERN,
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            protect(ai_callbacks.handle_invalid_callback),
            pattern=AI_REMOVE_CALLBACK_PATTERN,
        )
    )
    application.add_handler(MessageHandler(filters.COMMAND, protect(unknown_command)))
    application.add_handler(
        CallbackQueryHandler(
            protect(callbacks.handle_invalid_callback),
            pattern=EMAIL_CALLBACK_PATTERN,
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            protect(job_callbacks.handle_invalid_callback),
            pattern=JOB_CALLBACK_PATTERN,
        )
    )
    application.add_error_handler(handle_error)
    return application

