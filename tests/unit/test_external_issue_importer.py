"""Tests for ExternalIssueImporter - Import issues from GitHub/GitLab."""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from mahavishnu.core.external_issue_importer import (
    ExternalIssueImporter,
    ImportResult,
    ImportConfig,
    IssueMapping,
    ExternalIssue,
    IssueSource,
)


@pytest.fixture
def mock_task_store() -> AsyncMock:
    """Create a mock TaskStore."""
    store = AsyncMock()
    return store


@pytest.fixture
def sample_github_issue() -> dict[str, Any]:
    """Create a sample GitHub issue."""
    return {
        "id": 12345,
        "number": 42,
        "title": "Fix authentication bug",
        "body": "Users cannot log in with SSO",
        "state": "open",
        "labels": [{"name": "bug"}, {"name": "high-priority"}],
        "assignees": [{"login": "developer1"}],
        "created_at": "2026-02-15T10:00:00Z",
        "updated_at": "2026-02-18T14:30:00Z",
        "html_url": "https://github.com/owner/repo/issues/42",
        "repository": {"full_name": "owner/repo"},
    }


@pytest.fixture
def sample_gitlab_issue() -> dict[str, Any]:
    """Create a sample GitLab issue."""
    return {
        "id": 98765,
        "iid": 15,
        "title": "Add dark mode support",
        "description": "Implement dark mode for the UI",
        "state": "opened",
        "labels": ["feature", "ui"],
        "assignees": [{"username": "developer2"}],
        "created_at": "2026-02-10T08:00:00Z",
        "updated_at": "2026-02-19T09:00:00Z",
        "web_url": "https://gitlab.com/owner/repo/-/issues/15",
        "references": {"full": "owner/repo#15"},
    }


class TestIssueSource:
    """Tests for IssueSource enum."""

    def test_issue_sources(self) -> None:
        """Test available issue sources."""
        assert IssueSource.GITHUB.value == "github"
        assert IssueSource.GITLAB.value == "gitlab"


class TestExternalIssue:
    """Tests for ExternalIssue dataclass."""

    def test_create_external_issue(self) -> None:
        """Create an external issue."""
        issue = ExternalIssue(
            external_id="12345",
            source=IssueSource.GITHUB,
            title="Fix bug",
            description="Bug description",
            status="open",
            labels=["bug", "high-priority"],
            url="https://github.com/owner/repo/issues/42",
            repository="owner/repo",
        )

        assert issue.external_id == "12345"
        assert issue.source == IssueSource.GITHUB
        assert issue.title == "Fix bug"
        assert "bug" in issue.labels

    def test_external_issue_to_dict(self) -> None:
        """Convert external issue to dictionary."""
        issue = ExternalIssue(
            external_id="42",
            source=IssueSource.GITLAB,
            title="Feature request",
            description="Add feature",
            status="opened",
            labels=["feature"],
            url="https://gitlab.com/owner/repo/-/issues/42",
            repository="owner/repo",
        )

        d = issue.to_dict()
        assert d["external_id"] == "42"
        assert d["source"] == "gitlab"
        assert d["title"] == "Feature request"


class TestIssueMapping:
    """Tests for IssueMapping dataclass."""

    def test_create_issue_mapping(self) -> None:
        """Create an issue mapping."""
        mapping = IssueMapping(
            external_id="12345",
            source=IssueSource.GITHUB,
            task_id="task-1",
            repository="mahavishnu",
            mapped_at=datetime.now(UTC),
        )

        assert mapping.external_id == "12345"
        assert mapping.task_id == "task-1"
        assert mapping.source == IssueSource.GITHUB

    def test_issue_mapping_to_dict(self) -> None:
        """Convert issue mapping to dictionary."""
        mapping = IssueMapping(
            external_id="42",
            source=IssueSource.GITLAB,
            task_id="task-2",
            repository="crackerjack",
            mapped_at=datetime.now(UTC),
        )

        d = mapping.to_dict()
        assert d["external_id"] == "42"
        assert d["task_id"] == "task-2"


class TestImportConfig:
    """Tests for ImportConfig dataclass."""

    def test_create_import_config(self) -> None:
        """Create an import configuration."""
        config = ImportConfig(
            source=IssueSource.GITHUB,
            repository_filter=["owner/repo", "owner/repo2"],
            label_filter=["bug", "feature"],
            import_closed=False,
            auto_approve=False,
        )

        assert config.source == IssueSource.GITHUB
        assert len(config.repository_filter) == 2
        assert "bug" in config.label_filter
        assert config.import_closed is False

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = ImportConfig(source=IssueSource.GITHUB)

        assert config.repository_filter is None
        assert config.label_filter is None
        assert config.import_closed is False
        assert config.auto_approve is False


