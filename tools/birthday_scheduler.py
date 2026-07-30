"""
tools/birthday_scheduler.py - Sends birthday WhatsApp messages on behalf of Diego.

Contact data comes from the BIRTHDAY_CONTACTS env var (JSON array, Railway only — never git).

Two message types:
  - direct:   Sends a warm greeting directly to the birthday person.
  - sobrino:  Sends a heads-up to the parent (Sensei or Alanis) that Diego will write soon.

All messages are sent ghost-mode from Diego's WhatsApp number via WAHA. Because
Beli — not Diego — writes them, they refer to Diego in the third person and end
with _SIGNATURE so the recipient knows who is actually writing.
"""
import json
import logging
import datetime
import re
import zoneinfo

from tools.whatsapp_sender import send_whatsapp_message

logger = logging.getLogger("beli.birthday")

_CDMX_TZ = zoneinfo.ZoneInfo("America/Mexico_City")

# Every automated birthday message carries this signature. The messages go out
# from Diego's own WhatsApp number, so without it the recipient cannot tell who
# is actually writing.
_SIGNATURE = "(Beli, asistente de Diego)"

# Sentence that follows the greeting in a "sobrino" message. Some kids get a
# message from Diego directly, others are reached through their parent, so a
# contact may override this with its own "followup" field in BIRTHDAY_CONTACTS.
_DEFAULT_SOBRINO_FOLLOWUP = "Diego se pondrá en contacto contigo durante el día."


def check_and_send_birthdays(
    waha_url: str,
    session: str,
    api_key: str,
    contacts_json: str,
    skip_names: set[str] | frozenset = frozenset(),
) -> tuple[list[str], list[str]]:
    """
    Checks today's date (CDMX) against the birthday list and sends WhatsApp messages.
    Called daily at 6 AM CDMX by the Telegram job queue.

    skip_names: contacts already delivered today (used by the retry job so a
    second pass never double-sends).

    Returns (failures, delivered_names):
      failures        — human-readable failure descriptions (empty = all good)
      delivered_names — names successfully delivered in THIS pass
    """
    if not contacts_json or not waha_url:
        logger.debug("[Birthday] Skipped — BIRTHDAY_CONTACTS or WAHA_URL not configured.")
        return [], []

    try:
        contacts = json.loads(contacts_json)
    except Exception as e:
        logger.error(f"[Birthday] Failed to parse BIRTHDAY_CONTACTS: {e}")
        return [f"No pude leer BIRTHDAY_CONTACTS: {e}"], []

    today = datetime.datetime.now(tz=_CDMX_TZ)
    logger.info(f"[Birthday] Checking birthdays for {today.strftime('%B %d')}...")

    attempted = 0
    failures: list[str] = []
    delivered: list[str] = []
    for contact in contacts:
        if contact.get("month") == today.month and contact.get("day") == today.day:
            contact_type = contact.get("type", "direct")
            name = contact.get("name", "")
            if name in skip_names:
                logger.info(f"[Birthday] {name}: already delivered today — skipping.")
                continue

            if contact_type == "direct":
                phone = contact.get("phone", "")
                if phone:
                    attempted += 1
                    result = _send_direct_greeting(waha_url, session, api_key, name, phone)
                    if _is_success(result):
                        delivered.append(name)
                    else:
                        failures.append(f"Felicitación a {name}: {result}")

            elif contact_type == "sobrino":
                parent_name = contact.get("parent_name", "")
                parent_phone = contact.get("parent_phone", "")
                if parent_phone:
                    attempted += 1
                    result = _send_parent_notification(
                        waha_url, session, api_key, name, parent_name, parent_phone,
                        followup=contact.get("followup") or _DEFAULT_SOBRINO_FOLLOWUP,
                    )
                    if _is_success(result):
                        delivered.append(name)
                    else:
                        failures.append(f"Aviso a {parent_name} (cumple {name}): {result}")

    if attempted == 0:
        logger.info("[Birthday] No birthdays pending today.")
    else:
        logger.info(f"[Birthday] {len(delivered)}/{attempted} message(s) delivered.")
    return failures, delivered


def _is_success(result: str) -> bool:
    return result.startswith("✓")


