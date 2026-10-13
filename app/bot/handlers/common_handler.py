"""Handlers shared across Telegram workflows."""

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler


WELCOME_TEXT = (
    "Welcome to AI Email Automation Assistant.\n\n"
    "I can help you create a professional email draft for review. "
    "Nothing will be sent in Phase 1.\n\n"
    "Use /send to create a draft or /help to see available commands."
)

HELP_TEXT = (
    "Available commands:\n"
    "/start - Show the welcome message\n"
    "/help - Show this help\n"
    "/send - Create a general email draft\n"
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
    if update.effective_message:
        await update.effective_message.reply_text(
            "Cancelled. No email was sent. Use /send when you want to start again."
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

