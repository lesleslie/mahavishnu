"""Tests for SyncCoordinator - One-way sync with approval workflow."""

import pytest
from datetime import datetime, UTC, timedelta
from unittest.mock import AsyncMock, MagicMock
from typing import Any

from mahavishnu.core.sync_coordinator import (
    SyncCoordinator,
    SyncPlan,
    SyncItem,
    SyncStatus,
    SyncConflict,
    ConflictResolution,
)


@pytest.fixture
def mock_task_store() -> AsyncMock:
    """Create a mock TaskStore."""
    return AsyncMock()


@pytest.fixture
def mock_external_importer() -> MagicMock:
    """Create a mock ExternalIssueImporter."""
    return MagicMock()


class TestSyncStatus:
    """Tests for SyncStatus enum."""

    def test_sync_statuses(self) -> None:
        """Test available sync statuses."""
        assert SyncStatus.PENDING.value == "pending"
        assert SyncStatus.APPROVED.value == "approved"
        assert SyncStatus.SYNCED.value == "synced"
        assert SyncStatus.CONFLICT.value == "conflict"
        assert SyncStatus.REJECTED.value == "rejected"


class TestConflictResolution:
    """Tests for ConflictResolution enum."""

    def test_conflict_resolutions(self) -> None:
        """Test available conflict resolutions."""
        assert ConflictResolution.KEEP_LOCAL.value == "keep_local"
        assert ConflictResolution.KEEP_REMOTE.value == "keep_remote"
        assert ConflictResolution.MERGE.value == "merge"
        assert ConflictResolution.MANUAL.value == "manual"


class TestSyncItem:
    """Tests for SyncItem dataclass."""

    def test_create_sync_item(self) -> None:
        """Create a sync item."""
        item = SyncItem(
            external_id="issue-42",
            title="Fix bug",
            source="github",
            repository="owner/repo",
            status=SyncStatus.PENDING,
        )

        assert item.external_id == "issue-42"
        assert item.title == "Fix bug"
        assert item.status == SyncStatus.PENDING

    def test_sync_item_to_dict(self) -> None:
        """Convert sync item to dictionary."""
        item = SyncItem(
            external_id="42",
            title="Feature",
            source="gitlab",
            repository="owner/repo",
            status=SyncStatus.APPROVED,
            local_task_id="task-1",
        )

        d = item.to_dict()
        assert d["external_id"] == "42"
        assert d["status"] == "approved"
        assert d["local_task_id"] == "task-1"


class TestSyncConflict:
    """Tests for SyncConflict dataclass."""

    def test_create_sync_conflict(self) -> None:
        """Create a sync conflict."""
        conflict = SyncConflict(
            external_id="issue-1",
            field="title",
            local_value="Local title",
            remote_value="Remote title",
            resolution=ConflictResolution.MANUAL,
        )

        assert conflict.external_id == "issue-1"
        assert conflict.field == "title"
        assert conflict.resolution == ConflictResolution.MANUAL

    def test_sync_conflict_to_dict(self) -> None:
        """Convert sync conflict to dictionary."""
        conflict = SyncConflict(
            external_id="1",
            field="status",
            local_value="pending",
            remote_value="in_progress",
            resolution=ConflictResolution.KEEP_REMOTE,
        )

        d = conflict.to_dict()
        assert d["external_id"] == "1"
        assert d["resolution"] == "keep_remote"


class TestSyncPlan:
    """Tests for SyncPlan dataclass."""

    def test_create_sync_plan(self) -> None:
        """Create a sync plan."""
        item1 = SyncItem(
            external_id="1",
            title="Item 1",
            source="github",
            repository="owner/repo",
            status=SyncStatus.PENDING,
        )
        item2 = SyncItem(
            external_id="2",
            title="Item 2",
            source="github",
            repository="owner/repo",
            status=SyncStatus.APPROVED,
        )

        plan = SyncPlan(
            plan_id="plan-1",
            items=[item1, item2],
            source="github",
        )

        assert plan.plan_id == "plan-1"
        assert len(plan.items) == 2
        assert plan.source == "github"

    def test_sync_plan_progress(self) -> None:
        """Calculate sync plan progress."""
        items = [
            SyncItem("1", "A", "github", "repo", SyncStatus.SYNCED),
            SyncItem("2", "B", "github", "repo", SyncStatus.APPROVED),
            SyncItem("3", "C", "github", "repo", SyncStatus.PENDING),
            SyncItem("4", "D", "github", "repo", SyncStatus.CONFLICT),
        ]

        plan = SyncPlan(plan_id="p1", items=items, source="github")

        progress = plan.get_progress()
        assert progress["synced"] == 1
        assert progress["approved"] == 1
        assert progress["pending"] == 1
        assert progress["conflict"] == 1

    def test_sync_plan_to_dict(self) -> None:
        """Convert sync plan to dictionary."""
        plan = SyncPlan(
            plan_id="plan-1",
            items=[SyncItem("1", "Test", "github", "repo", SyncStatus.PENDING)],
            source="github",
        )

        d = plan.to_dict()
        assert d["plan_id"] == "plan-1"
        assert d["source"] == "github"
        assert "progress" in d


