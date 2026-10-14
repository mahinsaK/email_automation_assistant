"""Resolve a Gmail email sender for the authenticated Telegram user."""

from __future__ import annotations

from typing import Protocol

from app.services.email_sender import EmailSender
from app.services.gmail.client import GmailClientFactory
from app.services.gmail.mime_builder import GmailMIMEBuilder
from app.services.gmail.sender import GmailEmailSender
from app.services.gmail_connection import UserGmailConnectionService


class UserEmailSenderResolver(Protocol):
    async def resolve(self, telegram_user_id: int) -> EmailSender | None: ...


class UnavailableUserEmailSenderResolver:
    """Explicitly disable delivery while preserving connection-first UX."""

    async def resolve(self, telegram_user_id: int) -> None:
        return None


class ConfiguredUserEmailSenderResolver:
    """Build an isolated Gmail sender from one user's encrypted connection."""

    def __init__(
        self,
        *,
        connection_service: UserGmailConnectionService,
        client_factory: GmailClientFactory,
        mime_builder: GmailMIMEBuilder,
    ) -> None:
        self._connection_service = connection_service
        self._client_factory = client_factory
        self._mime_builder = mime_builder

    async def resolve(self, telegram_user_id: int) -> EmailSender | None:
        credential = await self._connection_service.resolve(telegram_user_id)
        if credential is None:
            return None
        session = await self._client_factory.create(credential)
        if session.refreshed_token:
            await self._connection_service.rotate_refresh_token(
                credential,
                session.refreshed_token,
            )
        return GmailEmailSender(
            client=session.client,
            mime_builder=self._mime_builder,
            sender_email=credential.google_email,
        )
