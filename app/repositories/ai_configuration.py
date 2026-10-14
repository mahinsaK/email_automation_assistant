"""Repository boundary and SQLite adapter for encrypted AI credentials."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypeVar

from app.models.ai_configuration import AIProviderType, StoredAIConfiguration


class AIConfigurationRepositoryError(RuntimeError):
    """Raised when encrypted configuration persistence is unavailable."""


class AIConfigurationRepository(Protocol):
    """Persistence port scoped by authenticated Telegram user ID."""

    async def initialize(self) -> None:
        """Create required storage structures when absent."""
        ...

    async def get_for_user(
        self,
        telegram_user_id: int,
    ) -> StoredAIConfiguration | None:
        """Return only the requested user's configuration."""
        ...

    async def save(self, configuration: StoredAIConfiguration) -> None:
        """Insert or atomically replace one user's configuration."""
        ...

    async def delete_for_user(self, telegram_user_id: int) -> bool:
        """Delete only the requested user's configuration."""
        ...


T = TypeVar("T")


class SQLiteAIConfigurationRepository:
    """Small async-safe SQLite adapter using short-lived worker-thread calls."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    async def initialize(self) -> None:
        await self._run(self._initialize_sync)

    async def get_for_user(
        self,
        telegram_user_id: int,
    ) -> StoredAIConfiguration | None:
        return await self._run(self._get_for_user_sync, telegram_user_id)

    async def save(self, configuration: StoredAIConfiguration) -> None:
        await self._run(self._save_sync, configuration)

    async def delete_for_user(self, telegram_user_id: int) -> bool:
        return await self._run(self._delete_for_user_sync, telegram_user_id)

    async def _run(self, operation: Callable[..., T], *args: object) -> T:
        try:
            return await asyncio.to_thread(operation, *args)
        except (OSError, sqlite3.Error, ValueError) as error:
            raise AIConfigurationRepositoryError(
                "AI configuration storage is unavailable."
            ) from error

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_sync(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_ai_configurations (
                    telegram_user_id INTEGER PRIMARY KEY,
                    provider TEXT NOT NULL,
                    encrypted_api_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _get_for_user_sync(
        self,
        telegram_user_id: int,
    ) -> StoredAIConfiguration | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT telegram_user_id, provider, encrypted_api_key,
                       created_at, updated_at
                FROM user_ai_configurations
                WHERE telegram_user_id = ?
                """,
                (telegram_user_id,),
            ).fetchone()
        if row is None:
            return None
        return StoredAIConfiguration(
            telegram_user_id=int(row["telegram_user_id"]),
            provider=AIProviderType(str(row["provider"])),
            encrypted_api_key=str(row["encrypted_api_key"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _save_sync(self, configuration: StoredAIConfiguration) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_ai_configurations (
                    telegram_user_id,
                    provider,
                    encrypted_api_key,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    provider = excluded.provider,
                    encrypted_api_key = excluded.encrypted_api_key,
                    updated_at = excluded.updated_at
                """,
                (
                    configuration.telegram_user_id,
                    configuration.provider.value,
                    configuration.encrypted_api_key,
                    configuration.created_at.isoformat(),
                    configuration.updated_at.isoformat(),
                ),
            )

    def _delete_for_user_sync(self, telegram_user_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM user_ai_configurations WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            return cursor.rowcount > 0
