"""
main.py - Entry point for Beli.

Run with:  python main.py
"""
import asyncio
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import config
from brain.claude_client import BelisBrain
from brain.openai_client import GPT4oClient
from brain.router import Router
from memory.manager import MemoryManager
from channels.telegram import TelegramChannel
from channels.whatsapp_webhook import handle_webhook
from channels.email_webhook import handle_email_webhook, register_webhook
from tools.executor import set_memory

logger = logging.getLogger("beli.main")

# ── HTTP server ──────────────────────────────────────────────────────────────

class _HealthHandler(BaseHTTPRequestHandler):
    """
    HTTP handler for Beli's embedded web server.
      GET  /health              → 200 OK  (used by GitHub Actions health check)
      POST /whatsapp/webhook    → 200 OK  (receives events from WAHA)
      POST /email/webhook       → 200 OK  (receives events from AgentMail)
    """

    whatsapp_callback = None  # callable(payload: dict) -> None
    email_callback    = None  # callable(payload: dict) -> None

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):  # noqa: N802
        length  = int(self.headers.get("Content-Length", 0))
        body    = self.rfile.read(length)

        # Always respond 200 immediately so services don't retry
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

        # Access via class, not self — avoids Python descriptor binding
        # (self.callback would bind the handler instance as first arg)
        callback = None
        if self.path == "/whatsapp/webhook":
            callback = _HealthHandler.whatsapp_callback
        elif self.path == "/email/webhook":
            callback = _HealthHandler.email_callback

        if callback:
            try:
                payload = json.loads(body)
                threading.Thread(target=callback, args=(payload,), daemon=True).start()
            except Exception as e:
                logger.error(f"Webhook parse error ({self.path}): {e}")

    def log_message(self, fmt, *args):  # suppress access logs
        pass


def _start_health_server() -> None:
    """Starts the HTTP server in a background daemon thread."""
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"HTTP server listening on port {port}")


# ── Startup ───────────────────────────────────────────────────────────────────

async def startup() -> None:
    """Initializes Beli's components before starting."""
    logger.info("=" * 50)
    logger.info("  Starting Beli — Personal AI Assistant")
    logger.info("=" * 50)

    config.validate()

    memory = MemoryManager(db_path=config.DB_PATH, window_size=config.MEMORY_WINDOW)
    await memory.initialize()
    set_memory(memory)

    claude = BelisBrain(api_key=config.ANTHROPIC_API_KEY, model=config.CLAUDE_MODEL)

    # Wire up GPT-4o routing if an OpenAI key is provided
    if config.OPENAI_API_KEY:
        gpt = GPT4oClient(api_key=config.OPENAI_API_KEY)
        brain = Router(claude_brain=claude, gpt_client=gpt)
        logger.info("Router active: Claude (tools) + GPT-4o (general chat)")
    else:
        brain = Router(claude_brain=claude, gpt_client=None)
        logger.info("Router active: Claude only (no OPENAI_API_KEY set)")

    return memory, brain


def main() -> None:
    """Starts Beli with all configured channels."""
    loop = asyncio.new_event_loop()
    memory, brain = loop.run_until_complete(startup())
    loop.close()

    telegram = TelegramChannel(
        token=config.TELEGRAM_BOT_TOKEN,
        brain=brain,
        memory=memory,
        reminder_hour=config.REMINDER_HOUR,
        reminder_minute=config.REMINDER_MINUTE,
        reminder_days_before_end=config.REMINDER_DAYS_BEFORE_END,
        telegram_api_id=config.TELEGRAM_API_ID,
        telegram_api_hash=config.TELEGRAM_API_HASH,
        owner_session_string=config.OWNER_SESSION_STRING,
        owner_chat_id=config.OWNER_TELEGRAM_CHAT_ID,
        waha_url=config.WAHA_URL,
        waha_session=config.WAHA_SESSION,
        waha_api_key=config.WAHA_API_KEY,
        birthday_contacts_json=config.BIRTHDAY_CONTACTS,
        birthday_hour=config.BIRTHDAY_HOUR,
        x_api_key=config.X_API_KEY,
        x_api_secret=config.X_API_SECRET,
        x_bearer_token=config.X_BEARER_TOKEN,
        x_access_token=config.X_ACCESS_TOKEN,
        x_access_token_secret=config.X_ACCESS_TOKEN_SECRET,
    )

    # ── WhatsApp webhook ──────────────────────────────────────────────────────
    if config.OWNER_TELEGRAM_CHAT_ID and config.WAHA_URL:
        def _on_whatsapp(payload: dict) -> None:
            handle_webhook(
                payload=payload,
                bot_token=config.TELEGRAM_BOT_TOKEN,
                owner_chat_id=config.OWNER_TELEGRAM_CHAT_ID,
                waha_url=config.WAHA_URL,
                waha_session=config.WAHA_SESSION,
                waha_api_key=config.WAHA_API_KEY,
                groq_api_key=config.GROQ_API_KEY,
            )
        _HealthHandler.whatsapp_callback = _on_whatsapp
        logger.info("WhatsApp webhook handler registered.")
    else:
        logger.info("WhatsApp webhook disabled (WAHA_URL or OWNER_TELEGRAM_CHAT_ID not set).")

    # ── Email webhook ─────────────────────────────────────────────────────────
    if config.OWNER_TELEGRAM_CHAT_ID and config.AGENTMAIL_API_KEY:
        def _on_email(payload: dict) -> None:
            handle_email_webhook(
                payload=payload,
                bot_token=config.TELEGRAM_BOT_TOKEN,
                owner_chat_id=config.OWNER_TELEGRAM_CHAT_ID,
                brain=brain,
                memory=memory,
                owner_email=config.OWNER_EMAIL,
            )
        _HealthHandler.email_callback = _on_email
        logger.info("Email webhook handler registered.")

        # Auto-register webhook with AgentMail if BELI_PUBLIC_URL is set
        if config.BELI_PUBLIC_URL:
            webhook_url = f"{config.BELI_PUBLIC_URL.rstrip('/')}/email/webhook"
            register_webhook(config.AGENTMAIL_API_KEY, config.AGENTMAIL_INBOX_ID, webhook_url)
    else:
        logger.info("Email webhook disabled (AGENTMAIL_API_KEY or OWNER_TELEGRAM_CHAT_ID not set).")

    # ── HTTP server ───────────────────────────────────────────────────────────
    _start_health_server()

    logger.info("Beli is ready. Waiting for messages on Telegram...")
    telegram.run()


if __name__ == "__main__":
    main()
