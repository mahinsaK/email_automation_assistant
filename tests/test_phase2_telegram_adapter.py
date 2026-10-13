"""Focused adapter tests for Phase 2 Telegram state transitions."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.ext import ConversationHandler

from app.bot.handlers.general_email_handler import build_general_email_callbacks
from app.bot.keyboards import CANCEL, CONFIRM
from app.bot.states import GeneralEmailState
from app.models.email import EmailDraft, SendResult
from app.workflows.general_email import GeneralEmailRequest, GeneralEmailWorkflow


class StaticGenerator:
    async def generate(
        self,
        *,
        recipient: str,
        purpose: str,
        context: str,
    ) -> EmailDraft:
        return EmailDraft(recipient=recipient, subject=purpose, body=context)


class CountingSender:
    def __init__(self) -> None:
        self.calls = 0

    async def send(self, draft: EmailDraft) -> SendResult:
        self.calls += 1
        return SendResult(success=True, message_id="adapter-test")


def make_message(text: str = ""):
    return SimpleNamespace(text=text, reply_text=AsyncMock())


def make_callback_update(data: str, message=None):
    message = message or make_message()
    query = SimpleNamespace(
        data=data,
        message=message,
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    return SimpleNamespace(callback_query=query, effective_message=message)


def make_text_update(text: str):
    message = make_message(text)
    return SimpleNamespace(callback_query=None, effective_message=message)


def make_active_callbacks():
    sender = CountingSender()
    workflow = GeneralEmailWorkflow(StaticGenerator(), sender)
    session = asyncio.run(
        workflow.start(
            GeneralEmailRequest(
                recipient="user@example.com",
                purpose="A subject",
                context="A body",
            )
        )
    )
    callbacks = build_general_email_callbacks(workflow)
    context = SimpleNamespace(user_data={"general_email": {"session": session}})
    return callbacks, sender, context


def test_inline_cancel_clears_state_without_calling_sender() -> None:
    callbacks, sender, context = make_active_callbacks()
    update = make_callback_update(CANCEL)

    state = asyncio.run(callbacks.handle_action(update, context))

    assert state == ConversationHandler.END
    assert "general_email" not in context.user_data
    assert sender.calls == 0
    update.callback_query.answer.assert_awaited_once()


def test_confirmation_calls_sender_once_clears_state_and_ends() -> None:
    callbacks, sender, context = make_active_callbacks()
    update = make_callback_update(CONFIRM)

    state = asyncio.run(callbacks.handle_action(update, context))

    assert state == ConversationHandler.END
    assert "general_email" not in context.user_data
    assert sender.calls == 1
    assert "mock-send completed" in update.callback_query.message.reply_text.await_args.args[0]


def test_invalid_edited_recipient_stays_in_edit_recipient_state() -> None:
    callbacks, _, context = make_active_callbacks()
    original_session = context.user_data["general_email"]["session"]
    update = make_text_update("invalid-address")

    state = asyncio.run(callbacks.receive_edited_recipient(update, context))

    assert state is GeneralEmailState.EDIT_RECIPIENT
    assert context.user_data["general_email"]["session"] is original_session
    update.effective_message.reply_text.assert_awaited_once()


def test_stale_confirmation_is_handled_without_sender_call() -> None:
    callbacks, sender, _ = make_active_callbacks()
    context = SimpleNamespace(user_data={})
    update = make_callback_update(CONFIRM)

    state = asyncio.run(callbacks.handle_action(update, context))

    assert state == ConversationHandler.END
    assert sender.calls == 0
    update.callback_query.answer.assert_awaited_once()
    assert "no longer active" in update.callback_query.message.reply_text.await_args.args[0]
