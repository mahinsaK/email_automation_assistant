"""Network-free tests for Gmail MIME, sender, and per-user resolution."""

import asyncio
import base64
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.models.email import EmailDraft, EmailStatus
from app.models.gmail_connection import GoogleOAuthGrant, ResolvedGmailCredential
from app.models.job_application import CandidateProfile, EmailAttachment, JobApplicationRequest
from app.repositories.gmail_connection import SQLiteGmailConnectionRepository
from app.services.credential_cipher import FernetCredentialCipher
from app.services.gmail.client import GmailClientSession, GoogleGmailClientFactory
from app.services.gmail.mime_builder import GmailMIMEBuilder
from app.services.gmail.oauth_service import GMAIL_SEND_SCOPE
from app.services.gmail.sender import GmailEmailSender
from app.services.gmail_connection import GmailAuthorizationError, UserGmailConnectionService
from app.services.job_requirements import (
    CandidateRequirementMatcher,
    DeterministicJobRequirementExtractor,
)
from app.services.user_email_sender import ConfiguredUserEmailSenderResolver
from app.workflows.general_email import GeneralEmailWorkflow
from app.workflows.job_application import JobApplicationResources, JobApplicationWorkflow


class FakeGmailClient:
    def __init__(self) -> None:
        self.raw_messages: list[str] = []
        self.fail_authorization = False

    async def send_raw(self, raw_message: str) -> dict[str, str]:
        self.raw_messages.append(raw_message)
        if self.fail_authorization:
            raise GmailAuthorizationError("revoked")
        return {"id": "gmail-message-1", "threadId": "gmail-thread-1"}


class FakeClientFactory:
    def __init__(self, client: FakeGmailClient) -> None:
        self.client = client
        self.credentials: list[object] = []
        self.refreshed_token: str | None = None

    async def create(self, credential: object) -> GmailClientSession:
        self.credentials.append(credential)
        return GmailClientSession(
            client=self.client,
            refreshed_token=self.refreshed_token,
        )


class UnusedSender:
    async def send(self, draft: EmailDraft):
        raise AssertionError("The dynamically resolved Gmail sender must be used")


class UnusedProfileService:
    async def get_profile(self):
        raise AssertionError


class UnusedAttachmentService:
    async def prepare(self):
        raise AssertionError


def make_connection_service(tmp_path: Path) -> UserGmailConnectionService:
    repository = SQLiteGmailConnectionRepository(tmp_path / "assistant.db")
    asyncio.run(repository.initialize())
    return UserGmailConnectionService(
        repository=repository,
        cipher=FernetCredentialCipher(Fernet.generate_key().decode("ascii")),
    )


def decode_message(raw_message: str):
    return BytesParser(policy=policy.default).parsebytes(
        base64.urlsafe_b64decode(raw_message.encode("ascii"))
    )


def test_general_email_mime_encodes_headers_and_plain_text() -> None:
    raw = GmailMIMEBuilder().build(
        EmailDraft(
            recipient="receiver@example.com",
            subject="Test subject",
            body="First paragraph.\n\nSecond paragraph.",
        ),
        sender_email="sender@gmail.com",
    )

    message = decode_message(raw)

    assert message["To"] == "receiver@example.com"
    assert message["From"] == "sender@gmail.com"
    assert message["Subject"] == "Test subject"
    assert "Second paragraph." in message.get_content()
    assert not message.is_multipart()


def test_job_application_mime_contains_pdf_attachment(tmp_path: Path) -> None:
    cv = tmp_path / "Candidate CV.pdf"
    cv.write_bytes(b"%PDF-1.4 fake cv")
    raw = GmailMIMEBuilder().build(
        EmailDraft(
            recipient="careers@example.com",
            subject="Application",
            body="Please see my CV.",
            attachments=(str(cv),),
        ),
        sender_email="candidate@gmail.com",
    )

    message = decode_message(raw)
    attachments = list(message.iter_attachments())

    assert message.is_multipart()
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "Candidate CV.pdf"
    assert attachments[0].get_content_type() == "application/pdf"
    assert attachments[0].get_payload(decode=True) == b"%PDF-1.4 fake cv"


