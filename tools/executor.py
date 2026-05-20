"""
tools/executor.py - Routes Claude's tool calls to the right handler.
"""
import asyncio
import logging
from functools import partial
from config import config
from tools.telegram_sender import find_telegram_contact, send_as_owner, read_telegram_chats, read_chat_history
from tools.whatsapp_sender import send_whatsapp_message, read_whatsapp_chats, read_whatsapp_chat_history
from tools.email_sender import send_email
from tools.calendar_tool import read_calendar_events, create_calendar_event
from tools.gmail_tool import read_gmail_inbox, read_gmail_message, send_gmail_message
from tools.tasks_tool import (
    list_task_lists,
    list_tasks,
    create_task,
    complete_task,
    delete_task,
    find_list_id_by_name,
)

logger = logging.getLogger("beli.tools.executor")

# Lazy-loaded memory manager reference (set by main.py at startup)
_memory = None

# Optional video bytes to attach on the next post_tweet call (set by Telegram handler)
_pending_video: bytes | None = None
_pending_video_filename: str = "video.mp4"

def set_pending_video(video_bytes: bytes | None, filename: str = "video.mp4") -> None:
    """Called by the Telegram channel when the user sends a video with a tweet request."""
    global _pending_video, _pending_video_filename
    _pending_video = video_bytes
    _pending_video_filename = filename

def set_memory(memory) -> None:
    """Called at startup so executor can read user preferences like timezone."""
    global _memory
    _memory = memory

async def _get_timezone() -> str:
    if _memory is None:
        return "America/Mexico_City"
    return await _memory.get_setting("timezone", "America/Mexico_City")


