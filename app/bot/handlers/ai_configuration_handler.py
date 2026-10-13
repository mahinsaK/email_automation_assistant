"""Telegram adapter for per-user bring-your-own-AI configuration."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from telegram import Message, Update
from telegram.ext import ContextTypes, ConversationHandler

from app.bot.keyboards import (
    AI_CONFIG_CANCEL,
    AI_CONFIG_REPLACE,
    AI_CONFIG_RETRY,
    AI_PROVIDER_CALLBACKS,
    AI_REMOVE_CONFIRM,
    AI_REMOVE_KEEP,
    ai_provider_keyboard,
    ai_remove_keyboard,
    ai_replace_keyboard,
    ai_validation_retry_keyboard,
    draft_method_keyboard,
)
from app.bot.states import GeneralEmailState
from app.models.ai_configuration import AIProviderType
from app.services.ai_configuration import (
    AIConfigurationUnavailableError,
    AIValidationUnavailableError,
    InvalidAICredentialError,
    UnsupportedAIProviderError,
    UserAIConfigurationService,
)


LOGGER = logging.getLogger(__name__)
CONFIGURATION_KEY = "ai_configuration"
EMAIL_WORKFLOW_KEY = "general_email"

Callback = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[int | None]]


@dataclass(frozen=True, slots=True)
class AIConfigurationCallbacks:
    """Named callbacks for AI configuration, status, and removal."""

    begin: Callback
    begin_from_email: Callback
    handle_replace: Callback
    handle_provider: Callback
    receive_api_key: Callback
    handle_retry: Callback
    status: Callback
    begin_remove: Callback
    handle_remove: Callback
    handle_invalid_callback: Callback


def _telegram_user_id(update: Update) -> int | None:
    user = update.effective_user
    return user.id if user is not None else None


def _configuration_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    value = context.user_data.get(CONFIGURATION_KEY)
    return value if isinstance(value, dict) else None


def build_ai_configuration_callbacks(
    service: UserAIConfigurationService,
    *,
    application_ai_available: bool = False,
) -> AIConfigurationCallbacks:
    """Create Telegram callbacks around the configuration application service."""

    async def _return_after_configuration(
        message: Message | None,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        data = _configuration_data(context)
        resume_email = bool(data and data.get("resume_email"))
        context.user_data.pop(CONFIGURATION_KEY, None)
        email_data = context.user_data.get(EMAIL_WORKFLOW_KEY)
        if resume_email and isinstance(email_data, dict) and "recipient" in email_data:
            if message:
                await message.reply_text(
                    "How would you like to create this email?",
                    reply_markup=draft_method_keyboard(),
                )
            return GeneralEmailState.WAITING_DRAFT_METHOD
        return ConversationHandler.END

    async def _begin(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        resume_email: bool,
    ) -> int:
        message = update.effective_message
        user_id = _telegram_user_id(update)
        if message is None or user_id is None:
            return ConversationHandler.END

        LOGGER.info("AI configuration started")
        context.user_data[CONFIGURATION_KEY] = {"resume_email": resume_email}
        if not service.credential_storage_available:
            await message.reply_text(
                "⚠️ Secure AI credential storage is not available.\n\n"
                "The bot administrator must configure CREDENTIAL_ENCRYPTION_KEY. "
                "Manual email drafting is still available."
            )
            return await _return_after_configuration(message, context)

        try:
            existing = await service.get_status(user_id)
        except AIConfigurationUnavailableError:
            await message.reply_text(
                "⚠️ AI configuration storage is unavailable right now.\n\n"
                "Your existing configuration has not been changed."
            )
            return await _return_after_configuration(message, context)

        if existing is not None:
            await message.reply_text(
                "AI is already configured.\n\n"
                f"Provider: {existing.provider.display_name}\n\n"
                "Would you like to replace it?",
                reply_markup=ai_replace_keyboard(),
            )
            return GeneralEmailState.AI_CONFIG_REPLACE_CONFIRM

        await message.reply_text(
            "Choose an AI provider:",
            reply_markup=ai_provider_keyboard(),
        )
        return GeneralEmailState.AI_CONFIG_PROVIDER

    async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        email_data = context.user_data.get(EMAIL_WORKFLOW_KEY)
        resume_email = isinstance(email_data, dict) and "recipient" in email_data
        return await _begin(update, context, resume_email=resume_email)

    async def begin_from_email(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        return await _begin(update, context, resume_email=True)

    async def _cancel(
        query: Any,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        if query.message:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("AI configuration cancelled.")
        return await _return_after_configuration(query.message, context)

    async def _invalid_after_answer(
        query: Any,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        context.user_data.pop(CONFIGURATION_KEY, None)
        if query.message:
            await query.message.reply_text(
                "That AI configuration action is no longer valid. "
                "Use /configure_ai to start again."
            )
        LOGGER.warning("Stale or invalid AI configuration callback received")
        return ConversationHandler.END

    async def handle_replace(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        query = update.callback_query
        if query is None:
            return ConversationHandler.END
        await query.answer()
        if _configuration_data(context) is None:
            return await _invalid_after_answer(query, context)
        if query.data == AI_CONFIG_CANCEL:
            return await _cancel(query, context)
        if query.data != AI_CONFIG_REPLACE:
            return await _invalid_after_answer(query, context)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "Choose the replacement AI provider:",
            reply_markup=ai_provider_keyboard(),
        )
        return GeneralEmailState.AI_CONFIG_PROVIDER

    async def handle_provider(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        query = update.callback_query
        if query is None:
            return ConversationHandler.END
        await query.answer()
        data = _configuration_data(context)
        if data is None:
            return await _invalid_after_answer(query, context)
        if query.data == AI_CONFIG_CANCEL:
            return await _cancel(query, context)
        provider = AI_PROVIDER_CALLBACKS.get(query.data or "")
        if provider is None:
            return await _invalid_after_answer(query, context)

        data["provider"] = provider
        LOGGER.info("AI provider selected")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"Send your {provider.display_name} API key.\n\n"
            "For security, the key will not be shown back after configuration."
        )
        return GeneralEmailState.AI_CONFIG_API_KEY

    async def receive_api_key(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        message = update.effective_message
        user_id = _telegram_user_id(update)
        data = _configuration_data(context)
        provider = data.get("provider") if data else None
        if (
            message is None
            or user_id is None
            or not isinstance(provider, AIProviderType)
        ):
            context.user_data.pop(CONFIGURATION_KEY, None)
            if message:
                await message.reply_text(
                    "This AI configuration session is no longer active. "
                    "Use /configure_ai to start again."
                )
            return ConversationHandler.END

        api_key = (message.text or "").strip()
        try:
            delete = getattr(message, "delete", None)
            if callable(delete):
                await delete()
        except Exception:
            LOGGER.warning("Could not delete Telegram credential message")

        if not api_key:
            api_key = ""
            await message.reply_text(
                "❌ The API key cannot be empty. Please try again.",
                reply_markup=ai_validation_retry_keyboard(),
            )
            return GeneralEmailState.AI_CONFIG_RETRY

        await message.reply_text("Validating your API key...")
        try:
            try:
                result = await service.configure(
                    telegram_user_id=user_id,
                    provider=provider,
                    api_key=api_key,
                )
            finally:
                api_key = ""
        except InvalidAICredentialError:
            await message.reply_text(
                "❌ That API key could not be validated.\n\n"
                "Please check the key and try again.",
                reply_markup=ai_validation_retry_keyboard(),
            )
            return GeneralEmailState.AI_CONFIG_RETRY
        except AIValidationUnavailableError:
            await message.reply_text(
                "⚠️ The provider could not be reached right now.\n\n"
                "Your key has not been saved. Please try again later.",
                reply_markup=ai_validation_retry_keyboard(),
            )
            return GeneralEmailState.AI_CONFIG_RETRY
        except (AIConfigurationUnavailableError, UnsupportedAIProviderError):
            await message.reply_text(
                "⚠️ Your AI configuration could not be saved.\n\n"
                "Your existing configuration has not been changed.",
                reply_markup=ai_validation_retry_keyboard(),
            )
            return GeneralEmailState.AI_CONFIG_RETRY

        action = "replaced" if result.replaced else "configured"
        await message.reply_text(
            f"✅ AI {action} successfully.\n\n"
            f"Provider: {result.provider.display_name}\n\n"
            "AI draft generation is now available for your account."
        )
        return await _return_after_configuration(message, context)

    async def handle_retry(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        query = update.callback_query
        if query is None:
            return ConversationHandler.END
        await query.answer()
        if _configuration_data(context) is None:
            return await _invalid_after_answer(query, context)
        if query.data == AI_CONFIG_CANCEL:
            return await _cancel(query, context)
        if query.data != AI_CONFIG_RETRY:
            return await _invalid_after_answer(query, context)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("Send the API key again.")
        return GeneralEmailState.AI_CONFIG_API_KEY

    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user_id = _telegram_user_id(update)
        if message is None or user_id is None:
            return
        try:
            configuration = await service.get_status(user_id)
        except AIConfigurationUnavailableError:
            await message.reply_text(
                "⚠️ AI status is temporarily unavailable.\n\n"
                "Manual email drafting is still available."
            )
            return

        try:
            usable = await service.is_configured(user_id)
        except AIConfigurationUnavailableError:
            usable = False
        if configuration is not None and usable:
            await message.reply_text(
                "🤖 AI Status\n\n"
                f"Provider: {configuration.provider.display_name}\n"
                "Status: Configured ✅\n"
                "Credential: Stored securely\n\n"
                "AI generation is available."
            )
            return
        if configuration is not None:
            await message.reply_text(
                "🤖 AI Status\n\n"
                f"Provider: {configuration.provider.display_name}\n"
                "Status: Stored but unavailable ⚠️\n\n"
                "The server encryption key must be restored before AI can be used."
            )
            return
        if application_ai_available:
            await message.reply_text(
                "🤖 AI Status\n\n"
                "Personal configuration: Not configured\n"
                "Application development fallback: Available ✅"
            )
            return
        await message.reply_text(
            "🤖 AI Status\n\n"
            "Status: Not configured\n\n"
            "Use /configure_ai to enable AI generation. "
            "Manual email drafting is still available."
        )

    async def begin_remove(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        message = update.effective_message
        user_id = _telegram_user_id(update)
        if message is None or user_id is None:
            return ConversationHandler.END
        try:
            existing = await service.get_status(user_id)
        except AIConfigurationUnavailableError:
            await message.reply_text("⚠️ AI configuration storage is unavailable.")
            return ConversationHandler.END
        if existing is None:
            await message.reply_text(
                "You do not have a saved AI configuration. "
                "Manual email drafting remains available."
            )
            return ConversationHandler.END
        await message.reply_text(
            "Remove your saved AI configuration?",
            reply_markup=ai_remove_keyboard(),
        )
        return GeneralEmailState.AI_REMOVE_CONFIRM

    async def handle_remove(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        query = update.callback_query
        user_id = _telegram_user_id(update)
        if query is None or user_id is None:
            return ConversationHandler.END
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=None)
        if query.data == AI_REMOVE_KEEP:
            await query.message.reply_text("Your AI configuration was kept.")
            return ConversationHandler.END
        if query.data != AI_REMOVE_CONFIRM:
            return await _invalid_after_answer(query, context)
        try:
            await service.remove(user_id)
        except AIConfigurationUnavailableError:
            await query.message.reply_text(
                "⚠️ Your AI configuration could not be removed right now."
            )
            return ConversationHandler.END
        await query.message.reply_text(
            "✅ Your AI configuration has been removed.\n\n"
            "Manual email drafting is still available."
        )
        return ConversationHandler.END

    async def handle_invalid_callback(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        context.user_data.pop(CONFIGURATION_KEY, None)
        query = update.callback_query
        if query:
            await query.answer()
            if query.message:
                await query.message.reply_text(
                    "That AI configuration action is no longer valid. "
                    "Use /configure_ai to start again."
                )
        LOGGER.warning("Stale or invalid AI configuration callback received")
        return ConversationHandler.END

    return AIConfigurationCallbacks(
        begin=begin,
        begin_from_email=begin_from_email,
        handle_replace=handle_replace,
        handle_provider=handle_provider,
        receive_api_key=receive_api_key,
        handle_retry=handle_retry,
        status=status,
        begin_remove=begin_remove,
        handle_remove=handle_remove,
        handle_invalid_callback=handle_invalid_callback,
    )
