"""
tools/telegram_sender.py - Telegram contact/group search and messaging via Telethon.

Architecture
────────────
Private helpers (prefixed with _):
  _entity_name(entity)          → display name for any entity type
  _entity_kind(entity)          → "contact" | "group" | "channel"
  _is_muted(dialog)             → True if notifications are silenced
  _resolve_entity(client, q)    → (dialog, entity) from any identifier type
  _load_cache / _save_to_cache  → persistent contact/group cache

Public tools (called by executor.py):
  find_telegram_contact()  → searches contacts + groups, returns structured results
  send_as_owner()          → sends FROM owner's personal account (ghost mode)
  read_telegram_chats()    → overview of recent conversations
  read_chat_history()      → full history of a specific chat
"""
import datetime
import json
import logging
import zoneinfo
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import GetContactsRequest
from telethon.tl.types import Channel, Chat, User

logger = logging.getLogger("beli.tools.telegram_sender")

_OWNER_SESSION_PATH = str(Path(__file__).parent.parent / "data" / "telethon_session")
_CACHE_PATH         = Path(__file__).parent.parent / "data" / "contact_cache.json"


# ── Session factory ───────────────────────────────────────────────────────────

def _owner_client(api_id: int, api_hash: str) -> TelegramClient:
    """Returns a TelegramClient for the owner's account."""
    from config import config
    session = StringSession(config.OWNER_SESSION_STRING) if config.OWNER_SESSION_STRING else _OWNER_SESSION_PATH
    return TelegramClient(session, api_id, api_hash)


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_to_cache(nickname: str, name: str, telegram_id: int = None,
                   username: str = "", phone: str = "") -> None:
    cache = _load_cache()
    cache[nickname.lower()] = {
        "telegram_id": telegram_id,
        "name": name,
        "username": username or "",
        "phone": phone or "",
    }
    _CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Cached: '{nickname}' → {name} (id={telegram_id})")


# ── Entity helpers ────────────────────────────────────────────────────────────

def _entity_name(entity) -> str:
    """Returns the display name for any Telegram entity."""
    return (
        getattr(entity, "title", None)
        or f"{getattr(entity, 'first_name', '') or ''} {getattr(entity, 'last_name', '') or ''}".strip()
        or "Desconocido"
    )


def _entity_kind(entity) -> str:
    """Returns 'contact', 'group', or 'channel'."""
    if isinstance(entity, User):
        return "contact"
    if isinstance(entity, Channel):
        return "channel" if getattr(entity, "broadcast", False) else "group"
    if isinstance(entity, Chat):
        return "group"
    return "unknown"


def _is_muted(dialog) -> bool:
    """
    Returns True if the dialog's notifications are permanently or temporarily silenced.
    Handles both datetime and int representations of mute_until (Telethon varies by version).
    """
    ns = getattr(getattr(dialog, "dialog", None), "notify_settings", None)
    if not ns:
        return False
    mute_until = getattr(ns, "mute_until", None)
    if not mute_until:
        return False
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    if isinstance(mute_until, datetime.datetime):
        if mute_until.tzinfo is None:
            mute_until = mute_until.replace(tzinfo=datetime.timezone.utc)
        return mute_until > now
    # Integer fallback (Unix timestamp)
    return int(mute_until) > int(now.timestamp())


# ── Core entity resolver ──────────────────────────────────────────────────────

async def _resolve_entity(client: TelegramClient, identifier) -> tuple:
    """
    Resolves any Telegram identifier to (dialog | None, entity | None).

    Accepted identifier types:
      - int   → numeric telegram_id; searched via iter_dialogs (preserves access_hash)
      - str starting with digits / '+' → phone number; resolved via get_entity
      - str   → @username or display name; dialogs first, get_entity as fallback

    Returns (dialog, entity). dialog is None when entity was resolved via get_entity
    (no mute/unread metadata available in that case).
    """
    # ── Numeric ID: must go through dialogs to get access_hash ────────────────
    if isinstance(identifier, int):
        async for dlg in client.iter_dialogs():
            if getattr(dlg.entity, "id", None) == identifier:
                return dlg, dlg.entity
        return None, None

    if not isinstance(identifier, str):
        return None, None

    clean = identifier.lstrip("+")

    # ── Phone number ──────────────────────────────────────────────────────────
    if clean.isdigit():
        try:
            entity = await client.get_entity(identifier)
            return None, entity
        except Exception:
            return None, None

    # ── @username or display name: dialogs first ──────────────────────────────
    query = identifier.lower().lstrip("@")
    async for dlg in client.iter_dialogs():
        e     = dlg.entity
        uname = (getattr(e, "username", "") or "").lower()
        name  = _entity_name(e).lower()
        if uname == query or query in name:
            return dlg, e

    # ── Fallback: get_entity for @usernames of accounts not in recent dialogs ─
    try:
        entity = await client.get_entity(identifier)
        return None, entity
    except Exception:
        return None, None


