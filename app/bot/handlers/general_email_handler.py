"""Telegram adapter for the general email approval workflow."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from telegram import Message, Update
from telegram.ext import ContextTypes, ConversationHandler

from app.bot.keyboards import (
    AI_CONFIGURE,
    AI_ENTER_MANUAL,
    AI_UNAVAILABLE_CANCEL,
    BACK_TO_PREVIEW,
    CANCEL,
    CONFIRM,
    DRAFT_AI,
    DRAFT_MANUAL,
    EDIT,
    EDIT_BODY,
    EDIT_CONTEXT,
    EDIT_RECIPIENT,
    EDIT_SUBJECT,
    EMAIL_GMAIL_BACK,
    REGENERATE,
    TONE_CALLBACKS,
    ai_unavailable_keyboard,
    draft_method_keyboard,
    edit_menu_keyboard,
    email_gmail_required_keyboard,
    preview_actions_keyboard,
    tone_keyboard,
)
from app.bot.states import GeneralEmailState
from app.services.validation import (
    MAX_BODY_LENGTH,
    MAX_CONTEXT_LENGTH,
    MAX_PURPOSE_LENGTH,
    MAX_SUBJECT_LENGTH,
    InputValidationError,
    validate_email,
    validate_text,
)
from app.services.email_generator import EmailGenerator
from app.services.gmail.client import GmailClientError
from app.services.gmail_connection import (
    GmailAuthorizationError,
    GmailConnectionError,
)
from app.services.ai_configuration import AIConfigurationError
from app.services.user_email_generator import UserEmailGeneratorResolver
from app.services.user_email_sender import UserEmailSenderResolver
from app.workflows.general_email import (
    DraftMode,
    GeneralEmailRequest,
    GeneralEmailSession,
    GeneralEmailWorkflow,
)


LOGGER = logging.getLogger(__name__)
WORKFLOW_KEY = "general_email"
STALE_MESSAGE = "This email draft is no longer active. Use /send to start a new email."

Callback = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[int | None]]
AuthorizationURL = Callable[[int], Awaitable[str | None]]


@dataclass(frozen=True, slots=True)
class GeneralEmailCallbacks:
    """Named Telegram callbacks used by the router's explicit state machine."""

    begin: Callback
    receive_recipient: Callback
    handle_draft_method: Callback
    handle_ai_unavailable: Callback
    receive_manual_subject: Callback
    receive_manual_body: Callback
    receive_purpose: Callback
    receive_context: Callback
    handle_tone: Callback
    handle_action: Callback
    handle_edit_choice: Callback
    receive_edited_recipient: Callback
    receive_edited_subject: Callback
    receive_edited_body: Callback
    receive_edited_context: Callback
    handle_invalid_callback: Callback


def _workflow_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    value = context.user_data.get(WORKFLOW_KEY)
    return value if isinstance(value, dict) else None


def _active_session(
    context: ContextTypes.DEFAULT_TYPE,
) -> GeneralEmailSession | None:
    data = _workflow_data(context)
    session = data.get("session") if data else None
    return session if isinstance(session, GeneralEmailSession) else None


def _store_session(
    context: ContextTypes.DEFAULT_TYPE,
    session: GeneralEmailSession,
) -> None:
    context.user_data[WORKFLOW_KEY] = {"session": session}


async def _show_preview(message: Message, session: GeneralEmailSession) -> None:
    """Render previews safely within Telegram's message-size limit."""

    preview = session.draft.as_preview()
    chunks = [preview[index : index + 4000] for index in range(0, len(preview), 4000)]
    for index, chunk in enumerate(chunks):
        keyboard = (
            preview_actions_keyboard(session.draft_mode)
            if index == len(chunks) - 1
            else None
        )
        await message.reply_text(chunk, reply_markup=keyboard)


async def _show_stale(message: Message | None) -> int:
    LOGGER.warning("Stale email workflow callback or input received")
    if message:
        await message.reply_text(STALE_MESSAGE)
    return ConversationHandler.END


