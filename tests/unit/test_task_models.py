"""Tests for core/task_models.py — Pydantic validation and sanitization."""

from pydantic import ValidationError
import pytest

from mahavishnu.core.task_models import (
    FTSSearchQuery,
    TaskCreateRequest,
    TaskFilter,
    TaskUpdateRequest,
)

# ---------------------------------------------------------------------------
# TaskCreateRequest
# ---------------------------------------------------------------------------


class TestTaskCreateRequestBasic:
    """Basic creation and field validation."""

    def test_minimal_valid(self):
        req = TaskCreateRequest(title="Fix bug", repository="my-repo")
        assert req.title == "Fix bug"
        assert req.repository == "my-repo"
        assert req.priority == "medium"
        assert req.description is None
        assert req.deadline is None
        assert req.tags is None

    def test_all_fields(self):
        req = TaskCreateRequest(
            title="Fix bug",
            description="A description",
            repository="my_repo-123",
            priority="high",
            tags=["backend", "urgent"],
            metadata={"env": "prod"},
        )
        assert req.title == "Fix bug"
        assert req.repository == "my_repo-123"
        assert req.priority == "high"
        assert req.tags == ["backend", "urgent"]

    def test_all_priority_values(self):
        for p in ("low", "medium", "high", "critical"):
            req = TaskCreateRequest(title="T", repository="repo", priority=p)
            assert req.priority == p

    def test_invalid_priority(self):
        with pytest.raises(ValidationError, match="priority"):
            TaskCreateRequest(title="T", repository="repo", priority="urgent")


class TestTaskCreateRequestTitle:
    """Title sanitization: null bytes, control chars, length."""

    def test_null_bytes_removed(self):
        req = TaskCreateRequest(title="Hello\x00World", repository="repo")
        assert req.title == "HelloWorld"

    def test_control_chars_removed(self):
        req = TaskCreateRequest(title="A\x01B\x1fC", repository="repo")
        assert req.title == "ABC"

    def test_newline_and_tab_preserved(self):
        req = TaskCreateRequest(title="Line1\nLine2\tTab", repository="repo")
        assert "\n" in req.title
        assert "\t" in req.title

    def test_whitespace_stripped(self):
        req = TaskCreateRequest(title="  hello  ", repository="repo")
        assert req.title == "hello"

    def test_empty_after_sanitization(self):
        with pytest.raises(ValidationError, match="empty"):
            TaskCreateRequest(title="\x00\x01\x02", repository="repo")

    def test_title_too_long(self):
        with pytest.raises(ValidationError):
            TaskCreateRequest(title="A" * 201, repository="repo")


class TestTaskCreateRequestDescription:
    """Description sanitization."""

    def test_null_bytes_removed(self):
        req = TaskCreateRequest(title="T", repository="repo", description="a\x00b")
        assert req.description == "ab"

    def test_empty_after_sanitization_becomes_none(self):
        req = TaskCreateRequest(title="T", repository="repo", description="  \x00  ")
        assert req.description is None

    def test_none_stays_none(self):
        req = TaskCreateRequest(title="T", repository="repo", description=None)
        assert req.description is None

    def test_too_long(self):
        with pytest.raises(ValidationError):
            TaskCreateRequest(title="T", repository="repo", description="x" * 5001)


class TestTaskCreateRequestRepository:
    """Repository name validation — whitelist pattern, no path traversal."""

    def test_valid_names(self):
        for name in ("repo", "my-repo", "my_repo", "Repo123"):
            req = TaskCreateRequest(title="T", repository=name)
            assert req.repository == name

    def test_rejects_path_traversal(self):
        with pytest.raises(ValidationError, match="invalid"):
            TaskCreateRequest(title="T", repository="../../../etc")

    def test_rejects_spaces(self):
        with pytest.raises(ValidationError, match="invalid"):
            TaskCreateRequest(title="T", repository="my repo")

    def test_rejects_leading_hyphen(self):
        with pytest.raises(ValidationError, match="hyphen"):
            TaskCreateRequest(title="T", repository="-repo")

    def test_rejects_leading_underscore(self):
        with pytest.raises(ValidationError, match="underscore"):
            TaskCreateRequest(title="T", repository="_repo")


class TestTaskCreateRequestTags:
    """Tag validation and deduplication."""

    def test_valid_tags(self):
        req = TaskCreateRequest(title="T", repository="repo", tags=["backend", "python-3"])
        assert req.tags == ["backend", "python-3"]

    def test_tags_lowered(self):
        req = TaskCreateRequest(title="T", repository="repo", tags=["Backend", "PYTHON"])
        assert req.tags == ["backend", "python"]

    def test_duplicate_tags_deduplicated(self):
        req = TaskCreateRequest(title="T", repository="repo", tags=["tag", "Tag", "TAG"])
        assert req.tags == ["tag"]

    def test_too_many_tags(self):
        with pytest.raises(ValidationError):
            TaskCreateRequest(title="T", repository="repo", tags=[f"t{i}" for i in range(11)])

    def test_tag_starts_with_hyphen_rejected(self):
        with pytest.raises(ValidationError, match="Invalid tag"):
            TaskCreateRequest(title="T", repository="repo", tags=["-bad"])

    def test_empty_tags_become_none(self):
        req = TaskCreateRequest(title="T", repository="repo", tags=["  ", ""])
        assert req.tags is None

    def test_none_tags_stay_none(self):
        req = TaskCreateRequest(title="T", repository="repo", tags=None)
        assert req.tags is None


