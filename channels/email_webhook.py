"""
channels/email_webhook.py - Handles incoming emails forwarded by AgentMail.

AgentMail sends a POST to /email/webhook for every message.received event.
This module parses the payload and notifies the owner via Telegram.

The owner can then reply by telling Beli:
  "responde el correo de [name] sobre [subject]: [mensaje]"
"""
import logging

import requests

logger = logging.getLogger("beli.email.webhook")


def handle_email_webhook(
    payload: dict,
    bot_token: str,
    owner_chat_id: int,
) -> None:
    """
    Processes an AgentMail webhook payload and notifies the owner via Telegram.
    Called from the HTTP server thread — must be synchronous.
    """
    try:
        event_type = payload.get("event_type", "")

        # Only handle incoming messages
        if event_type != "message.received":
            logger.debug(f"[Email] Ignoring event type: {event_type}")
            return

        message = payload.get("message", {})

        sender  = message.get("from", "Desconocido")
        subject = message.get("subject") or "(sin asunto)"
        # Prefer full text; fall back to preview
        body    = (
            message.get("text")
            or message.get("extracted_text")
            or message.get("preview")
            or ""
        ).strip()

        # Trim long bodies
        preview = body[:500] + ("…" if len(body) > 500 else "")

        # Extract display name from "Name <email@...>" format
        sender_name = sender.split("<")[0].strip().strip('"') or sender

        logger.info(f"[Email] Incoming from {sender} | Subject: {subject}")

        notification = (
            f"Nuevo correo de {sender}\n"
            f"Asunto: {subject}\n\n"
            f"{preview}\n\n"
            f"Para responder: \"responde el correo de {sender_name}: [tu mensaje]\""
        )

        _send_telegram(bot_token, owner_chat_id, notification)

    except Exception as e:
        logger.exception(f"[Email] Error handling webhook: {e}")


def _send_telegram(token: str, chat_id: int, text: str) -> None:
    """Sends a Telegram message synchronously via Bot API."""
    try:
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(f"[Email] Owner notified via Telegram (chat_id={chat_id})")
    except Exception as e:
        logger.error(f"[Email] Failed to notify owner: {e}")


def register_webhook(api_key: str, inbox_id: str, webhook_url: str) -> None:
    """
    Ensures the AgentMail webhook is registered for this inbox.
    Safe to call at startup — skips if the URL is already registered.
    """
    if not api_key or not webhook_url:
        return

    base = "https://api.agentmail.to/v0"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        # List existing webhooks
        resp = requests.get(f"{base}/webhooks", headers=headers, timeout=10)
        resp.raise_for_status()
        existing = resp.json() if isinstance(resp.json(), list) else resp.json().get("webhooks", [])

        target = webhook_url.rstrip("/")
        for wh in existing:
            if wh.get("url", "").rstrip("/") == target:
                logger.info(f"[Email] Webhook already registered: {target}")
                return

        # Register new webhook
        payload = {
            "url": webhook_url,
            "event_types": ["message.received"],
        }
        resp2 = requests.post(f"{base}/webhooks", json=payload, headers=headers, timeout=10)
        if resp2.status_code in (200, 201):
            logger.info(f"[Email] Webhook registered successfully: {webhook_url}")
        else:
            logger.warning(f"[Email] Webhook registration returned {resp2.status_code}: {resp2.text}")

    except Exception as e:
        logger.warning(f"[Email] Could not register webhook: {e}")