def _send_direct_greeting(
    waha_url: str, session: str, api_key: str, name: str, phone: str
) -> str:
    msg = (
        f"¡Feliz cumpleaños {name}! 🎂 "
        f"Diego te manda un abrazo enorme — te escribirá personalmente en un rato. "
        f"{_SIGNATURE}"
    )
    result = send_whatsapp_message(
        waha_url=waha_url, recipient=phone, message=msg, session=session, api_key=api_key,
        allow_unsaved=True,  # curated birthday numbers — skip the saved-contact gate
    )
    logger.info(f"[Birthday] Greeting → {name}: {result}")
    return result


def _send_parent_notification(
    waha_url: str, session: str, api_key: str,
    child_name: str, parent_name: str, parent_phone: str,
    followup: str = _DEFAULT_SOBRINO_FOLLOWUP,
) -> str:
    msg = (
        f"¡Feliz cumpleaños a {child_name}! 🎉 "
        f"{followup} "
        f"{_SIGNATURE}"
    )
    result = send_whatsapp_message(
        waha_url=waha_url, recipient=parent_phone, message=msg, session=session, api_key=api_key,
        allow_unsaved=True,  # curated birthday numbers — skip the saved-contact gate
    )
    logger.info(f"[Birthday] Parent notification → {parent_name} (for {child_name}): {result}")
    return result


# ── Birthdays Beli knows but was never told to act on ────────────────────────
# The scheduler only reads BIRTHDAY_CONTACTS. A birthday mentioned in chat is
# stored as a memory fact and would otherwise never trigger a message, so we
# surface those to the owner instead of letting them sit there unnoticed.

_MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
_MONTHS_EN = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
_MONTH_NUM = {m: i + 1 for i, m in enumerate(_MONTHS_ES)}
_MONTH_NUM.update({m: i + 1 for i, m in enumerate(_MONTHS_EN)})

_MENTIONS_BIRTHDAY = re.compile(r"birthday|cumplea", re.I)
_DATE_EN = re.compile(r"\b(" + "|".join(_MONTHS_EN) + r")\s+(\d{1,2})\b", re.I)
_DATE_ES = re.compile(r"\b(\d{1,2})\s+de\s+(" + "|".join(_MONTHS_ES) + r")\b", re.I)
_NAME_PATTERNS = [
    re.compile(r"['\"]([^'\"]{2,40})['\"]"),                       # named 'Amistaa'
    re.compile(r"\bnamed\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]*)", re.U),  # named Amistaa
    re.compile(r"\bllamad[oa]\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]*)", re.U),
]


def format_date_es(month: int, day: int) -> str:
    """'29 de mayo' — for showing a birthday back to the owner."""
    return f"{day} de {_MONTHS_ES[month - 1]}"


def _extract_birthday(fact: str) -> tuple[str, int, int] | None:
    """Parses '...named X whose birthday is May 29' → ('X', 5, 29). None if absent."""
    if not _MENTIONS_BIRTHDAY.search(fact):
        return None

    if m := _DATE_EN.search(fact):
        month, day = _MONTH_NUM[m.group(1).lower()], int(m.group(2))
    elif m := _DATE_ES.search(fact):
        month, day = _MONTH_NUM[m.group(2).lower()], int(m.group(1))
    else:
        return None
    if not (1 <= day <= 31):
        return None

    for pattern in _NAME_PATTERNS:
        if n := pattern.search(fact):
            return n.group(1).strip(), month, day
    return None


def find_unscheduled_birthdays(
    facts: list[str], contacts_json: str
) -> list[tuple[str, int, int]]:
    """
    Returns (name, month, day) for every birthday found in memory facts whose
    person is NOT in BIRTHDAY_CONTACTS — i.e. birthdays that would silently
    never be celebrated. Sorted by name.
    """
    try:
        contacts = json.loads(contacts_json) if contacts_json else []
    except Exception:
        contacts = []
    known = {str(c.get("name", "")).strip().lower() for c in contacts}

    found: dict[str, tuple[int, int]] = {}
    for fact in facts:
        parsed = _extract_birthday(fact)
        if not parsed:
            continue
        name, month, day = parsed
        if name.lower() in known:
            continue
        found[name] = (month, day)

    return sorted((n, m, d) for n, (m, d) in found.items())
