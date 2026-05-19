"""
tools/telegram_sender.py - Telegram contact search and message sending via Telethon.

Flow:
  1. find_telegram_contact() → searches owner's contacts AND groups, returns who/what was found
  2. send_as_owner()         → sends FROM the owner's personal account (ghost mode) — works for
                               both individual contacts and group chats
  3. read_telegram_chats()   → overview of recent conversations
  4. read_chat_history()     → full history of a specific chat
"""
import json
import logging
from pathlib import Path

import datetime

from telethon import TelegramClient
from telethon.errors import FloodWaitError, UsernameNotOccupiedError
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import GetContactsRequest
from telethon.tl.types import User, Channel, Chat

logger = logging.getLogger("beli.tools.telegram_sender")

_OWNER_SESSION_PATH = str(Path(__file__).parent.parent / "data" / "telethon_session")
_CACHE_PATH         = Path(__file__).parent.parent / "data" / "contact_cache.json"


def _owner_client(api_id: int, api_hash: str) -> TelegramClient:
    """Returns a TelegramClient for the owner's account (StringSession in cloud, file locally)."""
    from config import config
    session = StringSession(config.OWNER_SESSION_STRING) if config.OWNER_SESSION_STRING else _OWNER_SESSION_PATH
    return TelegramClient(session, api_id, api_hash)


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
    Searches the owner's Telegram contacts by name.
    Checks the confirmed-contact cache first — if a match is found there,
    returns immediately without hitting the Telegram API and without asking
    the owner for confirmation (it was already confirmed in a prior session).
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
                f"send_as_owner(nickname='{nick}', message='...'). "
                f"NO pidas confirmación — ya fue confirmado antes."
            )

    # ── Live search via Telegram API — contacts + groups ────────────────────────
    try:
        async with _owner_client(api_id, api_hash) as client:
            search = name.lower().strip()
            matches = []  # list of (label, telegram_id, type, extra)

            # 1. Individual contacts
            result = await client(GetContactsRequest(hash=0))
            for c in result.users:
                first    = (c.first_name or "").lower()
                last     = (c.last_name  or "").lower()
                uname    = (c.username   or "").lower()
                phone    = (c.phone      or "").replace(" ", "").replace("-", "")
                full     = f"{first} {last}".strip()
                if (search in full or search in uname or
                        first.startswith(search) or last.startswith(search) or
                        search.replace(" ", "").replace("-", "") in phone):
                    label = f"{c.first_name or ''} {c.last_name or ''}".strip()
                    if c.username:
                        label += f" (@{c.username})"
                    if c.phone:
                        label += f" | +{c.phone}"
                    matches.append(("contact", c.id, label))

            # 2. Group chats and channels
            async for dialog in client.iter_dialogs():
                entity = dialog.entity
                if isinstance(entity, User):
                    continue  # already covered above
                title = getattr(entity, "title", "") or ""
                if search in title.lower():
                    kind  = "channel" if isinstance(entity, Channel) and getattr(entity, "broadcast", False) else "group"
                    uname = getattr(entity, "username", "") or ""
                    label = title
                    if uname:
                        label += f" (@{uname})"
                    matches.append((kind, entity.id, label))

            if not matches:
                return (
                    f"No encontré ningún contacto ni grupo llamado '{name}' en Telegram. "
                    f"Intenta con otro nombre o pide al propietario el @username o ID exacto."
                )

            if len(matches) == 1:
                kind, tid, label = matches[0]
                kind_es = {"contact": "contacto", "group": "grupo", "channel": "canal"}.get(kind, kind)
                return (
                    f"Encontré 1 {kind_es}: {label} (telegram_id={tid}).\n\n"
                    f"Muéstrale esto al propietario y confirma que es correcto antes de enviar. "
                    f"Luego usa send_as_owner(nickname='...', telegram_id={tid}, message='...')."
                )

            lines = "\n".join(
                f"  {i+1}. [{{'contact':'contacto','group':'grupo','channel':'canal'}}.get(k, k)}] {lbl} (id={tid})"
                for i, (k, tid, lbl) in enumerate(matches)
            )
            return (
                f"Encontré {len(matches)} resultados para '{name}':\n{lines}\n\n"
                f"Pregúntale al propietario cuál es el correcto."
            )

    except Exception as e:
        logger.exception(f"Error searching contacts/groups: {e}")
        return f"Error al buscar en Telegram: {e}"


