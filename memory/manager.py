"""
memory/manager.py - Beli's persistent memory management using SQLite.

Stores conversation history and important facts about each user.
The database is created automatically at data/beli_memory.db.
"""
import logging
import aiosqlite
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("beli.memory")


class MemoryManager:
    """Manages persistent memory across conversations."""

    def __init__(self, db_path: Path, window_size: int = 20):
        self.db_path = str(db_path)
        self.window_size = window_size

    async def initialize(self) -> None:
        """Creates database tables if they do not exist."""
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
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key        TEXT PRIMARY KEY,
                    value      TEXT NOT NULL,
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            # Index to speed up per-user lookups
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_user
                ON conversations (channel, user_id, id)
            """)
            await db.commit()
        logger.info(f"Database initialized at: {self.db_path}")

    async def save_message(self, channel: str, user_id: str, role: str, content: str) -> None:
        """
        Saves a message to the conversation history.
        role: 'user' or 'assistant'
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO conversations (channel, user_id, role, content) VALUES (?, ?, ?, ?)",
                (channel, str(user_id), role, content),
            )
            await db.commit()

    async def get_history(self, channel: str, user_id: str) -> list[dict]:
        """
        Retrieves the last N messages for a user to use as context.
        Returns a list of dicts with 'role' and 'content' (Claude API format).
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
        logger.debug(f"History loaded for {channel}/{user_id}: {len(history)} messages")
        return history

    async def save_fact(self, channel: str, user_id: str, fact: str) -> None:
        """Saves an important fact about the user for permanent recall."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO user_facts (channel, user_id, fact) VALUES (?, ?, ?)",
                (channel, str(user_id), fact),
            )
            await db.commit()
        logger.info(f"Fact saved for {channel}/{user_id}: {fact}")

    async def get_facts(self, channel: str, user_id: str) -> list[str]:
        """Retrieves all saved facts for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT fact FROM user_facts WHERE channel = ? AND user_id = ? ORDER BY id",
                (channel, str(user_id)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [row["fact"] for row in rows]

    async def get_messages_since(self, channel: str, user_id: str, after_id: int) -> list[dict]:
        """Returns messages with id greater than after_id (used for fact extraction)."""
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

    async def get_all_facts(self) -> list[str]:
        """Returns every stored fact, across all channels and users.

        Reads user_facts directly rather than going through the conversation
        list, so facts survive a cleared history.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT fact FROM user_facts ORDER BY id") as cursor:
                rows = await cursor.fetchall()
        return [row["fact"] for row in rows]

    async def get_all_active_users(self) -> list[tuple[str, str]]:
        """Returns all (channel, user_id) pairs that have conversations."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT DISTINCT channel, user_id FROM conversations"
            ) as cursor:
                rows = await cursor.fetchall()
        return [(row["channel"], row["user_id"]) for row in rows]

    async def get_extraction_checkpoint(self, channel: str, user_id: str) -> int:
        """Returns the id of the last message already processed for extraction. 0 if never processed."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT last_message_id FROM extraction_checkpoints WHERE channel = ? AND user_id = ?",
                (channel, str(user_id)),
            ) as cursor:
                row = await cursor.fetchone()
        return row["last_message_id"] if row else 0

    async def save_extraction_checkpoint(self, channel: str, user_id: str, last_message_id: int) -> None:
        """Saves the id of the last processed message to avoid reprocessing it."""
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
        """Checks if a very similar fact is already saved (avoids exact duplicates)."""
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

    async def get_setting(self, key: str, default: str = "") -> str:
        """Returns a global setting value, or default if not set."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ) as cursor:
                row = await cursor.fetchone()
        return row["value"] if row else default

    async def save_setting(self, key: str, value: str) -> None:
        """Saves or updates a global setting."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
                """,
                (key, value),
            )
            await db.commit()

    async def clear_history(self, channel: str, user_id: str) -> int:
        """Clears a user's conversation history. Returns the number of messages deleted."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM conversations WHERE channel = ? AND user_id = ?",
                (channel, str(user_id)),
            )
            await db.commit()
            count = cursor.rowcount
        logger.info(f"History cleared for {channel}/{user_id}: {count} messages deleted")
        return count
