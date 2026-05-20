"""
brain/router.py - Intelligent routing between Claude (tools) and GPT-4o (chat).

Decision logic:
  1. A lightweight Claude Haiku classifier checks whether the message requires
     external tools (send message, create event, read chats, tasks, etc.)
  2. If YES  → Claude handles the full tool-use loop (BelisBrain.think)
  3. If NO   → GPT-4o answers for faster, cheaper general conversation
  4. Fallback → if GPT-4o is not configured, Claude handles everything

Images are always routed through Claude (multimodal support).

The Router exposes the same think() / think_with_image() interface as
BelisBrain, making it a transparent drop-in replacement.
"""
import logging
import anthropic

from brain.claude_client import BelisBrain
from brain.openai_client import GPT4oClient

logger = logging.getLogger("beli.brain.router")

# Short messages that confirm a pending action — must always go to Claude
_CONFIRMATION_PATTERNS = [
    "sí", "si", "dale", "confirma", "confirmado", "ok", "okay", "sí por favor",
    "si por favor", "hazlo", "envíalo", "envíala", "mándalo", "mándala",
    "adelante", "procede", "perfecto", "listo", "va", "claro", "sí señor",
]

def _is_confirmation(message: str) -> bool:
    """Returns True if the message looks like a short confirmation."""
    normalized = message.strip().lower().rstrip(".,!¡¿?")
    return normalized in _CONFIRMATION_PATTERNS or len(normalized.split()) <= 3

# Keywords that indicate the last assistant turn involved a tool result
_TOOL_RESULT_KEYWORDS = [
    # Confirmation requests
    "¿confirmas?", "confirmas", "¿envío", "¿lo envío", "¿procedo",
    # Tool read results (reading chats, messages, calendar, tasks)
    "revisé", "leí los mensajes", "encontré", "no encontré",
    "no hay mensajes", "últimos", "mensajes con", "mensajes de",
    "conversaciones", "chat", "tu agenda", "tu calendario",
    "no pude", "parece que no",
]

def _history_has_pending_action(history: list[dict]) -> bool:
    """
    Returns True if the last assistant message involved a tool action or result,
    meaning the user's follow-up should go to Claude (not GPT-4o).
    """
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            content = (msg.get("content") or "").lower()
            return any(k in content for k in _TOOL_RESULT_KEYWORDS)
    return False

# Classifier model: Haiku is fast and cheap — only needs to output 1 token
_CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"

_CLASSIFIER_SYSTEM = """\
You are a message router for a personal AI assistant.
Your ONLY job is to decide whether the user's message requires calling external tools.

Tools are needed for:
- Sending messages (Telegram, WhatsApp, email)
- Reading chats or inbox
- Creating, editing, or deleting calendar events
- Creating, completing, or deleting tasks / shopping list items
- Setting timezone or preferences
- Any real-world action or data lookup from connected services

Tools are NOT needed for:
- General questions and information ("¿cuándo fue...?", "¿qué es...?")
- Advice, opinions, brainstorming
- Writing help, translation, coding
- Small talk and greetings
- Math, logic, or reasoning problems

Reply with exactly one word: TOOLS or CHAT"""


class Router:
    """
    Drop-in replacement for BelisBrain that routes messages to the best model.

    Usage:
        router = Router(claude_brain=brain, gpt_client=gpt)
        response = await router.think(system_prompt, history, message)
    """

    def __init__(self, claude_brain: BelisBrain, gpt_client: GPT4oClient | None = None):
        self.claude = claude_brain
        self.gpt = gpt_client
        self._classifier = anthropic.AsyncAnthropic(
            api_key=claude_brain.client.api_key
        )

    # ── Public interface (same as BelisBrain) ─────────────────────────────────

    async def think(
        self,
        system_prompt: str,
        history: list[dict],
        new_message: str | None,
        max_tokens: int = 1024,
    ) -> str:
        """Routes the message to Claude (tools) or GPT-4o (chat)."""
        # If GPT-4o isn't configured, behave exactly like Claude
        if self.gpt is None or new_message is None:
            return await self.claude.think(system_prompt, history, new_message, max_tokens)

        # Confirmations must always go to Claude — GPT-4o has no tools and
        # would output the tool call as plain text instead of executing it.
        if _is_confirmation(new_message) and _history_has_pending_action(history):
            logger.info("Router → Claude (confirmation of pending action)")
            return await self.claude.think(system_prompt, history, new_message, max_tokens)

        # Classify the message
        needs_tools = await self._classify(new_message)

        if needs_tools:
            logger.info("Router → Claude (tools needed)")
            return await self.claude.think(system_prompt, history, new_message, max_tokens)
        else:
            logger.info("Router → GPT-4o (general chat)")
            return await self.gpt.chat(system_prompt, history, new_message, max_tokens)

    async def think_with_image(
        self,
        system_prompt: str,
        history: list[dict],
        caption: str,
        image_b64: str,
        media_type: str = "image/jpeg",
        max_tokens: int = 1024,
    ) -> str:
        """Images always go through Claude (multimodal support)."""
        logger.info("Router → Claude (image message)")
        return await self.claude.think_with_image(
            system_prompt=system_prompt,
            history=history,
            caption=caption,
            image_b64=image_b64,
            media_type=media_type,
            max_tokens=max_tokens,
        )

    # ── Classifier ────────────────────────────────────────────────────────────

    async def _classify(self, message: str) -> bool:
        """
        Returns True if the message requires tool use, False for general chat.
        Uses Claude Haiku with max_tokens=1 for speed and cost efficiency.
        Falls back to True (Claude) on any error so no message is ever dropped.
        """
        try:
            resp = await self._classifier.messages.create(
                model=_CLASSIFIER_MODEL,
                max_tokens=5,
                system=_CLASSIFIER_SYSTEM,
                messages=[{"role": "user", "content": message}],
            )
            answer = (resp.content[0].text if resp.content else "TOOLS").strip().upper()
            logger.debug(f"Classifier answer: {answer!r} for: {message[:80]!r}")
            return answer != "CHAT"
        except Exception as e:
            logger.warning(f"Classifier failed ({e}), defaulting to Claude")
            return True  # Safe fallback: Claude handles everything
