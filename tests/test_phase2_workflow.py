"""Unit tests for the framework-independent Phase 2 approval lifecycle."""

import asyncio

from app.models.email import EmailDraft, EmailStatus, SendResult
from app.services.validation import InputValidationError
from app.workflows.general_email import GeneralEmailRequest, GeneralEmailWorkflow


class RecordingGenerator:
    """Generator test double that exposes invocation count and input."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    async def generate(
        self,
        *,
        recipient: str,
        purpose: str,
        context: str,
        tone: str = "Professional",
    ) -> EmailDraft:
        self.calls.append((recipient, purpose, context, tone))
        number = len(self.calls)
        return EmailDraft(
            recipient=recipient,
            subject=f"Generated subject {number}",
            body=f"Generated from: {context}",
        )


class RecordingSender:
    """Sender test double with a configurable provider-style result."""

    def __init__(self, result: SendResult | None = None) -> None:
        self.result = result or SendResult(success=True, message_id="test-1")
        self.calls: list[EmailDraft] = []

    async def send(self, draft: EmailDraft) -> SendResult:
        self.calls.append(draft)
        return self.result


def start_session(
    generator: RecordingGenerator | None = None,
    sender: RecordingSender | None = None,
):
    generator = generator or RecordingGenerator()
    sender = sender or RecordingSender()
    workflow = GeneralEmailWorkflow(generator, sender)
    session = asyncio.run(
        workflow.start(
            GeneralEmailRequest(
                recipient="first@example.com",
                purpose="Project update",
                context="The first context",
            )
        )
    )
    return workflow, generator, sender, session


def test_preview_confirm_calls_sender_exactly_once() -> None:
    workflow, _, sender, session = start_session()

    outcome = asyncio.run(workflow.approve(session))

    assert outcome.result.success is True
    assert outcome.session.draft.status is EmailStatus.SENT
    assert len(sender.calls) == 1


def test_duplicate_confirmation_does_not_call_sender_twice() -> None:
    workflow, _, sender, session = start_session()

    first = asyncio.run(workflow.approve(session))
    duplicate = asyncio.run(workflow.approve(session))

    assert first.result.success is True
    assert duplicate.duplicate is True
    assert len(sender.calls) == 1


def test_regenerate_calls_generator_again_and_keeps_session_active() -> None:
    workflow, generator, _, session = start_session()

    regenerated = asyncio.run(workflow.regenerate(session))

    assert len(generator.calls) == 2
    assert regenerated.draft.subject == "Generated subject 2"
    assert regenerated.draft.status is EmailStatus.PREVIEWED
    assert regenerated.confirmation_id == session.confirmation_id


def test_edit_recipient_changes_only_recipient_content() -> None:
    workflow, _, _, session = start_session()

    updated = workflow.edit_recipient(session, "second@example.com")

    assert updated.request.recipient == "second@example.com"
    assert updated.draft.recipient == "second@example.com"
    assert updated.draft.subject == session.draft.subject
    assert updated.draft.body == session.draft.body
    assert session.draft.recipient == "first@example.com"


def test_edit_subject_changes_only_subject() -> None:
    workflow, _, _, session = start_session()

    updated = workflow.edit_subject(session, "Manually edited subject")

    assert updated.draft.subject == "Manually edited subject"
    assert updated.draft.recipient == session.draft.recipient
    assert updated.draft.body == session.draft.body


def test_edit_body_changes_only_body() -> None:
    workflow, _, _, session = start_session()

    updated = workflow.edit_body(session, "A manually edited message")

    assert updated.draft.body == "A manually edited message"
    assert updated.draft.recipient == session.draft.recipient
    assert updated.draft.subject == session.draft.subject


def test_edit_context_updates_request_and_regenerates() -> None:
    workflow, generator, _, session = start_session()

    updated = asyncio.run(workflow.edit_context(session, "The revised context"))

    assert updated.request.context == "The revised context"
    assert updated.draft.body == "Generated from: The revised context"
    assert len(generator.calls) == 2


def test_invalid_edited_recipient_is_rejected_without_mutation() -> None:
    workflow, _, _, session = start_session()

    try:
        workflow.edit_recipient(session, "not-an-email")
    except InputValidationError:
        pass
    else:
        raise AssertionError("Invalid recipient should have been rejected")

    assert session.draft.recipient == "first@example.com"


def test_sender_failure_keeps_draft_available_and_retryable() -> None:
    failure = SendResult(success=False, error="Simulated outage")
    workflow, _, sender, session = start_session(sender=RecordingSender(failure))

    failed = asyncio.run(workflow.approve(session))
    retried = asyncio.run(workflow.approve(failed.session))

    assert failed.result.success is False
    assert failed.session.draft.status is EmailStatus.PREVIEWED
    assert retried.duplicate is False
    assert len(sender.calls) == 2


def test_cancellation_never_calls_sender() -> None:
    workflow, _, sender, session = start_session()

    workflow.cancel(session)

    assert sender.calls == []
