"""AI-backed email generation strategy with deterministic fallback."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from app.models.email import EmailDraft
from app.prompts.general_email import build_general_email_prompts
from app.services.ai.base import (
    AIProviderError,
    AIResponseValidationError,
    LLMProvider,
)
from app.services.ai.models import AIEmailOutput
from app.services.email_generator import EmailGenerator


LOGGER = logging.getLogger(__name__)


class AIEmailGenerator:
    """Generate validated drafts through an LLM and fall back on expected failures."""

    def __init__(self, provider: LLMProvider, fallback: EmailGenerator) -> None:
        self._provider = provider
        self._fallback = fallback

    async def generate(
        self,
        *,
        recipient: str,
        purpose: str,
        context: str,
        tone: str = "Professional",
    ) -> EmailDraft:
        system_prompt, user_prompt = build_general_email_prompts(
            recipient=recipient,
            purpose=purpose,
            context=context,
            tone=tone,
        )
        LOGGER.info("AI email generation requested")

        try:
            raw_response = await self._provider.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=AIEmailOutput,
            )
            output = self._validate_response(raw_response)
        except AIProviderError:
            LOGGER.warning("AI provider unavailable; deterministic fallback used")
            return await self._fallback.generate(
                recipient=recipient,
                purpose=purpose,
                context=context,
                tone=tone,
            )
        except AIResponseValidationError:
            LOGGER.warning("AI response validation failed; deterministic fallback used")
            return await self._fallback.generate(
                recipient=recipient,
                purpose=purpose,
                context=context,
                tone=tone,
            )

        LOGGER.info("AI email generation completed")
        return EmailDraft(
            recipient=recipient,
            subject=output.subject,
            body=output.body,
        )

    @staticmethod
    def _validate_response(raw_response: str) -> AIEmailOutput:
        try:
            return AIEmailOutput.model_validate_json(raw_response)
        except (ValidationError, ValueError, TypeError) as error:
            raise AIResponseValidationError(
                "The AI response did not match the email schema."
            ) from error
