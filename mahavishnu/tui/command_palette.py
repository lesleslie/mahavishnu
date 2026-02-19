"""Command Palette for Mahavishnu.

Provides a Ctrl+K fuzzy search interface for commands:
- Fuzzy search across all commands
- Category-based organization
- Keyboard navigation
- Quick actions

Usage:
    from mahavishnu.tui.command_palette import CommandPalette, Command

    palette = CommandPalette()
    palette.register(Command(
        id="task.create",
        name="Create Task",
        category=CommandCategory.TASK,
        shortcut="tc",
        action=lambda: create_task(),
    ))

    # Show palette (in interactive mode)
    await palette.show()
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

from pydantic import BaseModel, Field, ConfigDict

logger = logging.getLogger(__name__)


class CommandCategory(Enum):
    """Categories for organizing commands."""

    TASK = "task"
    REPOSITORY = "repository"
    SEARCH = "search"
    SYSTEM = "system"
    NAVIGATION = "navigation"
    HELP = "help"


@dataclass
class Command:
    """A command in the palette."""

    id: str
    name: str
    category: CommandCategory
    description: str = ""
    shortcut: str = ""
    keywords: list[str] = field(default_factory=list)
    action: Callable[[], Any] | Callable[[], Coroutine[Any, Any, Any]] | None = None
    enabled: bool = True
    priority: int = 0  # Higher = more important

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Command):
            return False
        return self.id == other.id


class CommandMatch(BaseModel):
    """Result of matching a command against a query."""

    model_config = ConfigDict(extra="forbid")

    command: Command
    score: float = Field(ge=0.0, le=1.0)
    match_type: str = "fuzzy"  # exact, prefix, fuzzy, keyword
    matched_text: str = ""


class FuzzyMatcher:
    """Fuzzy string matching for command search."""

    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text for comparison."""
        return text.lower().strip()

    @staticmethod
    def score(query: str, target: str) -> float:
        """Calculate fuzzy match score between query and target.

        Args:
            query: Search query
            target: Target string to match against

        Returns:
            Score between 0.0 and 1.0
        """
        query = FuzzyMatcher.normalize(query)
        target = FuzzyMatcher.normalize(target)

        if not query:
            return 0.0

        if not target:
            return 0.0

        # Exact match
        if query == target:
            return 1.0

        # Prefix match
        if target.startswith(query):
            return 0.9

        # Contains match
        if query in target:
            return 0.8

        # Word match (any word starts with query)
        words = target.split()
        for word in words:
            if word.startswith(query):
                return 0.7

        # Fuzzy match - check if query chars appear in order
        score = FuzzyMatcher._fuzzy_score(query, target)
        return score

    @staticmethod
    def _fuzzy_score(query: str, target: str) -> float:
        """Calculate fuzzy match score based on character sequence.

        Characters must appear in order but can have gaps.
        Bonus for consecutive characters and start of words.
        """
        query_idx = 0
        score = 0.0
        consecutive_bonus = 0.0
        last_match_idx = -2

        for i, char in enumerate(target):
            if query_idx >= len(query):
                break

            if char == query[query_idx]:
                # Base score for match
                score += 1.0

                # Bonus for consecutive matches
                if i == last_match_idx + 1:
                    consecutive_bonus += 0.5
                    score += consecutive_bonus
                else:
                    consecutive_bonus = 0.0

                # Bonus for matching start of word
                if i == 0 or target[i - 1] in " _-":
                    score += 0.5

                last_match_idx = i
                query_idx += 1

        # Penalize if not all query chars matched
        if query_idx < len(query):
            return 0.0

        # Normalize score
        max_possible = len(query) * 2.0  # Max with bonuses
        return min(0.6, score / max_possible)  # Cap at 0.6 for fuzzy


