"""Network-free tests for Gmail OAuth state, encryption, and persistence."""

import asyncio
import base64
import hashlib
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet

from app.models.gmail_connection import GoogleOAuthGrant
from app.repositories.gmail_connection import SQLiteGmailConnectionRepository
from app.services.credential_cipher import FernetCredentialCipher
from app.services.gmail.callback_server import GmailOAuthCallbackHandler
from app.services.gmail.oauth_service import (
    GMAIL_SEND_SCOPE,
    GmailOAuthService,
    GoogleOAuthError,
    GoogleOAuthLibraryGateway,
)
from app.services.gmail.oauth_state import InMemoryOAuthStateStore, OAuthStateError
from app.services.gmail_connection import UserGmailConnectionService


class FakeOAuthGateway:
    def __init__(self, grant: GoogleOAuthGrant) -> None:
        self.grant = grant
        self.fail = False
        self.codes: list[str] = []
        self.authorization_verifiers: dict[str, str] = {}
        self.exchange_verifiers: list[str] = []

    def authorization_url(self, *, state: str, code_verifier: str) -> str:
        self.authorization_verifiers[state] = code_verifier
        return f"https://accounts.example/authorize?state={state}"

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
    ) -> GoogleOAuthGrant:
        self.codes.append(code)
        self.exchange_verifiers.append(code_verifier)
        if self.fail:
            raise GoogleOAuthError("exchange failed")
        return self.grant


def make_service(
    tmp_path: Path,
) -> tuple[UserGmailConnectionService, SQLiteGmailConnectionRepository]:
    repository = SQLiteGmailConnectionRepository(tmp_path / "assistant.db")
    asyncio.run(repository.initialize())
    service = UserGmailConnectionService(
        repository=repository,
        cipher=FernetCredentialCipher(Fernet.generate_key().decode("ascii")),
    )
    return service, repository


def test_google_authorization_url_contains_redirect_scope_and_state() -> None:
    gateway = GoogleOAuthLibraryGateway(
        client_id="client-id.apps.googleusercontent.com",
        client_secret="client-secret",
        redirect_uri="http://localhost:8000/oauth/google/callback",
        scopes=(
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            GMAIL_SEND_SCOPE,
        ),
    )

    code_verifier = "pkce-verifier-" + ("a" * 50)
    url = gateway.authorization_url(
        state="opaque-state",
        code_verifier=code_verifier,
    )
    query = parse_qs(urlparse(url).query)
    expected_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")

    assert query["redirect_uri"] == [
        "http://localhost:8000/oauth/google/callback"
    ]
    assert query["state"] == ["opaque-state"]
    assert GMAIL_SEND_SCOPE in query["scope"][0].split()
    assert query["access_type"] == ["offline"]
    assert query["code_challenge"] == [expected_challenge]
    assert query["code_challenge_method"] == ["S256"]
    assert gateway._new_flow(code_verifier=code_verifier).code_verifier == code_verifier


