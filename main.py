"""
main.py - Punto de entrada de Beli.

Ejecutar con:  python main.py
"""
import asyncio
import logging

from config import config
from brain.claude_client import BelisBrain
from memory.manager import MemoryManager
from channels.telegram import TelegramChannel
from channels.beli_listener import BeliListener
from telegram import Bot

logger = logging.getLogger("beli.main")


async def startup() -> None:
    """Inicializa los componentes de Beli antes de arrancar."""
    logger.info("=" * 50)
    logger.info("  Iniciando Beli — Asistente Personal de IA")
    logger.info("=" * 50)

    # Validar que todas las credenciales estén configuradas
    config.validate()

    # Inicializar base de datos de memoria
    memory = MemoryManager(
        db_path=config.DB_PATH,
        window_size=config.MEMORY_WINDOW,
    )
    await memory.initialize()

    # Inicializar el cerebro (Claude)
    brain = BelisBrain(
        api_key=config.ANTHROPIC_API_KEY,
        model=config.CLAUDE_MODEL,
    )

    return memory, brain


def main() -> None:
    """Arranca Beli con todos los canales configurados."""
    # Inicializar componentes async
    loop = asyncio.new_event_loop()
    memory, brain = loop.run_until_complete(startup())
    loop.close()

    # Set up Beli's incoming-message listener (her own Telegram account)
    beli_listener = None
    if config.BELI_TELEGRAM_PHONE and config.TELEGRAM_API_ID:
        beli_listener = BeliListener(
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH,
            session_path=config.BELI_SESSION_PATH,
            bot=Bot(token=config.TELEGRAM_BOT_TOKEN),
            memory=memory,
        )
        logger.info("Beli's Telegram listener configured.")
    else:
        logger.warning("BELI_TELEGRAM_PHONE not set — incoming message listener disabled.")

    # Iniciar canal Telegram
    telegram = TelegramChannel(
        token=config.TELEGRAM_BOT_TOKEN,
        brain=brain,
        memory=memory,
        reminder_hour=config.REMINDER_HOUR,
        reminder_minute=config.REMINDER_MINUTE,
        reminder_days_before_end=config.REMINDER_DAYS_BEFORE_END,
        beli_listener=beli_listener,
    )

    logger.info("Beli está lista. Esperando mensajes en Telegram...")
    telegram.run()


if __name__ == "__main__":
    main()
