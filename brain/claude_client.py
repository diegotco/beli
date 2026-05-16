"""
brain/claude_client.py - Beli's brain: Anthropic API integration with tool use support.

Handles the full tool use loop:
  1. Send message to Claude with available tools
  2. If Claude calls a tool → execute it → return result to Claude
  3. Repeat until Claude gives a final text response
"""
import logging
import anthropic
from tools.definitions import TOOLS
from tools.executor import execute_tool

logger = logging.getLogger("beli.brain")

MAX_TOOL_ROUNDS = 5  # Safety limit to prevent infinite tool loops


class BelisBrain:
    """Interface with the Claude API. Supports tool use for real-world actions."""

    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        logger.info(f"Beli's brain initialized with model: {model}")

    async def think_with_image(
        self,
        system_prompt: str,
        history: list[dict],
        caption: str,
        image_b64: str,
        media_type: str = "image/jpeg",
        max_tokens: int = 1024,
    ) -> str:
        """Like think(), but the user's message includes an image (base64 encoded)."""
        image_message = {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_b64,
                    },
                },
                {
                    "type": "text",
                    "text": caption or "Diego envió esta imagen.",
                },
            ],
        }
        messages = history + [image_message]

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
                tools=TOOLS,
                messages=messages,
            )
            usage = response.usage
            logger.info(f"Tokens (image) — in: {usage.input_tokens}, out: {usage.output_tokens}")
            text_blocks = [b for b in response.content if hasattr(b, "text")]
            return text_blocks[0].text if text_blocks else "No pude procesar la imagen. Intenta de nuevo."
        except Exception as e:
            logger.exception(f"Error processing image: {e}")
            return "Hubo un error al procesar la imagen. Por favor intenta de nuevo."

    async def think(
        self,
        system_prompt: str,
        history: list[dict],
        new_message: str,
        max_tokens: int = 1024,
    ) -> str:
        """
        Generates Beli's response, executing any tool calls along the way.

        Args:
            system_prompt: Beli's personality and context
            history: Previous messages [{"role": "user/assistant", "content": "..."}]
            new_message: The new message from Diego
            max_tokens: Max tokens in the response

        Returns:
            Beli's final text response as a string
        """
        messages = history + [{"role": "user", "content": new_message}]

        for round_num in range(MAX_TOOL_ROUNDS):
            logger.debug(f"Claude round {round_num + 1}, messages: {len(messages)}")

            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=[
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    tools=TOOLS,
                    messages=messages,
                )
            except anthropic.APIConnectionError:
                logger.error("Connection error with Anthropic API")
                return "Lo siento, no puedo conectarme al servicio ahora mismo. Intenta de nuevo en unos segundos."
            except anthropic.RateLimitError:
                logger.error("Anthropic API rate limit reached")
                return "Estoy recibiendo demasiadas solicitudes. Espera un par de segundos e intenta de nuevo."
            except anthropic.APIStatusError as e:
                logger.error(f"Anthropic API error: {e.status_code} - {e.message}")
                return "Ocurrió un error inesperado. Por favor intenta de nuevo."

            # Log token usage
            usage = response.usage
            logger.info(
                f"Tokens — in: {usage.input_tokens}, out: {usage.output_tokens}, "
                f"cache_read: {getattr(usage, 'cache_read_input_tokens', 0)}"
            )

            # ── Case 1: Claude wants to use a tool ──────────────────────────
            if response.stop_reason == "tool_use":
                # Add Claude's response (with tool_use blocks) to the message history
                messages.append({"role": "assistant", "content": response.content})

                # Execute each tool call and collect results
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    logger.info(f"Tool call: {block.name} | inputs: {block.input}")
                    result = await execute_tool(block.name, block.input)
                    logger.info(f"Tool result: {result}")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

                # Return tool results to Claude so it can formulate the final response
                messages.append({"role": "user", "content": tool_results})
                continue  # Next round: Claude sees the results and responds

            # ── Case 2: Claude gave a final text response ───────────────────
            text_blocks = [b for b in response.content if hasattr(b, "text")]
            if text_blocks:
                return text_blocks[0].text

            # Fallback — should not happen
            logger.warning("Claude returned no text and no tool_use. Empty response.")
            return "No pude generar una respuesta. Por favor intenta de nuevo."

        # Exceeded tool rounds limit
        logger.error(f"Exceeded max tool rounds ({MAX_TOOL_ROUNDS})")
        return "La tarea requirió demasiados pasos y no pude completarla. Intenta siendo más específico."
