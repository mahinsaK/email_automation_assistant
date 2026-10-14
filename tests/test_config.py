"""Tests for environment-based Phase 3 configuration."""

import pytest

from app.config import ConfigurationError, Settings


def test_ai_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-test-token")
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("AI_MODEL", "test-model")
    monkeypatch.setenv("AI_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "test-encryption-key")
    monkeypatch.setenv("DATABASE_PATH", "data/test.db")
    monkeypatch.setenv("CANDIDATE_PROFILE_PATH", "data/test-profile.json")
    monkeypatch.setenv("CV_FILE_PATH", "attachments/test-cv.pdf")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-client-secret")
    monkeypatch.setenv(
        "GOOGLE_OAUTH_REDIRECT_URI",
        "https://example.com/oauth/google/callback",
    )
    monkeypatch.setenv("OAUTH_CALLBACK_HOST", "0.0.0.0")
    monkeypatch.setenv("OAUTH_CALLBACK_PORT", "9000")

    settings = Settings.from_env()

    assert settings.openai_api_key == "openai-test-key"
    assert settings.ai_model == "test-model"
    assert settings.ai_timeout_seconds == 12.5
    assert settings.credential_encryption_key == "test-encryption-key"
    assert settings.database_path == "data/test.db"
    assert settings.candidate_profile_path == "data/test-profile.json"
    assert settings.cv_file_path == "attachments/test-cv.pdf"
    assert settings.google_client_id == "google-client-id"
    assert settings.google_client_secret == "google-client-secret"
    assert settings.google_oauth_redirect_uri == (
        "https://example.com/oauth/google/callback"
    )
    assert settings.oauth_callback_host == "0.0.0.0"
    assert settings.oauth_callback_port == 9000


def test_gmail_scope_configuration_rejects_broad_or_missing_send_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-test-token")
    monkeypatch.setenv(
        "GMAIL_OAUTH_SCOPES",
        "https://www.googleapis.com/auth/gmail.readonly",
    )

    with pytest.raises(ConfigurationError, match="gmail.send"):
        Settings.from_env()

    monkeypatch.setenv(
        "GMAIL_OAUTH_SCOPES",
        "https://www.googleapis.com/auth/gmail.send "
        "https://www.googleapis.com/auth/gmail.readonly",
    )
    with pytest.raises(ConfigurationError, match="may only contain"):
        Settings.from_env()


def test_unknown_ai_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-test-token")
    monkeypatch.setenv("AI_PROVIDER", "unknown-provider")

    with pytest.raises(ConfigurationError, match="AI_PROVIDER"):
        Settings.from_env()
