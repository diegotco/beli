"""
channels/loop_ref.py - Shared reference to the PTB asyncio event loop.

PTB starts its event loop inside run_polling(), which is blocking.
We store a reference in post_init so HTTP-server threads can submit
work to the same loop via asyncio.run_coroutine_threadsafe().
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger("beli.loop_ref")

_loop: Optional[asyncio.AbstractEventLoop] = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Called from telegram._post_init() once the PTB loop is running."""
    global _loop
    _loop = loop
    logger.debug("[LoopRef] PTB event loop registered.")


def get_loop() -> Optional[asyncio.AbstractEventLoop]:
    """Returns the PTB event loop, or None if not yet initialized."""
    return _loop
