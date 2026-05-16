"""
memory/manager.py - Gestión de memoria persistente de Beli usando SQLite.

Guarda el historial de conversaciones y hechos importantes sobre cada usuario.
La base de datos se crea automáticamente en data/beli_memory.db.
"""
import logging
import aiosqlite
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("beli.memory")


class MemoryManager:
    """Gestiona la memoria persistente entre conversaciones."""

    def __init__(self, db_path: Path, window_size: int = 20):
        self.db_path = str(db_path)
        self.window_size = window_size

    async def initialize(self) -> None:
        """Crea las tablas de la base de datos si no existen."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel   TEXT NOT NULL,
                    user_id   TEXT NOT NULL,
                    role      TEXT NOT NULL,
                    content   TEXT NOT NULL,
                    timestamp TEXT DEFAULT (datetime('now'))
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_facts (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel    TEXT NOT NULL,
                    user_id    TEXT NOT NULL,
                    fact       TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS extraction_checkpoints (
                    channel         TEXT NOT NULL,
                    user_id         TEXT NOT NULL,
                    last_message_id INTEGER NOT NULL DEFAULT 0,
                    updated_at      TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (channel, user_id)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS telegram_chats (
                    chat_id    TEXT PRIMARY KEY,
                    first_seen TEXT DEFAULT (datetime('now')),
                    last_seen  TEXT DEFAULT (datetime('now'))
                )
            """)
            # Índice para acelerar búsquedas por usuario
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_user
                ON conversations (channel, user_id, id)
            """)
            await db.commit()
        logger.info(f"Base de datos inicializada en: {self.db_path}")

    async def save_message(self, channel: str, user_id: str, role: str, content: str) -> None:
        """
        Guarda un mensaje en el historial.
        role: 'user' o 'assistant'
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO conversations (channel, user_id, role, content) VALUES (?, ?, ?, ?)",
                (channel, str(user_id), role, content),
            )
            await db.commit()

    async def get_history(self, channel: str, user_id: str) -> list[dict]:
        """
        Recupera los últimos N mensajes de un usuario para usarlos como contexto.
        Devuelve lista de dicts con 'role' y 'content' (formato Claude API).
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT role, content FROM (
                    SELECT role, content, id
                    FROM conversations
                    WHERE channel = ? AND user_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) ORDER BY id ASC
                """,
                (channel, str(user_id), self.window_size),
            ) as cursor:
                rows = await cursor.fetchall()

        history = [{"role": row["role"], "content": row["content"]} for row in rows]
        logger.debug(f"Historial cargado para {channel}/{user_id}: {len(history)} mensajes")
        return history

    async def save_fact(self, channel: str, user_id: str, fact: str) -> None:
        """Guarda un hecho importante sobre el usuario para recordarlo siempre."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO user_facts (channel, user_id, fact) VALUES (?, ?, ?)",
                (channel, str(user_id), fact),
            )
            await db.commit()
        logger.info(f"Hecho guardado para {channel}/{user_id}: {fact}")

    async def get_facts(self, channel: str, user_id: str) -> list[str]:
        """Recupera todos los hechos guardados de un usuario."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT fact FROM user_facts WHERE channel = ? AND user_id = ? ORDER BY id",
                (channel, str(user_id)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [row["fact"] for row in rows]

    async def get_messages_since(self, channel: str, user_id: str, after_id: int) -> list[dict]:
        """Devuelve los mensajes con id mayor a after_id (para extracción de hechos)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, role, content FROM conversations
                WHERE channel = ? AND user_id = ? AND id > ?
                ORDER BY id ASC
                """,
                (channel, str(user_id), after_id),
            ) as cursor:
                rows = await cursor.fetchall()
        return [{"id": row["id"], "role": row["role"], "content": row["content"]} for row in rows]

    async def get_all_active_users(self) -> list[tuple[str, str]]:
        """Devuelve todos los pares (channel, user_id) que tienen conversaciones."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT DISTINCT channel, user_id FROM conversations"
            ) as cursor:
                rows = await cursor.fetchall()
        return [(row["channel"], row["user_id"]) for row in rows]

    async def get_extraction_checkpoint(self, channel: str, user_id: str) -> int:
        """Devuelve el id del último mensaje ya procesado para extracción. 0 si nunca se procesó."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT last_message_id FROM extraction_checkpoints WHERE channel = ? AND user_id = ?",
                (channel, str(user_id)),
            ) as cursor:
                row = await cursor.fetchone()
        return row["last_message_id"] if row else 0

    async def save_extraction_checkpoint(self, channel: str, user_id: str, last_message_id: int) -> None:
        """Guarda el id del último mensaje procesado para no reprocesarlo."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO extraction_checkpoints (channel, user_id, last_message_id)
                VALUES (?, ?, ?)
                ON CONFLICT(channel, user_id) DO UPDATE SET
                    last_message_id = excluded.last_message_id,
                    updated_at = datetime('now')
                """,
                (channel, str(user_id), last_message_id),
            )
            await db.commit()

    async def fact_exists(self, channel: str, user_id: str, fact: str) -> bool:
        """Verifica si un hecho muy similar ya está guardado (evita duplicados exactos)."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM user_facts WHERE channel = ? AND user_id = ? AND fact = ?",
                (channel, str(user_id), fact),
            ) as cursor:
                return await cursor.fetchone() is not None

    async def register_telegram_chat(self, chat_id: str) -> None:
        """Saves a Telegram chat_id so Beli can send proactive messages later."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO telegram_chats (chat_id) VALUES (?)
                ON CONFLICT(chat_id) DO UPDATE SET last_seen = datetime('now')
                """,
                (str(chat_id),),
            )
            await db.commit()

    async def get_telegram_chat_ids(self) -> list[str]:
        """Returns all known Telegram chat IDs."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT chat_id FROM telegram_chats") as cursor:
                rows = await cursor.fetchall()
        return [row["chat_id"] for row in rows]

    async def clear_history(self, channel: str, user_id: str) -> int:
        """Borra el historial de conversación de un usuario. Devuelve cuántos mensajes se borraron."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM conversations WHERE channel = ? AND user_id = ?",
                (channel, str(user_id)),
            )
            await db.commit()
            count = cursor.rowcount
        logger.info(f"Historial borrado para {channel}/{user_id}: {count} mensajes eliminados")
        return count
