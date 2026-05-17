"""
tools/executor.py - Routes Claude's tool calls to the right handler.
"""
import asyncio
import logging
from functools import partial
from config import config
from tools.telegram_sender import find_telegram_contact, send_telegram_message
from tools.email_sender import send_email

logger = logging.getLogger("beli.tools.executor")


async def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Executes a tool by name and returns a plain-text result."""
    logger.info(f"Executing tool: {tool_name} | inputs: {tool_input}")

    if tool_name == "find_telegram_contact":
        return await find_telegram_contact(
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH,
            name=tool_input.get("name", ""),
        )

    if tool_name == "send_telegram_message":
        return await send_telegram_message(
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH,
            nickname=tool_input.get("nickname", ""),
            message=tool_input.get("message", ""),
            telegram_id=tool_input.get("telegram_id"),
            username=tool_input.get("username"),
            contact_phone=tool_input.get("contact_phone"),
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

    logger.warning(f"Unknown tool called: {tool_name}")
    return f"Tool '{tool_name}' is not implemented yet."