# ── Tool 1: Find contact or group ─────────────────────────────────────────────

async def find_telegram_contact(api_id: int, api_hash: str, name: str) -> str:
    """
    Searches the owner's Telegram contacts AND group chats by name.
    Checks the confirmed-contact cache first — returns immediately if found.
    """
    logger.info(f"Searching for: '{name}'")
    search_lower = name.lower().strip()

    # Cache-first ──────────────────────────────────────────────────────────────
    cache = _load_cache()
    for nick, data in cache.items():
        cached_name = (data.get("name") or "").lower()
        if search_lower and search_lower in cached_name:
            tid   = data.get("telegram_id")
            uname = data.get("username") or ""
            logger.info(f"Cache hit: '{name}' → '{nick}' (id={tid})")
            return (
                f"'{data['name']}' ya está confirmado (nickname='{nick}', telegram_id={tid}"
                f"{', @' + uname if uname else ''}). "
                f"Envía directamente con send_as_owner(nickname='{nick}', message='...'). "
                f"NO pidas confirmación — ya fue confirmado antes."
            )

    # Live search ──────────────────────────────────────────────────────────────
    try:
        async with _owner_client(api_id, api_hash) as client:
            search  = name.lower().strip()
            matches = []  # (kind, telegram_id, display_label)

            # Individual contacts (fast path via Contacts API)
            result = await client(GetContactsRequest(hash=0))
            for c in result.users:
                first = (c.first_name or "").lower()
                last  = (c.last_name  or "").lower()
                uname = (c.username   or "").lower()
                phone = (c.phone      or "").replace(" ", "").replace("-", "")
                full  = f"{first} {last}".strip()
                if (search in full or search in uname
                        or first.startswith(search) or last.startswith(search)
                        or search.replace(" ", "").replace("-", "") in phone):
                    label = _entity_name(c)
                    if c.username:
                        label += f" (@{c.username})"
                    if c.phone:
                        label += f" | +{c.phone}"
                    matches.append(("contact", c.id, label))

            # Groups and channels (via dialogs)
            seen_ids = {tid for _, tid, _ in matches}
            async for dlg in client.iter_dialogs():
                e = dlg.entity
                if isinstance(e, User):
                    continue
                title = getattr(e, "title", "") or ""
                if search in title.lower() and e.id not in seen_ids:
                    kind  = _entity_kind(e)
                    label = title
                    uname = getattr(e, "username", "") or ""
                    if uname:
                        label += f" (@{uname})"
                    matches.append((kind, e.id, label))

            if not matches:
                return (
                    f"No encontré ningún contacto ni grupo llamado '{name}' en Telegram. "
                    f"Intenta con otro nombre o proporciona el @username o ID exacto."
                )

            kind_es = {"contact": "contacto", "group": "grupo", "channel": "canal"}

            if len(matches) == 1:
                kind, tid, label = matches[0]
                return (
                    f"Encontré 1 {kind_es.get(kind, kind)}: {label} (telegram_id={tid}).\n\n"
                    f"Confirma con el propietario que es el correcto y luego usa "
                    f"send_as_owner(nickname='...', telegram_id={tid}, message='...')."
                )

            lines = "\n".join(
                f"  {i+1}. [{kind_es.get(k, k)}] {lbl} (id={tid})"
                for i, (k, tid, lbl) in enumerate(matches)
            )
            return f"Encontré {len(matches)} resultados para '{name}':\n{lines}\n\nPregúntale al propietario cuál es el correcto."

    except Exception as e:
        logger.exception(f"Error searching contacts/groups: {e}")
        return f"Error al buscar en Telegram: {e}"


