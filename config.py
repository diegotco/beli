"""
config.py - Loads and validates all of Beli's configuration.
Reads the .env file and exposes a Config object with all settings.
"""
import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load variables from the .env file
load_dotenv()

# ============================================================
# LOGGING SETUP
# ============================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        # Print to console
        logging.StreamHandler(sys.stdout),
        # Save to file
        logging.FileHandler(LOG_DIR / "beli.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger("beli.config")


# ============================================================
# CONFIGURATION CLASS
# ============================================================

class Config:
    """Centralizes all project configuration."""

    # Project paths
    BASE_DIR = Path(__file__).parent
    DATA_DIR = BASE_DIR / "data"
    DATA_DIR.mkdir(exist_ok=True)
    DB_PATH = DATA_DIR / "beli_memory.db"

    # Anthropic / Claude
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    # Telegram Bot (chat interface between Beli and the owner)
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_BOT_USERNAME: str = os.getenv("TELEGRAM_BOT_USERNAME", "")

    # Telegram User API credentials (shared by both sessions)
    TELEGRAM_API_ID: int = int(os.getenv("TELEGRAM_API_ID", "0"))
    TELEGRAM_API_HASH: str = os.getenv("TELEGRAM_API_HASH", "")

    # Owner's Telethon session — used only to search their contact list
    OWNER_SESSION_PATH: str = str(DATA_DIR / "telethon_session")
    OWNER_SESSION_STRING: str = os.getenv("OWNER_SESSION_STRING", "")

    # Beli's own Telegram account — used to send & receive messages
    BELI_TELEGRAM_PHONE: str = os.getenv("BELI_TELEGRAM_PHONE", "")
    BELI_SESSION_PATH: str = str(DATA_DIR / "beli_session")
    BELI_SESSION_STRING: str = os.getenv("BELI_SESSION_STRING", "")

    # AgentMail (Beli's own email: beli@agentmail.to)
    AGENTMAIL_API_KEY: str = os.getenv("AGENTMAIL_API_KEY", "")
    AGENTMAIL_INBOX_ID: str = os.getenv("AGENTMAIL_INBOX_ID", "beli")

    # Memory
    MEMORY_WINDOW: int = int(os.getenv("MEMORY_WINDOW", "20"))

    # Monthly reminders
    REMINDER_HOUR: int = int(os.getenv("REMINDER_HOUR", "9"))
    REMINDER_MINUTE: int = int(os.getenv("REMINDER_MINUTE", "0"))
    REMINDER_DAYS_BEFORE_END: int = int(os.getenv("REMINDER_DAYS_BEFORE_END", "4"))

    @classmethod
    def validate(cls) -> None:
        """Checks that all critical variables are configured."""
        errors = []

        if not cls.ANTHROPIC_API_KEY or cls.ANTHROPIC_API_KEY.startswith("sk-ant-xxx"):
            errors.append("ANTHROPIC_API_KEY is not set in the .env file")

        if not cls.TELEGRAM_BOT_TOKEN or cls.TELEGRAM_BOT_TOKEN.startswith("123456789"):
            errors.append("TELEGRAM_BOT_TOKEN is not set in the .env file")

        if errors:
            logger.error("=== CONFIGURATION ERRORS ===")
            for err in errors:
                logger.error(f"  ✗ {err}")
            logger.error("Please edit the .env file with your real credentials.")
            sys.exit(1)

        logger.info("Configuration validated successfully.")
        logger.info(f"  Claude model: {cls.CLAUDE_MODEL}")
        logger.info(f"  Memory window: {cls.MEMORY_WINDOW} messages")


config = Config()
