"""Email delivery interface and the non-delivering Phase 2 implementation."""

from __future__ import annotations

import logging
from typing import Protocol

from app.models.email import EmailDraft, SendResult


LOGGER = logging.getLogger(__name__)


class EmailSender(Protocol):
    """Port implemented by mock and future real email delivery providers."""

    async def send(self, draft: EmailDraft) -> SendResult:
        """Attempt delivery and return a provider-independent result."""
        ...


class MockEmailSender:
    """Simulate delivery without contacting any external system.

    ``failure_message`` makes the sender return a controlled failure, which lets
    tests and development exercise retry behavior without Gmail.
    """

    def __init__(self, failure_message: str | None = None) -> None:
        self._failure_message = failure_message
        self._requests: list[EmailDraft] = []

    @property
    def requests(self) -> tuple[EmailDraft, ...]:
        """Drafts submitted to this sender, exposed read-only for verification."""

        return tuple(self._requests)

    async def send(self, draft: EmailDraft) -> SendResult:
        LOGGER.info("Mock email send requested")
        self._requests.append(draft)

        if self._failure_message:
            LOGGER.error("Mock email sender failed")
            return SendResult(success=False, error=self._failure_message)

        message_id = f"mock-{len(self._requests)}"
        LOGGER.info("Mock email send completed")
        return SendResult(success=True, message_id=message_id)