# ── Tool 2: Send as owner (ghost mode) ────────────────────────────────────────

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
    Sends a message FROM the owner's personal Telegram account.
    Works for individual contacts AND group chats.
    Requires explicit owner confirmation before calling.
    """
    cache  = _load_cache()
    cached = cache.get(nickname.lower())

    if username:
        username = username.lstrip("@")

    # Determine lookup identifier (priority: explicit args > cache)
    if telegram_id:
        identifier = int(telegram_id)
    elif username:
        identifier = username
    elif contact_phone:
        identifier = contact_phone
    elif cached:
        identifier = (
            int(cached["telegram_id"]) if cached.get("telegram_id")
            else cached.get("username") or cached.get("phone")
        )
        if not identifier:
            return f"'{nickname}' está en caché pero sin ID, @username ni teléfono."
    else:
        return (
            f"No tengo forma de contactar a '{nickname}'. "
            f"Proporciona telegram_id, @username, o teléfono; "
            f"o usa find_telegram_contact para buscarlo primero."
        )

    logger.info(f"[Ghost] Sending to '{nickname}' (identifier={identifier!r})")

    try:
        async with _owner_client(api_id, api_hash) as client:
            dialog, entity = await _resolve_entity(client, identifier)

            if entity is None:
                return (
                    f"No pude encontrar '{nickname}' (identifier={identifier!r}) en Telegram. "
                    f"Usa find_telegram_contact para obtener el telegram_id correcto."
                )

            # Block sends to muted groups — they're silenced intentionally
            if dialog and _is_muted(dialog) and isinstance(entity, (Channel, Chat)):
                return (
                    f"El grupo '{_entity_name(entity)}' está silenciado. "
                    f"No envío mensajes a grupos silenciados para no interrumpir sin querer. "
                    f"Desactiva el silencio en Telegram primero si quieres enviar."
                )

            await client.send_message(entity, message)

            name_out = _entity_name(entity)
            uname    = getattr(entity, "username", "") or ""
            logger.info(f"[Ghost] Sent as owner → {name_out} (id={getattr(entity, 'id', '?')})")

            # Update cache for individual contacts
            if isinstance(entity, User):
                _save_to_cache(
                    nickname=nickname,
                    name=name_out,
                    telegram_id=getattr(entity, "id", None),
                    username=uname,
                    phone=contact_phone or (cached or {}).get("phone", ""),
                )

            return (
                f"✓ ENVIADO EXITOSAMENTE como tú a {name_out}"
                f"{' (@' + uname + ')' if uname else ''}."
            )

    except FloodWaitError as e:
        return f"Telegram pidió esperar {e.seconds} segundos antes de enviar más mensajes."
    except Exception as e:
        logger.exception(f"[Ghost] Error sending to '{nickname}': {e}")
        return f"Error al enviar el mensaje: {e}"


# ── Tool 3: Read recent chats (overview) ─────────────────────────────────────

async def read_telegram_chats(api_id: int, api_hash: str, limit: int = 5, timezone: str = "America/Mexico_City") -> str:
    """
    Reads the owner's most recent Telegram conversations, including all folders.
    Returns a summary with sender, last message preview, unread count, and timestamp.
    """
    limit = min(max(1, limit), 30)
    logger.info(f"Reading {limit} most recent chats (all folders).")

    try:
        async with _owner_client(api_id, api_hash) as client:
            # Fetch from all folders to catch archived/muted channels too
            all_dialogs: list = []
            seen_ids: set = set()
            for folder in (0, 1):  # 0 = main, 1 = archived
                try:
                    folder_dialogs = await client.get_dialogs(limit=limit, folder=folder)
                    for d in folder_dialogs:
                        did = d.id if hasattr(d, "id") else id(d)
                        if did not in seen_ids:
                            seen_ids.add(did)
                            all_dialogs.append(d)
                except Exception:
                    pass

            # Sort by last message date descending and cap to limit
            all_dialogs.sort(
                key=lambda d: d.message.date if d.message and d.message.date else __import__("datetime").datetime.min.replace(tzinfo=__import__("datetime").timezone.utc),
                reverse=True,
            )
            dialogs = all_dialogs[:limit]

            if not dialogs:
                return "No encontré conversaciones recientes en Telegram."

            lines = []
            for i, dialog in enumerate(dialogs, 1):
                entity = dialog.entity
                name   = _entity_name(entity)
                if isinstance(entity, User) and entity.username:
                    name += f" (@{entity.username})"

                msg = dialog.message
                if msg and msg.text:
                    preview = msg.text[:80] + ("…" if len(msg.text) > 80 else "")
                    sender  = "Tú" if msg.out else name.split("(")[0].strip()
                    unread  = f" [{dialog.unread_count} sin leer]" if dialog.unread_count else ""
                    try:
                        tz_info = zoneinfo.ZoneInfo(timezone)
                    except Exception:
                        tz_info = zoneinfo.ZoneInfo("America/Mexico_City")
                    ts      = msg.date.astimezone(tz_info).strftime("%d/%m/%Y %H:%M") if msg.date else ""
                    lines.append(f"{i}. {name}{unread} — {ts}\n   {sender}: {preview}")
                else:
                    lines.append(f"{i}. {name} — (sin mensajes de texto)")

            return "Tus últimas conversaciones en Telegram:\n\n" + "\n\n".join(lines)

    except Exception as e:
        logger.exception(f"Error reading chats: {e}")
        return f"Error al leer los chats de Telegram: {e}"


# ── Media helpers ─────────────────────────────────────────────────────────────

async def _download_msg_media(client: TelegramClient, msg) -> bytes | None:
    """Downloads a Telethon message's media to bytes. Returns None on failure."""
    try:
        import io
        buf = io.BytesIO()
        await client.download_media(msg, file=buf)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.warning(f"[Telegram] Media download failed for msg {msg.id}: {e}")
        return None


