"""
tools/definitions.py - Tool schemas exposed to Claude via the Anthropic API.
"""

TOOLS = [
    {
        "name": "find_telegram_contact",
        "description": (
            "Searches the owner's Telegram contacts AND group chats by name. "
            "Use this before sending to a first-time contact or group. "
            "Returns the full name/title, @username, and ID so the owner can confirm it's the right one. "
            "Works for individual contacts, group chats, and channels."
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
            "Works for individual contacts AND group chats — the recipient or group sees it as the owner. "
            "Use this when the owner says 'dile a', 'envía al grupo', 'mándale', 'escríbele', etc. "
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
        "name": "send_whatsapp_message",
        "description": (
            "Sends a WhatsApp message FROM the owner's personal number (ghost mode). "
            "The recipient sees it as if the owner wrote it directly. "
            "Use when the owner says 'mándale por WhatsApp', 'escríbele por WhatsApp', etc. "
            "ALWAYS show a draft and wait for explicit confirmation before calling. "
            "Accepts phone number ('+525561103975') or WhatsApp chat ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Phone number ('+525561103975'), WhatsApp chat ID ('525561103975@c.us' or group '120363xxx@g.us'), or contact/group name ('Ñaños', 'Mom'). Name-based lookup is supported.",
                },
                "message": {
                    "type": "string",
                    "description": "The exact message text to send.",
                },
            },
            "required": ["recipient", "message"],
        },
    },
    {
        "name": "read_whatsapp_chats",
        "description": (
            "Reads the owner's most recent WhatsApp conversations. "
            "Use when the owner asks to check, review, or summarize their WhatsApp chats."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of recent chats to read (default 10, max 20).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "read_whatsapp_chat_history",
        "description": (
            "Reads the recent message history of a specific WhatsApp chat. "
            "Search by contact name or provide a phone number."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone_or_name": {
                    "type": "string",
                    "description": "Contact name or phone number ('+525561103975').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of messages to read (default 30, max 100).",
                },
            },
            "required": ["phone_or_name"],
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
