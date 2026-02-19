"""Sync Coordinator for Mahavishnu.

Manages one-way synchronization with approval workflow:
- Create sync plans from external sources
- Approve/reject individual items
- Detect and resolve conflicts
- Track sync progress

Usage:
    from mahavishnu.core.sync_coordinator import SyncCoordinator

    coordinator = SyncCoordinator(task_store, external_importer)

    # Create sync plan
    plan = await coordinator.create_plan(external_items, source="github")

    # Approve items
    coordinator.approve_item("issue-1")

    # Sync approved items
    result = await coordinator.sync_approved()
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any

from mahavishnu.core.task_store import TaskStore

logger = logging.getLogger(__name__)


class SyncStatus(str, Enum):
    """Status of a sync item."""

    PENDING = "pending"  # Awaiting approval
    APPROVED = "approved"  # Approved for sync
    SYNCED = "synced"  # Successfully synced
    CONFLICT = "conflict"  # Has conflict
    REJECTED = "rejected"  # Rejected by user
    FAILED = "failed"  # Sync failed


class ConflictResolution(str, Enum):
    """How to resolve a sync conflict."""

    KEEP_LOCAL = "keep_local"  # Keep local version
    KEEP_REMOTE = "keep_remote"  # Keep remote version
    MERGE = "merge"  # Merge both versions
    MANUAL = "manual"  # Requires manual resolution


@dataclass
class SyncItem:
    """An item to be synchronized.

    Attributes:
        external_id: ID in external system
        title: Item title
        source: External source (github, gitlab)
        repository: Repository identifier
        status: Current sync status
        local_task_id: Mahavishnu task ID if synced
        labels: Item labels
        description: Item description
        created_at: When item was created externally
        approved_at: When item was approved
        synced_at: When item was synced
    """

    external_id: str
    title: str
    source: str
    repository: str
    status: SyncStatus = SyncStatus.PENDING
    local_task_id: str | None = None
    labels: list[str] = field(default_factory=list)
    description: str = ""
    created_at: datetime | None = None
    approved_at: datetime | None = None
    synced_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "external_id": self.external_id,
            "title": self.title,
            "source": self.source,
            "repository": self.repository,
            "status": self.status.value,
            "local_task_id": self.local_task_id,
            "labels": self.labels,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "synced_at": self.synced_at.isoformat() if self.synced_at else None,
        }


@dataclass
class SyncConflict:
    """Represents a conflict between local and remote.

    Attributes:
        external_id: External item ID
        field: Field with conflict
        local_value: Value in local system
        remote_value: Value from external system
        resolution: How conflict was resolved
        resolved_at: When conflict was resolved
    """

    external_id: str
    field: str
    local_value: Any
    remote_value: Any
    resolution: ConflictResolution = ConflictResolution.MANUAL
    resolved_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "external_id": self.external_id,
            "field": self.field,
            "local_value": str(self.local_value),
            "remote_value": str(self.remote_value),
            "resolution": self.resolution.value,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


@dataclass
class SyncPlan:
    """A plan for synchronizing external items.

    Attributes:
        plan_id: Unique plan identifier
        items: Items to sync
        source: External source
        created_at: When plan was created
        total_items: Total number of items
    """

    plan_id: str
    items: list[SyncItem] = field(default_factory=list)
    source: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    total_items: int = 0

    def get_progress(self) -> dict[str, int]:
        """Get progress statistics.

        Returns:
            Dictionary with counts by status
        """
        counts = {
            "pending": 0,
            "approved": 0,
            "synced": 0,
            "conflict": 0,
            "rejected": 0,
            "failed": 0,
        }

        for item in self.items:
            if item.status.value in counts:
                counts[item.status.value] += 1

        return counts

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "plan_id": self.plan_id,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "total_items": len(self.items),
            "items": [i.to_dict() for i in self.items],
            "progress": self.get_progress(),
        }


class SyncCoordinator:
    """Coordinates one-way synchronization with approval workflow.

    Features:
    - Create sync plans from external sources
    - Approve/reject individual items
    - Batch operations for efficiency
    - Conflict detection and resolution
    - Progress tracking

    Example:
        coordinator = SyncCoordinator(task_store, external_importer)

        # Create plan from external items
        plan = await coordinator.create_plan(items, source="github")

        # Review and approve
        coordinator.approve_item("issue-1")
        coordinator.batch_approve(["issue-2", "issue-3"])

        # Sync
        result = await coordinator.sync_approved()
        print(f"Synced {result['synced']} items")
    """

    def __init__(
        self,
        task_store: TaskStore,
        external_importer: Any,  # ExternalIssueImporter
    ) -> None:
        """Initialize the sync coordinator.

        Args:
            task_store: TaskStore for task operations
            external_importer: ExternalIssueImporter for importing
        """
        self.task_store = task_store
        self.external_importer = external_importer
        self._items: dict[str, SyncItem] = {}
        self._conflicts: dict[str, SyncConflict] = {}
        self._plans: dict[str, SyncPlan] = {}

    async def create_plan(
        self,
        items: list[dict[str, Any]],
        source: str,
    ) -> SyncPlan:
        """Create a sync plan from external items.

        Args:
            items: List of external items to sync
            source: External source (github, gitlab)

        Returns:
            SyncPlan with items awaiting approval
        """
        sync_items: list[SyncItem] = []

        for item_data in items:
            item = SyncItem(
                external_id=item_data.get("external_id", item_data.get("id", "")),
                title=item_data.get("title", ""),
                source=source,
                repository=item_data.get("repository", ""),
                labels=item_data.get("labels", []),
                description=item_data.get("description", ""),
                status=SyncStatus.PENDING,
                created_at=datetime.now(UTC),
            )
            sync_items.append(item)
            self._items[item.external_id] = item

        plan = SyncPlan(
            plan_id=str(uuid.uuid4()),
            items=sync_items,
            source=source,
            total_items=len(sync_items),
        )

        self._plans[plan.plan_id] = plan

        logger.info(f"Created sync plan {plan.plan_id} with {len(sync_items)} items from {source}")

        return plan

    def approve_item(self, external_id: str) -> bool:
        """Approve an item for synchronization.

        Args:
            external_id: External item ID

        Returns:
            True if approved, False if not found
        """
        item = self._items.get(external_id)
        if not item:
            return False

        if item.status != SyncStatus.PENDING:
            return False

        item.status = SyncStatus.APPROVED
        item.approved_at = datetime.now(UTC)

        logger.info(f"Approved sync item: {external_id}")
        return True

    def reject_item(self, external_id: str, reason: str = "") -> bool:
        """Reject an item for synchronization.

        Args:
            external_id: External item ID
            reason: Reason for rejection

        Returns:
            True if rejected, False if not found
        """
        item = self._items.get(external_id)
        if not item:
            return False

        item.status = SyncStatus.REJECTED
        logger.info(f"Rejected sync item: {external_id} ({reason})")
        return True

    def batch_approve(self, external_ids: list[str]) -> int:
        """Approve multiple items at once.

        Args:
            external_ids: List of external IDs to approve

        Returns:
            Number of items approved
        """
        approved = 0
        for external_id in external_ids:
            if self.approve_item(external_id):
                approved += 1
        return approved

    def batch_reject(self, external_ids: list[str], reason: str = "") -> int:
        """Reject multiple items at once.

        Args:
            external_ids: List of external IDs to reject
            reason: Reason for rejection

        Returns:
            Number of items rejected
        """
        rejected = 0
        for external_id in external_ids:
            if self.reject_item(external_id, reason):
                rejected += 1
        return rejected

    async def sync_approved(self) -> dict[str, int]:
        """Synchronize all approved items.

        Returns:
            Dictionary with sync results
        """
        result = {
            "synced": 0,
            "failed": 0,
            "skipped": 0,
        }

        for item in self._items.values():
            if item.status != SyncStatus.APPROVED:
                continue

            try:
                # Import via external importer
                from mahavishnu.core.external_issue_importer import ExternalIssue, IssueSource

                external = ExternalIssue(
                    external_id=item.external_id,
                    source=IssueSource.GITHUB if item.source == "github" else IssueSource.GITLAB,
                    title=item.title,
                    description=item.description,
                    status="open",
                    labels=item.labels,
                    url="",
                    repository=item.repository,
                )

                task_id = await self.external_importer.import_issue(external)

                if task_id:
                    item.status = SyncStatus.SYNCED
                    item.local_task_id = task_id
                    item.synced_at = datetime.now(UTC)
                    result["synced"] += 1
                    logger.info(f"Synced item {item.external_id} as task {task_id}")
                else:
                    item.status = SyncStatus.FAILED
                    result["failed"] += 1

            except Exception as e:
                item.status = SyncStatus.CONFLICT
                result["failed"] += 1
                logger.error(f"Failed to sync item {item.external_id}: {e}")

        return result

    def detect_conflicts(self) -> list[SyncConflict]:
        """Detect conflicts between local and remote items.

        Returns:
            List of detected conflicts
        """
        conflicts: list[SyncConflict] = []

        # This would compare external items with local tasks
        # For now, return empty list (no conflicts detected by default)
        return conflicts

    def resolve_conflict(
        self,
        external_id: str,
        field: str,
        resolution: ConflictResolution,
    ) -> bool:
        """Resolve a sync conflict.

        Args:
            external_id: External item ID
            field: Field with conflict
            resolution: How to resolve

        Returns:
            True if resolved, False if not found
        """
        key = f"{external_id}:{field}"
        conflict = self._conflicts.get(key)

        if not conflict:
            return False

        conflict.resolution = resolution
        conflict.resolved_at = datetime.now(UTC)

        # Update item status if all conflicts resolved
        item = self._items.get(external_id)
        if item and item.status == SyncStatus.CONFLICT:
            # Check if all conflicts for this item are resolved
            item_conflicts = [
                c for k, c in self._conflicts.items()
                if k.startswith(f"{external_id}:")
            ]
            if all(c.resolution != ConflictResolution.MANUAL for c in item_conflicts):
                item.status = SyncStatus.APPROVED

        logger.info(f"Resolved conflict for {external_id}.{field}: {resolution.value}")
        return True

    def get_pending_items(self) -> list[SyncItem]:
        """Get all items pending approval.

        Returns:
            List of pending SyncItems
        """
        return [
            item for item in self._items.values()
            if item.status == SyncStatus.PENDING
        ]

    def get_approved_items(self) -> list[SyncItem]:
        """Get all approved items.

        Returns:
            List of approved SyncItems
        """
        return [
            item for item in self._items.values()
            if item.status == SyncStatus.APPROVED
        ]

    def get_sync_summary(self) -> dict[str, int]:
        """Get sync summary statistics.

        Returns:
            Dictionary with counts by status
        """
        counts = {
            "pending": 0,
            "approved": 0,
            "synced": 0,
            "conflict": 0,
            "rejected": 0,
            "failed": 0,
            "total": 0,
        }

        for item in self._items.values():
            counts["total"] += 1
            if item.status.value in counts:
                counts[item.status.value] += 1

        return counts

    def auto_approve(
        self,
        label_filter: list[str] | None = None,
        repository_filter: list[str] | None = None,
    ) -> int:
        """Auto-approve items matching criteria.

        Args:
            label_filter: Only approve items with these labels
            repository_filter: Only approve items from these repos

        Returns:
            Number of items auto-approved
        """
        approved = 0

        for item in self._items.values():
            if item.status != SyncStatus.PENDING:
                continue

            # Check label filter
            if label_filter:
                if not any(label in item.labels for label in label_filter):
                    continue

            # Check repository filter
            if repository_filter:
                if item.repository not in repository_filter:
                    continue

            item.status = SyncStatus.APPROVED
            item.approved_at = datetime.now(UTC)
            approved += 1

        logger.info(f"Auto-approved {approved} items")
        return approved

    def get_plan(self, plan_id: str) -> SyncPlan | None:
        """Get a sync plan by ID.

        Args:
            plan_id: Plan ID to retrieve

        Returns:
            SyncPlan if found, None otherwise
        """
        return self._plans.get(plan_id)


__all__ = [
    "SyncCoordinator",
    "SyncPlan",
    "SyncItem",
    "SyncStatus",
    "SyncConflict",
    "ConflictResolution",
]
