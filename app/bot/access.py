"""Optional Telegram user allow-list guard."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar, cast

from telegram import Update
from telegram.ext import ContextTypes


HandlerResult = int | None
Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[HandlerResult]]
F = TypeVar("F", bound=Handler)


def owner_only(allowed_user_id: int | None) -> Callable[[F], F]:
    """Allow all users when unset, or only the configured Telegram user."""

    def decorator(handler: F) -> F:
        @wraps(handler)
        async def wrapper(
            update: Update,
            context: ContextTypes.DEFAULT_TYPE,
        ) -> HandlerResult:
            user = update.effective_user
            if allowed_user_id is not None and (
                user is None or user.id != allowed_user_id
            ):
                if update.effective_message:
                    await update.effective_message.reply_text(
                        "Sorry, this bot is private."
                    )
                return None
            return await handler(update, context)

        return cast(F, wrapper)

    return decorator

