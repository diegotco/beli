"""
tools/birthday_scheduler.py - Sends birthday WhatsApp messages on behalf of Diego.

Contact data comes from the BIRTHDAY_CONTACTS env var (JSON array, Railway only — never git).

Two message types:
  - direct:   Sends a warm greeting directly to the birthday person.
  - sobrino:  Sends a heads-up to the parent (Sensei or Alanis) that Diego will write soon.

All messages are sent ghost-mode from Diego's WhatsApp number via WAHA.
"""
import json
import logging
import datetime
import zoneinfo

from tools.whatsapp_sender import send_whatsapp_message

logger = logging.getLogger("beli.birthday")

_CDMX_TZ = zoneinfo.ZoneInfo("America/Mexico_City")


def check_and_send_birthdays(
    waha_url: str,
    session: str,
    api_key: str,
    contacts_json: str,
) -> None:
    """
    Checks today's date (CDMX) against the birthday list and sends WhatsApp messages.
    Called daily at 6 AM CDMX by the Telegram job queue.
    """
    if not contacts_json or not waha_url:
        logger.debug("[Birthday] Skipped — BIRTHDAY_CONTACTS or WAHA_URL not configured.")
        return

    try:
        contacts = json.loads(contacts_json)
    except Exception as e:
        logger.error(f"[Birthday] Failed to parse BIRTHDAY_CONTACTS: {e}")
        return

    today = datetime.datetime.now(tz=_CDMX_TZ)
    logger.info(f"[Birthday] Checking birthdays for {today.strftime('%B %d')}...")

    sent = 0
    for contact in contacts:
        if contact.get("month") == today.month and contact.get("day") == today.day:
            contact_type = contact.get("type", "direct")
            name = contact.get("name", "")

            if contact_type == "direct":
                phone = contact.get("phone", "")
                if phone:
                    _send_direct_greeting(waha_url, session, api_key, name, phone)
                    sent += 1

            elif contact_type == "sobrino":
                parent_name = contact.get("parent_name", "")
                parent_phone = contact.get("parent_phone", "")
                if parent_phone:
                    _send_parent_notification(waha_url, session, api_key, name, parent_name, parent_phone)
                    sent += 1

    if sent == 0:
        logger.info("[Birthday] No birthdays today.")
    else:
        logger.info(f"[Birthday] {sent} message(s) sent.")


def _send_direct_greeting(
    waha_url: str, session: str, api_key: str, name: str, phone: str
) -> None:
    msg = (
        f"¡Feliz cumpleaños {name}! 🎂 "
        f"Diego te manda un abrazo enorme — te escribirá personalmente en un rato."
    )
    result = send_whatsapp_message(
        waha_url=waha_url, recipient=phone, message=msg, session=session, api_key=api_key
    )
    logger.info(f"[Birthday] Greeting → {name}: {result}")


def _send_parent_notification(
    waha_url: str, session: str, api_key: str,
    child_name: str, parent_name: str, parent_phone: str
) -> None:
    msg = (
        f"¡Hoy cumple años {child_name}! 🎉 "
        f"Diego te escribirá pronto."
    )
    result = send_whatsapp_message(
        waha_url=waha_url, recipient=parent_phone, message=msg, session=session, api_key=api_key
    )
    logger.info(f"[Birthday] Parent notification → {parent_name} (for {child_name}): {result}")
