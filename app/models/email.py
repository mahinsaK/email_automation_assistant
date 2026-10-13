"""Email domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class EmailStatus(StrEnum):
    """Lifecycle states available to an email draft."""

    DRAFT = "draft"
    PREVIEWED = "previewed"


@dataclass(frozen=True, slots=True)
class EmailDraft:
    """A provider-independent email draft produced by a workflow."""

    recipient: str
    subject: str
    body: str
    attachments: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: EmailStatus = EmailStatus.DRAFT

    def as_preview(self) -> str:
        """Render a safe plain-text preview for any user interface."""

        attachment_text = ", ".join(self.attachments) if self.attachments else "None"
        return (
            "EMAIL PREVIEW\n\n"
            f"Recipient:\n{self.recipient}\n\n"
            f"Subject:\n{self.subject}\n\n"
            f"Body:\n{self.body}\n\n"
            f"Attachments:\n{attachment_text}"
        )

