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

MAX_TOOL_ROUNDS = 20  # Safety limit to prevent infinite tool loops

# Tools that perform real-world sends — their results are the source of truth
ACTION_TOOLS = {"send_telegram_message", "send_email", "send_whatsapp_message", "send_as_owner", "send_gmail_message"}
CALENDAR_WRITE_TOOLS = {"create_calendar_event", "delete_calendar_event", "update_calendar_event"}

# Tasks tools — tracked separately so we can catch task-related hallucinations
TASK_TOOLS = {"add_to_shopping_list", "create_task"}

# Web tools — tracked to catch fabricated errors
WEB_TOOLS = {"web_scrape", "web_search", "web_fill_form", "web_api_call"}

# Phrases Claude uses when it (falsely) claims a web/API call failed without actually calling the tool
_WEB_ERROR_CLAIM_PATTERNS = [
    "endpoint devolvió un error",
    "la ruta no existe",
    "el endpoint no existe",
    "error 404",
    "error 400",
    "error 500",
    "no pude completar el registro",
    "no pude acceder a la página",
    "la página no respondió",
    "no pude llamar",
    "falló la llamada",
]

def _claims_web_error(text: str) -> bool:
    lower = text.lower()
    return any(p in lower for p in _WEB_ERROR_CLAIM_PATTERNS)

# Data-read tools — their results are the source of truth for balance/transaction claims
DATA_TOOLS = {"payg0_balance", "payg0_transactions", "payg0_usage"}

# Signal returned by every successful tool execution (defined in email_sender,
# telegram_sender, and whatsapp_sender).  This is the ONLY accepted proof of a completed send.
SUCCESS_SIGNAL = "✓ ENVIADO EXITOSAMENTE"

# Signal prefix returned by add_to_shopping_list on success
TASK_SUCCESS_SIGNAL = "✓ Agregué"

# Phrases Claude uses when it (falsely) claims to know Payg0 balance/transactions
_PAYG0_CLAIM_PATTERNS = [
    "tu saldo",
    "saldo actual",
    "saldo en payg0",
    "saldo es",
    "saldo de",
    "tienes $",
    "tienes mxn",
    "tu saldo es",
    "el saldo es",
    "saldo disponible",
    "tus transacciones",
    "tus últimas transacciones",
    "tu historial",
    "tus movimientos",
    "últimos pagos",
]

# Spanish phrases Claude uses when it (falsely) claims to have sent something.
# IMPORTANT: be specific — overly broad patterns fire during legitimate
# planning/progress responses and corrupt the retry loop.
_SUCCESS_CLAIM_PATTERNS = [
    # singular — clear post-send claims
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
    # plural — only the unambiguous forms
    "enviados exitosamente",
    "todos recibieron",
    "recibieron el mensaje",
    # short confirmation forms Beli uses as standalone lines
    "enviado ✓",
    "mensaje enviado ✓",
    "listo, enviado",
]

CALENDAR_SUCCESS_SIGNAL = "✓ Evento"

# Phrases Claude uses when it (falsely) claims to have created/modified a calendar event,
# OR when it wrongly asserts an event already exists based on conversation history alone.
_CALENDAR_CLAIM_PATTERNS = [
    # Creation claims
    "agendé",
    "lo agendé",
    "ya agendé",
    "agendé el recordatorio",
    "agendé el evento",
    "creé el evento",
    "el evento fue creado",
    "evento creado",
    "recordatorio creado",
    "agregué al calendario",
    "añadí al calendario",
    "lo añadí al calendario",
    "lo agregué al calendario",
    "actualicé el evento",
    "modifiqué el evento",
    "eliminé el evento",
    # "Already exists" claims based on history (not verified via read_calendar_events)
    "ya tienes ese recordatorio",
    "ya está agendado",
    "ya lo tienes agendado",
    "ya está en tu calendario",
    "ya lo agendamos",
    "recordatorio agendado para",
    "tienes ese evento",
]

def _claims_calendar_action(text: str) -> bool:
    lower = text.lower()
    return any(p in lower for p in _CALENDAR_CLAIM_PATTERNS)

# Phrases Claude uses when it (falsely) claims to have added tasks/shopping items
_TASK_CLAIM_PATTERNS = [
    "agregué",
    "añadí",
    "añadí a tu lista",
    "agregué a tu lista",
    "los agregué",
    "ya los agregué",
    "guardé en tu lista",
    "actualicé tu lista",
]


def _claims_success(text: str) -> bool:
    """Returns True if the text contains a false send-success pattern."""
    lower = text.lower()
    return any(p in lower for p in _SUCCESS_CLAIM_PATTERNS)


def _claims_task_success(text: str) -> bool:
    """Returns True if the text claims to have added tasks/shopping items."""
    lower = text.lower()
    return any(p in lower for p in _TASK_CLAIM_PATTERNS)


