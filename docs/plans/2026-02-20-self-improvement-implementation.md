# Self-Improvement System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build Mahavishnu's self-improvement system with parallel fix pools, dual tracking, and triggered review workflow.

**Architecture:** Three-phase approach - fix pools with quality gates, ecosystem.yaml + Session-Buddy tracking, and MCP-triggered review_and_fix workflow with manual approval gates.

**Tech Stack:** FastMCP, asyncio pools, Pydantic models, Crackerjack quality gates, WebSocket broadcasting

---

## Phase 1: Core Infrastructure

### Task 1: Approval Manager

**Files:**
- Create: `mahavishnu/core/approval_manager.py`
- Test: `tests/unit/test_approval_manager.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_approval_manager.py
"""Tests for the approval manager."""

import pytest
from datetime import datetime, UTC, timedelta

from mahavishnu.core.approval_manager import (
    ApprovalManager,
    ApprovalRequest,
    ApprovalOption,
    ApprovalResult,
)


class TestApprovalRequest:
    """Test ApprovalRequest model."""

    def test_create_version_bump_request(self) -> None:
        """Test creating a version bump approval request."""
        request = ApprovalRequest(
            id="approval-001",
            approval_type="version_bump",
            context={
                "current_version": "0.24.2",
                "suggested_version": "0.24.3",
                "bump_type": "patch",
            },
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
            options=[
                ApprovalOption(
                    label="Approve patch",
                    description="Bump 0.24.2 -> 0.24.3",
                    is_recommended=True,
                ),
                ApprovalOption(
                    label="Minor bump",
                    description="Bump 0.24.2 -> 0.25.0",
                    is_recommended=False,
                ),
                ApprovalOption(
                    label="Skip",
                    description="Do not bump version",
                    is_recommended=False,
                ),
            ],
        )

        assert request.id == "approval-001"
        assert request.approval_type == "version_bump"
        assert len(request.options) == 3
        assert request.options[0].is_recommended is True

    def test_request_expired(self) -> None:
        """Test checking if request is expired."""
        request = ApprovalRequest(
            id="approval-002",
            approval_type="publish",
            context={},
            created_at=datetime.now(UTC) - timedelta(hours=1),
            expires_at=datetime.now(UTC) - timedelta(minutes=30),
            options=[],
        )

        assert request.is_expired is True

    def test_request_not_expired(self) -> None:
        """Test checking if request is not expired."""
        request = ApprovalRequest(
            id="approval-003",
            approval_type="publish",
            context={},
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
            options=[],
        )

        assert request.is_expired is False


class TestApprovalManager:
    """Test ApprovalManager class."""

    @pytest.fixture
    def manager(self) -> ApprovalManager:
        """Create approval manager instance."""
        return ApprovalManager()

    def test_create_approval_request(self, manager: ApprovalManager) -> None:
        """Test creating an approval request."""
        request = manager.create_request(
            approval_type="version_bump",
            context={
                "current_version": "0.24.2",
                "suggested_version": "0.24.3",
            },
        )

        assert request.id.startswith("approval-")
        assert request.approval_type == "version_bump"
        assert request.is_expired is False
        assert request in manager.pending_requests

    def test_get_pending_request(self, manager: ApprovalManager) -> None:
        """Test retrieving a pending request."""
        request = manager.create_request(
            approval_type="publish",
            context={"version": "0.24.3"},
        )

        retrieved = manager.get_request(request.id)
        assert retrieved == request

    def test_get_nonexistent_request(self, manager: ApprovalManager) -> None:
        """Test retrieving a nonexistent request."""
        retrieved = manager.get_request("nonexistent-id")
        assert retrieved is None

    def test_respond_to_request_approve(self, manager: ApprovalManager) -> None:
        """Test approving a request."""
        request = manager.create_request(
            approval_type="version_bump",
            context={"suggested_version": "0.24.3"},
            options=[
                ApprovalOption(label="Approve", description="Approve", is_recommended=True),
            ],
        )

        result = manager.respond(request.id, approved=True, selected_option=0)

        assert result.approved is True
        assert result.selected_option == 0
        assert request not in manager.pending_requests

    def test_respond_to_request_reject(self, manager: ApprovalManager) -> None:
        """Test rejecting a request."""
        request = manager.create_request(
            approval_type="version_bump",
            context={},
        )

        result = manager.respond(request.id, approved=False)

        assert result.approved is False
        assert request not in manager.pending_requests

    def test_respond_to_expired_request(self, manager: ApprovalManager) -> None:
        """Test responding to an expired request raises error."""
        request = ApprovalRequest(
            id="expired-request",
            approval_type="version_bump",
            context={},
            created_at=datetime.now(UTC) - timedelta(hours=1),
            expires_at=datetime.now(UTC) - timedelta(minutes=30),
            options=[],
        )
        manager._pending_requests[request.id] = request

        with pytest.raises(ValueError, match="expired"):
            manager.respond(request.id, approved=True)

    def test_cleanup_expired_requests(self, manager: ApprovalManager) -> None:
        """Test cleaning up expired requests."""
        # Create an expired request directly
        expired = ApprovalRequest(
            id="expired",
            approval_type="version_bump",
            context={},
            created_at=datetime.now(UTC) - timedelta(hours=1),
            expires_at=datetime.now(UTC) - timedelta(minutes=30),
            options=[],
        )
        manager._pending_requests[expired.id] = expired

        # Create a valid request
        valid = manager.create_request(approval_type="publish", context={})

        manager.cleanup_expired()

        assert expired not in manager.pending_requests
        assert valid in manager.pending_requests
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_approval_manager.py -v`
Expected: FAIL with "No module named 'mahavishnu.core.approval_manager'"

