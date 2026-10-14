"""Domain values for per-user Gmail OAuth connections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class GmailConnection:
    """Encrypted Gmail authorization persisted for one Telegram user."""

    telegram_user_id: int
    google_email: str
    encrypted_refresh_token: str
    scopes: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class GmailConnectionInfo:
    """Safe connection metadata suitable for status and UI messages."""

    telegram_user_id: int
    google_email: str
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedGmailCredential:
    """Short-lived decrypted credential used only for client construction."""

    telegram_user_id: int
    google_email: str
    refresh_token: str
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoogleOAuthGrant:
    """Validated result returned by an OAuth authorization-code exchange."""

    google_email: str
    refresh_token: str
    scopes: tuple[str, ...]