def test_gmail_sender_returns_structured_success_and_revoked_failure() -> None:
    client = FakeGmailClient()
    sender = GmailEmailSender(
        client=client,
        mime_builder=GmailMIMEBuilder(),
        sender_email="sender@gmail.com",
    )
    draft = EmailDraft("receiver@example.com", "Subject", "Body")

    success = asyncio.run(sender.send(draft))
    client.fail_authorization = True
    revoked = asyncio.run(sender.send(draft))

    assert success.success is True
    assert success.message_id == "gmail-message-1"
    assert success.thread_id == "gmail-thread-1"
    assert revoked.success is False
    assert revoked.error_code == "gmail_authorization_invalid"


def test_missing_attachment_returns_safe_failure_without_api_call(
    tmp_path: Path,
) -> None:
    client = FakeGmailClient()
    sender = GmailEmailSender(
        client=client,
        mime_builder=GmailMIMEBuilder(),
        sender_email="sender@gmail.com",
    )
    draft = EmailDraft(
        "receiver@example.com",
        "Subject",
        "Body",
        attachments=(str(tmp_path / "missing.pdf"),),
    )

    result = asyncio.run(sender.send(draft))

    assert result.success is False
    assert result.error_code == "mime_build_failed"
    assert client.raw_messages == []


def test_sender_resolution_is_user_scoped_and_rotates_refresh_token(
    tmp_path: Path,
) -> None:
    service = make_connection_service(tmp_path)
    asyncio.run(
        service.save_grant(
            101,
            GoogleOAuthGrant(
                "user-a@gmail.com",
                "old-token",
                (GMAIL_SEND_SCOPE,),
            ),
        )
    )
    client = FakeGmailClient()
    factory = FakeClientFactory(client)
    factory.refreshed_token = "rotated-token"
    resolver = ConfiguredUserEmailSenderResolver(
        connection_service=service,
        client_factory=factory,  # type: ignore[arg-type]
        mime_builder=GmailMIMEBuilder(),
    )

    resolved = asyncio.run(resolver.resolve(101))

    assert resolved is not None
    assert asyncio.run(resolver.resolve(202)) is None
    credential = asyncio.run(service.resolve(101))
    assert credential is not None
    assert credential.refresh_token == "rotated-token"
    assert credential.google_email == "user-a@gmail.com"


def test_google_client_factory_refreshes_access_before_building_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import google.auth.transport.requests
    import google.oauth2.credentials
    import google_auth_httplib2
    import googleapiclient.discovery
    import httplib2

    calls: dict[str, object] = {}

    class FakeCredentials:
        def __init__(self, **kwargs: object) -> None:
            calls["credential_kwargs"] = kwargs
            self.refresh_token = str(kwargs["refresh_token"])

        def refresh(self, request: object) -> None:
            calls["refresh_request"] = request

    class FakeRequest:
        pass

    class FakeHTTP:
        def __init__(self, *, timeout: int) -> None:
            calls["timeout"] = timeout

    class FakeAuthorizedHTTP:
        def __init__(self, credentials: object, *, http: object) -> None:
            calls["authorized_credentials"] = credentials
            calls["http"] = http

    fake_service = object()

    def fake_build(*args: object, **kwargs: object) -> object:
        calls["build_args"] = args
        calls["build_kwargs"] = kwargs
        return fake_service

    monkeypatch.setattr(google.oauth2.credentials, "Credentials", FakeCredentials)
    monkeypatch.setattr(google.auth.transport.requests, "Request", FakeRequest)
    monkeypatch.setattr(httplib2, "Http", FakeHTTP)
    monkeypatch.setattr(google_auth_httplib2, "AuthorizedHttp", FakeAuthorizedHTTP)
    monkeypatch.setattr(googleapiclient.discovery, "build", fake_build)
    factory = GoogleGmailClientFactory(
        client_id="client-id",
        client_secret="client-secret",
    )

    session = asyncio.run(
        factory.create(
            ResolvedGmailCredential(
                telegram_user_id=101,
                google_email="user@gmail.com",
                refresh_token="valid-refresh-token",
                scopes=(GMAIL_SEND_SCOPE,),
            )
        )
    )

    assert calls["refresh_request"].__class__ is FakeRequest
    assert calls["timeout"] == 30
    assert calls["build_args"] == ("gmail", "v1")
    assert session.refreshed_token == "valid-refresh-token"


