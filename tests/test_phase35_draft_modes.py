"""Phase 3.5 tests for manual and optional-AI draft creation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.ext import ConversationHandler

from app.bot.handlers.general_email_handler import build_general_email_callbacks
from app.bot.keyboards import (
    AI_ENTER_MANUAL,
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
    REGENERATE,
    TONE_CALLBACK_PREFIX,
    edit_menu_keyboard,
    preview_actions_keyboard,
)
from app.bot.states import GeneralEmailState
from app.models.email import EmailDraft, SendResult
from app.services.validation import (
    MAX_BODY_LENGTH,
    MAX_SUBJECT_LENGTH,
    InputValidationError,
)
from app.workflows.general_email import (
    DraftMode,
    GeneralEmailWorkflow,
    WorkflowStateError,
)


class RecordingGenerator:
    """Generator double used to prove which draft path invokes generation."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    async def generate(
        self,
        *,
        recipient: str,
        purpose: str,
        context: str,
        tone: str = "Professional",
    ) -> EmailDraft:
        self.calls.append((recipient, purpose, context, tone))
        return EmailDraft(
            recipient=recipient,
            subject=f"AI: {purpose}",
            body=f"{tone}: {context}",
        )


class RecordingSender:
    def __init__(self) -> None:
        self.calls: list[EmailDraft] = []

    async def send(self, draft: EmailDraft) -> SendResult:
        self.calls.append(draft)
        return SendResult(success=True, message_id="phase35-test")


def make_message(text: str = "") -> SimpleNamespace:
    return SimpleNamespace(text=text, reply_text=AsyncMock())


def make_text_update(text: str) -> SimpleNamespace:
    message = make_message(text)
    return SimpleNamespace(callback_query=None, effective_message=message)


def make_callback_update(data: str) -> SimpleNamespace:
    message = make_message()
    query = SimpleNamespace(
        data=data,
        message=message,
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    return SimpleNamespace(callback_query=query, effective_message=message)


def callback_values(markup: object) -> set[str]:
    return {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    }


def test_manual_draft_uses_shared_model_without_calling_generator() -> None:
    generator = RecordingGenerator()
    workflow = GeneralEmailWorkflow(generator, RecordingSender())

    session = workflow.start_manual(
        recipient=" writer@example.com ",
        subject="  My subject  ",
        body="  First paragraph.\n\nSecond paragraph.  ",
    )

    assert session.draft_mode is DraftMode.MANUAL
    assert session.request is None
    assert session.draft.recipient == "writer@example.com"
    assert session.draft.subject == "My subject"
    assert session.draft.body == "First paragraph.\n\nSecond paragraph."
    assert generator.calls == []


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        ("   ", "Valid body"),
        ("x" * (MAX_SUBJECT_LENGTH + 1), "Valid body"),
        ("Valid subject", " \n "),
        ("Valid subject", "x" * (MAX_BODY_LENGTH + 1)),
    ],
)
def test_manual_draft_rejects_invalid_subject_or_body(
    subject: str,
    body: str,
) -> None:
    workflow = GeneralEmailWorkflow(RecordingGenerator(), RecordingSender())

    with pytest.raises(InputValidationError):
        workflow.start_manual(
            recipient="writer@example.com",
            subject=subject,
            body=body,
        )


def test_manual_draft_editing_preserves_other_fields() -> None:
    workflow = GeneralEmailWorkflow(RecordingGenerator(), RecordingSender())
    original = workflow.start_manual(
        recipient="first@example.com",
        subject="Original subject",
        body="Original body",
    )

    recipient_edit = workflow.edit_recipient(original, "second@example.com")
    subject_edit = workflow.edit_subject(original, "Revised subject")
    body_edit = workflow.edit_body(original, "Revised body")

    assert recipient_edit.draft.recipient == "second@example.com"
    assert recipient_edit.draft.subject == "Original subject"
    assert recipient_edit.draft.body == "Original body"
    assert recipient_edit.draft.created_at == original.draft.created_at
    assert subject_edit.draft.recipient == original.draft.recipient
    assert subject_edit.draft.subject == "Revised subject"
    assert subject_edit.draft.body == original.draft.body
    assert body_edit.draft.recipient == original.draft.recipient
    assert body_edit.draft.subject == original.draft.subject
    assert body_edit.draft.body == "Revised body"


