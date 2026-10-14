"""Build RFC-compliant base64url Gmail messages with attachments."""

from __future__ import annotations

import base64
import mimetypes
from email.message import EmailMessage
from pathlib import Path

from app.models.email import EmailDraft


class MIMEBuildError(RuntimeError):
    """Raised when an outgoing email cannot be represented safely."""


class GmailMIMEBuilder:
    """Create a plain-text MIME message from the shared email model."""

    def build(self, draft: EmailDraft, *, sender_email: str) -> str:
        try:
            message = EmailMessage()
            message["To"] = draft.recipient
            message["From"] = sender_email
            message["Subject"] = draft.subject
            message.set_content(draft.body)
            for attachment_path in draft.attachments:
                self._add_attachment(message, Path(attachment_path))
            return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        except (OSError, TypeError, ValueError) as error:
            raise MIMEBuildError("The email or an attachment could not be prepared.") from error

    @staticmethod
    def _add_attachment(message: EmailMessage, path: Path) -> None:
        if not path.is_file() or path.stat().st_size <= 0:
            raise OSError("Attachment is missing or empty.")
        content_type, encoding = mimetypes.guess_type(path.name)
        if content_type is None or encoding is not None:
            content_type = "application/octet-stream"
        maintype, subtype = content_type.split("/", 1)
        message.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )
