"""Telegram handler composition root."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.bot.access import owner_only
from app.bot.handlers.common_handler import cancel, help_command, start, unknown_command
from app.bot.handlers.general_email_handler import build_general_email_callbacks
from app.bot.states import GeneralEmailState
from app.config import Settings
from app.services.email_generator import DeterministicEmailGenerator
from app.workflows.general_email import GeneralEmailWorkflow


LOGGER = logging.getLogger(__name__)


async def handle_error(update: object, context: object) -> None:
    """Log unexpected Telegram errors without leaking user input or secrets."""

    error = getattr(context, "error", None)
    LOGGER.error(
        "Unhandled Telegram update error",
        exc_info=(type(error), error, error.__traceback__) if error else None,
    )


def build_application(settings: Settings) -> Application:
    """Wire concrete dependencies and return the configured Telegram app."""

    workflow = GeneralEmailWorkflow(DeterministicEmailGenerator())
    begin, recipient, purpose, additional_context = build_general_email_callbacks(
        workflow
    )
    protect = owner_only(settings.allowed_telegram_user_id)

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", protect(start)))
    application.add_handler(CommandHandler("help", protect(help_command)))
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("send", protect(begin))],
            states={
                GeneralEmailState.WAITING_RECIPIENT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, protect(recipient))
                ],
                GeneralEmailState.WAITING_PURPOSE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, protect(purpose))
                ],
                GeneralEmailState.WAITING_CONTEXT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        protect(additional_context),
                    )
                ],
            },
            fallbacks=[CommandHandler("cancel", protect(cancel))],
            allow_reentry=True,
        )
    )
    application.add_handler(CommandHandler("cancel", protect(cancel)))
    application.add_handler(MessageHandler(filters.COMMAND, protect(unknown_command)))
    application.add_error_handler(handle_error)
    return application