def test_manual_draft_cannot_be_regenerated() -> None:
    workflow = GeneralEmailWorkflow(RecordingGenerator(), RecordingSender())
    session = workflow.start_manual(
        recipient="writer@example.com",
        subject="Subject",
        body="Body",
    )

    with pytest.raises(WorkflowStateError):
        asyncio.run(workflow.regenerate(session))


def test_manual_keyboards_hide_ai_only_actions() -> None:
    manual_preview = callback_values(preview_actions_keyboard(DraftMode.MANUAL))
    ai_preview = callback_values(preview_actions_keyboard(DraftMode.AI))
    manual_edits = callback_values(edit_menu_keyboard(DraftMode.MANUAL))
    ai_edits = callback_values(edit_menu_keyboard(DraftMode.AI))

    assert REGENERATE not in manual_preview
    assert manual_preview == {CONFIRM, EDIT, CANCEL}
    assert ai_preview == {CONFIRM, EDIT, REGENERATE, CANCEL}
    assert EDIT_CONTEXT not in manual_edits
    assert manual_edits == {
        EDIT_RECIPIENT,
        EDIT_SUBJECT,
        EDIT_BODY,
        BACK_TO_PREVIEW,
    }
    assert EDIT_CONTEXT in ai_edits


def test_manual_selection_enters_subject_state() -> None:
    callbacks = build_general_email_callbacks(
        GeneralEmailWorkflow(None, RecordingSender())
    )
    context = SimpleNamespace(
        user_data={"general_email": {"recipient": "writer@example.com"}}
    )
    update = make_callback_update(DRAFT_MANUAL)

    state = asyncio.run(callbacks.handle_draft_method(update, context))

    assert state is GeneralEmailState.MANUAL_WAITING_SUBJECT
    assert context.user_data["general_email"]["draft_mode"] is DraftMode.MANUAL
    update.callback_query.answer.assert_awaited_once()


def test_invalid_manual_subject_and_body_remain_in_entry_states() -> None:
    callbacks = build_general_email_callbacks(
        GeneralEmailWorkflow(None, RecordingSender())
    )
    subject_context = SimpleNamespace(
        user_data={"general_email": {"recipient": "writer@example.com"}}
    )
    body_context = SimpleNamespace(
        user_data={
            "general_email": {
                "recipient": "writer@example.com",
                "manual_subject": "Subject",
            }
        }
    )

    subject_state = asyncio.run(
        callbacks.receive_manual_subject(make_text_update("   "), subject_context)
    )
    body_state = asyncio.run(
        callbacks.receive_manual_body(make_text_update("\n "), body_context)
    )

    assert subject_state is GeneralEmailState.MANUAL_WAITING_SUBJECT
    assert body_state is GeneralEmailState.MANUAL_WAITING_BODY


def test_ai_unavailable_offers_manual_fallback() -> None:
    callbacks = build_general_email_callbacks(
        GeneralEmailWorkflow(None, RecordingSender())
    )
    context = SimpleNamespace(
        user_data={"general_email": {"recipient": "writer@example.com"}}
    )
    unavailable_update = make_callback_update(DRAFT_AI)

    unavailable_state = asyncio.run(
        callbacks.handle_draft_method(unavailable_update, context)
    )
    fallback_update = make_callback_update(AI_ENTER_MANUAL)
    fallback_state = asyncio.run(
        callbacks.handle_ai_unavailable(fallback_update, context)
    )

    assert unavailable_state is GeneralEmailState.WAITING_AI_UNAVAILABLE_ACTION
    unavailable_message = unavailable_update.callback_query.message.reply_text.await_args
    assert "AI generation is not configured" in unavailable_message.args[0]
    assert AI_ENTER_MANUAL in callback_values(unavailable_message.kwargs["reply_markup"])
    assert fallback_state is GeneralEmailState.MANUAL_WAITING_SUBJECT
    assert context.user_data["general_email"]["draft_mode"] is DraftMode.MANUAL