# ── Tool 2: Send as owner (ghost mode) ───────────────────────────────────────

async def send_as_owner(
    api_id: int,
    api_hash: str,
    nickname: str,
    message: str,
    telegram_id: int | None = None,
    username: str | None = None,
    contact_phone: str | None = None,
) -> str:
    """
    Sends a message FROM the owner's personal Telegram account (ghost mode).
    The recipient sees the message as coming from the owner, not from Beli.
    Requires explicit owner confirmation before calling.
    """
    cache = _load_cache()
    cached = cache.get(nickname.lower())

    if username:
        username = username.lstrip("@")

    # Resolve identifier
    if telegram_id:
        identifier = int(telegram_id)
        logger.info(f"[Ghost] Using telegram_id={telegram_id} for '{nickname}'")
    elif username:
        identifier = username
        logger.info(f"[Ghost] Using @{username} for '{nickname}'")
    elif contact_phone:
        identifier = contact_phone
        logger.info(f"[Ghost] Using phone={contact_phone} for '{nickname}'")
    elif cached:
        if cached.get("telegram_id"):
            identifier = int(cached["telegram_id"])
        elif cached.get("username"):
            identifier = cached["username"]
        elif cached.get("phone"):
            identifier = cached["phone"]
        else:
            return f"El contacto '{nickname}' está en caché pero sin ID, @username ni teléfono."
        logger.info(f"[Ghost] Cache hit: '{nickname}' → {cached['name']} ({identifier})")
    else:
        return (
            f"No tengo forma de contactar a '{nickname}'. "
            f"Proporciona telegram_id, @username, o teléfono."
        )

    try:
        async with _owner_client(api_id, api_hash) as client:
            entity = None

            # Try direct resolution first
            try:
                entity = await client.get_entity(identifier)
            except Exception:
                pass

            # Fallback: search dialogs by name (catches groups, channels, and contacts
            # not yet in Telegram's local cache)
            if entity is None:
                search = str(identifier).lower()
                async for dialog in client.iter_dialogs():
                    e = dialog.entity
                    title = (
                        getattr(e, "title", None)
                        or f"{getattr(e, 'first_name', '') or ''} {getattr(e, 'last_name', '') or ''}".strip()
                    )
                    if search in title.lower():
                        entity = e
                        logger.info(f"[Ghost] Resolved '{identifier}' via dialog search → {title}")
                        break

            if entity is None:
                return (
                    f"No pude encontrar '{nickname}' en tus chats de Telegram. "
                    f"Usa find_telegram_contact para buscarlo primero."
                )

            await client.send_message(entity, message)

            name_out = (
                getattr(entity, "title", None)
                or f"{getattr(entity, 'first_name', '') or ''} {getattr(entity, 'last_name', '') or ''}".strip()
                or nickname
            )
            uname = getattr(entity, "username", "") or ""
            logger.info(f"[Ghost] Sent as owner → {name_out}")
            return (
                f"✓ ENVIADO EXITOSAMENTE como tú a {name_out}"
                f"{' (@' + uname + ')' if uname else ''}."
            )

    except FloodWaitError as e:
        return f"Telegram pidió esperar {e.seconds} segundos antes de enviar más mensajes."
    except Exception as e:
        logger.exception(f"[Ghost] Error sending as owner to '{nickname}': {e}")
        return f"Error al enviar el mensaje desde tu cuenta: {e}"


