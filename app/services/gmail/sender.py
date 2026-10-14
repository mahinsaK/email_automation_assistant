"""Gmail API adapter for the existing email sender port."""

from __future__ import annotations

import asyncio
import logging

from app.models.email import EmailDraft, SendResult
from app.services.gmail.client import GmailClient, GmailClientError
from app.services.gmail.mime_builder import GmailMIMEBuilder, MIMEBuildError
from app.services.gmail_connection import GmailAuthorizationError


LOGGER = logging.getLogger(__name__)


class GmailEmailSender:
    """Send one already-approved email through an authenticated Gmail client."""

    def __init__(
        self,
        *,
        client: GmailClient,
        mime_builder: GmailMIMEBuilder,
        sender_email: str,
    ) -> None:
        self._client = client
        self._mime_builder = mime_builder
        self._sender_email = sender_email

    async def send(self, draft: EmailDraft) -> SendResult:
        LOGGER.info("Gmail send requested")
        try:
            raw_message = await asyncio.to_thread(
                self._mime_builder.build,
                draft,
                sender_email=self._sender_email,
            )
            response = await self._client.send_raw(raw_message)
        except GmailAuthorizationError:
            LOGGER.warning("Gmail authorization rejected during send")
            return SendResult(
                success=False,
                error="Gmail connection is invalid or revoked.",
                error_code="gmail_authorization_invalid",
            )
        except MIMEBuildError:
            LOGGER.warning("Gmail MIME or attachment preparation failed")
            return SendResult(
                success=False,
                error="The email or attachment could not be prepared.",
                error_code="mime_build_failed",
            )
        except GmailClientError:
            LOGGER.warning("Gmail delivery failed")
            return SendResult(
                success=False,
                error="Gmail could not send the email.",
                error_code="gmail_delivery_failed",
            )

        message_id = response.get("id")
        thread_id = response.get("threadId")
        if not isinstance(message_id, str) or not message_id:
            LOGGER.error("Gmail send response did not include a message ID")
            return SendResult(
                success=False,
                error="Gmail did not confirm delivery.",
                error_code="gmail_invalid_response",
            )
        LOGGER.info("Gmail send completed")
        return SendResult(
            success=True,
            message_id=message_id,
            thread_id=thread_id if isinstance(thread_id, str) else None,
        )
