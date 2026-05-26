"""
channels/payg0_webhook.py - Handles incoming Payg0 payment events.

Payg0 sends a POST to /payg0/webhook for each payment event.
This module verifies the HMAC signature, parses the event,
and notifies the owner via Telegram.
"""
import hashlib
import hmac
import json
import logging

import requests

logger = logging.getLogger("beli.payg0.webhook")

_EMOJI = {
    "payment.received":   "💰",
    "payment.completed":  "💸",
    "payment.pending":    "⏳",
    "payment.failed":     "❌",
    "payment.cancelled":  "🚫",
    "payment.expired":    "⌛",
}

_EVENT_LABEL = {
    "payment.received":   "Pago recibido",
    "payment.completed":  "Pago completado",
    "payment.pending":    "Pago pendiente de reclamación",
    "payment.failed":     "Pago fallido",
    "payment.cancelled":  "Pago cancelado",
    "payment.expired":    "Pago expirado",
}


def _verify_signature(body: bytes, signature_header: str, secret: str) -> bool:
    """Verifies the Payg0 HMAC-SHA256 signature.

    Accepts both formats Payg0 may send:
      - raw hex:         "b7e1a4f2c9d8..."
      - prefixed:        "sha256=b7e1a4f2c9d8..."
    """
    if not secret:
        return True  # Skip verification if no secret configured
    try:
        digest   = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        prefixed = "sha256=" + digest
        # Accept either format
        valid = (
            hmac.compare_digest(digest,   signature_header) or
            hmac.compare_digest(prefixed, signature_header)
        )
        if not valid:
            logger.warning(
                f"[Payg0] Signature mismatch — "
                f"header='{signature_header[:20]}…' "
                f"expected='{digest[:20]}…'"
            )
        return valid
    except Exception as e:
        logger.warning(f"[Payg0] Signature verification error: {e}")
        return False


def _send_telegram(token: str, chat_id: int, text: str) -> None:
    """Sends a Telegram notification synchronously."""
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info(f"[Payg0] Owner notified via Telegram (chat_id={chat_id})")
    except Exception as e:
        logger.error(f"[Payg0] Failed to notify owner via Telegram: {e}")


def handle_payg0_webhook(
    payload: dict,
    raw_body: bytes,
    signature_header: str,
    bot_token: str,
    owner_chat_id: int,
    webhook_secret: str = "",
) -> None:
    """
    Processes a Payg0 webhook payload and notifies the owner via Telegram.
    Called from the HTTP server thread — must be synchronous.
    """
    try:
        logger.info(
            f"[Payg0] Webhook POST received — "
            f"has_signature={bool(signature_header)} "
            f"has_secret={bool(webhook_secret)} "
            f"body_size={len(raw_body)}b"
        )

        # Verify signature
        if signature_header and webhook_secret:
            if not _verify_signature(raw_body, signature_header, webhook_secret):
                logger.warning("[Payg0] Invalid webhook signature — ignoring.")
                return
        elif webhook_secret and not signature_header:
            logger.warning("[Payg0] PAYG0_WEBHOOK_SECRET is set but no signature header received.")

        event = payload.get("event", payload.get("type", ""))
        data  = payload.get("data", payload.get("payload", payload))

        logger.info(f"[Payg0] Webhook received: event={event}")

        if not event:
            logger.warning(f"[Payg0] Webhook with no event field: {str(payload)[:200]}")
            return

        emoji = _EMOJI.get(event, "🔔")
        label = _EVENT_LABEL.get(event, event)

        # Extract payment fields
        amount    = data.get("amount", "?")
        sender    = data.get("sender", data.get("from", data.get("senderId", "?")))
        recipient = data.get("recipient", data.get("to", data.get("recipientId", "")))
        desc      = data.get("description", data.get("note", ""))
        tx_id     = data.get("id", "")

        # Only notify for incoming payments (sender != owner) or all events
        lines = [f"{emoji} Payg0 — {label}"]

        if event == "payment.received":
            nickname = data.get("sender_nickname", "")
            sender   = f"@{nickname}" if nickname else data.get("sender_id", "?")
            lines.append(f"De: {sender}")
            lines.append(f"Monto: ${amount} MXN")
        elif event == "payment.completed":
            lines.append(f"De: {sender}")
            lines.append(f"Monto: ${amount} MXN")
        elif event == "payment.pending":
            lines.append(f"De: {sender}")
            lines.append(f"Monto: ${amount} MXN")
            lines.append("(el destinatario aún no reclama el pago)")
        elif event in ("payment.failed", "payment.cancelled", "payment.expired"):
            lines.append(f"Monto: ${amount} MXN")
            if recipient:
                lines.append(f"Para: {recipient}")

        if desc:
            lines.append(f"Descripción: {desc}")

        _send_telegram(bot_token, owner_chat_id, "\n".join(lines))

    except Exception as e:
        logger.exception(f"[Payg0] Error handling webhook: {e}")


