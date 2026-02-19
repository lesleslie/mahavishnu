"""External Issue Importer for Mahavishnu.

Imports issues from external sources (GitHub, GitLab) into the task system:
- Parse issues from GitHub/GitLab APIs
- Filter by labels, repositories, status
- Map external issues to Mahavishnu tasks
- Track imported issues to prevent duplicates

Usage:
    from mahavishnu.core.external_issue_importer import ExternalIssueImporter

    importer = ExternalIssueImporter(task_store)

    # Import from GitHub
    issues = await importer.fetch_github_issues("owner/repo")
    result = await importer.import_batch(issues)

    # Check mapping
    mapping = importer.get_mapping("12345", IssueSource.GITHUB)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any

from mahavishnu.core.task_store import Task, TaskStatus, TaskPriority, TaskStore

logger = logging.getLogger(__name__)


class IssueSource(str, Enum):
    """Source of external issues."""

    GITHUB = "github"
    GITLAB = "gitlab"


@dataclass
class ExternalIssue:
    """Represents an issue from an external source.

    Attributes:
        external_id: ID in the external system
        source: Where the issue came from
        title: Issue title
        description: Issue body/description
        status: Issue status (open, closed, etc.)
        labels: Labels/tags on the issue
        url: URL to the original issue
        repository: Repository identifier
        assignees: List of assignee usernames
        created_at: When the issue was created
        updated_at: When the issue was last updated
    """

    external_id: str
    source: IssueSource
    title: str
    description: str
    status: str
    labels: list[str] = field(default_factory=list)
    url: str = ""
    repository: str = ""
    assignees: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "external_id": self.external_id,
            "source": self.source.value,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "labels": self.labels,
            "url": self.url,
            "repository": self.repository,
            "assignees": self.assignees,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


@dataclass
class IssueMapping:
    """Maps an external issue to a Mahavishnu task.

    Attributes:
        external_id: ID in the external system
        source: Where the issue came from
        task_id: Mahavishnu task ID
        repository: Mahavishnu repository
        mapped_at: When the mapping was created
        approved: Whether the import was approved
    """

    external_id: str
    source: IssueSource
    task_id: str
    repository: str
    mapped_at: datetime
    approved: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "external_id": self.external_id,
            "source": self.source.value,
            "task_id": self.task_id,
            "repository": self.repository,
            "mapped_at": self.mapped_at.isoformat(),
            "approved": self.approved,
        }


@dataclass
class ImportConfig:
    """Configuration for importing external issues.

    Attributes:
        source: Which external source to import from
        repository_filter: Only import from these repos (None = all)
        label_filter: Only import issues with these labels (None = all)
        import_closed: Whether to import closed issues
        auto_approve: Skip approval workflow
        default_priority: Priority for imported tasks
        default_repository: Repository for imported tasks
    """

    source: IssueSource
    repository_filter: list[str] | None = None
    label_filter: list[str] | None = None
    import_closed: bool = False
    auto_approve: bool = False
    default_priority: TaskPriority = TaskPriority.MEDIUM
    default_repository: str = "mahavishnu"


@dataclass
class ImportResult:
    """Result of an import operation.

    Attributes:
        imported_count: Number of successfully imported issues
        skipped_count: Number of skipped issues (duplicates, filters)
        failed_count: Number of failed imports
        imported_task_ids: IDs of created tasks
        errors: Error messages
    """

    imported_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    imported_task_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_processed(self) -> int:
        """Total number of issues processed."""
        return self.imported_count + self.skipped_count + self.failed_count

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "imported_count": self.imported_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "total_processed": self.total_processed,
            "imported_task_ids": self.imported_task_ids,
            "errors": self.errors,
        }


class ExternalIssueImporter:
    """Imports issues from external sources into Mahavishnu.

    Features:
    - Parse issues from GitHub and GitLab
    - Filter by repository, labels, status
    - Map external labels to task tags
    - Track imports to prevent duplicates
    - Support approval workflow

    Example:
        config = ImportConfig(
            source=IssueSource.GITHUB,
            label_filter=["bug", "feature"],
        )
        importer = ExternalIssueImporter(task_store, config)

        # Parse and import
        external = importer.parse_github_issue(github_data)
        task_id = await importer.import_issue(external)
    """

    def __init__(
        self,
        task_store: TaskStore,
        config: ImportConfig | None = None,
    ) -> None:
        """Initialize the importer.

        Args:
            task_store: TaskStore for creating tasks
            config: Import configuration (optional)
        """
        self.task_store = task_store
        self._config = config or ImportConfig(source=IssueSource.GITHUB)
        self._imported_ids: set[str] = set()
        self._mappings: dict[str, IssueMapping] = {}

    def parse_github_issue(self, data: dict[str, Any]) -> ExternalIssue:
        """Parse a GitHub issue API response.

        Args:
            data: GitHub issue data from API

        Returns:
            ExternalIssue object
        """
        labels = [label.get("name", "") for label in data.get("labels", [])]
        assignees = [a.get("login", "") for a in data.get("assignees", [])]

        created_at = None
        if data.get("created_at"):
            created_at = datetime.fromisoformat(
                data["created_at"].replace("Z", "+00:00")
            )

        updated_at = None
        if data.get("updated_at"):
            updated_at = datetime.fromisoformat(
                data["updated_at"].replace("Z", "+00:00")
            )

        repository = data.get("repository", {}).get("full_name", "")

        return ExternalIssue(
            external_id=str(data.get("id", data.get("number", ""))),
            source=IssueSource.GITHUB,
            title=data.get("title", ""),
            description=data.get("body", "") or "",
            status=data.get("state", "open"),
            labels=labels,
            url=data.get("html_url", ""),
            repository=repository,
            assignees=assignees,
            created_at=created_at,
            updated_at=updated_at,
        )

    def parse_gitlab_issue(self, data: dict[str, Any]) -> ExternalIssue:
        """Parse a GitLab issue API response.

        Args:
            data: GitLab issue data from API

        Returns:
            ExternalIssue object
        """
        labels = data.get("labels", [])
        if isinstance(labels, list) and labels and isinstance(labels[0], dict):
            labels = [l.get("name", "") for l in labels]

        assignees = [a.get("username", "") for a in data.get("assignees", [])]

        created_at = None
        if data.get("created_at"):
            created_at = datetime.fromisoformat(
                data["created_at"].replace("Z", "+00:00")
            )

        updated_at = None
        if data.get("updated_at"):
            updated_at = datetime.fromisoformat(
                data["updated_at"].replace("Z", "+00:00")
            )

        # Extract repository from references
        refs = data.get("references", {})
        repository = refs.get("full", "").split("#")[0] if refs.get("full") else ""

        return ExternalIssue(
            external_id=str(data.get("id", data.get("iid", ""))),
            source=IssueSource.GITLAB,
            title=data.get("title", ""),
            description=data.get("description", "") or "",
            status=data.get("state", "opened"),
            labels=labels if isinstance(labels, list) else [],
            url=data.get("web_url", ""),
            repository=repository,
            assignees=assignees,
            created_at=created_at,
            updated_at=updated_at,
        )

    def should_import(self, issue: ExternalIssue) -> bool:
        """Check if an issue should be imported.

        Args:
            issue: The issue to check

        Returns:
            True if the issue should be imported
        """
        # Check for duplicates
        key = f"{issue.source.value}:{issue.external_id}"
        if key in self._imported_ids:
            logger.debug(f"Skipping duplicate issue: {key}")
            return False

        # Check status filter (skip closed by default)
        if not self._config.import_closed:
            if issue.status in ("closed", "merged"):
                logger.debug(f"Skipping closed issue: {issue.external_id}")
                return False

        # Check repository filter
        if self._config.repository_filter:
            if issue.repository not in self._config.repository_filter:
                logger.debug(
                    f"Skipping issue from filtered repo: {issue.repository}"
                )
                return False

        # Check label filter
        if self._config.label_filter:
            if not any(label in issue.labels for label in self._config.label_filter):
                logger.debug(
                    f"Skipping issue without required labels: {issue.external_id}"
                )
                return False

        return True

    async def import_issue(self, issue: ExternalIssue) -> str | None:
        """Import an external issue as a Mahavishnu task.

        Args:
            issue: The issue to import

        Returns:
            Task ID if imported, None if skipped
        """
        if not self.should_import(issue):
            return None

        try:
            # Create task from external issue
            task = Task(
                id="",  # Will be assigned by store
                title=issue.title,
                description=issue.description,
                repository=self._config.default_repository,
                status=TaskStatus.PENDING,
                priority=self._config.default_priority,
                tags=issue.labels,
                created_at=datetime.now(UTC),
                metadata={
                    "external_source": issue.source.value,
                    "external_id": issue.external_id,
                    "external_url": issue.url,
                    "external_repository": issue.repository,
                    "imported_at": datetime.now(UTC).isoformat(),
                },
            )

            created_task = await self.task_store.create(task)

            # Track the import
            key = f"{issue.source.value}:{issue.external_id}"
            self._imported_ids.add(key)

            # Create mapping
            self._mappings[key] = IssueMapping(
                external_id=issue.external_id,
                source=issue.source,
                task_id=created_task.id,
                repository=task.repository,
                mapped_at=datetime.now(UTC),
                approved=self._config.auto_approve,
            )

            logger.info(
                f"Imported issue {issue.external_id} from {issue.source.value} "
                f"as task {created_task.id}"
            )

            return created_task.id

        except Exception as e:
            logger.error(f"Failed to import issue {issue.external_id}: {e}")
            return None

    async def import_batch(self, issues: list[ExternalIssue]) -> ImportResult:
        """Import multiple issues in batch.

        Args:
            issues: List of issues to import

        Returns:
            ImportResult with statistics
        """
        result = ImportResult()

        for issue in issues:
            task_id = await self.import_issue(issue)

            if task_id:
                result.imported_count += 1
                result.imported_task_ids.append(task_id)
            elif f"{issue.source.value}:{issue.external_id}" in self._imported_ids:
                result.skipped_count += 1
            else:
                result.failed_count += 1
                result.errors.append(f"Failed to import issue {issue.external_id}")

        logger.info(
            f"Batch import complete: {result.imported_count} imported, "
            f"{result.skipped_count} skipped, {result.failed_count} failed"
        )

        return result

    def get_mapping(
        self,
        external_id: str,
        source: IssueSource,
    ) -> IssueMapping | None:
        """Get the task mapping for an external issue.

        Args:
            external_id: External issue ID
            source: Issue source

        Returns:
            IssueMapping if found, None otherwise
        """
        key = f"{source.value}:{external_id}"
        return self._mappings.get(key)

    def get_all_mappings(self) -> list[IssueMapping]:
        """Get all issue mappings.

        Returns:
            List of all IssueMapping objects
        """
        return list(self._mappings.values())

    def clear_mappings(self) -> None:
        """Clear all mappings and imported IDs."""
        self._mappings.clear()
        self._imported_ids.clear()


__all__ = [
    "ExternalIssueImporter",
    "ExternalIssue",
    "IssueMapping",
    "ImportConfig",
    "ImportResult",
    "IssueSource",
]
