"""Handlers shared across Telegram workflows."""

import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler


LOGGER = logging.getLogger(__name__)


WELCOME_TEXT = (
    "Welcome to AI Email Automation Assistant.\n\n"
    "I can help you enter a draft manually or create one with configured AI, "
    "then edit and approve it. "
    "Email delivery is still simulated; no real email is sent.\n\n"
    "Use /send to create a draft or /help to see available commands."
)

HELP_TEXT = (
    "Available commands:\n"
    "/start - Show the welcome message\n"
    "/help - Show this help\n"
    "/send - Create a general email draft\n"
    "/configure_ai - Configure or replace your AI provider credential\n"
    "/ai_status - Show your AI configuration status\n"
    "/remove_ai - Remove your saved AI configuration\n"
    "/cancel - Cancel the active workflow"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Introduce the bot."""

    if update.effective_message:
        await update.effective_message.reply_text(WELCOME_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List commands without changing conversation state."""

    if update.effective_message:
        await update.effective_message.reply_text(HELP_TEXT)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Clear temporary state and end the current conversation."""

    context.user_data.pop("general_email", None)
    context.user_data.pop("ai_configuration", None)
    LOGGER.info("Email workflow cancelled")
    if update.effective_message:
        await update.effective_message.reply_text(
            "❌ Email cancelled. Nothing was sent. Use /send to start again."
        )
    return ConversationHandler.END


async def unknown_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Respond to unsupported commands instead of silently ignoring them."""

    if update.effective_message:
        await update.effective_message.reply_text(
            "I do not recognize that command. Use /help to see available commands."
        )

