"""
tools/whatsapp_sender.py - WhatsApp messaging via WAHA (WhatsApp HTTP API).

WAHA is a self-hosted Docker container that wraps WhatsApp Web and exposes
a clean REST API. All messages are sent FROM the owner's personal WhatsApp number.

WAHA API reference: https://waha.devlike.pro/docs/how-to/send-messages/
"""
import logging
import re
from typing import Optional

import requests

logger = logging.getLogger("beli.tools.whatsapp")

_DEFAULT_SESSION = "default"
_REQUEST_TIMEOUT = 30  # seconds


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_chat_id(phone: str) -> str:
    """
    Converts a phone number to a WhatsApp chat ID.
    '+52 556 110 3975' → '525561103975@c.us'
    """
    clean = phone.lstrip("+").replace(" ", "").replace("-", "")
    return f"{clean}@c.us"


def _display_name(chat: dict) -> str:
    """Returns the best available display name for a chat."""
    return (
        chat.get("name")
        or chat.get("id", "").replace("@c.us", "").replace("@g.us", "")
        or "Desconocido"
    )


# ── Tool 1: Send WhatsApp message ─────────────────────────────────────────────

def _headers(api_key: str = "") -> dict:
    """Returns WAHA auth headers. Empty key means no auth required."""
    if api_key:
        return {"X-Api-Key": api_key}
    return {}