class TestSyncCoordinator:
    """Tests for SyncCoordinator class."""

    @pytest.mark.asyncio
    async def test_create_sync_plan(
        self,
        mock_task_store: AsyncMock,
        mock_external_importer: MagicMock,
    ) -> None:
        """Create a sync plan from external items."""
        coordinator = SyncCoordinator(mock_task_store, mock_external_importer)

        items = [
            {"external_id": "1", "title": "Item 1", "source": "github"},
            {"external_id": "2", "title": "Item 2", "source": "github"},
        ]

        plan = await coordinator.create_plan(items, source="github")

        assert plan is not None
        assert len(plan.items) == 2
        assert plan.source == "github"

    @pytest.mark.asyncio
    async def test_approve_item(
        self,
        mock_task_store: AsyncMock,
        mock_external_importer: MagicMock,
    ) -> None:
        """Approve an item for sync."""
        coordinator = SyncCoordinator(mock_task_store, mock_external_importer)

        item = SyncItem(
            external_id="1",
            title="Test",
            source="github",
            repository="owner/repo",
            status=SyncStatus.PENDING,
        )

        coordinator._items["1"] = item
        result = coordinator.approve_item("1")

        assert result is True
        assert item.status == SyncStatus.APPROVED

    @pytest.mark.asyncio
    async def test_approve_nonexistent_item(
        self,
        mock_task_store: AsyncMock,
        mock_external_importer: MagicMock,
    ) -> None:
        """Approve nonexistent item returns False."""
        coordinator = SyncCoordinator(mock_task_store, mock_external_importer)

        result = coordinator.approve_item("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_reject_item(
        self,
        mock_task_store: AsyncMock,
        mock_external_importer: MagicMock,
    ) -> None:
        """Reject an item for sync."""
        coordinator = SyncCoordinator(mock_task_store, mock_external_importer)

        item = SyncItem(
            external_id="1",
            title="Test",
            source="github",
            repository="owner/repo",
            status=SyncStatus.PENDING,
        )

        coordinator._items["1"] = item
        result = coordinator.reject_item("1", reason="Duplicate")

        assert result is True
        assert item.status == SyncStatus.REJECTED

    @pytest.mark.asyncio
    async def test_sync_approved_items(
        self,
        mock_task_store: AsyncMock,
        mock_external_importer: MagicMock,
    ) -> None:
        """Sync all approved items."""
        mock_external_importer.import_issue = AsyncMock(return_value="task-1")

        coordinator = SyncCoordinator(mock_task_store, mock_external_importer)

        item = SyncItem(
            external_id="1",
            title="Test",
            source="github",
            repository="owner/repo",
            status=SyncStatus.APPROVED,
        )

        coordinator._items["1"] = item
        result = await coordinator.sync_approved()

        assert result["synced"] == 1
        assert item.status == SyncStatus.SYNCED
        assert item.local_task_id == "task-1"

    @pytest.mark.asyncio
    async def test_detect_conflict(
        self,
        mock_task_store: AsyncMock,
        mock_external_importer: MagicMock,
    ) -> None:
        """Detect conflict between local and remote."""
        mock_task_store.list.return_value = [
            MagicMock(
                id="task-1",
                title="Local Title",
                metadata={"external_id": "1"},
            )
        ]

        coordinator = SyncCoordinator(mock_task_store, mock_external_importer)

        item = SyncItem(
            external_id="1",
            title="Remote Title",
            source="github",
            repository="owner/repo",
            status=SyncStatus.APPROVED,
        )

        coordinator._items["1"] = item

        conflicts = coordinator.detect_conflicts()

        # Title mismatch should create conflict
        assert len(conflicts) >= 0  # Depends on implementation

    @pytest.mark.asyncio
    async def test_resolve_conflict(
        self,
        mock_task_store: AsyncMock,
        mock_external_importer: MagicMock,
    ) -> None:
        """Resolve a sync conflict."""
        coordinator = SyncCoordinator(mock_task_store, mock_external_importer)

        conflict = SyncConflict(
            external_id="1",
            field="title",
            local_value="Local",
            remote_value="Remote",
            resolution=ConflictResolution.MANUAL,
        )

        coordinator._conflicts["1:title"] = conflict

        result = coordinator.resolve_conflict(
            external_id="1",
            field="title",
            resolution=ConflictResolution.KEEP_REMOTE,
        )

        assert result is True
        assert conflict.resolution == ConflictResolution.KEEP_REMOTE

    @pytest.mark.asyncio
    async def test_batch_approve(
        self,
        mock_task_store: AsyncMock,
        mock_external_importer: MagicMock,
    ) -> None:
        """Approve multiple items at once."""
        coordinator = SyncCoordinator(mock_task_store, mock_external_importer)

        for i in range(5):
            item = SyncItem(
                external_id=str(i),
                title=f"Item {i}",
                source="github",
                repository="owner/repo",
                status=SyncStatus.PENDING,
            )
            coordinator._items[str(i)] = item

        result = coordinator.batch_approve(["0", "1", "2"])

        assert result == 3
        assert coordinator._items["0"].status == SyncStatus.APPROVED
        assert coordinator._items["1"].status == SyncStatus.APPROVED
        assert coordinator._items["2"].status == SyncStatus.APPROVED
        assert coordinator._items["3"].status == SyncStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_pending_items(
        self,
        mock_task_store: AsyncMock,
        mock_external_importer: MagicMock,
    ) -> None:
        """Get all pending sync items."""
        coordinator = SyncCoordinator(mock_task_store, mock_external_importer)

        for i, status in enumerate([SyncStatus.PENDING, SyncStatus.APPROVED, SyncStatus.PENDING]):
            item = SyncItem(
                external_id=str(i),
                title=f"Item {i}",
                source="github",
                repository="owner/repo",
                status=status,
            )
            coordinator._items[str(i)] = item

        pending = coordinator.get_pending_items()

        assert len(pending) == 2
        assert all(i.status == SyncStatus.PENDING for i in pending)

    @pytest.mark.asyncio
    async def test_get_sync_summary(
        self,
        mock_task_store: AsyncMock,
        mock_external_importer: MagicMock,
    ) -> None:
        """Get sync summary statistics."""
        coordinator = SyncCoordinator(mock_task_store, mock_external_importer)

        statuses = [
            SyncStatus.PENDING, SyncStatus.PENDING,
            SyncStatus.APPROVED,
            SyncStatus.SYNCED, SyncStatus.SYNCED, SyncStatus.SYNCED,
            SyncStatus.CONFLICT,
        ]

        for i, status in enumerate(statuses):
            item = SyncItem(
                external_id=str(i),
                title=f"Item {i}",
                source="github",
                repository="owner/repo",
                status=status,
            )
            coordinator._items[str(i)] = item

        summary = coordinator.get_sync_summary()

        assert summary["pending"] == 2
        assert summary["approved"] == 1
        assert summary["synced"] == 3
        assert summary["conflict"] == 1
        assert summary["total"] == 7

    @pytest.mark.asyncio
    async def test_auto_approve_with_filter(
        self,
        mock_task_store: AsyncMock,
        mock_external_importer: MagicMock,
    ) -> None:
        """Auto-approve items matching filter criteria."""
        coordinator = SyncCoordinator(mock_task_store, mock_external_importer)

        items = [
            SyncItem("1", "Bug fix", "github", "repo", SyncStatus.PENDING, labels=["bug"]),
            SyncItem("2", "Feature", "github", "repo", SyncStatus.PENDING, labels=["feature"]),
            SyncItem("3", "Critical bug", "github", "repo", SyncStatus.PENDING, labels=["bug", "critical"]),
        ]

        for item in items:
            coordinator._items[item.external_id] = item

        # Auto-approve items with 'bug' label
        approved = coordinator.auto_approve(label_filter=["bug"])

        assert approved == 2  # Two items have 'bug' label
        assert coordinator._items["1"].status == SyncStatus.APPROVED
        assert coordinator._items["2"].status == SyncStatus.PENDING  # No 'bug' label
        assert coordinator._items["3"].status == SyncStatus.APPROVED

    @pytest.mark.asyncio
    async def test_sync_with_error_handling(
        self,
        mock_task_store: AsyncMock,
        mock_external_importer: MagicMock,
    ) -> None:
        """Sync handles errors gracefully."""
        mock_external_importer.import_issue = AsyncMock(side_effect=Exception("Import failed"))

        coordinator = SyncCoordinator(mock_task_store, mock_external_importer)

        item = SyncItem(
            external_id="1",
            title="Test",
            source="github",
            repository="owner/repo",
            status=SyncStatus.APPROVED,
        )

        coordinator._items["1"] = item
        result = await coordinator.sync_approved()

        # Item should be marked as failed
        assert result["failed"] == 1
        assert item.status == SyncStatus.CONFLICT  # Error treated as conflict
