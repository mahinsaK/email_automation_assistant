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
from app.bot.handlers.common_handler import cancel, help_command, start, unknown_command
from app.bot.handlers.general_email_handler import build_general_email_callbacks
from app.bot.keyboards import (
    ACTION_PATTERN,
    EDIT_PATTERN,
    EMAIL_CALLBACK_PATTERN,
    TONE_PATTERN,
)
from app.bot.states import GeneralEmailState
from app.config import Settings
from app.services.ai.openai_provider import OpenAIProvider
from app.services.ai_email_generator import AIEmailGenerator
from app.services.email_generator import DeterministicEmailGenerator, EmailGenerator
from app.services.email_sender import MockEmailSender
from app.workflows.general_email import GeneralEmailWorkflow


LOGGER = logging.getLogger(__name__)


def build_email_generator(settings: Settings) -> EmailGenerator:
    """Select and construct the configured generation strategy."""

    deterministic = DeterministicEmailGenerator()
    if settings.ai_provider == "openai" and settings.openai_api_key:
        provider = OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.ai_model,
            timeout_seconds=settings.ai_timeout_seconds,
        )
        LOGGER.info("AI email generation enabled with OpenAI")
        return AIEmailGenerator(provider=provider, fallback=deterministic)

    LOGGER.info("AI provider unavailable; deterministic generator enabled")
    return deterministic


async def handle_error(update: object, context: object) -> None:
    """Log unexpected Telegram errors without leaking user input or secrets."""

    error = getattr(context, "error", None)
    LOGGER.error(
        "Unhandled Telegram update error",
        exc_info=(type(error), error, error.__traceback__) if error else None,
    )


def build_application(settings: Settings) -> Application:
    """Wire concrete dependencies and return the configured Telegram app."""

    workflow = GeneralEmailWorkflow(
        generator=build_email_generator(settings),
        sender=MockEmailSender(),
    )
    callbacks = build_general_email_callbacks(workflow)
    protect = owner_only(settings.allowed_telegram_user_id)

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", protect(start)))
    application.add_handler(CommandHandler("help", protect(help_command)))
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
            entry_points=[CommandHandler("send", protect(callbacks.begin))],
            states={
                GeneralEmailState.WAITING_RECIPIENT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(callbacks.receive_recipient),
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
            },
            fallbacks=[
                CommandHandler("cancel", protect(cancel)),
                CallbackQueryHandler(
                    protect(callbacks.handle_invalid_callback),
                    pattern=EMAIL_CALLBACK_PATTERN,
                ),
            ],
            allow_reentry=True,
        )
    application.add_handler(conversation_handler)
    application.add_handler(CommandHandler("cancel", protect(cancel)))
    application.add_handler(MessageHandler(filters.COMMAND, protect(unknown_command)))
    application.add_handler(
        CallbackQueryHandler(
            protect(callbacks.handle_invalid_callback),
            pattern=EMAIL_CALLBACK_PATTERN,
        )
    )
    application.add_error_handler(handle_error)
    return application