async def _describe_image(api_key: str, image_bytes: bytes, caption: str = "") -> str:
    """Describes an image via Claude Vision. Delegates to tools/vision.py."""
    from tools.vision import describe_image
    return await describe_image(api_key, image_bytes, caption)


# ── Tool 4: Read full history of a specific chat ──────────────────────────────

async def _process_single_message(
    client,
    msg,
    entity,
    transcriber,
    groq_api_key: str,
    anthropic_api_key: str,
    timezone: str = "America/Mexico_City",
) -> str | None:
    """
    Processes one Telegram message into a formatted string.
    Returns None for service messages that should be skipped.
    All media operations (download + Vision/Whisper) happen here so they
    can be run concurrently via asyncio.gather.
    """
    try:
        tz_info = zoneinfo.ZoneInfo(timezone)
    except Exception:
        tz_info = zoneinfo.ZoneInfo("America/Mexico_City")
    ts = msg.date.astimezone(tz_info).strftime("%d/%m/%Y %H:%M") if msg.date else ""

    if msg.out:
        sender = "Tú"
    elif isinstance(entity, User):
        sender = (entity.first_name or "Contacto").strip()
    elif msg.sender:
        sender = (getattr(msg.sender, "first_name", "") or "Miembro").strip()
    else:
        sender = "Miembro"

    if msg.text:
        body = msg.text[:200]

    elif msg.voice or msg.audio:
        if transcriber:
            audio_bytes = await _download_msg_media(client, msg)
            if audio_bytes:
                filename = "voice.ogg" if msg.voice else "audio.mp3"
                text = transcriber(groq_api_key, audio_bytes, filename)
                body = f"[Audio] {text}" if not text.startswith("ERROR:") else "[audio — no se pudo transcribir]"
            else:
                body = "[audio — no se pudo descargar]"
        else:
            body = "[audio]"

    elif msg.photo:
        caption = msg.message or ""
        if anthropic_api_key:
            image_bytes = await _download_msg_media(client, msg)
            if image_bytes:
                description = await _describe_image(anthropic_api_key, image_bytes, caption)
                body = f"[Imagen] {description}"
            else:
                body = "[imagen — no se pudo descargar]"
        else:
            body = f"[imagen{': ' + caption if caption else ''}]"

    elif msg.sticker:
        body = "[sticker]"

    elif msg.video:
        body = f"[video{': ' + msg.message if msg.message else ''}]"

    elif msg.document:
        fname = ""
        if msg.document.attributes:
            for attr in msg.document.attributes:
                fname = getattr(attr, "file_name", "") or ""
                if fname:
                    break
        body = f"[archivo: {fname}]" if fname else "[archivo]"

    else:
        return None  # service messages, polls, etc.

    return f"[{ts}] {sender}: {body}"


