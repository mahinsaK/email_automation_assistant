"""Telegram adapter for per-user Gmail OAuth connection management."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.keyboards import (
    GMAIL_CONNECT_CANCEL,
    GMAIL_CONNECT_RECONNECT,
    GMAIL_DISCONNECT_CONFIRM,
    GMAIL_DISCONNECT_KEEP,
    gmail_authorization_keyboard,
    gmail_disconnect_keyboard,
    gmail_reconnect_keyboard,
)
from app.services.gmail.oauth_service import GmailOAuthService, GoogleOAuthError
from app.services.gmail_connection import (
    GmailConnectionError,
    UserGmailConnectionService,
)


LOGGER = logging.getLogger(__name__)

Callback = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[int | None]]
AuthorizationURL = Callable[[int], Awaitable[str | None]]


@dataclass(frozen=True, slots=True)
class GmailConnectionCallbacks:
    connect: Callback
    status: Callback
    begin_disconnect: Callback
    handle_connect_action: Callback
    handle_disconnect_action: Callback
    authorization_url: AuthorizationURL


def build_gmail_connection_callbacks(
    connection_service: UserGmailConnectionService,
    *,
    oauth_service: GmailOAuthService | None,
) -> GmailConnectionCallbacks:
    """Build Telegram callbacks without coupling OAuth to Telegram."""

    async def authorization_url(telegram_user_id: int) -> str | None:
        if oauth_service is None or not connection_service.credential_storage_available:
            return None
        try:
            return oauth_service.begin(telegram_user_id)
        except GoogleOAuthError:
            LOGGER.warning("Gmail authorization URL creation failed")
            return None

    async def _send_authorization_link(update: Update) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None:
            return
        url = await authorization_url(user.id)
        if url is None:
            await message.reply_text(
                "⚠️ Gmail OAuth is not configured on this server.\n\n"
                "The administrator must configure Google OAuth credentials and "
                "secure credential encryption."
            )
            return
        await message.reply_text(
            "Connect your Gmail account securely using Google.\n\n"
            "The link expires and can be used only once. Gmail passwords are "
            "never requested or stored.",
            reply_markup=gmail_authorization_keyboard(url),
        )

    async def connect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None:
            return
        try:
            existing = await connection_service.get_status(user.id)
        except GmailConnectionError:
            await message.reply_text("⚠️ Gmail connection status is unavailable.")
            return
        if existing is not None:
            await message.reply_text(
                "Gmail is already connected.\n\n"
                f"Account:\n{existing.google_email}\n\n"
                "Would you like to reconnect?",
                reply_markup=gmail_reconnect_keyboard(),
            )
            return
        await _send_authorization_link(update)

    async def handle_connect_action(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        if query.message:
            await query.edit_message_reply_markup(reply_markup=None)
        if query.data == GMAIL_CONNECT_CANCEL:
            if query.message:
                await query.message.reply_text("Gmail reconnection cancelled.")
            return
        if query.data != GMAIL_CONNECT_RECONNECT:
            if query.message:
                await query.message.reply_text("That Gmail action is not valid.")
            return
        await _send_authorization_link(update)

    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None:
            return
        try:
            connection = await connection_service.get_status(user.id)
        except GmailConnectionError:
            await message.reply_text("⚠️ Gmail status is temporarily unavailable.")
            return
        if connection is None:
            await message.reply_text(
                "📧 Gmail Status\n\n"
                "Status: Not connected\n\n"
                "Use /connect_gmail to connect your account."
            )
            return
        await message.reply_text(
            "📧 Gmail Status\n\n"
            f"Account: {connection.google_email}\n"
            "Status: Connected ✅"
        )

    async def begin_disconnect(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None:
            return
        try:
            connection = await connection_service.get_status(user.id)
        except GmailConnectionError:
            await message.reply_text("⚠️ Gmail status is temporarily unavailable.")
            return
        if connection is None:
            await message.reply_text("Gmail is not connected.")
            return
        await message.reply_text(
            "Disconnect Gmail?",
            reply_markup=gmail_disconnect_keyboard(),
        )

    async def handle_disconnect_action(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        query = update.callback_query
        user = update.effective_user
        if query is None or user is None:
            return
        await query.answer()
        if query.message:
            await query.edit_message_reply_markup(reply_markup=None)
        if query.data == GMAIL_DISCONNECT_KEEP:
            if query.message:
                await query.message.reply_text("Your Gmail connection was kept.")
            return
        if query.data != GMAIL_DISCONNECT_CONFIRM:
            if query.message:
                await query.message.reply_text("That Gmail action is not valid.")
            return
        try:
            await connection_service.remove(user.id)
        except GmailConnectionError:
            if query.message:
                await query.message.reply_text(
                    "⚠️ Gmail could not be disconnected right now."
                )
            return
        if query.message:
            await query.message.reply_text(
                "✅ Gmail disconnected.\n\n"
                "Your saved authorization has been removed."
            )

    return GmailConnectionCallbacks(
        connect=connect,
        status=status,
        begin_disconnect=begin_disconnect,
        handle_connect_action=handle_connect_action,
        handle_disconnect_action=handle_disconnect_action,
        authorization_url=authorization_url,
    )
