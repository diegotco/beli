"""
brain/claude_client.py - Beli's brain: Anthropic API integration with tool use support.

Handles the full tool use loop:
  1. Send message to Claude with available tools
  2. If Claude calls a tool → execute it → return result to Claude
  3. Repeat until Claude gives a final text response

Anti-hallucination guard:
  After the tool loop, before delivering the final text to the user, the code
  checks whether Claude is claiming a successful action (send email / Telegram)
  without a confirmed "✓ ENVIADO EXITOSAMENTE" from the actual tool.
  If the claim doesn't match the tool result, the fabricated text is replaced
  with the real outcome — no matter what Claude wrote.
"""
import logging
import anthropic
from tools.definitions import TOOLS
from tools.executor import execute_tool

logger = logging.getLogger("beli.brain")

MAX_TOOL_ROUNDS = 5  # Safety limit to prevent infinite tool loops

# Tools that perform real-world sends — their results are the source of truth
ACTION_TOOLS = {"send_telegram_message", "send_email", "send_whatsapp_message", "send_as_owner"}

# Signal returned by every successful tool execution (defined in email_sender,
# telegram_sender, and whatsapp_sender).  This is the ONLY accepted proof of a completed send.
SUCCESS_SIGNAL = "✓ ENVIADO EXITOSAMENTE"

# Spanish phrases Claude uses when it (falsely) claims to have sent something
_SUCCESS_CLAIM_PATTERNS = [
    "enviado exitosamente",
    "se envió",
    "el correo se envió",
    "el mensaje se envió",
    "fue enviado",
    "se ha enviado",
    "correo enviado",
    "mensaje enviado",
    "envié el correo",
    "envié el mensaje",
    "lo envié",
    "ya envié",
    "envié exitosamente",
]


def _claims_success(text: str) -> bool:
    """Returns True if the text contains a false-success pattern."""
    lower = text.lower()
    return any(p in lower for p in _SUCCESS_CLAIM_PATTERNS)


class BelisBrain:
    """Interface with the Claude API. Supports tool use for real-world actions."""

    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        logger.info(f"Brain initialized with model: {model}")

    async def think_with_image(
        self,
        system_prompt: str,
        history: list[dict],
        caption: str,
        image_b64: str,
        media_type: str = "image/jpeg",
        max_tokens: int = 1024,
    ) -> str:
        """Like think(), but the first user message includes an image (base64 encoded).
        Supports the full tool-use loop and anti-hallucination guard, same as think()."""
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
                    "text": caption or "El propietario envió esta imagen.",
                },
            ],
        }
        # Delegate to think() by injecting the image message into history
        return await self.think(
            system_prompt=system_prompt,
            history=history + [image_message],
            new_message=None,
            max_tokens=max_tokens,
        )

    async def think(
        self,
        system_prompt: str,
        history: list[dict],
        new_message: str | None,
        max_tokens: int = 1024,
    ) -> str:
        """
        Generates Beli's response, executing any tool calls along the way.

        Args:
            system_prompt: Beli's personality and context
            history: Previous messages [{"role": "user/assistant", "content": "..."}]
            new_message: The new message from the owner
            max_tokens: Max tokens in the response

        Returns:
            Beli's final text response as a string — guaranteed honest about tool results.
        """
        messages = history if new_message is None else history + [{"role": "user", "content": new_message}]

        # Collect results from action tools called during this turn.
        # Used by the anti-hallucination guard below.
        action_tool_results: list[str] = []

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
                # Surface actionable errors to the owner instead of a generic message
                body = getattr(e, "body", {}) or {}
                err_type = body.get("error", {}).get("type", "")
                if e.status_code == 400 and "credit balance" in str(e.message).lower():
                    return "⚠️ Sin créditos en Anthropic API. Ve a console.anthropic.com → Plans & Billing para recargar."
                if e.status_code == 529 or err_type == "overloaded_error":
                    return "Los servidores de Anthropic están sobrecargados en este momento. Intenta en unos minutos."
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

                    # Track results from send actions for the honesty guard
                    if block.name in ACTION_TOOLS:
                        action_tool_results.append(result)

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
            if not text_blocks:
                logger.warning("Claude returned no text and no tool_use. Empty response.")
                return "No pude generar una respuesta. Por favor intenta de nuevo."

            final_text = text_blocks[0].text

            # ── Anti-hallucination guard ────────────────────────────────────
            # Verify that success claims are backed by an actual tool result.
            tool_confirmed_success = any(SUCCESS_SIGNAL in r for r in action_tool_results)

            if _claims_success(final_text) and not tool_confirmed_success:
                if action_tool_results:
                    # Tools ran but returned an error — Claude is hiding the failure.
                    logger.error(
                        f"HALLUCINATION BLOCKED: Claude claimed success but tool returned: "
                        f"{action_tool_results}"
                    )
                    last_result = action_tool_results[-1]
                    return (
                        f"No pude completar la acción. Esto es lo que reportó el sistema:\n\n"
                        f"{last_result}"
                    )
                else:
                    # No action tool was called at all — pure fabrication.
                    logger.error(
                        "HALLUCINATION BLOCKED: Claude claimed success without calling any tool."
                    )
                    return (
                        "No ejecuté ninguna acción real — no llamé a ninguna herramienta. "
                        "¿Quieres que lo intente ahora?"
                    )

            return final_text

        # Exceeded tool rounds limit
        logger.error(f"Exceeded max tool rounds ({MAX_TOOL_ROUNDS})")
        return "La tarea requirió demasiados pasos y no pude completarla. Intenta siendo más específico."
