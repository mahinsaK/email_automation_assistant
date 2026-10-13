"""Telegram adapter for grounded job application email preparation."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from telegram import Message, Update
from telegram.ext import ContextTypes, ConversationHandler

from app.bot.keyboards import (
    JOB_AI_CANCEL,
    JOB_AI_CONFIGURE,
    JOB_AI_ENTER_MANUAL,
    JOB_BACK_TO_PREVIEW,
    JOB_CANCEL,
    JOB_CONFIRM,
    JOB_DRAFT_AI,
    JOB_DRAFT_MANUAL,
    JOB_EDIT,
    JOB_EDIT_BODY,
    JOB_EDIT_COMPANY,
    JOB_EDIT_DESCRIPTION,
    JOB_EDIT_RECIPIENT,
    JOB_EDIT_ROLE,
    JOB_EDIT_SUBJECT,
    JOB_REGENERATE,
    JOB_TONE_CALLBACKS,
    job_ai_unavailable_keyboard,
    job_draft_method_keyboard,
    job_edit_menu_keyboard,
    job_preview_actions_keyboard,
    job_tone_keyboard,
)
from app.bot.states import JobApplicationState
from app.models.job_application import JobApplicationRequest
from app.services.ai_configuration import AIConfigurationError
from app.services.attachment import AttachmentValidationError
from app.services.candidate_profile import CandidateProfileError
from app.services.job_application_generator import (
    JobApplicationEmailGenerator,
    UserJobApplicationGeneratorResolver,
)
from app.services.validation import (
    MAX_BODY_LENGTH,
    MAX_SUBJECT_LENGTH,
    InputValidationError,
    validate_email,
    validate_text,
)
from app.workflows.general_email import DraftMode
from app.workflows.job_application import (
    MAX_COMPANY_NAME_LENGTH,
    MAX_JOB_DESCRIPTION_LENGTH,
    MAX_ROLE_LENGTH,
    JobApplicationResources,
    JobApplicationSession,
    JobApplicationWorkflow,
)


LOGGER = logging.getLogger(__name__)
WORKFLOW_KEY = "job_application"
STALE_MESSAGE = (
    "This job application draft is no longer active. "
    "Use /apply to start a new application."
)

Callback = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[int | None]]


@dataclass(frozen=True, slots=True)
class JobApplicationCallbacks:
    begin: Callback
    receive_company_email: Callback
    receive_company_name: Callback
    receive_role: Callback
    receive_job_description: Callback
    handle_draft_method: Callback
    handle_ai_unavailable: Callback
    receive_manual_subject: Callback
    receive_manual_body: Callback
    handle_tone: Callback
    handle_action: Callback
    handle_edit_choice: Callback
    receive_edited_recipient: Callback
    receive_edited_company: Callback
    receive_edited_role: Callback
    receive_edited_job_description: Callback
    receive_edited_subject: Callback
    receive_edited_body: Callback
    handle_invalid_callback: Callback


def _workflow_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    value = context.user_data.get(WORKFLOW_KEY)
    return value if isinstance(value, dict) else None


def _active_session(
    context: ContextTypes.DEFAULT_TYPE,
) -> JobApplicationSession | None:
    data = _workflow_data(context)
    session = data.get("session") if data else None
    return session if isinstance(session, JobApplicationSession) else None


def _store_session(
    context: ContextTypes.DEFAULT_TYPE,
    session: JobApplicationSession,
) -> None:
    context.user_data[WORKFLOW_KEY] = {"session": session}


def _request_from_data(data: dict[str, Any]) -> JobApplicationRequest:
    return JobApplicationRequest(
        company_email=str(data["company_email"]),
        company_name=str(data["company_name"]),
        role=str(data["role"]),
        job_description=str(data["job_description"]),
    )


async def _show_stale(message: Message | None) -> int:
    LOGGER.warning("Stale job application callback or input received")
    if message:
        await message.reply_text(STALE_MESSAGE)
    return ConversationHandler.END


async def _show_preview(message: Message, session: JobApplicationSession) -> None:
    draft = session.prepared_email.draft
    matched = ", ".join(session.match_result.matched_skills) or "None"
    preview = (
        "JOB APPLICATION PREVIEW\n\n"
        f"Company:\n{session.request.company_name}\n\n"
        f"Role:\n{session.request.role}\n\n"
        f"To:\n{draft.recipient}\n\n"
        f"Subject:\n{draft.subject}\n\n"
        f"Message:\n{draft.body}\n\n"
        f"Attachment:\n{session.attachment.file_name}\n\n"
        f"Matched requirements:\n{matched}"
    )
    chunks = [preview[index : index + 4000] for index in range(0, len(preview), 4000)]
    for index, chunk in enumerate(chunks):
        keyboard = (
            job_preview_actions_keyboard(session.draft_mode)
            if index == len(chunks) - 1
            else None
        )
        await message.reply_text(chunk, reply_markup=keyboard)


def build_job_application_callbacks(
    workflow: JobApplicationWorkflow,
    *,
    generator_resolver: UserJobApplicationGeneratorResolver | None = None,
    start_ai_configuration: Callback | None = None,
) -> JobApplicationCallbacks:
    """Create job application callbacks with dependencies injected."""

    async def _ai_available(update: Update) -> bool:
        if generator_resolver is None or update.effective_user is None:
            return False
        try:
            return await generator_resolver.is_available(update.effective_user.id)
        except Exception:
            LOGGER.exception("Job application AI availability lookup failed")
            return False

    async def _resolve_generator(
        update: Update,
    ) -> JobApplicationEmailGenerator | None:
        if generator_resolver is None or update.effective_user is None:
            return None
        return await generator_resolver.resolve(update.effective_user.id)

    async def begin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        context.user_data.pop("general_email", None)
        context.user_data.pop("ai_configuration", None)
        context.user_data[WORKFLOW_KEY] = {}
        message = update.effective_message
        LOGGER.info("Job application workflow started")
        try:
            resources = await workflow.prepare_resources()
        except CandidateProfileError:
            context.user_data.pop(WORKFLOW_KEY, None)
            if message:
                await message.reply_text(
                    "⚠️ The candidate profile is missing or invalid.\n\n"
                    "Create the configured profile JSON from "
                    "data/candidate_profile.example.json, then use /apply again."
                )
            return ConversationHandler.END
        except AttachmentValidationError:
            context.user_data.pop(WORKFLOW_KEY, None)
            if message:
                await message.reply_text(
                    "⚠️ The configured CV is missing, empty, unreadable, or has an "
                    "unsupported file type.\n\nNo application was prepared."
                )
            return ConversationHandler.END

        context.user_data[WORKFLOW_KEY] = {"resources": resources}
        if message:
            await message.reply_text("Enter the company email address:")
        return JobApplicationState.WAITING_COMPANY_EMAIL

    async def receive_company_email(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        message = update.effective_message
        data = _workflow_data(context)
        if data is None:
            return await _show_stale(message)
        try:
            data["company_email"] = validate_email(message.text if message else "")
        except InputValidationError as error:
            if message:
                await message.reply_text(f"{error} Please enter it again.")
            return JobApplicationState.WAITING_COMPANY_EMAIL
        if message:
            await message.reply_text("Enter the company name:")
        return JobApplicationState.WAITING_COMPANY_NAME

    async def _receive_text(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        key: str,
        field_name: str,
        max_length: int,
        retry_state: JobApplicationState,
        prompt: str,
        next_state: JobApplicationState,
    ) -> int:
        message = update.effective_message
        data = _workflow_data(context)
        if data is None:
            return await _show_stale(message)
        try:
            data[key] = validate_text(
                message.text if message else "",
                field_name=field_name,
                max_length=max_length,
            )
        except InputValidationError as error:
            if message:
                await message.reply_text(f"{error} Please enter it again.")
            return retry_state
        if message and prompt:
            await message.reply_text(prompt)
        return next_state

    async def receive_company_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        return await _receive_text(
            update,
            context,
            key="company_name",
            field_name="Company name",
            max_length=MAX_COMPANY_NAME_LENGTH,
            retry_state=JobApplicationState.WAITING_COMPANY_NAME,
            prompt="Enter the role you are applying for:",
            next_state=JobApplicationState.WAITING_ROLE,
        )

    async def receive_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        return await _receive_text(
            update,
            context,
            key="role",
            field_name="Role",
            max_length=MAX_ROLE_LENGTH,
            retry_state=JobApplicationState.WAITING_ROLE,
            prompt="Paste the job description:",
            next_state=JobApplicationState.WAITING_JOB_DESCRIPTION,
        )

    async def receive_job_description(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        state = await _receive_text(
            update,
            context,
            key="job_description",
            field_name="Job description",
            max_length=MAX_JOB_DESCRIPTION_LENGTH,
            retry_state=JobApplicationState.WAITING_JOB_DESCRIPTION,
            prompt="",
            next_state=JobApplicationState.WAITING_DRAFT_METHOD,
        )
        if state is JobApplicationState.WAITING_DRAFT_METHOD and update.effective_message:
            await update.effective_message.reply_text(
                "How would you like to create the application email?",
                reply_markup=job_draft_method_keyboard(),
            )
        return state

    async def handle_draft_method(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        query = update.callback_query
        if query is None:
            return await _show_stale(update.effective_message)
        await query.answer()
        data = _workflow_data(context)
        if query.message is None or data is None or "job_description" not in data:
            return await _show_stale(query.message)
        if query.data == JOB_DRAFT_MANUAL:
            data["draft_mode"] = DraftMode.MANUAL
            LOGGER.info("Manual job application mode selected")
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("Enter the application email subject:")
            return JobApplicationState.MANUAL_WAITING_SUBJECT
        if query.data == JOB_DRAFT_AI:
            data["draft_mode"] = DraftMode.AI
            LOGGER.info("AI job application mode selected")
            await query.edit_message_reply_markup(reply_markup=None)
            if await _ai_available(update):
                await query.message.reply_text(
                    "Choose the tone for the application email:",
                    reply_markup=job_tone_keyboard(),
                )
                return JobApplicationState.WAITING_TONE
            LOGGER.info("AI job application generation unavailable")
            await query.message.reply_text(
                "🤖 AI generation is not configured for your account.\n\n"
                "You can still enter the application email manually; the CV "
                "will remain attached.",
                reply_markup=job_ai_unavailable_keyboard(),
            )
            return JobApplicationState.WAITING_AI_UNAVAILABLE_ACTION
        await query.message.reply_text(
            "That draft method is not valid. Use the current buttons."
        )
        return JobApplicationState.WAITING_DRAFT_METHOD

    async def handle_ai_unavailable(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        query = update.callback_query
        if query is None:
            return await _show_stale(update.effective_message)
        await query.answer()
        if query.message is None or _workflow_data(context) is None:
            return await _show_stale(query.message)
        if query.data == JOB_AI_CONFIGURE:
            if start_ai_configuration is not None:
                return await start_ai_configuration(update, context)
            await query.message.reply_text(
                "AI configuration is unavailable here. Enter the draft manually."
            )
            return JobApplicationState.WAITING_AI_UNAVAILABLE_ACTION
        if query.data == JOB_AI_ENTER_MANUAL:
            data = _workflow_data(context)
            if data is None:
                return await _show_stale(query.message)
            data["draft_mode"] = DraftMode.MANUAL
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("Enter the application email subject:")
            return JobApplicationState.MANUAL_WAITING_SUBJECT
        if query.data == JOB_AI_CANCEL:
            context.user_data.pop(WORKFLOW_KEY, None)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                "❌ Job application cancelled.\n\nNothing was sent."
            )
            return ConversationHandler.END
        await query.message.reply_text("That action is not valid.")
        return JobApplicationState.WAITING_AI_UNAVAILABLE_ACTION

    async def receive_manual_subject(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        message = update.effective_message
        data = _workflow_data(context)
        if data is None:
            return await _show_stale(message)
        try:
            data["manual_subject"] = validate_text(
                message.text if message else "",
                field_name="Subject",
                max_length=MAX_SUBJECT_LENGTH,
            )
        except InputValidationError as error:
            if message:
                await message.reply_text(f"{error} Please enter it again.")
            return JobApplicationState.MANUAL_WAITING_SUBJECT
        if message:
            await message.reply_text("Enter the application email body:")
        return JobApplicationState.MANUAL_WAITING_BODY

    async def receive_manual_body(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        message = update.effective_message
        data = _workflow_data(context)
        if data is None:
            return await _show_stale(message)
        try:
            body = validate_text(
                message.text if message else "",
                field_name="Email body",
                max_length=MAX_BODY_LENGTH,
            )
            resources = data["resources"]
            if not isinstance(resources, JobApplicationResources):
                raise TypeError
            session = workflow.start_manual(
                request=_request_from_data(data),
                resources=resources,
                subject=str(data["manual_subject"]),
                body=body,
            )
        except InputValidationError as error:
            if message:
                await message.reply_text(f"{error} Please enter it again.")
            return JobApplicationState.MANUAL_WAITING_BODY
        except (KeyError, TypeError):
            context.user_data.pop(WORKFLOW_KEY, None)
            return await _show_stale(message)
        _store_session(context, session)
        if message:
            await _show_preview(message, session)
        return JobApplicationState.WAITING_FOR_ACTION

    async def handle_tone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        if query is None:
            return await _show_stale(update.effective_message)
        await query.answer()
        data = _workflow_data(context)
        tone = JOB_TONE_CALLBACKS.get(query.data or "")
        if query.message is None or data is None:
            return await _show_stale(query.message)
        if tone is None:
            await query.message.reply_text("That tone is not supported.")
            return JobApplicationState.WAITING_TONE
        try:
            generator = await _resolve_generator(update)
            if generator is None:
                await query.message.reply_text(
                    "🤖 AI generation is no longer configured.\n\n"
                    "Configure AI or enter the draft manually.",
                    reply_markup=job_ai_unavailable_keyboard(),
                )
                return JobApplicationState.WAITING_AI_UNAVAILABLE_ACTION
            resources = data["resources"]
            if not isinstance(resources, JobApplicationResources):
                raise TypeError
            session = await workflow.start_ai(
                request=_request_from_data(data),
                resources=resources,
                generator=generator,
                tone=tone,
            )
        except (KeyError, TypeError):
            context.user_data.pop(WORKFLOW_KEY, None)
            return await _show_stale(query.message)
        except AIConfigurationError:
            LOGGER.warning("Job application AI configuration unavailable")
            await query.message.reply_text(
                "⚠️ AI configuration is unavailable. Your application data is "
                "unchanged; choose manual drafting or configure AI.",
                reply_markup=job_ai_unavailable_keyboard(),
            )
            return JobApplicationState.WAITING_AI_UNAVAILABLE_ACTION
        except Exception:
            LOGGER.exception("Job application generation failed")
            await query.message.reply_text(
                "I could not create the application draft. Your data is unchanged."
            )
            return JobApplicationState.WAITING_TONE
        await query.edit_message_reply_markup(reply_markup=None)
        _store_session(context, session)
        await _show_preview(query.message, session)
        return JobApplicationState.WAITING_FOR_ACTION

    async def handle_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        if query is None:
            return await _show_stale(update.effective_message)
        await query.answer()
        session = _active_session(context)
        if query.message is None or session is None:
            return await _show_stale(query.message)
        if query.data == JOB_CONFIRM:
            outcome = await workflow.approve(session)
            if outcome.duplicate:
                await query.message.reply_text(
                    "This application is already being processed. It was not "
                    "submitted twice."
                )
                return JobApplicationState.WAITING_FOR_ACTION
            _store_session(context, outcome.session)
            if outcome.result.success:
                await query.edit_message_reply_markup(reply_markup=None)
                context.user_data.pop(WORKFLOW_KEY, None)
                await query.message.reply_text(
                    "✅ Job application approved and mock-send completed "
                    "successfully.\n\n"
                    f"To:\n{outcome.session.approval.draft.recipient}\n\n"
                    f"Subject:\n{outcome.session.approval.draft.subject}\n\n"
                    f"CV prepared:\n{outcome.session.attachment.file_name}\n\n"
                    "Real Gmail delivery is not enabled yet."
                )
                return ConversationHandler.END
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                "⚠️ The mock job application send could not be completed.\n\n"
                "No real email was delivered. Your draft and CV remain available."
            )
            await _show_preview(query.message, outcome.session)
            return JobApplicationState.WAITING_FOR_ACTION
        if query.data == JOB_REGENERATE:
            if session.draft_mode is DraftMode.MANUAL:
                await query.message.reply_text(
                    "Manual drafts cannot be regenerated. Use Edit instead."
                )
                return JobApplicationState.WAITING_FOR_ACTION
            try:
                generator = await _resolve_generator(update)
                if generator is None:
                    await query.message.reply_text(
                        "AI generation is no longer configured. The draft is unchanged."
                    )
                    return JobApplicationState.WAITING_FOR_ACTION
                regenerated = await workflow.regenerate(session, generator)
            except Exception:
                LOGGER.exception("Job application regeneration failed")
                await query.message.reply_text(
                    "I could not regenerate the application. The draft is unchanged."
                )
                return JobApplicationState.WAITING_FOR_ACTION
            await query.edit_message_reply_markup(reply_markup=None)
            _store_session(context, regenerated)
            await _show_preview(query.message, regenerated)
            return JobApplicationState.WAITING_FOR_ACTION
        if query.data == JOB_EDIT:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                "What would you like to edit?",
                reply_markup=job_edit_menu_keyboard(),
            )
            return JobApplicationState.EDIT_MENU
        if query.data == JOB_CANCEL:
            workflow.cancel(session)
            context.user_data.pop(WORKFLOW_KEY, None)
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                "❌ Job application cancelled.\n\nNothing was sent."
            )
            return ConversationHandler.END
        await query.message.reply_text("That action is not valid.")
        return JobApplicationState.WAITING_FOR_ACTION

    async def handle_edit_choice(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        query = update.callback_query
        if query is None:
            return await _show_stale(update.effective_message)
        await query.answer()
        session = _active_session(context)
        if query.message is None or session is None:
            return await _show_stale(query.message)
        if query.data == JOB_BACK_TO_PREVIEW:
            await query.edit_message_reply_markup(reply_markup=None)
            await _show_preview(query.message, session)
            return JobApplicationState.WAITING_FOR_ACTION
        choices = {
            JOB_EDIT_RECIPIENT: (
                "Enter the new company email address:",
                JobApplicationState.EDIT_RECIPIENT,
            ),
            JOB_EDIT_COMPANY: (
                "Enter the new company name:",
                JobApplicationState.EDIT_COMPANY,
            ),
            JOB_EDIT_ROLE: ("Enter the new role:", JobApplicationState.EDIT_ROLE),
            JOB_EDIT_DESCRIPTION: (
                "Paste the new job description:",
                JobApplicationState.EDIT_JOB_DESCRIPTION,
            ),
            JOB_EDIT_SUBJECT: (
                "Enter the new subject:",
                JobApplicationState.EDIT_SUBJECT,
            ),
            JOB_EDIT_BODY: (
                "Enter the new application message:",
                JobApplicationState.EDIT_BODY,
            ),
        }
        selection = choices.get(query.data or "")
        if selection is None:
            await query.message.reply_text("That edit option is not valid.")
            return JobApplicationState.EDIT_MENU
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(selection[0])
        return selection[1]

    async def _edit_text(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        operation: Callable[[JobApplicationSession, str], JobApplicationSession],
        retry_state: JobApplicationState,
        metadata: bool = False,
    ) -> int:
        message = update.effective_message
        session = _active_session(context)
        if session is None:
            return await _show_stale(message)
        try:
            updated = operation(session, message.text if message else "")
        except InputValidationError as error:
            if message:
                await message.reply_text(f"{error} Please enter it again.")
            return retry_state
        _store_session(context, updated)
        if message:
            if metadata and updated.draft_mode is DraftMode.AI:
                await message.reply_text(
                    "Application details updated and matching recalculated. "
                    "Use Regenerate if you want the email text rewritten."
                )
            await _show_preview(message, updated)
        return JobApplicationState.WAITING_FOR_ACTION

    async def receive_edited_recipient(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        return await _edit_text(
            update,
            context,
            operation=workflow.edit_recipient,
            retry_state=JobApplicationState.EDIT_RECIPIENT,
        )

    async def receive_edited_company(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        return await _edit_text(
            update,
            context,
            operation=workflow.edit_company,
            retry_state=JobApplicationState.EDIT_COMPANY,
            metadata=True,
        )

    async def receive_edited_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        return await _edit_text(
            update,
            context,
            operation=workflow.edit_role,
            retry_state=JobApplicationState.EDIT_ROLE,
            metadata=True,
        )

    async def receive_edited_job_description(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int:
        return await _edit_text(
            update,
            context,
            operation=workflow.edit_job_description,
            retry_state=JobApplicationState.EDIT_JOB_DESCRIPTION,
            metadata=True,
        )

    async def receive_edited_subject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        return await _edit_text(
            update,
            context,
            operation=workflow.edit_subject,
            retry_state=JobApplicationState.EDIT_SUBJECT,
        )

    async def receive_edited_body(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        return await _edit_text(
            update,
            context,
            operation=workflow.edit_body,
            retry_state=JobApplicationState.EDIT_BODY,
        )

    async def handle_invalid_callback(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> int | None:
        query = update.callback_query
        if query:
            await query.answer()
        if _workflow_data(context) is None:
            return await _show_stale(query.message if query else update.effective_message)
        LOGGER.warning("Invalid callback received for active job application")
        if query and query.message:
            await query.message.reply_text(
                "That action is no longer valid. Use the latest buttons."
            )
        return None

    return JobApplicationCallbacks(
        begin=begin,
        receive_company_email=receive_company_email,
        receive_company_name=receive_company_name,
        receive_role=receive_role,
        receive_job_description=receive_job_description,
        handle_draft_method=handle_draft_method,
        handle_ai_unavailable=handle_ai_unavailable,
        receive_manual_subject=receive_manual_subject,
        receive_manual_body=receive_manual_body,
        handle_tone=handle_tone,
        handle_action=handle_action,
        handle_edit_choice=handle_edit_choice,
        receive_edited_recipient=receive_edited_recipient,
        receive_edited_company=receive_edited_company,
        receive_edited_role=receive_edited_role,
        receive_edited_job_description=receive_edited_job_description,
        receive_edited_subject=receive_edited_subject,
        receive_edited_body=receive_edited_body,
        handle_invalid_callback=handle_invalid_callback,
    )