class TestTaskCreateRequestDeadline:
    """Deadline validation — ISO 8601, must be future."""

    def test_invalid_format(self):
        with pytest.raises(ValidationError, match="Invalid deadline format"):
            TaskCreateRequest(title="T", repository="repo", deadline="not-a-date")

    def test_none_deadline_ok(self):
        req = TaskCreateRequest(title="T", repository="repo", deadline=None)
        assert req.deadline is None


# ---------------------------------------------------------------------------
# TaskUpdateRequest
# ---------------------------------------------------------------------------


class TestTaskUpdateRequest:
    """Partial update validation."""

    def test_empty_update(self):
        req = TaskUpdateRequest()
        assert req.title is None
        assert req.description is None
        assert req.priority is None

    def test_title_sanitized(self):
        req = TaskUpdateRequest(title="Clean\x00Title")
        assert req.title == "CleanTitle"

    def test_empty_string_deadline_clears(self):
        req = TaskUpdateRequest(deadline="")
        assert req.deadline is None

    def test_invalid_status(self):
        with pytest.raises(ValidationError):
            TaskUpdateRequest(status="exploding")


# ---------------------------------------------------------------------------
# FTSSearchQuery
# ---------------------------------------------------------------------------


class TestFTSSearchQuery:
    """Full-text search query sanitization and conversion."""

    def test_valid_query(self):
        q = FTSSearchQuery(query="authentication bug")
        assert q.query == "authentication bug"
        assert q.limit == 50
        assert q.offset == 0

    def test_null_bytes_removed(self):
        q = FTSSearchQuery(query="auth\x00bug")
        assert q.query == "authbug"

    def test_whitespace_normalized(self):
        q = FTSSearchQuery(query="auth   bug   fix")
        assert q.query == "auth bug fix"

    def test_sql_comment_rejected(self):
        with pytest.raises(ValidationError, match="dangerous"):
            FTSSearchQuery(query="auth -- drop")

    def test_sql_block_comment_rejected(self):
        with pytest.raises(ValidationError, match="dangerous"):
            FTSSearchQuery(query="auth /* comment */")

    def test_semicolon_rejected(self):
        with pytest.raises(ValidationError, match="dangerous"):
            FTSSearchQuery(query="auth; drop")

    def test_xp_prefix_rejected(self):
        with pytest.raises(ValidationError, match="dangerous"):
            FTSSearchQuery(query="xp_cmdshell")

    def test_exec_call_rejected(self):
        with pytest.raises(ValidationError, match="dangerous"):
            FTSSearchQuery(query="exec(something)")

    def test_query_too_long(self):
        with pytest.raises(ValidationError):
            FTSSearchQuery(query="x" * 501)

    def test_empty_after_sanitization(self):
        with pytest.raises(ValidationError, match="empty"):
            FTSSearchQuery(query="\x00  ")

    def test_to_tsquery_format(self):
        q = FTSSearchQuery(query="authentication bug fix")
        result = q.to_tsquery_format()
        assert result == "authentication & bug & fix"

    def test_to_tsquery_strips_special(self):
        q = FTSSearchQuery(query="auth&test|value")
        result = q.to_tsquery_format()
        # Special chars within terms are stripped by the regex
        assert "authtest" in result

    def test_limit_and_offset_validation(self):
        q = FTSSearchQuery(query="test", limit=100, offset=50)
        assert q.limit == 100
        assert q.offset == 50

    def test_invalid_limit(self):
        with pytest.raises(ValidationError):
            FTSSearchQuery(query="test", limit=0)

    def test_invalid_offset(self):
        with pytest.raises(ValidationError):
            FTSSearchQuery(query="test", offset=-1)


# ---------------------------------------------------------------------------
# TaskFilter
# ---------------------------------------------------------------------------


class TestTaskFilter:
    """Task filter validation."""

    def test_empty_filter(self):
        f = TaskFilter()
        assert f.status is None
        assert f.priority is None
        assert f.limit == 50

    def test_valid_filter(self):
        f = TaskFilter(status="in_progress", priority="high", repository="my-repo")
        assert f.status == "in_progress"
        assert f.priority == "high"

    def test_invalid_repository(self):
        with pytest.raises(ValidationError):
            TaskFilter(repository="../../etc")

    def test_invalid_date_format(self):
        with pytest.raises(ValidationError, match="Invalid date format"):
            TaskFilter(created_after="not-a-date")

    def test_date_range_inverted(self):
        with pytest.raises(ValidationError, match="must be before"):
            TaskFilter(
                created_after="2026-03-01T00:00:00Z",
                created_before="2026-02-01T00:00:00Z",
            )

    def test_valid_date_range(self):
        f = TaskFilter(
            created_after="2026-02-01T00:00:00Z",
            created_before="2026-03-01T00:00:00Z",
        )
        assert f.created_after == "2026-02-01T00:00:00Z"


# ---------------------------------------------------------------------------
# __all__ exports
# ---------------------------------------------------------------------------


class TestExports:
    def test_all_exports(self):
        from mahavishnu.core import task_models

        assert set(task_models.__all__) == {
            "TaskCreateRequest",
            "TaskUpdateRequest",
            "FTSSearchQuery",
            "TaskFilter",
        }