class CommandPalette:
    """Command palette with fuzzy search and keyboard navigation."""

    def __init__(self, min_score: float = 0.3) -> None:
        self._commands: dict[str, Command] = {}
        self._matcher = FuzzyMatcher()
        self._min_score = min_score
        self._history: list[str] = []

    def register(self, command: Command) -> None:
        """Register a command."""
        self._commands[command.id] = command
        logger.debug(f"Registered command: {command.id}")

    def unregister(self, command_id: str) -> bool:
        """Unregister a command.

        Returns:
            True if command was removed, False if not found
        """
        if command_id in self._commands:
            del self._commands[command_id]
            return True
        return False

    def get(self, command_id: str) -> Command | None:
        """Get a command by ID."""
        return self._commands.get(command_id)

    def list_all(self) -> list[Command]:
        """List all registered commands."""
        return list(self._commands.values())

    def list_by_category(self, category: CommandCategory) -> list[Command]:
        """List commands by category."""
        return [cmd for cmd in self._commands.values() if cmd.category == category]

    def search(self, query: str) -> list[CommandMatch]:
        """Search commands with fuzzy matching.

        Args:
            query: Search query

        Returns:
            List of command matches sorted by score
        """
        if not query.strip():
            # Return all enabled commands, sorted by priority
            commands = [
                CommandMatch(
                    command=cmd,
                    score=0.5,
                    match_type="none",
                    matched_text="",
                )
                for cmd in self._commands.values()
                if cmd.enabled
            ]
            return sorted(commands, key=lambda m: (-m.command.priority, m.command.name))

        matches: list[CommandMatch] = []
        query_lower = query.lower()

        for cmd in self._commands.values():
            if not cmd.enabled:
                continue

            best_score = 0.0
            match_type = "fuzzy"
            matched_text = ""

            # Check name
            name_score = self._matcher.score(query, cmd.name)
            if name_score > best_score:
                best_score = name_score
                match_type = "exact" if name_score == 1.0 else "fuzzy"
                matched_text = cmd.name

            # Check shortcut
            if cmd.shortcut:
                shortcut_score = self._matcher.score(query, cmd.shortcut)
                if shortcut_score > best_score:
                    best_score = shortcut_score
                    match_type = "shortcut"
                    matched_text = cmd.shortcut

            # Check keywords
            for keyword in cmd.keywords:
                keyword_score = self._matcher.score(query, keyword)
                if keyword_score > best_score:
                    best_score = keyword_score
                    match_type = "keyword"
                    matched_text = keyword

            # Check description
            if cmd.description:
                desc_score = self._matcher.score(query, cmd.description) * 0.8
                if desc_score > best_score:
                    best_score = desc_score
                    match_type = "description"
                    matched_text = cmd.description

            # Check ID
            id_score = self._matcher.score(query, cmd.id) * 0.7
            if id_score > best_score:
                best_score = id_score
                match_type = "id"
                matched_text = cmd.id

            if best_score >= self._min_score:
                matches.append(
                    CommandMatch(
                        command=cmd,
                        score=best_score,
                        match_type=match_type,
                        matched_text=matched_text,
                    )
                )

        # Sort by score, then priority, then name
        matches.sort(key=lambda m: (-m.score, -m.command.priority, m.command.name))
        return matches

    async def execute(self, command_id: str) -> Any:
        """Execute a command by ID.

        Args:
            command_id: Command ID to execute

        Returns:
            Result of the command action

        Raises:
            ValueError: If command not found or has no action
        """
        command = self._commands.get(command_id)
        if not command:
            raise ValueError(f"Command not found: {command_id}")

        if not command.action:
            raise ValueError(f"Command has no action: {command_id}")

        # Add to history
        self._history.append(command_id)
        if len(self._history) > 100:
            self._history = self._history[-100:]

        logger.info(f"Executing command: {command_id}")

        # Execute action
        result = command.action()
        if asyncio.iscoroutine(result):
            return await result
        return result

    def get_history(self, limit: int = 10) -> list[str]:
        """Get recent command history.

        Args:
            limit: Maximum number of history items

        Returns:
            List of command IDs in reverse chronological order
        """
        return list(reversed(self._history[-limit:]))

    def clear_history(self) -> None:
        """Clear command history."""
        self._history.clear()


