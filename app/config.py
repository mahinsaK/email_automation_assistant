"""Environment-based application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv


DEFAULT_AI_MODEL = "gpt-4o-mini"
DEFAULT_DATABASE_PATH = "data/email_assistant.db"
DEFAULT_CANDIDATE_PROFILE_PATH = "data/candidate_profile.json"
DEFAULT_CV_FILE_PATH = "attachments/CV.pdf"
SUPPORTED_AI_PROVIDERS = {"openai", "deterministic"}
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GOOGLE_EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
DEFAULT_GMAIL_OAUTH_SCOPES = ("openid", GOOGLE_EMAIL_SCOPE, GMAIL_SEND_SCOPE)
ALLOWED_GMAIL_OAUTH_SCOPES = frozenset(DEFAULT_GMAIL_OAUTH_SCOPES)


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings needed to start the Telegram adapter."""

    telegram_bot_token: str
    allowed_telegram_user_id: int | None = None
    log_level: str = "INFO"
    ai_provider: str = "openai"
    openai_api_key: str | None = None
    ai_model: str = DEFAULT_AI_MODEL
    ai_timeout_seconds: float = 30.0
    credential_encryption_key: str | None = None
    database_path: str = DEFAULT_DATABASE_PATH
    candidate_profile_path: str = DEFAULT_CANDIDATE_PROFILE_PATH
    cv_file_path: str = DEFAULT_CV_FILE_PATH
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_oauth_redirect_uri: str = (
        "http://localhost:8000/oauth/google/callback"
    )
    gmail_oauth_scopes: tuple[str, ...] = DEFAULT_GMAIL_OAUTH_SCOPES
    oauth_callback_host: str = "127.0.0.1"
    oauth_callback_port: int = 8000
    oauth_state_ttl_seconds: int = 600

    @property
    def ai_enabled(self) -> bool:
        """Whether a real supported AI provider is fully configured."""

        return self.ai_provider == "openai" and bool(self.openai_api_key)

    @property
    def gmail_oauth_enabled(self) -> bool:
        """Whether real Gmail connection and delivery can be offered."""

        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.google_oauth_redirect_uri
            and self.credential_encryption_key
        )

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables and an optional local .env file."""

        load_dotenv()
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise ConfigurationError(
                "TELEGRAM_BOT_TOKEN is missing. Copy .env.example to .env and add it."
            )

        allowed_id_value = os.getenv("ALLOWED_TELEGRAM_USER_ID", "").strip()
        allowed_id: int | None = None
        if allowed_id_value:
            try:
                allowed_id = int(allowed_id_value)
            except ValueError as error:
                raise ConfigurationError(
                    "ALLOWED_TELEGRAM_USER_ID must be an integer."
                ) from error

        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
        ai_provider = os.getenv("AI_PROVIDER", "openai").strip().lower() or "openai"
        if ai_provider not in SUPPORTED_AI_PROVIDERS:
            choices = ", ".join(sorted(SUPPORTED_AI_PROVIDERS))
            raise ConfigurationError(f"AI_PROVIDER must be one of: {choices}.")

        openai_api_key = os.getenv("OPENAI_API_KEY", "").strip() or None
        ai_model = os.getenv("AI_MODEL", DEFAULT_AI_MODEL).strip() or DEFAULT_AI_MODEL
        credential_encryption_key = (
            os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip() or None
        )
        database_path = (
            os.getenv("DATABASE_PATH", DEFAULT_DATABASE_PATH).strip()
            or DEFAULT_DATABASE_PATH
        )
        candidate_profile_path = (
            os.getenv("CANDIDATE_PROFILE_PATH", DEFAULT_CANDIDATE_PROFILE_PATH).strip()
            or DEFAULT_CANDIDATE_PROFILE_PATH
        )
        cv_file_path = (
            os.getenv("CV_FILE_PATH", DEFAULT_CV_FILE_PATH).strip()
            or DEFAULT_CV_FILE_PATH
        )
        google_client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip() or None
        google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip() or None
        google_oauth_redirect_uri = (
            os.getenv(
                "GOOGLE_OAUTH_REDIRECT_URI",
                "http://localhost:8000/oauth/google/callback",
            ).strip()
            or "http://localhost:8000/oauth/google/callback"
        )
        redirect = urlparse(google_oauth_redirect_uri)
        if redirect.scheme not in {"http", "https"} or not redirect.netloc:
            raise ConfigurationError(
                "GOOGLE_OAUTH_REDIRECT_URI must be an absolute HTTP(S) URL."
            )
        scopes_value = os.getenv("GMAIL_OAUTH_SCOPES", "").replace(",", " ")
        gmail_oauth_scopes = tuple(scopes_value.split()) or DEFAULT_GMAIL_OAUTH_SCOPES
        if GMAIL_SEND_SCOPE not in gmail_oauth_scopes:
            raise ConfigurationError("GMAIL_OAUTH_SCOPES must include gmail.send.")
        if not set(gmail_oauth_scopes).issubset(ALLOWED_GMAIL_OAUTH_SCOPES):
            raise ConfigurationError(
                "GMAIL_OAUTH_SCOPES may only contain openid, userinfo.email, "
                "and gmail.send."
            )
        oauth_callback_host = (
            os.getenv("OAUTH_CALLBACK_HOST", "127.0.0.1").strip() or "127.0.0.1"
        )
        try:
            oauth_callback_port = int(
                os.getenv("OAUTH_CALLBACK_PORT", "8000").strip()
            )
            oauth_state_ttl_seconds = int(
                os.getenv("OAUTH_STATE_TTL_SECONDS", "600").strip()
            )
        except ValueError as error:
            raise ConfigurationError(
                "OAuth callback port and state TTL must be integers."
            ) from error
        if not 1 <= oauth_callback_port <= 65535:
            raise ConfigurationError(
                "OAUTH_CALLBACK_PORT must be between 1 and 65535."
            )
        if not 60 <= oauth_state_ttl_seconds <= 3600:
            raise ConfigurationError(
                "OAUTH_STATE_TTL_SECONDS must be between 60 and 3600."
            )
        timeout_value = os.getenv("AI_TIMEOUT_SECONDS", "30").strip()
        try:
            ai_timeout_seconds = float(timeout_value)
        except ValueError as error:
            raise ConfigurationError("AI_TIMEOUT_SECONDS must be a number.") from error
        if not 1 <= ai_timeout_seconds <= 120:
            raise ConfigurationError(
                "AI_TIMEOUT_SECONDS must be between 1 and 120 seconds."
            )

        return cls(
            telegram_bot_token=token,
            allowed_telegram_user_id=allowed_id,
            log_level=log_level,
            ai_provider=ai_provider,
            openai_api_key=openai_api_key,
            ai_model=ai_model,
            ai_timeout_seconds=ai_timeout_seconds,
            credential_encryption_key=credential_encryption_key,
            database_path=database_path,
            candidate_profile_path=candidate_profile_path,
            cv_file_path=cv_file_path,
            google_client_id=google_client_id,
            google_client_secret=google_client_secret,
            google_oauth_redirect_uri=google_oauth_redirect_uri,
            gmail_oauth_scopes=gmail_oauth_scopes,
            oauth_callback_host=oauth_callback_host,
            oauth_callback_port=oauth_callback_port,
            oauth_state_ttl_seconds=oauth_state_ttl_seconds,
        )

