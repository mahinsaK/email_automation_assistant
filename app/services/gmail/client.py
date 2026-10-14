"""Authenticated Gmail API client factory and narrow send adapter."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from app.models.gmail_connection import ResolvedGmailCredential
from app.services.gmail.oauth_service import GOOGLE_TOKEN_ENDPOINT
from app.services.gmail_connection import GmailAuthorizationError


LOGGER = logging.getLogger(__name__)


class GmailClientError(RuntimeError):
    """Raised for a safe, retryable Gmail API delivery failure."""


class GmailClient(Protocol):
    async def send_raw(self, raw_message: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class GmailClientSession:
    client: GmailClient
    refreshed_token: str | None = None


class GmailClientFactory(Protocol):
    async def create(
        self,
        credential: ResolvedGmailCredential,
    ) -> GmailClientSession: ...


class GoogleGmailClient:
    """Narrow asynchronous facade over the blocking discovery client."""

    def __init__(self, service: Any) -> None:
        self._service = service

    async def send_raw(self, raw_message: str) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(self._send_sync, raw_message)
        except Exception as error:
            status = getattr(getattr(error, "resp", None), "status", None)
            if status == 401:
                raise GmailAuthorizationError(
                    "Gmail authorization is invalid or revoked."
                ) from error
            LOGGER.warning("Gmail API send failed: %s", type(error).__name__)
            raise GmailClientError("Gmail could not send the email.") from error
        return result if isinstance(result, dict) else {}

    def _send_sync(self, raw_message: str) -> dict[str, Any]:
        return (
            self._service.users()
            .messages()
            .send(userId="me", body={"raw": raw_message})
            .execute()
        )


class GoogleGmailClientFactory:
    """Refresh short-lived access and build an authenticated Gmail client."""

    def __init__(self, *, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret

    async def create(
        self,
        credential: ResolvedGmailCredential,
    ) -> GmailClientSession:
        try:
            return await asyncio.to_thread(self._create_sync, credential)
        except GmailAuthorizationError:
            raise
        except Exception as error:
            LOGGER.warning("Gmail client creation failed: %s", type(error).__name__)
            raise GmailClientError("Gmail is temporarily unavailable.") from error

    def _create_sync(
        self,
        credential: ResolvedGmailCredential,
    ) -> GmailClientSession:
        try:
            from google.auth.exceptions import RefreshError
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_httplib2 import AuthorizedHttp
            from googleapiclient.discovery import build
            import httplib2
        except ImportError as error:
            raise GmailClientError("Google Gmail dependencies are unavailable.") from error

        credentials = Credentials(
            token=None,
            refresh_token=credential.refresh_token,
            token_uri=GOOGLE_TOKEN_ENDPOINT,
            client_id=self._client_id,
            client_secret=self._client_secret,
            scopes=list(credential.scopes),
        )
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            raise GmailAuthorizationError(
                "Gmail authorization is invalid or revoked."
            ) from error
        authorized_http = AuthorizedHttp(
            credentials,
            http=httplib2.Http(timeout=30),
        )
        service = build(
            "gmail",
            "v1",
            http=authorized_http,
            cache_discovery=False,
        )
        refreshed_token = credentials.refresh_token
        return GmailClientSession(
            client=GoogleGmailClient(service),
            refreshed_token=refreshed_token,
        )
