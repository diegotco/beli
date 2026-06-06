"""
log_buffer.py - In-memory ring buffer for recent log entries.

Attached to Python's root logger at startup so every module's logs
are captured. Exposed via the /logs Telegram command so logs can be
inspected without going to Railway.

Usage:
    from log_buffer import log_buffer
    lines = log_buffer.get_last(50)
"""
import logging
from collections import deque


class _LogBuffer(logging.Handler):
    """A logging.Handler that stores the last `capacity` formatted records."""

    def __init__(self, capacity: int = 500):
        super().__init__()
        self._buf: deque[str] = deque(maxlen=capacity)
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s — %(message)s",
                datefmt="%H:%M:%S",
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._buf.append(self.format(record))
        except Exception:
            self.handleError(record)

    def get_last(self, n: int = 50) -> list[str]:
        """Return the last *n* log lines (oldest first)."""
        return list(self._buf)[-n:]

    def clear(self) -> None:
        self._buf.clear()


# Singleton — imported everywhere
log_buffer = _LogBuffer(capacity=500)


def attach() -> None:
    """Attach the buffer to the root logger.  Call once at startup."""
    root = logging.getLogger()
    # Avoid double-attaching on reload
    for h in root.handlers:
        if isinstance(h, _LogBuffer):
            return
    log_buffer.setLevel(logging.DEBUG)
    root.addHandler(log_buffer)
