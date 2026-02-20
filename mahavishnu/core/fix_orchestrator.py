"""Orchestrates fix execution with quality gates and approval workflow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mahavishnu.core.approval_manager import ApprovalManager
    from mahavishnu.core.coordination.manager import CoordinationManager
    from mahavishnu.pools.manager import PoolManager


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
            stage = "fast_hooks" if not quality_result.fast_hooks else "tests"
            return FixResult(
                success=False,
                stage=stage,
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
        for result in results:
            if isinstance(result, Exception):
                final_results.append(
                    FixResult(
                        success=False,
                        stage="execution",
                        error_message=str(result),
                    )
                )
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
        """Update issue status after fix.

        Args:
            issue_id: ID of the issue to update.
            execution_result: Result from pool execution.
            quality_result: Result from quality gates.
        """
        # TODO: Implement with actual CoordinationManager
        pass
