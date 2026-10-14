"""Credential encryption boundary and Fernet implementation."""

from __future__ import annotations

from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken


class CredentialCipherError(RuntimeError):
    """Raised when credential encryption or decryption cannot be completed."""


class CredentialCipher(Protocol):
    """Authenticated symmetric encryption boundary for credentials at rest."""

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a credential for persistence."""
        ...

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a credential for short-lived provider construction."""
        ...


class FernetCredentialCipher:
    """Encrypt credentials using authenticated Fernet tokens."""

    def __init__(self, encryption_key: str) -> None:
        try:
            self._fernet = Fernet(encryption_key.encode("ascii"))
        except (UnicodeEncodeError, ValueError) as error:
            raise CredentialCipherError(
                "CREDENTIAL_ENCRYPTION_KEY is not a valid Fernet key."
            ) from error

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            raise CredentialCipherError("Credential cannot be empty.")
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as error:
            raise CredentialCipherError(
                "Stored credential could not be decrypted."
            ) from error