def create_default_palette() -> CommandPalette:
    """Create a command palette with default Mahavishnu commands."""
    palette = CommandPalette()

    # Task commands
    palette.register(
        Command(
            id="task.create",
            name="Create Task",
            category=CommandCategory.TASK,
            description="Create a new task",
            shortcut="tc",
            keywords=["new", "add", "task", "create"],
            priority=10,
        )
    )

    palette.register(
        Command(
            id="task.list",
            name="List Tasks",
            category=CommandCategory.TASK,
            description="List all tasks with filters",
            shortcut="tl",
            keywords=["show", "view", "list", "tasks"],
            priority=9,
        )
    )

    palette.register(
        Command(
            id="task.update",
            name="Update Task",
            category=CommandCategory.TASK,
            description="Update an existing task",
            shortcut="tu",
            keywords=["edit", "modify", "update", "task"],
            priority=8,
        )
    )

    palette.register(
        Command(
            id="task.delete",
            name="Delete Task",
            category=CommandCategory.TASK,
            description="Delete a task",
            shortcut="td",
            keywords=["remove", "delete", "task"],
            priority=7,
        )
    )

    palette.register(
        Command(
            id="task.status",
            name="Update Task Status",
            category=CommandCategory.TASK,
            description="Quick status update for a task",
            shortcut="ts",
            keywords=["status", "complete", "progress", "task"],
            priority=8,
        )
    )

    # Repository commands
    palette.register(
        Command(
            id="repo.list",
            name="List Repositories",
            category=CommandCategory.REPOSITORY,
            description="List all configured repositories",
            shortcut="rl",
            keywords=["repos", "show", "list", "repositories"],
            priority=8,
        )
    )

    palette.register(
        Command(
            id="repo.sweep",
            name="Sweep Repositories",
            category=CommandCategory.REPOSITORY,
            description="Execute workflow sweep across repositories",
            shortcut="rs",
            keywords=["sweep", "workflow", "repositories"],
            priority=6,
        )
    )

    # Search commands
    palette.register(
        Command(
            id="search.tasks",
            name="Search Tasks",
            category=CommandCategory.SEARCH,
            description="Semantic search across tasks",
            shortcut="st",
            keywords=["find", "search", "tasks", "semantic"],
            priority=9,
        )
    )

    palette.register(
        Command(
            id="search.similar",
            name="Find Similar Tasks",
            category=CommandCategory.SEARCH,
            description="Find tasks similar to a given task",
            shortcut="ss",
            keywords=["similar", "related", "find", "tasks"],
            priority=7,
        )
    )

    # System commands
    palette.register(
        Command(
            id="system.health",
            name="System Health Check",
            category=CommandCategory.SYSTEM,
            description="Check system health and status",
            shortcut="sh",
            keywords=["health", "status", "check", "system"],
            priority=5,
        )
    )

    palette.register(
        Command(
            id="system.config",
            name="View Configuration",
            category=CommandCategory.SYSTEM,
            description="View current configuration",
            shortcut="sc",
            keywords=["config", "settings", "view"],
            priority=4,
        )
    )

    # Help commands
    palette.register(
        Command(
            id="help.commands",
            name="Help: Commands",
            category=CommandCategory.HELP,
            description="Show all available commands",
            shortcut="hc",
            keywords=["help", "commands", "list", "usage"],
            priority=3,
        )
    )

    palette.register(
        Command(
            id="help.shortcuts",
            name="Help: Keyboard Shortcuts",
            category=CommandCategory.HELP,
            description="Show keyboard shortcuts reference",
            shortcut="hs",
            keywords=["help", "shortcuts", "keyboard", "keys"],
            priority=2,
        )
    )

    return palette


# Singleton instance
_default_palette: CommandPalette | None = None


def get_command_palette() -> CommandPalette:
    """Get the default command palette instance."""
    global _default_palette
    if _default_palette is None:
        _default_palette = create_default_palette()
    return _default_palette
