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
    WAITING_DRAFT_METHOD = 11
    MANUAL_WAITING_SUBJECT = 12
    MANUAL_WAITING_BODY = 13
    WAITING_AI_UNAVAILABLE_ACTION = 14
    AI_CONFIG_REPLACE_CONFIRM = 20
    AI_CONFIG_PROVIDER = 21
    AI_CONFIG_API_KEY = 22
    AI_CONFIG_RETRY = 23
    AI_REMOVE_CONFIRM = 24

