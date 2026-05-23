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

        import asyncio as _asyncio
        import re as _re
        import json as _json

        # Lazy-import transcriber
        transcriber = None
        if groq_api_key:
            try:
                from tools.transcriber import transcribe_audio
                transcriber = transcribe_audio
            except ImportError:
                logger.warning("[WhatsApp] transcriber module not available")

        def _fix_url(url: str) -> str:
            """Replace WAHA-internal localhost URLs with the public WAHA base URL."""
            if not url:
                return url
            if url.startswith("/"):
                return waha_url.rstrip("/") + url
            if "localhost" in url or "127.0.0.1" in url:
                return _re.sub(
                    r'https?://(?:localhost|127\.0\.0\.1)(?::\d+)?',
                    waha_url.rstrip("/"),
                    url,
                )
            return url

        def _get_media_bytes(msg: dict, media_obj: dict) -> bytes | None:
            """Downloads media bytes: tries direct URL first, then /download endpoint."""
            raw_url = (
                media_obj.get("url")
                or msg.get("mediaUrl")
                or msg.get("_data", {}).get("mediaUrl")
            )
            media_url = _fix_url(raw_url)

            if media_url:
                try:
                    r = requests.get(media_url, headers=_headers(api_key), timeout=_REQUEST_TIMEOUT)
                    r.raise_for_status()
                    return r.content
                except Exception as e:
                    logger.warning(f"[WhatsApp] Direct URL download failed ({media_url!r}): {e}")

            msg_id = msg.get("id", "")
            if msg_id:
                return _download_media(waha_url, msg_id, session, api_key)
            return None

        async def _process_msg(msg: dict) -> str:
            """Processes one WAHA message into a formatted '[dt] sender: body' string."""
            msg_type  = msg.get("type", "")
            has_media = msg.get("hasMedia", False)
            from_me   = msg.get("fromMe", False)

            # ── Sender ───────────────────────────────────────────────────────
            if from_me:
                sender = "Tú"
            else:
                author_jid  = msg.get("author") or msg.get("participant") or ""
                notify_name = (
                    msg.get("_data", {}).get("notifyName")
                    or msg.get("notifyName") or ""
                )
                if notify_name:
                    sender = notify_name
                elif author_jid:
                    sender = author_jid.replace("@c.us", "").replace("@s.whatsapp.net", "")
                else:
                    sender = phone_or_name.split()[0]

            # ── Timestamp ────────────────────────────────────────────────────
            # Prefer the top-level WAHA 'timestamp' field (guaranteed UTC Unix
            # seconds) over the internal '_data.t' field (same value but WAHA
            # sometimes omits it or gives a local-time value in older builds).
            ts_raw = msg.get("timestamp") or msg.get("_data", {}).get("t") or 0
            dt = ""
            if ts_raw:
                try:
                    # Handle both integer Unix timestamps and ISO 8601 strings
                    if isinstance(ts_raw, str):
                        # e.g. "2026-05-20T17:49:00.000Z" — parse as UTC then convert
                        import re as _re2
                        clean = _re2.sub(r'\.\d+', '', ts_raw).replace("Z", "+00:00")
                        ts_dt = datetime.datetime.fromisoformat(clean).astimezone(tz_info)
                        dt = ts_dt.strftime("%d/%m/%Y %H:%M")
                    else:
                        ts = int(ts_raw)
                        if ts > 9_999_999_999:
                            ts = ts // 1000
                        dt = datetime.datetime.fromtimestamp(ts, tz=tz_info).strftime("%d/%m/%Y %H:%M")
                except Exception:
                    dt = ""

            # ── Media type detection ─────────────────────────────────────────
            nested_type    = msg.get("_data", {}).get("type", "")
            effective_type = msg_type or nested_type
            media_obj      = msg.get("media") or {}
            mimetype       = (
                media_obj.get("mimetype", "")
                or msg.get("mimetype", "")
                or msg.get("_data", {}).get("mimetype", "")
            ).lower()

            is_audio = (
                effective_type in ("ptt", "audio")
                or "audio" in mimetype
                or (
                    has_media
                    and not (msg.get("body") or msg.get("caption"))
                    and effective_type not in ("image", "video", "document", "sticker")
                    and mimetype == ""
                )
            )
            is_image = not is_audio and (
                effective_type == "image" or "image/" in mimetype
            )

            if not msg.get("body") and not msg.get("caption") and has_media:
                logger.info(
                    f"[WhatsApp] media — type={msg_type!r} nested={nested_type!r} "
                    f"mimetype={mimetype!r} is_audio={is_audio} is_image={is_image}"
                )

            # ── Body ─────────────────────────────────────────────────────────
            if is_audio:
                if has_media and transcriber:
                    logger.info(
                        f"[WhatsApp] AUDIO id={msg.get('id','')!r} "
                        f"ts_top={msg.get('timestamp')} ts_data_t={msg.get('_data',{}).get('t')} "
                        f"media={_json.dumps(media_obj)[:200]}"
                    )
                    audio_bytes = _get_media_bytes(msg, media_obj)
                    if audio_bytes:
                        filename = "voice.ogg" if msg_type == "ptt" else "audio.ogg"
                        text = transcriber(groq_api_key, audio_bytes, filename)
                        body = f"[Audio] {text}" if not text.startswith("ERROR:") else "[audio — no se pudo transcribir]"
                    else:
                        body = "[audio — no se pudo descargar]"
                elif has_media:
                    body = "[audio — falta clave Groq]"
                else:
                    body = "[nota de voz]"

            elif is_image:
                if has_media and anthropic_api_key:
                    img_bytes = _get_media_bytes(msg, media_obj)
                    if img_bytes:
                        from tools.vision import describe_image
                        caption_text = msg.get("caption") or msg.get("body") or ""
                        description = await describe_image(anthropic_api_key, img_bytes, caption_text)
                        body = f"[Imagen] {description}"
                    else:
                        body = "[imagen — no se pudo descargar]"
                else:
                    caption_text = msg.get("caption") or msg.get("body") or ""
                    body = f"[imagen{': ' + caption_text if caption_text else ''}]"

            else:
                body = msg.get("body") or msg.get("caption") or (f"[{msg_type}]" if msg_type else "[media]")

            return f"[{dt}] {sender}: {body[:2000]}"

        # Process all messages concurrently (audio + image in parallel)
        results = await _asyncio.gather(*[_process_msg(msg) for msg in reversed(messages)])
        lines = list(results)

        today_str = datetime.datetime.now(tz=tz_info).strftime("%d/%m/%Y")
        total = len(lines)

        # ── Pre-compute last-3 per sender (put at the TOP so Claude reads it first) ──
        from collections import defaultdict
        sender_msgs: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for i, line in enumerate(lines, 1):
            if "] " in line:
                rest = line.split("] ", 1)[1]
                if ": " in rest:
                    sender_name = rest.split(": ", 1)[0]
                    sender_msgs[sender_name].append((i, line))

        summary_parts = [
            "╔══ ÚLTIMOS MENSAJES POR REMITENTE ══╗",
            "(Usa esta sección para responder preguntas sobre los últimos N mensajes de alguien.)",
        ]
        for sender, msgs in sorted(sender_msgs.items()):
            last3 = msgs[-3:]
            summary_parts.append(
                f"\n{sender} — últimos {min(3, len(msgs))} de {len(msgs)} mensajes (el más reciente al final):"
            )
            for num, m in last3:
                summary_parts.append(f"  [#{num}/{total}] {m}")
        summary_parts.append("╚══════════════════════════════════╝\n")
        summary_str = "\n".join(summary_parts) + "\n"

        # ── Numbered full history ─────────────────────────────────────────────────
        header = (
            f"Historial completo de WhatsApp con '{phone_or_name}' — hoy es {today_str}. "
            f"{total} mensajes en ORDEN CRONOLÓGICO (el más antiguo primero = #1, el más reciente = #{total}).\n"
            f"Cada línea: [#N/{total}] [dd/mm/YYYY HH:MM] Remitente: mensaje\n"
        )
        numbered = [f"[#{i}/{total}] {line}" for i, line in enumerate(lines, 1)]

        return summary_str + header + "\n".join(numbered)

    except Exception as e:
        logger.exception(f"[WhatsApp] Error reading history for {chat_id}: {e}")
        return f"Error al leer el historial de WhatsApp: {e}"