def test_ai_available_selection_continues_to_purpose() -> None:
    workflow = GeneralEmailWorkflow(RecordingGenerator(), RecordingSender())
    callbacks = build_general_email_callbacks(workflow)
    context = SimpleNamespace(
        user_data={"general_email": {"recipient": "writer@example.com"}}
    )

    state = asyncio.run(
        callbacks.handle_draft_method(make_callback_update(DRAFT_AI), context)
    )

    assert workflow.ai_available is True
    assert state is GeneralEmailState.WAITING_PURPOSE
    assert context.user_data["general_email"]["draft_mode"] is DraftMode.AI


def test_manual_flow_smoke_sends_exactly_once() -> None:
    generator = RecordingGenerator()
    sender = RecordingSender()
    callbacks = build_general_email_callbacks(GeneralEmailWorkflow(generator, sender))
    context = SimpleNamespace(user_data={})

    recipient_state = asyncio.run(
        callbacks.receive_recipient(make_text_update("manual@example.com"), context)
    )
    method_state = asyncio.run(
        callbacks.handle_draft_method(make_callback_update(DRAFT_MANUAL), context)
    )
    subject_state = asyncio.run(
        callbacks.receive_manual_subject(make_text_update("Manual subject"), context)
    )
    preview_state = asyncio.run(
        callbacks.receive_manual_body(
            make_text_update("First line.\n\nSecond line."),
            context,
        )
    )
    confirm_state = asyncio.run(
        callbacks.handle_action(make_callback_update(CONFIRM), context)
    )

    assert recipient_state is GeneralEmailState.WAITING_DRAFT_METHOD
    assert method_state is GeneralEmailState.MANUAL_WAITING_SUBJECT
    assert subject_state is GeneralEmailState.MANUAL_WAITING_BODY
    assert preview_state is GeneralEmailState.WAITING_FOR_ACTION
    assert confirm_state == ConversationHandler.END
    assert generator.calls == []
    assert len(sender.calls) == 1
    assert sender.calls[0].subject == "Manual subject"


def test_fake_ai_flow_smoke_sends_exactly_once() -> None:
    generator = RecordingGenerator()
    sender = RecordingSender()
    callbacks = build_general_email_callbacks(GeneralEmailWorkflow(generator, sender))
    context = SimpleNamespace(user_data={})

    asyncio.run(callbacks.receive_recipient(make_text_update("ai@example.com"), context))
    method_state = asyncio.run(
        callbacks.handle_draft_method(make_callback_update(DRAFT_AI), context)
    )
    purpose_state = asyncio.run(
        callbacks.receive_purpose(make_text_update("Project update"), context)
    )
    context_state = asyncio.run(
        callbacks.receive_context(make_text_update("Share the current status."), context)
    )
    preview_state = asyncio.run(
        callbacks.handle_tone(
            make_callback_update(f"{TONE_CALLBACK_PREFIX}professional"),
            context,
        )
    )
    confirm_state = asyncio.run(
        callbacks.handle_action(make_callback_update(CONFIRM), context)
    )

    assert method_state is GeneralEmailState.WAITING_PURPOSE
    assert purpose_state is GeneralEmailState.WAITING_CONTEXT
    assert context_state is GeneralEmailState.WAITING_TONE
    assert preview_state is GeneralEmailState.WAITING_FOR_ACTION
    assert confirm_state == ConversationHandler.END
    assert len(generator.calls) == 1
    assert len(sender.calls) == 1
