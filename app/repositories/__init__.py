"""Persistence adapters and repository interfaces."""

from app.repositories.ai_configuration import (
    AIConfigurationRepository,
    AIConfigurationRepositoryError,
    SQLiteAIConfigurationRepository,
)
from app.repositories.gmail_connection import (
    GmailConnectionRepository,
    GmailConnectionRepositoryError,
    SQLiteGmailConnectionRepository,
)

__all__ = [
    "AIConfigurationRepository",
    "AIConfigurationRepositoryError",
    "GmailConnectionRepository",
    "GmailConnectionRepositoryError",
    "SQLiteAIConfigurationRepository",
    "SQLiteGmailConnectionRepository",
]