def build_general_email_callbacks(
    workflow: GeneralEmailWorkflow,
    *,
    generator_resolver: UserEmailGeneratorResolver | None = None,
    sender_resolver: UserEmailSenderResolver | None = None,
    gmail_authorization_url: AuthorizationURL | None = None,
    start_ai_configuration: Callback | None = None,
) -> GeneralEmailCallbacks:
    """Create Telegram callbacks with application workflow dependencies injected."""

    async def _ai_available(update: Update) -> bool:
        if generator_resolver is None:
            return workflow.ai_available
        user = update.effective_user
        if user is None:
            return False
        try:
            return await generator_resolver.is_available(user.id)
        except Exception:
            LOGGER.exception("User AI availability lookup failed")
            return False

    async def _resolve_generator(update: Update) -> EmailGenerator | None:
        if generator_resolver is None:
            return None
        user = update.effective_user
        if user is None:
            return None
        return await generator_resolver.resolve(user.id)

    async def _offer_gmail_connection(
        update: Update,
        *,
        invalid: bool = False,
    ) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None:
            return
        authorization_url = None
        if user is not None and gmail_authorization_url is not None:
            authorization_url = await gmail_authorization_url(user.id)
        text = (
            "⚠️ Your Gmail connection is no longer valid.\n\n"
            "Reconnect Gmail before sending. Your email draft has been kept."
            if invalid
            else "📧 Gmail is not connected.\n\n"
            "Connect Gmail before sending. Your email draft has been kept."
        )
        await message.reply_text(
            text,
            reply_markup=email_gmail_required_keyboard(authorization_url),
        )

    async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data.pop("ai_configuration", None)
        context.user_data.pop("job_application", None)
        context.user_data[WORKFLOW_KEY] = {}
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
        message = update.effective_message
        text = message.text if message else ""
        try:
            data = context.user_data.setdefault(WORKFLOW_KEY, {})
            data["recipient"] = validate_email(text or "")
        except InputValidationError as error:
            if message:
                await message.reply_text(f"{error} Please enter it again.")
            return GeneralEmailState.WAITING_RECIPIENT

        if message:
            await message.reply_text(
                "How would you like to create this email?",
                reply_markup=draft_method_keyboard(),
            )
        return GeneralEmailState.WAITING_DRAFT_METHOD

    async def handle_draft_method(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        query = update.callback_query
        if not query:
            return await _show_stale(update.effective_message)
        await query.answer()
        if not query.message:
            return await _show_stale(None)

        data = _workflow_data(context)
        if data is None or "recipient" not in data:
            return await _show_stale(query.message)

        if query.data == DRAFT_MANUAL:
            data["draft_mode"] = DraftMode.MANUAL
            LOGGER.info("Manual draft mode selected")
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("Enter the email subject:")
            return GeneralEmailState.MANUAL_WAITING_SUBJECT

        if query.data == DRAFT_AI:
            data["draft_mode"] = DraftMode.AI
            LOGGER.info("AI draft mode selected")
            await query.edit_message_reply_markup(reply_markup=None)
            if await _ai_available(update):
                await query.message.reply_text(
                    "What is the purpose of the email?\n"
                    "For example: meeting request, introduction, or follow-up."
                )
                return GeneralEmailState.WAITING_PURPOSE

            LOGGER.info("AI generation unavailable")
            await query.message.reply_text(
                "🤖 AI generation is not configured for your account.\n\n"
                "You can still create and approve emails manually.",
                reply_markup=ai_unavailable_keyboard(),
            )
            return GeneralEmailState.WAITING_AI_UNAVAILABLE_ACTION

        LOGGER.warning("Invalid draft method callback received")
        await query.message.reply_text(
            "That draft method is not supported. Use one of the current buttons."
        )
        return GeneralEmailState.WAITING_DRAFT_METHOD

    async def handle_ai_unavailable(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        query = update.callback_query
        if not query:
            return await _show_stale(update.effective_message)
        await query.answer()
        if not query.message:
            return await _show_stale(None)
        if _workflow_data(context) is None:
            return await _show_stale(query.message)

        if query.data == AI_CONFIGURE:
            if start_ai_configuration is not None:
                return await start_ai_configuration(update, context)
            await query.message.reply_text(
                "AI configuration through Telegram is not available yet. "
                "Configure the server environment or enter the draft manually."
            )
            return GeneralEmailState.WAITING_AI_UNAVAILABLE_ACTION

        if query.data == AI_ENTER_MANUAL:
            data = _workflow_data(context)
            if data is None:
                return await _show_stale(query.message)
            data["draft_mode"] = DraftMode.MANUAL
            LOGGER.info("Manual draft mode selected after unavailable AI request")
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("Enter the email subject:")
            return GeneralEmailState.MANUAL_WAITING_SUBJECT

        if query.data == AI_UNAVAILABLE_CANCEL:
            context.user_data.pop(WORKFLOW_KEY, None)
            LOGGER.info("Email workflow cancelled")
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("❌ Email cancelled.\n\nNothing was sent.")
            return ConversationHandler.END

        LOGGER.warning("Invalid unavailable-AI action received")
        await query.message.reply_text(
            "That action is not supported. Use one of the current buttons."
        )
        return GeneralEmailState.WAITING_AI_UNAVAILABLE_ACTION

    async def receive_manual_subject(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        message = update.effective_message
        text = message.text if message else ""
        data = _workflow_data(context)
        if data is None:
            return await _show_stale(message)
        try:
            data["manual_subject"] = validate_text(
                text or "",
                field_name="Subject",
                max_length=MAX_SUBJECT_LENGTH,
            )
        except InputValidationError as error:
            if message:
                await message.reply_text(f"{error} Please enter the subject again.")
            return GeneralEmailState.MANUAL_WAITING_SUBJECT

        if message:
            await message.reply_text("Enter the email body:")
        return GeneralEmailState.MANUAL_WAITING_BODY

    async def receive_manual_body(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        message = update.effective_message
        text = message.text if message else ""
        data = _workflow_data(context)
        if data is None:
            return await _show_stale(message)
        try:
            body = validate_text(
                text or "",
                field_name="Email body",
                max_length=MAX_BODY_LENGTH,
            )
            session = workflow.start_manual(
                recipient=str(data["recipient"]),
                subject=str(data["manual_subject"]),
                body=body,
            )
        except InputValidationError as error:
            if message:
                await message.reply_text(f"{error} Please enter the body again.")
            return GeneralEmailState.MANUAL_WAITING_BODY
        except (KeyError, TypeError):
            context.user_data.pop(WORKFLOW_KEY, None)
            return await _show_stale(message)

        _store_session(context, session)
        if message:
            await _show_preview(message, session)
        return GeneralEmailState.WAITING_FOR_ACTION

    async def receive_purpose(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        message = update.effective_message
        text = message.text if message else ""
        try:
            data = context.user_data.setdefault(WORKFLOW_KEY, {})
            data["purpose"] = validate_text(
                text or "",
                field_name="Purpose",
                max_length=MAX_PURPOSE_LENGTH,
            )
        except InputValidationError as error:
            if message:
                await message.reply_text(f"{error} Please enter it again.")
            return GeneralEmailState.WAITING_PURPOSE

        if message:
            await message.reply_text("Add the important context to include in the email.")
        return GeneralEmailState.WAITING_CONTEXT

    async def receive_context(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        message = update.effective_message
        text = message.text if message else ""
        try:
            additional_context = validate_text(
                text or "",
                field_name="Additional context",
                max_length=MAX_CONTEXT_LENGTH,
            )
            data = context.user_data[WORKFLOW_KEY]
            data["context"] = additional_context
        except InputValidationError as error:
            if message:
                await message.reply_text(f"{error} Please enter it again.")
            return GeneralEmailState.WAITING_CONTEXT
        except (KeyError, TypeError):
            context.user_data.pop(WORKFLOW_KEY, None)
            return await _show_stale(message)

        if message:
            await message.reply_text(
                "Choose the tone for this email:",
                reply_markup=tone_keyboard(),
            )
        return GeneralEmailState.WAITING_TONE

    async def handle_tone(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        query = update.callback_query
        if not query:
            return await _show_stale(update.effective_message)
        await query.answer()
        if not query.message:
            return await _show_stale(None)

        tone = TONE_CALLBACKS.get(query.data or "")
        data = _workflow_data(context)
        if tone is None:
            LOGGER.warning("Invalid tone callback received")
            await query.message.reply_text(
                "That tone is not supported. Please use one of the current buttons."
            )
            return GeneralEmailState.WAITING_TONE
        if data is None:
            return await _show_stale(query.message)

        try:
            generator = await _resolve_generator(update)
            if generator_resolver is not None and generator is None:
                await query.message.reply_text(
                    "🤖 AI generation is no longer configured.\n\n"
                    "Choose Configure AI or enter the draft manually.",
                    reply_markup=ai_unavailable_keyboard(),
                )
                return GeneralEmailState.WAITING_AI_UNAVAILABLE_ACTION
            request = GeneralEmailRequest(
                recipient=str(data["recipient"]),
                purpose=str(data["purpose"]),
                context=str(data["context"]),
                tone=tone,
            )
            session = await workflow.start(request, generator=generator)
        except (KeyError, TypeError):
            context.user_data.pop(WORKFLOW_KEY, None)
            return await _show_stale(query.message)
        except AIConfigurationError:
            LOGGER.warning("User AI configuration could not be resolved")
            await query.message.reply_text(
                "⚠️ Your AI configuration is unavailable right now.\n\n"
                "You can configure AI again or enter the draft manually.",
                reply_markup=ai_unavailable_keyboard(),
            )
            return GeneralEmailState.WAITING_AI_UNAVAILABLE_ACTION
        except Exception:
            LOGGER.exception("Email draft generation failed")
            context.user_data.pop(WORKFLOW_KEY, None)
            await query.message.reply_text(
                "I could not create the draft. Please try /send again."
            )
            return ConversationHandler.END

        await query.edit_message_reply_markup(reply_markup=None)
        _store_session(context, session)
        LOGGER.info("Email draft generated and previewed")
        await _show_preview(query.message, session)
        return GeneralEmailState.WAITING_FOR_ACTION

    async def handle_action(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        query = update.callback_query
        if not query:
            return await _show_stale(update.effective_message)
        await query.answer()
        if not query.message:
            return await _show_stale(None)

        session = _active_session(context)
        if not session:
            return await _show_stale(query.message)

        if query.data == CONFIRM:
            sender = None
            if sender_resolver is not None:
                user = update.effective_user
                if user is None:
                    return await _show_stale(query.message)
                try:
                    sender = await sender_resolver.resolve(user.id)
                except GmailAuthorizationError:
                    await _offer_gmail_connection(update, invalid=True)
                    return GeneralEmailState.WAITING_FOR_ACTION
                except (GmailConnectionError, GmailClientError):
                    LOGGER.warning("Gmail sender could not be resolved")
                    await query.message.reply_text(
                        "⚠️ Gmail is temporarily unavailable. Your draft was kept."
                    )
                    return GeneralEmailState.WAITING_FOR_ACTION
                if sender is None:
                    await _offer_gmail_connection(update)
                    return GeneralEmailState.WAITING_FOR_ACTION

            outcome = await workflow.approve(session, sender=sender)
            if outcome.duplicate:
                await query.message.reply_text(
                    "This draft is already being processed. It was not submitted twice."
                )
                return GeneralEmailState.WAITING_FOR_ACTION

            _store_session(context, outcome.session)
            if outcome.result.success:
                await query.edit_message_reply_markup(reply_markup=None)
                context.user_data.pop(WORKFLOW_KEY, None)
                if sender_resolver is None:
                    success_text = (
                        "✅ Email approved and mock-send completed successfully.\n\n"
                        f"To:\n{outcome.session.draft.recipient}\n\n"
                        f"Subject:\n{outcome.session.draft.subject}\n\n"
                        "Real Gmail delivery is not enabled in this test setup."
                    )
                else:
                    success_text = (
                        "✅ Email sent successfully.\n\n"
                        f"To:\n{outcome.session.draft.recipient}\n\n"
                        f"Subject:\n{outcome.session.draft.subject}"
                    )
                await query.message.reply_text(success_text)
                return ConversationHandler.END

            await query.edit_message_reply_markup(reply_markup=None)
            if outcome.result.error_code == "gmail_authorization_invalid":
                await _offer_gmail_connection(update, invalid=True)
                await _show_preview(query.message, outcome.session)
                return GeneralEmailState.WAITING_FOR_ACTION
            await query.message.reply_text(
                "⚠️ The email could not be sent.\n\n"
                "The draft was kept. You can try again or cancel."
            )
            await _show_preview(query.message, outcome.session)
            return GeneralEmailState.WAITING_FOR_ACTION

        if query.data == EMAIL_GMAIL_BACK:
            await query.edit_message_reply_markup(reply_markup=None)
            await _show_preview(query.message, session)
            return GeneralEmailState.WAITING_FOR_ACTION

        if query.data == REGENERATE:
            if session.draft_mode is DraftMode.MANUAL:
                LOGGER.warning("Regenerate callback rejected for manual draft")
                await query.message.reply_text(
                    "Manual drafts cannot be regenerated. Use Edit to change the text."
                )
                return GeneralEmailState.WAITING_FOR_ACTION
            try:
                generator = await _resolve_generator(update)
                if generator_resolver is not None and generator is None:
                    await query.message.reply_text(
                        "AI generation is no longer configured. Your draft is unchanged."
                    )
                    return GeneralEmailState.WAITING_FOR_ACTION
                regenerated = await workflow.regenerate(
                    session,
                    generator=generator,
                )
            except Exception:
                LOGGER.exception("Email draft regeneration failed")
                await query.message.reply_text(
                    "I could not regenerate the draft. Your current draft is unchanged."
                )
                return GeneralEmailState.WAITING_FOR_ACTION
            await query.edit_message_reply_markup(reply_markup=None)
            _store_session(context, regenerated)
            await _show_preview(query.message, regenerated)
            return GeneralEmailState.WAITING_FOR_ACTION

        if query.data == EDIT:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                "What would you like to edit?",
                reply_markup=edit_menu_keyboard(session.draft_mode),
            )
            return GeneralEmailState.EDIT_MENU

        if query.data == CANCEL:
            workflow.cancel(session)
            context.user_data.pop(WORKFLOW_KEY, None)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("❌ Email cancelled.\n\nNothing was sent.")
            return ConversationHandler.END

        LOGGER.warning("Unknown email action callback received")
        await query.message.reply_text("That action is not valid. Use the current buttons.")
        return GeneralEmailState.WAITING_FOR_ACTION

    async def handle_edit_choice(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        query = update.callback_query
        if not query:
            return await _show_stale(update.effective_message)
        await query.answer()
        if not query.message:
            return await _show_stale(None)
        session = _active_session(context)
        if not session:
            return await _show_stale(query.message)

        prompts = {
            EDIT_RECIPIENT: (
                "Enter the new recipient email address.",
                GeneralEmailState.EDIT_RECIPIENT,
            ),
            EDIT_SUBJECT: ("Enter the new subject.", GeneralEmailState.EDIT_SUBJECT),
            EDIT_BODY: ("Enter the new email message.", GeneralEmailState.EDIT_BODY),
            EDIT_CONTEXT: (
                "Enter the new original context. This will regenerate the draft.",
                GeneralEmailState.EDIT_CONTEXT,
            ),
        }
        if query.data == BACK_TO_PREVIEW:
            await query.edit_message_reply_markup(reply_markup=None)
            await _show_preview(query.message, session)
            return GeneralEmailState.WAITING_FOR_ACTION

        if query.data == EDIT_CONTEXT and session.draft_mode is DraftMode.MANUAL:
            LOGGER.warning("Context edit callback rejected for manual draft")
            await query.message.reply_text(
                "Manual drafts do not have generation context. "
                "Edit the subject or message instead."
            )
            return GeneralEmailState.EDIT_MENU

        selection = prompts.get(query.data or "")
        if not selection:
            LOGGER.warning("Unknown edit callback received")
            await query.message.reply_text(
                "That edit option is not valid. Use the current buttons."
            )
            return GeneralEmailState.EDIT_MENU

        prompt, next_state = selection
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(prompt)
        return next_state

    async def receive_edited_recipient(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        message = update.effective_message
        session = _active_session(context)
        if not session:
            return await _show_stale(message)
        try:
            updated = workflow.edit_recipient(session, message.text if message else "")
        except InputValidationError as error:
            if message:
                await message.reply_text(f"{error} Please enter it again.")
            return GeneralEmailState.EDIT_RECIPIENT
        _store_session(context, updated)
        if message:
            await _show_preview(message, updated)
        return GeneralEmailState.WAITING_FOR_ACTION

    async def receive_edited_subject(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        message = update.effective_message
        session = _active_session(context)
        if not session:
            return await _show_stale(message)
        try:
            updated = workflow.edit_subject(session, message.text if message else "")
        except InputValidationError as error:
            if message:
                await message.reply_text(f"{error} Please enter it again.")
            return GeneralEmailState.EDIT_SUBJECT
        _store_session(context, updated)
        if message:
            await _show_preview(message, updated)
        return GeneralEmailState.WAITING_FOR_ACTION

    async def receive_edited_body(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        message = update.effective_message
        session = _active_session(context)
        if not session:
            return await _show_stale(message)
        try:
            updated = workflow.edit_body(session, message.text if message else "")
        except InputValidationError as error:
            if message:
                await message.reply_text(f"{error} Please enter it again.")
            return GeneralEmailState.EDIT_BODY
        _store_session(context, updated)
        if message:
            await _show_preview(message, updated)
        return GeneralEmailState.WAITING_FOR_ACTION

    async def receive_edited_context(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        message = update.effective_message
        session = _active_session(context)
        if not session:
            return await _show_stale(message)
        try:
            generator = await _resolve_generator(update)
            if generator_resolver is not None and generator is None:
                if message:
                    await message.reply_text(
                        "AI generation is no longer configured. Your draft is unchanged."
                    )
                return GeneralEmailState.EDIT_CONTEXT
            updated = await workflow.edit_context(
                session,
                message.text if message else "",
                generator=generator,
            )
        except InputValidationError as error:
            if message:
                await message.reply_text(f"{error} Please enter it again.")
            return GeneralEmailState.EDIT_CONTEXT
        except Exception:
            LOGGER.exception("Email draft generation after context edit failed")
            if message:
                await message.reply_text(
                    "I could not regenerate from that context. Your draft is unchanged."
                )
            return GeneralEmailState.EDIT_CONTEXT
        _store_session(context, updated)
        if message:
            await _show_preview(message, updated)
        return GeneralEmailState.WAITING_FOR_ACTION

    async def handle_invalid_callback(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int | None:
        query = update.callback_query
        if query:
            await query.answer()
        if _workflow_data(context) is None:
            return await _show_stale(query.message if query else update.effective_message)
        LOGGER.warning("Invalid callback received for active email workflow")
        if query and query.message:
            await query.message.reply_text(
                "That action is no longer valid. Use the latest available buttons."
            )
        return None

    return GeneralEmailCallbacks(
        begin=begin,
        receive_recipient=receive_recipient,
        handle_draft_method=handle_draft_method,
        handle_ai_unavailable=handle_ai_unavailable,
        receive_manual_subject=receive_manual_subject,
        receive_manual_body=receive_manual_body,
        receive_purpose=receive_purpose,
        receive_context=receive_context,
        handle_tone=handle_tone,
        handle_action=handle_action,
        handle_edit_choice=handle_edit_choice,
        receive_edited_recipient=receive_edited_recipient,
        receive_edited_subject=receive_edited_subject,
        receive_edited_body=receive_edited_body,
        receive_edited_context=receive_edited_context,
        handle_invalid_callback=handle_invalid_callback,
    )