async def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Executes a tool by name and returns a plain-text result."""
    logger.info(f"Executing tool: {tool_name} | inputs: {tool_input}")

    if tool_name == "find_telegram_contact":
        return await find_telegram_contact(
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH,
            name=tool_input.get("name", ""),
        )

    if tool_name == "send_as_owner":
        return await send_as_owner(
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH,
            nickname=tool_input.get("nickname", ""),
            message=tool_input.get("message", ""),
            telegram_id=tool_input.get("telegram_id"),
            username=tool_input.get("username"),
            contact_phone=tool_input.get("contact_phone"),
        )

    if tool_name == "send_whatsapp_message":
        return send_whatsapp_message(
            waha_url=config.WAHA_URL,
            recipient=tool_input.get("recipient", ""),
            message=tool_input.get("message", ""),
            session=config.WAHA_SESSION,
            api_key=config.WAHA_API_KEY,
            mentions=tool_input.get("mentions"),
        )

    if tool_name == "read_whatsapp_chats":
        return read_whatsapp_chats(
            waha_url=config.WAHA_URL,
            limit=tool_input.get("limit", 10),
            session=config.WAHA_SESSION,
            api_key=config.WAHA_API_KEY,
        )

    if tool_name == "read_whatsapp_chat_history":
        tz = await _get_timezone()
        return read_whatsapp_chat_history(
            waha_url=config.WAHA_URL,
            phone_or_name=tool_input.get("phone_or_name", ""),
            limit=tool_input.get("limit", 30),
            session=config.WAHA_SESSION,
            api_key=config.WAHA_API_KEY,
            timezone=tz,
            groq_api_key=config.GROQ_API_KEY,
        )

    if tool_name == "send_email":
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(
                send_email,
                api_key=config.AGENTMAIL_API_KEY,
                inbox_id=config.AGENTMAIL_INBOX_ID,
                to=tool_input.get("to", ""),
                subject=tool_input.get("subject", ""),
                body=tool_input.get("body", ""),
            ),
        )

    if tool_name == "read_chat_history":
        return await read_chat_history(
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH,
            chat_name=tool_input.get("chat_name", ""),
            limit=tool_input.get("limit", 30),
            groq_api_key=config.GROQ_API_KEY,
            anthropic_api_key=config.ANTHROPIC_API_KEY,
        )

    if tool_name == "read_telegram_chats":
        return await read_telegram_chats(
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH,
            limit=tool_input.get("limit", 5),
        )

    if tool_name == "set_timezone":
        tz = tool_input.get("timezone", "")
        location = tool_input.get("location_name", tz)
        if _memory and tz:
            import zoneinfo
            try:
                zoneinfo.ZoneInfo(tz)
                await _memory.save_setting("timezone", tz)
                logger.info(f"Timezone updated to: {tz}")
                return f"Timezone updated to {tz} ({location})."
            except Exception:
                return f"Invalid timezone '{tz}'."
        return "No se pudo actualizar el timezone."

    if tool_name == "read_calendar_events":
        tz = await _get_timezone()
        return read_calendar_events(
            credentials_json=config.GOOGLE_CALENDAR_CREDENTIALS,
            days_ahead=tool_input.get("days_ahead", 7),
            max_results=tool_input.get("max_results", 20),
            timezone=tz,
        )

    if tool_name == "create_calendar_event":
        tz = await _get_timezone()
        return create_calendar_event(
            credentials_json=config.GOOGLE_CALENDAR_CREDENTIALS,
            title=tool_input.get("title", ""),
            start_datetime=tool_input.get("start_datetime", ""),
            end_datetime=tool_input.get("end_datetime", ""),
            description=tool_input.get("description", ""),
            location=tool_input.get("location", ""),
            timezone=tz,
        )

    # ── Google Tasks ──────────────────────────────────────────────────────────
    # Beli may only read/write "Lista de compras".
    # "Mis no negociables" and any other list are permanently blocked.

    def _safe_list_id(requested: str) -> str | None:
        """Returns the allowed list ID, or None if the request targets a blocked list."""
        # Block protected lists immediately
        if requested in config.TASKS_BLOCKED_LIST_IDS:
            return None
        # If no list specified or shopping list requested by name → dynamic lookup
        if not requested or requested == "@default" or "compras" in requested.lower():
            live_id = find_list_id_by_name(
                config.GOOGLE_CALENDAR_CREDENTIALS, "compras"
            )
            if live_id:
                return live_id
            # Fall back to hardcoded ID if lookup fails
            return config.TASKS_SHOPPING_LIST_ID
        # Allow shopping list by its hardcoded ID
        if requested == config.TASKS_SHOPPING_LIST_ID:
            return config.TASKS_SHOPPING_LIST_ID
        # Any other list: block (allowlist approach)
        return None

    if tool_name == "list_task_lists":
        # Show the real shopping list ID so Beli always uses the correct one
        live_id = find_list_id_by_name(
            config.GOOGLE_CALENDAR_CREDENTIALS, "compras"
        )
        list_id = live_id or config.TASKS_SHOPPING_LIST_ID
        return f"Lista de tareas disponible:\n• Lista de compras (id: {list_id})"

    if tool_name == "list_tasks":
        list_id = _safe_list_id(tool_input.get("list_id", ""))
        if list_id is None:
            return "No tengo acceso a esa lista."
        return list_tasks(
            credentials_json=config.GOOGLE_CALENDAR_CREDENTIALS,
            list_id=list_id,
            show_completed=tool_input.get("show_completed", False),
        )

    if tool_name == "create_task":
        list_id = _safe_list_id(tool_input.get("list_id", ""))
        if list_id is None:
            return "No tengo permiso para modificar esa lista."
        return create_task(
            credentials_json=config.GOOGLE_CALENDAR_CREDENTIALS,
            title=tool_input.get("title", ""),
            list_id=list_id,
            notes=tool_input.get("notes", ""),
            due_date=tool_input.get("due_date", ""),
        )

    if tool_name == "complete_task":
        list_id = _safe_list_id(tool_input.get("list_id", ""))
        if list_id is None:
            return "No tengo permiso para modificar esa lista."
        return complete_task(
            credentials_json=config.GOOGLE_CALENDAR_CREDENTIALS,
            task_title_or_id=tool_input.get("task_title_or_id", ""),
            list_id=list_id,
        )

    if tool_name == "delete_task":
        list_id = _safe_list_id(tool_input.get("list_id", ""))
        if list_id is None:
            return "No tengo permiso para modificar esa lista."
        return delete_task(
            credentials_json=config.GOOGLE_CALENDAR_CREDENTIALS,
            task_title_or_id=tool_input.get("task_title_or_id", ""),
            list_id=list_id,
        )

    # ── Gmail ─────────────────────────────────────────────────────────────────

    if tool_name == "read_gmail_inbox":
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(
                read_gmail_inbox,
                credentials_json=config.GMAIL_CREDENTIALS,
                max_results=tool_input.get("max_results", 10),
                unread_only=tool_input.get("unread_only", False),
            ),
        )

    if tool_name == "read_gmail_message":
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(
                read_gmail_message,
                credentials_json=config.GMAIL_CREDENTIALS,
                message_id_or_subject=tool_input.get("message_id_or_subject", ""),
            ),
        )

    if tool_name == "send_gmail_message":
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(
                send_gmail_message,
                credentials_json=config.GMAIL_CREDENTIALS,
                to=tool_input.get("to", ""),
                subject=tool_input.get("subject", ""),
                body=tool_input.get("body", ""),
                thread_id=tool_input.get("thread_id"),
            ),
        )

    if tool_name == "post_tweet":
        from tools.x_monitor import post_tweet
        global _pending_video, _pending_video_filename
        video = _pending_video if tool_input.get("has_video") else None
        filename = _pending_video_filename
        _pending_video = None  # consume once
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(
                post_tweet,
                api_key=config.X_API_KEY,
                api_secret=config.X_API_SECRET,
                bearer_token=config.X_BEARER_TOKEN,
                access_token=config.X_ACCESS_TOKEN,
                access_token_secret=config.X_ACCESS_TOKEN_SECRET,
                text=tool_input.get("text", ""),
                video_bytes=video,
                video_filename=filename,
            ),
        )

    logger.warning(f"Unknown tool called: {tool_name}")
    return f"Tool '{tool_name}' is not implemented yet."
