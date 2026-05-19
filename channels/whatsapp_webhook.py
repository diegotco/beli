"""
channels/whatsapp_webhook.py - Handles incoming WhatsApp messages from WAHA.

WAHA sends a POST webhook to /whatsapp/webhook for every incoming event.
This module parses the payload, optionally transcribes audio, and notifies
the owner via Telegram.

The owner can then reply by telling @IamBeliBot:
  "respóndele por WhatsApp a [name]: [message]"
"""
import logging

import requests

logger = logging.getLogger("beli.whatsapp.webhook")

_REQUEST_TIMEOUT = 30


# ── Helpers ───────────────────────────────────────────────────────────────────

def _download_media_by_id(waha_url: str, message_id: str, session: str, api_key: str) -> bytes | None:
    """Downloads media bytes for a WAHA message ID. Returns None on failure."""
    try:
        url  = f"{waha_url.rstrip('/')}/api/{session}/messages/{message_id}/download"
        hdrs = {"X-Api-Key": api_key} if api_key else {}
        resp = requests.get(url, headers=hdrs, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.warning(f"[WhatsApp] Media download failed for {message_id}: {e}")
        return None


def _transcribe(groq_api_key: str, audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Transcribes audio bytes via Groq Whisper. Returns text or error string."""
    try:
        from tools.transcriber import transcribe_audio
        return transcribe_audio(groq_api_key, audio_bytes, filename)
    except Exception as e:
        return f"ERROR: {e}"


def _get_group_name(waha_url: str, session: str, api_key: str, group_id: str) -> str | None:
    """Fetches the group name from WAHA using the /groups/{id} endpoint.

    The /chats/{id} endpoint does not support individual lookup and returns 404.
    /groups/{id} is the correct endpoint and returns the 'subject' field.
    """
    try:
        url  = f"{waha_url.rstrip('/')}/api/{session}/groups/{group_id}"
        hdrs = {"X-Api-Key": api_key} if api_key else {}
        resp = requests.get(url, headers=hdrs, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("subject") or data.get("name") or None
    except Exception as e:
        logger.warning(f"[WhatsApp] Could not fetch group name for {group_id}: {e}")
        return None


def _send_telegram(token: str, chat_id: int, text: str) -> None:
    """Sends a Telegram message synchronously via Bot API (no asyncio)."""
    try:
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(f"[WhatsApp] Owner notified via Telegram (chat_id={chat_id})")
    except Exception as e:
        logger.error(f"[WhatsApp] Failed to notify owner via Telegram: {e}")


# ── Main handler ──────────────────────────────────────────────────────────────

def handle_webhook(
    payload: dict,
    bot_token: str,
    owner_chat_id: int,
    waha_url: str = "",
    waha_session: str = "default",
    waha_api_key: str = "",
    groq_api_key: str = "",
) -> None:
    """
    Processes a WAHA webhook payload and notifies the owner via Telegram.
    Called from the HTTP server thread — must be synchronous.

    Supports:
      - Text messages
      - Voice notes / audio (transcribed via Groq Whisper if key is set)
      - Images (noted as [imagen])
      - Other media (noted as [media])
    """
    try:
        event = payload.get("event", "")

        # Only handle incoming messages
        if event not in ("message", "message.any"):
            return

        msg     = payload.get("payload", {})
        from_me = msg.get("fromMe", False)

        # Ignore messages sent by the owner
        if from_me:
            return

        chat_id     = msg.get("chatId", "") or msg.get("from", "")
        msg_type    = msg.get("type", "")
        has_media   = msg.get("hasMedia", False)
        msg_id      = msg.get("id", "")
        is_group    = chat_id.endswith("@g.us")

        # Filter out WhatsApp system broadcasts (status updates, etc.)
        if chat_id.startswith("status@") or chat_id == "status@broadcast":
            return

        # For group messages the individual sender is in 'author' or 'from';
        # 'chatId' is the group ID, not the sender.
        sender_jid = (
            msg.get("author")
            or msg.get("from")
            or (chat_id if not is_group else "")
        )
        sender_name = (
            msg.get("_data", {}).get("notifyName")
            or msg.get("notifyName")
            or sender_jid.replace("@c.us", "").replace("@g.us", "")
            or "Desconocido"
        )

        # For groups, try to resolve the group name via WAHA API
        group_name = None
        if is_group and waha_url:
            group_name = (
                msg.get("_data", {}).get("chat", {}).get("name")
                or msg.get("_data", {}).get("subject")
                or _get_group_name(waha_url, waha_session, waha_api_key, chat_id)
            )

        if is_group:
            channel_label = f"WhatsApp Grupo: {group_name}" if group_name else "WhatsApp Grupo"
        else:
            channel_label = "WhatsApp"

        logger.info(f"[WhatsApp] Incoming {msg_type} from {sender_name} ({chat_id})")

        # ── Resolve message body ──────────────────────────────────────────────

        if msg_type in ("ptt", "audio") and has_media:
            # Voice note — try to transcribe
            audio_bytes = None

            # Try mediaUrl first
            media_url = msg.get("mediaUrl") or msg.get("_data", {}).get("mediaUrl")
            if media_url:
                try:
                    hdrs = {"X-Api-Key": waha_api_key} if waha_api_key else {}
                    r = requests.get(media_url, headers=hdrs, timeout=_REQUEST_TIMEOUT)
                    r.raise_for_status()
                    audio_bytes = r.content
                except Exception as e:
                    logger.warning(f"[WhatsApp] Direct mediaUrl failed: {e}")

            # Fallback to download endpoint
            if not audio_bytes and msg_id and waha_url:
                audio_bytes = _download_media_by_id(waha_url, msg_id, waha_session, waha_api_key)

            if audio_bytes and groq_api_key:
                text = _transcribe(groq_api_key, audio_bytes, "voice.ogg")
                if text.startswith("ERROR:"):
                    body = "[audio — no se pudo transcribir]"
                else:
                    body = f"[Audio] {text}"
            elif audio_bytes:
                body = "[audio — Groq no configurado]"
            else:
                body = "[audio — no se pudo descargar]"

        elif msg_type == "image" and has_media:
            caption = msg.get("caption") or ""
            body = f"[imagen]{' — ' + caption if caption else ''}"

        elif msg_type in ("document", "video", "sticker"):
            caption = msg.get("caption") or ""
            body = f"[{msg_type}]{' — ' + caption if caption else ''}"

        else:
            body = msg.get("body") or msg.get("text") or ""
            if not body:
                return  # Nothing useful to forward

        # ── Build and send notification ───────────────────────────────────────

        first_name = sender_name.split()[0] if sender_name else "esta persona"

        if is_group and group_name:
            notification = (
                f"WhatsApp Grupo: {group_name}\n"
                f"{sender_name}: {body}\n\n"
                f"Para responder: \"respóndele por WhatsApp en {group_name} a {first_name}: [tu mensaje]\""
            )
        elif is_group:
            notification = (
                f"WhatsApp Grupo\n"
                f"{sender_name}: {body}\n\n"
                f"Para responder: \"respóndele por WhatsApp a {first_name}: [tu mensaje]\""
            )
        else:
            notification = (
                f"Mensaje de {sender_name} por WhatsApp:\n\n"
                f"{body}\n\n"
                f"Para responder: \"respóndele por WhatsApp a {first_name}: [tu mensaje]\""
            )

        from settings.notifications import get_settings
        if not get_settings().should_notify_whatsapp(chat_id):
            logger.debug(f"[WhatsApp] Notifications disabled for {chat_id} — skipping.")
            return

        _send_telegram(bot_token, owner_chat_id, notification)

    except Exception as e:
        logger.exception(f"[WhatsApp] Error handling webhook: {e}")
