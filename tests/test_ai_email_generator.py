"""Unit tests for AI generation, validation, prompts, and fallback behavior."""

import asyncio

import pytest
from pydantic import BaseModel

from app.models.email import EmailDraft, EmailTone
from app.services.ai.base import AIProviderError
from app.services.ai_email_generator import AIEmailGenerator
from app.services.email_generator import DeterministicEmailGenerator
from app.services.email_sender import MockEmailSender
from app.workflows.general_email import GeneralEmailRequest, GeneralEmailWorkflow


class FakeProvider:
    """Return queued raw responses while recording prompts."""

    def __init__(self, *responses: str, error: Exception | None = None) -> None:
        self.responses = list(responses)
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_model": response_model,
            }
        )
        if self.error:
            raise self.error
        return self.responses.pop(0)


class RecordingFallback(DeterministicEmailGenerator):
    def __init__(self) -> None:
        self.calls = 0

    async def generate(
        self,
        *,
        recipient: str,
        purpose: str,
        context: str,
        tone: str = "Professional",
    ) -> EmailDraft:
        self.calls += 1
        return await super().generate(
            recipient=recipient,
            purpose=purpose,
            context=context,
            tone=tone,
        )


def generate_with(provider: FakeProvider):
    fallback = RecordingFallback()
    generator = AIEmailGenerator(provider, fallback)
    draft = asyncio.run(
        generator.generate(
            recipient="recipient@example.com",
            purpose="Internship inquiry",
            context="Ask whether summer positions are available.",
            tone="Friendly",
        )
    )
    return draft, fallback


def test_valid_ai_output_creates_email_draft() -> None:
    provider = FakeProvider(
        '{"subject":"Test Subject","body":"Test body"}'
    )

    draft, fallback = generate_with(provider)

    assert draft == EmailDraft(
        recipient="recipient@example.com",
        subject="Test Subject",
        body="Test body",
        created_at=draft.created_at,
    )
    assert fallback.calls == 0


@pytest.mark.parametrize(
    "response",
    [
        "not valid JSON",
        '{"body":"Hello"}',
        '{"subject":"A subject","body":"   "}',
    ],
)
def test_invalid_ai_output_uses_deterministic_fallback(response: str) -> None:
    draft, fallback = generate_with(FakeProvider(response))

    assert draft.subject == "Internship inquiry"
    assert fallback.calls == 1


def test_provider_error_uses_deterministic_fallback() -> None:
    provider = FakeProvider(error=AIProviderError("temporary failure"))

    draft, fallback = generate_with(provider)

    assert draft.subject == "Internship inquiry"
    assert fallback.calls == 1


def test_unexpected_programming_error_is_not_hidden_by_fallback() -> None:
    provider = FakeProvider(error=RuntimeError("programming bug"))
    generator = AIEmailGenerator(provider, RecordingFallback())

    with pytest.raises(RuntimeError, match="programming bug"):
        asyncio.run(
            generator.generate(
                recipient="recipient@example.com",
                purpose="Purpose",
                context="Context",
                tone="Professional",
            )
        )


def test_prompt_contains_only_request_fields_and_separates_user_data() -> None:
    provider = FakeProvider('{"subject":"Subject","body":"Body"}')

    generate_with(provider)

    call = provider.calls[0]
    user_prompt = str(call["user_prompt"])
    system_prompt = str(call["system_prompt"])
    assert "recipient@example.com" in user_prompt
    assert "Internship inquiry" in user_prompt
    assert "summer positions" in user_prompt
    assert "Friendly" in user_prompt
    assert "<email_request>" in user_prompt
    assert "Do not invent" in system_prompt
    assert "API key" not in user_prompt


def test_regeneration_invokes_ai_provider_again_with_stored_tone() -> None:
    provider = FakeProvider(
        '{"subject":"First","body":"First body"}',
        '{"subject":"Second","body":"Second body"}',
    )
    workflow = GeneralEmailWorkflow(
        AIEmailGenerator(provider, DeterministicEmailGenerator()),
        MockEmailSender(),
    )
    session = asyncio.run(
        workflow.start(
            GeneralEmailRequest(
                recipient="recipient@example.com",
                purpose="Purpose",
                context="Context",
                tone=EmailTone.CONCISE,
            )
        )
    )

    regenerated = asyncio.run(workflow.regenerate(session))

    assert regenerated.draft.subject == "Second"
    assert len(provider.calls) == 2
    assert '"tone": "Concise"' in str(provider.calls[1]["user_prompt"])
