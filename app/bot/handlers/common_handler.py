"""Handlers shared across Telegram workflows."""

import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler


LOGGER = logging.getLogger(__name__)


WELCOME_TEXT = (
    "Welcome to AI Email Automation Assistant.\n\n"
    "I can help you enter a draft manually or create one with configured AI, "
    "then edit and approve it. I can also prepare grounded job application "
    "emails with your configured CV. Approved emails can be delivered only "
    "through your explicitly connected Gmail account.\n\n"
    "Use /send for a general email, /apply for a job application, or /help."
)

HELP_TEXT = (
    "Available commands:\n"
    "/start - Show the welcome message\n"
    "/help - Show this help\n"
    "/send - Create a general email draft\n"
    "/apply - Create a job/internship application email with CV attachment\n"
    "/configure_ai - Configure or replace your AI provider credential\n"
    "/ai_status - Show your AI configuration status\n"
    "/remove_ai - Remove your saved AI configuration\n"
    "/connect_gmail - Connect Gmail securely using Google OAuth\n"
    "/gmail_status - Show whether Gmail is connected\n"
    "/disconnect_gmail - Remove your saved Gmail authorization\n"
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
    context.user_data.pop("job_application", None)
    context.user_data.pop("ai_configuration", None)
    LOGGER.info("Active email workflow cancelled")
    if update.effective_message:
        await update.effective_message.reply_text(
            "❌ Workflow cancelled. Nothing was sent. "
            "Use /send or /apply to start again."
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