async def read_telegram_chats(api_id: int, api_hash: str, limit: int = 5) -> str:
    """
    Reads the owner's most recent Telegram conversations using their own session.
    Returns a human-readable summary of each chat with sender, preview, and time.
    """
    limit = min(max(1, limit), 20)
    logger.info(f"Reading {limit} most recent Telegram chats for the owner.")

    try:
        async with _owner_client(api_id, api_hash) as client:
            dialogs = await client.get_dialogs(limit=limit)
            if not dialogs:
                return "No encontré conversaciones recientes en Telegram."

            lines = []
            for i, dialog in enumerate(dialogs, 1):
                entity = dialog.entity

                # Determine chat name
                if isinstance(entity, User):
                    name = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
                    if entity.username:
                        name += f" (@{entity.username})"
                elif isinstance(entity, (Channel, Chat)):
                    name = getattr(entity, "title", "Grupo/Canal")
                else:
                    name = "Desconocido"

                # Last message preview
                msg = dialog.message
                if msg and msg.text:
                    preview = msg.text[:80] + ("…" if len(msg.text) > 80 else "")
                    sender = "Tú" if msg.out else name.split("(")[0].strip()
                    unread = f" [{dialog.unread_count} sin leer]" if dialog.unread_count else ""
                    # Format timestamp
                    ts = msg.date.astimezone().strftime("%d %b %H:%M") if msg.date else ""
                    lines.append(f"{i}. **{name}**{unread} — {ts}\n   {sender}: {preview}")
                else:
                    lines.append(f"{i}. **{name}** — (sin mensajes de texto)")

            return "Tus últimas conversaciones en Telegram:\n\n" + "\n\n".join(lines)

    except Exception as e:
        logger.exception(f"Error reading Telegram chats: {e}")
        return f"Error al leer los chats de Telegram: {e}"


# ── Tool 4: Read full history of a specific chat ─────────────────────────────

async def read_chat_history(api_id: int, api_hash: str, chat_name: str, limit: int = 30) -> str:
    """
    Reads the recent message history of a specific Telegram chat by name.
    Returns formatted messages with sender, timestamp, and content.
    """
    limit = min(max(1, limit), 100)
    logger.info(f"Reading chat history for '{chat_name}' (last {limit} messages).")

    try:
        async with _owner_client(api_id, api_hash) as client:
            # Find the dialog by name
            search = chat_name.lower().strip()
            target = None
            async for dialog in client.iter_dialogs():
                entity = dialog.entity
                if isinstance(entity, User):
                    name = f"{entity.first_name or ''} {entity.last_name or ''}".strip()
                    username = entity.username or ""
                elif isinstance(entity, (Channel, Chat)):
                    name = getattr(entity, "title", "")
                    username = getattr(entity, "username", "") or ""
                else:
                    continue

                if search in name.lower() or search in username.lower():
                    target = dialog
                    break

            if not target:
                return f"No encontré ninguna conversación llamada '{chat_name}' en Telegram."

            # Fetch messages
            messages = []
            async for msg in client.iter_messages(target.entity, limit=limit):
                if not msg.text:
                    continue
                ts = msg.date.astimezone().strftime("%d %b %H:%M") if msg.date else ""
                if msg.out:
                    sender = "Tú"
                else:
                    entity = target.entity
                    if isinstance(entity, User):
                        sender = f"{entity.first_name or ''}".strip() or "Contacto"
                    else:
                        # Group: try to get sender name
                        if msg.sender:
                            sender = f"{getattr(msg.sender, 'first_name', '') or ''}".strip() or "Miembro"
                        else:
                            sender = "Miembro"
                messages.append(f"[{ts}] {sender}: {msg.text}")

            if not messages:
                return f"No encontré mensajes de texto en la conversación con '{chat_name}'."

            messages.reverse()  # Chronological order
            header = f"Últimos {len(messages)} mensajes de '{chat_name}':\n\n"
            return header + "\n".join(messages)

    except Exception as e:
        logger.exception(f"Error reading chat history for '{chat_name}': {e}")
        return f"Error al leer el historial de '{chat_name}': {e}"
