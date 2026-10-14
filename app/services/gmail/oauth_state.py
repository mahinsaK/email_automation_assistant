"""One-time in-memory OAuth state with expiry and user binding."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass


class OAuthStateError(RuntimeError):
    """Raised when OAuth state is missing, expired, forged, or already used."""


@dataclass(frozen=True, slots=True)
class PendingOAuthState:
    telegram_user_id: int
    code_verifier: str
    expires_at: float


class InMemoryOAuthStateStore:
    """Store opaque random OAuth state for one application instance."""

    def __init__(self, *, ttl_seconds: int = 600) -> None:
        if ttl_seconds < 60:
            raise ValueError("OAuth state TTL must be at least 60 seconds.")
        self._ttl_seconds = ttl_seconds
        self._states: dict[str, PendingOAuthState] = {}

    def create(self, telegram_user_id: int, *, code_verifier: str) -> str:
        self._discard_expired()
        state = secrets.token_urlsafe(32)
        self._states[state] = PendingOAuthState(
            telegram_user_id=telegram_user_id,
            code_verifier=code_verifier,
            expires_at=time.monotonic() + self._ttl_seconds,
        )
        return state

    def consume(self, state: str) -> PendingOAuthState:
        if not state:
            raise OAuthStateError("OAuth state is missing or invalid.")
        pending = self._states.pop(state, None)
        if pending is None:
            raise OAuthStateError("OAuth state is missing or invalid.")
        if pending.expires_at <= time.monotonic():
            raise OAuthStateError("OAuth state has expired.")
        return pending

    def _discard_expired(self) -> None:
        now = time.monotonic()
        self._states = {
            state: pending
            for state, pending in self._states.items()
            if pending.expires_at > now
        }
