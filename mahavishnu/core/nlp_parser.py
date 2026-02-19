"""Natural Language Parser for Mahavishnu Task Orchestration.

Parses natural language task descriptions into structured task requests:
- Intent classification (create, list, update, delete, search)
- Entity extraction (title, repository, priority, tags, due date)
- Confidence scoring with fallback prompts

Usage:
    from mahavishnu.core.nlp_parser import NlpParser

    parser = NlpParser()
    result = await parser.parse("create a bug fix task for session-buddy repo")

    if result.confidence >= 0.8:
        task = TaskCreateRequest(**result.entities)
    else:
        # Prompt for clarification
        clarification = parser.get_clarification_prompt(result)
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """Supported intents for task operations."""

    CREATE = "create"
    LIST = "list"
    UPDATE = "update"
    DELETE = "delete"
    SEARCH = "search"
    ASSIGN = "assign"
    COMPLETE = "complete"
    BLOCK = "block"
    UNKNOWN = "unknown"


class Priority(str, Enum):
    """Task priority levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ParsedEntity:
    """Extracted entity from natural language."""

    name: str
    value: Any
    confidence: float
    source_text: str


@dataclass
class ParseResult:
    """Result of NLP parsing."""

    intent: Intent
    confidence: float
    entities: dict[str, ParsedEntity]
    raw_text: str
    clarification_needed: list[str] = field(default_factory=list)

    def to_task_request(self) -> dict[str, Any]:
        """Convert to task request dictionary."""
        result = {}
        for name, entity in self.entities.items():
            result[name] = entity.value
        return result

    def is_confident(self, threshold: float = 0.8) -> bool:
        """Check if parsing confidence meets threshold."""
        return self.confidence >= threshold


