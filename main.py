"""
main.py - Entry point for Beli.

Run with:  python main.py
"""
import asyncio
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import config
from brain.claude_client import BelisBrain
from memory.manager import MemoryManager
from channels.telegram import TelegramChannel

logger = logging.getLogger("beli.main")

# ── Health check HTTP server ─────────────────────────────────────────────────

class _HealthHandler(BaseHTTPRequestHandler):
    """Tiny HTTP handler: GET /health → 200 OK. Everything else → 404."""

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):  # suppress access logs to keep output clean
        pass


def _start_health_server() -> None:
    """Starts the health-check HTTP server in a background daemon thread."""
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health server listening on port {port} — GET /health returns 200 OK")


async def startup() -> None:
    """Initializes Beli's components before starting."""
    logger.info("=" * 50)
    logger.info("  Starting Beli — Personal AI Assistant")
    logger.info("=" * 50)

    # Validate that all required credentials are configured
    config.validate()

    # Initialize memory database
    memory = MemoryManager(
        db_path=config.DB_PATH,
        window_size=config.MEMORY_WINDOW,
    )
    await memory.initialize()

    # Initialize the brain (Claude)
    brain = BelisBrain(
        api_key=config.ANTHROPIC_API_KEY,
        model=config.CLAUDE_MODEL,
    )

    return memory, brain


def main() -> None:
    """Starts Beli with all configured channels."""
    # Initialize async components
    loop = asyncio.new_event_loop()
    memory, brain = loop.run_until_complete(startup())
    loop.close()

    # Start the Telegram channel
    telegram = TelegramChannel(
        token=config.TELEGRAM_BOT_TOKEN,
        brain=brain,
        memory=memory,
        reminder_hour=config.REMINDER_HOUR,
        reminder_minute=config.REMINDER_MINUTE,
        reminder_days_before_end=config.REMINDER_DAYS_BEFORE_END,
    )

    # Start lightweight health-check server (used by UptimeRobot / Railway)
    _start_health_server()

    logger.info("Beli is ready. Waiting for messages on Telegram...")
    telegram.run()


if __name__ == "__main__":
    main()
