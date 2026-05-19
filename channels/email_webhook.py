"""
channels/email_webhook.py - Handles incoming emails forwarded by AgentMail.

AgentMail sends a POST to /email/webhook for every message.received event.
This module:
  1. Parses the payload
  2. Routes the email body through Beli's brain so she can act on it
  3. Sends Beli's response (and a brief header) to the owner via Telegram
"""
import asyncio
import logging

import requests

logger = logging.getLogger("beli.email.webhook")

CHANNEL = "telegram"  # share conversation context with the Telegram channel


def handle_email_webhook(
    payload: dict,
    bot_token: str,
    owner_chat_id: int,
    brain=None,
    memory=None,
) -> None:
    """
    Processes an AgentMail webhook payload.
    - Sends a brief header notification to the owner.
    - Routes the email body through Beli's brain so she can act on it.
    Called from the HTTP server thread — synchronous wrapper around async logic.
    """
    try:
        # Log the full payload for debugging (truncated to 500 chars)
        logger.info(f"[Email] Webhook received: {str(payload)[:500]}")

        # AgentMail may use 'event_type', 'type', or 'event' as the key
        event_type = (
            payload.get("event_type")
            or payload.get("type")
            or payload.get("event")
            or ""
        )

        # Only handle incoming messages
        if event_type and event_type != "message.received":
            logger.info(f"[Email] Ignoring event type: {event_type!r}")
            return

        # Message data may be nested under 'message' or at the top level
        message = payload.get("message") or payload

        # 'from' may be a string "Name <email>" or an object {"name": ..., "address": ...}
        raw_from = message.get("from") or message.get("sender") or "Desconocido"
        if isinstance(raw_from, dict):
            name  = raw_from.get("name") or ""
            addr  = raw_from.get("address") or raw_from.get("email") or ""
            sender = f"{name} <{addr}>".strip(" <>") if name else addr or "Desconocido"
        else:
            sender = str(raw_from)

        subject = message.get("subject") or "(sin asunto)"
        body    = (
            message.get("text")
            or message.get("body")
            or message.get("extracted_text")
            or message.get("preview")
            or ""
        ).strip()

        logger.info(f"[Email] Incoming from {sender} | Subject: {subject}")

        # Brief header so the owner knows an email triggered this
        header = f"Correo de {sender} | Asunto: {subject}"
        _send_telegram(bot_token, owner_chat_id, header)

        # Route through Beli's brain if available
        if brain and memory and body:
            asyncio.run(_process_with_brain(
                brain, memory, owner_chat_id,
                sender, subject, body, bot_token,
            ))
        elif body:
            # Fallback: no brain — show body and suggest reply
            sender_name = sender.split("<")[0].strip().strip('"') or sender
            preview = body[:500] + ("…" if len(body) > 500 else "")
            _send_telegram(
                bot_token, owner_chat_id,
                f"{preview}\n\nPara responder: \"responde el correo de {sender_name}: [tu mensaje]\"",
            )

    except Exception as e:
        logger.exception(f"[Email] Error handling webhook: {e}")


async def _process_with_brain(brain, memory, owner_chat_id, sender, subject, body, bot_token):
    """Runs Beli's brain on the email body and sends the response to the owner."""
    try:
        from personality import get_system_prompt

        history = await memory.get_history(CHANNEL, owner_chat_id)
        facts   = await memory.get_facts(CHANNEL, owner_chat_id)

        system_prompt = get_system_prompt(extra_context=facts)

        # Present the email as a message from the owner
        email_message = (
            f"[Email recibido de {sender} — Asunto: {subject}]\n\n"
            f"{body}"
        )

        response = await brain.think(
            system_prompt=system_prompt,
            history=history,
            new_message=email_message,
            max_tokens=1024,
        )

        # Persist in conversation memory so context carries forward
        await memory.save_message(CHANNEL, owner_chat_id, "user",      email_message)
        await memory.save_message(CHANNEL, owner_chat_id, "assistant", response)

        _send_telegram(bot_token, owner_chat_id, response)
        logger.info("[Email] Brain response sent to owner.")

    except Exception as e:
        logger.exception(f"[Email] Brain processing failed: {e}")


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
