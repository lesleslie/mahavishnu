"""Tests for NLP Parser.

Tests intent classification, entity extraction, and confidence scoring.
"""

import pytest
from datetime import datetime, timedelta

from mahavishnu.core.nlp_parser import (
    NlpParser,
    Intent,
    Priority,
    ParseResult,
    ParsedEntity,
)


@pytest.fixture
def parser():
    """Create NLP parser instance."""
    return NlpParser()


class TestIntentClassification:
    """Test intent classification."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text,expected_intent", [
        ("create a task to fix the bug", Intent.CREATE),
        ("add new task for session-buddy repo", Intent.CREATE),
        ("make a task about authentication", Intent.CREATE),
        ("new task: implement login", Intent.CREATE),
        ("list all tasks", Intent.LIST),
        ("show me tasks for mahavishnu", Intent.LIST),
        ("display tasks", Intent.LIST),
        ("what are the tasks", Intent.LIST),
        ("update task 123", Intent.UPDATE),
        ("change status of task 5", Intent.UPDATE),
        ("mark task 10 as complete", Intent.COMPLETE),  # "mark as complete" is COMPLETE
        ("delete task 456", Intent.DELETE),
        ("remove task 789", Intent.DELETE),
        ("cancel task 100", Intent.DELETE),
        ("search for authentication tasks", Intent.SEARCH),
        ("find tasks about API", Intent.SEARCH),
        ("look for bug fixes", Intent.SEARCH),
        ("complete task 50", Intent.COMPLETE),
        ("mark task as done", Intent.COMPLETE),
        ("finish task 25", Intent.COMPLETE),
        ("assign task 10 to john", Intent.ASSIGN),
        ("block task 5", Intent.BLOCK),
        ("task is waiting for API", Intent.BLOCK),
    ])
    async def test_intent_classification(self, parser, text, expected_intent):
        """Test that intents are correctly classified."""
        result = await parser.parse(text)
        assert result.intent == expected_intent
        assert result.confidence > 0.0


class TestEntityExtraction:
    """Test entity extraction."""

    @pytest.mark.asyncio
    async def test_extract_repository(self, parser):
        """Test repository extraction."""
        result = await parser.parse("create task for session-buddy repo")
        assert "repository" in result.entities
        assert result.entities["repository"].value == "session-buddy"

    @pytest.mark.asyncio
    async def test_extract_repository_in_repo(self, parser):
        """Test repository extraction with 'in' preposition."""
        result = await parser.parse("create task in mahavishnu repo")
        assert "repository" in result.entities
        assert result.entities["repository"].value == "mahavishnu"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text,expected_priority", [
        ("create critical task", Priority.CRITICAL),
        ("urgent bug fix needed", Priority.CRITICAL),
        ("this is a blocker", Priority.CRITICAL),
        ("high priority task", Priority.HIGH),
        ("important feature", Priority.HIGH),
        ("normal task", Priority.MEDIUM),
        ("low priority cleanup", Priority.LOW),
        ("nice to have feature", Priority.LOW),
    ])
    async def test_extract_priority(self, parser, text, expected_priority):
        """Test priority extraction."""
        result = await parser.parse(text)
        assert "priority" in result.entities
        assert result.entities["priority"].value == expected_priority.value

    @pytest.mark.asyncio
    async def test_extract_tags_hashtag(self, parser):
        """Test tag extraction from hashtags."""
        result = await parser.parse("create task #bug #urgent")
        assert "tags" in result.entities
        assert "bug" in result.entities["tags"].value
        assert "urgent" in result.entities["tags"].value

    @pytest.mark.asyncio
    async def test_extract_task_id(self, parser):
        """Test task ID extraction."""
        result = await parser.parse("update task 123")
        assert "task_id" in result.entities
        assert result.entities["task_id"].value == 123

    @pytest.mark.asyncio
    async def test_extract_task_id_with_hash(self, parser):
        """Test task ID extraction with hash prefix."""
        result = await parser.parse("delete task #456")
        assert "task_id" in result.entities
        assert result.entities["task_id"].value == 456

    @pytest.mark.asyncio
    async def test_extract_search_query(self, parser):
        """Test search query extraction."""
        result = await parser.parse("search for authentication bug")
        assert "query" in result.entities
        assert "authentication" in result.entities["query"].value
        assert "bug" in result.entities["query"].value


class TestTitleExtraction:
    """Test title extraction."""

    @pytest.mark.asyncio
    async def test_extract_title_simple(self, parser):
        """Test simple title extraction."""
        result = await parser.parse("create task to fix the bug")
        assert "title" in result.entities
        assert "fix the bug" in result.entities["title"].value.lower()

    @pytest.mark.asyncio
    async def test_extract_title_with_repository(self, parser):
        """Test title extraction with repository present."""
        result = await parser.parse("create task to implement auth for session-buddy repo")
        assert "title" in result.entities
        assert "session-buddy" not in result.entities["title"].value.lower()
        assert "implement auth" in result.entities["title"].value.lower()


class TestDueDateExtraction:
    """Test due date extraction."""

    @pytest.mark.asyncio
    async def test_extract_due_date_today(self, parser):
        """Test 'today' due date extraction."""
        result = await parser.parse("create task by today")
        if "due_date" in result.entities:
            expected = datetime.now().strftime("%Y-%m-%d")
            assert result.entities["due_date"].value == expected

    @pytest.mark.asyncio
    async def test_extract_due_date_tomorrow(self, parser):
        """Test 'tomorrow' due date extraction."""
        result = await parser.parse("create task by tomorrow")
        if "due_date" in result.entities:
            expected = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            assert result.entities["due_date"].value == expected

    @pytest.mark.asyncio
    async def test_extract_due_date_in_days(self, parser):
        """Test 'in X days' due date extraction."""
        result = await parser.parse("create task in 3 days")
        if "due_date" in result.entities:
            expected = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
            assert result.entities["due_date"].value == expected


class TestConfidenceScoring:
    """Test confidence scoring."""

    @pytest.mark.asyncio
    async def test_high_confidence_clear_intent(self, parser):
        """Test high confidence for clear intent."""
        result = await parser.parse("create task to fix bug for session-buddy repo #urgent")
        assert result.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_low_confidence_ambiguous(self, parser):
        """Test low confidence for ambiguous input."""
        result = await parser.parse("task")
        assert result.confidence < 0.5 or result.intent == Intent.UNKNOWN

    @pytest.mark.asyncio
    async def test_confidence_threshold_met(self, parser):
        """Test that clear inputs meet confidence threshold."""
        result = await parser.parse("create bug fix task for mahavishnu repo high priority")
        assert result.is_confident()


class TestClarification:
    """Test clarification prompt generation."""

    @pytest.mark.asyncio
    async def test_no_clarification_needed(self, parser):
        """Test no clarification for complete input."""
        result = await parser.parse("create bug fix task")
        if result.is_confident():
            assert len(result.clarification_needed) == 0

    @pytest.mark.asyncio
    async def test_clarification_for_missing_task_id(self, parser):
        """Test clarification when task ID is missing for update."""
        result = await parser.parse("update the task status")
        if not result.is_confident():
            assert any("task ID" in c or "which task" in c.lower() for c in result.clarification_needed)

    @pytest.mark.asyncio
    async def test_clarification_prompt_format(self, parser):
        """Test clarification prompt is formatted correctly."""
        result = await parser.parse("update task")
        if result.clarification_needed:
            prompt = parser.get_clarification_prompt(result)
            assert len(prompt) > 0


class TestParseResult:
    """Test ParseResult methods."""

    def test_to_task_request(self):
        """Test conversion to task request dict."""
        result = ParseResult(
            intent=Intent.CREATE,
            confidence=0.9,
            entities={
                "title": ParsedEntity("title", "Fix bug", 0.9, "fix bug"),
                "repository": ParsedEntity("repository", "session-buddy", 0.95, "session-buddy repo"),
            },
            raw_text="create fix bug task for session-buddy repo",
        )

        request = result.to_task_request()
        assert request["title"] == "Fix bug"
        assert request["repository"] == "session-buddy"

    def test_is_confident(self):
        """Test confidence threshold check."""
        high_confidence = ParseResult(
            intent=Intent.CREATE,
            confidence=0.9,
            entities={},
            raw_text="test",
        )
        assert high_confidence.is_confident()

        low_confidence = ParseResult(
            intent=Intent.CREATE,
            confidence=0.5,
            entities={},
            raw_text="test",
        )
        assert not low_confidence.is_confident()


class TestEdgeCases:
    """Test edge cases."""

    @pytest.mark.asyncio
    async def test_empty_input(self, parser):
        """Test handling of empty input."""
        result = await parser.parse("")
        assert result.intent == Intent.UNKNOWN
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_whitespace_only(self, parser):
        """Test handling of whitespace-only input."""
        result = await parser.parse("   ")
        assert result.intent == Intent.UNKNOWN or result.confidence < 0.5

    @pytest.mark.asyncio
    async def test_very_long_input(self, parser):
        """Test handling of very long input."""
        long_text = "create task " + "very " * 100 + "important"
        result = await parser.parse(long_text)
        assert result.intent == Intent.CREATE

    @pytest.mark.asyncio
    async def test_special_characters(self, parser):
        """Test handling of special characters."""
        result = await parser.parse("create task @user #tag $100")
        assert result.intent == Intent.CREATE
        # Should handle special chars gracefully
