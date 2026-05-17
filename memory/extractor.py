"""
memory/extractor.py - Automatic extraction of important facts.

Runs hourly: reviews new conversations and asks Claude to identify
what is worth remembering permanently about the user.
"""
import json
import logging

from brain.claude_client import BelisBrain
from memory.manager import MemoryManager

logger = logging.getLogger("beli.extractor")

EXTRACTION_PROMPT = """
Analyze this conversation between the owner and their personal assistant Beli.
Your task is to extract important facts about the owner that are worth remembering long-term.

What TO remember:
- Relevant personal data (work, city, family, projects)
- Important preferences and habits
- Goals or objectives they mentioned
- Commitments, dates, or important events
- Explicit instructions about how they want to be assisted
- Background information that will make future conversations more useful

What NOT to remember:
- Trivial day-to-day questions or answers
- Topics already in "Already saved facts"
- Passing observations with no future relevance

Already saved facts (do not duplicate or paraphrase):
{existing_facts}

Conversation to analyze:
{conversation}

Reply ONLY with a JSON array of strings. Each string is one fact.
If there is nothing new and important, reply with an empty array: []

Examples of correct format:
["Works at a tech startup", "Prefers Beli to be direct and concise"]
[]
"""


class FactExtractor:
    """Automatically extracts and saves important facts from conversations."""

    def __init__(self, memory: MemoryManager, brain: BelisBrain):
        self.memory = memory
        self.brain = brain

    async def run_for_all_users(self) -> None:
        """
        Entry point for the hourly job.
        Processes all users with new conversations.
        """
        logger.info("Starting automatic fact extraction...")
        users = await self.memory.get_all_active_users()

        if not users:
            logger.info("No users with conversations yet.")
            return

        total_new_facts = 0
        for channel, user_id in users:
            new_facts = await self._extract_for_user(channel, user_id)
            total_new_facts += new_facts

        logger.info(f"Extraction complete. New facts saved: {total_new_facts}")

    async def _extract_for_user(self, channel: str, user_id: str) -> int:
        """
        Extracts facts for a specific user.
        Returns how many new facts were saved.
        """
        # Get only new messages since the last extraction
        last_id = await self.memory.get_extraction_checkpoint(channel, user_id)
        new_messages = await self.memory.get_messages_since(channel, user_id, last_id)

        if not new_messages:
            logger.debug(f"No new messages for {channel}/{user_id}")
            return 0

        logger.info(f"Analyzing {len(new_messages)} new messages for {channel}/{user_id}")

        # Format the conversation for Claude
        conversation_text = "\n".join(
            f"{'Usuario' if m['role'] == 'user' else 'Beli'}: {m['content']}"
            for m in new_messages
        )

        # Get already saved facts to avoid duplicates
        existing_facts = await self.memory.get_facts(channel, user_id)
        existing_text = "\n".join(f"- {f}" for f in existing_facts) if existing_facts else "(none yet)"

        # Build the extraction prompt
        prompt = EXTRACTION_PROMPT.format(
            existing_facts=existing_text,
            conversation=conversation_text,
        )

        # Ask Claude to identify important facts
        raw_response = await self.brain.think(
            system_prompt="You are an information extraction system. Reply only with valid JSON.",
            history=[],
            new_message=prompt,
            max_tokens=512,
        )

        # Parse the JSON response
        facts = self._parse_facts(raw_response)

        if not facts:
            logger.debug(f"No new facts found for {channel}/{user_id}")
        else:
            logger.info(f"Facts extracted for {channel}/{user_id}: {facts}")

        # Save new facts (checking for exact duplicates)
        saved = 0
        for fact in facts:
            fact = fact.strip()
            if fact and not await self.memory.fact_exists(channel, user_id, fact):
                await self.memory.save_fact(channel, user_id, fact)
                saved += 1

        # Update the checkpoint to the last processed message
        last_processed_id = new_messages[-1]["id"]
        await self.memory.save_extraction_checkpoint(channel, user_id, last_processed_id)

        return saved

    def _parse_facts(self, raw: str) -> list[str]:
        """Safely extracts the JSON array from Claude's response."""
        raw = raw.strip()
        try:
            # Try to parse directly
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(f) for f in data if f]
        except json.JSONDecodeError:
            pass

        # If Claude added text before/after the JSON, search for the array
        try:
            start = raw.index("[")
            end = raw.rindex("]") + 1
            data = json.loads(raw[start:end])
            if isinstance(data, list):
                return [str(f) for f in data if f]
        except (ValueError, json.JSONDecodeError):
            pass

        logger.warning(f"Could not parse extractor response: {raw[:200]}")
        return []
