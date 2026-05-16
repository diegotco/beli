"""
memory/extractor.py - Extracción automática de hechos importantes.

Cada hora revisa las conversaciones nuevas y le pide a Claude que identifique
qué vale la pena recordar permanentemente sobre el usuario.
"""
import json
import logging

from brain.claude_client import BelisBrain
from memory.manager import MemoryManager

logger = logging.getLogger("beli.extractor")

EXTRACTION_PROMPT = """
Analiza esta conversación entre Diego y su asistente personal Beli.
Tu tarea es extraer hechos importantes sobre Diego que valga la pena recordar a largo plazo.

Qué SÍ recordar:
- Datos personales relevantes (trabajo, ciudad, familia, proyectos)
- Preferencias y hábitos importantes
- Objetivos o metas que mencionó
- Compromisos, fechas o eventos importantes
- Instrucciones explícitas sobre cómo quiere ser atendido
- Información de contexto que hará futuras conversaciones más útiles

Qué NO recordar:
- Preguntas o respuestas triviales del día a día
- Temas que ya están en los "Hechos ya guardados"
- Observaciones pasajeras sin relevancia futura

Hechos ya guardados (no duplicar ni parafrasear):
{existing_facts}

Conversación a analizar:
{conversation}

Responde ÚNICAMENTE con un array JSON de strings. Cada string es un hecho.
Si no hay nada nuevo importante, responde con un array vacío: []

Ejemplos de formato correcto:
["Trabaja en una startup de tecnología", "Prefiere que Beli sea directa y sin rodeos"]
[]
"""


class FactExtractor:
    """Extrae y guarda hechos importantes de las conversaciones de forma automática."""

    def __init__(self, memory: MemoryManager, brain: BelisBrain):
        self.memory = memory
        self.brain = brain

    async def run_for_all_users(self) -> None:
        """
        Punto de entrada del job horario.
        Procesa todos los usuarios con conversaciones nuevas.
        """
        logger.info("Iniciando extracción automática de hechos...")
        users = await self.memory.get_all_active_users()

        if not users:
            logger.info("No hay usuarios con conversaciones aún.")
            return

        total_new_facts = 0
        for channel, user_id in users:
            new_facts = await self._extract_for_user(channel, user_id)
            total_new_facts += new_facts

        logger.info(f"Extracción completada. Hechos nuevos guardados: {total_new_facts}")

    async def _extract_for_user(self, channel: str, user_id: str) -> int:
        """
        Extrae hechos para un usuario específico.
        Devuelve cuántos hechos nuevos se guardaron.
        """
        # Obtener solo los mensajes nuevos desde la última extracción
        last_id = await self.memory.get_extraction_checkpoint(channel, user_id)
        new_messages = await self.memory.get_messages_since(channel, user_id, last_id)

        if not new_messages:
            logger.debug(f"Sin mensajes nuevos para {channel}/{user_id}")
            return 0

        logger.info(f"Analizando {len(new_messages)} mensajes nuevos de {channel}/{user_id}")

        # Formatear la conversación para Claude
        conversation_text = "\n".join(
            f"{'Diego' if m['role'] == 'user' else 'Beli'}: {m['content']}"
            for m in new_messages
        )

        # Obtener hechos ya guardados para evitar duplicados
        existing_facts = await self.memory.get_facts(channel, user_id)
        existing_text = "\n".join(f"- {f}" for f in existing_facts) if existing_facts else "(ninguno aún)"

        # Construir el prompt de extracción
        prompt = EXTRACTION_PROMPT.format(
            existing_facts=existing_text,
            conversation=conversation_text,
        )

        # Pedir a Claude que identifique hechos importantes
        raw_response = await self.brain.think(
            system_prompt="Eres un sistema de extracción de información. Responde solo con JSON válido.",
            history=[],
            new_message=prompt,
            max_tokens=512,
        )

        # Parsear la respuesta JSON
        facts = self._parse_facts(raw_response)

        if not facts:
            logger.debug(f"No se encontraron hechos nuevos para {channel}/{user_id}")
        else:
            logger.info(f"Hechos extraídos para {channel}/{user_id}: {facts}")

        # Guardar hechos nuevos (verificando que no sean duplicados exactos)
        saved = 0
        for fact in facts:
            fact = fact.strip()
            if fact and not await self.memory.fact_exists(channel, user_id, fact):
                await self.memory.save_fact(channel, user_id, fact)
                saved += 1

        # Actualizar el checkpoint al último mensaje procesado
        last_processed_id = new_messages[-1]["id"]
        await self.memory.save_extraction_checkpoint(channel, user_id, last_processed_id)

        return saved

    def _parse_facts(self, raw: str) -> list[str]:
        """Extrae el array JSON de la respuesta de Claude de forma segura."""
        raw = raw.strip()
        try:
            # Intentar parsear directamente
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(f) for f in data if f]
        except json.JSONDecodeError:
            pass

        # Si Claude añadió texto antes/después del JSON, buscar el array
        try:
            start = raw.index("[")
            end = raw.rindex("]") + 1
            data = json.loads(raw[start:end])
            if isinstance(data, list):
                return [str(f) for f in data if f]
        except (ValueError, json.JSONDecodeError):
            pass

        logger.warning(f"No se pudo parsear la respuesta del extractor: {raw[:200]}")
        return []
