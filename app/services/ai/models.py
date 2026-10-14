"""Validation models for untrusted external AI responses."""

from pydantic import BaseModel, ConfigDict, Field

from app.services.validation import MAX_BODY_LENGTH, MAX_SUBJECT_LENGTH


class AIEmailOutput(BaseModel):
    """Strict structured response accepted from an AI provider."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject: str = Field(min_length=1, max_length=MAX_SUBJECT_LENGTH)
    body: str = Field(min_length=1, max_length=MAX_BODY_LENGTH)
