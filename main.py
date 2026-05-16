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

    # Iniciar canal Telegram
    telegram = TelegramChannel(
        token=config.TELEGRAM_BOT_TOKEN,
        brain=brain,
        memory=memory,
        reminder_hour=config.REMINDER_HOUR,
        reminder_minute=config.REMINDER_MINUTE,
        reminder_days_before_end=config.REMINDER_DAYS_BEFORE_END,
    )

    logger.info("Beli está lista. Esperando mensajes en Telegram...")
    telegram.run()


if __name__ == "__main__":
    main()