**Step 3: Write minimal implementation**

```python
# mahavishnu/core/approval_manager.py
"""Manual approval management for version bumps and publishing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from typing import Any, Literal

from pydantic import BaseModel


@dataclass
class ApprovalOption:
    """An option the user can select in an approval request."""

    label: str
    description: str
    is_recommended: bool = False


@dataclass
class ApprovalRequest:
    """Represents a pending approval request."""

    id: str
    approval_type: Literal["version_bump", "publish"]
    context: dict[str, Any]
    created_at: datetime
    expires_at: datetime
    options: list[ApprovalOption]

    @property
    def is_expired(self) -> bool:
        """Check if this request has expired."""
        return datetime.now(UTC) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "approval_type": self.approval_type,
            "context": self.context,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "is_expired": self.is_expired,
            "options": [
                {
                    "label": opt.label,
                    "description": opt.description,
                    "is_recommended": opt.is_recommended,
                }
                for opt in self.options
            ],
        }


@dataclass
class ApprovalResult:
    """Result of an approval decision."""

    approved: bool
    selected_option: int | None = None
    rejection_reason: str | None = None


class ApprovalManager:
    """Manages manual approval workflows for version bumps and publishing."""

    def __init__(self, default_timeout_minutes: int = 30) -> None:
        """Initialize the approval manager.

        Args:
            default_timeout_minutes: Default time before requests expire.
        """
        self._pending_requests: dict[str, ApprovalRequest] = {}
        self._default_timeout = timedelta(minutes=default_timeout_minutes)

    @property
    def pending_requests(self) -> list[ApprovalRequest]:
        """Get all pending requests."""
        return list(self._pending_requests.values())

    def create_request(
        self,
        approval_type: Literal["version_bump", "publish"],
        context: dict[str, Any],
        options: list[ApprovalOption] | None = None,
        timeout_minutes: int | None = None,
    ) -> ApprovalRequest:
        """Create a new approval request.

        Args:
            approval_type: Type of approval needed.
            context: Context data for the approval.
            options: Available options for the user.
            timeout_minutes: Custom timeout (uses default if None).

        Returns:
            The created approval request.
        """
        request_id = f"approval-{uuid.uuid4().hex[:8]}"
        timeout = timedelta(minutes=timeout_minutes) if timeout_minutes else self._default_timeout

        # Generate default options if not provided
        if options is None:
            options = self._generate_default_options(approval_type, context)

        request = ApprovalRequest(
            id=request_id,
            approval_type=approval_type,
            context=context,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timeout,
            options=options,
        )

        self._pending_requests[request.id] = request
        return request

    def _generate_default_options(
        self,
        approval_type: Literal["version_bump", "publish"],
        context: dict[str, Any],
    ) -> list[ApprovalOption]:
        """Generate default options for an approval type."""
        if approval_type == "version_bump":
            current = context.get("current_version", "0.0.0")
            suggested = context.get("suggested_version", "")
            return [
                ApprovalOption(
                    label="Approve patch",
                    description=f"Bump {current} -> {suggested}",
                    is_recommended=True,
                ),
                ApprovalOption(
                    label="Minor bump",
                    description="Request minor version bump instead",
                    is_recommended=False,
                ),
                ApprovalOption(
                    label="Skip",
                    description="Do not bump version",
                    is_recommended=False,
                ),
            ]
        elif approval_type == "publish":
            return [
                ApprovalOption(
                    label="Publish to PyPI",
                    description="Publish the new version to PyPI",
                    is_recommended=True,
                ),
                ApprovalOption(
                    label="GitHub Release",
                    description="Create a GitHub release only",
                    is_recommended=False,
                ),
                ApprovalOption(
                    label="Skip",
                    description="Do not publish",
                    is_recommended=False,
                ),
            ]
        return []

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Get a pending request by ID."""
        return self._pending_requests.get(request_id)

    def respond(
        self,
        request_id: str,
        approved: bool,
        selected_option: int | None = None,
        rejection_reason: str | None = None,
    ) -> ApprovalResult:
        """Respond to an approval request.

        Args:
            request_id: ID of the request to respond to.
            approved: Whether the request is approved.
            selected_option: Index of the selected option (if approved).
            rejection_reason: Reason for rejection (if not approved).

        Returns:
            The approval result.

        Raises:
            ValueError: If request not found or expired.
        """
        request = self._pending_requests.get(request_id)
        if request is None:
            raise ValueError(f"Request {request_id} not found")

        if request.is_expired:
            del self._pending_requests[request_id]
            raise ValueError(f"Request {request_id} has expired")

        # Remove from pending
        del self._pending_requests[request_id]

        return ApprovalResult(
            approved=approved,
            selected_option=selected_option,
            rejection_reason=rejection_reason,
        )

    def cleanup_expired(self) -> int:
        """Remove all expired requests.

        Returns:
            Number of requests removed.
        """
        expired_ids = [
            req.id for req in self._pending_requests.values() if req.is_expired
        ]
        for req_id in expired_ids:
            del self._pending_requests[req_id]
        return len(expired_ids)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_approval_manager.py -v`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add mahavishnu/core/approval_manager.py tests/unit/test_approval_manager.py
