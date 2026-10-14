"""Telegram adapter tests for Gmail connection and send recovery UX."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cryptography.fernet import Fernet

from app.bot.handlers.general_email_handler import build_general_email_callbacks
from app.bot.handlers.gmail_connection_handler import build_gmail_connection_callbacks
from app.bot.keyboards import (
    CONFIRM,
    EMAIL_GMAIL_BACK,
    GMAIL_DISCONNECT_CONFIRM,
)
from app.bot.states import GeneralEmailState
from app.models.email import EmailDraft, SendResult
from app.models.gmail_connection import GoogleOAuthGrant
from app.repositories.gmail_connection import SQLiteGmailConnectionRepository
from app.services.credential_cipher import FernetCredentialCipher
from app.services.gmail.oauth_service import GMAIL_SEND_SCOPE
from app.services.gmail_connection import GmailAuthorizationError, UserGmailConnectionService
from app.workflows.general_email import GeneralEmailWorkflow


class FakeOAuthService:
    def begin(self, telegram_user_id: int) -> str:
        return f"https://accounts.example/connect?state=user-{telegram_user_id}"


class RecordingSender:
    def __init__(self) -> None:
        self.calls: list[EmailDraft] = []

    async def send(self, draft: EmailDraft) -> SendResult:
        self.calls.append(draft)
        return SendResult(success=True, message_id="gmail-message")


class StaticSenderResolver:
    def __init__(self, sender: RecordingSender | None, *, revoked: bool = False) -> None:
        self.sender = sender
        self.revoked = revoked

    async def resolve(self, telegram_user_id: int):
        if self.revoked:
            raise GmailAuthorizationError("revoked")
        return self.sender


def make_message(text: str = "") -> SimpleNamespace:
    return SimpleNamespace(text=text, reply_text=AsyncMock())


def make_text_update(text: str = "", user_id: int = 101) -> SimpleNamespace:
    message = make_message(text)
    return SimpleNamespace(
        callback_query=None,
        effective_message=message,
        effective_user=SimpleNamespace(id=user_id),
    )


def make_callback_update(data: str, user_id: int = 101) -> SimpleNamespace:
    message = make_message()
    query = SimpleNamespace(
        data=data,
        message=message,
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    return SimpleNamespace(
        callback_query=query,
        effective_message=message,
        effective_user=SimpleNamespace(id=user_id),
    )


def reply_texts(message: SimpleNamespace) -> str:
    return " ".join(str(call.args[0]) for call in message.reply_text.await_args_list)


def make_connection_service(tmp_path: Path) -> UserGmailConnectionService:
    repository = SQLiteGmailConnectionRepository(tmp_path / "assistant.db")
    asyncio.run(repository.initialize())
    return UserGmailConnectionService(
        repository=repository,
        cipher=FernetCredentialCipher(Fernet.generate_key().decode("ascii")),
    )


def test_connect_and_status_never_expose_refresh_token(tmp_path: Path) -> None:
    service = make_connection_service(tmp_path)
    callbacks = build_gmail_connection_callbacks(
        service,
        oauth_service=FakeOAuthService(),  # type: ignore[arg-type]
    )
    context = SimpleNamespace(user_data={})
    connect_update = make_text_update("/connect_gmail")

    asyncio.run(callbacks.connect(connect_update, context))

    markup = connect_update.effective_message.reply_text.await_args.kwargs[
        "reply_markup"
    ]
    assert markup.inline_keyboard[0][0].url.startswith("https://accounts.example/")

    refresh_token = "never-display-this-refresh-token"
    asyncio.run(
        service.save_grant(
            101,
            GoogleOAuthGrant(
                "user@gmail.com",
                refresh_token,
                (GMAIL_SEND_SCOPE,),
            ),
        )
    )
    status_update = make_text_update("/gmail_status")
    asyncio.run(callbacks.status(status_update, context))
    status_text = reply_texts(status_update.effective_message)

    assert "user@gmail.com" in status_text
    assert "Connected" in status_text
    assert refresh_token not in status_text

    reconnect_update = make_text_update("/connect_gmail")
    asyncio.run(callbacks.connect(reconnect_update, context))
    reconnect_text = reply_texts(reconnect_update.effective_message)
    assert "already connected" in reconnect_text
    assert refresh_token not in reconnect_text


def test_disconnected_status_and_disconnect_command_are_safe(tmp_path: Path) -> None:
    service = make_connection_service(tmp_path)
    callbacks = build_gmail_connection_callbacks(service, oauth_service=None)
    context = SimpleNamespace(user_data={})
    status_update = make_text_update("/gmail_status")
    disconnect_update = make_text_update("/disconnect_gmail")

    asyncio.run(callbacks.status(status_update, context))
    asyncio.run(callbacks.begin_disconnect(disconnect_update, context))

    assert "Not connected" in reply_texts(status_update.effective_message)
    assert "not connected" in reply_texts(disconnect_update.effective_message)


def test_disconnect_deletes_only_requesting_users_connection(tmp_path: Path) -> None:
    service = make_connection_service(tmp_path)
    callbacks = build_gmail_connection_callbacks(service, oauth_service=None)
    for user_id, email in ((101, "a@gmail.com"), (202, "b@gmail.com")):
        asyncio.run(
            service.save_grant(
                user_id,
                GoogleOAuthGrant(email, f"token-{user_id}", (GMAIL_SEND_SCOPE,)),
            )
        )
    update = make_callback_update(GMAIL_DISCONNECT_CONFIRM, user_id=101)

    asyncio.run(
        callbacks.handle_disconnect_action(update, SimpleNamespace(user_data={}))
    )

    assert asyncio.run(service.get_status(101)) is None
    remaining = asyncio.run(service.get_status(202))
    assert remaining is not None
    assert remaining.google_email == "b@gmail.com"


def test_confirm_without_gmail_keeps_draft_and_offers_connection() -> None:
    default_sender = RecordingSender()
    workflow = GeneralEmailWorkflow(generator=None, sender=default_sender)
    session = workflow.start_manual(
        recipient="receiver@example.com",
        subject="Subject",
        body="Body",
    )
    callbacks = build_general_email_callbacks(
        workflow,
        sender_resolver=StaticSenderResolver(None),  # type: ignore[arg-type]
        gmail_authorization_url=lambda user_id: _url(user_id),
    )
    context = SimpleNamespace(user_data={"general_email": {"session": session}})
    update = make_callback_update(CONFIRM)

    state = asyncio.run(callbacks.handle_action(update, context))

    assert state is GeneralEmailState.WAITING_FOR_ACTION
    assert context.user_data["general_email"]["session"] == session
    assert default_sender.calls == []
    markup = update.effective_message.reply_text.await_args.kwargs["reply_markup"]
    callback_values = {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    }
    assert EMAIL_GMAIL_BACK in callback_values
    assert any(button.url for row in markup.inline_keyboard for button in row)


def test_revoked_gmail_keeps_draft_and_requests_reconnect() -> None:
    workflow = GeneralEmailWorkflow(generator=None, sender=RecordingSender())
    session = workflow.start_manual(
        recipient="receiver@example.com",
        subject="Subject",
        body="Body",
    )
    callbacks = build_general_email_callbacks(
        workflow,
        sender_resolver=StaticSenderResolver(None, revoked=True),  # type: ignore[arg-type]
        gmail_authorization_url=lambda user_id: _url(user_id),
    )
    context = SimpleNamespace(user_data={"general_email": {"session": session}})
    update = make_callback_update(CONFIRM)

    state = asyncio.run(callbacks.handle_action(update, context))

    assert state is GeneralEmailState.WAITING_FOR_ACTION
    assert context.user_data["general_email"]["session"] == session
    assert "no longer valid" in reply_texts(update.effective_message)


async def _url(user_id: int) -> str:
    return f"https://accounts.example/connect?user={user_id}"
