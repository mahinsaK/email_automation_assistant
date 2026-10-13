"""Tests for the email domain model."""

from app.models.email import EmailDraft


def test_preview_contains_all_user_visible_fields() -> None:
    draft = EmailDraft(
        recipient="user@example.com",
        subject="Project update",
        body="The project is on schedule.",
    )

    preview = draft.as_preview()

    assert "user@example.com" in preview
    assert "Project update" in preview
    assert "The project is on schedule." in preview
    assert "Attachments:\nNone" in preview

