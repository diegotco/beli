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
from channels.payg0_webhook import handle_payg0_webhook, register_payg0_webhook
from channels.sario_webhook import handle_sario_webhook, register_sario_webhook
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
    sario_callback    = None  # callable(payload: dict, raw: bytes, sig: str) -> None

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
        elif self.path == "/payg0/webhook":
            callback = _HealthHandler.payg0_callback
        elif self.path == "/sario/webhook":
            callback = _HealthHandler.sario_callback

        if callback:
            try:
                payload = json.loads(body)
                # Each service uses a different signature header
                if self.path == "/sario/webhook":
                    signature = self.headers.get("X-Sario-Signature", "")
                else:
                    signature = self.headers.get("X-Payg0-Signature", "")
                threading.Thread(
                    target=callback, args=(payload, body, signature), daemon=True
                ).start()
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
        google_calendar_credentials=config.GOOGLE_CALENDAR_CREDENTIALS,
        morning_agenda_hour=config.MORNING_AGENDA_HOUR,
        birthday_contacts_json=config.BIRTHDAY_CONTACTS,
        birthday_hour=config.BIRTHDAY_HOUR,
        x_api_key=config.X_API_KEY,
        x_api_secret=config.X_API_SECRET,
        x_bearer_token=config.X_BEARER_TOKEN,
        x_access_token=config.X_ACCESS_TOKEN,
        x_access_token_secret=config.X_ACCESS_TOKEN_SECRET,
        payg0_api_key=config.PAYG0_API_KEY,
    )

    # ── WhatsApp webhook ──────────────────────────────────────────────────────
    if config.OWNER_TELEGRAM_CHAT_ID and config.WAHA_URL:
        def _on_whatsapp(payload: dict, _body: bytes = b"", _sig: str = "") -> None:
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
        def _on_email(payload: dict, _body: bytes = b"", _sig: str = "") -> None:
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

    # ── Payg0 webhook ─────────────────────────────────────────────────────────
    if config.OWNER_TELEGRAM_CHAT_ID and config.PAYG0_API_KEY:
        def _on_payg0(payload: dict, raw_body: bytes = b"", signature: str = "") -> None:
            handle_payg0_webhook(
                payload=payload,
                raw_body=raw_body,
                signature_header=signature,
                bot_token=config.TELEGRAM_BOT_TOKEN,
                owner_chat_id=config.OWNER_TELEGRAM_CHAT_ID,
                webhook_secret=config.PAYG0_WEBHOOK_SECRET,
            )
        _HealthHandler.payg0_callback = _on_payg0
        logger.info("Payg0 webhook handler registered.")

        # Auto-register webhook with Payg0 if BELI_PUBLIC_URL is set
        if config.BELI_PUBLIC_URL and not config.PAYG0_WEBHOOK_SECRET:
            webhook_url = f"{config.BELI_PUBLIC_URL.rstrip('/')}/payg0/webhook"
            secret = register_payg0_webhook(config.PAYG0_API_KEY, webhook_url)
            if secret:
                logger.info(f"[Payg0] Webhook secret: {secret} — add as PAYG0_WEBHOOK_SECRET in Railway.")
    else:
        logger.info("Payg0 webhook disabled (PAYG0_API_KEY or OWNER_TELEGRAM_CHAT_ID not set).")

    # ── SARIO webhook ─────────────────────────────────────────────────────────
    if config.OWNER_TELEGRAM_CHAT_ID and config.SARIO_API_KEY:
        def _on_sario(payload: dict, raw_body: bytes = b"", signature: str = "") -> None:
            handle_sario_webhook(
                payload=payload,
                raw_body=raw_body,
                signature_header=signature,
                webhook_secret=config.SARIO_WEBHOOK_SECRET,
                sario_api_key=config.SARIO_API_KEY,
                bot_token=config.TELEGRAM_BOT_TOKEN,
                owner_chat_id=config.OWNER_TELEGRAM_CHAT_ID,
                brain=brain,
                memory=memory,
            )
        _HealthHandler.sario_callback = _on_sario
        logger.info("SARIO webhook handler registered.")

        # Auto-register webhook with SARIO on startup
        if config.BELI_PUBLIC_URL and not config.SARIO_WEBHOOK_SECRET:
            secret = register_sario_webhook(config.SARIO_API_KEY, config.BELI_PUBLIC_URL)
            if secret:
                logger.info(
                    f"[SARIO] Webhook secret obtained: {secret}\n"
                    f"        → Add as SARIO_WEBHOOK_SECRET in Railway."
                )
    else:
        logger.info("SARIO webhook disabled (SARIO_API_KEY or OWNER_TELEGRAM_CHAT_ID not set).")

    # ── HTTP server ───────────────────────────────────────────────────────────
    _start_health_server()

    logger.info("Beli is ready. Waiting for messages on Telegram...")
    telegram.run()


if __name__ == "__main__":
    main()
