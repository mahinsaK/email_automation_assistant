"""In-process Phase 3 smoke test with no external API or real email delivery."""

import asyncio

from pydantic import BaseModel

from app.models.email import EmailStatus, EmailTone
from app.services.ai_email_generator import AIEmailGenerator
from app.services.email_generator import DeterministicEmailGenerator
from app.services.email_sender import MockEmailSender
from app.workflows.general_email import GeneralEmailRequest, GeneralEmailWorkflow


class SmokeProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> str:
        self.calls += 1
        return '{"subject":"AI smoke subject","body":"AI smoke body"}'


def test_ai_preview_to_approval_uses_only_mock_sender() -> None:
    provider = SmokeProvider()
    sender = MockEmailSender()
    workflow = GeneralEmailWorkflow(
        AIEmailGenerator(provider, DeterministicEmailGenerator()),
        sender,
    )

    session = asyncio.run(
        workflow.start(
            GeneralEmailRequest(
                recipient="recipient@example.com",
                purpose="Smoke test",
                context="Use the fake provider only.",
                tone=EmailTone.PROFESSIONAL,
            )
        )
    )
    outcome = asyncio.run(workflow.approve(session))

    assert session.draft.subject == "AI smoke subject"
    assert session.draft.status is EmailStatus.PREVIEWED
    assert outcome.result.success is True
    assert outcome.session.draft.status is EmailStatus.SENT
    assert provider.calls == 1
    assert len(sender.requests) == 1
