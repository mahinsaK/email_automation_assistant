"""Telegram inline keyboards and trusted callback identifiers."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


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