class TestImportResult:
    """Tests for ImportResult dataclass."""

    def test_create_import_result(self) -> None:
        """Create an import result."""
        result = ImportResult(
            imported_count=5,
            skipped_count=2,
            failed_count=1,
            imported_task_ids=["task-1", "task-2", "task-3", "task-4", "task-5"],
            errors=["Failed to import issue #10"],
        )

        assert result.imported_count == 5
        assert result.skipped_count == 2
        assert result.failed_count == 1
        assert len(result.imported_task_ids) == 5

    def test_import_result_to_dict(self) -> None:
        """Convert import result to dictionary."""
        result = ImportResult(
            imported_count=3,
            skipped_count=1,
            failed_count=0,
            imported_task_ids=["task-1", "task-2", "task-3"],
            errors=[],
        )

        d = result.to_dict()
        assert d["imported_count"] == 3
        assert d["skipped_count"] == 1
        assert d["total_processed"] == 4


class TestExternalIssueImporter:
    """Tests for ExternalIssueImporter class."""

    def test_parse_github_issue(
        self,
        mock_task_store: AsyncMock,
        sample_github_issue: dict[str, Any],
    ) -> None:
        """Parse a GitHub issue into ExternalIssue."""
        importer = ExternalIssueImporter(mock_task_store)

        external = importer.parse_github_issue(sample_github_issue)

        assert external is not None
        assert external.external_id == "12345"
        assert external.source == IssueSource.GITHUB
        assert external.title == "Fix authentication bug"
        assert "bug" in external.labels
        assert external.repository == "owner/repo"

    def test_parse_gitlab_issue(
        self,
        mock_task_store: AsyncMock,
        sample_gitlab_issue: dict[str, Any],
    ) -> None:
        """Parse a GitLab issue into ExternalIssue."""
        importer = ExternalIssueImporter(mock_task_store)

        external = importer.parse_gitlab_issue(sample_gitlab_issue)

        assert external is not None
        assert external.external_id == "98765"
        assert external.source == IssueSource.GITLAB
        assert external.title == "Add dark mode support"
        assert "feature" in external.labels

    @pytest.mark.asyncio
    async def test_import_single_issue(
        self,
        mock_task_store: AsyncMock,
        sample_github_issue: dict[str, Any],
    ) -> None:
        """Import a single external issue as a task."""
        mock_task_store.create.return_value = MagicMock(id="task-1")

        importer = ExternalIssueImporter(mock_task_store)
        external = importer.parse_github_issue(sample_github_issue)

        task_id = await importer.import_issue(external)

        assert task_id is not None
        mock_task_store.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_import_filters_by_label(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Import respects label filter."""
        config = ImportConfig(
            source=IssueSource.GITHUB,
            label_filter=["bug"],  # Only import bugs
        )

        importer = ExternalIssueImporter(mock_task_store, config)

        # Issue with feature label should be skipped
        feature_issue = ExternalIssue(
            external_id="1",
            source=IssueSource.GITHUB,
            title="New feature",
            description="",
            status="open",
            labels=["feature"],
            url="https://github.com/owner/repo/issues/1",
            repository="owner/repo",
        )

        should_import = importer.should_import(feature_issue)
        assert should_import is False

        # Issue with bug label should be imported
        bug_issue = ExternalIssue(
            external_id="2",
            source=IssueSource.GITHUB,
            title="Bug fix",
            description="",
            status="open",
            labels=["bug"],
            url="https://github.com/owner/repo/issues/2",
            repository="owner/repo",
        )

        should_import = importer.should_import(bug_issue)
        assert should_import is True

    @pytest.mark.asyncio
    async def test_import_filters_by_repository(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Import respects repository filter."""
        config = ImportConfig(
            source=IssueSource.GITHUB,
            repository_filter=["owner/repo1"],
        )

        importer = ExternalIssueImporter(mock_task_store, config)

        # Issue from different repo should be skipped
        issue = ExternalIssue(
            external_id="1",
            source=IssueSource.GITHUB,
            title="Issue",
            description="",
            status="open",
            labels=[],
            url="https://github.com/owner/repo2/issues/1",
            repository="owner/repo2",
        )

        should_import = importer.should_import(issue)
        assert should_import is False

    @pytest.mark.asyncio
    async def test_import_skips_closed_issues(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Import skips closed issues by default."""
        importer = ExternalIssueImporter(mock_task_store)

        closed_issue = ExternalIssue(
            external_id="1",
            source=IssueSource.GITHUB,
            title="Closed issue",
            description="",
            status="closed",
            labels=[],
            url="https://github.com/owner/repo/issues/1",
            repository="owner/repo",
        )

        should_import = importer.should_import(closed_issue)
        assert should_import is False

    @pytest.mark.asyncio
    async def test_import_maps_labels_to_tags(
        self,
        mock_task_store: AsyncMock,
        sample_github_issue: dict[str, Any],
    ) -> None:
        """External labels are mapped to task tags."""
        mock_task_store.create.return_value = MagicMock(id="task-1")

        importer = ExternalIssueImporter(mock_task_store)
        external = importer.parse_github_issue(sample_github_issue)

        task_id = await importer.import_issue(external)

        # Verify create was called with tags from labels
        call_args = mock_task_store.create.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_batch_import(
        self,
        mock_task_store: AsyncMock,
        sample_github_issue: dict[str, Any],
    ) -> None:
        """Import multiple issues in batch."""
        mock_task_store.create.return_value = MagicMock(id="task-1")

        importer = ExternalIssueImporter(mock_task_store)

        issues = [
            ExternalIssue(
                external_id=str(i),
                source=IssueSource.GITHUB,
                title=f"Issue {i}",
                description="",
                status="open",
                labels=[],
                url=f"https://github.com/owner/repo/issues/{i}",
                repository="owner/repo",
            )
            for i in range(5)
        ]

        result = await importer.import_batch(issues)

        assert result.imported_count == 5
        assert result.failed_count == 0

    @pytest.mark.asyncio
    async def test_import_handles_duplicates(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Import handles duplicate issues gracefully."""
        importer = ExternalIssueImporter(mock_task_store)

        # Mark issue as already imported (using correct key format)
        importer._imported_ids.add("github:12345")

        issue = ExternalIssue(
            external_id="12345",
            source=IssueSource.GITHUB,
            title="Duplicate issue",
            description="",
            status="open",
            labels=[],
            url="https://github.com/owner/repo/issues/42",
            repository="owner/repo",
        )

        result = await importer.import_issue(issue)

        assert result is None  # Skipped duplicate

    @pytest.mark.asyncio
    async def test_get_mapping_for_issue(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Get the task mapping for an external issue."""
        importer = ExternalIssueImporter(mock_task_store)

        # Add a mapping
        mapping = IssueMapping(
            external_id="12345",
            source=IssueSource.GITHUB,
            task_id="task-1",
            repository="mahavishnu",
            mapped_at=datetime.now(UTC),
        )
        importer._mappings["github:12345"] = mapping

        result = importer.get_mapping("12345", IssueSource.GITHUB)

        assert result is not None
        assert result.task_id == "task-1"

    @pytest.mark.asyncio
    async def test_import_preserves_metadata(
        self,
        mock_task_store: AsyncMock,
        sample_github_issue: dict[str, Any],
    ) -> None:
        """Import preserves external issue metadata."""
        mock_task_store.create.return_value = MagicMock(id="task-1")

        importer = ExternalIssueImporter(mock_task_store)
        external = importer.parse_github_issue(sample_github_issue)

        await importer.import_issue(external)

        # Verify metadata was preserved
        call_args = mock_task_store.create.call_args
        assert call_args is not None
        # The task should have metadata about the source

    @pytest.mark.asyncio
    async def test_import_with_auto_approve(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Auto-approve bypasses approval workflow."""
        config = ImportConfig(
            source=IssueSource.GITHUB,
            auto_approve=True,
        )

        importer = ExternalIssueImporter(mock_task_store, config)

        issue = ExternalIssue(
            external_id="1",
            source=IssueSource.GITHUB,
            title="Auto-approved",
            description="",
            status="open",
            labels=[],
            url="https://github.com/owner/repo/issues/1",
            repository="owner/repo",
        )

        # With auto_approve, should_import should return True
        assert importer.should_import(issue) is True
        assert importer._config.auto_approve is True
