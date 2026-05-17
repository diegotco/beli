"""
config.py - Carga y valida todas las configuraciones de Beli.
Lee el archivo .env y expone un objeto Config con todos los ajustes.
"""
import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables del archivo .env
load_dotenv()

# ============================================================
# CONFIGURACIÓN DE LOGGING
# ============================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        # Mostrar en consola
        logging.StreamHandler(sys.stdout),
        # Guardar en archivo
        logging.FileHandler(LOG_DIR / "beli.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger("beli.config")


# ============================================================
# CLASE DE CONFIGURACIÓN
# ============================================================

class Config:
    """Centraliza toda la configuración del proyecto."""

    # Rutas del proyecto
    BASE_DIR = Path(__file__).parent
    DATA_DIR = BASE_DIR / "data"
    DATA_DIR.mkdir(exist_ok=True)
    DB_PATH = DATA_DIR / "beli_memory.db"

    # Anthropic / Claude
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    # Telegram Bot (for Beli's chat interface with Diego)
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # Telegram User API credentials (shared by both sessions)
    TELEGRAM_API_ID: int = int(os.getenv("TELEGRAM_API_ID", "0"))
    TELEGRAM_API_HASH: str = os.getenv("TELEGRAM_API_HASH", "")

    # Diego's Telethon session — used only to search his contact list
    DIEGO_SESSION_PATH: str = str(DATA_DIR / "telethon_session")

    # Beli's own Telegram account — used to send & receive messages
    BELI_TELEGRAM_PHONE: str = os.getenv("BELI_TELEGRAM_PHONE", "")
    BELI_SESSION_PATH: str = str(DATA_DIR / "beli_session")

    # AgentMail (Beli's own email: beli@agentmail.to)
    AGENTMAIL_API_KEY: str = os.getenv("AGENTMAIL_API_KEY", "")
    AGENTMAIL_INBOX_ID: str = os.getenv("AGENTMAIL_INBOX_ID", "beli")

    # Memoria
    MEMORY_WINDOW: int = int(os.getenv("MEMORY_WINDOW", "20"))

    # Recordatorios mensuales
    REMINDER_HOUR: int = int(os.getenv("REMINDER_HOUR", "9"))
    REMINDER_MINUTE: int = int(os.getenv("REMINDER_MINUTE", "0"))
    REMINDER_DAYS_BEFORE_END: int = int(os.getenv("REMINDER_DAYS_BEFORE_END", "4"))

    @classmethod
    def validate(cls) -> None:
        """Verifica que todas las variables críticas estén configuradas."""
        errors = []

        if not cls.ANTHROPIC_API_KEY or cls.ANTHROPIC_API_KEY.startswith("sk-ant-xxx"):
            errors.append("ANTHROPIC_API_KEY no está configurada en el archivo .env")

        if not cls.TELEGRAM_BOT_TOKEN or cls.TELEGRAM_BOT_TOKEN.startswith("123456789"):
            errors.append("TELEGRAM_BOT_TOKEN no está configurada en el archivo .env")

        if errors:
            logger.error("=== ERRORES DE CONFIGURACIÓN ===")
            for err in errors:
                logger.error(f"  ✗ {err}")
            logger.error("Por favor edita el archivo .env con tus credenciales reales.")
            sys.exit(1)

        logger.info("Configuración validada correctamente.")
        logger.info(f"  Modelo Claude: {cls.CLAUDE_MODEL}")
        logger.info(f"  Ventana de memoria: {cls.MEMORY_WINDOW} mensajes")


config = Config()
