"""Reusable validation functions for workflow input."""

from __future__ import annotations

import re


class InputValidationError(ValueError):
    """Raised when user-supplied workflow input is invalid."""


MAX_PURPOSE_LENGTH = 200
MAX_CONTEXT_LENGTH = 4000
MAX_SUBJECT_LENGTH = 200
MAX_BODY_LENGTH = 10_000


_EMAIL_PATTERN = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)


def validate_email(value: str) -> str:
    """Return a normalized email address or raise a user-facing error."""

    email = value.strip()
    if not email:
        raise InputValidationError("Email address cannot be empty.")
    if len(email) > 254 or not _EMAIL_PATTERN.fullmatch(email):
        raise InputValidationError("That does not appear to be a valid email address.")
    return email


def validate_text(value: str, *, field_name: str, max_length: int) -> str:
    """Validate and normalize a required text field."""

    text = value.strip()
    if not text:
        raise InputValidationError(f"{field_name} cannot be empty.")
    if len(text) > max_length:
        raise InputValidationError(
            f"{field_name} is too long. Please use at most {max_length} characters."
        )
    return text

