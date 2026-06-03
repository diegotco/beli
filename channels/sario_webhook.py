"""
channels/sario_webhook.py - Handles incoming messages from SARIO via webhook.

SARIO sends a POST to /sario/webhook for every message in threads where
Beli is a member. This module:
  1. Verifies the HMAC-SHA256 signature
  2. Ignores ping events
  3. Passes the message through Beli's brain
  4. Replies via POST /api/messages
  5. Notifies the owner via Telegram

Webhook registration: PUT https://chat.b3li.io/api/agent/webhook
  Body: {"url": "https://your-app.railway.app/sario/webhook"}
  Response: {"url": "...", "secret": "whsec_..."}  ← store as SARIO_WEBHOOK_SECRET
"""
import asyncio
import hashlib
import hmac
import logging

import requests

logger = logging.getLogger("beli.sario.webhook")

_SARIO_BASE = "https://chat.b3li.io"
CHANNEL = "sario"


# ── Signature verification ────────────────────────────────────────────────────

def _valid_signature(raw_body: bytes, header: str | None, secret: str) -> bool:
    if not header or not secret:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header)


# ── Send reply to SARIO ───────────────────────────────────────────────────────

def _send_sario_reply(api_key: str, thread_id: str, body: str, event_id: str) -> None:
    try:
        resp = requests.post(
            f"{_SARIO_BASE}/api/messages",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"threadId": thread_id, "body": body, "eventId": event_id},
            timeout=15,
        )
        resp.raise_for_status()
        logger.info(f"[SARIO] Reply sent to thread {thread_id}")
    except Exception as e:
        logger.error(f"[SARIO] Failed to send reply: {e}")


# ── Brain processing ──────────────────────────────────────────────────────────

async def _process_message(
    brain,
    memory,
    owner_chat_id: int,
    bot_token: str,
    sario_api_key: str,
    task: dict,
    thread_title: str,
) -> None:
    thread_id    = task.get("threadId", "")
    event_id     = task.get("eventId", "")
    message_text = task.get("messageToAnswer", "")
    sender       = task.get("messageFrom", "?")

    if not message_text:
        return

    logger.info(f"[SARIO] New message from {sender} in '{thread_title}': {message_text[:80]}")

    # Build conversation history for this SARIO thread
    history = await memory.get_history(CHANNEL, thread_id)

    # Context note so Beli knows she's in a SARIO chat
    context = (
        f"[Estás respondiendo un mensaje en SARIO — chat '{thread_title}'. "
        f"El usuario '{sender}' te escribió. Responde de forma natural y concisa.]"
    )

    try:
        from personality import get_system_prompt
        system = get_system_prompt(extra_context=context)
        reply = await brain.think(
            system_prompt=system,
            history=history,
            new_message=message_text,
            max_tokens=1024,
        )
    except Exception as e:
        logger.error(f"[SARIO] Brain error: {e}")
        reply = "Lo siento, ocurrió un error al procesar tu mensaje."

    # Save to memory
    await memory.save_message(CHANNEL, thread_id, "user", f"{sender}: {message_text}")
    await memory.save_message(CHANNEL, thread_id, "assistant", reply)

    # Send reply to SARIO
    _send_sario_reply(sario_api_key, thread_id, reply, event_id)

    # Notify owner on Telegram
    if owner_chat_id and bot_token:
        try:
            note = (
                f"💬 *SARIO* — {thread_title}\n"
                f"*{sender}:* {message_text}\n\n"
                f"*Beli respondió:* {reply}"
            )
            requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": owner_chat_id,
                    "text": note,
                    "parse_mode": "Markdown",
                },
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"[SARIO] Telegram notification failed: {e}")


def _run_async(brain, memory, owner_chat_id, bot_token, sario_api_key, task, thread_title):
    from channels.loop_ref import get_loop
    coro = _process_message(
        brain, memory, owner_chat_id, bot_token, sario_api_key, task, thread_title
    )
    loop = get_loop()
    if loop and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        def _on_done(f):
            exc = f.exception()
            if exc:
                logger.error(f"[SARIO] Processing raised: {exc}", exc_info=exc)
        future.add_done_callback(_on_done)
    else:
        logger.warning("[SARIO] PTB loop not available — falling back to asyncio.run()")
        asyncio.run(coro)


# ── Main webhook handler ──────────────────────────────────────────────────────

def handle_sario_webhook(
    payload: dict,
    raw_body: bytes,
    signature_header: str,
    webhook_secret: str,
    sario_api_key: str,
    bot_token: str,
    owner_chat_id: int,
    brain=None,
    memory=None,
) -> None:
    # Verify signature
    if webhook_secret and not _valid_signature(raw_body, signature_header, webhook_secret):
        logger.warning("[SARIO] Invalid webhook signature — ignoring.")
        return

    event_type   = payload.get("type", "")
    thread_title = payload.get("threadTitle", "SARIO")

    # Ping — just acknowledge, no action needed
    if event_type == "ping":
        logger.info("[SARIO] Ping received ✓")
        return

    if event_type == "message.created":
        task = payload.get("nextTask")
        if not task:
            logger.info("[SARIO] message.created with no nextTask — skipping.")
            return

        import threading
        threading.Thread(
            target=_run_async,
            args=(brain, memory, owner_chat_id, bot_token, sario_api_key, task, thread_title),
            daemon=True,
        ).start()
    else:
        logger.info(f"[SARIO] Unknown event type: {event_type}")


# ── Webhook registration ──────────────────────────────────────────────────────

def register_sario_webhook(api_key: str, public_url: str) -> str | None:
    """
    Registers Beli's webhook with SARIO.
    Returns the webhook secret (store as SARIO_WEBHOOK_SECRET).
    """
    webhook_url = f"{public_url.rstrip('/')}/sario/webhook"
    try:
        resp = requests.put(
            f"{_SARIO_BASE}/api/agent/webhook",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"url": webhook_url},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        secret = data.get("secret", "")
        logger.info(f"[SARIO] Webhook registered: {webhook_url}")
        if secret:
            logger.info(f"[SARIO] Webhook secret: {secret} — add as SARIO_WEBHOOK_SECRET in Railway.")
        return secret
    except Exception as e:
        logger.error(f"[SARIO] Failed to register webhook: {e}")
        return None
