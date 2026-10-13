"""Tests for the non-delivering Phase 2 email sender."""

import asyncio

from app.models.email import EmailDraft
from app.services.email_sender import MockEmailSender


def test_mock_sender_simulates_success_and_records_request() -> None:
    sender = MockEmailSender()
    draft = EmailDraft("user@example.com", "Subject", "Body")

    result = asyncio.run(sender.send(draft))

    assert result.success is True
    assert result.message_id == "mock-1"
    assert sender.requests == (draft,)


def test_mock_sender_can_simulate_failure() -> None:
    sender = MockEmailSender(failure_message="Development failure")
    draft = EmailDraft("user@example.com", "Subject", "Body")

    result = asyncio.run(sender.send(draft))

    assert result.success is False
    assert result.error == "Development failure"
    assert sender.requests == (draft,)
