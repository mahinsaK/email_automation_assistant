"""Tests for reusable workflow input validation."""

import pytest

from app.services.validation import InputValidationError, validate_email, validate_text


@pytest.mark.parametrize(
    "value",
    ["person@example.com", "name.surname+tag@sub.example.co.uk"],
)
def test_validate_email_accepts_common_valid_addresses(value: str) -> None:
    assert validate_email(f"  {value}  ") == value


@pytest.mark.parametrize(
    "value",
    ["", "missing-at.example.com", "person@localhost", "@example.com"],
)
def test_validate_email_rejects_invalid_addresses(value: str) -> None:
    with pytest.raises(InputValidationError):
        validate_email(value)


def test_validate_text_rejects_empty_and_oversized_values() -> None:
    with pytest.raises(InputValidationError, match="cannot be empty"):
        validate_text("  ", field_name="Purpose", max_length=10)

    with pytest.raises(InputValidationError, match="too long"):
        validate_text("12345678901", field_name="Purpose", max_length=10)

