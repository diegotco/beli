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

logger = logging.getLogger("beli.tools.executor")

# Lazy-loaded memory manager reference (set by main.py at startup)
_memory = None

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

    logger.warning(f"Unknown tool called: {tool_name}")
    return f"Tool '{tool_name}' is not implemented yet."