def _find_webhook_id(api_key: str, webhook_url: str) -> str:
    """Finds the Payg0 webhook ID for the given URL via GET /webhooks."""
    try:
        resp = requests.get(
            "https://api.payg0.io/api/v1/webhooks",
            headers={"X-API-Key": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else data.get("webhooks", data.get("data", []))
        for wh in items:
            if wh.get("url") == webhook_url:
                return wh.get("id", "")
    except Exception as e:
        logger.warning(f"[Payg0] Could not list webhooks: {e}")
    return ""


def _rotate_webhook_secret(api_key: str, webhook_id: str) -> str:
    """Rotates the secret for an existing webhook via POST /webhooks/{id}/rotate-secret."""
    try:
        resp = requests.post(
            f"https://api.payg0.io/api/v1/webhooks/{webhook_id}/rotate-secret",
            headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("secret", data.get("signingSecret", ""))
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            logger.warning("[Payg0] rotate-secret endpoint not yet available.")
        else:
            logger.warning(f"[Payg0] rotate-secret failed: {e.response.status_code} — {e.response.text}")
    except Exception as e:
        logger.warning(f"[Payg0] rotate-secret error: {e}")
    return ""


def register_payg0_webhook(api_key: str, webhook_url: str) -> str:
    """
    Registers the Beli webhook URL with Payg0.
    Called at startup if BELI_PUBLIC_URL and PAYG0_API_KEY are set.
    Returns the webhook secret (to be saved as PAYG0_WEBHOOK_SECRET).

    If webhook already exists (409), attempts rotate-secret to get a fresh secret.
    """
    _HEADERS = {"X-API-Key": api_key, "Content-Type": "application/json"}
    _EVENTS  = ["payment.received"]
    try:
        resp = requests.post(
            "https://api.payg0.io/api/v1/webhooks",
            headers=_HEADERS,
            json={"url": webhook_url, "events": _EVENTS},
            timeout=15,
        )
        resp.raise_for_status()
        data   = resp.json()
        secret = data.get("secret", data.get("signingSecret", ""))
        logger.info(f"[Payg0] Webhook registered at {webhook_url}")
        if secret:
            logger.info(f"[Payg0] Webhook secret: {secret} — add as PAYG0_WEBHOOK_SECRET in Railway.")
        return secret

    except requests.HTTPError as e:
        if e.response.status_code == 409:
            logger.info("[Payg0] Webhook already registered — attempting rotate-secret to recover secret.")
            webhook_id = _find_webhook_id(api_key, webhook_url)
            if webhook_id:
                secret = _rotate_webhook_secret(api_key, webhook_id)
                if secret:
                    logger.info(f"[Payg0] Rotated webhook secret: {secret} — add as PAYG0_WEBHOOK_SECRET in Railway.")
                    return secret
                else:
                    logger.info("[Payg0] rotate-secret not available yet — webhook works without secret verification.")
            else:
                logger.info("[Payg0] Could not find webhook ID — webhook works without secret verification.")
            return ""
        logger.error(f"[Payg0] Failed to register webhook: {e.response.status_code} — {e.response.text}")
        return ""
    except Exception as e:
        logger.error(f"[Payg0] Failed to register webhook: {e}")
        return ""
