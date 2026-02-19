"""Tests for task model validation and input sanitization.

This module tests the Pydantic models for task operations to ensure:
1. Valid inputs are accepted
2. Invalid inputs are rejected with clear error messages
3. Sanitization removes dangerous characters
4. SQL injection attempts are blocked
5. Edge cases are handled correctly
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from mahavishnu.core.task_models import (
    FTSSearchQuery,
    TaskCreateRequest,
    TaskFilter,
    TaskUpdateRequest,
)


class TestTaskCreateRequest:
    """Tests for TaskCreateRequest validation."""

    # Valid inputs
    def test_valid_minimal_request(self):
        """Test that minimal valid request is accepted."""
        request = TaskCreateRequest(
            title="Test task",
            repository="test-repo",
        )
        assert request.title == "Test task"
        assert request.repository == "test-repo"
        assert request.priority == "medium"
        assert request.description is None

    def test_valid_full_request(self):
        """Test that full valid request is accepted."""
        request = TaskCreateRequest(
            title="Fix authentication bug",
            description="Users cannot login after password reset",
            repository="session-buddy",
            priority="high",
            deadline=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            tags=["authentication", "bug", "urgent"],
        )
        assert request.title == "Fix authentication bug"
        assert request.priority == "high"
        assert len(request.tags) == 3

    def test_all_priority_levels(self):
        """Test that all priority levels are accepted."""
        for priority in ["low", "medium", "high", "critical"]:
            request = TaskCreateRequest(
                title="Test",
                repository="test-repo",
                priority=priority,
            )
            assert request.priority == priority

    # Title validation
    def test_empty_title_rejected(self):
        """Test that empty title is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            TaskCreateRequest(title="", repository="test-repo")
        # Pydantic v2 returns "at least 1 character" error for min_length
        assert "1 character" in str(exc_info.value) or "empty" in str(exc_info.value).lower()

    def test_null_byte_in_title_removed(self):
        """Test that null bytes in title are removed."""
        request = TaskCreateRequest(
            title="Test\x00task with null bytes",
            repository="test-repo",
        )
        assert "\x00" not in request.title
        assert request.title == "Testtask with null bytes"

    def test_control_characters_removed(self):
        """Test that control characters are removed from title."""
        request = TaskCreateRequest(
            title="Test\x01\x02\x03task",
            repository="test-repo",
        )
        assert "\x01" not in request.title
        assert "\x02" not in request.title
        assert "\x03" not in request.title

    def test_newline_and_tab_preserved(self):
        """Test that newline and tab are preserved in title."""
        request = TaskCreateRequest(
            title="Line 1\nLine 2\tTabbed",
            repository="test-repo",
        )
        assert "\n" in request.title
        assert "\t" in request.title

    def test_whitespace_stripped(self):
        """Test that leading/trailing whitespace is stripped."""
        request = TaskCreateRequest(
            title="  Test task  ",
            repository="test-repo",
        )
        assert request.title == "Test task"

    def test_title_too_long_rejected(self):
        """Test that title over 200 characters is rejected."""
        long_title = "a" * 201
        with pytest.raises(ValidationError) as exc_info:
            TaskCreateRequest(title=long_title, repository="test-repo")
        assert "200" in str(exc_info.value)

    # Repository validation
    def test_valid_repository_names(self):
        """Test that valid repository names are accepted."""
        valid_names = [
            "test-repo",
            "test_repo",
            "TestRepo",
            "test123",
            "a",
            "test-repo-123",
        ]
        for name in valid_names:
            request = TaskCreateRequest(title="Test", repository=name)
            assert request.repository == name

    def test_repository_path_traversal_rejected(self):
        """Test that path traversal in repository name is rejected."""
        invalid_names = [
            "../../../etc",
            "test/../other",
        ]
        for name in invalid_names:
            with pytest.raises(ValidationError) as exc_info:
                TaskCreateRequest(title="Test", repository=name)
            assert "invalid" in str(exc_info.value).lower()

    def test_repository_special_chars_rejected(self):
        """Test that special characters in repository name are rejected."""
        invalid_names = [
            "test repo",  # space
            "test.repo",  # dot
            "test:repo",  # colon
            "test/repo",  # slash
        ]
        for name in invalid_names:
            with pytest.raises(ValidationError) as exc_info:
                TaskCreateRequest(title="Test", repository=name)
            assert "invalid" in str(exc_info.value).lower()

    # Deadline validation
    def test_valid_future_deadline(self):
        """Test that valid future deadline is accepted."""
        future = datetime.now(timezone.utc) + timedelta(days=7)
        request = TaskCreateRequest(
            title="Test",
            repository="test-repo",
            deadline=future.isoformat(),
        )
        assert request.deadline is not None

    def test_past_deadline_rejected(self):
        """Test that past deadline is rejected."""
        past = datetime.now(timezone.utc) - timedelta(days=1)
        with pytest.raises(ValidationError) as exc_info:
            TaskCreateRequest(
                title="Test",
                repository="test-repo",
                deadline=past.isoformat(),
            )
        assert "future" in str(exc_info.value).lower()


class TestFTSSearchQuery:
    """Tests for FTSSearchQuery validation."""

    def test_valid_query(self):
        """Test that valid query is accepted."""
        query = FTSSearchQuery(query="authentication bug")
        assert query.query == "authentication bug"

    def test_empty_query_rejected(self):
        """Test that empty query is rejected."""
        with pytest.raises(ValidationError):
            FTSSearchQuery(query="")

    def test_null_byte_removed(self):
        """Test that null bytes are removed from query."""
        query = FTSSearchQuery(query="test\x00query")
        assert "\x00" not in query.query

    # SQL injection prevention
    def test_sql_comment_injection_rejected(self):
        """Test that SQL comment injection is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            FTSSearchQuery(query="test -- comment")
        assert "dangerous" in str(exc_info.value).lower()

    def test_sql_statement_separator_rejected(self):
        """Test that SQL statement separator is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            FTSSearchQuery(query="test; DROP TABLE")
        assert "dangerous" in str(exc_info.value).lower()

    def test_whitespace_normalized(self):
        """Test that multiple spaces are normalized to single space."""
        query = FTSSearchQuery(query="test    query   here")
        assert query.query == "test query here"

    def test_tsquery_format(self):
        """Test conversion to PostgreSQL tsquery format."""
        query = FTSSearchQuery(query="authentication bug login")
        tsquery = query.to_tsquery_format()
        assert tsquery == "authentication & bug & login"


class TestTaskUpdateRequest:
    """Tests for TaskUpdateRequest validation."""

    def test_empty_update_accepted(self):
        """Test that empty update is accepted."""
        update = TaskUpdateRequest()
        assert update.title is None
        assert update.description is None

    def test_partial_update(self):
        """Test that partial update is accepted."""
        update = TaskUpdateRequest(priority="high")
        assert update.priority == "high"


class TestTaskFilter:
    """Tests for TaskFilter validation."""

    def test_empty_filter(self):
        """Test that empty filter is accepted."""
        filter_obj = TaskFilter()
        assert filter_obj.status is None

    def test_valid_filter(self):
        """Test that valid filter is accepted."""
        filter_obj = TaskFilter(
            status="in_progress",
            priority="high",
            repository="test-repo",
        )
        assert filter_obj.status == "in_progress"
