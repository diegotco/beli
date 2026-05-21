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
    from urllib.parse import quote
    try:
        # URL-encode the message ID — it contains @ and _ which need encoding
        encoded_id = quote(message_id, safe="")
        url = f"{waha_url.rstrip('/')}/api/{session}/messages/{encoded_id}/download"
        resp = requests.get(url, headers=_headers(api_key), timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.warning(f"[WhatsApp] Could not download media for message {message_id}: {e}")
        return None


async def read_whatsapp_chat_history(
    waha_url: str,
    phone_or_name: str,
    limit: int = 30,
    session: str = _DEFAULT_SESSION,
    api_key: str = "",
    timezone: str = "America/Mexico_City",
    groq_api_key: str = "",
    anthropic_api_key: str = "",
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

            # Timestamp: prefer _data.t (raw WhatsApp protocol time, most reliable),
            # then top-level timestamp. Avoid _data.messageTimestamp — unreliable for
            # outgoing messages (WAHA may stamp with cache time, not original send time).
            ts = msg.get("_data", {}).get("t") or msg.get("timestamp") or 0
            if ts:
                try:
                    if ts > 9_999_999_999:   # guard against ms timestamps
                        ts = ts // 1000
                    dt = datetime.datetime.fromtimestamp(ts, tz=tz_info).strftime("%d/%m/%Y %H:%M")
                except Exception:
                    dt = ""
            else:
                dt = ""

            # Detect audio — read mimetype from all available sources FIRST, then decide.
            nested_type = msg.get("_data", {}).get("type", "")
            effective_type = msg_type or nested_type
            media_obj = msg.get("media") or {}
            mimetype = (
                media_obj.get("mimetype", "")           # WAHA v2: media.mimetype
                or msg.get("mimetype", "")
                or msg.get("_data", {}).get("mimetype", "")
            ).lower()

            # Only use the hasMedia fallback if there's truly no type info AND
            # the mimetype doesn't indicate a non-audio media type.
            # This prevents images/videos with missing type from being flagged as audio.
            is_audio = (
                effective_type in ("ptt", "audio")
                or "audio" in mimetype
                # Conservative fallback: only when has_media, no body, AND
                # mimetype is explicitly empty (not just non-audio)
                or (
                    has_media
                    and not (msg.get("body") or msg.get("caption"))
                    and effective_type not in ("image", "video", "document", "sticker")
                    and mimetype == ""   # only if we truly have NO type info at all
                )
            )
            if not msg.get("body") and not msg.get("caption") and has_media:
                logger.info(
                    f"[WhatsApp] media msg — type={msg_type!r} nested={nested_type!r} "
                    f"mimetype={mimetype!r} is_audio={is_audio} media_keys={list(media_obj.keys())}"
                )

            # Audio / voice note
            if is_audio:
                if has_media and transcriber:
                    msg_id    = msg.get("id", "")
                    # media_obj already set above; try all URL locations
                    media_url = (
                        media_obj.get("url")
                        or msg.get("mediaUrl")
                        or msg.get("_data", {}).get("mediaUrl")
                    )

                    # WAHA running inside Docker often returns internal localhost URLs.
                    # Replace with the public WAHA base URL so we can actually reach it.
                    if media_url and (
                        media_url.startswith("/")
                        or "localhost" in media_url
                        or "127.0.0.1" in media_url
                    ):
                        import re as _re
                        if media_url.startswith("/"):
                            media_url = waha_url.rstrip("/") + media_url
                        else:
                            media_url = _re.sub(
                                r'https?://(?:localhost|127\.0\.0\.1)(?::\d+)?',
                                waha_url.rstrip("/"),
                                media_url,
                            )

                    # Full diagnostic dump for audio messages
                    import json as _json
                    logger.info(
                        f"[WhatsApp] AUDIO id={msg_id!r} "
                        f"ts_top={msg.get('timestamp')} ts_data_t={msg.get('_data',{}).get('t')} "
                        f"ts_data_msg={msg.get('_data',{}).get('messageTimestamp')} "
                        f"mediaUrl={media_url!r} media={_json.dumps(media_obj)[:400]}"
                    )

                    audio_bytes = None
                    if media_url:
                        try:
                            audio_resp = requests.get(media_url, headers=_headers(api_key), timeout=_REQUEST_TIMEOUT)
                            audio_resp.raise_for_status()
                            audio_bytes = audio_resp.content
                            logger.info(f"[WhatsApp] mediaUrl download OK — {len(audio_bytes)} bytes")
                        except Exception as e:
                            logger.warning(f"[WhatsApp] mediaUrl download failed ({media_url!r}): {e}")

                    if not audio_bytes and msg_id:
                        logger.info(f"[WhatsApp] Trying /download endpoint for msg_id={msg_id!r}")
                        audio_bytes = _download_media(waha_url, msg_id, session, api_key)
                        if audio_bytes:
                            logger.info(f"[WhatsApp] /download endpoint OK — {len(audio_bytes)} bytes")
                        else:
                            logger.warning(f"[WhatsApp] /download endpoint also failed for msg_id={msg_id!r}")

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
                # Image — download and describe via Claude Vision
                is_image = (
                    effective_type == "image"
                    or "image/" in mimetype
                )
                if is_image and has_media and anthropic_api_key:
                    img_url = (
                        media_obj.get("url")
                        or msg.get("mediaUrl")
                        or msg.get("_data", {}).get("mediaUrl")
                    )
                    # Fix localhost/relative URLs (same logic as audio)
                    if img_url and (
                        img_url.startswith("/")
                        or "localhost" in img_url
                        or "127.0.0.1" in img_url
                    ):
                        import re as _re2
                        if img_url.startswith("/"):
                            img_url = waha_url.rstrip("/") + img_url
                        else:
                            img_url = _re2.sub(
                                r'https?://(?:localhost|127\.0\.0\.1)(?::\d+)?',
                                waha_url.rstrip("/"),
                                img_url,
                            )

                    img_bytes = None
                    if img_url:
                        try:
                            img_resp = requests.get(img_url, headers=_headers(api_key), timeout=_REQUEST_TIMEOUT)
                            img_resp.raise_for_status()
                            img_bytes = img_resp.content
                        except Exception as e:
                            logger.warning(f"[WhatsApp] Image URL download failed: {e}")

                    if not img_bytes:
                        msg_id = msg.get("id", "")
                        if msg_id:
                            img_bytes = _download_media(waha_url, msg_id, session, api_key)

                    if img_bytes:
                        from tools.vision import describe_image
                        caption_text = msg.get("caption") or msg.get("body") or ""
                        description = await describe_image(anthropic_api_key, img_bytes, caption_text)
                        body = f"[Imagen] {description}"
                    else:
                        body = "[imagen — no se pudo descargar]"
                else:
                    body = msg.get("body") or msg.get("caption") or (f"[{msg_type}]" if msg_type else "[media]")

            lines.append(f"[{dt}] {sender}: {body[:2000]}")

        today_str = datetime.date.today().strftime("%d/%m/%Y")
        header = (
            f"Historial del chat con '{phone_or_name}' — "
            f"hoy es {today_str} (usa esta fecha para distinguir mensajes de hoy vs ayer).\n"
            f"Cada mensaje incluye [dd/mm/yyyy HH:MM]. Filtra por fecha cuando el owner pida mensajes de un día específico.\n"
        )
        return header + f"Últimos {len(lines)} mensajes:\n\n" + "\n".join(lines)

    except Exception as e:
        logger.exception(f"[WhatsApp] Error reading history for {chat_id}: {e}")
        return f"Error al leer el historial de WhatsApp: {e}"
