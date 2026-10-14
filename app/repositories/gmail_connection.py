"""Repository boundary and SQLite adapter for Gmail OAuth connections."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol, TypeVar

from app.models.gmail_connection import GmailConnection


class GmailConnectionRepositoryError(RuntimeError):
    """Raised when Gmail connection persistence is unavailable."""


class GmailConnectionRepository(Protocol):
    """Persistence port scoped by authenticated Telegram user ID."""

    async def initialize(self) -> None: ...

    async def get_for_user(
        self,
        telegram_user_id: int,
    ) -> GmailConnection | None: ...

    async def save(self, connection: GmailConnection) -> None: ...

    async def delete_for_user(self, telegram_user_id: int) -> bool: ...


T = TypeVar("T")


class SQLiteGmailConnectionRepository:
    """Small async-safe SQLite Gmail connection adapter."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    async def initialize(self) -> None:
        await self._run(self._initialize_sync)

    async def get_for_user(
        self,
        telegram_user_id: int,
    ) -> GmailConnection | None:
        return await self._run(self._get_for_user_sync, telegram_user_id)

    async def save(self, connection: GmailConnection) -> None:
        await self._run(self._save_sync, connection)

    async def delete_for_user(self, telegram_user_id: int) -> bool:
        return await self._run(self._delete_for_user_sync, telegram_user_id)

    async def _run(self, operation: Callable[..., T], *args: object) -> T:
        try:
            return await asyncio.to_thread(operation, *args)
        except (OSError, sqlite3.Error, TypeError, ValueError) as error:
            raise GmailConnectionRepositoryError(
                "Gmail connection storage is unavailable."
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
                CREATE TABLE IF NOT EXISTS gmail_connections (
                    telegram_user_id INTEGER PRIMARY KEY,
                    google_email TEXT NOT NULL,
                    encrypted_refresh_token TEXT NOT NULL,
                    scopes TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _get_for_user_sync(
        self,
        telegram_user_id: int,
    ) -> GmailConnection | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT telegram_user_id, google_email, encrypted_refresh_token,
                       scopes, created_at, updated_at
                FROM gmail_connections
                WHERE telegram_user_id = ?
                """,
                (telegram_user_id,),
            ).fetchone()
        if row is None:
            return None
        scopes = json.loads(str(row["scopes"]))
        if not isinstance(scopes, list) or any(
            not isinstance(scope, str) for scope in scopes
        ):
            raise ValueError("Stored Gmail scopes are invalid.")
        return GmailConnection(
            telegram_user_id=int(row["telegram_user_id"]),
            google_email=str(row["google_email"]),
            encrypted_refresh_token=str(row["encrypted_refresh_token"]),
            scopes=tuple(scopes),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _save_sync(self, connection: GmailConnection) -> None:
        with self._connect() as database:
            database.execute(
                """
                INSERT INTO gmail_connections (
                    telegram_user_id,
                    google_email,
                    encrypted_refresh_token,
                    scopes,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    google_email = excluded.google_email,
                    encrypted_refresh_token = excluded.encrypted_refresh_token,
                    scopes = excluded.scopes,
                    updated_at = excluded.updated_at
                """,
                (
                    connection.telegram_user_id,
                    connection.google_email,
                    connection.encrypted_refresh_token,
                    json.dumps(connection.scopes),
                    connection.created_at.isoformat(),
                    connection.updated_at.isoformat(),
                ),
            )

    def _delete_for_user_sync(self, telegram_user_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM gmail_connections WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            return cursor.rowcount > 0
