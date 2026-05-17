"""
tools/telegram_sender.py - Telegram contact search and message sending via Telethon.

Two-step flow for safety:
  1. find_telegram_contact() → returns match details for Diego to confirm
  2. send_telegram_message()  → sends using the confirmed telegram_id, then caches
"""
import json
import logging
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import FloodWaitError, UsernameNotOccupiedError
from telethon.tl.functions.contacts import GetContactsRequest, ImportContactsRequest
from telethon.tl.types import InputPhoneContact

logger = logging.getLogger("beli.tools.telegram_sender")

_DIEGO_SESSION_PATH = str(Path(__file__).parent.parent / "data" / "telethon_session")
_BELI_SESSION_PATH  = str(Path(__file__).parent.parent / "data" / "beli_session")
_CACHE_PATH         = Path(__file__).parent.parent / "data" / "contact_cache.json"

# Shared Beli client — set by BeliListener on startup so send_telegram_message
# reuses the already-open connection instead of creating a second one.
_shared_beli_client = None

def set_shared_beli_client(client) -> None:
    global _shared_beli_client
    _shared_beli_client = client
    logger.info("Shared Beli Telegram client registered.")


# ── Cache helpers ────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_to_cache(nickname: str, name: str, telegram_id: int = None, username: str = "", phone: str = "") -> None:
    cache = _load_cache()
    cache[nickname.lower()] = {
        "telegram_id": telegram_id,
        "name": name,
        "username": username or "",
        "phone": phone or "",
    }
    _CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Cached contact: '{nickname}' → {name} (id={telegram_id}, phone={phone})")


# ── Tool 1: Find contact ─────────────────────────────────────────────────────

async def find_telegram_contact(api_id: int, api_hash: str, name: str) -> str:
    """
    Searches Diego's Telegram contacts by name.
    Checks the confirmed-contact cache first — if a match is found there,
    returns immediately without hitting the Telegram API and without asking
    Diego for confirmation (it was already confirmed in a prior session).
    """
    logger.info(f"Searching Telegram contacts for: '{name}'")
    search_lower = name.lower().strip()

    # ── Cache-first: skip API call if already confirmed ──────────────────────
    cache = _load_cache()
    for nick, data in cache.items():
        cached_name = (data.get("name") or "").lower()
        if search_lower and search_lower in cached_name:
            tid    = data.get("telegram_id")
            uname  = data.get("username") or ""
            logger.info(f"Cache hit for '{name}' → nickname='{nick}' (id={tid})")
            return (
                f"Contacto '{data['name']}' ya confirmado previamente "
                f"(nickname='{nick}', telegram_id={tid}"
                f"{', @' + uname if uname else ''}). "
                f"Envía el mensaje directamente con "
                f"send_telegram_message(nickname='{nick}', message='...'). "
                f"NO pidas confirmación a Diego — ya fue confirmado antes."
            )

    # ── Live search via Telegram API (uses Diego's session = his contact list) ─
    try:
        async with TelegramClient(_DIEGO_SESSION_PATH, api_id, api_hash) as client:
            result = await client(GetContactsRequest(hash=0))
            all_contacts = result.users
            search = name.lower().strip()
            matches = []

            for contact in all_contacts:
                first    = (contact.first_name or "").lower()
                last     = (contact.last_name  or "").lower()
                username = (contact.username   or "").lower()
                phone    = (contact.phone      or "").replace(" ", "").replace("-", "")
                full     = f"{first} {last}".strip()

                if (search in full or search in username or
                        first.startswith(search) or last.startswith(search) or
                        search.replace(" ", "").replace("-", "") in phone):
                    matches.append(contact)

            if not matches:
                return (
                    f"No encontré ningún contacto llamado '{name}' en la lista de Telegram de Diego. "
                    f"Pídele a Diego que te dé el @username o número de teléfono exacto."
                )

            def _format_contact(c, index=None) -> str:
                full_name = f"{c.first_name or ''} {c.last_name or ''}".strip()
                uname = f"@{c.username}" if c.username else "sin @username"
                phone = f"+{c.phone}" if c.phone else "sin teléfono"
                prefix = f"  {index}. " if index is not None else "  "
                return f"{prefix}{full_name} | {uname} | {phone} | ID: {c.id}"

            if len(matches) == 1:
                c = matches[0]
                phone_val = f"+{c.phone}" if c.phone else ""
                return (
                    f"Encontré 1 contacto:\n{_format_contact(c)}\n\n"
                    f"{'Este contacto solo tiene número de teléfono (' + phone_val + '), sin @username. Puedes enviarle el mensaje usando contact_phone=' + phone_val + '.' if phone_val and not c.username else ''}"
                    f"Muéstrale estos datos a Diego y confirma que es la persona correcta antes de enviar."
                )

            # Multiple matches
            lines = "\n".join(_format_contact(c, i+1) for i, c in enumerate(matches))
            return (
                f"Encontré {len(matches)} contactos que coinciden con '{name}':\n{lines}\n\n"
                f"Pregúntale a Diego cuál es el correcto."
            )

    except Exception as e:
        logger.exception(f"Error searching contacts: {e}")
        return f"Error al buscar en los contactos de Telegram: {e}"