def _claims_payg0_data(text: str) -> bool:
    """Returns True if the text claims to have Payg0 balance or transaction data."""
    lower = text.lower()
    return any(p in lower for p in _PAYG0_CLAIM_PATTERNS)


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
        action_tool_results:   list[str] = []
        task_tool_results:     list[str] = []
        data_tool_results:     list[str] = []
        calendar_tool_results: list[str] = []
        web_tool_results:      list[str] = []
        _hallucination_retry_done = False  # allow one automatic retry

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

                    # Track results from send/task/data/calendar actions for the honesty guard
                    if block.name in ACTION_TOOLS:
                        action_tool_results.append(result)
                    if block.name in TASK_TOOLS:
                        task_tool_results.append(result)
                    if block.name in DATA_TOOLS:
                        data_tool_results.append(result)
                    if block.name in CALENDAR_WRITE_TOOLS:
                        calendar_tool_results.append(result)
                    if block.name in WEB_TOOLS:
                        web_tool_results.append(result)

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
                # If a task tool just succeeded, use its result as the confirmation
                if task_tool_results and any(TASK_SUCCESS_SIGNAL in r for r in task_tool_results):
                    return task_tool_results[-1]
                # If a send tool just succeeded, confirm briefly
                if action_tool_results and any(SUCCESS_SIGNAL in r for r in action_tool_results):
                    return "Listo ✓"
                logger.warning("Claude returned no text and no tool_use. Empty response.")
                return "No pude generar una respuesta. Por favor intenta de nuevo."

            final_text = text_blocks[0].text

            # ── Anti-hallucination guard ────────────────────────────────────
            # Verify that success claims are backed by an actual tool result.
            tool_confirmed_success = any(SUCCESS_SIGNAL in r for r in action_tool_results)

            # If Claude is asking for confirmation it hasn't acted yet — never block these.
            is_asking_confirmation = any(
                p in final_text.lower()
                for p in ["¿confirmas?", "¿confirmas", "¿envío", "¿lo envío", "¿procedo", "¿lo hago"]
            )

            # Log which pattern triggered (helps diagnose false positives)
            triggered_pattern = next(
                (p for p in _SUCCESS_CLAIM_PATTERNS if p in final_text.lower()), None
            )
            if triggered_pattern:
                logger.info(
                    f"Guard candidate — pattern={triggered_pattern!r} "
                    f"tool_confirmed={tool_confirmed_success} "
                    f"is_asking_confirmation={is_asking_confirmation} "
                    f"text[:200]={final_text[:200]!r}"
                )

            if _claims_success(final_text) and not tool_confirmed_success and not is_asking_confirmation:
                logger.error(
                    f"HALLUCINATION GUARD fired — pattern={triggered_pattern!r} "
                    f"final_text[:300]={final_text[:300]!r} "
                    f"action_tool_results={action_tool_results}"
                )
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
                    # On first occurrence: inject a correction and retry silently.
                    if not _hallucination_retry_done:
                        _hallucination_retry_done = True
                        logger.warning(
                            "HALLUCINATION: claimed success without calling tool — injecting retry"
                        )
                        messages.append({"role": "assistant", "content": response.content})
                        messages.append({
                            "role": "user",
                            "content": (
                                "Error: escribiste el resultado sin haber llamado ninguna herramienta. "
                                "Los envíos NO se realizaron. "
                                "Debes ejecutar las herramientas ahora, una por una, empezando por el PRIMER contacto. "
                                "Llama find_telegram_contact o send_as_owner para el primer contacto — "
                                "no respondas con texto, ejecuta el tool call directamente."
                            ),
                        })
                        continue  # retry — Claude sees the correction
                    logger.error(
                        "HALLUCINATION BLOCKED (2nd attempt): claimed success without any tool call."
                    )
                    return (
                        "Hubo un problema interno al ejecutar la acción. "
                        "Por favor intenta de nuevo."
                    )

            # ── Task anti-hallucination guard ───────────────────────────────
            # Catches cases where Claude claims to have added items to the
            # shopping list without actually calling add_to_shopping_list.
            task_confirmed = any(TASK_SUCCESS_SIGNAL in r for r in task_tool_results)

            if _claims_task_success(final_text) and not task_confirmed:
                logger.error(
                    f"TASK HALLUCINATION GUARD fired — final_text[:200]={final_text[:200]!r} "
                    f"task_tool_results={task_tool_results}"
                )
                if task_tool_results:
                    # Tool ran but returned an error
                    last_result = task_tool_results[-1]
                    logger.error(f"TASK HALLUCINATION BLOCKED: tool returned error: {last_result}")
                    return (
                        f"No pude agregar los ítems a tu lista. Esto es lo que reportó el sistema:\n\n"
                        f"{last_result}"
                    )
                else:
                    # Tool was never called — pure fabrication
                    if not _hallucination_retry_done:
                        _hallucination_retry_done = True
                        logger.warning(
                            "TASK HALLUCINATION: claimed to add items without calling tool — injecting retry"
                        )
                        messages.append({"role": "assistant", "content": response.content})
                        messages.append({
                            "role": "user",
                            "content": (
                                "Error interno: dijiste que agregaste los ítems pero no llamaste a "
                                "add_to_shopping_list. Debes llamar AHORA a add_to_shopping_list con "
                                "todos los ítems en el array 'items'. No respondas con texto, solo ejecuta el tool call."
                            ),
                        })
                        continue  # retry
                    logger.error("TASK HALLUCINATION BLOCKED (2nd attempt): no tool call.")
                    return (
                        "Hubo un problema al agregar los ítems. Por favor intenta de nuevo."
                    )

            # ── Calendar anti-hallucination guard ───────────────────────────
            # Catches cases where Claude claims to have created/modified a
            # calendar event without actually calling create_calendar_event etc.
            calendar_confirmed = any(CALENDAR_SUCCESS_SIGNAL in r for r in calendar_tool_results)

            if _claims_calendar_action(final_text) and not calendar_confirmed:
                logger.error(
                    f"CALENDAR HALLUCINATION GUARD fired — final_text[:200]={final_text[:200]!r} "
                    f"calendar_tool_results={calendar_tool_results}"
                )
                if calendar_tool_results:
                    last_result = calendar_tool_results[-1]
                    return (
                        f"No pude completar la acción en el calendario. Esto reportó el sistema:\n\n"
                        f"{last_result}"
                    )
                else:
                    if not _hallucination_retry_done:
                        _hallucination_retry_done = True
                        logger.warning(
                            "CALENDAR HALLUCINATION: claimed calendar action without calling tool — injecting retry"
                        )
                        messages.append({"role": "assistant", "content": response.content})
                        messages.append({
                            "role": "user",
                            "content": (
                                "Error: dijiste que agendaste o modificaste un evento pero no llamaste "
                                "ninguna herramienta de calendario. "
                                "Debes llamar AHORA a create_calendar_event, update_calendar_event o "
                                "delete_calendar_event según corresponda. "
                                "No respondas con texto, ejecuta el tool call directamente."
                            ),
                        })
                        continue  # retry
                    logger.error("CALENDAR HALLUCINATION BLOCKED (2nd attempt): no tool call.")
                    return "No pude completar la acción en el calendario. Por favor intenta de nuevo."

            # ── Web tool fabricated-error guard ─────────────────────────────
            # Catches cases where Claude claims a web/API call failed
            # without actually calling any web tool.
            if _claims_web_error(final_text) and not web_tool_results:
                logger.error(
                    f"WEB ERROR HALLUCINATION GUARD fired — "
                    f"final_text[:200]={final_text[:200]!r}"
                )
                if not _hallucination_retry_done:
                    _hallucination_retry_done = True
                    logger.warning(
                        "WEB HALLUCINATION: claimed web error without calling tool — injecting retry"
                    )
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({
                        "role": "user",
                        "content": (
                            "Error: reportaste un fallo de red o API sin haber llamado ninguna herramienta web. "
                            "No puedes saber si hubo un error sin intentarlo. "
                            "Llama AHORA a web_api_call, web_scrape, o web_fill_form según corresponda. "
                            "Ejecuta el tool call directamente — no respondas con texto."
                        ),
                    })
                    continue
                logger.error("WEB HALLUCINATION BLOCKED (2nd attempt): no tool call.")
                return "No pude completar la acción web. Por favor intenta de nuevo."

            # ── Payg0 data anti-hallucination guard ─────────────────────────
            # Catches cases where Claude states Payg0 balance/transactions
            # without actually calling payg0_balance or payg0_transactions.
            if _claims_payg0_data(final_text) and not data_tool_results:
                logger.error(
                    f"PAYG0 HALLUCINATION GUARD fired — final_text[:200]={final_text[:200]!r}"
                )
                if not _hallucination_retry_done:
                    _hallucination_retry_done = True
                    logger.warning(
                        "PAYG0 HALLUCINATION: claimed balance/transactions without calling tool — injecting retry"
                    )
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({
                        "role": "user",
                        "content": (
                            "Error interno: respondiste con datos de Payg0 sin llamar al tool. "
                            "Debes llamar AHORA a payg0_balance o payg0_transactions según lo que se pidió. "
                            "No respondas con texto, solo ejecuta el tool call."
                        ),
                    })
                    continue  # retry
                logger.error("PAYG0 HALLUCINATION BLOCKED (2nd attempt): no tool call.")
                return (
                    "Hubo un problema al consultar tu saldo de Payg0. Por favor intenta de nuevo."
                )

            return final_text

        # Exceeded tool rounds limit
        logger.error(f"Exceeded max tool rounds ({MAX_TOOL_ROUNDS})")
        # If some sends succeeded, report partial success instead of a generic error
        if action_tool_results:
            sent_count = sum(1 for r in action_tool_results if SUCCESS_SIGNAL in r)
            if sent_count:
                return f"Completé {sent_count} envío(s) pero la tarea era demasiado larga para terminarla en un solo turno. Pídeme que continúe si quedaron pendientes."
        return "La tarea requirió demasiados pasos y no pude completarla. Intenta dividirla en partes más pequeñas."
