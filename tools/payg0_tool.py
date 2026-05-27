"""
tools/payg0_tool.py - Payg0 payment integration for Beli.

Payg0 is a MXN payment platform for humans and AI agents.
API base: https://api.payg0.io
Auth: X-API-Key header
"""
import logging
import requests

logger = logging.getLogger("beli.tools.payg0")

_BASE_URL = "https://api.payg0.io"
_TIMEOUT = 15


def _headers(api_key: str) -> dict:
    return {"X-API-Key": api_key, "Content-Type": "application/json"}


def payg0_balance(api_key: str) -> str:
    """Returns the current Payg0 wallet balance in MXN."""
    if not api_key:
        return "No está configurada la API key de Payg0 (PAYG0_API_KEY)."
    try:
        resp = requests.get(
            f"{_BASE_URL}/api/v1/wallet/balance",
            headers=_headers(api_key),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        balance = data.get("balance", data.get("amount", "?"))
        return f"Saldo Payg0: ${balance} MXN"
    except requests.HTTPError as e:
        return f"Error al consultar saldo Payg0: {e.response.status_code} — {e.response.text}"
    except Exception as e:
        logger.exception(f"[Payg0] Error getting balance: {e}")
        return f"Error al consultar saldo Payg0: {e}"


def payg0_transactions(api_key: str, limit: int = 10) -> str:
    """Returns recent Payg0 transaction history."""
    if not api_key:
        return "No está configurada la API key de Payg0 (PAYG0_API_KEY)."
    try:
        resp = requests.get(
            f"{_BASE_URL}/api/v1/payments/history",
            headers=_headers(api_key),
            params={"limit": limit},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        logger.info(f"[Payg0] /payments/history raw response keys: {list(data.keys()) if isinstance(data, dict) else f'list[{len(data)}]'}")
        logger.info(f"[Payg0] /payments/history raw: {str(data)[:500]}")

        # Handle all known response shapes
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = (
                data.get("payments")
                or data.get("data")
                or data.get("transactions")
                or data.get("results")
                or data.get("items")
                or []
            )
        else:
            items = []

        if not items:
            return f"No hay transacciones recientes en Payg0. (Respuesta cruda: {str(data)[:300]})"

        lines = []
        for tx in items[:limit]:
            tx_id     = str(tx.get("id", ""))          # full UUID — never truncate
            status    = tx.get("status", "")
            amount    = tx.get("amount", "?")
            recipient = tx.get("recipient", tx.get("to", tx.get("recipientId", "?")))
            desc      = tx.get("description", tx.get("note", ""))
            created   = str(tx.get("createdAt", tx.get("created_at", tx.get("date", ""))))[:10]
            line = f"• [{created}] ID:{tx_id} ${amount} MXN → {recipient} [{status}]"
            if desc:
                line += f" — {desc}"
            lines.append(line)

        return f"Últimas {len(lines)} transacciones Payg0:\n\n" + "\n".join(lines)
    except requests.HTTPError as e:
        return f"Error al obtener historial Payg0: {e.response.status_code} — {e.response.text}"
    except Exception as e:
        logger.exception(f"[Payg0] Error getting transactions: {e}")
        return f"Error al obtener historial Payg0: {e}"


def payg0_send_payment(
    api_key: str,
    recipient: str,
    amount: float,
    description: str = "",
) -> str:
    """
    Sends a payment via Payg0.

    Args:
        api_key:     Payg0 API key
        recipient:   @username or email address of the recipient
        amount:      Amount in MXN
        description: Optional payment description
    """
    if not api_key:
        return "No está configurada la API key de Payg0 (PAYG0_API_KEY)."
    try:
        payload: dict = {"recipient": recipient, "amount": amount}
        if description:
            payload["description"] = description

        resp = requests.post(
            f"{_BASE_URL}/api/v1/payments/send",
            headers=_headers(api_key),
            json=payload,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        status    = data.get("status", "COMPLETED")
        tx_id     = data.get("id", "")
        amount_out = data.get("amount", amount)
        reason    = data.get("reason", "")

        result = f"✓ Pago enviado a {recipient}: ${amount_out} MXN [{status}]"
        if reason:
            result += f" — {reason}"
        if tx_id:
            result += f"\nID: {tx_id}"
        logger.info(f"[Payg0] Payment sent to {recipient}: ${amount_out} MXN (id={tx_id})")
        return result

    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("message", e.response.text)
        except Exception:
            detail = str(e)
        logger.error(f"[Payg0] HTTP error sending payment to {recipient}: {detail}")
        return f"Error al enviar pago Payg0: {detail}"
    except Exception as e:
        logger.exception(f"[Payg0] Error sending payment to {recipient}: {e}")
        return f"Error al enviar pago Payg0: {e}"


def payg0_payment_detail(api_key: str, payment_id: str) -> str:
    """Returns full details of a specific Payg0 transaction by ID."""
    if not api_key:
        return "No está configurada la API key de Payg0 (PAYG0_API_KEY)."
    try:
        resp = requests.get(
            f"{_BASE_URL}/api/v1/payments/{payment_id}",
            headers=_headers(api_key),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        tx = resp.json()

        status    = tx.get("status", "?")
        amount    = tx.get("amount", "?")
        recipient = tx.get("recipient", tx.get("to", "?"))
        sender    = tx.get("sender", tx.get("from", "?"))
        desc      = tx.get("description", "")
        created   = tx.get("createdAt", tx.get("created_at", ""))[:19].replace("T", " ")
        tx_id     = tx.get("id", payment_id)   # full UUID

        lines = [
            f"ID: {tx_id}",
            f"Estado: {status}",
            f"Monto: ${amount} MXN",
            f"De: {sender}  →  Para: {recipient}",
            f"Fecha: {created}",
        ]
        if desc:
            lines.append(f"Descripción: {desc}")

        return "\n".join(lines)

    except requests.HTTPError as e:
        return f"Error al obtener detalle del pago: {e.response.status_code} — {e.response.text}"
    except Exception as e:
        logger.exception(f"[Payg0] Error getting payment detail {payment_id}: {e}")
        return f"Error al obtener detalle del pago: {e}"


def payg0_cancel_payment(api_key: str, payment_id: str) -> str:
    """Cancels a PENDING Payg0 payment. Only the sender can cancel."""
    if not api_key:
        return "No está configurada la API key de Payg0 (PAYG0_API_KEY)."
    try:
        resp = requests.post(
            f"{_BASE_URL}/api/v1/payments/{payment_id}/cancel",
            headers=_headers(api_key),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", "CANCELLED")
        logger.info(f"[Payg0] Payment {payment_id} cancelled — status: {status}")
        return f"✓ Pago {payment_id[:8]}… cancelado correctamente. Estado: {status}"

    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("message", e.response.text)
        except Exception:
            detail = str(e)
        logger.error(f"[Payg0] HTTP error cancelling payment {payment_id}: {detail}")
        return f"Error al cancelar el pago: {detail}"
    except Exception as e:
        logger.exception(f"[Payg0] Error cancelling payment {payment_id}: {e}")
        return f"Error al cancelar el pago: {e}"


def _get_my_user_id(api_key: str) -> str | None:
    """Fetches the owner's Payg0 user ID via GET /api/v1/auth/me."""
    try:
        resp = requests.get(
            f"{_BASE_URL}/api/v1/auth/me",
            headers=_headers(api_key),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"[Payg0] /auth/me response keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
        logger.info(f"[Payg0] /auth/me raw: {str(data)[:300]}")
        user_id = (
            data.get("id")
            or data.get("userId")
            or data.get("user_id")
            or data.get("_id")
            or data.get("uuid")
            or (data.get("user", {}) or {}).get("id")
        )
        logger.info(f"[Payg0] Extracted user_id: {user_id}")
        return str(user_id) if user_id is not None else None
    except Exception as e:
        logger.warning(f"[Payg0] Could not fetch user ID: {e}")
        return None


def payg0_check_tier(api_key: str) -> str:
    """
    Returns the owner's current Payg0 tier, monthly limits, and usage percentages.
    Used internally before sending payments and on request to check incoming capacity.
    """
    if not api_key:
        return "No está configurada la API key de Payg0 (PAYG0_API_KEY)."

    user_id = _get_my_user_id(api_key)
    if not user_id:
        return "No se pudo obtener el ID de usuario de Payg0 para consultar el tier."

    tier_url = f"{_BASE_URL}/api/v1/users/{user_id}/tier"
    logger.info(f"[Payg0] Calling tier endpoint: {tier_url}")
    try:
        resp = requests.get(
            tier_url,
            headers=_headers(api_key),
            timeout=_TIMEOUT,
        )
        logger.info(f"[Payg0] Tier response status: {resp.status_code}")
        if not resp.ok:
            logger.warning(f"[Payg0] Tier error body: {resp.text[:300]}")
        resp.raise_for_status()
        data = resp.json()

        tier        = data.get("tier", data.get("name", "?"))
        sent_used   = data.get("sentAmount", data.get("sent_amount", data.get("monthlyUsed", "?")))
        sent_limit  = data.get("sentLimit",  data.get("sent_limit",  data.get("monthlyLimit", "?")))
        recv_used   = data.get("receivedAmount", data.get("received_amount", ""))
        recv_limit  = data.get("receivedLimit",  data.get("received_limit", ""))
        sent_pct    = data.get("sentPercentage",  data.get("sent_pct", ""))
        recv_pct    = data.get("receivedPercentage", data.get("recv_pct", ""))

        lines = [f"Tier Payg0: {tier}"]

        if sent_limit:
            pct_str = f" ({sent_pct}% usado)" if sent_pct != "" else ""
            lines.append(f"Enviado este mes: ${sent_used} / ${sent_limit} MXN{pct_str}")
        if recv_limit:
            pct_str = f" ({recv_pct}% usado)" if recv_pct != "" else ""
            lines.append(f"Recibido este mes: ${recv_used} / ${recv_limit} MXN{pct_str}")

        # Warn if close to limits
        warnings = []
        for pct, label in [(sent_pct, "envíos"), (recv_pct, "recepción")]:
            try:
                if float(pct) >= 90:
                    warnings.append(f"⚠️ Límite de {label} al {pct}% — quedan pocos fondos disponibles.")
                elif float(pct) >= 75:
                    warnings.append(f"⚠️ Límite de {label} al {pct}% del mes.")
            except (TypeError, ValueError):
                pass

        if warnings:
            lines.append("")
            lines.extend(warnings)

        return "\n".join(lines)

    except requests.HTTPError as e:
        return f"Error al consultar tier Payg0: {e.response.status_code} — user_id={user_id} — {e.response.text}"
    except Exception as e:
        logger.exception(f"[Payg0] Error checking tier: {e}")
        return f"Error al consultar tier Payg0 (user_id={user_id}): {e}"
