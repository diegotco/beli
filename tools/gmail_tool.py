"""
tools/gmail_tool.py - Gmail integration for Beli.

Lets Beli read the owner's inbox and send emails FROM the owner's
personal Gmail address (not beli@agentmail.to).

Uses Gmail API v1 with OAuth 2.0 credentials.
Credentials JSON is stored in the GMAIL_CREDENTIALS env var.
One-time setup: python setup_gmail.py
"""
import base64
import json
import logging
import re
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger("beli.tools.gmail")

_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_service(credentials_json: str):
    """Builds and returns an authenticated Gmail API service."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds_data = json.loads(credentials_json)
    creds = Credentials(
        token=creds_data.get("token"),
        refresh_token=creds_data.get("refresh_token"),
        token_uri=creds_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=creds_data.get("client_id"),
        client_secret=creds_data.get("client_secret"),
        scopes=creds_data.get("scopes", _SCOPES),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_header(headers: list, name: str) -> str:
    """Returns a header value by name (case-insensitive)."""
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "")
    return ""


def _decode_body(payload: dict) -> str:
    """
    Recursively extracts plain-text content from a Gmail message payload.
    Prefers text/plain; falls back to HTML with tags stripped.
    """
    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    if "parts" in payload:
        plain = ""
        html_fallback = ""
        for part in payload["parts"]:
            part_type = part.get("mimeType", "")
            data = part.get("body", {}).get("data", "")

            if part_type == "text/plain" and data:
                plain += base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            elif part_type == "text/html" and data and not plain:
                raw_html = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
                stripped = re.sub(r"<[^>]+>", " ", raw_html)
                html_fallback = re.sub(r"\s{2,}", " ", stripped).strip()
            elif part_type.startswith("multipart/"):
                sub = _decode_body(part)
                if sub:
                    plain += sub

        return plain or html_fallback

    return ""


def _clean_sender(raw: str) -> str:
    """'John Doe <john@example.com>' → 'John Doe'"""
    name = re.sub(r"\s*<[^>]+>", "", raw).strip().strip('"')
    return name or raw


# ── Tool 1: Read inbox ────────────────────────────────────────────────────────

def read_gmail_inbox(
    credentials_json: str,
    max_results: int = 10,
    unread_only: bool = False,
) -> str:
    """
    Returns a formatted summary of recent Gmail messages.

    Args:
        credentials_json: JSON string with OAuth credentials (GMAIL_CREDENTIALS).
        max_results:       Number of emails to return (default 10, max 20).
        unread_only:       If True, only returns unread messages.
    """
    if not credentials_json:
        return (
            "No están configuradas las credenciales de Gmail (GMAIL_CREDENTIALS). "
            "Corre python setup_gmail.py para configurarlas."
        )

    max_results = min(max(1, max_results), 20)

    try:
        service = _get_service(credentials_json)

        query = "is:unread" if unread_only else ""
        result = service.users().messages().list(
            userId="me",
            labelIds=["INBOX"],
            q=query,
            maxResults=max_results,
        ).execute()

        messages = result.get("messages", [])
        if not messages:
            label = "sin leer" if unread_only else "recientes"
            return f"No hay correos {label} en tu bandeja de entrada de Gmail."

        lines = []
        for i, msg_ref in enumerate(messages, 1):
            msg = service.users().messages().get(
                userId="me",
                id=msg_ref["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()

            headers  = msg.get("payload", {}).get("headers", [])
            sender   = _clean_sender(_get_header(headers, "From"))
            subject  = _get_header(headers, "Subject") or "(sin asunto)"
            snippet  = msg.get("snippet", "")[:120]
            is_unread = "UNREAD" in msg.get("labelIds", [])
            msg_id   = msg_ref["id"]

            unread_dot = " 🔵" if is_unread else ""
            lines.append(
                f"{i}. {sender}{unread_dot}\n"
                f"   Asunto: {subject}\n"
                f"   {snippet}\n"
                f"   [id: {msg_id}]"
            )

        title = "Correos sin leer" if unread_only else "Correos recientes"
        return f"{title} en Gmail:\n\n" + "\n\n".join(lines)

    except Exception as e:
        logger.exception(f"[Gmail] Error reading inbox: {e}")
        return f"Error al leer Gmail: {e}"


# ── Tool 2: Read full message ─────────────────────────────────────────────────

def read_gmail_message(
    credentials_json: str,
    message_id_or_subject: str,
) -> str:
    """
    Reads the full content of a specific Gmail message.

    Args:
        credentials_json:       JSON string with OAuth credentials.
        message_id_or_subject:  Gmail message ID (from read_gmail_inbox) or
                                subject text to search for.
    """
    if not credentials_json:
        return "No están configuradas las credenciales de Gmail (GMAIL_CREDENTIALS)."

    try:
        service = _get_service(credentials_json)

        # If it looks like a raw Gmail ID (no spaces, alphanumeric), use it directly
        needle = message_id_or_subject.strip()
        if re.match(r"^[A-Za-z0-9_\-]{10,}$", needle):
            msg_id = needle
        else:
            # Search by subject
            result = service.users().messages().list(
                userId="me",
                q=f"subject:{needle}",
                maxResults=1,
            ).execute()
            msgs = result.get("messages", [])
            if not msgs:
                return f"No encontré ningún correo con asunto '{needle}' en Gmail."
            msg_id = msgs[0]["id"]

        msg = service.users().messages().get(
            userId="me",
            id=msg_id,
            format="full",
        ).execute()

        headers  = msg.get("payload", {}).get("headers", [])
        sender   = _get_header(headers, "From")
        to       = _get_header(headers, "To")
        subject  = _get_header(headers, "Subject") or "(sin asunto)"
        date     = _get_header(headers, "Date")
        body     = _decode_body(msg.get("payload", {}))

        body_text = body[:3000].strip() if body else "(sin cuerpo de texto)"

        return (
            f"De: {sender}\n"
            f"Para: {to}\n"
            f"Asunto: {subject}\n"
            f"Fecha: {date}\n"
            f"ID: {msg_id}\n\n"
            f"--- Contenido ---\n{body_text}"
        )

    except Exception as e:
        logger.exception(f"[Gmail] Error reading message '{message_id_or_subject}': {e}")
        return f"Error al leer el correo de Gmail: {e}"


# ── Tool 3: Send from owner's Gmail ──────────────────────────────────────────

def send_gmail_message(
    credentials_json: str,
    to: str,
    subject: str,
    body: str,
    thread_id: Optional[str] = None,
) -> str:
    """
    Sends an email FROM the owner's personal Gmail account.

    Args:
        credentials_json: JSON string with OAuth credentials.
        to:               Recipient email address.
        subject:          Email subject.
        body:             Plain-text email body.
        thread_id:        Optional Gmail thread ID to reply in-thread.
    """
    if not credentials_json:
        return "No están configuradas las credenciales de Gmail (GMAIL_CREDENTIALS)."

    try:
        service = _get_service(credentials_json)

        # Get owner's email address for the From header
        profile = service.users().getProfile(userId="me").execute()
        owner_email = profile.get("emailAddress", "me")

        mime_msg = MIMEText(body, "plain", "utf-8")
        mime_msg["To"]      = to
        mime_msg["From"]    = owner_email
        mime_msg["Subject"] = subject

        raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
        payload: dict = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id

        result = service.users().messages().send(
            userId="me",
            body=payload,
        ).execute()

        sent_id = result.get("id", "")
        logger.info(f"[Gmail] Email sent to {to} | Subject: {subject} | id: {sent_id}")
        return f"✓ ENVIADO EXITOSAMENTE desde {owner_email} a {to} con asunto '{subject}'."

    except Exception as e:
        logger.exception(f"[Gmail] Error sending email to {to}: {e}")
        return f"Error al enviar el correo desde Gmail: {e}"
