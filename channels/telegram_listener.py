"""
channels/telegram_listener.py - Proactive Telegram notifications via Telethon.

Keeps a persistent Telethon connection to the owner's account and forwards
incoming messages to the owner via the Telegram Bot API.

Only notifies for:
  - Direct messages from contacts (1-on-1)
  - Group/channel messages only if the chat is NOT muted

The owner can then reply by telling @IamBeliBot:
  "respóndele a [name] por Telegram: [mensaje]"
"""
import asyncio
import datetime
import logging

import requests
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetPeerDialogsRequest
from telethon.tl.types import Channel, Chat, User

logger = logging.getLogger("beli.telegram.listener")

# How long to wait before reconnecting after an error
_RECONNECT_DELAY = 30  # seconds

# Chats to always ignore (e.g. Telegram service notifications, Beli's own bot)
_IGNORED_USERNAMES = {"telegram", "telegramchannel", "spambot", "iambelibot"}


def _entity_name(entity) -> str:
    return (
        getattr(entity, "title", None)
        or f"{getattr(entity, 'first_name', '') or ''} {getattr(entity, 'last_name', '') or ''}".strip()
        or "Desconocido"
    )


async def _is_muted_for_chat(client: TelegramClient, chat) -> bool:
    """
    Queries Telegram directly for the mute status of a specific chat/channel.

    Uses GetPeerDialogsRequest so we don't depend on the chat appearing in the
    first N results of get_dialogs() (which defaults to 20 and would miss any
    channel not recently active).

    Muted-forever is represented by mute_until == 2147483647 (max int32).
    """
    try:
        result = await client(GetPeerDialogsRequest(peers=[chat]))
        if not result.dialogs:
            return False
        d  = result.dialogs[0]
        ns = getattr(d, "notify_settings", None)
        if ns is None:
            return False
        mute_until = getattr(ns, "mute_until", None)
        if not mute_until:
            return False
        now_ts = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
        return int(mute_until) > now_ts
    except Exception as e:
        logger.debug(f"[Listener] Could not check mute status for chat: {e}")
        return False  # If we can't check, default to not-muted (safe fallback)


def _send_telegram(token: str, chat_id: int, text: str) -> None:
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10).raise_for_status()
    except Exception as e:
        logger.error(f"[Listener] Failed to notify owner: {e}")


async def _build_notification(event, client: TelegramClient, bot_token: str, owner_chat_id: int) -> None:
    """Processes a new incoming message and sends a notification to the owner."""
    try:
        msg = event.message
        if not msg or msg.out:
            return  # Skip outgoing messages

        # Get sender and chat info
        chat   = await event.get_chat()
        sender = await event.get_sender()

        chat_name   = _entity_name(chat)
        sender_name = _entity_name(sender) if sender else chat_name

        # Skip ignored accounts and bots (prevents loop with Beli's own bot)
        username = (getattr(sender, "username", "") or "").lower()
        if username in _IGNORED_USERNAMES:
            return
        if getattr(sender, "bot", False):
            return

        # Determine chat type and mute status
        is_direct  = isinstance(chat, User)
        is_group   = isinstance(chat, (Chat, Channel))

        # Check notification settings before going further
        from settings.notifications import get_settings
        if not get_settings().should_notify_telegram(is_group=is_group):
            return

        # For groups/channels: skip muted ones
        if is_group:
            if await _is_muted_for_chat(client, chat):
                logger.debug(f"[Listener] Skipping muted chat: {chat_name}")
                return

        # Build message body
        body = msg.text or ""
        if not body:
            if msg.voice or msg.audio:
                body = "[audio]"
            elif msg.photo:
                body = "[imagen]"
            elif msg.video:
                body = "[video]"
            elif msg.sticker:
                body = "[sticker]"
            elif msg.document:
                body = "[archivo]"
            else:
                return  # Nothing useful to forward

        body_preview = body[:300] + ("…" if len(body) > 300 else "")

        # Format notification
        if is_direct:
            channel_label = "Telegram"
            notification = (
                f"Mensaje de {sender_name} por {channel_label}:\n\n"
                f"{body_preview}\n\n"
                f"Para responder: \"respóndele a {sender_name.split()[0]} por Telegram: [tu mensaje]\""
            )
        else:
            notification = (
                f"Mensaje en {chat_name} (Telegram):\n"
                f"{sender_name}: {body_preview}\n\n"
                f"Para responder: \"respóndele a {sender_name.split()[0]} en {chat_name}: [tu mensaje]\""
            )

        _send_telegram(bot_token, owner_chat_id, notification)

    except Exception as e:
        logger.exception(f"[Listener] Error processing message: {e}")


async def run_listener(
    api_id: int,
    api_hash: str,
    session_string: str,
    bot_token: str,
    owner_chat_id: int,
) -> None:
    """
    Starts a persistent Telethon listener. Reconnects automatically on error.
    Intended to run as a long-lived asyncio task.
    """
    from config import config
    session = StringSession(session_string) if session_string else str(
        __import__("pathlib").Path(__file__).parent.parent / "data" / "telethon_session"
    )

    logger.info("[Listener] Starting Telegram listener...")

    while True:
        try:
            async with TelegramClient(session, api_id, api_hash) as client:
                logger.info("[Listener] Connected. Listening for new messages...")

                @client.on(events.NewMessage(incoming=True))
                async def _handler(event):
                    await _build_notification(event, client, bot_token, owner_chat_id)

                await client.run_until_disconnected()

        except Exception as e:
            logger.error(f"[Listener] Disconnected: {e}. Reconnecting in {_RECONNECT_DELAY}s...")
            await asyncio.sleep(_RECONNECT_DELAY)