# ── Tool 2: Send message ─────────────────────────────────────────────────────

async def send_telegram_message(
    api_id: int,
    api_hash: str,
    nickname: str,
    message: str,
    telegram_id: int | None = None,
    contact_phone: str | None = None,
    username: str | None = None,
) -> str:
    """
    Sends a Telegram message using:
    - telegram_id (int): direct Telegram user ID
    - username (str): @username, works for users AND bots (e.g. '@hermes_de_diego_bot')
    - contact_phone (str): phone in international format e.g. '+19293959561'
    - nickname only: looks up in cache
    """
    cache = _load_cache()
    cached = cache.get(nickname.lower())

    # Normalize username — strip leading @ if present
    if username:
        username = username.lstrip("@")

    # Resolve identifier — prefer explicit args, fall back to cache
    if telegram_id:
        identifier = int(telegram_id)
        logger.info(f"Using telegram_id={telegram_id} for '{nickname}'")
    elif username:
        identifier = username          # Telethon resolves @username natively
        logger.info(f"Using username=@{username} for '{nickname}'")
    elif contact_phone:
        identifier = contact_phone
        logger.info(f"Using phone={contact_phone} for '{nickname}'")
    elif cached:
        if cached.get("telegram_id"):
            identifier = int(cached["telegram_id"])
        elif cached.get("username"):
            identifier = cached["username"]
        elif cached.get("phone"):
            identifier = cached["phone"]
        else:
            return f"El contacto '{nickname}' está en caché pero sin ID, @username ni teléfono. Usa find_telegram_contact de nuevo."
        logger.info(f"Cache hit: '{nickname}' → {cached['name']} ({identifier})")
    else:
        return (
            f"No tengo forma de contactar a '{nickname}'. "
            f"Proporciona telegram_id, @username, o teléfono."
        )

    # Phone number to use as fallback (for new accounts with no prior contact history)
    phone_fallback = contact_phone or (cached or {}).get("phone", "") if cached else contact_phone

    async def _do_send(client) -> str:
        nonlocal identifier
        try:
            entity = await client.get_entity(identifier)
        except Exception as e:
            # Beli's account is new — it may lack the access_hash for this user.
            # Import via phone number to resolve the entity.
            if phone_fallback:
                logger.info(f"get_entity failed ({e}), trying phone import: {phone_fallback}")
                # Use real name from cache; fall back to nickname
                cached_name = (cached or {}).get("name", "") or nickname.capitalize()
                name_parts  = cached_name.split()
                first       = name_parts[0] if name_parts else nickname.capitalize()
                last        = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
                result = await client(ImportContactsRequest([
                    InputPhoneContact(client_id=0, phone=phone_fallback, first_name=first, last_name=last)
                ]))
                if result.users:
                    entity = result.users[0]
                else:
                    return f"No se pudo resolver el contacto. Verifica que el número {phone_fallback} esté en Telegram."
            else:
                raise
        await client.send_message(entity, message)

        full_name = f"{getattr(entity, 'first_name', '') or ''} {getattr(entity, 'last_name', '') or ''}".strip()
        username  = getattr(entity, "username", "") or ""
        entity_id = getattr(entity, "id", None)

        _save_to_cache(
            nickname=nickname,
            name=full_name,
            telegram_id=entity_id,
            username=username,
            phone=contact_phone or (cached or {}).get("phone", ""),
        )
        logger.info(f"Message sent to {full_name} (id={entity_id})")
        return f"✓ ENVIADO EXITOSAMENTE a {full_name} ({'@'+username if username else contact_phone or 'sin @username'})."

    try:
        # Prefer the shared client (already open by the listener) to avoid session lock
        if _shared_beli_client and _shared_beli_client.is_connected():
            logger.info("Using shared Beli client for sending.")
            return await _do_send(_shared_beli_client)
        else:
            async with TelegramClient(_BELI_SESSION_PATH, api_id, api_hash) as client:
                return await _do_send(client)

    except FloodWaitError as e:
        return f"Telegram pidió esperar {e.seconds} segundos antes de enviar más mensajes."
    except Exception as e:
        logger.exception(f"Error sending message ({identifier}): {e}")
        return f"Error al enviar el mensaje: {e}"
