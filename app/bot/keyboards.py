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

ACTION_PATTERN = r"^email:(confirm|edit|regenerate|cancel|gmail:back)$"
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

JOB_DRAFT_MANUAL = "job:draft:manual"
JOB_DRAFT_AI = "job:draft:ai"
JOB_DRAFT_METHOD_PATTERN = r"^job:draft:(manual|ai)$"

JOB_AI_CONFIGURE = "job:ai:configure"
JOB_AI_ENTER_MANUAL = "job:ai:manual"
JOB_AI_CANCEL = "job:ai:cancel"
JOB_AI_UNAVAILABLE_PATTERN = r"^job:ai:(configure|manual|cancel)$"

JOB_TONE_CALLBACK_PREFIX = "job:tone:"
JOB_TONE_PATTERN = r"^job:tone:(professional|concise|friendly|formal)$"
JOB_TONE_CALLBACKS = {
    f"{JOB_TONE_CALLBACK_PREFIX}professional": EmailTone.PROFESSIONAL,
    f"{JOB_TONE_CALLBACK_PREFIX}concise": EmailTone.CONCISE,
    f"{JOB_TONE_CALLBACK_PREFIX}friendly": EmailTone.FRIENDLY,
    f"{JOB_TONE_CALLBACK_PREFIX}formal": EmailTone.FORMAL,
}

JOB_CONFIRM = "job:confirm"
JOB_EDIT = "job:edit"
JOB_REGENERATE = "job:regenerate"
JOB_CANCEL = "job:cancel"
JOB_ACTION_PATTERN = r"^job:(confirm|edit|regenerate|cancel|gmail:back)$"

JOB_EDIT_RECIPIENT = "job:edit:recipient"
JOB_EDIT_COMPANY = "job:edit:company"
JOB_EDIT_ROLE = "job:edit:role"
JOB_EDIT_DESCRIPTION = "job:edit:description"
JOB_EDIT_SUBJECT = "job:edit:subject"
JOB_EDIT_BODY = "job:edit:body"
JOB_BACK_TO_PREVIEW = "job:edit:back"
JOB_EDIT_PATTERN = (
    r"^job:edit:(recipient|company|role|description|subject|body|back)$"
)
JOB_CALLBACK_PATTERN = r"^job:"

EMAIL_GMAIL_BACK = "email:gmail:back"
JOB_GMAIL_BACK = "job:gmail:back"

GMAIL_CONNECT_RECONNECT = "gmail_connect:reconnect"
GMAIL_CONNECT_CANCEL = "gmail_connect:cancel"
GMAIL_CONNECT_CALLBACK_PATTERN = r"^gmail_connect:(reconnect|cancel)$"
GMAIL_DISCONNECT_CONFIRM = "gmail_disconnect:confirm"
GMAIL_DISCONNECT_KEEP = "gmail_disconnect:keep"
GMAIL_DISCONNECT_CALLBACK_PATTERN = r"^gmail_disconnect:(confirm|keep)$"

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


def gmail_authorization_keyboard(authorization_url: str) -> InlineKeyboardMarkup:
    """Open Google's authorization page without putting tokens in Telegram."""

    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Connect Gmail", url=authorization_url)]]
    )


def gmail_reconnect_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Reconnect",
                    callback_data=GMAIL_CONNECT_RECONNECT,
                )
            ],
            [
                InlineKeyboardButton(
                    "Cancel",
                    callback_data=GMAIL_CONNECT_CANCEL,
                )
            ],
        ]
    )


def gmail_disconnect_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Disconnect",
                    callback_data=GMAIL_DISCONNECT_CONFIRM,
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Keep Connected",
                    callback_data=GMAIL_DISCONNECT_KEEP,
                )
            ],
        ]
    )


def email_gmail_required_keyboard(
    authorization_url: str | None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if authorization_url:
        rows.append([InlineKeyboardButton("Connect Gmail", url=authorization_url)])
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    "Back to Preview",
                    callback_data=EMAIL_GMAIL_BACK,
                )
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=CANCEL)],
        ]
    )
    return InlineKeyboardMarkup(rows)


def job_gmail_required_keyboard(
    authorization_url: str | None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if authorization_url:
        rows.append([InlineKeyboardButton("Connect Gmail", url=authorization_url)])
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    "Back to Preview",
                    callback_data=JOB_GMAIL_BACK,
                )
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=JOB_CANCEL)],
        ]
    )
    return InlineKeyboardMarkup(rows)


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


def job_draft_method_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✍️ Enter Draft", callback_data=JOB_DRAFT_MANUAL)],
            [InlineKeyboardButton("🤖 Generate with AI", callback_data=JOB_DRAFT_AI)],
        ]
    )


def job_ai_unavailable_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔑 Configure AI", callback_data=JOB_AI_CONFIGURE)],
            [
                InlineKeyboardButton(
                    "✍️ Enter Draft Instead",
                    callback_data=JOB_AI_ENTER_MANUAL,
                )
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=JOB_AI_CANCEL)],
        ]
    )


def job_tone_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💼 Professional",
                    callback_data=f"{JOB_TONE_CALLBACK_PREFIX}professional",
                ),
                InlineKeyboardButton(
                    "⚡ Concise",
                    callback_data=f"{JOB_TONE_CALLBACK_PREFIX}concise",
                ),
            ],
            [
                InlineKeyboardButton(
                    "😊 Friendly",
                    callback_data=f"{JOB_TONE_CALLBACK_PREFIX}friendly",
                ),
                InlineKeyboardButton(
                    "🎓 Formal",
                    callback_data=f"{JOB_TONE_CALLBACK_PREFIX}formal",
                ),
            ],
        ]
    )


def job_preview_actions_keyboard(draft_mode: DraftMode) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("✅ Confirm & Send", callback_data=JOB_CONFIRM)],
        [InlineKeyboardButton("✏️ Edit", callback_data=JOB_EDIT)],
    ]
    if draft_mode is DraftMode.AI:
        rows.append(
            [
                InlineKeyboardButton(
                    "🔄 Regenerate",
                    callback_data=JOB_REGENERATE,
                ),
                InlineKeyboardButton("❌ Cancel", callback_data=JOB_CANCEL),
            ]
        )
    else:
        rows.append([InlineKeyboardButton("❌ Cancel", callback_data=JOB_CANCEL)])
    return InlineKeyboardMarkup(rows)


def job_edit_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📧 Recipient", callback_data=JOB_EDIT_RECIPIENT)],
            [InlineKeyboardButton("🏢 Company", callback_data=JOB_EDIT_COMPANY)],
            [InlineKeyboardButton("💼 Role", callback_data=JOB_EDIT_ROLE)],
            [
                InlineKeyboardButton(
                    "📋 Job Description",
                    callback_data=JOB_EDIT_DESCRIPTION,
                )
            ],
            [InlineKeyboardButton("📌 Subject", callback_data=JOB_EDIT_SUBJECT)],
            [InlineKeyboardButton("📝 Message", callback_data=JOB_EDIT_BODY)],
            [
                InlineKeyboardButton(
                    "↩️ Back to Preview",
                    callback_data=JOB_BACK_TO_PREVIEW,
                )
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
