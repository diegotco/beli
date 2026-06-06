"""
channels/telegram_listener.py - Proactive Telegram notifications via Telethon.

Keeps a persistent Telethon connection to the owner's account and forwards
incoming messages to the owner via the Telegram Bot API.

Only notifies for:
  - Direct messages from contacts (1-on-1)
  - Group/channel messages only if the chat is NOT muted AND the owner
    has opted into group notifications via /notificaciones

Muted chats are cached at startup and refreshed hourly so each incoming
message only does an O(1) set lookup instead of a Telegram API call.

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

# ── Muted-chats cache ─────────────────────────────────────────────────────────
# Populated at startup and refreshed every hour.
# Hard rule: any chat_id in this set is NEVER forwarded, regardless of settings.
_muted_chat_ids: set[int] = set()
_MUTED_CACHE_REFRESH_INTERVAL = 3600  # seconds (1 hour)


async def _load_muted_chats(client: TelegramClient) -> None:
    """
    Iterates ALL of the owner's dialogs and builds a set of muted group/channel IDs.

    Uses iter_dialogs() which paginates automatically — catches every chat
    regardless of how many the owner has or how recently they were active.
    Muted-forever is represented by mute_until == 2147483647 (max int32).
    """
    global _muted_chat_ids
    now_ts = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
    muted: set[int] = set()
    try:
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if not isinstance(entity, (Chat, Channel)):
                continue
            raw = getattr(dialog, "dialog", None)
            ns  = getattr(raw, "notify_settings", None) if raw else None
            if ns is None:
                continue
            mute_until = getattr(ns, "mute_until", None)
            if mute_until:
                # Telethon may return mute_until as datetime or as int timestamp
                if isinstance(mute_until, datetime.datetime):
                    mu_ts = int(mute_until.replace(tzinfo=datetime.timezone.utc).timestamp()
                                if mute_until.tzinfo is None else mute_until.timestamp())
                else:
                    mu_ts = int(mute_until)
                if mu_ts > now_ts:
                    eid = getattr(entity, "id", None)
                    if eid:
                        muted.add(eid)
        _muted_chat_ids = muted
        logger.info(
            f"[Listener] Muted-chats cache loaded — {len(_muted_chat_ids)} muted chats."
        )
    except Exception as e:
        logger.error(f"[Listener] Could not load muted chats: {e}")


async def _refresh_muted_cache_loop(client: TelegramClient) -> None:
    """Background task: refreshes the muted-chats cache every hour."""
    while True:
        await asyncio.sleep(_MUTED_CACHE_REFRESH_INTERVAL)
        logger.debug("[Listener] Refreshing muted-chats cache…")
        await _load_muted_chats(client)


# ── Per-message fallback (used only if cache is empty) ────────────────────────

async def _is_muted_for_chat(client: TelegramClient, chat) -> bool:
    """
    Fallback: queries Telegram directly for the mute status of one specific chat.
    Only called when the cache hasn't been populated yet.
    """
    try:
        result = await client(GetPeerDialogsRequest(peers=[chat]))
        if not result.dialogs:
            return False
        ns = getattr(result.dialogs[0], "notify_settings", None)
        if ns is None:
            return False
        mute_until = getattr(ns, "mute_until", None)
        if not mute_until:
            return False
        now_ts = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
        if isinstance(mute_until, datetime.datetime):
            mu_ts = int(mute_until.replace(tzinfo=datetime.timezone.utc).timestamp()
                        if mute_until.tzinfo is None else mute_until.timestamp())
        else:
            mu_ts = int(mute_until)
        return mu_ts > now_ts
    except Exception as e:
        logger.debug(f"[Listener] Could not check mute status for chat: {e}")
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _entity_name(entity) -> str:
    return (
        getattr(entity, "title", None)
        or f"{getattr(entity, 'first_name', '') or ''} {getattr(entity, 'last_name', '') or ''}".strip()
        or "Desconocido"
    )


def _send_telegram(token: str, chat_id: int, text: str) -> None:
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10).raise_for_status()
    except Exception as e:
        logger.error(f"[Listener] Failed to notify owner: {e}")


# ── Main notification handler ─────────────────────────────────────────────────

async def _build_notification(event, client: TelegramClient, bot_token: str, owner_chat_id: int) -> None:
    """Processes a new incoming message and sends a notification to the owner."""
    try:
        msg = event.message
        if not msg or msg.out:
            return  # Skip outgoing messages

        chat   = await event.get_chat()
        sender = await event.get_sender()

        chat_name   = _entity_name(chat)
        sender_name = _entity_name(sender) if sender else chat_name

        # Skip ignored accounts and bots
        username = (getattr(sender, "username", "") or "").lower()
        if username in _IGNORED_USERNAMES:
            return
        if getattr(sender, "bot", False):
            return

        is_direct = isinstance(chat, User)
        is_group  = isinstance(chat, (Chat, Channel))

        # Hard rule: muted groups/channels are NEVER forwarded.
        # Check the cache first (O(1)); fall back to a direct API call only if
        # the cache hasn't been loaded yet (first few seconds after startup).
        if is_group:
            chat_id = getattr(chat, "id", None)
            if chat_id in _muted_chat_ids:
                logger.debug(f"[Listener] Skipping muted chat (cache): {chat_name}")
                return
            if not _muted_chat_ids and await _is_muted_for_chat(client, chat):
                logger.debug(f"[Listener] Skipping muted chat (fallback): {chat_name}")
                return

        # Check notification settings (user opt-in)
        from settings.notifications import get_settings
        if not get_settings().should_notify_telegram(is_group=is_group):
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
                return

        body_preview = body[:300] + ("…" if len(body) > 300 else "")

        if is_direct:
            notification = (
                f"Mensaje de {sender_name} por Telegram:\n\n"
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


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_listener(
    api_id: int,
    api_hash: str,
    session_string: str,
    bot_token: str,
    owner_chat_id: int,
) -> None:
    """
    Starts a persistent Telethon listener. Reconnects automatically on error.
    On each connection: loads the muted-chats cache and starts the hourly refresh.
    """
    session = StringSession(session_string) if session_string else str(
        __import__("pathlib").Path(__file__).parent.parent / "data" / "telethon_session"
    )

    logger.info("[Listener] Starting Telegram listener...")

    while True:
        try:
            async with TelegramClient(session, api_id, api_hash) as client:
                logger.info("[Listener] Connected. Loading muted-chats cache…")

                # Load muted chats before registering the message handler
                await _load_muted_chats(client)

                # Start hourly cache refresh as a background task
                refresh_task = asyncio.ensure_future(
                    _refresh_muted_cache_loop(client)
                )

                @client.on(events.NewMessage(incoming=True))
                async def _handler(event):
                    await _build_notification(event, client, bot_token, owner_chat_id)

                logger.info("[Listener] Ready. Listening for new messages...")
                await client.run_until_disconnected()

        except Exception as e:
            logger.error(f"[Listener] Disconnected: {e}. Reconnecting in {_RECONNECT_DELAY}s...")
            await asyncio.sleep(_RECONNECT_DELAY)
        finally:
            try:
                refresh_task.cancel()
            except Exception:
                pass
