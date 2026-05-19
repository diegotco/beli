"""
channels/whatsapp_webhook.py - Handles incoming WhatsApp messages from WAHA.

WAHA sends a POST webhook to /whatsapp/webhook for every incoming event.
This module parses the payload and notifies the owner via Telegram Bot API.

Notification format mirrors Telegram's BeliListener — owner can reply by
telling @IamBeliBot: "respóndele por WhatsApp a [name]: [message]"
"""
import json
import logging

import requests

logger = logging.getLogger("beli.whatsapp.webhook")


def handle_webhook(payload: dict, bot_token: str, owner_chat_id: int) -> None:
    """
    Processes a WAHA webhook payload and notifies the owner via Telegram.

    Called from the HTTP server thread — must be synchronous.
    Uses Telegram Bot API directly (no asyncio needed).
    """
    try:
        event = payload.get("event", "")

        # Only handle incoming text messages (ignore status updates, etc.)
        if event not in ("message", "message.any"):
            return

        msg     = payload.get("payload", {})
        from_me = msg.get("fromMe", False)

        # Ignore messages sent by the owner
        if from_me:
            return

        chat_id      = msg.get("chatId", "") or msg.get("from", "")
        body         = msg.get("body") or msg.get("text") or ""
        sender_name  = (
            msg.get("_data", {}).get("notifyName")
            or msg.get("notifyName")
            or chat_id.replace("@c.us", "").replace("@g.us", "")
            or "Desconocido"
        )
        is_group     = chat_id.endswith("@g.us")
        channel_label = "WhatsApp Grupo" if is_group else "WhatsApp"

        if not body:
            return  # Skip media-only messages for now

        logger.info(f"[WhatsApp] Incoming from {sender_name} ({chat_id}): {body[:80]}")

        first_name = sender_name.split()[0] if sender_name else "esta persona"
        chat_id_display = chat_id.replace("@c.us", "").replace("@g.us", "")

        notification = (
            f"📱 *{sender_name}* te escribió por {channel_label}:\n\n"
            f"{body}\n\n"
            f"💬 _Para responder: \"respóndele por WhatsApp a {first_name}: [tu mensaje]\"_\n"
            f"_(chat\\_id: `{chat_id_display}`)_"
        )

        _send_telegram(bot_token, owner_chat_id, notification)

    except Exception as e:
        logger.exception(f"[WhatsApp] Error handling webhook: {e}")


def _send_telegram(token: str, chat_id: int, text: str) -> None:
    """Sends a Telegram message synchronously via Bot API (no asyncio)."""
    try:
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(f"[WhatsApp] Owner notified via Telegram (chat_id={chat_id})")
    except Exception as e:
        logger.error(f"[WhatsApp] Failed to notify owner via Telegram: {e}")
