"""Validate local CV files and expose attachment metadata only."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from app.models.job_application import EmailAttachment


LOGGER = logging.getLogger(__name__)
_ALLOWED_CV_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class AttachmentValidationError(RuntimeError):
    """Raised when configured attachment metadata is unsafe or unavailable."""


class CVAttachmentService:
    """Prepare CV metadata without reading or sending the file content."""

    def __init__(self, cv_file_path: str | Path) -> None:
        self._cv_file_path = Path(cv_file_path)

    async def prepare(self) -> EmailAttachment:
        try:
            attachment = await asyncio.to_thread(self._prepare_sync)
        except OSError as error:
            LOGGER.warning("CV attachment unavailable")
            raise AttachmentValidationError(
                "The configured CV file is missing or unreadable."
            ) from error
        LOGGER.info("CV attachment prepared")
        return attachment

    def _prepare_sync(self) -> EmailAttachment:
        path = self._cv_file_path
        if not path.is_file() or not os.access(path, os.R_OK):
            raise OSError("CV file does not exist or is unreadable.")
        size = path.stat().st_size
        if size <= 0:
            raise OSError("CV file is empty.")
        mime_type = _ALLOWED_CV_TYPES.get(path.suffix.lower())
        if mime_type is None:
            raise OSError("CV file type is unsupported.")
        return EmailAttachment(
            file_path=str(path.resolve()),
            file_name=path.name,
            mime_type=mime_type,
            size_bytes=size,
        )
