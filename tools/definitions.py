"""
tools/definitions.py - Tool schemas exposed to Claude via the Anthropic API.
"""

TOOLS = [
    {
        "name": "find_telegram_contact",
        "description": (
            "Searches Diego's real Telegram contact list by name and returns who was found. "
            "Use this FIRST before sending any message to a first-time contact. "
            "Returns the contact's full name, @username, and ID so Diego can confirm it's the right person. "
            "You already know nickname→real name mappings from Diego's profile: "
            "Alanis=Bernardo, Sensei=Esteban, Cetre=Silvia, Agus=Agustín, Joaco=Joaquín. "
            "Always translate the nickname to the real name before calling this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The contact's real first name to search for (e.g. 'Bernardo', 'Esteban', 'Silvia').",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "send_telegram_message",
        "description": (
            "Sends a Telegram message to a contact. "
            "For contacts already in cache (previously confirmed by Diego), call this directly. "
            "For new contacts, always call find_telegram_contact first, show Diego the result, "
            "and only call this tool after Diego explicitly confirms the recipient is correct. "
            "Pass the telegram_id returned by find_telegram_contact to guarantee the right person receives the message."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nickname": {
                    "type": "string",
                    "description": "Diego's nickname for this contact (e.g. 'alanis', 'sensei'). Used as cache key.",
                },
                "telegram_id": {
                    "type": "integer",
                    "description": "Telegram user ID returned by find_telegram_contact. Use when available.",
                },
                "contact_phone": {
                    "type": "string",
                    "description": (
                        "Phone number in international format (e.g. '+19293959561'). "
                        "Use this when the contact has no @username and no telegram_id — "
                        "Telethon can send messages via phone number if the person is in Diego's contacts."
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
        "name": "send_email",
        "description": (
            "Sends an email from Beli's own address (beli@agentmail.to) on Diego's behalf. "
            "Use when Diego asks to send an email to someone. "
            "Always confirm recipient, subject, and body with Diego before calling this tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address.",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line.",
                },
                "body": {
                    "type": "string",
                    "description": "Full email body text.",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
]
