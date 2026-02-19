"""Tests for Command Palette Module.

Tests cover:
- Command registration and management
- Fuzzy search matching
- Command execution
- History tracking
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from mahavishnu.tui.command_palette import (
    CommandPalette,
    Command,
    CommandCategory,
    CommandMatch,
    FuzzyMatcher,
    create_default_palette,
    get_command_palette,
)


class TestCommand:
    """Test Command dataclass."""

    def test_minimal_command(self) -> None:
        """Test minimal command creation."""
        cmd = Command(
            id="test.cmd",
            name="Test Command",
            category=CommandCategory.TASK,
        )
        assert cmd.id == "test.cmd"
        assert cmd.name == "Test Command"
        assert cmd.category == CommandCategory.TASK
        assert cmd.description == ""
        assert cmd.shortcut == ""
        assert cmd.keywords == []
        assert cmd.action is None
        assert cmd.enabled is True

    def test_full_command(self) -> None:
        """Test command with all fields."""
        action = lambda: "result"
        cmd = Command(
            id="test.cmd",
            name="Test Command",
            category=CommandCategory.SEARCH,
            description="A test command",
            shortcut="tc",
            keywords=["test", "command"],
            action=action,
            enabled=False,
            priority=10,
        )
        assert cmd.description == "A test command"
        assert cmd.shortcut == "tc"
        assert cmd.keywords == ["test", "command"]
        assert cmd.action is action
        assert cmd.enabled is False
        assert cmd.priority == 10

    def test_command_hash(self) -> None:
        """Test command hashing."""
        cmd1 = Command(id="test", name="Test", category=CommandCategory.TASK)
        cmd2 = Command(id="test", name="Different", category=CommandCategory.SEARCH)
        cmd3 = Command(id="other", name="Test", category=CommandCategory.TASK)

        assert hash(cmd1) == hash(cmd2)  # Same ID
        assert hash(cmd1) != hash(cmd3)  # Different ID

    def test_command_equality(self) -> None:
        """Test command equality."""
        cmd1 = Command(id="test", name="Test", category=CommandCategory.TASK)
        cmd2 = Command(id="test", name="Different", category=CommandCategory.SEARCH)
        cmd3 = Command(id="other", name="Test", category=CommandCategory.TASK)

        assert cmd1 == cmd2  # Same ID
        assert cmd1 != cmd3  # Different ID
        assert cmd1 != "not a command"  # Different type


class TestCommandMatch:
    """Test CommandMatch model."""

    def test_minimal_match(self) -> None:
        """Test minimal match creation."""
        cmd = Command(id="test", name="Test", category=CommandCategory.TASK)
        match = CommandMatch(command=cmd, score=0.5)
        assert match.command == cmd
        assert match.score == 0.5
        assert match.match_type == "fuzzy"
        assert match.matched_text == ""

    def test_full_match(self) -> None:
        """Test match with all fields."""
        cmd = Command(id="test", name="Test", category=CommandCategory.TASK)
        match = CommandMatch(
            command=cmd,
            score=0.95,
            match_type="exact",
            matched_text="Test",
        )
        assert match.score == 0.95
        assert match.match_type == "exact"
        assert match.matched_text == "Test"

    def test_score_validation(self) -> None:
        """Test score validation."""
        from pydantic import ValidationError

        cmd = Command(id="test", name="Test", category=CommandCategory.TASK)

        # Valid scores
        CommandMatch(command=cmd, score=0.0)
        CommandMatch(command=cmd, score=1.0)
        CommandMatch(command=cmd, score=0.5)

        # Invalid scores
        with pytest.raises(ValidationError):
            CommandMatch(command=cmd, score=-0.1)

        with pytest.raises(ValidationError):
            CommandMatch(command=cmd, score=1.1)


class TestFuzzyMatcher:
    """Test fuzzy matching algorithm."""

    def test_exact_match(self) -> None:
        """Test exact match returns 1.0."""
        score = FuzzyMatcher.score("test", "test")
        assert score == 1.0

    def test_case_insensitive(self) -> None:
        """Test case insensitive matching."""
        score = FuzzyMatcher.score("TEST", "test")
        assert score == 1.0

        score = FuzzyMatcher.score("Test", "TEST")
        assert score == 1.0

    def test_prefix_match(self) -> None:
        """Test prefix match."""
        score = FuzzyMatcher.score("test", "testing")
        assert score == 0.9

    def test_contains_match(self) -> None:
        """Test contains match."""
        score = FuzzyMatcher.score("test", "my test case")
        assert score == 0.8

    def test_word_prefix_match(self) -> None:
        """Test word prefix match (query starts a word in target)."""
        # "case" starts the second word in "test case"
        score = FuzzyMatcher.score("case", "test case")
        # Should be contains match (0.8) since "case" is in "test case"
        assert score >= 0.7

    def test_fuzzy_match(self) -> None:
        """Test fuzzy character match."""
        score = FuzzyMatcher.score("tst", "test")
        assert score > 0.0
        assert score < 0.7

    def test_no_match(self) -> None:
        """Test no match returns 0.0."""
        score = FuzzyMatcher.score("xyz", "test")
        assert score == 0.0

    def test_empty_query(self) -> None:
        """Test empty query returns 0.0."""
        score = FuzzyMatcher.score("", "test")
        assert score == 0.0

    def test_empty_target(self) -> None:
        """Test empty target returns 0.0."""
        score = FuzzyMatcher.score("test", "")
        assert score == 0.0

    def test_partial_fuzzy_match(self) -> None:
        """Test partial fuzzy match."""
        # Query chars must appear in order
        score = FuzzyMatcher.score("tce", "test case")
        # 't', 'c', 'e' appear in order
        assert score > 0.0


class TestCommandPalette:
    """Test command palette functionality."""

    @pytest.fixture
    def palette(self) -> CommandPalette:
        """Create empty palette."""
        return CommandPalette()

    @pytest.fixture
    def sample_command(self) -> Command:
        """Create sample command."""
        return Command(
            id="test.cmd",
            name="Test Command",
            category=CommandCategory.TASK,
            description="A test command",
            shortcut="tc",
            keywords=["test", "sample"],
        )

    def test_register_command(self, palette: CommandPalette, sample_command: Command) -> None:
        """Test registering a command."""
        palette.register(sample_command)
        assert palette.get("test.cmd") == sample_command

    def test_unregister_command(self, palette: CommandPalette, sample_command: Command) -> None:
        """Test unregistering a command."""
        palette.register(sample_command)
        result = palette.unregister("test.cmd")
        assert result is True
        assert palette.get("test.cmd") is None

    def test_unregister_nonexistent(self, palette: CommandPalette) -> None:
        """Test unregistering nonexistent command."""
        result = palette.unregister("nonexistent")
        assert result is False

    def test_list_all(self, palette: CommandPalette) -> None:
        """Test listing all commands."""
        cmd1 = Command(id="cmd1", name="Command 1", category=CommandCategory.TASK)
        cmd2 = Command(id="cmd2", name="Command 2", category=CommandCategory.SEARCH)

        palette.register(cmd1)
        palette.register(cmd2)

        commands = palette.list_all()
        assert len(commands) == 2

    def test_list_by_category(self, palette: CommandPalette) -> None:
        """Test listing by category."""
        cmd1 = Command(id="cmd1", name="Command 1", category=CommandCategory.TASK)
        cmd2 = Command(id="cmd2", name="Command 2", category=CommandCategory.SEARCH)
        cmd3 = Command(id="cmd3", name="Command 3", category=CommandCategory.TASK)

        palette.register(cmd1)
        palette.register(cmd2)
        palette.register(cmd3)

        task_commands = palette.list_by_category(CommandCategory.TASK)
        assert len(task_commands) == 2

        search_commands = palette.list_by_category(CommandCategory.SEARCH)
        assert len(search_commands) == 1

    def test_search_empty_query(self, palette: CommandPalette) -> None:
        """Test search with empty query."""
        cmd = Command(
            id="cmd",
            name="Test",
            category=CommandCategory.TASK,
            priority=5,
        )
        palette.register(cmd)

        results = palette.search("")
        assert len(results) == 1
        assert results[0].command == cmd

    def test_search_by_name(self, palette: CommandPalette) -> None:
        """Test search by name."""
        cmd = Command(
            id="cmd",
            name="Create Task",
            category=CommandCategory.TASK,
        )
        palette.register(cmd)

        results = palette.search("create")
        assert len(results) == 1
        assert results[0].command == cmd

    def test_search_by_shortcut(self, palette: CommandPalette) -> None:
        """Test search by shortcut."""
        cmd = Command(
            id="cmd",
            name="Create Task",
            category=CommandCategory.TASK,
            shortcut="ct",
        )
        palette.register(cmd)

        results = palette.search("ct")
        assert len(results) >= 1
        # Find the command in results
        found = any(r.command.id == "cmd" for r in results)
        assert found

    def test_search_by_keyword(self, palette: CommandPalette) -> None:
        """Test search by keyword."""
        cmd = Command(
            id="cmd",
            name="Create Task",
            category=CommandCategory.TASK,
            keywords=["new", "add"],
        )
        palette.register(cmd)

        results = palette.search("new")
        assert len(results) >= 1
        found = any(r.command.id == "cmd" for r in results)
        assert found

    def test_search_disabled_command(self, palette: CommandPalette) -> None:
        """Test search excludes disabled commands."""
        cmd = Command(
            id="cmd",
            name="Test",
            category=CommandCategory.TASK,
            enabled=False,
        )
        palette.register(cmd)

        results = palette.search("test")
        assert len(results) == 0

    def test_search_sorted_by_score(self, palette: CommandPalette) -> None:
        """Test search results sorted by score."""
        cmd1 = Command(
            id="cmd1",
            name="Test Command",
            category=CommandCategory.TASK,
            priority=1,
        )
        cmd2 = Command(
            id="cmd2",
            name="Testing",
            category=CommandCategory.TASK,
            priority=2,
        )

        palette.register(cmd1)
        palette.register(cmd2)

        results = palette.search("test")
        # Both should match, exact match should be higher
        assert len(results) == 2
        # Scores should be descending
        if len(results) > 1:
            assert results[0].score >= results[1].score

    @pytest.mark.asyncio
    async def test_execute_command(self, palette: CommandPalette) -> None:
        """Test executing a command."""
        executed = []

        def action():
            executed.append("done")
            return "result"

        cmd = Command(
            id="cmd",
            name="Test",
            category=CommandCategory.TASK,
            action=action,
        )
        palette.register(cmd)

        result = await palette.execute("cmd")

        assert executed == ["done"]
        assert result == "result"

    @pytest.mark.asyncio
    async def test_execute_async_command(self, palette: CommandPalette) -> None:
        """Test executing an async command."""

        async def async_action():
            return "async_result"

        cmd = Command(
            id="cmd",
            name="Test",
            category=CommandCategory.TASK,
            action=async_action,
        )
        palette.register(cmd)

        result = await palette.execute("cmd")
        assert result == "async_result"

    @pytest.mark.asyncio
    async def test_execute_nonexistent(self, palette: CommandPalette) -> None:
        """Test executing nonexistent command."""
        with pytest.raises(ValueError) as exc_info:
            await palette.execute("nonexistent")
        assert "not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_no_action(self, palette: CommandPalette) -> None:
        """Test executing command without action."""
        cmd = Command(
            id="cmd",
            name="Test",
            category=CommandCategory.TASK,
        )
        palette.register(cmd)

        with pytest.raises(ValueError) as exc_info:
            await palette.execute("cmd")
        assert "no action" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_history(self, palette: CommandPalette) -> None:
        """Test command history."""
        cmd = Command(
            id="cmd",
            name="Test",
            category=CommandCategory.TASK,
            action=lambda: None,
        )
        palette.register(cmd)

        await palette.execute("cmd")
        await palette.execute("cmd")

        history = palette.get_history()
        assert len(history) == 2
        assert history[0] == "cmd"

    def test_clear_history(self, palette: CommandPalette) -> None:
        """Test clearing history."""
        palette._history = ["cmd1", "cmd2", "cmd3"]
        palette.clear_history()
        assert palette._history == []


class TestDefaultPalette:
    """Test default palette creation."""

    def test_create_default_palette(self) -> None:
        """Test creating default palette."""
        palette = create_default_palette()
        commands = palette.list_all()

        # Should have multiple default commands
        assert len(commands) > 5

        # Should have task commands
        task_commands = palette.list_by_category(CommandCategory.TASK)
        assert len(task_commands) >= 5

    def test_get_command_palette_singleton(self) -> None:
        """Test singleton pattern."""
        palette1 = get_command_palette()
        palette2 = get_command_palette()
        assert palette1 is palette2

    def test_default_palette_search(self) -> None:
        """Test search in default palette."""
        palette = create_default_palette()

        results = palette.search("create")
        assert len(results) >= 1

        # Find create task command
        found = any("create" in r.command.name.lower() for r in results)
        assert found
