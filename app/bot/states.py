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


class JobApplicationState(IntEnum):
    """Explicit states for the specialized job application workflow."""

    WAITING_COMPANY_EMAIL = 100
    WAITING_COMPANY_NAME = 101
    WAITING_ROLE = 102
    WAITING_JOB_DESCRIPTION = 103
    WAITING_DRAFT_METHOD = 104
    MANUAL_WAITING_SUBJECT = 105
    MANUAL_WAITING_BODY = 106
    WAITING_TONE = 107
    WAITING_FOR_ACTION = 108
    WAITING_AI_UNAVAILABLE_ACTION = 109
    EDIT_MENU = 110
    EDIT_RECIPIENT = 111
    EDIT_COMPANY = 112
    EDIT_ROLE = 113
    EDIT_JOB_DESCRIPTION = 114
    EDIT_SUBJECT = 115
    EDIT_BODY = 116

