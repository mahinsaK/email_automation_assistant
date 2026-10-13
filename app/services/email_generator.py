"""Email generation interface and the deterministic Phase 1 implementation."""

from __future__ import annotations

from typing import Protocol

from app.models.email import EmailDraft


class EmailGenerator(Protocol):
    """Port implemented by deterministic or AI-backed email generators."""

    async def generate(
        self,
        *,
        recipient: str,
        purpose: str,
        context: str,
    ) -> EmailDraft:
        """Generate an email draft from validated workflow context."""
        ...


class DeterministicEmailGenerator:
    """Create predictable drafts without calling an external AI provider."""

    async def generate(
        self,
        *,
        recipient: str,
        purpose: str,
        context: str,
    ) -> EmailDraft:
        normalized_purpose = purpose.strip()
        normalized_context = context.strip()
        subject = normalized_purpose.rstrip(".!?")
        subject = subject[:1].upper() + subject[1:]

        body = (
            "Hello,\n\n"
            f"I am writing regarding {normalized_purpose.lower()}.\n\n"
            f"{normalized_context}\n\n"
            "Thank you for your time. I look forward to hearing from you.\n\n"
            "Best regards"
        )
        return EmailDraft(
            recipient=recipient,
            subject=subject,
            body=body,
        )

