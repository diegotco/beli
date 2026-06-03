"""
tools/sario_tool.py - SARIO chat platform integration for Beli.

SARIO is a chat platform for humans and AI agents (chat.b3li.io).
Beli's agent account: username 'beli', authenticated via SARIO_API_KEY.

API base: https://chat.b3li.io
Auth: Authorization: Bearer <apiKey>
Docs: http://chat.b3li.io/developers
"""
import logging
import requests

logger = logging.getLogger("beli.tools.sario")

_BASE_URL = "https://chat.b3li.io"
_TIMEOUT = 20


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def sario_send_message(api_key: str, thread_id: str, body: str, event_id: str = "") -> str:
    """Sends a message to a SARIO thread as Beli."""
    if not api_key:
        return "No está configurada la SARIO_API_KEY."
    try:
        payload = {"threadId": thread_id, "body": body}
        if event_id:
            payload["eventId"] = event_id
        resp = requests.post(
            f"{_BASE_URL}/api/messages",
            headers=_headers(api_key),
            json=payload,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        logger.info(f"[SARIO] Message sent to thread {thread_id}")
        return f"✓ Mensaje enviado en SARIO al hilo {thread_id}."
    except requests.HTTPError as e:
        return f"Error al enviar mensaje en SARIO: {e.response.status_code} — {e.response.text}"
    except Exception as e:
        logger.exception(f"[SARIO] Error sending message: {e}")
        return f"Error al enviar mensaje en SARIO: {e}"


def sario_check_messages(api_key: str) -> str:
    """
    Polls SARIO for pending messages directed at Beli.
    Uses long-polling (blocks up to 20s). Returns any pending task or 'no messages'.
    """
    if not api_key:
        return "No está configurada la SARIO_API_KEY."
    try:
        resp = requests.get(
            f"{_BASE_URL}/api/wait",
            headers=_headers(api_key),
            timeout=25,  # slightly above server's 20s poll window
        )
        resp.raise_for_status()
        data = resp.json()
        task = data.get("nextTask")
        pending = data.get("pendingCount", 0)

        if not task:
            return f"No hay mensajes pendientes en SARIO. (pendingCount: {pending})"

        thread_id  = task.get("threadId", "")
        event_id   = task.get("eventId", "")
        message    = task.get("messageToAnswer", "")
        sender     = task.get("messageFrom", "?")

        return (
            f"Nuevo mensaje en SARIO:\n"
            f"De: {sender}\n"
            f"Hilo: {thread_id}\n"
            f"EventID: {event_id}\n"
            f"Mensaje: {message}\n"
            f"Pendientes: {pending}"
        )
    except requests.HTTPError as e:
        return f"Error al consultar mensajes SARIO: {e.response.status_code} — {e.response.text}"
    except Exception as e:
        logger.exception(f"[SARIO] Error checking messages: {e}")
        return f"Error al consultar mensajes SARIO: {e}"


def sario_create_thread(api_key: str, title: str) -> str:
    """Creates a new SARIO chat thread and returns its ID."""
    if not api_key:
        return "No está configurada la SARIO_API_KEY."
    try:
        resp = requests.post(
            f"{_BASE_URL}/api/threads",
            headers=_headers(api_key),
            json={"title": title},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        thread_id = data.get("threadId", data.get("id", ""))
        logger.info(f"[SARIO] Thread created: {thread_id} — {title}")
        return f"✓ Hilo SARIO creado: '{title}' (ID: {thread_id})"
    except requests.HTTPError as e:
        return f"Error al crear hilo SARIO: {e.response.status_code} — {e.response.text}"
    except Exception as e:
        logger.exception(f"[SARIO] Error creating thread: {e}")
        return f"Error al crear hilo SARIO: {e}"


def sario_create_invite(api_key: str, thread_id: str) -> str:
    """Generates an invite link for a SARIO thread."""
    if not api_key:
        return "No está configurada la SARIO_API_KEY."
    try:
        resp = requests.post(
            f"{_BASE_URL}/api/invites",
            headers=_headers(api_key),
            json={"threadId": thread_id},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("token", data.get("invite", ""))
        invite_url = f"https://chat.b3li.io/i/{token}" if token else str(data)
        logger.info(f"[SARIO] Invite created for thread {thread_id}: {invite_url}")
        return f"✓ Invitación SARIO generada: {invite_url}"
    except requests.HTTPError as e:
        return f"Error al generar invitación SARIO: {e.response.status_code} — {e.response.text}"
    except Exception as e:
        logger.exception(f"[SARIO] Error creating invite: {e}")
        return f"Error al generar invitación SARIO: {e}"


def sario_accept_invite(api_key: str, invite_token: str) -> str:
    """Accepts a SARIO invite link and joins the thread."""
    if not api_key:
        return "No está configurada la SARIO_API_KEY."
    try:
        resp = requests.post(
            f"{_BASE_URL}/api/invites/{invite_token}/accept",
            headers=_headers(api_key),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        thread_id = data.get("threadId", "")
        title = data.get("title", "")
        logger.info(f"[SARIO] Joined thread {thread_id} — {title}")
        return f"✓ Unida al hilo SARIO: '{title}' (ID: {thread_id})"
    except requests.HTTPError as e:
        return f"Error al aceptar invitación SARIO: {e.response.status_code} — {e.response.text}"
    except Exception as e:
        logger.exception(f"[SARIO] Error accepting invite: {e}")
        return f"Error al aceptar invitación SARIO: {e}"
