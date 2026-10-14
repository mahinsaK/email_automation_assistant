"""Google OAuth gateway and connection orchestration."""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Protocol

from app.models.gmail_connection import GmailConnectionInfo, GoogleOAuthGrant
from app.services.gmail.oauth_state import InMemoryOAuthStateStore, OAuthStateError
from app.services.gmail_connection import UserGmailConnectionService


LOGGER = logging.getLogger(__name__)
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GOOGLE_EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
OPENID_SCOPE = "openid"


class GoogleOAuthError(RuntimeError):
    """Safe OAuth authorization or token-exchange failure."""


class GoogleOAuthGateway(Protocol):
    def authorization_url(self, *, state: str, code_verifier: str) -> str: ...

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
    ) -> GoogleOAuthGrant: ...


class GoogleOAuthLibraryGateway:
    """Adapter around Google's OAuth client library."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: tuple[str, ...],
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._scopes = scopes

    def authorization_url(self, *, state: str, code_verifier: str) -> str:
        flow = self._new_flow(state=state, code_verifier=code_verifier)
        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return str(authorization_url)

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
    ) -> GoogleOAuthGrant:
        if not code:
            raise GoogleOAuthError("Google authorization code is missing.")
        try:
            return await asyncio.to_thread(
                self._exchange_code_sync,
                code,
                code_verifier,
            )
        except GoogleOAuthError:
            raise
        except Exception as error:
            LOGGER.warning("Google OAuth code exchange failed: %s", type(error).__name__)
            raise GoogleOAuthError("Google authorization could not be completed.") from error

    def _exchange_code_sync(
        self,
        code: str,
        code_verifier: str,
    ) -> GoogleOAuthGrant:
        flow = self._new_flow(code_verifier=code_verifier)
        flow.fetch_token(code=code)
        credentials = flow.credentials
        refresh_token = credentials.refresh_token
        if not refresh_token:
            raise GoogleOAuthError(
                "Google did not return a refresh token. Revoke the prior grant "
                "and reconnect."
            )
        response = flow.oauth2session.get(GOOGLE_USERINFO_ENDPOINT, timeout=15)
        response.raise_for_status()
        user_info = response.json()
        google_email = user_info.get("email") if isinstance(user_info, dict) else None
        if not isinstance(google_email, str) or not google_email:
            raise GoogleOAuthError("Google account email could not be verified.")
        granted_scopes = tuple(
            credentials.granted_scopes or credentials.scopes or self._scopes
        )
        if GMAIL_SEND_SCOPE not in granted_scopes:
            raise GoogleOAuthError("Gmail send permission was not granted.")
        return GoogleOAuthGrant(
            google_email=google_email,
            refresh_token=refresh_token,
            scopes=granted_scopes,
        )

    def _new_flow(
        self,
        *,
        state: str | None = None,
        code_verifier: str,
    ):
        try:
            from google_auth_oauthlib.flow import Flow
        except ImportError as error:
            raise GoogleOAuthError("Google OAuth dependencies are unavailable.") from error
        client_config = {
            "web": {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "auth_uri": GOOGLE_AUTHORIZATION_ENDPOINT,
                "token_uri": GOOGLE_TOKEN_ENDPOINT,
                "redirect_uris": [self._redirect_uri],
            }
        }
        flow = Flow.from_client_config(
            client_config,
            scopes=list(self._scopes),
            state=state,
            code_verifier=code_verifier,
            autogenerate_code_verifier=False,
        )
        flow.redirect_uri = self._redirect_uri
        return flow


class GmailOAuthService:
    """Bind one-time OAuth state to encrypted per-user persistence."""

    def __init__(
        self,
        *,
        gateway: GoogleOAuthGateway,
        state_store: InMemoryOAuthStateStore,
        connection_service: UserGmailConnectionService,
    ) -> None:
        self._gateway = gateway
        self._state_store = state_store
        self._connection_service = connection_service

    def begin(self, telegram_user_id: int) -> str:
        code_verifier = secrets.token_urlsafe(64)
        state = self._state_store.create(
            telegram_user_id,
            code_verifier=code_verifier,
        )
        LOGGER.info("Gmail OAuth connection started")
        return self._gateway.authorization_url(
            state=state,
            code_verifier=code_verifier,
        )

    def cancel(self, state: str) -> None:
        """Consume a denied authorization state so it cannot be replayed."""

        self._state_store.consume(state)

    async def complete(
        self,
        *,
        state: str,
        code: str,
    ) -> GmailConnectionInfo:
        """Consume state before exchange, preventing replay on any outcome."""

        try:
            pending = self._state_store.consume(state)
        except OAuthStateError:
            LOGGER.warning("Invalid or expired Gmail OAuth state received")
            raise
        grant = await self._gateway.exchange_code(
            code=code,
            code_verifier=pending.code_verifier,
        )
        info = await self._connection_service.save_grant(
            pending.telegram_user_id,
            grant,
        )
        LOGGER.info("Gmail OAuth connection completed")
        return info
