"""
settings/notifications.py - Persisted notification preferences for Beli.

Stores a JSON file at data/notification_settings.json.
All keys default to False (notifications off by default).

Keys:
  whatsapp_direct  — direct WhatsApp messages
  whatsapp_groups  — WhatsApp group messages
  telegram_direct  — direct Telegram messages
  telegram_groups  — Telegram group/channel messages
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger("beli.settings.notifications")

_SETTINGS_FILENAME = "notification_settings.json"

_DEFAULTS: dict[str, bool] = {
    "whatsapp_direct": False,
    "whatsapp_groups": False,
    "telegram_direct": False,
    "telegram_groups": False,
}


class NotificationSettings:
    """Reads and writes notification toggle state from a JSON file."""

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / _SETTINGS_FILENAME
        self._data: dict[str, bool] = dict(_DEFAULTS)
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Loads settings from disk, falling back to defaults for missing keys."""
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for key in _DEFAULTS:
                if key in raw:
                    self._data[key] = bool(raw[key])
        except Exception as e:
            logger.warning(f"[NotificationSettings] Could not load {self._path}: {e}")

    def _save(self) -> None:
        """Persists current settings to disk."""
        try:
            self._path.write_text(
                json.dumps(self._data, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"[NotificationSettings] Could not save {self._path}: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_notify_whatsapp(self, chat_id: str) -> bool:
        """Returns True if WhatsApp notifications are enabled for the given chat_id.

        Uses whatsapp_groups for group chats (chat_id ends with @g.us),
        whatsapp_direct for everything else.
        """
        if chat_id.endswith("@g.us"):
            return self._data["whatsapp_groups"]
        return self._data["whatsapp_direct"]

    def should_notify_telegram(self, is_group: bool) -> bool:
        """Returns True if Telegram notifications are enabled for the given chat type."""
        if is_group:
            return self._data["telegram_groups"]
        return self._data["telegram_direct"]

    def toggle(self, key: str) -> bool:
        """Toggles a boolean setting key, saves to disk, and returns the new value."""
        if key not in _DEFAULTS:
            raise ValueError(f"Unknown notification key: {key!r}")
        new_value = not self._data[key]
        self._data[key] = new_value
        self._save()
        logger.info(f"[NotificationSettings] {key} → {new_value}")
        return new_value

    def is_enabled(self, key: str) -> bool:
        """Returns the current value of a setting key."""
        if key not in _DEFAULTS:
            raise ValueError(f"Unknown notification key: {key!r}")
        return self._data[key]


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_instance: NotificationSettings | None = None


def get_settings() -> NotificationSettings:
    """Returns the module-level singleton, initializing it lazily."""
    global _instance
    if _instance is None:
        from config import config  # lazy import — avoids circular dependencies
        _instance = NotificationSettings(data_dir=config.DATA_DIR)
    return _instance