def _resolve_chat_id(
    waha_url: str,
    recipient: str,
    session: str,
    api_key: str,
) -> tuple[str, str]:
    """
    Resolves a recipient string to a WhatsApp chat ID and display label.
    Accepts: phone numbers, chat IDs (@c.us / @g.us), or contact/group names.
    Returns: (chat_id, display_label)
    """
    # Already a proper WhatsApp ID
    if "@" in recipient:
        return recipient, recipient

    # Looks like a phone number → convert directly
    stripped = recipient.lstrip("+").replace(" ", "").replace("-", "")
    if stripped.isdigit():
        chat_id = f"{stripped}@c.us"
        return chat_id, recipient

    # Name-based lookup — search recent chats (covers both contacts and groups)
    try:
        resp = requests.get(
            f"{waha_url.rstrip('/')}/api/{session}/chats",
            params={"limit": 50},
            headers=_headers(api_key),
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        chats = resp.json()
        search = recipient.lower()
        match = next(
            (c for c in chats if search in _display_name(c).lower()),
            None,
        )
        if match:
            return match["id"], _display_name(match)
        # Name not found in chats — signal as error so we don't send to a garbage ID
        return None, f"No se encontró ningún chat llamado '{recipient}' en WhatsApp."
    except Exception as e:
        logger.warning(f"[WhatsApp] Name lookup failed for '{recipient}': {e}")
        return None, f"Error al buscar el chat '{recipient}': {e}"


def send_whatsapp_message(
    waha_url: str,
    recipient: str,
    message: str,
    session: str = _DEFAULT_SESSION,
    api_key: str = "",
    mentions: list[str] | None = None,
) -> str:
    """
    Sends a WhatsApp text message FROM the owner's personal number.

    Args:
        waha_url:  Base URL of the WAHA service (e.g. 'https://waha.up.railway.app')
        recipient: Phone number ('+525561103975'), WhatsApp chat ID ('525561103975@c.us'),
                   group ID ('120363xxxxxxxx@g.us'), or contact/group name ('Ñaños', 'Mom')
        message:   Text to send. Use @{phone} (digits only) to mention someone, e.g. "@593987370597"
        mentions:  List of phone numbers (digits only) to mention, e.g. ["593987370597"].
                   WhatsApp will show the contact's saved name, not the number.
        session:   WAHA session name (default: 'default')
    """
    chat_id, display_label = _resolve_chat_id(waha_url, recipient, session, api_key)

    if chat_id is None:
        logger.error(f"[WhatsApp] Could not resolve recipient '{recipient}': {display_label}")
        return f"Error: {display_label}"

    url     = f"{waha_url.rstrip('/')}/api/sendText"
    payload: dict = {"session": session, "chatId": chat_id, "text": message}

    # Add mentions array — WAHA expects "{number}@c.us" format
    if mentions:
        payload["mentions"] = [
            f"{re.sub(r'[^0-9]', '', m)}@c.us" for m in mentions
        ]

    logger.info(f"[WhatsApp] Sending to {chat_id}: {message[:60]}...")

    try:
        resp = requests.post(url, json=payload, headers=_headers(api_key), timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        logger.info(f"[WhatsApp] Sent successfully to {chat_id}")
        return f"✓ ENVIADO EXITOSAMENTE por WhatsApp a {display_label}."
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("message", e.response.text)
        except Exception:
            detail = str(e)
        logger.error(f"[WhatsApp] HTTP error sending to {chat_id}: {detail}")
        return f"Error al enviar por WhatsApp: {detail}"
    except Exception as e:
        logger.exception(f"[WhatsApp] Error sending to {chat_id}: {e}")
        return f"Error al enviar por WhatsApp: {e}"


# ── Tool 2: Read recent WhatsApp chats ────────────────────────────────────────

def read_whatsapp_chats(
    waha_url: str,
    limit: int = 10,
    session: str = _DEFAULT_SESSION,
    api_key: str = "",
) -> str:
    """
    Returns a summary of the owner's most recent WhatsApp conversations.
    """
    limit = min(max(1, limit), 30)
    url   = f"{waha_url.rstrip('/')}/api/{session}/chats"

    logger.info(f"[WhatsApp] Reading {limit} recent chats.")

    try:
        resp = requests.get(url, params={"limit": limit}, headers=_headers(api_key), timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        chats = resp.json()

        if not chats:
            return "No encontré conversaciones recientes en WhatsApp."

        lines = []
        for i, chat in enumerate(chats[:limit], 1):
            name    = _display_name(chat)
            unread  = chat.get("unreadCount", 0)
            last    = chat.get("lastMessage") or {}
            preview = (last.get("body") or last.get("caption") or "[sin preview]")[:80]
            from_me = last.get("fromMe", False)
            sender  = "Tú" if from_me else name.split()[0]
            unread_label = f" [{unread} sin leer]" if unread else ""
            lines.append(f"{i}. {name}{unread_label}\n   {sender}: {preview}")

        return "Tus últimas conversaciones en WhatsApp:\n\n" + "\n\n".join(lines)

    except Exception as e:
        logger.exception(f"[WhatsApp] Error reading chats: {e}")
        return f"Error al leer los chats de WhatsApp: {e}"


# ── Tool 3: Read chat history ─────────────────────────────────────────────────

def _download_media(waha_url: str, message_id: str, session: str, api_key: str) -> bytes | None:
    """Downloads media bytes for a given WAHA message ID. Returns None on failure."""
    try:
        url = f"{waha_url.rstrip('/')}/api/{session}/messages/{message_id}/download"
        resp = requests.get(url, headers=_headers(api_key), timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.warning(f"[WhatsApp] Could not download media for message {message_id}: {e}")
        return None


def read_whatsapp_chat_history(
    waha_url: str,
    phone_or_name: str,
    limit: int = 30,
    session: str = _DEFAULT_SESSION,
    api_key: str = "",
    timezone: str = "America/Mexico_City",
    groq_api_key: str = "",
) -> str:
    """
    Reads the recent message history of a specific WhatsApp chat.
    Accepts a phone number or searches by name among recent chats.
    """
    limit = min(max(1, limit), 100)

    # Resolve chat ID
    if phone_or_name.lstrip("+").replace(" ", "").isdigit() or "@" in phone_or_name:
        chat_id = _to_chat_id(phone_or_name) if "@" not in phone_or_name else phone_or_name
    else:
        # Search by name in recent chats
        try:
            chats_resp = requests.get(
                f"{waha_url.rstrip('/')}/api/{session}/chats",
                params={"limit": 50},
                headers=_headers(api_key),
                timeout=_REQUEST_TIMEOUT,
            )
            chats_resp.raise_for_status()
            chats = chats_resp.json()
            search = phone_or_name.lower()
            match  = next(
                (c for c in chats if search in _display_name(c).lower()),
                None,
            )
            if not match:
                return (
                    f"No encontré ningún chat llamado '{phone_or_name}' en WhatsApp. "
                    f"Intenta con el número de teléfono."
                )
            chat_id = match["id"]
        except Exception as e:
            return f"Error al buscar el chat '{phone_or_name}': {e}"

    url = f"{waha_url.rstrip('/')}/api/{session}/chats/{chat_id}/messages"
    logger.info(f"[WhatsApp] Reading {limit} messages from {chat_id}.")

    try:
        resp = requests.get(
            url,
            params={"limit": limit, "downloadMedia": "true"},
            headers=_headers(api_key),
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        messages = resp.json()

        if not messages:
            return f"No encontré mensajes en el chat con '{phone_or_name}'."

        import datetime, zoneinfo
        try:
            tz_info = zoneinfo.ZoneInfo(timezone)
        except Exception:
            tz_info = zoneinfo.ZoneInfo("America/Mexico_City")

        # Lazy-import transcriber only if we'll need it
        transcriber = None
        if groq_api_key:
            try:
                from tools.transcriber import transcribe_audio
                transcriber = transcribe_audio
            except ImportError:
                logger.warning("[WhatsApp] transcriber module not available")

        lines = []
        for msg in reversed(messages):
            msg_type = msg.get("type", "")
            has_media = msg.get("hasMedia", False)
            from_me   = msg.get("fromMe", False)
            if from_me:
                sender = "Tú"
            else:
                # For group messages, 'author' or 'participant' holds the individual sender's JID
                author_jid = msg.get("author") or msg.get("participant") or ""
                notify_name = (
                    msg.get("_data", {}).get("notifyName")
                    or msg.get("notifyName")
                    or ""
                )
                if notify_name:
                    sender = notify_name
                elif author_jid:
                    sender = author_jid.replace("@c.us", "").replace("@s.whatsapp.net", "")
                else:
                    sender = phone_or_name.split()[0]

            ts = msg.get("timestamp", "")
            if ts:
                dt = datetime.datetime.fromtimestamp(ts, tz=tz_info).strftime("%d %b %H:%M")
            else:
                dt = ""

            # Detect audio — WAHA is inconsistent: sometimes omits type, hasMedia, or both.
            # Use all available signals: type, _data.type, mimetype, and hasMedia+empty-body.
            nested_type = msg.get("_data", {}).get("type", "")
            effective_type = msg_type or nested_type
            mimetype = (
                msg.get("mimetype", "")
                or msg.get("_data", {}).get("mimetype", "")
            ).lower()
            is_audio = (
                effective_type in ("ptt", "audio")
                or "audio" in mimetype
                or (
                    has_media
                    and not (msg.get("body") or msg.get("caption"))
                    and effective_type not in ("image", "video", "document", "sticker")
                    and "image" not in mimetype
                    and "video" not in mimetype
                )
            )
            logger.debug(
                f"[WhatsApp] msg type={msg_type!r} nested={nested_type!r} "
                f"mimetype={mimetype!r} hasMedia={has_media} is_audio={is_audio}"
            )

            # Audio / voice note
            if is_audio:
                if has_media and transcriber:
                    msg_id    = msg.get("id", "")
                    media_url = msg.get("mediaUrl") or msg.get("_data", {}).get("mediaUrl")

                    audio_bytes = None
                    if media_url:
                        try:
                            audio_resp = requests.get(media_url, headers=_headers(api_key), timeout=_REQUEST_TIMEOUT)
                            audio_resp.raise_for_status()
                            audio_bytes = audio_resp.content
                        except Exception as e:
                            logger.warning(f"[WhatsApp] Direct mediaUrl download failed: {e}")

                    if not audio_bytes and msg_id:
                        audio_bytes = _download_media(waha_url, msg_id, session, api_key)

                    if audio_bytes:
                        filename = "voice.ogg" if msg_type == "ptt" else "audio.ogg"
                        text = transcriber(groq_api_key, audio_bytes, filename)
                        body = f"[Audio] {text}" if not text.startswith("ERROR:") else "[audio — no se pudo transcribir]"
                    else:
                        body = "[audio — no se pudo descargar]"
                elif has_media:
                    body = "[audio — no hay clave Groq para transcribir]"
                else:
                    body = "[nota de voz]"

            else:
                body = msg.get("body") or msg.get("caption") or (f"[{msg_type}]" if msg_type else "[media]")

            lines.append(f"[{dt}] {sender}: {body[:200]}")

        return f"Últimos {len(lines)} mensajes con '{phone_or_name}':\n\n" + "\n".join(lines)

    except Exception as e:
        logger.exception(f"[WhatsApp] Error reading history for {chat_id}: {e}")
        return f"Error al leer el historial de WhatsApp: {e}"
