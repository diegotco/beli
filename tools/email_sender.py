"""
tools/email_sender.py - Sends emails via AgentMail API (beli@agentmail.to).

AgentMail gives Beli her own email address. Emails are sent via REST API.
API docs: https://docs.agentmail.to/api-reference/inboxes/messages/send
"""
import logging
import requests

logger = logging.getLogger("beli.tools.email_sender")

AGENTMAIL_BASE_URL = "https://api.agentmail.to/v0"


def send_email(api_key: str, inbox_id: str, to: str, subject: str, body: str) -> str:
    """
    Sends an email from beli@agentmail.to via the AgentMail REST API.
    Returns a plain-text string describing the result (success or error).
    """
    if not api_key:
        return "No está configurada la AGENTMAIL_API_KEY en el archivo .env."

    url = f"{AGENTMAIL_BASE_URL}/inboxes/{inbox_id}/messages"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": [to] if isinstance(to, str) else to,
        "subject": subject,
        "text": body,
    }

    logger.info(f"Sending email via AgentMail to {to} | Subject: {subject}")

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)

        if response.status_code in (200, 201):
            logger.info(f"Email sent successfully to {to}")
            return f"✓ ENVIADO EXITOSAMENTE a {to} con asunto '{subject}' desde beli@agentmail.to."

        # Handle known error codes
        if response.status_code == 401:
            return "Error de autenticación con AgentMail. Verifica que AGENTMAIL_API_KEY en .env sea correcta."
        if response.status_code == 404:
            return f"Inbox '{inbox_id}' no encontrado en AgentMail. Verifica AGENTMAIL_INBOX_ID en .env."

        # Generic API error
        logger.error(f"AgentMail API error: {response.status_code} — {response.text}")
        return f"Error al enviar el email (código {response.status_code}): {response.text}"

    except requests.Timeout:
        logger.error("AgentMail API request timed out")
        return "La solicitud a AgentMail tardó demasiado. Intenta de nuevo."

    except requests.RequestException as e:
        logger.exception(f"Network error sending email: {e}")
        return f"Error de red al conectar con AgentMail: {e}"
