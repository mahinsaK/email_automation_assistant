"""Framework-independent general email and approval use cases."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from uuid import uuid4

from app.models.email import EmailDraft, EmailStatus, SendResult
from app.services.email_generator import EmailGenerator
from app.services.email_sender import EmailSender
from app.services.validation import validate_email, validate_text


LOGGER = logging.getLogger(__name__)


class WorkflowStateError(RuntimeError):
    """Raised when an operation is invalid for the current approval state."""


@dataclass(frozen=True, slots=True)
class GeneralEmailRequest:
    """Validated source information used to generate an email draft."""

    recipient: str
    purpose: str
    context: str


@dataclass(frozen=True, slots=True)
class GeneralEmailSession:
    """Immutable snapshot of one email's request and approval lifecycle."""

    request: GeneralEmailRequest
    draft: EmailDraft
    confirmation_id: str = field(default_factory=lambda: uuid4().hex)


@dataclass(frozen=True, slots=True)
class ApprovalOutcome:
    """Result of an approval attempt, including the next session snapshot."""

    session: GeneralEmailSession
    result: SendResult
    duplicate: bool = False


class GeneralEmailWorkflow:
    """Coordinate generation, editing, approval, and provider-independent send."""

    def __init__(self, generator: EmailGenerator, sender: EmailSender) -> None:
        self._generator = generator
        self._sender = sender
        # Claim before awaiting I/O so rapid double clicks cannot send twice.
        self._claimed_confirmations: set[str] = set()

    async def create_draft(self, request: GeneralEmailRequest) -> EmailDraft:
        """Validate a request and generate a draft (kept for the Phase 1 API)."""

        validated_request = self._validate_request(request)
        return await self._generate(validated_request)

    async def start(self, request: GeneralEmailRequest) -> GeneralEmailSession:
        """Start an approval lifecycle with a newly generated preview."""

        validated_request = self._validate_request(request)
        draft = await self._generate(validated_request)
        return GeneralEmailSession(request=validated_request, draft=draft)

    async def regenerate(
        self,
        session: GeneralEmailSession,
    ) -> GeneralEmailSession:
        """Generate a fresh draft from the stored original request."""

        self._require_editable(session)
        draft = await self._generate(session.request)
        LOGGER.info("Email draft regenerated")
        return replace(session, draft=draft)

    def edit_recipient(
        self,
        session: GeneralEmailSession,
        recipient: str,
    ) -> GeneralEmailSession:
        """Update recipient in both request and draft without regenerating content."""

        self._require_editable(session)
        validated = validate_email(recipient)
        request = replace(session.request, recipient=validated)
        draft = replace(session.draft, recipient=validated)
        LOGGER.info("Email draft recipient edited")
        return replace(session, request=request, draft=draft)

    def edit_subject(
        self,
        session: GeneralEmailSession,
        subject: str,
    ) -> GeneralEmailSession:
        """Update only the generated subject."""

        self._require_editable(session)
        validated = validate_text(subject, field_name="Subject", max_length=200)
        LOGGER.info("Email draft subject edited")
        return replace(session, draft=replace(session.draft, subject=validated))

    def edit_body(
        self,
        session: GeneralEmailSession,
        body: str,
    ) -> GeneralEmailSession:
        """Update only the generated message body."""

        self._require_editable(session)
        validated = validate_text(body, field_name="Message", max_length=10_000)
        LOGGER.info("Email draft body edited")
        return replace(session, draft=replace(session.draft, body=validated))

    async def edit_context(
        self,
        session: GeneralEmailSession,
        context: str,
    ) -> GeneralEmailSession:
        """Update source context and intentionally regenerate the entire draft."""

        self._require_editable(session)
        validated = validate_text(
            context,
            field_name="Original context",
            max_length=4000,
        )
        request = replace(session.request, context=validated)
        draft = await self._generate(request)
        LOGGER.info("Original context edited and email draft regenerated")
        return replace(session, request=request, draft=draft)

    async def approve(self, session: GeneralEmailSession) -> ApprovalOutcome:
        """Claim and send one draft at most once, while retaining failures for retry."""

        if (
            session.draft.status is not EmailStatus.PREVIEWED
            or session.confirmation_id in self._claimed_confirmations
        ):
            return ApprovalOutcome(
                session=session,
                result=SendResult(
                    success=False,
                    error="This draft is already being sent or has been sent.",
                ),
                duplicate=True,
            )

        self._claimed_confirmations.add(session.confirmation_id)
        sending_session = replace(
            session,
            draft=replace(session.draft, status=EmailStatus.SENDING),
        )
        LOGGER.info("Email draft approved by user")

        try:
            result = await self._sender.send(sending_session.draft)
        except Exception as error:
            LOGGER.exception("Email sender raised an unexpected error")
            result = SendResult(success=False, error=str(error) or "Sender failed")

        if result.success:
            sent_session = replace(
                sending_session,
                draft=replace(sending_session.draft, status=EmailStatus.SENT),
            )
            return ApprovalOutcome(session=sent_session, result=result)

        self._claimed_confirmations.discard(session.confirmation_id)
        retryable_session = replace(
            sending_session,
            draft=replace(sending_session.draft, status=EmailStatus.PREVIEWED),
        )
        LOGGER.error("Email sender failed")
        return ApprovalOutcome(session=retryable_session, result=result)

    def cancel(self, session: GeneralEmailSession | None = None) -> None:
        """Record cancellation; the adapter owns removal of its temporary state."""

        LOGGER.info("Email workflow cancelled")

    async def _generate(self, request: GeneralEmailRequest) -> EmailDraft:
        draft = await self._generator.generate(
            recipient=request.recipient,
            purpose=request.purpose,
            context=request.context,
        )
        return replace(draft, status=EmailStatus.PREVIEWED)

    @staticmethod
    def _validate_request(request: GeneralEmailRequest) -> GeneralEmailRequest:
        return GeneralEmailRequest(
            recipient=validate_email(request.recipient),
            purpose=validate_text(
                request.purpose,
                field_name="Purpose",
                max_length=200,
            ),
            context=validate_text(
                request.context,
                field_name="Additional context",
                max_length=4000,
            ),
        )

    @staticmethod
    def _require_editable(session: GeneralEmailSession) -> None:
        if session.draft.status is not EmailStatus.PREVIEWED:
            raise WorkflowStateError("Only a draft awaiting approval can be changed.")