class NlpParser:
    """
    Natural Language Parser for task operations.

    Uses pattern matching and keyword extraction for intent classification
    and entity extraction. Designed to work without external NLP dependencies
    but can be extended with ML models.

    Features:
    - Intent classification with confidence scores
    - Entity extraction (title, repository, priority, tags, due date)
    - Graceful handling of ambiguous input
    - Clarification prompt generation
    """

    # Intent patterns with weights
    INTENT_PATTERNS: dict[Intent, list[tuple[str, float]]] = {
        Intent.CREATE: [
            (r"\b(create|add|new|make|start)\b", 0.8),
            (r"\b(task|issue|ticket|item)\b", 0.3),
            (r"\bfor\s+(\w+)\s+repo\b", 0.2),
        ],
        Intent.LIST: [
            (r"\b(list|show|display|get all|all tasks)\b", 0.9),
            (r"\b(what are|what is|show me)\b", 0.5),
            (r"\btasks?\s+(for|in|from)\b", 0.3),
        ],
        Intent.UPDATE: [
            (r"\b(update|change|modify|edit|set)\b", 0.8),
            (r"\b(mark|set)\s+(status|priority)\b", 0.6),
            (r"\btask\s+\d+\b", 0.3),
        ],
        Intent.DELETE: [
            (r"\b(delete|remove|trash|cancel)\b", 0.9),
            (r"\bget rid of\b", 0.7),
        ],
        Intent.SEARCH: [
            (r"\b(search|find|look for|query)\b", 0.9),
            (r"\bcontaining|with|about\b", 0.4),
            (r"\b(tasks?|items?)\s+(with|containing|about)\b", 0.5),
        ],
        Intent.ASSIGN: [
            (r"\b(assign|give|delegate)\b", 0.9),
            (r"\bto\s+(\w+)\b", 0.3),
        ],
        Intent.COMPLETE: [
            (r"\b(complete|finish|done|close|resolve)\b", 0.9),
            (r"\bmark\s+(as\s+)?(complete|done|finished)\b", 0.8),
        ],
        Intent.BLOCK: [
            (r"\b(block|hold|pause|stop)\b", 0.8),
            (r"\bwaiting\s+(for|on)\b", 0.7),
        ],
    }

    # Priority keywords (order matters - check multi-word phrases first in extraction)
    PRIORITY_KEYWORDS: dict[Priority, list[str]] = {
        Priority.CRITICAL: ["critical", "urgent", "asap", "emergency", "blocker", "hotfix"],
        Priority.HIGH: ["high priority", "high", "important", "soon"],
        Priority.MEDIUM: ["medium priority", "normal priority", "medium", "normal", "regular"],
        Priority.LOW: ["low priority", "nice to have", "low", "minor", "eventually", "someday"],
    }

    # Repository name patterns (includes hyphens and underscores)
    REPO_PATTERNS = [
        r"\bfor\s+([a-zA-Z0-9_-]+)\s+repo",
        r"\bin\s+([a-zA-Z0-9_-]+)\s+repo",
        r"\brepo[:\s]+([a-zA-Z0-9_-]+)",
        r"\b([a-zA-Z0-9_-]+)/(?:main|master|develop)\b",
    ]

    # Tag patterns
    TAG_PATTERNS = [
        r"#(\w+)",
        r"\btag(?:s)?[:\s]+([\w\s,-]+)",
        r"\blabeled?\s+(?:as\s+)?([\w\s,-]+)",
    ]

    # Due date patterns
    DUE_DATE_PATTERNS = [
        (r"\bby\s+(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", "relative_day"),
        (r"\bby\s+(next\s+week|this\s+week|eow|end\s+of\s+week)\b", "relative_week"),
        (r"\bby\s+(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b", "date"),
        (r"\bdue\s+(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", "relative_day"),
        (r"\bin\s+(\d+)\s+(days?|hours?|weeks?)\b", "duration"),
    ]

    def __init__(self, confidence_threshold: float = 0.8):
        """Initialize NLP parser.

        Args:
            confidence_threshold: Minimum confidence for automatic processing
        """
        self.confidence_threshold = confidence_threshold
        self._compiled_patterns: dict[Intent, list[tuple[re.Pattern, float]]] = {}

        # Pre-compile patterns
        for intent, patterns in self.INTENT_PATTERNS.items():
            self._compiled_patterns[intent] = [
                (re.compile(p, re.IGNORECASE), w) for p, w in patterns
            ]

    async def parse(self, text: str) -> ParseResult:
        """
        Parse natural language text into structured result.

        Args:
            text: Natural language input

        Returns:
            ParseResult with intent, entities, and confidence
        """
        text = text.strip()
        if not text:
            return ParseResult(
                intent=Intent.UNKNOWN,
                confidence=0.0,
                entities={},
                raw_text=text,
                clarification_needed=["Please provide a task description"],
            )

        # Classify intent
        intent, intent_confidence = self._classify_intent(text)

        # Extract entities based on intent
        entities = await self._extract_entities(text, intent)

        # Calculate overall confidence
        confidence = self._calculate_confidence(intent, intent_confidence, entities, text)

        # Determine if clarification needed
        clarification_needed = self._get_clarification_needs(intent, entities, confidence)

        return ParseResult(
            intent=intent,
            confidence=confidence,
            entities=entities,
            raw_text=text,
            clarification_needed=clarification_needed,
        )

    def _classify_intent(self, text: str) -> tuple[Intent, float]:
        """Classify the intent of the text."""
        scores: dict[Intent, float] = {}

        for intent, patterns in self._compiled_patterns.items():
            score = 0.0
            for pattern, weight in patterns:
                if pattern.search(text):
                    score += weight
            scores[intent] = min(score, 1.0)  # Cap at 1.0

        if not scores or max(scores.values()) == 0:
            return Intent.UNKNOWN, 0.0

        best_intent = max(scores, key=scores.get)
        return best_intent, scores[best_intent]

    async def _extract_entities(
        self, text: str, intent: Intent
    ) -> dict[str, ParsedEntity]:
        """Extract entities from text based on intent."""
        entities: dict[str, ParsedEntity] = {}

        # Always try to extract these
        entities["title"] = self._extract_title(text, intent)
        entities["repository"] = self._extract_repository(text)
        entities["priority"] = self._extract_priority(text)
        entities["tags"] = self._extract_tags(text)
        entities["due_date"] = self._extract_due_date(text)

        # Intent-specific extraction
        if intent == Intent.UPDATE:
            entities["task_id"] = self._extract_task_id(text)
            entities["status"] = self._extract_status(text)

        elif intent == Intent.DELETE:
            entities["task_id"] = self._extract_task_id(text)

        elif intent == Intent.SEARCH:
            entities["query"] = self._extract_search_query(text)

        # Remove None values
        entities = {k: v for k, v in entities.items() if v is not None}

        return entities

    def _extract_title(self, text: str, intent: Intent) -> ParsedEntity | None:
        """Extract task title from text."""
        # Remove common prefixes
        prefixes = [
            r"^create\s+(?:a\s+)?(?:task\s+)?(?:to\s+)?",
            r"^add\s+(?:a\s+)?(?:task\s+)?(?:to\s+)?",
            r"^new\s+(?:task\s+)?(?:to\s+)?",
            r"^make\s+(?:a\s+)?(?:task\s+)?(?:to\s+)?",
            r"^i\s+need\s+(?:to\s+)?",
            r"^please\s+",
        ]

        title = text.lower()
        for prefix in prefixes:
            title = re.sub(prefix, "", title, flags=re.IGNORECASE)

        # Remove entity indicators (use patterns that match hyphens in repo names)
        title = re.sub(r"\s+for\s+[a-zA-Z0-9_-]+\s+repo.*", "", title)
        title = re.sub(r"\s+in\s+[a-zA-Z0-9_-]+\s+repo.*", "", title)
        title = re.sub(r"\s+repo[:\s]+[a-zA-Z0-9_-]+.*", "", title)
        title = re.sub(r"\s+priority[:\s]+\w+.*", "", title)
        title = re.sub(r"\s+by\s+(tomorrow|today|next week).*", "", title)
        title = re.sub(r"#\w+", "", title)
        title = re.sub(r"\s+", " ", title).strip()

        if not title or len(title) < 3:
            return None

        # Capitalize first letter
        title = title[0].upper() + title[1:] if len(title) > 1 else title.upper()

        return ParsedEntity(
            name="title",
            value=title,
            confidence=0.7 if len(title) > 10 else 0.5,
            source_text=text,
        )

    def _extract_repository(self, text: str) -> ParsedEntity | None:
        """Extract repository name from text."""
        for pattern in self.REPO_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                repo = match.group(1).lower()
                return ParsedEntity(
                    name="repository",
                    value=repo,
                    confidence=0.9,
                    source_text=match.group(0),
                )
        return None

    def _extract_priority(self, text: str) -> ParsedEntity | None:
        """Extract priority from text.

        Checks multi-word phrases first to avoid false matches
        (e.g., "low priority" should match LOW, not HIGH from "priority").
        """
        text_lower = text.lower()

        # Build a list of all (priority, keyword) pairs sorted by keyword length (longest first)
        all_keywords: list[tuple[Priority, str]] = []
        for priority, keywords in self.PRIORITY_KEYWORDS.items():
            for keyword in keywords:
                all_keywords.append((priority, keyword))

        # Sort by keyword length descending (longest first)
        all_keywords.sort(key=lambda x: len(x[1]), reverse=True)

        for priority, keyword in all_keywords:
            if keyword in text_lower:
                return ParsedEntity(
                    name="priority",
                    value=priority.value,
                    confidence=0.85,
                    source_text=keyword,
                )
        return None

    def _extract_tags(self, text: str) -> ParsedEntity | None:
        """Extract tags from text."""
        tags = []

        # Hashtags
        for match in re.finditer(r"#(\w+)", text):
            tags.append(match.group(1).lower())

        # Explicit tags
        for pattern in self.TAG_PATTERNS[1:]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                tag_list = [t.strip().lower() for t in match.group(1).split(",")]
                tags.extend(tag_list)
                break

        if not tags:
            return None

        return ParsedEntity(
            name="tags",
            value=list(set(tags)),  # Remove duplicates
            confidence=0.9,
            source_text=text,
        )

    def _extract_due_date(self, text: str) -> ParsedEntity | None:
        """Extract due date from text."""
        text_lower = text.lower()

        # Relative days
        days_map = {
            "today": 0,
            "tomorrow": 1,
            "monday": self._days_until_weekday(0),
            "tuesday": self._days_until_weekday(1),
            "wednesday": self._days_until_weekday(2),
            "thursday": self._days_until_weekday(3),
            "friday": self._days_until_weekday(4),
            "saturday": self._days_until_weekday(5),
            "sunday": self._days_until_weekday(6),
        }

        for pattern, pattern_type in self.DUE_DATE_PATTERNS:
            match = re.search(pattern, text_lower)
            if match:
                if pattern_type == "relative_day":
                    day_name = match.group(1)
                    if day_name in days_map:
                        due_date = datetime.now() + timedelta(days=days_map[day_name])
                        return ParsedEntity(
                            name="due_date",
                            value=due_date.strftime("%Y-%m-%d"),
                            confidence=0.9,
                            source_text=match.group(0),
                        )
                elif pattern_type == "relative_week":
                    # End of week
                    days_ahead = 4 - datetime.now().weekday()  # Friday
                    if days_ahead <= 0:
                        days_ahead += 7
                    due_date = datetime.now() + timedelta(days=days_ahead)
                    return ParsedEntity(
                        name="due_date",
                        value=due_date.strftime("%Y-%m-%d"),
                        confidence=0.8,
                        source_text=match.group(0),
                    )
                elif pattern_type == "duration":
                    amount = int(match.group(1))
                    unit = match.group(2)
                    if "day" in unit:
                        due_date = datetime.now() + timedelta(days=amount)
                    elif "week" in unit:
                        due_date = datetime.now() + timedelta(weeks=amount)
                    elif "hour" in unit:
                        due_date = datetime.now() + timedelta(hours=amount)
                    return ParsedEntity(
                        name="due_date",
                        value=due_date.strftime("%Y-%m-%d"),
                        confidence=0.85,
                        source_text=match.group(0),
                    )

        return None

    def _days_until_weekday(self, target_weekday: int) -> int:
        """Calculate days until next occurrence of weekday."""
        today = datetime.now().weekday()
        days = target_weekday - today
        if days <= 0:
            days += 7
        return days

    def _extract_task_id(self, text: str) -> ParsedEntity | None:
        """Extract task ID from text."""
        # Look for task #123 or task 123 patterns
        match = re.search(r"task\s+#?(\d+)", text, re.IGNORECASE)
        if match:
            return ParsedEntity(
                name="task_id",
                value=int(match.group(1)),
                confidence=0.95,
                source_text=match.group(0),
            )

        # Just a number
        match = re.search(r"\b(\d+)\b", text)
        if match:
            return ParsedEntity(
                name="task_id",
                value=int(match.group(1)),
                confidence=0.5,
                source_text=match.group(0),
            )

        return None

    def _extract_status(self, text: str) -> ParsedEntity | None:
        """Extract status from text."""
        status_keywords = {
            "in_progress": ["in progress", "working on", "started"],
            "completed": ["complete", "done", "finished", "resolved"],
            "blocked": ["blocked", "waiting", "stuck"],
            "cancelled": ["cancel", "abandoned", "dropped"],
        }

        text_lower = text.lower()
        for status, keywords in status_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return ParsedEntity(
                        name="status",
                        value=status,
                        confidence=0.85,
                        source_text=keyword,
                    )

        return None

    def _extract_search_query(self, text: str) -> ParsedEntity | None:
        """Extract search query from text."""
        # Remove search-specific words
        query = re.sub(
            r"^(search|find|look for|query)\s+(for\s+)?",
            "",
            text,
            flags=re.IGNORECASE,
        )
        query = re.sub(r"\s+(containing|with|about)\s+", " ", query)
        query = query.strip()

        if not query or len(query) < 2:
            return None

        return ParsedEntity(
            name="query",
            value=query,
            confidence=0.8,
            source_text=text,
        )

    def _calculate_confidence(
        self,
        intent: Intent,
        intent_confidence: float,
        entities: dict[str, ParsedEntity],
        raw_text: str = "",
    ) -> float:
        """Calculate overall confidence score."""
        if intent == Intent.UNKNOWN:
            return 0.0

        # Penalize very short inputs (ambiguous by nature)
        word_count = len(raw_text.split())
        if word_count <= 1:
            return min(intent_confidence * 0.3, 0.4)  # Max 0.4 for single-word inputs
        elif word_count <= 2:
            base_penalty = 0.7  # Reduce confidence for 2-word inputs
        else:
            base_penalty = 1.0

        # Base confidence from intent
        confidence = intent_confidence * 0.4 * base_penalty

        # Add entity confidence
        if entities:
            entity_confidences = [e.confidence for e in entities.values()]
            avg_entity_confidence = sum(entity_confidences) / len(entity_confidences)
            confidence += avg_entity_confidence * 0.4 * base_penalty

        # Check for required entities based on intent
        required_entities = {
            Intent.CREATE: ["title"],
            Intent.UPDATE: ["task_id"],
            Intent.DELETE: ["task_id"],
            Intent.SEARCH: ["query"],
        }

        if intent in required_entities:
            has_required = all(e in entities for e in required_entities[intent])
            confidence += 0.2 if has_required else 0.0
        else:
            confidence += 0.1

        return min(confidence, 1.0)

    def _get_clarification_needs(
        self,
        intent: Intent,
        entities: dict[str, ParsedEntity],
        confidence: float,
    ) -> list[str]:
        """Determine what clarifications are needed."""
        needs = []

        if confidence < self.confidence_threshold:
            if intent == Intent.UNKNOWN:
                needs.append("Could you clarify what you'd like to do? (create, list, update, delete, search)")
            elif intent == Intent.CREATE and "title" not in entities:
                needs.append("What should the task title be?")
            elif intent == Intent.UPDATE and "task_id" not in entities:
                needs.append("Which task would you like to update? (provide task ID)")
            elif intent == Intent.DELETE and "task_id" not in entities:
                needs.append("Which task would you like to delete? (provide task ID)")
            elif intent == Intent.SEARCH and "query" not in entities:
                needs.append("What would you like to search for?")

        return needs

    def get_clarification_prompt(self, result: ParseResult) -> str:
        """Generate a clarification prompt for ambiguous input."""
        if not result.clarification_needed:
            return ""

        if len(result.clarification_needed) == 1:
            return f"I need a bit more information. {result.clarification_needed[0]}"

        prompt = "I need clarification on a few things:\n"
        for i, need in enumerate(result.clarification_needed, 1):
            prompt += f"  {i}. {need}\n"
        return prompt


# Convenience function
async def parse_task(text: str) -> ParseResult:
    """Parse natural language task description.

    Args:
        text: Natural language input

    Returns:
        ParseResult with intent and entities
    """
    parser = NlpParser()
    return await parser.parse(text)
