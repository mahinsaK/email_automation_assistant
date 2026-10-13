"""Tests for the framework-independent general email use case."""

import asyncio

import pytest

from app.models.email import EmailDraft
from app.services.email_generator import DeterministicEmailGenerator
from app.services.validation import InputValidationError
from app.workflows.general_email import GeneralEmailRequest, GeneralEmailWorkflow


def test_workflow_generates_a_deterministic_draft() -> None:
    workflow = GeneralEmailWorkflow(DeterministicEmailGenerator())

    draft = asyncio.run(
        workflow.create_draft(
            GeneralEmailRequest(
                recipient="team@example.com",
                purpose="Meeting request",
                context="Could we meet on Friday to discuss the project?",
            )
        )
    )

    assert draft.recipient == "team@example.com"
    assert draft.subject == "Meeting request"
    assert "meet on Friday" in draft.body
    assert draft.attachments == ()


def test_workflow_rejects_invalid_input_before_generation() -> None:
    workflow = GeneralEmailWorkflow(DeterministicEmailGenerator())

    with pytest.raises(InputValidationError):
        asyncio.run(
            workflow.create_draft(
                GeneralEmailRequest(
                    recipient="not-an-email",
                    purpose="Meeting request",
                    context="Some context",
                )
            )
        )


class FakeGenerator:
    """Test double proving the workflow depends on an interface."""

    async def generate(
        self,
        *,
        recipient: str,
        purpose: str,
        context: str,
    ) -> EmailDraft:
        return EmailDraft(recipient=recipient, subject="Fake", body=context)


def test_workflow_accepts_an_injected_generator() -> None:
    workflow = GeneralEmailWorkflow(FakeGenerator())

    draft = asyncio.run(
        workflow.create_draft(
            GeneralEmailRequest(
                recipient="user@example.com",
                purpose="A purpose",
                context="Known context",
            )
        )
    )

    assert draft.subject == "Fake"

