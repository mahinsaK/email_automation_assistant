"""Telegram adapter and offline smoke tests for Phase 4 job applications."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.ext import ConversationHandler

from app.bot.handlers.job_application_handler import build_job_application_callbacks
from app.bot.keyboards import (
    JOB_AI_ENTER_MANUAL,
    JOB_CONFIRM,
    JOB_DRAFT_AI,
    JOB_DRAFT_MANUAL,
    JOB_REGENERATE,
    JOB_TONE_CALLBACK_PREFIX,
)
from app.bot.states import JobApplicationState
from app.models.email import EmailDraft, SendResult
from app.models.job_application import CandidateProfile, EmailAttachment
from app.services.job_requirements import (
    CandidateRequirementMatcher,
    DeterministicJobRequirementExtractor,
)
from app.workflows.general_email import GeneralEmailWorkflow
from app.workflows.job_application import JobApplicationWorkflow


class StaticProfileService:
    async def get_profile(self) -> CandidateProfile:
        return CandidateProfile(name="Alex Candidate", skills=("Python", "SQL"))


class StaticAttachmentService:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def prepare(self) -> EmailAttachment:
        return EmailAttachment(
            file_path=str(self.path.resolve()),
            file_name=self.path.name,
            mime_type="application/pdf",
            size_bytes=self.path.stat().st_size,
        )


class RecordingSender:
    def __init__(self) -> None:
        self.calls: list[EmailDraft] = []

    async def send(self, draft: EmailDraft) -> SendResult:
        self.calls.append(draft)
        return SendResult(success=True, message_id="phase4-smoke")


class RecordingJobGenerator:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, **kwargs: object) -> EmailDraft:
        self.calls += 1
        request = kwargs["request"]
        return EmailDraft(
            recipient=request.company_email,  # type: ignore[union-attr]
            subject="AI application",
            body="Grounded AI application body",
        )


class StaticJobGeneratorResolver:
    def __init__(self, generator: RecordingJobGenerator | None) -> None:
        self.generator = generator

    async def is_available(self, user_id: int) -> bool:
        return self.generator is not None

    async def resolve(self, user_id: int) -> RecordingJobGenerator | None:
        return self.generator


def make_message(text: str = "") -> SimpleNamespace:
    return SimpleNamespace(text=text, reply_text=AsyncMock())


def make_text_update(text: str, user_id: int = 101) -> SimpleNamespace:
    message = make_message(text)
    return SimpleNamespace(
        callback_query=None,
        effective_message=message,
        effective_user=SimpleNamespace(id=user_id),
    )


def make_callback_update(data: str, user_id: int = 101) -> SimpleNamespace:
    message = make_message()
    query = SimpleNamespace(
        data=data,
        message=message,
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    return SimpleNamespace(
        callback_query=query,
        effective_message=message,
        effective_user=SimpleNamespace(id=user_id),
    )


def callback_data(message: SimpleNamespace) -> set[str]:
    values: set[str] = set()
    for call in message.reply_text.await_args_list:
        markup = call.kwargs.get("reply_markup")
        if markup:
            values.update(button.callback_data for row in markup.inline_keyboard for button in row)
    return values


def make_callbacks(
    tmp_path: Path,
    *,
    resolver: StaticJobGeneratorResolver | None = None,
) -> tuple[object, RecordingSender]:
    cv = tmp_path / "CV.pdf"
    cv.write_bytes(b"%PDF")
    sender = RecordingSender()
    workflow = JobApplicationWorkflow(
        profile_service=StaticProfileService(),  # type: ignore[arg-type]
        attachment_service=StaticAttachmentService(cv),  # type: ignore[arg-type]
        requirement_extractor=DeterministicJobRequirementExtractor(),
        matcher=CandidateRequirementMatcher(),
        approval_workflow=GeneralEmailWorkflow(generator=None, sender=sender),
    )
    return (
        build_job_application_callbacks(
            workflow,
            generator_resolver=resolver,
        ),
        sender,
    )


def collect_application_details(callbacks: object, context: SimpleNamespace) -> None:
    assert asyncio.run(callbacks.begin(make_text_update("/apply"), context)) is (
        JobApplicationState.WAITING_COMPANY_EMAIL
    )
    assert asyncio.run(
        callbacks.receive_company_email(make_text_update("jobs@example.com"), context)
    ) is JobApplicationState.WAITING_COMPANY_NAME
    assert asyncio.run(
        callbacks.receive_company_name(make_text_update("Example Co"), context)
    ) is JobApplicationState.WAITING_ROLE
    assert asyncio.run(
        callbacks.receive_role(make_text_update("Software Engineer"), context)
    ) is JobApplicationState.WAITING_JOB_DESCRIPTION
    state = asyncio.run(
        callbacks.receive_job_description(
            make_text_update("Python and AWS required; SQL preferred."),
            context,
        )
    )
    assert state is JobApplicationState.WAITING_DRAFT_METHOD


def test_manual_job_application_smoke_sends_once_without_generator(
    tmp_path: Path,
) -> None:
    generator = RecordingJobGenerator()
    callbacks, sender = make_callbacks(
        tmp_path,
        resolver=StaticJobGeneratorResolver(generator),
    )
    context = SimpleNamespace(user_data={})
    collect_application_details(callbacks, context)

    assert asyncio.run(
        callbacks.handle_draft_method(
            make_callback_update(JOB_DRAFT_MANUAL),
            context,
        )
    ) is JobApplicationState.MANUAL_WAITING_SUBJECT
    assert asyncio.run(
        callbacks.receive_manual_subject(make_text_update("My application"), context)
    ) is JobApplicationState.MANUAL_WAITING_BODY
    body_update = make_text_update("Please consider my application.")
    assert asyncio.run(callbacks.receive_manual_body(body_update, context)) is (
        JobApplicationState.WAITING_FOR_ACTION
    )
    assert JOB_REGENERATE not in callback_data(body_update.effective_message)

    assert asyncio.run(
        callbacks.handle_action(make_callback_update(JOB_CONFIRM), context)
    ) == ConversationHandler.END
    assert generator.calls == 0
    assert len(sender.calls) == 1
    assert sender.calls[0].attachments == (str((tmp_path / "CV.pdf").resolve()),)


def test_ai_job_application_smoke_uses_fake_generator_and_sends_once(
    tmp_path: Path,
) -> None:
    generator = RecordingJobGenerator()
    callbacks, sender = make_callbacks(
        tmp_path,
        resolver=StaticJobGeneratorResolver(generator),
    )
    context = SimpleNamespace(user_data={})
    collect_application_details(callbacks, context)

    assert asyncio.run(
        callbacks.handle_draft_method(make_callback_update(JOB_DRAFT_AI), context)
    ) is JobApplicationState.WAITING_TONE
    tone_update = make_callback_update(f"{JOB_TONE_CALLBACK_PREFIX}professional")
    assert asyncio.run(callbacks.handle_tone(tone_update, context)) is (
        JobApplicationState.WAITING_FOR_ACTION
    )
    assert JOB_REGENERATE in callback_data(tone_update.effective_message)

    assert asyncio.run(
        callbacks.handle_action(make_callback_update(JOB_CONFIRM), context)
    ) == ConversationHandler.END
    assert generator.calls == 1
    assert len(sender.calls) == 1


def test_ai_unavailable_offers_and_enters_manual_fallback(tmp_path: Path) -> None:
    callbacks, _ = make_callbacks(
        tmp_path,
        resolver=StaticJobGeneratorResolver(None),
    )
    context = SimpleNamespace(user_data={})
    collect_application_details(callbacks, context)
    ai_update = make_callback_update(JOB_DRAFT_AI)

    state = asyncio.run(callbacks.handle_draft_method(ai_update, context))

    assert state is JobApplicationState.WAITING_AI_UNAVAILABLE_ACTION
    assert JOB_AI_ENTER_MANUAL in callback_data(ai_update.effective_message)
    assert asyncio.run(
        callbacks.handle_ai_unavailable(
            make_callback_update(JOB_AI_ENTER_MANUAL),
            context,
        )
    ) is JobApplicationState.MANUAL_WAITING_SUBJECT


def test_invalid_manual_inputs_and_stale_callback_are_safe(tmp_path: Path) -> None:
    callbacks, _ = make_callbacks(tmp_path)
    context = SimpleNamespace(user_data={})
    collect_application_details(callbacks, context)
    asyncio.run(
        callbacks.handle_draft_method(make_callback_update(JOB_DRAFT_MANUAL), context)
    )

    assert asyncio.run(
        callbacks.receive_manual_subject(make_text_update("   "), context)
    ) is JobApplicationState.MANUAL_WAITING_SUBJECT

    stale_context = SimpleNamespace(user_data={})
    stale_state = asyncio.run(
        callbacks.handle_action(make_callback_update(JOB_CONFIRM), stale_context)
    )
    assert stale_state == ConversationHandler.END

