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
from telethon.tl.types import Channel, Chat, User

logger = logging.getLogger("beli.telegram.listener")

# How long to wait before reconnecting after an error
_RECONNECT_DELAY = 30  # seconds

# Chats to always ignore (e.g. Telegram service notifications)
_IGNORED_USERNAMES = {"telegram", "telegramchannel", "spambot"}


def _entity_name(entity) -> str:
    return (
        getattr(entity, "title", None)
        or f"{getattr(entity, 'first_name', '') or ''} {getattr(entity, 'last_name', '') or ''}".strip()
        or "Desconocido"
    )


def _is_muted(dialog) -> bool:
    ns = getattr(getattr(dialog, "dialog", None), "notify_settings", None)
    if not ns:
        return False
    mute_until = getattr(ns, "mute_until", None)
    if not mute_until:
        return False
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    if isinstance(mute_until, datetime.datetime):
        if mute_until.tzinfo is None:
            mute_until = mute_until.replace(tzinfo=datetime.timezone.utc)
        return mute_until > now
    return int(mute_until) > int(now.timestamp())


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

        # Skip ignored accounts
        username = (getattr(sender, "username", "") or "").lower()
        if username in _IGNORED_USERNAMES:
            return

        # Determine chat type and mute status
        is_direct  = isinstance(chat, User)
        is_group   = isinstance(chat, (Chat, Channel))

        # For groups/channels: skip muted ones
        if is_group:
            try:
                dialog = await client.get_dialogs()
                chat_id = getattr(chat, "id", None)
                for d in dialog:
                    if getattr(d.entity, "id", None) == chat_id:
                        if _is_muted(d):
                            logger.debug(f"[Listener] Skipping muted chat: {chat_name}")
                            return
                        break
            except Exception:
                pass  # If we can't check mute status, proceed anyway

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
