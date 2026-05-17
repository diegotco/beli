"""
channels/telegram.py - Telegram module for Beli.

Connects Beli to Telegram using python-telegram-bot.
Handles incoming messages, passes them to the brain, and returns the response.
"""
import base64
import calendar
import datetime
import io
import logging
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from brain.claude_client import BelisBrain
from memory.manager import MemoryManager
from memory.extractor import FactExtractor
from personality import get_system_prompt
from channels.beli_listener import BeliListener

logger = logging.getLogger("beli.telegram")

CHANNEL = "telegram"


class TelegramChannel:
    """Beli's Telegram bot."""

    def __init__(
        self,
        token: str,
        brain: BelisBrain,
        memory: MemoryManager,
        extraction_interval: int = 3600,
        reminder_hour: int = 9,
        reminder_minute: int = 0,
        reminder_days_before_end: int = 4,
        beli_listener: BeliListener | None = None,
    ):
        self.token = token
        self.brain = brain
        self.memory = memory
        self.extractor = FactExtractor(memory=memory, brain=brain)
        self.extraction_interval = extraction_interval
        self.reminder_hour = reminder_hour
        self.reminder_minute = reminder_minute
        self.reminder_days_before_end = reminder_days_before_end
        self.beli_listener = beli_listener
        self.app = (
            Application.builder()
            .token(token)
            .post_init(self._post_init)
            .post_shutdown(self._post_shutdown)
            .build()
        )
        self._register_handlers()

    async def _post_init(self, application: Application) -> None:
        """Called once after the bot starts — launches Beli's Telegram listener."""
        if self.beli_listener:
            await self.beli_listener.start()

    async def _post_shutdown(self, application: Application) -> None:
        """Called once when the bot shuts down — stops the listener cleanly."""
        if self.beli_listener:
            await self.beli_listener.stop()

    def _register_handlers(self) -> None:
        """Registers all command and message handlers."""
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("borrar", self._cmd_clear))
        self.app.add_handler(CommandHandler("ayuda", self._cmd_help))
        self.app.add_handler(CommandHandler("memoria", self._cmd_memory))
        self.app.add_handler(CommandHandler("contactos", self._cmd_contacts))
        # Hourly fact extraction job
        self.app.job_queue.run_repeating(
            self._job_extract_facts,
            interval=self.extraction_interval,
            first=60,
        )
        # Daily reminder check job
        self.app.job_queue.run_daily(
            self._job_monthly_reminder,
            time=datetime.time(hour=self.reminder_hour, minute=self.reminder_minute),
        )
        # Text messages
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        # Photo / screenshot messages
        self.app.add_handler(
            MessageHandler(filters.PHOTO, self._handle_photo)
        )
        # Global error handler
        self.app.add_error_handler(self._error_handler)
        logger.info("Telegram handlers registered.")

    # ------------------------------------------------------------------
    # COMMANDS
    # ------------------------------------------------------------------

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Initial greeting when the user sends /start."""
        user = update.effective_user
        user_id = str(user.id)
        logger.info(f"New user on Telegram: {user.full_name} (id={user_id})")

        welcome = (
            f"Hola {user.first_name} 👋 Soy Beli, tu asistente personal.\n\n"
            "Escríbeme lo que necesites. Recuerdo el contexto de nuestra conversación.\n\n"
            "Comandos disponibles:\n"
            "  /borrar — borra el historial de nuestra conversación\n"
            "  /ayuda  — muestra esta ayuda"
        )
        await update.message.reply_text(welcome)

    async def _cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Clears the user's conversation history."""
        user_id = str(update.effective_user.id)
        count = await self.memory.clear_history(CHANNEL, user_id)
        await update.message.reply_text(
            f"Listo, borré {count} mensajes de nuestra conversación. ¡Empezamos de cero!"
        )

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Shows the help message."""
        help_text = (
            "Soy Beli, tu asistente personal con IA.\n\n"
            "Comandos:\n"
            "  /borrar  — borra el historial de conversación\n"
            "  /memoria — muestra los hechos que recuerdo sobre ti\n"
            "  /ayuda   — muestra esta ayuda\n\n"
            "Simplemente escríbeme lo que necesites 💬"
        )
        await update.message.reply_text(help_text)

    async def _cmd_contacts(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Shows the cached Telegram contact mappings."""
        import json
        from pathlib import Path
        cache_path = Path(__file__).parent.parent / "data" / "contact_cache.json"
        if not cache_path.exists():
            await update.message.reply_text(
                "Aún no tengo contactos guardados en caché.\n"
                "La primera vez que le escribas a alguien por nombre, lo guardaré automáticamente."
            )
            return
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if not cache:
            await update.message.reply_text("La caché de contactos está vacía.")
            return
        lines = "\n".join(
            f"• {nickname} → {data['name']} {'(@' + data['username'] + ')' if data['username'] else ''}"
            for nickname, data in cache.items()
        )
        await update.message.reply_text(f"Contactos guardados en caché:\n\n{lines}")

    async def _cmd_memory(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Shows the saved facts about the user."""
        user_id = str(update.effective_user.id)
        facts = await self.memory.get_facts(CHANNEL, user_id)
        if not facts:
            await update.message.reply_text(
                "Todavía no tengo hechos guardados sobre ti. "
                "Después de nuestras primeras conversaciones, iré aprendiendo cosas importantes automáticamente."
            )
        else:
            lines = "\n".join(f"• {f}" for f in facts)
            await update.message.reply_text(f"Esto es lo que recuerdo sobre ti:\n\n{lines}")

    # ------------------------------------------------------------------
    # MESSAGES
    # ------------------------------------------------------------------

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Processes an incoming text message and replies with Beli's response."""
        user = update.effective_user
        user_id = str(user.id)
        user_name = user.full_name or user.username or user_id
        text = update.message.text

        logger.info(f"Message from {user_name} (id={user_id}): {text[:80]}{'...' if len(text) > 80 else ''}")

        # Register chat_id so Beli can send proactive messages (e.g. reminders)
        await self.memory.register_telegram_chat(update.effective_chat.id)

        # Show "typing..." indicator while Beli processes
        await update.message.chat.send_action(ChatAction.TYPING)

        # Load user history and facts
        history = await self.memory.get_history(CHANNEL, user_id)
        facts = await self.memory.get_facts(CHANNEL, user_id)
        extra_context = "\n".join(f"- {f}" for f in facts) if facts else ""

        # Build system prompt enriched with user context
        system = get_system_prompt(extra_context)

        # Ask the brain (Claude) for a response
        response = await self.brain.think(
            system_prompt=system,
            history=history,
            new_message=text,
        )

        # Save both messages to memory
        await self.memory.save_message(CHANNEL, user_id, "user", text)
        await self.memory.save_message(CHANNEL, user_id, "assistant", response)

        # Send response (Telegram has a 4096-character limit per message)
        if len(response) <= 4096:
            await update.message.reply_text(response)
        else:
            # Split long responses into multiple messages
            for chunk in _split_text(response, 4096):
                await update.message.reply_text(chunk)

        logger.info(f"Response sent to {user_name}: {response[:80]}{'...' if len(response) > 80 else ''}")

    async def _handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Processes an image sent by the owner — passes it to Claude's vision."""
        user = update.effective_user
        user_id = str(user.id)
        caption = update.message.caption or ""

        logger.info(f"Photo received from {user.full_name} | caption: '{caption}'")

        await update.message.chat.send_action(ChatAction.TYPING)
        await self.memory.register_telegram_chat(update.effective_chat.id)

        # Download the highest-resolution version of the photo
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        buf = io.BytesIO()
        await file.download_to_memory(buf)
        image_b64 = base64.b64encode(buf.getvalue()).decode()

        # Load context
        history = await self.memory.get_history(CHANNEL, user_id)
        facts = await self.memory.get_facts(CHANNEL, user_id)
        extra_context = "\n".join(f"- {f}" for f in facts) if facts else ""
        system = get_system_prompt(extra_context)

        # Ask Claude to read and respond to the image
        response = await self.brain.think_with_image(
            system_prompt=system,
            history=history,
            caption=caption,
            image_b64=image_b64,
        )

        # Save to memory as text (images aren't stored, only the caption + response)
        label = f"[imagen enviada por el propietario{': ' + caption if caption else ''}]"
        await self.memory.save_message(CHANNEL, user_id, "user", label)
        await self.memory.save_message(CHANNEL, user_id, "assistant", response)

        if len(response) <= 4096:
            await update.message.reply_text(response)
        else:
            for chunk in _split_text(response, 4096):
                await update.message.reply_text(chunk)

    # ------------------------------------------------------------------
    # JOBS & ERROR HANDLER
    # ------------------------------------------------------------------

    async def _job_extract_facts(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Hourly job: extracts important facts from recent conversations."""
        logger.info("Hourly job: starting fact extraction...")
        try:
            await self.extractor.run_for_all_users()
        except Exception as e:
            logger.exception(f"Error in fact extraction job: {e}")

    async def _job_monthly_reminder(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Daily job: sends subscription reminders N days before end of month."""
        today = datetime.date.today()
        last_day = calendar.monthrange(today.year, today.month)[1]
        days_remaining = last_day - today.day

        if days_remaining != self.reminder_days_before_end:
            return  # Not the right day, do nothing

        logger.info(f"Monthly reminder day triggered ({today}). Sending to all chats...")

        reminders_text = _load_reminders()
        if not reminders_text:
            logger.warning("reminders.md not found or empty — skipping reminder.")
            return

        message = (
            f"🔔 *Recordatorio mensual* — quedan {days_remaining} días para fin de mes.\n\n"
            f"Aquí están las suscripciones y servicios que deberías revisar antes de que termine el mes:\n\n"
            f"{reminders_text}"
        )

        chat_ids = await self.memory.get_telegram_chat_ids()
        if not chat_ids:
            logger.warning("No Telegram chat IDs registered yet — reminder not sent.")
            return

        for chat_id in chat_ids:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="Markdown",
                )
                logger.info(f"Reminder sent to chat_id={chat_id}")
            except Exception as e:
                logger.error(f"Failed to send reminder to chat_id={chat_id}: {e}")

    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Logs unhandled errors from the bot."""
        logger.error(f"Unhandled Telegram error: {context.error}", exc_info=context.error)

    # ------------------------------------------------------------------
    # START
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Starts the bot in polling mode (for local use)."""
        logger.info("Starting Beli on Telegram (polling mode)...")
        self.app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,  # Ignore messages that accumulated while offline
        )


# ------------------------------------------------------------------
# UTILITIES
# ------------------------------------------------------------------

def _load_reminders() -> str:
    """Reads reminders.md and formats it as plain text for Telegram."""
    path = Path(__file__).parent.parent / "reminders.md"
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    # Skip header/preamble lines; start from the first section heading
    output = []
    in_preamble = True
    for line in lines:
        if in_preamble and (not line.strip() or line.startswith("#") or line.startswith(">")):
            if line.startswith("## "):
                in_preamble = False  # First section heading = real content starts
            else:
                continue
        output.append(line)
    return "\n".join(output).strip()


def _split_text(text: str, max_length: int) -> list[str]:
    """Splits long text into chunks respecting paragraph boundaries."""
    chunks = []
    while len(text) > max_length:
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        chunks.append(text)
    return chunks
