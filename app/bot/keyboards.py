"""Telegram inline keyboards and trusted callback identifiers."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models.ai_configuration import AIProviderType
from app.models.email import EmailTone
from app.workflows.general_email import DraftMode


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

DRAFT_MANUAL = "email:draft:manual"
DRAFT_AI = "email:draft:ai"
DRAFT_METHOD_PATTERN = r"^email:draft:(manual|ai)$"

AI_CONFIGURE = "email:ai:configure"
AI_ENTER_MANUAL = "email:ai:manual"
AI_UNAVAILABLE_CANCEL = "email:ai:cancel"
AI_UNAVAILABLE_PATTERN = r"^email:ai:(configure|manual|cancel)$"

AI_CONFIG_PROVIDER_PREFIX = "ai_config:provider:"
AI_CONFIG_OPENAI = f"{AI_CONFIG_PROVIDER_PREFIX}{AIProviderType.OPENAI.value}"
AI_CONFIG_REPLACE = "ai_config:replace"
AI_CONFIG_RETRY = "ai_config:retry"
AI_CONFIG_CANCEL = "ai_config:cancel"
AI_CONFIG_PROVIDER_PATTERN = r"^ai_config:(provider:openai|cancel)$"
AI_CONFIG_REPLACE_PATTERN = r"^ai_config:(replace|cancel)$"
AI_CONFIG_RETRY_PATTERN = r"^ai_config:(retry|cancel)$"
AI_CONFIG_CALLBACK_PATTERN = r"^ai_config:"
AI_PROVIDER_CALLBACKS = {AI_CONFIG_OPENAI: AIProviderType.OPENAI}

AI_REMOVE_CONFIRM = "ai_remove:confirm"
AI_REMOVE_KEEP = "ai_remove:keep"
AI_REMOVE_PATTERN = r"^ai_remove:(confirm|keep)$"
AI_REMOVE_CALLBACK_PATTERN = r"^ai_remove:"

TONE_CALLBACK_PREFIX = "email:tone:"
TONE_PATTERN = r"^email:tone:(professional|concise|friendly|formal)$"
TONE_CALLBACKS = {
    f"{TONE_CALLBACK_PREFIX}professional": EmailTone.PROFESSIONAL,
    f"{TONE_CALLBACK_PREFIX}concise": EmailTone.CONCISE,
    f"{TONE_CALLBACK_PREFIX}friendly": EmailTone.FRIENDLY,
    f"{TONE_CALLBACK_PREFIX}formal": EmailTone.FORMAL,
}


def draft_method_keyboard() -> InlineKeyboardMarkup:
    """Let the user explicitly choose a draft creation strategy."""

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✍️ Enter Draft", callback_data=DRAFT_MANUAL)],
            [InlineKeyboardButton("🤖 Generate with AI", callback_data=DRAFT_AI)],
        ]
    )


def ai_unavailable_keyboard() -> InlineKeyboardMarkup:
    """Offer honest recovery choices when no real AI provider is configured."""

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔑 Configure AI", callback_data=AI_CONFIGURE)],
            [
                InlineKeyboardButton(
                    "✍️ Enter Draft Instead",
                    callback_data=AI_ENTER_MANUAL,
                )
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=AI_UNAVAILABLE_CANCEL)],
        ]
    )


def ai_provider_keyboard() -> InlineKeyboardMarkup:
    """Supported providers for bring-your-own-key configuration."""

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("OpenAI", callback_data=AI_CONFIG_OPENAI)],
            [InlineKeyboardButton("❌ Cancel", callback_data=AI_CONFIG_CANCEL)],
        ]
    )


def ai_replace_keyboard() -> InlineKeyboardMarkup:
    """Confirm entry into a replacement configuration flow."""

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Replace Configuration",
                    callback_data=AI_CONFIG_REPLACE,
                )
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=AI_CONFIG_CANCEL)],
        ]
    )


def ai_validation_retry_keyboard() -> InlineKeyboardMarkup:
    """Offer another credential attempt without retaining the failed key."""

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Try Again", callback_data=AI_CONFIG_RETRY)],
            [InlineKeyboardButton("❌ Cancel", callback_data=AI_CONFIG_CANCEL)],
        ]
    )


def ai_remove_keyboard() -> InlineKeyboardMarkup:
    """Require explicit confirmation before removing a credential."""

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Remove", callback_data=AI_REMOVE_CONFIRM)],
            [InlineKeyboardButton("❌ Keep", callback_data=AI_REMOVE_KEEP)],
        ]
    )


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


def preview_actions_keyboard(draft_mode: DraftMode) -> InlineKeyboardMarkup:
    """Actions available while a draft awaits explicit approval."""

    rows = [
        [InlineKeyboardButton("✅ Confirm & Send", callback_data=CONFIRM)],
        [InlineKeyboardButton("✏️ Edit", callback_data=EDIT)],
    ]
    if draft_mode is DraftMode.AI:
        rows.append(
            [
                InlineKeyboardButton("🔄 Regenerate", callback_data=REGENERATE),
                InlineKeyboardButton("❌ Cancel", callback_data=CANCEL),
            ]
        )
    else:
        rows.append([InlineKeyboardButton("❌ Cancel", callback_data=CANCEL)])
    return InlineKeyboardMarkup(rows)


def edit_menu_keyboard(draft_mode: DraftMode) -> InlineKeyboardMarkup:
    """Structured choices for editing source data or generated content."""

    rows = [
        [InlineKeyboardButton("📧 Recipient", callback_data=EDIT_RECIPIENT)],
        [InlineKeyboardButton("📌 Subject", callback_data=EDIT_SUBJECT)],
        [InlineKeyboardButton("📝 Message", callback_data=EDIT_BODY)],
    ]
    if draft_mode is DraftMode.AI:
        rows.append(
            [InlineKeyboardButton("📋 Original Context", callback_data=EDIT_CONTEXT)]
        )
    rows.append(
        [InlineKeyboardButton("↩️ Back to Preview", callback_data=BACK_TO_PREVIEW)]
    )
    return InlineKeyboardMarkup(rows)
