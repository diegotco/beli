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
            "Search by the contact or group name. "
            "Messages are returned in CHRONOLOGICAL ORDER (oldest first, newest last). "
            "To find the N most recent messages from a specific person, read from the END of the list upward."
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
                    "description": "Number of recent messages to fetch (default 50, max 100). Use higher values when filtering by a specific sender.",
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
            "Accepts phone number ('+525561103975') or WhatsApp chat ID. "
            "For @mentions in groups: include the phone number (digits only) in the message text "
            "as '@{number}' and pass it in the mentions array. WhatsApp shows the contact's name, not the number. "
            "Never show phone numbers in Telegram — use them silently in this tool only."
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
                    "description": "The exact message text to send. For mentions use '@{digits}' e.g. '@593987370597'. WhatsApp displays the contact name.",
                },
                "mentions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Phone numbers (digits only, no + or spaces) of people to @mention. e.g. ['593987370597']. Use when the message contains @mentions.",
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
    {
        "name": "set_timezone",
        "description": (
            "Updates the owner's current timezone. "
            "Call this automatically (no confirmation needed) whenever the owner mentions "
            "being in a new location, traveling, or arriving somewhere — e.g. "
            "'llegué a Ecuador', 'estoy en Nueva York', 'voy a España'. "
            "Look up the IANA timezone for that location and call this tool silently. "
            "Then confirm with a brief note like 'Actualicé tu horario a Guayaquil'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone name, e.g. 'America/Guayaquil', 'America/New_York', 'Europe/Madrid'.",
                },
                "location_name": {
                    "type": "string",
                    "description": "Human-readable location name for the confirmation message, e.g. 'Ecuador', 'Nueva York'.",
                },
            },
            "required": ["timezone", "location_name"],
        },
    },
    {
        "name": "read_calendar_events",
        "description": (
            "Reads upcoming events from the owner's primary Google Calendar. "
            "Use this when the owner asks about their schedule, agenda, or upcoming events. "
            "Returns a list of events with title, date/time, and location."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "description": "How many days ahead to look. Default 7. Use 1 for today, 30 for the month.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of events to return. Default 20.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "create_calendar_event",
        "description": (
            "Creates a new event in the owner's primary Google Calendar. "
            "Use this when the owner asks to schedule, add, or block time for something. "
            "Always confirm the title, date, and time with the owner before calling."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Event title/summary.",
                },
                "start_datetime": {
                    "type": "string",
                    "description": "Start date and time in ISO 8601 format, e.g. '2026-05-20T10:00:00'.",
                },
                "end_datetime": {
                    "type": "string",
                    "description": "End date and time in ISO 8601 format, e.g. '2026-05-20T11:00:00'.",
                },
                "description": {
                    "type": "string",
                    "description": "Optional event description or notes.",
                },
                "location": {
                    "type": "string",
                    "description": "Optional event location.",
                },
            },
            "required": ["title", "start_datetime", "end_datetime"],
        },
    },
    {
        "name": "list_task_lists",
        "description": (
            "Returns all of the owner's Google Tasks lists with their IDs. "
            "Use this when the owner asks to see their task lists or before operating on a specific list by name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_tasks",
        "description": (
            "Returns the tasks in a Google Tasks list. "
            "Use this when the owner asks to see, check, or review their tasks or to-do list. "
            "Defaults to the primary list. Pass show_completed=true to also show done tasks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "list_id": {
                    "type": "string",
                    "description": "Task list ID or '@default' for the primary list (default: '@default').",
                },
                "show_completed": {
                    "type": "boolean",
                    "description": "If true, also return completed tasks. Default false.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "create_task",
        "description": (
            "Creates a new task in a Google Tasks list. "
            "Use this when the owner asks to add, create, or save a task or to-do item."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Task title.",
                },
                "list_id": {
                    "type": "string",
                    "description": "Task list ID or '@default' for the primary list (default: '@default').",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional task notes or description.",
                },
                "due_date": {
                    "type": "string",
                    "description": "Optional due date in YYYY-MM-DD format, e.g. '2026-05-25'.",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "complete_task",
        "description": (
            "Marks a task as completed in a Google Tasks list. "
            "Use this when the owner says they finished, completed, or did a task. "
            "Finds the task by title (partial match) or by its ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_title_or_id": {
                    "type": "string",
                    "description": "Task title (or substring) to search for, or the exact task ID.",
                },
                "list_id": {
                    "type": "string",
                    "description": "Task list ID or '@default' for the primary list (default: '@default').",
                },
            },
            "required": ["task_title_or_id"],
        },
    },
    {
        "name": "delete_task",
        "description": (
            "Deletes a task from a Google Tasks list. "
            "Use this when the owner asks to remove, delete, or erase a task. "
            "Finds the task by title (partial match) or by its ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_title_or_id": {
                    "type": "string",
                    "description": "Task title (or substring) to search for, or the exact task ID.",
                },
                "list_id": {
                    "type": "string",
                    "description": "Task list ID or '@default' for the primary list (default: '@default').",
                },
            },
            "required": ["task_title_or_id"],
        },
    },
    {
        "name": "read_gmail_inbox",
        "description": (
            "Reads the owner's Gmail inbox and returns a summary of recent emails. "
            "Use when the owner asks to check, review, or summarize their email, inbox, or correos. "
            "Set unread_only=true when they ask specifically for unread or new emails. "
            "Returns sender, subject, snippet, and message ID for each email."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Number of emails to return (default 10, max 20).",
                },
                "unread_only": {
                    "type": "boolean",
                    "description": "If true, only return unread emails. Default false.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "read_gmail_message",
        "description": (
            "Reads the full content of a specific Gmail email. "
            "Use when the owner wants to read, open, or see the details of a particular email. "
            "Pass the message ID from read_gmail_inbox, or a subject keyword to search for."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id_or_subject": {
                    "type": "string",
                    "description": (
                        "Gmail message ID (from read_gmail_inbox, e.g. '18f3a2b4c5d6e7f8') "
                        "or subject text to search for (e.g. 'Propuesta de colaboración')."
                    ),
                },
            },
            "required": ["message_id_or_subject"],
        },
    },
    {
        "name": "send_gmail_message",
        "description": (
            "Sends an email FROM the owner's personal Gmail account. "
            "Use when the owner asks to reply or send an email from their personal address (not beli@agentmail.to). "
            "Use send_email (AgentMail) only if the owner explicitly wants it from Beli's address. "
            "ALWAYS show a full draft (To, Subject, body) and wait for explicit confirmation before sending. "
            "To reply to an existing email, pass the thread_id from read_gmail_message."
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
                    "description": "Email subject.",
                },
                "body": {
                    "type": "string",
                    "description": "Plain-text email body.",
                },
                "thread_id": {
                    "type": "string",
                    "description": "Optional. Gmail thread ID to send as a reply in the same thread.",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "get_x_my_tweets",
        "description": (
            "Returns Diego's most recent tweets from @DiegoCapital_99 with AGGREGATE engagement metrics "
            "(total likes, retweets, replies, impressions per tweet). "
            "Use when Diego asks about his tweet stats, performance, or wants to see his recent posts. "
            "IMPORTANT: This tool only returns counts — it does NOT return usernames of who liked or "
            "retweeted. Never invent or guess usernames. If Diego asks 'who liked my tweet', "
            "tell him the X API does not expose individual likers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of recent tweets to retrieve (1–10, default 5).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_x_mentions",
        "description": (
            "Returns Diego's most recent mentions on X (@DiegoCapital_99). "
            "Use when Diego asks who mentioned him, about his interactions, "
            "or wants to see what people are saying about him on X."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of recent mentions to retrieve (1–10, default 10).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "post_tweet",
        "description": (
            "Posts a tweet or native X poll on @DiegoCapital_99. "
            "Use when Diego asks to publish, post, or share something on X or Twitter. "
            "Use poll_options when Diego asks to create a poll/encuesta (2–4 options). "
            "If Diego sends a video file along with the text, set has_video=true. "
            "ALWAYS show the exact content and wait for explicit confirmation before posting."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The tweet text (max 280 characters).",
                },
                "has_video": {
                    "type": "boolean",
                    "description": "True if Diego provided a video file to attach to the tweet.",
                },
                "poll_options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of 2–4 poll options for a native X poll. Cannot be combined with video.",
                },
                "poll_duration_hours": {
                    "type": "integer",
                    "description": "How long the poll runs in hours (1–168). Default 24.",
                },
            },
            "required": ["text"],
        },
    },
]
