"""Conversation states owned by the Telegram adapter."""

from enum import IntEnum


class GeneralEmailState(IntEnum):
    """Steps in the Phase 1 /send conversation."""

    WAITING_RECIPIENT = 1
    WAITING_PURPOSE = 2
    WAITING_CONTEXT = 3

