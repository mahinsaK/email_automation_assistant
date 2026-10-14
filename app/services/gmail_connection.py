"""Encrypted per-user Gmail connection application service."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.models.gmail_connection import (
    GmailConnection,
    GmailConnectionInfo,
    GoogleOAuthGrant,
    ResolvedGmailCredential,
)
from app.repositories.gmail_connection import (
    GmailConnectionRepository,
    GmailConnectionRepositoryError,
)
from app.services.credential_cipher import CredentialCipher, CredentialCipherError


LOGGER = logging.getLogger(__name__)


class GmailConnectionError(RuntimeError):
    """Base safe error for Gmail connection operations."""


class GmailConnectionUnavailableError(GmailConnectionError):
    """Raised when encryption or persistence is unavailable."""


class GmailAuthorizationError(GmailConnectionError):
    """Raised when a stored Google authorization is invalid or revoked."""


class UserGmailConnectionService:
    """Encrypt, persist, resolve, rotate, and remove Gmail credentials."""

    def __init__(
        self,
        *,
        repository: GmailConnectionRepository,
        cipher: CredentialCipher | None,
    ) -> None:
        self._repository = repository
        self._cipher = cipher

    @property
    def credential_storage_available(self) -> bool:
        return self._cipher is not None

    async def save_grant(
        self,
        telegram_user_id: int,
        grant: GoogleOAuthGrant,
    ) -> GmailConnectionInfo:
        """Atomically replace a connection only after OAuth fully succeeds."""

        if self._cipher is None:
            raise GmailConnectionUnavailableError(
                "Secure Gmail credential storage is not configured."
            )
        if not grant.refresh_token or not grant.google_email:
            raise GmailAuthorizationError(
                "Google did not return a reusable Gmail authorization."
            )
        try:
            existing = await self._repository.get_for_user(telegram_user_id)
            now = datetime.now(UTC)
            connection = GmailConnection(
                telegram_user_id=telegram_user_id,
                google_email=grant.google_email,
                encrypted_refresh_token=self._cipher.encrypt(grant.refresh_token),
                scopes=grant.scopes,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            await self._repository.save(connection)
        except (GmailConnectionRepositoryError, CredentialCipherError) as error:
            LOGGER.error("Gmail connection persistence failed")
            raise GmailConnectionUnavailableError(
                "Gmail connection could not be saved."
            ) from error
        LOGGER.info("Gmail connection replaced" if existing else "Gmail connected")
        return self._to_info(connection)

    async def get_status(
        self,
        telegram_user_id: int,
    ) -> GmailConnectionInfo | None:
        try:
            connection = await self._repository.get_for_user(telegram_user_id)
        except GmailConnectionRepositoryError as error:
            LOGGER.error("Gmail connection status lookup failed")
            raise GmailConnectionUnavailableError(
                "Gmail connection status is unavailable."
            ) from error
        return self._to_info(connection) if connection else None

    async def resolve(
        self,
        telegram_user_id: int,
    ) -> ResolvedGmailCredential | None:
        try:
            connection = await self._repository.get_for_user(telegram_user_id)
        except GmailConnectionRepositoryError as error:
            raise GmailConnectionUnavailableError(
                "Gmail connection could not be resolved."
            ) from error
        if connection is None:
            return None
        if self._cipher is None:
            raise GmailConnectionUnavailableError(
                "Secure Gmail credential storage is unavailable."
            )
        try:
            refresh_token = self._cipher.decrypt(
                connection.encrypted_refresh_token
            )
        except CredentialCipherError as error:
            LOGGER.error("Stored Gmail credential decryption failed")
            raise GmailConnectionUnavailableError(
                "Stored Gmail connection cannot be resolved."
            ) from error
        return ResolvedGmailCredential(
            telegram_user_id=connection.telegram_user_id,
            google_email=connection.google_email,
            refresh_token=refresh_token,
            scopes=connection.scopes,
        )

    async def rotate_refresh_token(
        self,
        credential: ResolvedGmailCredential,
        refresh_token: str,
    ) -> None:
        if refresh_token == credential.refresh_token:
            return
        await self.save_grant(
            credential.telegram_user_id,
            GoogleOAuthGrant(
                google_email=credential.google_email,
                refresh_token=refresh_token,
                scopes=credential.scopes,
            ),
        )

    async def remove(self, telegram_user_id: int) -> bool:
        try:
            removed = await self._repository.delete_for_user(telegram_user_id)
        except GmailConnectionRepositoryError as error:
            LOGGER.error("Gmail connection removal failed")
            raise GmailConnectionUnavailableError(
                "Gmail connection could not be removed."
            ) from error
        if removed:
            LOGGER.info("Gmail disconnected")
        return removed

    @staticmethod
    def _to_info(connection: GmailConnection) -> GmailConnectionInfo:
        return GmailConnectionInfo(
            telegram_user_id=connection.telegram_user_id,
            google_email=connection.google_email,
            scopes=connection.scopes,
        )
