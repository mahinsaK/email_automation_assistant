"""Telegram adapter for the general email workflow."""

from __future__ import annotations

import logging
from collections.abc import Callable

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from app.bot.states import GeneralEmailState
from app.services.validation import InputValidationError, validate_email, validate_text
from app.workflows.general_email import GeneralEmailRequest, GeneralEmailWorkflow


LOGGER = logging.getLogger(__name__)


def build_general_email_callbacks(
    workflow: GeneralEmailWorkflow,
) -> tuple[Callable, Callable, Callable, Callable]:
    """Create Telegram callbacks with the workflow injected as a dependency."""

    async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data["general_email"] = {}
        LOGGER.info("General email workflow started")
        if update.effective_message:
            await update.effective_message.reply_text(
                "What is the recipient's email address?"
            )
        return GeneralEmailState.WAITING_RECIPIENT

    async def receive_recipient(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        text = update.effective_message.text if update.effective_message else ""
        try:
            workflow_data = context.user_data.setdefault("general_email", {})
            workflow_data["recipient"] = validate_email(text or "")
        except InputValidationError as error:
            await update.effective_message.reply_text(f"{error} Please enter it again.")
            return GeneralEmailState.WAITING_RECIPIENT

        await update.effective_message.reply_text(
            "What is the purpose of the email?\n"
            "For example: meeting request, introduction, or follow-up."
        )
        return GeneralEmailState.WAITING_PURPOSE

    async def receive_purpose(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        text = update.effective_message.text if update.effective_message else ""
        try:
            workflow_data = context.user_data.setdefault("general_email", {})
            workflow_data["purpose"] = validate_text(
                text or "",
                field_name="Purpose",
                max_length=200,
            )
        except InputValidationError as error:
            await update.effective_message.reply_text(f"{error} Please enter it again.")
            return GeneralEmailState.WAITING_PURPOSE

        await update.effective_message.reply_text(
            "Add the important context to include in the email."
        )
        return GeneralEmailState.WAITING_CONTEXT

    async def receive_context(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        text = update.effective_message.text if update.effective_message else ""
        try:
            additional_context = validate_text(
                text or "",
                field_name="Additional context",
                max_length=4000,
            )
            workflow_data = context.user_data["general_email"]
            request = GeneralEmailRequest(
                recipient=str(workflow_data["recipient"]),
                purpose=str(workflow_data["purpose"]),
                context=additional_context,
            )
            draft = await workflow.create_draft(request)
        except InputValidationError as error:
            await update.effective_message.reply_text(f"{error} Please enter it again.")
            return GeneralEmailState.WAITING_CONTEXT
        except (KeyError, TypeError):
            LOGGER.warning("Incomplete temporary workflow state")
            context.user_data.pop("general_email", None)
            await update.effective_message.reply_text(
                "Your draft details were incomplete. Please restart with /send."
            )
            return ConversationHandler.END
        except Exception:
            LOGGER.exception("Email draft generation failed")
            context.user_data.pop("general_email", None)
            await update.effective_message.reply_text(
                "I could not create the draft. Please try /send again."
            )
            return ConversationHandler.END

        LOGGER.info("Email draft generated and previewed")
        context.user_data.pop("general_email", None)
        await update.effective_message.reply_text(draft.as_preview())
        await update.effective_message.reply_text(
            "Preview complete. Phase 1 does not send emails."
        )
        return ConversationHandler.END

    return begin, receive_recipient, receive_purpose, receive_context