def test_real_sender_success_failure_and_duplicate_preserve_workflow_state() -> None:
    client = FakeGmailClient()
    sender = GmailEmailSender(
        client=client,
        mime_builder=GmailMIMEBuilder(),
        sender_email="sender@gmail.com",
    )
    workflow = GeneralEmailWorkflow(generator=None, sender=UnusedSender())
    session = workflow.start_manual(
        recipient="receiver@example.com",
        subject="Subject",
        body="Body",
    )

    sent = asyncio.run(workflow.approve(session, sender=sender))
    duplicate = asyncio.run(workflow.approve(session, sender=sender))

    assert sent.session.draft.status is EmailStatus.SENT
    assert duplicate.duplicate is True
    assert len(client.raw_messages) == 1

    failing_client = FakeGmailClient()
    failing_client.fail_authorization = True
    failing_sender = GmailEmailSender(
        client=failing_client,
        mime_builder=GmailMIMEBuilder(),
        sender_email="sender@gmail.com",
    )
    retry_session = workflow.start_manual(
        recipient="receiver@example.com",
        subject="Retry",
        body="Body",
    )
    failed = asyncio.run(workflow.approve(retry_session, sender=failing_sender))

    assert failed.result.success is False
    assert failed.session.draft.status is EmailStatus.PREVIEWED


def test_job_application_fake_gmail_smoke_sends_cv_exactly_once(
    tmp_path: Path,
) -> None:
    cv = tmp_path / "CV.pdf"
    cv.write_bytes(b"%PDF fake application cv")
    approval = GeneralEmailWorkflow(generator=None, sender=UnusedSender())
    workflow = JobApplicationWorkflow(
        profile_service=UnusedProfileService(),  # type: ignore[arg-type]
        attachment_service=UnusedAttachmentService(),  # type: ignore[arg-type]
        requirement_extractor=DeterministicJobRequirementExtractor(),
        matcher=CandidateRequirementMatcher(),
        approval_workflow=approval,
    )
    session = workflow.start_manual(
        request=JobApplicationRequest(
            company_email="careers@example.com",
            company_name="Example Co",
            role="Engineer",
            job_description="Python required",
        ),
        resources=JobApplicationResources(
            profile=CandidateProfile(name="Alex", skills=("Python",)),
            attachment=EmailAttachment(
                file_path=str(cv),
                file_name="CV.pdf",
                mime_type="application/pdf",
                size_bytes=cv.stat().st_size,
            ),
        ),
        subject="Application",
        body="Please see my CV.",
    )
    client = FakeGmailClient()
    sender = GmailEmailSender(
        client=client,
        mime_builder=GmailMIMEBuilder(),
        sender_email="candidate@gmail.com",
    )

    sent = asyncio.run(workflow.approve(session, sender=sender))
    duplicate = asyncio.run(workflow.approve(session, sender=sender))
    message = decode_message(client.raw_messages[0])

    assert sent.result.success is True
    assert duplicate.duplicate is True
    assert len(client.raw_messages) == 1
    assert [part.get_filename() for part in message.iter_attachments()] == ["CV.pdf"]
