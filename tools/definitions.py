"""
tools/definitions.py - Tool schemas exposed to Claude via the Anthropic API.
"""

TOOLS = [
    {
        "name": "find_telegram_contact",
        "description": (
            "Searches the owner's real Telegram contact list by name and returns who was found. "
            "Use this FIRST before sending any message to a first-time contact. "
            "Returns the contact's full name, @username, and ID so the owner can confirm it's the right person. "
            "If the owner uses a nickname, look up the real name in their profile (owner-profile.md) before calling this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The contact's real first name to search for.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "send_telegram_message",
        "description": (
            "Sends a Telegram message to a contact. "
            "ALWAYS try this tool first using just the nickname — if the contact was confirmed before, "
            "it will send immediately without needing anything else. "
            "Only call find_telegram_contact if this tool returns an error saying the contact is not found. "
            "If you already know the @username (e.g. from a screenshot), pass it directly via the 'username' field — "
            "no need to call find_telegram_contact at all."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nickname": {
                    "type": "string",
                    "description": "The owner's nickname for this contact (e.g. 'mom', 'boss'). Used as cache key.",
                },
                "telegram_id": {
                    "type": "integer",
                    "description": "Telegram user ID returned by find_telegram_contact. Use when available.",
                },
                "username": {
                    "type": "string",
                    "description": (
                        "Telegram @username of the recipient (e.g. '@some_bot' or 'some_bot'). "
                        "Works for regular users AND bots. Use this whenever you know the @username — "
                        "it is the most reliable identifier and does NOT require the person to be in the owner's contacts."
                    ),
                },
                "contact_phone": {
                    "type": "string",
                    "description": (
                        "Phone number in international format (e.g. '+15550001234'). "
                        "Use this when the contact has no @username and no telegram_id."
                    ),
                },
                "message": {
                    "type": "string",
                    "description": "The exact message text to send.",
                },
            },
            "required": ["nickname", "message"],
        },
    },
    {
        "name": "read_telegram_chats",
        "description": (
            "Reads the owner's most recent Telegram conversations and returns a summary. "
            "Use this when the owner asks to check, review, or summarize their Telegram chats. "
            "Returns the sender name, last message, and timestamp for each chat."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of recent chats to read (default 5, max 20).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "read_chat_history",
        "description": (
            "Reads the recent message history of a specific Telegram chat or contact. "
            "Use this when the owner asks to summarize, review, or search messages inside a specific conversation. "
            "Search by the contact or group name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "chat_name": {
                    "type": "string",
                    "description": "Name of the contact or group to read (e.g. 'Work Group', 'John').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of recent messages to fetch (default 30, max 100).",
                },
            },
            "required": ["chat_name"],
        },
    },
    {
        "name": "send_as_owner",
        "description": (
            "Sends a Telegram message FROM the owner's personal account (ghost mode). "
            "The recipient sees the message as if the owner wrote it directly — Beli's account is NOT shown. "
            "Use this when the owner says 'respóndele', 'dile', 'mándale', 'escríbele' referring to a reply "
            "they want to send AS THEMSELVES. "
            "ALWAYS show a draft first and wait for explicit confirmation before calling this tool. "
            "Never use this tool without the owner's explicit 'sí', 'dale', 'envíalo', or equivalent confirmation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nickname": {
                    "type": "string",
                    "description": "The owner's nickname for this contact (e.g. 'mom', 'carlos'). Used as cache key.",
                },
                "telegram_id": {
                    "type": "integer",
                    "description": "Telegram user ID. Use when available (from cache or contact search).",
                },
                "username": {
                    "type": "string",
                    "description": "Telegram @username of the recipient (without @).",
                },
                "contact_phone": {
                    "type": "string",
                    "description": "Phone in international format (e.g. '+15550001234').",
                },
                "message": {
                    "type": "string",
                    "description": "The exact message text to send as the owner.",
                },
            },
            "required": ["nickname", "message"],
        },
    },
    {
        "name": "send_email",
        "description": (
            "Sends an email from Beli's address (beli@agentmail.to) on the owner's behalf. "
            "Use when the owner asks to send an email. "
            "If the owner provides an email address directly in their message (e.g. 'envía un correo a foo@bar.com'), "
            "use that address as `to` — do NOT ask who the recipient is. "
            "If the owner mentions a contact name instead of an email, look it up in contacts.json. "
            "Draft a subject and body based on the owner's instructions, show the draft, and ask for confirmation before sending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": (
                        "Recipient email address. "
                        "Extract directly from the owner's message if they provide one. "
                        "If the owner gives a contact name, use their email from contacts.json."
                    ),
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject — infer from the owner's instructions if not explicitly stated.",
                },
                "body": {
                    "type": "string",
                    "description": "Full email body. Write it based on the owner's instructions.",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
]
