"""
channels/beli_listener.py - Listens for incoming messages on Beli's own Telegram account.

When someone replies to Beli or starts a conversation with her, Diego is notified
immediately via the bot with the sender's name and message content.
"""
import logging

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telegram import Bot
from tools.telegram_sender import set_shared_beli_client

logger = logging.getLogger("beli.listener")


class BeliListener:
    """
    Keeps Beli's Telethon session open and forwards incoming messages to Diego.
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
            name     = f"{first} {last}".strip() or "Desconocido"
            username = f" (@{sender.username})" if getattr(sender, "username", None) else ""
            text     = event.text or "[mensaje sin texto]"

            logger.info(f"Incoming → Beli from {name}{username}: {text[:80]}")

            notify = (
                f"📨 *{name}{username}* le respondió a Beli:\n\n"
                f"{text}"
            )

            chat_ids = await self.memory.get_telegram_chat_ids()
            for chat_id in chat_ids:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=notify,
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.exception(f"Error handling incoming message for Beli: {e}")

    async def stop(self) -> None:
        if self.client.is_connected():
            await self.client.disconnect()
        logger.info("Beli's Telegram listener stopped.")
