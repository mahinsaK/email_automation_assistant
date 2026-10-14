"""Minimal HTTP callback endpoint for Google OAuth redirects."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app.models.gmail_connection import GmailConnectionInfo
from app.services.gmail.oauth_service import GmailOAuthService, GoogleOAuthError
from app.services.gmail.oauth_state import OAuthStateError
from app.services.gmail_connection import GmailConnectionError


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OAuthCallbackResponse:
    status_code: int
    title: str
    message: str
    action_url: str | None = None


ConnectionNotifier = Callable[[GmailConnectionInfo], Awaitable[None]]
ReturnURLResolver = Callable[[], str | None]


class GmailOAuthCallbackHandler:
    """Framework-independent callback use case."""

    def __init__(
        self,
        oauth_service: GmailOAuthService,
        *,
        on_connected: ConnectionNotifier | None = None,
        return_url: ReturnURLResolver | None = None,
    ) -> None:
        self._oauth_service = oauth_service
        self._on_connected = on_connected
        self._return_url = return_url

    async def handle(self, query: dict[str, list[str]]) -> OAuthCallbackResponse:
        state = _first(query, "state")
        code = _first(query, "code")
        provider_error = _first(query, "error")
        if provider_error:
            LOGGER.warning("Google OAuth callback reported authorization failure")
            if state:
                try:
                    self._oauth_service.cancel(state)
                except OAuthStateError:
                    pass
            return OAuthCallbackResponse(
                400,
                "Gmail connection cancelled",
                "Google authorization was not completed. Return to Telegram and try again.",
            )
        if not state or not code:
            return OAuthCallbackResponse(
                400,
                "Invalid Gmail callback",
                "The authorization response is incomplete. Return to Telegram and retry.",
            )
        try:
            connection = await self._oauth_service.complete(state=state, code=code)
        except OAuthStateError:
            return OAuthCallbackResponse(
                400,
                "Invalid or expired request",
                "This connection link is invalid, expired, or already used.",
            )
        except (GoogleOAuthError, GmailConnectionError):
            return OAuthCallbackResponse(
                502,
                "Gmail connection failed",
                "The existing Gmail connection was not changed. Return to Telegram and retry.",
            )
        if self._on_connected is not None:
            try:
                await self._on_connected(connection)
            except Exception:
                # OAuth already succeeded. Telegram notification failure must
                # not roll back or misreport the saved Gmail connection.
                LOGGER.warning("Gmail connection notification could not be delivered")
        return OAuthCallbackResponse(
            200,
            "Gmail connected successfully",
            "Your bot has been notified. You can now return to Telegram.",
            action_url=self._return_url() if self._return_url else None,
        )


class OAuthCallbackServer:
    """Threaded local HTTP adapter scheduled against the bot event loop."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        callback_path: str,
        handler: GmailOAuthCallbackHandler,
    ) -> None:
        self._host = host
        self._port = port
        self._callback_path = callback_path
        self._handler = handler
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        callback_handler = self._handler
        callback_path = self._callback_path

        class RequestHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib API name
                parsed = urlparse(self.path)
                if parsed.path != callback_path:
                    self.send_error(404)
                    return
                future = asyncio.run_coroutine_threadsafe(
                    callback_handler.handle(parse_qs(parsed.query)),
                    loop,
                )
                try:
                    response = future.result(timeout=30)
                except Exception:
                    LOGGER.exception("Gmail OAuth callback handling failed")
                    response = OAuthCallbackResponse(
                        500,
                        "Gmail connection failed",
                        "Return to Telegram and try again.",
                    )
                body = _html_page(
                    response.title,
                    response.message,
                    action_url=response.action_url,
                ).encode("utf-8")
                self.send_response(response.status_code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                LOGGER.info("OAuth callback HTTP request completed")

        self._server = ThreadingHTTPServer((self._host, self._port), RequestHandler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="gmail-oauth-callback",
            daemon=True,
        )
        self._thread.start()
        LOGGER.info("Gmail OAuth callback server started")

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None
        LOGGER.info("Gmail OAuth callback server stopped")


def _first(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    return values[0] if values else None


def _html_page(
    title: str,
    message: str,
    *,
    action_url: str | None = None,
) -> str:
    action = (
        "<p><a class='button' "
        f"href='{escape(action_url, quote=True)}'>Return to Telegram</a></p>"
        if action_url
        else ""
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<style>body{font-family:system-ui,sans-serif;max-width:36rem;"
        "margin:4rem auto;padding:0 1.25rem;line-height:1.5}"
        ".button{display:inline-block;background:#229ed9;color:white;"
        "padding:.75rem 1rem;border-radius:.5rem;text-decoration:none;"
        "font-weight:600}</style>"
        f"<title>{escape(title)}</title></head><body><h1>{escape(title)}</h1>"
        f"<p>{escape(message)}</p>{action}</body></html>"
    )
