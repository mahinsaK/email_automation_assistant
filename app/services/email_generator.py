"""Email generation strategy interface and deterministic implementation."""

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
        tone: str = "Professional",
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
        tone: str = "Professional",
    ) -> EmailDraft:
        normalized_purpose = purpose.strip()
        normalized_context = context.strip()
        subject = normalized_purpose.rstrip(".!?")
        subject = subject[:1].upper() + subject[1:]

        if tone == "Concise":
            body = (
                "Hello,\n\n"
                f"I am writing regarding {normalized_purpose.lower()}. "
                f"{normalized_context}\n\nThank you."
            )
        elif tone == "Friendly":
            body = (
                "Hi,\n\n"
                f"I hope you are doing well. I am reaching out regarding "
                f"{normalized_purpose.lower()}.\n\n{normalized_context}\n\n"
                "Thanks for your time. I look forward to hearing from you.\n\n"
                "Best"
            )
        elif tone == "Formal":
            body = (
                "Dear Sir or Madam,\n\n"
                f"I am writing with regard to {normalized_purpose.lower()}.\n\n"
                f"{normalized_context}\n\n"
                "Thank you for your consideration. I look forward to your response.\n\n"
                "Yours faithfully"
            )
        else:
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