def test_oauth_success_binds_user_and_encrypts_refresh_token(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    service, repository = make_service(tmp_path)
    refresh_token = "google-refresh-secret"
    gateway = FakeOAuthGateway(
        GoogleOAuthGrant(
            google_email="user@gmail.com",
            refresh_token=refresh_token,
            scopes=(GMAIL_SEND_SCOPE,),
        )
    )
    oauth = GmailOAuthService(
        gateway=gateway,
        state_store=InMemoryOAuthStateStore(),
        connection_service=service,
    )
    state = parse_qs(urlparse(oauth.begin(101)).query)["state"][0]
    assert "101" not in state

    result = asyncio.run(oauth.complete(state=state, code="auth-code"))
    stored = asyncio.run(repository.get_for_user(101))
    database_bytes = (tmp_path / "assistant.db").read_bytes()

    assert result.google_email == "user@gmail.com"
    assert gateway.exchange_verifiers == [gateway.authorization_verifiers[state]]
    assert stored is not None
    assert stored.telegram_user_id == 101
    assert stored.encrypted_refresh_token != refresh_token
    assert refresh_token.encode() not in database_bytes
    assert refresh_token not in caplog.text
    assert "auth-code" not in caplog.text
    resolved = asyncio.run(service.resolve(101))
    assert resolved is not None
    assert resolved.refresh_token == refresh_token


def test_invalid_expired_and_replayed_states_fail_safely(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service, _ = make_service(tmp_path)
    gateway = FakeOAuthGateway(
        GoogleOAuthGrant("user@gmail.com", "refresh", (GMAIL_SEND_SCOPE,))
    )
    now = [100.0]
    monkeypatch.setattr(
        "app.services.gmail.oauth_state.time.monotonic",
        lambda: now[0],
    )
    store = InMemoryOAuthStateStore(ttl_seconds=60)
    oauth = GmailOAuthService(
        gateway=gateway,
        state_store=store,
        connection_service=service,
    )

    with pytest.raises(OAuthStateError):
        asyncio.run(oauth.complete(state="forged", code="code"))

    valid_state = parse_qs(urlparse(oauth.begin(101)).query)["state"][0]
    asyncio.run(oauth.complete(state=valid_state, code="first"))
    with pytest.raises(OAuthStateError):
        asyncio.run(oauth.complete(state=valid_state, code="replay"))

    expired_state = parse_qs(urlparse(oauth.begin(202)).query)["state"][0]
    now[0] += 61
    with pytest.raises(OAuthStateError, match="expired"):
        asyncio.run(oauth.complete(state=expired_state, code="late"))


def test_failed_reconnect_preserves_existing_connection(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)
    asyncio.run(
        service.save_grant(
            101,
            GoogleOAuthGrant(
                "old@gmail.com",
                "old-refresh-token",
                (GMAIL_SEND_SCOPE,),
            ),
        )
    )
    gateway = FakeOAuthGateway(
        GoogleOAuthGrant("new@gmail.com", "new-token", (GMAIL_SEND_SCOPE,))
    )
    gateway.fail = True
    oauth = GmailOAuthService(
        gateway=gateway,
        state_store=InMemoryOAuthStateStore(),
        connection_service=service,
    )
    state = parse_qs(urlparse(oauth.begin(101)).query)["state"][0]

    with pytest.raises(GoogleOAuthError):
        asyncio.run(oauth.complete(state=state, code="bad-code"))

    existing = asyncio.run(service.resolve(101))
    assert existing is not None
    assert existing.google_email == "old@gmail.com"
    assert existing.refresh_token == "old-refresh-token"


def test_multi_user_lookup_and_delete_are_isolated(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)
    for user_id, email, token in (
        (101, "a@gmail.com", "token-a"),
        (202, "b@gmail.com", "token-b"),
    ):
        asyncio.run(
            service.save_grant(
                user_id,
                GoogleOAuthGrant(email, token, (GMAIL_SEND_SCOPE,)),
            )
        )

    assert asyncio.run(service.resolve(101)).refresh_token == "token-a"  # type: ignore[union-attr]
    assert asyncio.run(service.remove(101)) is True
    assert asyncio.run(service.resolve(101)) is None
    assert asyncio.run(service.resolve(202)).refresh_token == "token-b"  # type: ignore[union-attr]


def test_callback_handler_returns_safe_browser_pages(tmp_path: Path) -> None:
    service, _ = make_service(tmp_path)
    gateway = FakeOAuthGateway(
        GoogleOAuthGrant("user@gmail.com", "refresh", (GMAIL_SEND_SCOPE,))
    )
    oauth = GmailOAuthService(
        gateway=gateway,
        state_store=InMemoryOAuthStateStore(),
        connection_service=service,
    )
    handler = GmailOAuthCallbackHandler(oauth)
    state = parse_qs(urlparse(oauth.begin(101)).query)["state"][0]

    success = asyncio.run(handler.handle({"state": [state], "code": ["code"]}))
    forged = asyncio.run(
        handler.handle({"state": ["forged"], "code": ["code"]})
    )

    assert success.status_code == 200
    assert "return to Telegram" in success.message
    assert forged.status_code == 400
    assert "forged" not in forged.message