git commit -m "feat: add approval manager for version bump and publish gates"
```

---

### Task 2: Fix Orchestrator

**Files:**
- Create: `mahavishnu/core/fix_orchestrator.py`
- Test: `tests/unit/test_fix_orchestrator.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_fix_orchestrator.py
"""Tests for the fix orchestrator."""

import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from mahavishnu.core.fix_orchestrator import (
    FixOrchestrator,
    FixResult,
    FixTask,
    QualityGateResult,
)
from mahavishnu.core.coordination.models import CrossRepoIssue, IssueStatus


class TestFixTask:
    """Test FixTask model."""

    def test_create_fix_task(self) -> None:
        """Test creating a fix task."""
        task = FixTask(
            issue_id="MHV-001",
            pool_type="python",
            prompt="Fix the asyncio.run() issue",
            affected_files=["mahavishnu/core/app.py"],
        )

        assert task.issue_id == "MHV-001"
        assert task.pool_type == "python"
        assert len(task.affected_files) == 1


class TestQualityGateResult:
    """Test QualityGateResult model."""

    def test_all_passed(self) -> None:
        """Test when all gates pass."""
        result = QualityGateResult(
            fast_hooks=True,
            tests=True,
            comprehensive=True,
            coverage=85.0,
        )

        assert result.all_passed is True

    def test_fast_hooks_failed(self) -> None:
        """Test when fast hooks fail."""
        result = QualityGateResult(
            fast_hooks=False,
            tests=True,
            comprehensive=True,
            coverage=85.0,
        )

        assert result.all_passed is False
        assert result.blocking_failure is True

    def test_tests_failed(self) -> None:
        """Test when tests fail."""
        result = QualityGateResult(
            fast_hooks=True,
            tests=False,
            comprehensive=True,
            coverage=75.0,
        )

        assert result.all_passed is False
        assert result.blocking_failure is True

    def test_comprehensive_failed_not_blocking(self) -> None:
        """Test when comprehensive hooks fail (non-blocking)."""
        result = QualityGateResult(
            fast_hooks=True,
            tests=True,
            comprehensive=False,
            coverage=85.0,
        )

        assert result.all_passed is False
        assert result.blocking_failure is False