# ── Tool 4: Edit a sent WhatsApp message ──────────────────────────────────────

def edit_whatsapp_message(
    waha_url: str,
    phone_or_name: str,
    message_text: str,
    new_text: str,
    session: str = _DEFAULT_SESSION,
    api_key: str = "",
) -> str:
    """
    Edits the most recent outgoing WhatsApp message that matches message_text.

    Args:
        waha_url:     Base URL of the WAHA service
        phone_or_name: Contact name or phone number identifying the chat
        message_text: Snippet of the sent message to find and edit
        new_text:     New text to replace it with
        session:      WAHA session name
        api_key:      WAHA API key
    """
    chat_id, display_label = _resolve_chat_id(waha_url, phone_or_name, session, api_key)
    if chat_id is None:
        return f"Error: {display_label}"

    # Fetch recent messages to locate the one to edit
    try:
        resp = requests.get(
            f"{waha_url.rstrip('/')}/api/{session}/chats/{chat_id}/messages",
            params={"limit": 50},
            headers=_headers(api_key),
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        messages = resp.json()
    except Exception as e:
        return f"Error al obtener mensajes para editar: {e}"

    # Find outgoing messages matching the snippet (most recent first — list order)
    snippet_lower = message_text.lower()
    candidates = [
        m for m in messages
        if m.get("fromMe") and (m.get("body") or m.get("caption") or "").lower().find(snippet_lower) != -1
    ]

    if not candidates:
        return f"No encontré ningún mensaje tuyo que contenga '{message_text}' en el chat con {display_label}."

    if len(candidates) > 1:
        previews = "\n".join(f"- \"{(m.get('body') or m.get('caption') or '')[:80]}\"" for m in candidates[:5])
        return (
            f"Encontré {len(candidates)} mensajes tuyos con '{message_text}':\n{previews}\n"
            "Sé más específico para que pueda editar el correcto."
        )

    target = candidates[0]
    msg_id = target.get("id", "")
    if not msg_id:
        return "No se pudo obtener el ID del mensaje para editarlo."

    try:
        from urllib.parse import quote
        encoded_id = quote(msg_id, safe="")
        edit_resp = requests.put(
            f"{waha_url.rstrip('/')}/api/{session}/chats/{chat_id}/messages/{encoded_id}",
            json={"text": new_text},
            headers=_headers(api_key),
            timeout=_REQUEST_TIMEOUT,
        )
        edit_resp.raise_for_status()
        logger.info(f"[WhatsApp] Edited message {msg_id} in '{display_label}'")
        return f"Mensaje editado en {display_label}. Nuevo texto: \"{new_text}\""
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("message", e.response.text)
        except Exception:
            detail = str(e)
        return f"Error al editar el mensaje de WhatsApp: {detail}"
    except Exception as e:
        logger.exception(f"[WhatsApp] Error editing message in '{display_label}': {e}")
        return f"Error al editar el mensaje de WhatsApp: {e}"


# ── Tool 5: Delete a sent WhatsApp message ────────────────────────────────────

def delete_whatsapp_message(
    waha_url: str,
    phone_or_name: str,
    message_text: str,
    delete_for_everyone: bool = True,
    session: str = _DEFAULT_SESSION,
    api_key: str = "",
) -> str:
    """
    Deletes the most recent outgoing WhatsApp message that matches message_text.

    Args:
        waha_url:            Base URL of the WAHA service
        phone_or_name:       Contact name or phone number identifying the chat
        message_text:        Snippet of the sent message to find and delete
        delete_for_everyone: True = delete for everyone (default), False = delete only locally
        session:             WAHA session name
        api_key:             WAHA API key
    """
    chat_id, display_label = _resolve_chat_id(waha_url, phone_or_name, session, api_key)
    if chat_id is None:
        return f"Error: {display_label}"

    # Fetch recent messages
    try:
        resp = requests.get(
            f"{waha_url.rstrip('/')}/api/{session}/chats/{chat_id}/messages",
            params={"limit": 50},
            headers=_headers(api_key),
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        messages = resp.json()
    except Exception as e:
        return f"Error al obtener mensajes para eliminar: {e}"

    snippet_lower = message_text.lower()
    candidates = [
        m for m in messages
        if m.get("fromMe") and (m.get("body") or m.get("caption") or "").lower().find(snippet_lower) != -1
    ]

    if not candidates:
        return f"No encontré ningún mensaje tuyo que contenga '{message_text}' en el chat con {display_label}."

    if len(candidates) > 1:
        previews = "\n".join(f"- \"{(m.get('body') or m.get('caption') or '')[:80]}\"" for m in candidates[:5])
        return (
            f"Encontré {len(candidates)} mensajes tuyos con '{message_text}':\n{previews}\n"
            "Sé más específico para que pueda borrar el correcto."
        )

    target = candidates[0]
    msg_id = target.get("id", "")
    original_text = (target.get("body") or target.get("caption") or "")[:80]
    if not msg_id:
        return "No se pudo obtener el ID del mensaje para eliminarlo."

    try:
        from urllib.parse import quote
        encoded_id = quote(msg_id, safe="")
        del_resp = requests.delete(
            f"{waha_url.rstrip('/')}/api/{session}/chats/{chat_id}/messages/{encoded_id}",
            params={"deleteForEveryone": "true" if delete_for_everyone else "false"},
            headers=_headers(api_key),
            timeout=_REQUEST_TIMEOUT,
        )
        del_resp.raise_for_status()
        scope = "para todos" if delete_for_everyone else "solo para ti"
        logger.info(f"[WhatsApp] Deleted message {msg_id} in '{display_label}' (for_everyone={delete_for_everyone})")
        return f"Mensaje eliminado {scope} en {display_label}. Texto eliminado: \"{original_text}\""
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("message", e.response.text)
        except Exception:
            detail = str(e)
        return f"Error al eliminar el mensaje de WhatsApp: {detail}"
    except Exception as e:
        logger.exception(f"[WhatsApp] Error deleting message in '{display_label}': {e}")
        return f"Error al eliminar el mensaje de WhatsApp: {e}"
