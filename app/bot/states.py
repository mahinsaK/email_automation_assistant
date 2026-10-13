"""Conversation states owned by the Telegram adapter."""

from enum import IntEnum


class GeneralEmailState(IntEnum):
    """Explicit states in the general email approval conversation."""

    WAITING_RECIPIENT = 1
    WAITING_PURPOSE = 2
    WAITING_CONTEXT = 3
    WAITING_FOR_ACTION = 4
    EDIT_MENU = 5
    EDIT_RECIPIENT = 6
    EDIT_SUBJECT = 7
    EDIT_BODY = 8
    EDIT_CONTEXT = 9
    WAITING_TONE = 10

