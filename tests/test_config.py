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

    settings = Settings.from_env()

    assert settings.openai_api_key == "openai-test-key"
    assert settings.ai_model == "test-model"
    assert settings.ai_timeout_seconds == 12.5
    assert settings.credential_encryption_key == "test-encryption-key"
    assert settings.database_path == "data/test.db"


def test_unknown_ai_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-test-token")
    monkeypatch.setenv("AI_PROVIDER", "unknown-provider")

    with pytest.raises(ConfigurationError, match="AI_PROVIDER"):
        Settings.from_env()