class TestFixOrchestrator:
    """Test FixOrchestrator class."""

    @pytest.fixture
    def mock_pool_manager(self) -> MagicMock:
        """Create mock pool manager."""
        manager = MagicMock()
        manager.execute_on_pool = AsyncMock(return_value={
            "success": True,
            "worker_id": "worker-001",
            "changes": ["app.py:707"],
        })
        manager.spawn_pool = AsyncMock(return_value="pool-001")
        return manager

    @pytest.fixture
    def mock_coordination_manager(self) -> MagicMock:
        """Create mock coordination manager."""
        manager = MagicMock()
        manager.update_issue = AsyncMock()
        return manager

    @pytest.fixture
    def mock_approval_manager(self) -> MagicMock:
        """Create mock approval manager."""
        manager = MagicMock()
        manager.create_request = MagicMock(return_value=MagicMock(id="approval-001"))
        manager.respond = MagicMock(return_value=MagicMock(approved=True, selected_option=0))
        return manager

    @pytest.fixture
    def orchestrator(
        self,
        mock_pool_manager: MagicMock,
        mock_coordination_manager: MagicMock,
        mock_approval_manager: MagicMock,
    ) -> FixOrchestrator:
        """Create fix orchestrator instance."""
        return FixOrchestrator(
            pool_manager=mock_pool_manager,
            coordination_manager=mock_coordination_manager,
            approval_manager=mock_approval_manager,
        )

    @pytest.mark.asyncio
    async def test_execute_fix_success(
        self,
        orchestrator: FixOrchestrator,
        mock_pool_manager: MagicMock,
    ) -> None:
        """Test successful fix execution."""
        task = FixTask(
            issue_id="MHV-001",
            pool_type="python",
            prompt="Fix the issue",
            affected_files=["app.py"],
        )

        with patch.object(orchestrator, "_run_quality_gates") as mock_gates:
            mock_gates.return_value = QualityGateResult(
                fast_hooks=True,
                tests=True,
                comprehensive=True,
                coverage=85.0,
            )

            result = await orchestrator.execute_fix("pool-001", task)

        assert result.success is True
        assert result.stage == "complete"
        mock_pool_manager.execute_on_pool.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_fix_quality_gate_failure(
        self,
        orchestrator: FixOrchestrator,
        mock_pool_manager: MagicMock,
    ) -> None:
        """Test fix execution with quality gate failure."""
        task = FixTask(
            issue_id="MHV-002",
            pool_type="python",
            prompt="Fix the issue",
            affected_files=["app.py"],
        )

        with patch.object(orchestrator, "_run_quality_gates") as mock_gates:
            mock_gates.return_value = QualityGateResult(
                fast_hooks=False,
                tests=True,
                comprehensive=True,
                coverage=85.0,
            )

            result = await orchestrator.execute_fix("pool-001", task)

        assert result.success is False
        assert result.stage == "fast_hooks"

    @pytest.mark.asyncio
    async def test_execute_fix_pool_failure(
        self,
        orchestrator: FixOrchestrator,
        mock_pool_manager: MagicMock,
    ) -> None:
        """Test fix execution with pool failure."""
        mock_pool_manager.execute_on_pool.return_value = {
            "success": False,
            "error": "Worker crashed",
        }

        task = FixTask(
            issue_id="MHV-003",
            pool_type="python",
            prompt="Fix the issue",
            affected_files=["app.py"],
        )

        result = await orchestrator.execute_fix("pool-001", task)

        assert result.success is False
        assert result.stage == "execution"
        assert "Worker crashed" in result.error_message

    @pytest.mark.asyncio
    async def test_execute_batch_parallel(
        self,
        orchestrator: FixOrchestrator,
        mock_pool_manager: MagicMock,
    ) -> None:
        """Test batch execution runs in parallel."""
        tasks = [
            FixTask(issue_id=f"MHV-00{i}", pool_type="python", prompt=f"Fix {i}", affected_files=[])
            for i in range(1, 4)
        ]

        with patch.object(orchestrator, "execute_fix") as mock_execute:
            mock_execute.return_value = FixResult(success=True, stage="complete")

            results = await orchestrator.execute_batch("pool-001", tasks)

        assert len(results) == 3
        assert all(r.success for r in results)
        assert mock_execute.call_count == 3
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_fix_orchestrator.py -v`
Expected: FAIL with "No module named 'mahavishnu.core.fix_orchestrator'"

**Step 3: Write minimal implementation**

```python
# mahavishnu/core/fix_orchestrator.py
"""Orchestrates fix execution with quality gates and approval workflow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mahavishnu.pools.manager import PoolManager
    from mahavishnu.core.coordination.manager import CoordinationManager
    from mahavishnu.core.approval_manager import ApprovalManager


@dataclass
class FixTask:
    """Represents a fix task to be executed."""

    issue_id: str
    pool_type: str
    prompt: str
    affected_files: list[str] = field(default_factory=list)


@dataclass
class QualityGateResult:
    """Results from quality gate checks."""

    fast_hooks: bool
    tests: bool
    comprehensive: bool
    coverage: float
    errors: list[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        """Check if all gates passed."""
        return self.fast_hooks and self.tests and self.comprehensive

    @property
    def blocking_failure(self) -> bool:
        """Check if there's a blocking failure (fast hooks or tests)."""
        return not self.fast_hooks or not self.tests

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "fast_hooks": self.fast_hooks,
            "tests": self.tests,
            "comprehensive": self.comprehensive,
            "coverage": self.coverage,
            "all_passed": self.all_passed,
            "blocking_failure": self.blocking_failure,
            "errors": self.errors,
        }


@dataclass
class FixResult:
    """Result of a fix execution."""

    success: bool
    stage: str
    quality_gates: QualityGateResult | None = None
    error_message: str = ""
    changes: list[str] = field(default_factory=list)
    worker_id: str = ""


