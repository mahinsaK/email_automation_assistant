"""General email use case."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.email import EmailDraft
from app.services.email_generator import EmailGenerator
from app.services.validation import validate_email, validate_text


@dataclass(frozen=True, slots=True)
class GeneralEmailRequest:
    """Input DTO for the general-email workflow."""

    recipient: str
    purpose: str
    context: str


class GeneralEmailWorkflow:
    """Validate input and coordinate email draft generation."""

    def __init__(self, generator: EmailGenerator) -> None:
        self._generator = generator

    async def create_draft(self, request: GeneralEmailRequest) -> EmailDraft:
        recipient = validate_email(request.recipient)
        purpose = validate_text(
            request.purpose,
            field_name="Purpose",
            max_length=200,
        )
        context = validate_text(
            request.context,
            field_name="Additional context",
            max_length=4000,
        )
        return await self._generator.generate(
            recipient=recipient,
            purpose=purpose,
            context=context,
        )

