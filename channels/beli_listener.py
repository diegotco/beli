"""
channels/beli_listener.py - Listens for incoming messages on Beli's own Telegram account.

When someone writes to @BeliAgent:
  1. An automatic acknowledgment is sent back to the contact
  2. The owner is notified via the bot with a reply hint
  3. If the contact keeps insisting, a polite deflection is sent once
  4. The owner can reply by telling @IamBeliBot: "respóndele a [name]: [message]"
"""
import logging

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telegram import Bot
from tools.telegram_sender import set_shared_beli_client
from channels.contact_handler import ContactHandler

logger = logging.getLogger("beli.listener")


class BeliListener:
    """
    Keeps Beli's Telethon session open and handles incoming messages from external contacts.
    Lifecycle: call start() when the bot starts, stop() when it shuts down.
    """

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_path: str,
        bot: Bot,
        memory,
    ):
        from config import config
        session = StringSession(config.BELI_SESSION_STRING) if config.BELI_SESSION_STRING else session_path
        self.client  = TelegramClient(session, api_id, api_hash)
        self.bot     = bot
        self.memory  = memory
        self.contact_handler = ContactHandler()

    async def start(self) -> None:
        await self.client.start()

        # Share the open client with the sender to avoid session lock conflicts
        set_shared_beli_client(self.client)

        @self.client.on(events.NewMessage(incoming=True))
        async def on_message(event):
            await self._handle_incoming(event)

        logger.info("Beli's Telegram listener active — watching for incoming messages.")

    async def _handle_incoming(self, event) -> None:
        try:
            sender = await event.get_sender()
            if not sender:
                return

            first    = getattr(sender, "first_name", "") or ""
            last     = getattr(sender, "last_name",  "") or ""
            name     = f"{first} {last}".strip() or "Unknown"
            username = getattr(sender, "username", "") or ""
            tid      = getattr(sender, "id", None)
            text     = event.text or "[non-text message]"

            # Process through the channel-agnostic contact handler
            reply_text, owner_notification = self.contact_handler.process(
                sender_id=str(tid or name),
                sender_name=name,
                sender_username=username,
                sender_telegram_id=tid,
                text=text,
                channel="Telegram",
            )

            # Send auto-reply to the contact if needed (acknowledgment or deflection)
            if reply_text:
                await event.reply(reply_text)
                logger.info(f"Auto-reply sent to {name}: {reply_text[:60]}...")

            # Notify the owner via the bot
            chat_ids = await self.memory.get_telegram_chat_ids()
            for chat_id in chat_ids:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=owner_notification,
                    parse_mode="Markdown",
                )

        except Exception as e:
            logger.exception(f"Error handling incoming message for Beli: {e}")

    async def stop(self) -> None:
        if self.client.is_connected():
            await self.client.disconnect()
        logger.info("Beli's Telegram listener stopped.")
