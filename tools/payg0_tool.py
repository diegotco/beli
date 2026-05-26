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
            f"{_BASE_URL}/api/v1/balance",
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

        # Handle both list response and {"payments": [...]} shape
        items = data if isinstance(data, list) else data.get("payments", data.get("data", []))

        if not items:
            return "No hay transacciones recientes en Payg0."

        lines = []
        for tx in items[:limit]:
            tx_id     = tx.get("id", "")[:8]
            status    = tx.get("status", "")
            amount    = tx.get("amount", "?")
            recipient = tx.get("recipient", tx.get("to", "?"))
            desc      = tx.get("description", "")
            created   = tx.get("createdAt", tx.get("created_at", ""))[:10]
            line = f"• [{created}] ${amount} MXN → {recipient} [{status}]"
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