async def read_chat_history(
    api_id: int,
    api_hash: str,
    chat_name: str,
    limit: int = 30,
    groq_api_key: str = "",
    anthropic_api_key: str = "",
    timezone: str = "America/Mexico_City",
) -> str:
    """
    Reads the recent message history of a specific Telegram chat by name.
    Works for individual contacts, groups, and channels.
    Transcribes voice/audio messages via Groq Whisper if groq_api_key is set.
    Describes images via Claude Vision if anthropic_api_key is set.
    All media (images + audio) is processed concurrently for speed.
    """
    import asyncio

    limit = min(max(1, limit), 100)
    logger.info(f"Reading chat history for '{chat_name}' (last {limit} messages).")

    try:
        async with _owner_client(api_id, api_hash) as client:
            dialog, entity = await _resolve_entity(client, chat_name)

            if entity is None:
                return f"No encontré ninguna conversación llamada '{chat_name}' en Telegram."

            transcriber = None
            if groq_api_key:
                try:
                    from tools.transcriber import transcribe_audio
                    transcriber = transcribe_audio
                except ImportError:
                    logger.warning("[Telegram] transcriber module not available")

            # Collect all raw messages first (fast — no media processing yet)
            raw_msgs = [msg async for msg in client.iter_messages(entity, limit=limit)]

            # Process all messages concurrently (downloads + Vision/Whisper in parallel)
            results = await asyncio.gather(*[
                _process_single_message(client, msg, entity, transcriber, groq_api_key, anthropic_api_key, timezone)
                for msg in raw_msgs
            ])

            # Filter out skipped service messages and reverse to chronological order
            messages = [r for r in reversed(results) if r is not None]

            if not messages:
                return f"No encontré mensajes en la conversación con '{chat_name}'."

            total = len(messages)

            # ── Pre-compute last-3 per sender (put at the TOP so Claude reads it first) ──
            from collections import defaultdict
            sender_msgs: dict[str, list[tuple[int, str]]] = defaultdict(list)
            for i, msg in enumerate(messages, 1):
                if "] " in msg:
                    rest = msg.split("] ", 1)[1]
                    if ": " in rest:
                        sender_name = rest.split(": ", 1)[0]
                        sender_msgs[sender_name].append((i, msg))

            summary_parts = [
                "╔══ ÚLTIMOS MENSAJES POR REMITENTE ══╗",
                "(Usa esta sección para responder preguntas sobre los últimos N mensajes de alguien.)",
            ]
            for sender, msgs in sorted(sender_msgs.items()):
                last3 = msgs[-3:]
                summary_parts.append(
                    f"\n{sender} — últimos {min(3, len(msgs))} de {len(msgs)} mensajes (el más reciente al final):"
                )
                for num, m in last3:
                    summary_parts.append(f"  [#{num}/{total}] {m}")
            summary_parts.append("╚══════════════════════════════════╝\n")
            summary_str = "\n".join(summary_parts) + "\n"

            # ── Numbered full history ─────────────────────────────────────────────────
            header = (
                f"Historial completo del chat de Telegram con '{chat_name}' — "
                f"{total} mensajes en ORDEN CRONOLÓGICO (el más antiguo primero = #1, el más reciente al final = #{total}).\n"
                f"Cada línea: [#N/{total}] [dd/mm/YYYY HH:MM] Remitente: mensaje\n"
            )
            numbered = [f"[#{i}/{total}] {msg}" for i, msg in enumerate(messages, 1)]

            return summary_str + header + "\n".join(numbered)

    except Exception as e:
        logger.exception(f"Error reading chat history for '{chat_name}': {e}")
        return f"Error al leer el historial de '{chat_name}': {e}"
