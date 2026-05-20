"""
brain/openai_client.py - GPT-4o wrapper for general-purpose conversation.

Used by the Router when a message doesn't require tools.
The same system_prompt and message history format as BelisBrain is reused so
the owner's personality context is always present.
"""
import logging
from openai import AsyncOpenAI

logger = logging.getLogger("beli.brain.openai")

GPT_MODEL = "gpt-4o"


class GPT4oClient:
    """Thin async wrapper around OpenAI Chat Completions API."""

    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)
        logger.info(f"GPT-4o client initialized (model: {GPT_MODEL})")

    async def chat(
        self,
        system_prompt: str,
        history: list[dict],
        new_message: str | None,
        max_tokens: int = 1024,
    ) -> str:
        """
        Generates a conversational response using GPT-4o.

        Args:
            system_prompt: Beli's personality/context (same as Claude uses)
            history: Previous messages [{"role": "user/assistant", "content": "..."}]
            new_message: The new message from the owner
            max_tokens: Max tokens in the response

        Returns:
            GPT-4o's text response as a string.
        """
        # Build the messages list with the system prompt first
        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        # Add conversation history, filtering out any non-standard roles
        for msg in history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role in ("user", "assistant") and isinstance(content, str):
                messages.append({"role": role, "content": content})

        if new_message:
            messages.append({"role": "user", "content": new_message})

        try:
            response = await self.client.chat.completions.create(
                model=GPT_MODEL,
                messages=messages,
                max_tokens=max_tokens,
            )
            text = response.choices[0].message.content or ""
            logger.info(
                f"GPT-4o — in: {response.usage.prompt_tokens}, "
                f"out: {response.usage.completion_tokens} tokens"
            )
            return text
        except Exception as e:
            logger.error(f"GPT-4o error: {e}")
            return "No pude generar una respuesta en este momento. Intenta de nuevo."
