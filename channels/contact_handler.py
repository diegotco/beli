"""
channels/contact_handler.py - Reusable logic for handling messages from external contacts.

Channel-agnostic: contains no Telegram or WhatsApp imports.
Used by beli_listener.py (Telegram) and future channels (WhatsApp, etc.).

Flow:
  1. Contact writes to Beli's account → auto-acknowledgment sent back
  2. Owner is notified via the bot with a reply hint
  3. If contact keeps insisting → polite deflection sent once
  4. Owner can reply by telling @IamBeliBot: "respóndele a [name]: [message]"
"""
import logging

logger = logging.getLogger("beli.contact_handler")

# Sent to the contact on their FIRST message
ACKNOWLEDGMENT = (
    "Hola, soy Beli 👋 El asistente personal de mi propietario.\n\n"
    "Ya le avisé que me escribiste. En cuanto tenga un momento, "
    "te responderá por este mismo chat."
)

# Sent ONCE if the contact keeps writing without getting a response
DEFLECTION = (
    "Entiendo que quieres seguir chateando, pero no tengo la capacidad "
    "de mantener una conversación directa contigo.\n\n"
    "Mi propietario ya está al tanto de todos tus mensajes y te responderá "
    "cuando pueda. No te preocupes, nada se pierde 🙂"
)

# How many unanswered messages before sending the deflection
INSISTENCE_THRESHOLD = 2


class _ContactSession:
    """Tracks the state of a single external contact within a runtime session."""
    def __init__(self):
        self.message_count: int = 0
        self.deflection_sent: bool = False


class ContactHandler:
    """
    Processes incoming messages from external contacts.

    Returns what to reply to the contact (or None) and what to notify the owner.
    Stateful per runtime session — sessions reset on restart, which is acceptable.

    Usage (channel-agnostic):
        handler = ContactHandler()
        reply, notify = handler.process(sender_id, sender_name, sender_username, telegram_id, text)
        if reply:
            send_to_contact(reply)
        send_to_owner(notify)
    """

    def __init__(self):
        self._sessions: dict[str, _ContactSession] = {}

    def process(
        self,
        sender_id: str,
        sender_name: str,
        sender_username: str,
        sender_telegram_id: int | None,
        text: str,
        channel: str = "Telegram",
    ) -> tuple[str | None, str]:
        """
        Process one incoming message from an external contact.

        Args:
            sender_id:           Unique identifier for the sender (Telegram user ID, WhatsApp number, etc.)
            sender_name:         Display name of the sender
            sender_username:     @username or handle (empty string if none)
            sender_telegram_id:  Telegram numeric ID (used so the owner can reply by ID if not in cache)
            text:                The message text
            channel:             Channel name for the notification ("Telegram", "WhatsApp", etc.)

        Returns:
            (reply_to_sender, owner_notification)
            reply_to_sender: text to send back to the contact, or None if no auto-reply needed
        """
        session = self._sessions.setdefault(sender_id, _ContactSession())
        session.message_count += 1

        logger.info(
            f"[{channel}] Incoming from {sender_name} "
            f"(id={sender_id}, msg#{session.message_count}): {text[:80]}"
        )

        # --- Build owner notification ---
        # Include @username or telegram_id so the owner (and Claude) can reply even to non-cached contacts
        if sender_username:
            identifier = f"@{sender_username}"
        elif sender_telegram_id:
            identifier = f"id:{sender_telegram_id}"
        else:
            identifier = sender_id

        first_name = sender_name.split()[0] if sender_name else "esta persona"

        owner_notification = (
            f"📨 *{sender_name}* ({identifier}) te escribió a Beli [{channel}]:\n\n"
            f"{text}\n\n"
            f"💬 _Para responderle: \"respóndele a {first_name}: [tu mensaje]\"_"
        )

        # --- Determine reply to the contact ---
        if session.message_count == 1:
            # First message → acknowledge
            reply = ACKNOWLEDGMENT
        elif session.message_count > INSISTENCE_THRESHOLD and not session.deflection_sent:
            # Insisting without response → deflect once
            session.deflection_sent = True
            reply = DEFLECTION
        else:
            # Subsequent messages after acknowledgment (or after deflection) → stay silent
            reply = None

        return reply, owner_notification
