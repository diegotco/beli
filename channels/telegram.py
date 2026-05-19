"""
channels/telegram.py - Telegram module for Beli.

Connects Beli to Telegram using python-telegram-bot.
Handles incoming messages, passes them to the brain, and returns the response.
"""
import asyncio
import base64
import calendar
import datetime
import io
import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from brain.claude_client import BelisBrain
from memory.manager import MemoryManager
from memory.extractor import FactExtractor
from personality import get_system_prompt
from tools.transcriber import transcribe_audio

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
        # Telethon listener params (optional — proactive notifications)
        telegram_api_id: int = 0,
        telegram_api_hash: str = "",
        owner_session_string: str = "",
        owner_chat_id: int = 0,
    ):
        self.token = token
        self.brain = brain
        self.memory = memory
        self.extractor = FactExtractor(memory=memory, brain=brain)
        self.extraction_interval = extraction_interval
        self.reminder_hour = reminder_hour
        self.reminder_minute = reminder_minute
        self.reminder_days_before_end = reminder_days_before_end

        # Listener config
        self._tg_api_id         = telegram_api_id
        self._tg_api_hash       = telegram_api_hash
        self._owner_session     = owner_session_string
        self._owner_chat_id     = owner_chat_id

        self.app = Application.builder().token(token).post_init(self._post_init).build()
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Registers all command and message handlers."""
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("borrar", self._cmd_clear))
        self.app.add_handler(CommandHandler("ayuda", self._cmd_help))
        self.app.add_handler(CommandHandler("memoria", self._cmd_memory))
        self.app.add_handler(CommandHandler("contactos", self._cmd_contacts))
        self.app.add_handler(CommandHandler("digest", self._cmd_digest))
        self.app.add_handler(CommandHandler("timezone", self._cmd_timezone))
        self.app.add_handler(CommandHandler("notificaciones", self._cmd_notifications))
        self.app.add_handler(CallbackQueryHandler(self._cb_notifications, pattern="^notif:"))
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
        # Voice notes
        self.app.add_handler(
            MessageHandler(filters.VOICE, self._handle_voice)
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
        tz = await self.memory.get_setting("timezone", "America/Mexico_City")
        help_text = (
            "Soy Beli, tu asistente personal con IA.\n\n"
            "Comandos:\n"
            "  /digest             — resumen de tus chats recientes de Telegram y WhatsApp\n"
            "  /notificaciones     — activar/desactivar notificaciones en tiempo real\n"
            "  /timezone <zona>    — cambia tu zona horaria (actual: " + tz + ")\n"
            "  /borrar             — borra el historial de conversación\n"
            "  /memoria            — muestra los hechos que recuerdo sobre ti\n"
            "  /ayuda              — muestra esta ayuda\n\n"
            "Ejemplos de zona horaria: America/Mexico_City, America/Guayaquil, America/New_York\n\n"
            "Simplemente escríbeme lo que necesites 💬"
        )
        await update.message.reply_text(help_text)

    async def _cmd_timezone(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Sets the user's preferred timezone."""
        import zoneinfo
        args = context.args
        if not args:
            tz = await self.memory.get_setting("timezone", "America/Mexico_City")
            await update.message.reply_text(
                f"Zona horaria actual: {tz}\n\n"
                "Para cambiarla: /timezone America/Guayaquil\n"
                "Otras opciones: America/New_York, Europe/Madrid, America/Bogota"
            )
            return
        tz_name = args[0]
        try:
            zoneinfo.ZoneInfo(tz_name)  # Validate
        except zoneinfo.ZoneInfoNotFoundError:
            await update.message.reply_text(
                f"'{tz_name}' no es una zona horaria válida.\n"
                "Ejemplos: America/Guayaquil, America/New_York, Europe/Madrid"
            )
            return
        await self.memory.save_setting("timezone", tz_name)
        logger.info(f"Timezone updated to: {tz_name}")
        await update.message.reply_text(f"Zona horaria actualizada a {tz_name} ✓")

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

    async def _cmd_digest(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Reads and summarizes the owner's recent Telegram activity with reply suggestions."""
        user_id = str(update.effective_user.id)
        await update.message.chat.send_action(ChatAction.TYPING)
        await self.memory.register_telegram_chat(update.effective_chat.id)

        history = await self.memory.get_history(CHANNEL, user_id)
        facts   = await self.memory.get_facts(CHANNEL, user_id)
        extra   = "\n".join(f"- {f}" for f in facts) if facts else ""
        system  = get_system_prompt(extra)
        tz      = await self.memory.get_setting("timezone", "America/Mexico_City")
        import zoneinfo as _zi
        _now    = datetime.datetime.now(tz=_zi.ZoneInfo(tz)).strftime("%A %d %b %Y, %H:%M")

        prompt = (
            f"Son las {_now} ({tz}). Haz un digest completo de mi actividad reciente en Telegram Y WhatsApp.\n\n"
            "PASO 1 — Telegram: llama read_telegram_chats con limit=20. "
            "Para TODOS los chats con mensajes sin leer (unread > 0), llama read_chat_history. "
            "Si un chat solo contiene imágenes/media sin texto, indícalo brevemente ('solo comparte imágenes'). "
            "Identifica cuáles necesitan respuesta.\n\n"
            "PASO 2 — WhatsApp: llama read_whatsapp_chats con limit=20. "
            "Para TODOS los chats con mensajes sin leer o con 'sin preview', llama read_whatsapp_chat_history para ver el contenido real. "
            "Identifica cuáles necesitan respuesta.\n\n"
            "RESULTADO: Resumen agrupado por plataforma (Telegram / WhatsApp). "
            "Para cada chat que necesita respuesta: quién escribió, de qué trata, borrador de respuesta. "
            "Para canales informativos: resumen breve de lo más relevante. "
            "Usa guiones simples, sin asteriscos ni negritas."
        )

        response = await self.brain.think(
            system_prompt=system,
            history=history,
            new_message=prompt,
            max_tokens=4096,
        )

        await self.memory.save_message(CHANNEL, user_id, "user", "[/digest — resumen de actividad en Telegram]")
        await self.memory.save_message(CHANNEL, user_id, "assistant", response)

        if len(response) <= 4096:
            await update.message.reply_text(_strip_markdown(response))
        else:
            for chunk in _split_text(response, 4096):
                await update.message.reply_text(_strip_markdown(chunk))

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
    # NOTIFICATION SETTINGS
    # ------------------------------------------------------------------

    def _notifications_keyboard(self) -> InlineKeyboardMarkup:
        """Builds an inline keyboard showing the current notification toggle state."""
        from settings.notifications import get_settings
        s = get_settings()

        def label(key: str, text: str) -> InlineKeyboardButton:
            icon = "🟢" if s.is_enabled(key) else "🔴"
            return InlineKeyboardButton(f"{icon} {text}", callback_data=f"notif:{key}")

        return InlineKeyboardMarkup([
            [InlineKeyboardButton("── WhatsApp ──", callback_data="notif:noop")],
            [label("whatsapp_direct", "Directos"), label("whatsapp_groups", "Grupos")],
            [InlineKeyboardButton("── Telegram ──", callback_data="notif:noop")],
            [label("telegram_direct", "Directos"), label("telegram_groups", "Grupos")],
        ])

    async def _cmd_notifications(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Shows the notification settings menu."""
        await update.message.reply_text(
            "🔔 Notificaciones en vivo\n\n"
            "Activa las fuentes de las que quieres recibir mensajes en tiempo real.\n"
            "Por defecto todo está desactivado.",
            reply_markup=self._notifications_keyboard(),
        )

    async def _cb_notifications(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles inline button presses for the notification settings menu."""
        query = update.callback_query

        key = query.data[len("notif:"):]  # strip "notif:" prefix
        if key == "noop":
            await query.answer()
            return

        from settings.notifications import get_settings
        new_value = get_settings().toggle(key)
        status_text = "✅ Activado" if new_value else "🔕 Desactivado"

        await query.edit_message_reply_markup(reply_markup=self._notifications_keyboard())
        await query.answer(status_text, show_alert=False)

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
            await update.message.reply_text(_strip_markdown(response))
        else:
            # Split long responses into multiple messages
            for chunk in _split_text(response, 4096):
                await update.message.reply_text(_strip_markdown(chunk))

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
            await update.message.reply_text(_strip_markdown(response))
        else:
            for chunk in _split_text(response, 4096):
                await update.message.reply_text(_strip_markdown(chunk))

    async def _handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Transcribes a voice note via Groq Whisper, then processes it like a text message."""
        from config import config

        user = update.effective_user
        user_id = str(user.id)
        user_name = user.full_name or user.username or user_id

        logger.info(f"Voice note received from {user_name} (id={user_id})")
        await update.message.chat.send_action(ChatAction.TYPING)
        await self.memory.register_telegram_chat(update.effective_chat.id)

        # Download the voice file (.ogg)
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        buf = io.BytesIO()
        await voice_file.download_to_memory(buf)
        audio_bytes = buf.getvalue()

        # Transcribe with Groq Whisper
        transcription = transcribe_audio(
            api_key=config.GROQ_API_KEY,
            audio_bytes=audio_bytes,
            filename="voice.ogg",
        )

        if transcription.startswith("ERROR:"):
            logger.error(f"Transcription failed: {transcription}")
            await update.message.reply_text(
                "No pude transcribir tu nota de voz. Intenta enviando el mensaje en texto."
            )
            return

        logger.info(f"Transcribed voice from {user_name}: {transcription[:80]}")

        # From here: treat exactly like a text message
        history = await self.memory.get_history(CHANNEL, user_id)
        facts = await self.memory.get_facts(CHANNEL, user_id)
        extra_context = "\n".join(f"- {f}" for f in facts) if facts else ""
        system = get_system_prompt(extra_context)

        response = await self.brain.think(
            system_prompt=system,
            history=history,
            new_message=transcription,
        )

        # Save to memory with a label indicating it was a voice note
        label = f"[nota de voz]: {transcription}"
        await self.memory.save_message(CHANNEL, user_id, "user", label)
        await self.memory.save_message(CHANNEL, user_id, "assistant", response)

        if len(response) <= 4096:
            await update.message.reply_text(_strip_markdown(response))
        else:
            for chunk in _split_text(response, 4096):
                await update.message.reply_text(_strip_markdown(chunk))

        logger.info(f"Response sent to {user_name} (voice→text): {response[:80]}")

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

    async def _post_init(self, application) -> None:
        """Called by PTB after the bot is initialized but before polling starts."""
        # Store the running event loop so HTTP threads can submit work to it safely
        from channels.loop_ref import set_loop
        set_loop(asyncio.get_running_loop())

        # Register visible command list (shown when user types "/")
        from telegram import BotCommand
        await application.bot.set_my_commands([
            BotCommand("digest",          "Resumen de tus chats recientes con sugerencias de respuesta"),
            BotCommand("notificaciones",  "Activar/desactivar notificaciones en tiempo real"),
            BotCommand("memoria",         "Ver los hechos que Beli recuerda sobre ti"),
            BotCommand("timezone",        "Cambiar zona horaria (ej. /timezone America/Merida)"),
            BotCommand("borrar",          "Borrar el historial de conversación"),
            BotCommand("ayuda",           "Ver todos los comandos disponibles"),
        ])

        if self._tg_api_id and self._tg_api_hash and self._owner_chat_id:
            from channels.telegram_listener import run_listener
            asyncio.create_task(
                run_listener(
                    api_id=self._tg_api_id,
                    api_hash=self._tg_api_hash,
                    session_string=self._owner_session,
                    bot_token=self.token,
                    owner_chat_id=self._owner_chat_id,
                )
            )
            logger.info("Telegram proactive listener started.")
        else:
            logger.info("Telegram listener disabled (missing api_id/api_hash/owner_chat_id).")

    def run(self) -> None:
        """Starts the bot in polling mode (for local use)."""
        logger.info("Starting Beli on Telegram (polling mode)...")
        self.app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )


# ------------------------------------------------------------------
# UTILITIES
# ------------------------------------------------------------------

def _load_reminders() -> str:
    """Reads reminders: env var REMINDERS_CONTENT takes priority over local file."""
    import os
    env_content = os.getenv("REMINDERS_CONTENT", "").strip()
    if env_content:
        lines = env_content.splitlines()
    else:
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


def _strip_markdown(text: str) -> str:
    """Removes markdown formatting that Beli shouldn't use (bold, headers)."""
    import re
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)   # **bold** → bold
    text = re.sub(r'\*(.+?)\*', r'\1', text)         # *italic* → italic
    text = re.sub(r'#{1,6}\s+', '', text)             # ### Header → Header
    return text


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