class FixOrchestrator:
    """Orchestrates fix execution with quality gates and approvals."""

    def __init__(
        self,
        pool_manager: PoolManager,
        coordination_manager: CoordinationManager,
        approval_manager: ApprovalManager,
    ) -> None:
        """Initialize the fix orchestrator.

        Args:
            pool_manager: Pool manager for executing fixes.
            coordination_manager: Coordination manager for tracking issues.
            approval_manager: Approval manager for manual gates.
        """
        self.pool_manager = pool_manager
        self.coordination_manager = coordination_manager
        self.approval_manager = approval_manager

    async def execute_fix(
        self,
        pool_id: str,
        task: FixTask,
    ) -> FixResult:
        """Execute a single fix task with quality gates.

        Args:
            pool_id: ID of the pool to execute on.
            task: The fix task to execute.

        Returns:
            The result of the fix execution.
        """
        # Step 1: Execute fix in pool
        try:
            execution_result = await self.pool_manager.execute_on_pool(
                pool_id,
                {
                    "prompt": task.prompt,
                    "issue_id": task.issue_id,
                    "files": task.affected_files,
                },
            )
        except Exception as e:
            return FixResult(
                success=False,
                stage="execution",
                error_message=str(e),
            )

        if not execution_result.get("success", False):
            return FixResult(
                success=False,
                stage="execution",
                error_message=execution_result.get("error", "Unknown error"),
            )

        # Step 2: Run quality gates
        quality_result = await self._run_quality_gates()

        # Step 3: Check blocking gates
        if quality_result.blocking_failure:
            return FixResult(
                success=False,
                stage="fast_hooks" if not quality_result.fast_hooks else "tests",
                quality_gates=quality_result,
            )

        # Step 4: Update issue status
        await self._update_issue_status(task.issue_id, execution_result, quality_result)

        return FixResult(
            success=True,
            stage="complete",
            quality_gates=quality_result,
            changes=execution_result.get("changes", []),
            worker_id=execution_result.get("worker_id", ""),
        )

    async def execute_batch(
        self,
        pool_id: str,
        tasks: list[FixTask],
    ) -> list[FixResult]:
        """Execute multiple fix tasks in parallel.

        Args:
            pool_id: ID of the pool to execute on.
            tasks: List of fix tasks to execute.

        Returns:
            List of results for each task.
        """
        results = await asyncio.gather(
            *[self.execute_fix(pool_id, task) for task in tasks],
            return_exceptions=True,
        )

        # Convert exceptions to failed results
        final_results: list[FixResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(FixResult(
                    success=False,
                    stage="execution",
                    error_message=str(result),
                ))
            else:
                final_results.append(result)

        return final_results

    async def _run_quality_gates(self) -> QualityGateResult:
        """Run quality gate checks.

        Returns:
            Quality gate results.
        """
        # TODO: Integrate with actual Crackerjack API
        # For now, return mock passing results
        return QualityGateResult(
            fast_hooks=True,
            tests=True,
            comprehensive=True,
            coverage=85.0,
        )

    async def _update_issue_status(
        self,
        issue_id: str,
        execution_result: dict[str, Any],
        quality_result: QualityGateResult,
    ) -> None:
        """Update issue status after fix."""
        # TODO: Implement with actual CoordinationManager
        pass
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_fix_orchestrator.py -v`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add mahavishnu/core/fix_orchestrator.py tests/unit/test_fix_orchestrator.py
git commit -m "feat: add fix orchestrator with quality gates"
```

---

## Phase 2: MCP Tools

### Task 3: Self-Improvement MCP Tools

**Files:**
- Create: `mahavishnu/mcp/tools/self_improvement_tools.py`
- Test: `tests/unit/test_self_improvement_tools.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_self_improvement_tools.py
"""Tests for self-improvement MCP tools."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mahavishnu.mcp.tools.self_improvement_tools import (
    ReviewScope,
    ReviewResult,
    SelfImprovementTools,
)


class TestReviewScope:
    """Test ReviewScope enum."""

    def test_scope_values(self) -> None:
        """Test scope enum values."""
        assert ReviewScope.CRITICAL.value == "critical"
        assert ReviewScope.SECURITY.value == "security"
        assert ReviewScope.PERFORMANCE.value == "performance"
        assert ReviewScope.QUALITY.value == "quality"
        assert ReviewScope.ALL.value == "all"


class TestSelfImprovementTools:
    """Test SelfImprovementTools class."""

    @pytest.fixture
    def mock_app(self) -> MagicMock:
        """Create mock MahavishnuApp."""
        app = MagicMock()
        app.pool_manager = MagicMock()
        app.coordination_manager = MagicMock()
        app.approval_manager = MagicMock()
        return app

    @pytest.fixture
    def tools(self, mock_app: MagicMock) -> SelfImprovementTools:
        """Create self-improvement tools instance."""
        return SelfImprovementTools(mock_app)

    @pytest.mark.asyncio
    async def test_review_and_fix_dry_run(
        self,
        tools: SelfImprovementTools,
    ) -> None:
        """Test review and fix in dry-run mode."""
        with patch.object(tools, "_run_review") as mock_review:
            mock_review.return_value = [
                {"id": "MHV-001", "title": "Test issue", "severity": "critical"},
            ]

            result = await tools.review_and_fix(
                scope=ReviewScope.CRITICAL,
                auto_fix=False,
                dry_run=True,
            )

        assert result["dry_run"] is True
        assert result["findings_count"] == 1
        assert result["issues_created"] == 0

    @pytest.mark.asyncio
    async def test_review_and_fix_creates_issues(
        self,
        tools: SelfImprovementTools,
        mock_app: MagicMock,
    ) -> None:
        """Test review and fix creates issues."""
        mock_app.coordination_manager.create_issue = AsyncMock(return_value=None)

        with patch.object(tools, "_run_review") as mock_review:
            mock_review.return_value = [
                {
                    "id": "MHV-001",
                    "title": "Test issue",
                    "severity": "critical",
                    "pool": "python",
                    "affected_files": ["app.py"],
                },
            ]

            result = await tools.review_and_fix(
                scope=ReviewScope.CRITICAL,
                auto_fix=False,
                dry_run=False,
            )

        assert result["findings_count"] == 1
        assert result["issues_created"] == 1
        mock_app.coordination_manager.create_issue.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_approval(
        self,
        tools: SelfImprovementTools,
        mock_app: MagicMock,
    ) -> None:
        """Test requesting manual approval."""
        mock_app.approval_manager.create_request = MagicMock(return_value=MagicMock(
            id="approval-001",
            approval_type="version_bump",
            to_dict=lambda: {"id": "approval-001"},
        ))

        result = await tools.request_approval(
            approval_type="version_bump",
            context={"version": "0.24.3"},
        )

        assert result["approval_id"] == "approval-001"
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_respond_to_approval(
        self,
        tools: SelfImprovementTools,
        mock_app: MagicMock,
    ) -> None:
        """Test responding to an approval request."""
        mock_app.approval_manager.respond = MagicMock(return_value=MagicMock(
            approved=True,
            selected_option=0,
        ))

        result = await tools.respond_to_approval(
            approval_id="approval-001",
            approved=True,
            selected_option=0,
        )

        assert result["approved"] is True

    @pytest.mark.asyncio
    async def test_get_pending_approvals(
        self,
        tools: SelfImprovementTools,
        mock_app: MagicMock,
    ) -> None:
        """Test getting pending approvals."""
        mock_app.approval_manager.pending_requests = [
            MagicMock(id="approval-001", approval_type="version_bump"),
            MagicMock(id="approval-002", approval_type="publish"),
        ]

        result = await tools.get_pending_approvals()

        assert result["count"] == 2
        assert len(result["approvals"]) == 2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_self_improvement_tools.py -v`
Expected: FAIL with "No module named 'mahavishnu.mcp.tools.self_improvement_tools'"

**Step 3: Write minimal implementation**

```python
# mahavishnu/mcp/tools/self_improvement_tools.py
"""MCP tools for self-improvement workflow."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mahavishnu.core.app import MahavishnuApp


class ReviewScope(str, Enum):
    """Scope for review operations."""

    CRITICAL = "critical"
    SECURITY = "security"
    PERFORMANCE = "performance"
    QUALITY = "quality"
    ALL = "all"


class SelfImprovementTools:
    """MCP tools for self-improvement workflow."""

    def __init__(self, app: MahavishnuApp) -> None:
        """Initialize self-improvement tools.

        Args:
            app: The Mahavishnu application instance.
        """
        self.app = app

    async def review_and_fix(
        self,
        scope: ReviewScope = ReviewScope.CRITICAL,
        auto_fix: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Run comprehensive review and optionally fix issues.

        Args:
            scope: Review scope - critical, security, performance, quality, or all.
            auto_fix: If True, automatically spawn fix pools for found issues.
            dry_run: If True, report findings without making changes.

        Returns:
            Dictionary with findings, issues created, and fix results.
        """
        # Run review agents
        findings = await self._run_review(scope)

        result: dict[str, Any] = {
            "scope": scope.value,
            "dry_run": dry_run,
            "findings_count": len(findings),
            "findings": findings,
            "issues_created": 0,
            "fixes_applied": [],
        }

        if dry_run:
            return result

        # Create issues in ecosystem.yaml
        for finding in findings:
            await self.app.coordination_manager.create_issue(
                issue_id=finding.get("id"),
                title=finding.get("title", ""),
                description=finding.get("description", ""),
                severity=finding.get("severity", "medium"),
                pool=finding.get("pool", "python"),
                affected_files=finding.get("affected_files", []),
            )
            result["issues_created"] += 1

        # Auto-fix if requested
        if auto_fix and findings:
            critical_findings = [
                f for f in findings if f.get("severity") == "critical"
            ]
            if critical_findings:
                fixes = await self._auto_fix(critical_findings)
                result["fixes_applied"] = fixes

        return result

    async def request_approval(
        self,
        approval_type: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Request manual approval for version bump or publish.

        Args:
            approval_type: Type of approval - "version_bump" or "publish".
            context: Context data for the approval.

        Returns:
            Dictionary with approval request details.
        """
        request = self.app.approval_manager.create_request(
            approval_type=approval_type,
            context=context,
        )

        # TODO: Broadcast via WebSocket
        # await self.app.websocket_server.broadcast(...)

        return {
            "approval_id": request.id,
            "status": "pending",
            "approval_type": approval_type,
            "expires_at": request.expires_at.isoformat(),
            "options": [
                {"label": opt.label, "description": opt.description}
                for opt in request.options
            ],
        }

    async def respond_to_approval(
        self,
        approval_id: str,
        approved: bool,
        selected_option: int | None = None,
        rejection_reason: str | None = None,
    ) -> dict[str, Any]:
        """Respond to a pending approval request.

        Args:
            approval_id: ID of the approval request.
            approved: Whether to approve.
            selected_option: Index of selected option (if approved).
            rejection_reason: Reason for rejection (if not approved).

        Returns:
            Dictionary with response result.
        """
        result = self.app.approval_manager.respond(
            request_id=approval_id,
            approved=approved,
            selected_option=selected_option,
            rejection_reason=rejection_reason,
        )

        return {
            "approval_id": approval_id,
            "approved": result.approved,
            "selected_option": result.selected_option,
            "rejection_reason": result.rejection_reason,
        }

    async def get_pending_approvals(self) -> dict[str, Any]:
        """Get all pending approval requests.

        Returns:
            Dictionary with pending approvals list.
        """
        requests = self.app.approval_manager.pending_requests

        return {
            "count": len(requests),
            "approvals": [
                {
                    "id": req.id,
                    "type": req.approval_type,
                    "created_at": req.created_at.isoformat(),
                    "is_expired": req.is_expired,
                }
                for req in requests
            ],
        }

    async def _run_review(self, scope: ReviewScope) -> list[dict[str, Any]]:
        """Run review agents based on scope.

        Args:
            scope: The review scope.

        Returns:
            List of findings from review agents.
        """
        # TODO: Spawn actual review agents via pool manager
        # For now, return placeholder findings
        findings: list[dict[str, Any]] = []

        if scope in (ReviewScope.CRITICAL, ReviewScope.ALL):
            findings.extend([
                {
                    "id": "MHV-001",
                    "title": "asyncio.run() in sync context",
                    "description": "app.py:707 calls asyncio.run() in sync method",
                    "severity": "critical",
                    "pool": "python",
                    "affected_files": ["mahavishnu/core/app.py"],
                },
            ])

        return findings

    async def _auto_fix(self, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Auto-fix critical findings.

        Args:
            findings: List of findings to fix.

        Returns:
            List of fix results.
        """
        # TODO: Implement with FixOrchestrator
        return []
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_self_improvement_tools.py -v`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add mahavishnu/mcp/tools/self_improvement_tools.py tests/unit/test_self_improvement_tools.py
git commit -m "feat: add self-improvement MCP tools"
```

---

## Phase 3: Initialize ecosystem.yaml

### Task 4: Create Initial Issues in ecosystem.yaml

**Files:**
- Modify: `settings/ecosystem.yaml`
- Test: Manual verification

**Step 1: Add coordination section to ecosystem.yaml**

```yaml
# settings/ecosystem.yaml - add at end

coordination:
  issues:
    # P0 Issues - Critical
    - id: MHV-001
      title: "asyncio.run() called in sync context"
      description: |
        app.py:707 calls asyncio.run() inside _check_user_repo_permission
        which will fail at runtime when called from async code.
      severity: critical
      priority: P0
      status: pending
      pool: python
      affected_files:
        - mahavishnu/core/app.py
      created_at: 2026-02-20T12:00:00Z
      labels: [async, bug, runtime-error]

    - id: MHV-002
      title: "Missing logger import in unified_orchestrator.py"
      description: |
        Lines 223-225 reference `logger` but it is never imported.
        Will crash when cancel_workflow hits an exception.
      severity: critical
      priority: P0
      status: pending
      pool: python
      affected_files:
        - mahavishnu/core/unified_orchestrator.py
      created_at: 2026-02-20T12:00:00Z
      labels: [bug, import-error]

    - id: MHV-003
      title: "No shutdown events in background loops"
      description: |
        Four background loops lack shutdown events and cannot gracefully stop:
        - resilience.py:705
        - monitoring.py:200
        - memory_aggregator.py:165
        - terminal/pool.py:201
      severity: critical
      priority: P0
      status: pending
      pool: perf
      affected_files:
        - mahavishnu/core/resilience.py
        - mahavishnu/core/monitoring.py
        - mahavishnu/pools/memory_aggregator.py
        - mahavishnu/terminal/pool.py
      created_at: 2026-02-20T12:00:00Z
      labels: [async, shutdown, graceful-stop]

    # P1 Issues - Important
    - id: MHV-004
      title: "N+1 HTTP pattern in batch insert"
      description: |
        memory_aggregator.py:118-147 makes sequential HTTP requests for each
        memory item in a batch. Should use parallel requests or batch endpoint.
      severity: high
      priority: P1
      status: pending
      pool: perf
      affected_files:
        - mahavishnu/pools/memory_aggregator.py
      created_at: 2026-02-20T12:00:00Z
      labels: [performance, http, batch]

    - id: MHV-005
      title: "SSRF vulnerability in content ingestion"
      description: |
        content_ingester.py accepts arbitrary URLs without validation.
        No blocklist for internal IP ranges, cloud metadata, or file:// protocol.
      severity: high
      priority: P1
      status: pending
      pool: security
      affected_files:
        - mahavishnu/ingesters/content_ingester.py
      created_at: 2026-02-20T12:00:00Z
      labels: [security, ssrf, input-validation]

    - id: MHV-006
      title: "Heap synchronization missing in pool manager"
      description: |
        pools/manager.py:185-232 modifies heap and dict without synchronization.
        Could cause race conditions under high concurrency.
      severity: high
      priority: P1
      status: pending
      pool: perf
      affected_files:
        - mahavishnu/pools/manager.py
      created_at: 2026-02-20T12:00:00Z
      labels: [concurrency, race-condition]

    # P2 Issues - Enhancement
    - id: MHV-007
      title: "datetime.utcnow() deprecation"
      description: |
        Python 3.12+ deprecates datetime.utcnow(). Six files use it.
        Should migrate to datetime.now(UTC).
      severity: medium
      priority: P2
      status: pending
      pool: python
      affected_files:
        - mahavishnu/core/dependency_graph.py
        - mahavishnu/core/task_ordering.py
        - mahavishnu/core/pattern_detection.py
        - mahavishnu/core/predictions.py
        - mahavishnu/models/pattern.py
      created_at: 2026-02-20T12:00:00Z
      labels: [deprecation, python-3.12]

    - id: MHV-008
      title: "Status enum proliferation"
      description: |
        20+ status enums with overlapping values (PENDING, IN_PROGRESS, etc).
        Should consolidate to ~4 base enums.
      severity: medium
      priority: P2
      status: pending
      pool: python
      affected_files:
        - mahavishnu/core/task_store.py
        - mahavishnu/core/dependency_graph.py
        - mahavishnu/core/progress_tracker.py
        - mahavishnu/core/coordination/models.py
      created_at: 2026-02-20T12:00:00Z
      labels: [refactoring, deduplication]

  plans:
    - id: PLAN-001
      title: "Phase 1 Critical Fixes"
      description: "Fix all P0 issues before any P1/P2 work"
      issue_ids: [MHV-001, MHV-002, MHV-003]
      status: pending
      created_at: 2026-02-20T12:00:00Z

    - id: PLAN-002
      title: "Phase 2 Performance & Security"
      description: "Address P1 performance and security issues"
      issue_ids: [MHV-004, MHV-005, MHV-006]
      depends_on: [PLAN-001]
      status: pending
      created_at: 2026-02-20T12:00:00Z

    - id: PLAN-003
      title: "Phase 3 Code Quality"
      description: "Address P2 code quality improvements"
      issue_ids: [MHV-007, MHV-008]
      depends_on: [PLAN-002]
      status: pending
      created_at: 2026-02-20T12:00:00Z

  todos:
    - id: TODO-001
      issue_id: MHV-003
      task: "Add shutdown event to resilience.py background loop"
      status: pending
    - id: TODO-002
      issue_id: MHV-003
      task: "Add shutdown event to monitoring.py background loop"
      status: pending
    - id: TODO-003
      issue_id: MHV-003
      task: "Add shutdown event to memory_aggregator.py background loop"
      status: pending
    - id: TODO-004
      issue_id: MHV-003
      task: "Add shutdown event to terminal/pool.py background loop"
      status: pending
```

**Step 2: Verify YAML is valid**

Run: `python -c "import yaml; yaml.safe_load(open('settings/ecosystem.yaml'))"`
Expected: No errors

**Step 3: Commit**

```bash
git add settings/ecosystem.yaml
git commit -m "feat: initialize ecosystem.yaml with review findings"
```

---

## Phase 4: Integration

### Task 5: Register MCP Tools

**Files:**
- Modify: `mahavishnu/mcp/server.py`

**Step 1: Add self-improvement tools to server**

```python
# In mahavishnu/mcp/server.py, add to imports:
from mahavishnu.mcp.tools.self_improvement_tools import SelfImprovementTools, ReviewScope

# In the server setup, register the tools:
@mcp.tool
async def review_and_fix(
    scope: str = "critical",
    auto_fix: bool = False,
    dry_run: bool = False,
) -> dict:
    """Run comprehensive review and optionally fix issues.

    Args:
        scope: Review scope - "critical", "security", "performance", "quality", or "all"
        auto_fix: If True, automatically spawn fix pools for found issues
        dry_run: If True, report findings without making changes

    Returns:
        Dictionary with findings, issues created, and fix results
    """
    tools = SelfImprovementTools(app)
    return await tools.review_and_fix(
        scope=ReviewScope(scope),
        auto_fix=auto_fix,
        dry_run=dry_run,
    )


@mcp.tool
async def request_approval(
    approval_type: str,
    context: dict,
) -> dict:
    """Request manual approval for version bump or publish.

    Args:
        approval_type: "version_bump" or "publish"
        context: Context data for the approval

    Returns:
        Dictionary with approval request details
    """
    tools = SelfImprovementTools(app)
    return await tools.request_approval(approval_type, context)


@mcp.tool
async def respond_to_approval(
    approval_id: str,
    approved: bool,
    selected_option: int | None = None,
    rejection_reason: str | None = None,
) -> dict:
    """Respond to a pending approval request.

    Args:
        approval_id: ID of the approval request
        approved: Whether to approve
        selected_option: Index of selected option (if approved)
        rejection_reason: Reason for rejection (if not approved)

    Returns:
        Dictionary with response result
    """
    tools = SelfImprovementTools(app)
    return await tools.respond_to_approval(
        approval_id=approval_id,
        approved=approved,
        selected_option=selected_option,
        rejection_reason=rejection_reason,
    )


@mcp.tool
async def get_pending_approvals() -> dict:
    """Get all pending approval requests.

    Returns:
        Dictionary with pending approvals list
    """
    tools = SelfImprovementTools(app)
    return await tools.get_pending_approvals()
```

**Step 2: Run quality checks**

Run: `ruff check mahavishnu/mcp/server.py`
Expected: No errors

**Step 3: Commit**

```bash
git add mahavishnu/mcp/server.py
git commit -m "feat: register self-improvement MCP tools"
```

---

## Summary

| Task | Files Created | Files Modified | Tests |
|------|---------------|----------------|-------|
| 1. Approval Manager | 1 | 0 | 1 |
| 2. Fix Orchestrator | 1 | 0 | 1 |
| 3. MCP Tools | 1 | 0 | 1 |
| 4. ecosystem.yaml | 0 | 1 | 0 |
| 5. Server Registration | 0 | 1 | 0 |
| **Total** | **3** | **2** | **3** |

---

## Verification Checklist

After completing all tasks:

- [ ] `pytest tests/unit/test_approval_manager.py -v` passes
- [ ] `pytest tests/unit/test_fix_orchestrator.py -v` passes
- [ ] `pytest tests/unit/test_self_improvement_tools.py -v` passes
- [ ] `ruff check mahavishnu/` passes
- [ ] `mahavishnu mcp start` runs without errors
- [ ] MCP tools registered and callable

---

## Next Steps (Post-Implementation)

1. **Phase 1 Execution:** Use the system to fix MHV-001, MHV-002, MHV-003
2. **WebSocket Integration:** Add real-time approval notifications
3. **Crackerjack Integration:** Connect `_run_quality_gates` to actual API
4. **Session-Buddy:** Add reflection capture after each fix
