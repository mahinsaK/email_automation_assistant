"""Telegram inline keyboards and trusted callback identifiers."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models.email import EmailTone


CONFIRM = "email:confirm"
EDIT = "email:edit"
REGENERATE = "email:regenerate"
CANCEL = "email:cancel"

EDIT_RECIPIENT = "email:edit:recipient"
EDIT_SUBJECT = "email:edit:subject"
EDIT_BODY = "email:edit:body"
EDIT_CONTEXT = "email:edit:context"
BACK_TO_PREVIEW = "email:edit:back"

ACTION_PATTERN = r"^email:(confirm|edit|regenerate|cancel)$"
EDIT_PATTERN = r"^email:edit:(recipient|subject|body|context|back)$"
EMAIL_CALLBACK_PATTERN = r"^email:"

TONE_CALLBACK_PREFIX = "email:tone:"
TONE_PATTERN = r"^email:tone:(professional|concise|friendly|formal)$"
TONE_CALLBACKS = {
    f"{TONE_CALLBACK_PREFIX}professional": EmailTone.PROFESSIONAL,
    f"{TONE_CALLBACK_PREFIX}concise": EmailTone.CONCISE,
    f"{TONE_CALLBACK_PREFIX}friendly": EmailTone.FRIENDLY,
    f"{TONE_CALLBACK_PREFIX}formal": EmailTone.FORMAL,
}


def tone_keyboard() -> InlineKeyboardMarkup:
    """Supported tones shown before draft generation."""

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💼 Professional",
                    callback_data=f"{TONE_CALLBACK_PREFIX}professional",
                ),
                InlineKeyboardButton(
                    "⚡ Concise",
                    callback_data=f"{TONE_CALLBACK_PREFIX}concise",
                ),
            ],
            [
                InlineKeyboardButton(
                    "😊 Friendly",
                    callback_data=f"{TONE_CALLBACK_PREFIX}friendly",
                ),
                InlineKeyboardButton(
                    "🎓 Formal",
                    callback_data=f"{TONE_CALLBACK_PREFIX}formal",
                ),
            ],
        ]
    )


def preview_actions_keyboard() -> InlineKeyboardMarkup:
    """Actions available while a draft awaits explicit approval."""

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Confirm & Send", callback_data=CONFIRM)],
            [InlineKeyboardButton("✏️ Edit", callback_data=EDIT)],
            [
                InlineKeyboardButton("🔄 Regenerate", callback_data=REGENERATE),
                InlineKeyboardButton("❌ Cancel", callback_data=CANCEL),
            ],
        ]
    )


def edit_menu_keyboard() -> InlineKeyboardMarkup:
    """Structured choices for editing source data or generated content."""

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📧 Recipient", callback_data=EDIT_RECIPIENT)],
            [InlineKeyboardButton("📌 Subject", callback_data=EDIT_SUBJECT)],
            [InlineKeyboardButton("📝 Message", callback_data=EDIT_BODY)],
            [InlineKeyboardButton("📋 Original Context", callback_data=EDIT_CONTEXT)],
            [InlineKeyboardButton("↩️ Back to Preview", callback_data=BACK_TO_PREVIEW)],
        ]
    )
