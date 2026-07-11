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
import json
import logging
import zoneinfo
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
        # Morning agenda
        google_calendar_credentials: str = "",
        morning_agenda_hour: int = 8,
        # Birthday greetings via WhatsApp
        waha_url: str = "",
        waha_session: str = "default",
        waha_api_key: str = "",
        birthday_contacts_json: str = "",
        birthday_hour: int = 6,
        # X / Twitter monitoring
        x_api_key: str = "",
        x_api_secret: str = "",
        x_bearer_token: str = "",
        x_access_token: str = "",
        x_access_token_secret: str = "",
        # Payg0
        payg0_api_key: str = "",
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

        # Morning agenda config
        self._calendar_credentials  = google_calendar_credentials
        self._morning_agenda_hour   = morning_agenda_hour

        # Birthday config
        self._waha_url              = waha_url
        self._waha_session          = waha_session
        self._waha_api_key          = waha_api_key
        self._birthday_contacts_json = birthday_contacts_json
        self._birthday_hour         = birthday_hour

        # X monitoring config
        self._x_api_key             = x_api_key
        self._x_api_secret          = x_api_secret
        self._x_bearer_token        = x_bearer_token
        self._x_access_token        = x_access_token
        self._x_access_token_secret = x_access_token_secret

        # Payg0 config
        self._payg0_api_key         = payg0_api_key

        # In-memory sets to avoid duplicate reminder notifications
        self._notified_event_ids:   set[str] = set()  # "event_id:YYYY-MM-DD"
        self._notified_pending_ids: set[str] = set()  # Payg0 payment UUIDs

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
        self.app.add_handler(CommandHandler("logs", self._cmd_logs))
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
        # X activity monitor — every 5 minutes
        if self._x_bearer_token:
            self.app.job_queue.run_repeating(
                self._job_x_monitor,
                interval=300,
                first=120,
            )
            logger.info("X monitor active — polling every 5 minutes.")

        # Daily birthday check — 6 AM CDMX
        if self._birthday_contacts_json and self._waha_url:
            self.app.job_queue.run_daily(
                self._job_birthday_check,
                time=datetime.time(
                    hour=self._birthday_hour,
                    minute=0,
                    tzinfo=zoneinfo.ZoneInfo("America/Mexico_City"),
                ),
            )
            logger.info(f"Birthday scheduler active — runs daily at {self._birthday_hour}:00 CDMX.")

        # WAHA health monitor — every 5 minutes
        if self._waha_url and self._owner_chat_id:
            self.app.job_queue.run_repeating(
                self._job_waha_health_check,
                interval=300,   # 5 minutes
                first=30,       # first check 30 seconds after startup
            )
            logger.info("WAHA health monitor active — checking every 5 minutes.")

        # Daily morning agenda — runs at morning_agenda_hour in owner's timezone
        if self._calendar_credentials:
            self.app.job_queue.run_daily(
                self._job_morning_agenda,
                time=datetime.time(
                    hour=self._morning_agenda_hour,
                    minute=0,
                    tzinfo=zoneinfo.ZoneInfo("America/Mexico_City"),
                ),
            )
            logger.info(f"Morning agenda active — runs daily at {self._morning_agenda_hour}:00 CDMX.")

        # Daily DB backup — 3 AM CDMX
        if self._owner_chat_id:
            self.app.job_queue.run_daily(
                self._job_db_backup,
                time=datetime.time(
                    hour=3,
                    minute=0,
                    tzinfo=zoneinfo.ZoneInfo("America/Mexico_City"),
                ),
            )
            logger.info("DB backup job active — runs daily at 03:00 CDMX.")

        # Event reminders — every 10 minutes, alerts 15-45 min before events
        if self._calendar_credentials and self._owner_chat_id:
            self.app.job_queue.run_repeating(
                self._job_event_reminder,
                interval=600,   # 10 minutes
                first=90,
            )
            logger.info("Event reminder job active — checking every 10 minutes.")

        # Payg0 pending check — every 4 hours (unclaimed outgoing payments only)
        # Received payments are handled in real-time via payment.received webhook
        if self._payg0_api_key and self._owner_chat_id:
            self.app.job_queue.run_repeating(
                self._job_payg0_pending_check,
                interval=14400,  # 4 hours
                first=120,
            )
            logger.info("Payg0 pending check active — polling every 4 hours.")

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
        # Video files (for posting to X)
        self.app.add_handler(
            MessageHandler(filters.VIDEO | filters.Document.VIDEO, self._handle_video)
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
            "  /logs [n]           — últimas n líneas de log (default 50, max 100)\n"
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
        tz      = await self.memory.get_setting("timezone", "America/Mexico_City")
        system  = get_system_prompt(extra, timezone=tz)
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
        logger.info(f"[CMD] /memoria called by user_id={user_id}")
        try:
            facts = await self.memory.get_facts(CHANNEL, user_id)
            if not facts:
                await update.message.reply_text(
                    "Todavía no tengo hechos guardados sobre ti. "
                    "Después de nuestras primeras conversaciones, iré aprendiendo cosas importantes automáticamente."
                )
            else:
                lines = "\n".join(f"• {f}" for f in facts)
                full_text = f"Esto es lo que recuerdo sobre ti ({len(facts)} hechos):\n\n{lines}"
                import io
                doc = io.BytesIO(full_text.encode("utf-8"))
                doc.name = "memoria.txt"
                await update.message.reply_document(
                    document=doc,
                    caption=f"Tengo {len(facts)} hechos guardados sobre ti.",
                )
        except Exception as e:
            logger.exception(f"[CMD] /memoria error for user_id={user_id}: {e}")
            await update.message.reply_text(f"❌ Error al leer la memoria: {e}")

    # ------------------------------------------------------------------
    # NOTIFICATION SETTINGS
    # ------------------------------------------------------------------

    # ── Notification menu helpers ─────────────────────────────────────────────

    @staticmethod
    def _notif_toggle_label(key: str, text: str) -> InlineKeyboardButton:
        from settings.notifications import get_settings
        icon = "🟢" if get_settings().is_enabled(key) else "🔴"
        return InlineKeyboardButton(f"{icon} {text}", callback_data=f"notif:toggle:{key}")

    @staticmethod
    def _notif_category_label(page: str, text: str) -> InlineKeyboardButton:
        """Returns True (any sub-key enabled) indicator for a category button."""
        from settings.notifications import get_settings
        s = get_settings()
        category_keys = {
            "messaging": ["whatsapp_direct", "whatsapp_groups", "telegram_direct", "telegram_groups"],
            "x":         ["x_mentions", "x_likes", "x_dms"],
            "agenda":    ["calendar_reminders", "event_reminders"],
            "payments":  ["payg0_pending_reminders"],
        }
        keys = category_keys.get(page, [])
        any_on = any(s.is_enabled(k) for k in keys)
        icon = "🟢" if any_on else "⚪"
        return InlineKeyboardButton(f"{icon} {text} ›", callback_data=f"notif:page:{page}")

    def _notifications_keyboard(self, page: str = "main") -> InlineKeyboardMarkup:
        """Builds the notification menu for the given page."""
        t = self._notif_toggle_label

        if page == "messaging":
            return InlineKeyboardMarkup([
                [InlineKeyboardButton("── WhatsApp ──", callback_data="notif:noop")],
                [t("whatsapp_direct", "Directos"), t("whatsapp_groups", "Grupos")],
                [InlineKeyboardButton("── Telegram ──", callback_data="notif:noop")],
                [t("telegram_direct", "Directos"), t("telegram_groups", "Grupos")],
                [InlineKeyboardButton("← Volver", callback_data="notif:page:main")],
            ])

        if page == "x":
            return InlineKeyboardMarkup([
                [t("x_mentions", "Menciones"), t("x_likes", "Likes")],
                [t("x_dms", "DMs")],
                [InlineKeyboardButton("← Volver", callback_data="notif:page:main")],
            ])

        if page == "agenda":
            return InlineKeyboardMarkup([
                [t("calendar_reminders", "📅 Agenda matutina")],
                [t("event_reminders",    "⏰ Recordatorio 30 min antes")],
                [InlineKeyboardButton("← Volver", callback_data="notif:page:main")],
            ])

        if page == "payments":
            return InlineKeyboardMarkup([
                [t("payg0_pending_reminders", "💸 Pagos pendientes (Payg0)")],
                [InlineKeyboardButton("← Volver", callback_data="notif:page:main")],
            ])

        # Main menu
        c = self._notif_category_label
        return InlineKeyboardMarkup([
            [c("messaging", "💬 Mensajería"), c("x", "𝕏 X")],
            [c("agenda",    "📅 Agenda"),     c("payments", "💸 Pagos")],
            [InlineKeyboardButton("✖ Cerrar", callback_data="notif:close")],
        ])

    async def _cmd_notifications(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Shows the notification settings menu."""
        logger.info(f"[CMD] /notificaciones called by user_id={update.effective_user.id}")
        try:
            await update.message.reply_text(
                "🔔 Notificaciones en vivo\n\n"
                "Activa las fuentes de las que quieres recibir notificaciones en tiempo real.\n"
                "Por defecto todo está desactivado.",
                reply_markup=self._notifications_keyboard(),
            )
        except Exception as e:
            logger.exception(f"[CMD] /notificaciones error: {e}")
            await update.message.reply_text(f"❌ Error al abrir notificaciones: {e}")

    async def _cb_notifications(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles inline button presses for the notification settings menu."""
        query = update.callback_query
        action = query.data[len("notif:"):]  # e.g. "noop", "close", "page:main", "toggle:x_likes"

        if action == "noop":
            await query.answer()
            return

        if action == "close":
            await query.message.delete()
            await query.answer()
            return

        if action.startswith("page:"):
            page = action[len("page:"):]
            await query.edit_message_reply_markup(reply_markup=self._notifications_keyboard(page))
            await query.answer()
            return

        if action.startswith("toggle:"):
            setting_key = action[len("toggle:"):]
            from settings.notifications import get_settings
            new_value = get_settings().toggle(setting_key)
            # Stay on the sub-page that contains this toggle
            if setting_key in ("whatsapp_direct", "whatsapp_groups", "telegram_direct", "telegram_groups"):
                page = "messaging"
            elif setting_key in ("x_mentions", "x_likes", "x_dms"):
                page = "x"
            elif setting_key in ("calendar_reminders", "event_reminders"):
                page = "agenda"
            elif setting_key == "payg0_pending_reminders":
                page = "payments"
            else:
                page = "main"
            status_text = "✅ Activado" if new_value else "🔕 Desactivado"
            await query.edit_message_reply_markup(reply_markup=self._notifications_keyboard(page))
            await query.answer(status_text, show_alert=False)

            # Warn the user that X DMs require the Basic plan
            if setting_key == "x_dms" and new_value:
                await query.message.reply_text(
                    "⚠️ Los DMs de X requieren el plan Basic ($100/mes) o superior.\n\n"
                    "Con tu plan actual el toggle quedará activo pero no recibirás notificaciones de DMs.\n\n"
                    "Puedes ver y contratar los planes aquí:\n"
                    "https://developer.x.com/en/portal/products"
                )
            return

        await query.answer()

    async def _cmd_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        /logs [n] — shows the last n log lines (default 50, max 100).
        Only the owner (OWNER_TELEGRAM_CHAT_ID) can use this command.
        """
        from log_buffer import log_buffer

        user_id = update.effective_user.id
        if self._owner_chat_id and user_id != self._owner_chat_id:
            await update.message.reply_text("⛔ Solo el owner puede ver los logs.")
            return

        # Parse optional count argument
        n = 50
        if context.args:
            try:
                n = max(1, min(100, int(context.args[0])))
            except ValueError:
                pass

        lines = log_buffer.get_last(n)
        if not lines:
            await update.message.reply_text("Sin logs en memoria todavía.")
            return

        # Telegram messages are limited to 4096 chars — split if needed
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 3800:
                await update.message.reply_text(f"```\n{chunk}\n```", parse_mode="Markdown")
                chunk = ""
            chunk += line + "\n"
        if chunk:
            await update.message.reply_text(f"```\n{chunk}\n```", parse_mode="Markdown")

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
        tz = await self.memory.get_setting("timezone", "America/Mexico_City")

        # Build system prompt enriched with user context
        system = get_system_prompt(extra_context, timezone=tz)

        # Ask the brain (Claude) for a response
        response = await self.brain.think(
            system_prompt=system,
            history=history,
            new_message=text,
            max_tokens=4096,
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
        image_bytes = buf.getvalue()
        image_b64 = base64.b64encode(image_bytes).decode()

        # Store bytes so Claude can forward the image (e.g. via send_whatsapp_image)
        from tools.executor import set_pending_image
        set_pending_image(image_bytes, f"photo_{photo.file_unique_id}.jpg")

        # Load context
        history = await self.memory.get_history(CHANNEL, user_id)
        facts = await self.memory.get_facts(CHANNEL, user_id)
        extra_context = "\n".join(f"- {f}" for f in facts) if facts else ""
        tz = await self.memory.get_setting("timezone", "America/Mexico_City")
        system = get_system_prompt(extra_context, timezone=tz)

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
        tz = await self.memory.get_setting("timezone", "America/Mexico_City")
        system = get_system_prompt(extra_context, timezone=tz)

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
    async def _handle_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handles video files sent by the owner — stores them for the next post_tweet call."""
        from tools.executor import set_pending_video
        if not update.message:
            return

        user_name = update.message.from_user.first_name if update.message.from_user else "Usuario"
        caption = update.message.caption or ""

        await update.message.chat.send_action(ChatAction.UPLOAD_VIDEO)

        # Download video bytes
        video = update.message.video or update.message.document
        if not video:
            return

        tg_file = await context.bot.get_file(video.file_id)
        video_bytes = await tg_file.download_as_bytearray()
        filename = getattr(video, "file_name", None) or "video.mp4"

        set_pending_video(bytes(video_bytes), filename)
        logger.info(f"[Telegram] Video received from {user_name} ({len(video_bytes)} bytes) — stored for tweet.")

        # If there's a caption, treat it as the tweet text and process normally
        if caption.strip():
            await self._process_message(update, context, caption.strip(), user_name)
        else:
            await update.message.reply_text(
                "Video recibido. ¿Cuál es el texto que quieres publicar junto con él en X?"
            )

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

    async def _job_x_monitor(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Every 15 min: checks X for new mentions, likes, and DMs."""
        from tools.x_monitor import (
            build_client, get_user_id, check_new_mentions,
            check_like_changes, check_new_dms, format_notifications,
        )
        try:
            client = build_client(
                self._x_api_key, self._x_api_secret, self._x_bearer_token,
                self._x_access_token, self._x_access_token_secret,
            )

            # Resolve user ID (cached in DB after first run)
            user_id = await self.memory.get_setting("x_user_id")
            if not user_id:
                user_id = get_user_id(client)
                if user_id:
                    await self.memory.save_setting("x_user_id", user_id)
                else:
                    logger.warning("[X] Could not resolve user ID — skipping.")
                    return

            # Load persisted state
            last_mention_id = await self.memory.get_setting("x_last_mention_id") or None
            last_dm_id      = await self.memory.get_setting("x_last_dm_id") or None
            like_counts_raw = await self.memory.get_setting("x_like_counts")
            like_counts     = json.loads(like_counts_raw) if like_counts_raw else {}

            # Check activity
            mentions,     new_mention_id = check_new_mentions(client, user_id, last_mention_id)
            like_changes, new_like_counts = check_like_changes(client, user_id, like_counts)
            dms,          new_dm_id      = check_new_dms(client, last_dm_id)

            # Persist updated state
            if new_mention_id and new_mention_id != last_mention_id:
                await self.memory.save_setting("x_last_mention_id", new_mention_id)
            if new_dm_id and new_dm_id != last_dm_id:
                await self.memory.save_setting("x_last_dm_id", new_dm_id)
            if new_like_counts != like_counts:
                await self.memory.save_setting("x_like_counts", json.dumps(new_like_counts))

            # Filter by notification toggles
            from settings.notifications import get_settings
            ns = get_settings()
            if not ns.is_enabled("x_mentions"):
                mentions = []
            if not ns.is_enabled("x_likes"):
                like_changes = []
            if not ns.is_enabled("x_dms"):
                dms = []

            notifications = format_notifications(mentions, like_changes, dms)
            if not notifications:
                return

            chat_ids = await self.memory.get_telegram_chat_ids()
            for chat_id in chat_ids:
                for msg in notifications:
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=msg)
                    except Exception as e:
                        logger.error(f"[X] Failed to send notification to {chat_id}: {e}")

        except Exception as e:
            logger.exception(f"[X] Error in X monitor job: {e}")

    _BIRTHDAY_MAX_RETRIES = 8          # every 2h → covers 6 AM to ~10 PM
    _BIRTHDAY_RETRY_SECONDS = 7200

    async def _job_birthday_check(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Daily job at 6 AM CDMX: sends birthday WhatsApp messages.

        If a send fails (e.g. WAHA down at 6 AM), it alerts the owner ONCE and
        keeps retrying every 2 hours for the rest of the day, skipping the
        contacts already delivered — a birthday message is never silently lost.
        """
        from tools.birthday_scheduler import check_and_send_birthdays
        import datetime as _dt
        try:
            retry_num = (context.job.data or {}).get("retry", 0) if context.job else 0

            # Names already delivered today (persisted so restarts don't double-send)
            today_key = "birthday_sent_" + _dt.datetime.now(
                tz=zoneinfo.ZoneInfo("America/Mexico_City")
            ).strftime("%Y-%m-%d")
            sent_raw = await self.memory.get_setting(today_key)
            already_sent = set(json.loads(sent_raw)) if sent_raw else set()

            failures, delivered = check_and_send_birthdays(
                waha_url=self._waha_url,
                session=self._waha_session,
                api_key=self._waha_api_key,
                contacts_json=self._birthday_contacts_json,
                skip_names=already_sent,
            )

            if delivered:
                already_sent.update(delivered)
                await self.memory.save_setting(today_key, json.dumps(sorted(already_sent)))
                if retry_num > 0:
                    # A retry finally got through — tell the owner it's resolved
                    await context.bot.send_message(
                        chat_id=self._owner_chat_id,
                        text=f"✅ Mensaje(s) de cumpleaños entregado(s) tras reintento: {', '.join(delivered)}.",
                    )

            if failures:
                if retry_num == 0:
                    # First failure of the day — alert the owner once
                    detail = "\n".join(f"• {f}" for f in failures)
                    await context.bot.send_message(
                        chat_id=self._owner_chat_id,
                        text=(
                            f"🎂⚠️ No pude enviar mensaje(s) de cumpleaños:\n{detail}\n\n"
                            f"Reintentaré cada 2 horas el resto del día. "
                            f"Si WAHA sigue caído, considera enviarlos manualmente."
                        ),
                    )
                if retry_num < self._BIRTHDAY_MAX_RETRIES:
                    context.job_queue.run_once(
                        self._job_birthday_check,
                        when=self._BIRTHDAY_RETRY_SECONDS,
                        data={"retry": retry_num + 1},
                        name=f"birthday_retry_{retry_num + 1}",
                    )
                    logger.info(
                        f"[Birthday] {len(failures)} failure(s) — retry "
                        f"{retry_num + 1}/{self._BIRTHDAY_MAX_RETRIES} scheduled in 2h."
                    )
                else:
                    logger.error("[Birthday] Max retries reached — giving up for today.")
                    await context.bot.send_message(
                        chat_id=self._owner_chat_id,
                        text=(
                            "🎂❌ Agoté los reintentos de hoy para los mensajes de cumpleaños "
                            "pendientes. Envíalos manualmente, por favor."
                        ),
                    )
        except Exception as e:
            logger.exception(f"Error in birthday check job: {e}")

    async def _job_morning_agenda(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Daily job at morning_agenda_hour: sends the day's calendar agenda if toggle is on."""
        from settings.notifications import get_settings
        if not get_settings().is_enabled("calendar_reminders"):
            return

        chat_id = self._owner_chat_id
        if not chat_id:
            return

        try:
            from tools.calendar_tool import read_calendar_events
            tz = await self.memory.get_setting("timezone", "America/Mexico_City")

            # Get today's events only (days_ahead=1)
            events_text = read_calendar_events(
                credentials_json=self._calendar_credentials,
                days_ahead=1,
                max_results=20,
                timezone=tz,
            )

            import datetime, zoneinfo
            tz_info  = zoneinfo.ZoneInfo(tz)
            today    = datetime.datetime.now(tz_info)
            weekdays = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
            months   = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
            date_str = f"{weekdays[today.weekday()]} {today.day} de {months[today.month - 1]}"

            if "no hay eventos" in events_text.lower() or "no encontré" in events_text.lower():
                msg = f"Buenos días, Diego. Hoy es {date_str}.\n\nNo tienes eventos agendados para hoy. ¡Buen día!"
            else:
                msg = f"Buenos días, Diego. Hoy es {date_str}.\n\nTu agenda de hoy:\n\n{events_text}"

            await context.bot.send_message(chat_id=chat_id, text=msg)
            logger.info(f"Morning agenda sent to {chat_id}.")

        except Exception as e:
            logger.exception(f"Error in morning agenda job: {e}")

    async def _job_event_reminder(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Every 10 min: sends a reminder for timed events starting in 15-45 minutes."""
        from settings.notifications import get_settings
        if not get_settings().is_enabled("event_reminders"):
            return

        chat_id = self._owner_chat_id
        if not chat_id:
            return

        try:
            import datetime, zoneinfo
            from tools.calendar_tool import get_upcoming_events_structured

            tz     = await self.memory.get_setting("timezone", "America/Mexico_City")
            events = get_upcoming_events_structured(
                credentials_json=self._calendar_credentials,
                minutes_ahead=50,   # look up to 50 min ahead
                timezone=tz,
            )
            now    = datetime.datetime.now(zoneinfo.ZoneInfo(tz))
            today  = now.date().isoformat()

            for ev in events:
                minutes_away = int((ev["start"] - now).total_seconds() / 60)
                if not (10 <= minutes_away <= 45):
                    continue  # outside the reminder window

                key = f"{ev['id']}:{today}"
                if key in self._notified_event_ids:
                    continue  # already notified today

                self._notified_event_ids.add(key)

                start_str = ev["start"].strftime("%H:%M")
                end_str   = ev["end"].strftime("%H:%M")
                lines = [f"📅 En {minutes_away} min: {ev['title']} ({start_str} – {end_str})"]
                if ev["location"]:
                    lines.append(f"📍 {ev['location']}")

                await context.bot.send_message(chat_id=chat_id, text="\n".join(lines))
                logger.info(f"[EventReminder] Sent reminder for '{ev['title']}' in {minutes_away} min.")

            # Prune old keys to avoid unbounded growth (keep only today's)
            self._notified_event_ids = {
                k for k in self._notified_event_ids if k.endswith(today)
            }

        except Exception as e:
            logger.exception(f"Error in event reminder job: {e}")

    async def _job_payg0_pending_check(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Every 4 hours: notifies about outgoing Payg0 payments still unclaimed.

        Received payments are handled in real-time via the payment.received webhook.
        """
        from settings.notifications import get_settings
        if not get_settings().is_enabled("payg0_pending_reminders"):
            return

        chat_id = self._owner_chat_id
        if not chat_id:
            return

        try:
            import requests as _req

            resp = _req.get(
                "https://api.payg0.io/api/v1/payments/history",
                headers={"X-API-Key": self._payg0_api_key},
                params={"limit": 50},
                timeout=15,
            )
            resp.raise_for_status()
            data  = resp.json()
            items = data if isinstance(data, list) else (
                data.get("transactions") or data.get("payments") or
                data.get("data") or []
            )

            new_pending = [
                tx for tx in items
                if tx.get("status", "").upper() == "PENDING"
                and tx.get("id") not in self._notified_pending_ids
            ]

            if not new_pending:
                return

            lines = ["⏳ Tienes pagos enviados que aún no han sido reclamados:\n"]
            for tx in new_pending:
                tx_id     = tx.get("id", "")
                amount    = tx.get("amount", "?")
                recipient = tx.get("receiver_email") or tx.get("recipient") or tx.get("receiver_id", "?")
                created   = str(tx.get("created_at", tx.get("createdAt", "")))[:10]
                desc      = tx.get("description", "")
                line      = f"• ${amount} MXN → {recipient} ({created})"
                if desc:
                    line += f" — {desc}"
                lines.append(line)
                self._notified_pending_ids.add(tx_id)

            lines.append("\nPuedes pedirme que cancele alguno si ya no lo necesitas.")
            await context.bot.send_message(chat_id=chat_id, text="\n".join(lines))
            logger.info(f"[Payg0PendingCheck] Notified about {len(new_pending)} pending payment(s).")

        except Exception as e:
            logger.exception(f"Error in Payg0 pending check job: {e}")

    async def _job_waha_health_check(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Every 5 minutes: checks if WAHA / WhatsApp session is reachable.

        Sends ONE Telegram notification on each state transition:
          up → down : immediate alert so the owner knows before trying to send
          down → up : back-online confirmation with downtime duration

        Subsequent checks during ongoing downtime just log — no repeated alerts.

        Session statuses reported by WAHA:
          WORKING       — connected and sending messages normally
          SCAN_QR_CODE  — needs QR code scan to reconnect
          STARTING      — session is starting up
          STOPPED       — session was stopped
          FAILED        — session failed
        """
        import datetime as _dt
        import requests as _req

        hdrs = {"X-Api-Key": self._waha_api_key} if self._waha_api_key else {}
        session_status = "unknown"

        # Primary check: /api/sessions/{session} — gives the real session status string
        try:
            url  = f"{self._waha_url.rstrip('/')}/api/sessions/{self._waha_session}"
            resp = _req.get(url, headers=hdrs, timeout=8)
            if resp.status_code < 400:
                session_status = resp.json().get("status", "unknown")
        except Exception:
            pass

        # Fallback: if sessions endpoint not available, use /api/{session}/me
        if session_status == "unknown":
            try:
                url  = f"{self._waha_url.rstrip('/')}/api/{self._waha_session}/me"
                resp = _req.get(url, headers=hdrs, timeout=8)
                session_status = "WORKING" if resp.status_code < 400 else "unreachable"
            except Exception:
                session_status = "unreachable"

        is_up = session_status == "WORKING"

        # Keep the in-process flag in sync so send attempts know the current state
        from tools.whatsapp_sender import set_waha_known_down
        set_waha_known_down(not is_up)

        # Always log the current status at INFO so /logs shows recent health history
        logger.info(f"[WAHA] Health check — session_status={session_status}")

        last_status = await self.memory.get_setting("waha_health", "unknown")
        now_str = _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        if last_status == "down" and is_up:
            # Transition: down → up
            down_since = await self.memory.get_setting("waha_down_since", "?")
            await self.memory.save_setting("waha_health", "up")
            await self.memory.save_setting("waha_down_since", "")
            logger.info(f"[WAHA] Session back WORKING at {now_str} (was down since {down_since}) — notifying owner.")
            try:
                await context.bot.send_message(
                    chat_id=self._owner_chat_id,
                    text=f"✅ WhatsApp (WAHA) está de vuelta en línea.\n_(caída detectada: {down_since})_",
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"[WAHA] Could not send back-online notification: {e}")

        elif last_status != "down" and not is_up:
            # Transition: up/unknown → down — notify ONCE so the owner knows immediately
            await self.memory.save_setting("waha_health", "down")
            await self.memory.save_setting("waha_down_since", now_str)
            logger.warning(f"[WAHA] Session is DOWN at {now_str} — status={session_status}")
            try:
                await context.bot.send_message(
                    chat_id=self._owner_chat_id,
                    text=(
                        f"⚠️ WhatsApp (WAHA) está caído — estado: `{session_status}`.\n"
                        f"Los mensajes de WhatsApp no se entregarán hasta que se recupere.\n"
                        f"_(detectado: {now_str})_"
                    ),
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"[WAHA] Could not send down notification: {e}")

        elif not is_up and last_status == "down":
            # Ongoing downtime — log periodically so /logs shows the session is still down
            down_since = await self.memory.get_setting("waha_down_since", "?")
            logger.warning(f"[WAHA] Still DOWN — status={session_status} (since {down_since})")

            # Remind the owner at most once per 24h during a prolonged outage.
            # Without this, a weeks-long outage produces a single transition
            # alert that is easy to miss (this is how Joaco's birthday message
            # was lost on 2026-07-05).
            last_reminder_raw = await self.memory.get_setting("waha_down_last_reminder")
            now_ts = _dt.datetime.now(tz=_dt.timezone.utc).timestamp()
            last_reminder_ts = float(last_reminder_raw) if last_reminder_raw else 0.0
            if now_ts - last_reminder_ts >= 86400:
                await self.memory.save_setting("waha_down_last_reminder", str(now_ts))
                try:
                    await context.bot.send_message(
                        chat_id=self._owner_chat_id,
                        text=(
                            f"⏰ Recordatorio: WhatsApp (WAHA) sigue caído desde {down_since} "
                            f"(estado: `{session_status}`). Los mensajes de WhatsApp — incluidos "
                            f"los de cumpleaños — NO están saliendo. "
                            f"Si el estado es SCAN_QR_CODE, escanea el QR en el dashboard de WAHA."
                        ),
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.error(f"[WAHA] Could not send daily down reminder: {e}")

        elif last_status == "unknown":
            # First check — just record the current state, no notification
            await self.memory.save_setting("waha_health", "up" if is_up else "down")
            if not is_up:
                await self.memory.save_setting("waha_down_since", now_str)
            logger.info(f"[WAHA] Initial health status recorded: {session_status}.")

    async def _job_db_backup(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Daily job at 03:00 CDMX: sends SQLite database as a Telegram document backup."""
        chat_id = self._owner_chat_id
        if not chat_id:
            return

        import datetime as dt
        from config import config

        db_path = config.DB_PATH
        if not db_path.exists():
            logger.warning("DB backup: database file not found, skipping.")
            return

        try:
            today = dt.date.today().strftime("%Y-%m-%d")
            filename = f"beli_memory_backup_{today}.db"
            with open(db_path, "rb") as f:
                db_bytes = f.read()

            size_kb = len(db_bytes) / 1024
            await context.bot.send_document(
                chat_id=chat_id,
                document=db_bytes,
                filename=filename,
                caption=f"🗄️ Backup diario de Beli — {today} ({size_kb:.1f} KB)",
            )
            logger.info(f"DB backup sent to {chat_id} ({size_kb:.1f} KB).")
        except Exception as e:
            logger.exception(f"Error in DB backup job: {e}")

    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Logs unhandled errors from the bot and notifies the user when possible."""
        logger.error(f"Unhandled Telegram error: {context.error}", exc_info=context.error)
        # Try to notify the user so errors are never silent
        try:
            if isinstance(update, Update) and update.effective_message:
                await update.effective_message.reply_text(
                    f"❌ Ocurrió un error inesperado: {context.error}"
                )
        except Exception:
            pass  # Don't let the error handler itself crash

    # ------------------------------------------------------------------
    # START
    # ------------------------------------------------------------------

    async def _post_init(self, application) -> None:
        """Called by PTB after the bot is initialized but before polling starts."""
        # Store the running event loop so HTTP threads can submit work to it safely
        from channels.loop_ref import set_loop
        set_loop(asyncio.get_running_loop())

        # Restore WAHA known-down state from DB immediately so that any WhatsApp
        # send attempt in the first minutes after startup already has the correct
        # flag — without this, the health check takes 2 min to set it and any
        # send attempt in that window would generate a duplicate ⚠️ alert.
        if self._waha_url and self._owner_chat_id:
            from tools.whatsapp_sender import set_waha_known_down
            health = await self.memory.get_setting("waha_health", "unknown")
            if health == "down":
                set_waha_known_down(True)
                logger.info("[WAHA] Startup: restored known-down flag from DB — suppressing duplicate alerts.")

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
