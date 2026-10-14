"""Framework-independent tests for the Phase 4 application workflow."""

import asyncio
from pathlib import Path

from app.models.email import EmailDraft, EmailStatus, EmailTone, SendResult
from app.models.job_application import (
    CandidateProfile,
    EmailAttachment,
    JobApplicationRequest,
    Project,
)
from app.services.job_requirements import (
    CandidateRequirementMatcher,
    DeterministicJobRequirementExtractor,
)
from app.workflows.general_email import DraftMode, GeneralEmailWorkflow
from app.workflows.job_application import (
    JobApplicationResources,
    JobApplicationWorkflow,
)


class UnusedProfileService:
    async def get_profile(self) -> CandidateProfile:
        raise AssertionError("Resources are already supplied in these tests")


class UnusedAttachmentService:
    async def prepare(self) -> EmailAttachment:
        raise AssertionError("Resources are already supplied in these tests")


class RecordingSender:
    def __init__(self, success: bool = True) -> None:
        self.success = success
        self.calls: list[EmailDraft] = []

    async def send(self, draft: EmailDraft) -> SendResult:
        self.calls.append(draft)
        return SendResult(success=self.success, message_id="mock-job")


class RecordingJobGenerator:
    def __init__(self) -> None:
        self.calls = 0
        self.last_kwargs: dict[str, object] = {}

    async def generate(self, **kwargs: object) -> EmailDraft:
        self.calls += 1
        self.last_kwargs = kwargs
        request = kwargs["request"]
        return EmailDraft(
            recipient=request.company_email,  # type: ignore[union-attr]
            subject=f"Generated {self.calls}",
            body="Grounded generated body",
        )


def make_resources(tmp_path: Path) -> JobApplicationResources:
    cv = tmp_path / "CV.pdf"
    cv.write_bytes(b"%PDF")
    return JobApplicationResources(
        profile=CandidateProfile(
            name="Alex Candidate",
            skills=("Python", "SQL"),
            projects=(Project(name="Analytics", technologies=("Python",)),),
        ),
        attachment=EmailAttachment(
            file_path=str(cv.resolve()),
            file_name="CV.pdf",
            mime_type="application/pdf",
            size_bytes=cv.stat().st_size,
        ),
    )


def make_request() -> JobApplicationRequest:
    return JobApplicationRequest(
        company_email="jobs@example.com",
        company_name="Example Co",
        role="Software Engineer",
        job_description="Python and AWS required. SQL preferred.",
    )


def make_workflow(sender: RecordingSender) -> JobApplicationWorkflow:
    return JobApplicationWorkflow(
        profile_service=UnusedProfileService(),  # type: ignore[arg-type]
        attachment_service=UnusedAttachmentService(),  # type: ignore[arg-type]
        requirement_extractor=DeterministicJobRequirementExtractor(),
        matcher=CandidateRequirementMatcher(),
        approval_workflow=GeneralEmailWorkflow(generator=None, sender=sender),
    )


def test_manual_application_prepares_cv_without_calling_generator(tmp_path: Path) -> None:
    sender = RecordingSender()
    workflow = make_workflow(sender)
    resources = make_resources(tmp_path)

    session = workflow.start_manual(
        request=make_request(),
        resources=resources,
        subject="My application",
        body="Please consider my application.",
    )

    assert session.draft_mode is DraftMode.MANUAL
    assert session.prepared_email.attachments == (resources.attachment,)
    assert session.approval.draft.attachments == (resources.attachment.file_path,)
    assert session.match_result.matched_skills == ("Python", "SQL")
    assert session.match_result.unmatched_skills == ("AWS",)


def test_ai_regeneration_and_metadata_edits_are_explicit(tmp_path: Path) -> None:
    sender = RecordingSender()
    workflow = make_workflow(sender)
    generator = RecordingJobGenerator()
    session = asyncio.run(
        workflow.start_ai(
            request=make_request(),
            resources=make_resources(tmp_path),
            generator=generator,
            tone=EmailTone.FORMAL,
        )
    )

    edited = workflow.edit_role(session, "Backend Engineer")
    edited = workflow.edit_job_description(edited, "Docker and SQL required.")

    assert generator.calls == 1
    assert generator.last_kwargs["profile"] == session.profile
    assert generator.last_kwargs["request"] == session.request
    assert generator.last_kwargs["match_result"] == session.match_result
    assert edited.approval.draft.subject == "Generated 1"
    assert edited.match_result.matched_skills == ("SQL",)
    assert edited.match_result.unmatched_skills == ("Docker",)

    regenerated = asyncio.run(workflow.regenerate(edited, generator))
    assert generator.calls == 2
    assert regenerated.approval.draft.subject == "Generated 2"
    assert regenerated.approval.draft.attachments == (
        regenerated.attachment.file_path,
    )


def test_all_draft_edits_preserve_unrelated_values_and_attachment(tmp_path: Path) -> None:
    workflow = make_workflow(RecordingSender())
    session = workflow.start_manual(
        request=make_request(),
        resources=make_resources(tmp_path),
        subject="Original subject",
        body="Original body",
    )
    attachment = session.approval.draft.attachments

    recipient = workflow.edit_recipient(session, "new@example.com")
    subject = workflow.edit_subject(recipient, "New subject")
    body = workflow.edit_body(subject, "New body")
    company = workflow.edit_company(body, "New Company")

    assert company.request.company_email == "new@example.com"
    assert company.approval.draft.recipient == "new@example.com"
    assert company.approval.draft.subject == "New subject"
    assert company.approval.draft.body == "New body"
    assert company.request.company_name == "New Company"
    assert company.approval.draft.attachments == attachment


def test_confirm_is_exactly_once_and_cancel_never_sends(tmp_path: Path) -> None:
    sender = RecordingSender()
    workflow = make_workflow(sender)
    session = workflow.start_manual(
        request=make_request(),
        resources=make_resources(tmp_path),
        subject="Application",
        body="Application body",
    )

    first = asyncio.run(workflow.approve(session))
    duplicate = asyncio.run(workflow.approve(session))

    assert first.result.success is True
    assert first.session.approval.draft.status is EmailStatus.SENT
    assert duplicate.duplicate is True
    assert len(sender.calls) == 1

    another = workflow.start_manual(
        request=make_request(),
        resources=make_resources(tmp_path),
        subject="Cancelled",
        body="Cancelled body",
    )
    workflow.cancel(another)
    assert len(sender.calls) == 1


def test_sender_failure_retains_preview_and_allows_retry(tmp_path: Path) -> None:
    sender = RecordingSender(success=False)
    workflow = make_workflow(sender)
    session = workflow.start_manual(
        request=make_request(),
        resources=make_resources(tmp_path),
        subject="Application",
        body="Application body",
    )

    failed = asyncio.run(workflow.approve(session))
    sender.success = True
    retried = asyncio.run(workflow.approve(failed.session))

    assert failed.result.success is False
    assert failed.session.approval.draft.status is EmailStatus.PREVIEWED
    assert retried.result.success is True
    assert len(sender.calls) == 2

