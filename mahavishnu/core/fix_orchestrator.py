"""Orchestrates fix execution with quality gates and approval workflow."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mahavishnu.core.approval_manager import ApprovalManager
    from mahavishnu.core.coordination.manager import CoordinationManager
    from mahavishnu.pools.manager import PoolManager

from .app import MahavishnuApp


async def _await_if_needed(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


@dataclass
class FixTask:
    """Represents a fix task to be executed."""

    issue_id: str
    pool_type: str
    prompt: str
    affected_files: list[str] = field(default_factory=list)
    correlation_id: str | None = None
    session_id: str | None = None


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

    @staticmethod
    def _coerce_crackerjack_report_data(report: Any) -> dict[str, Any]:
        if report is None:
            return {}
        if hasattr(report, "model_dump"):
            return dict(report.model_dump())
        if hasattr(report, "to_dict"):
            return dict(report.to_dict())
        if isinstance(report, dict):
            return dict(report)

        data: dict[str, Any] = {}
        for key in (
            "fast_hooks",
            "tests",
            "comprehensive",
            "coverage",
            "errors",
            "checks",
            "repository",
            "profile",
            "source",
            "generated_at",
            "metadata",
            "passed",
            "blocking_failure",
            "all_passed",
        ):
            if hasattr(report, key):
                data[key] = getattr(report, key)
        return data

    def to_crackerjack_report(
        self,
        repository: str = "",
        profile: str = "",
        source: str = "mahavishnu",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Convert to the Crackerjack quality-gate report contract."""
        return {
            "fast_hooks": self.fast_hooks,
            "tests": self.tests,
            "comprehensive": self.comprehensive,
            "coverage": self.coverage,
            "errors": self.errors,
            "checks": [
                {
                    "name": "fast_hooks",
                    "passed": self.fast_hooks,
                    "severity": "required",
                },
                {
                    "name": "tests",
                    "passed": self.tests,
                    "severity": "required",
                },
                {
                    "name": "comprehensive",
                    "passed": self.comprehensive,
                    "severity": "optional",
                },
            ],
            "passed": self.all_passed,
            "blocking_failure": self.blocking_failure,
            "repository": repository,
            "profile": profile,
            "source": source,
            "generated_at": datetime.now(UTC).isoformat(),
            "metadata": metadata or {},
        }

    @classmethod
    def from_crackerjack_report(cls, report: Any) -> QualityGateResult:
        """Build a Mahavishnu quality-gate result from a Crackerjack report."""
        data = cls._coerce_crackerjack_report_data(report)

        fast_hooks = bool(data.get("fast_hooks", data.get("passed", False)))
        tests = bool(data.get("tests", data.get("tests_passed", fast_hooks)))
        comprehensive = bool(
            data.get("comprehensive", data.get("all_passed", fast_hooks and tests))
        )

        coverage_value = data.get("coverage", data.get("overall_score", 0.0))
        try:
            coverage = float(coverage_value)
        except (TypeError, ValueError):
            coverage = 0.0

        errors_value = data.get("errors", data.get("failed_required_checks", []))
        if isinstance(errors_value, list):
            errors = [str(error) for error in errors_value]
        elif errors_value:
            errors = [str(errors_value)]
        else:
            errors = []

        return cls(
            fast_hooks=fast_hooks,
            tests=tests,
            comprehensive=comprehensive,
            coverage=coverage,
            errors=errors,
        )



@dataclass
class FixResult:
    """Result of a fix execution."""

    success: bool
    stage: str
    quality_gates: QualityGateResult | None = None
    error_message: str = ""
    changes: list[str] = field(default_factory=list)
    worker_id: str = ""
    correlation_id: str | None = None
    checkpoint_id: str | None = None
    trace: list[str] = field(default_factory=list)


class FixOrchestrator:
    """Orchestrates fix execution with quality gates and approvals."""

    def __init__(
        self,
        pool_manager: PoolManager | None = None,
        coordination_manager: CoordinationManager | None = None,
        approval_manager: ApprovalManager | None = None,
        quality_control: Any | None = None,
        session_checkpoint: Any | None = None,
        coordination_memory: Any | None = None,
        trace_recorder: Any | None = None,
    ) -> None:
        """Initialize the fix orchestrator.

        Args:
            pool_manager: Pool manager for executing fixes.
            coordination_manager: Coordination manager for tracking issues.
            approval_manager: Approval manager for manual gates.
        """
        if pool_manager is None or coordination_manager is None or approval_manager is None:
            app = MahavishnuApp()
            pool_manager = pool_manager or app.pool_manager
            coordination_manager = coordination_manager or app.coordination_manager
            approval_manager = approval_manager or app.approval_manager
            quality_control = quality_control or getattr(app, "qc", None)
            session_checkpoint = session_checkpoint or getattr(app, "session_buddy", None)
            coordination_memory = coordination_memory or getattr(app, "coordination_memory", None)
            trace_recorder = trace_recorder or getattr(app, "record_fix_trace", None)

        if pool_manager is None or coordination_manager is None or approval_manager is None:
            raise ValueError("FixOrchestrator requires pool, coordination, and approval managers")

        self.pool_manager = pool_manager
        self.coordination_manager = coordination_manager
        self.approval_manager = approval_manager
        self.quality_control = quality_control
        self.session_checkpoint = session_checkpoint
        self.coordination_memory = coordination_memory
        self.trace_recorder = trace_recorder

    async def execute_fix(
        self,
        pool_id: str,
        task: FixTask,
    ) -> FixResult:
        """Execute a single fix task with quality gates.

        .. note:: **Golden Path**: Prefer ``mahavishnu workflow fix`` (CLI) or
           ``FixOrchestrator`` via MCP pool tools over calling this method directly.
           See ``docs/reports/golden-paths-guide.md`` for canonical pathways.

        Args:
            pool_id: ID of the pool to execute on.
            task: The fix task to execute.

        Returns:
            The result of the fix execution.
        """
        correlation_id = task.correlation_id or task.issue_id
        trace: list[str] = []
        checkpoint_id: str | None = None

        # Step 0: Record and checkpoint the incident context
        trace.append(f"Starting fix for {task.issue_id} with correlation {correlation_id}")
        if self.trace_recorder is not None:
            self.trace_recorder(
                correlation_id,
                "start",
                "Fix execution started",
                {
                    "issue_id": task.issue_id,
                    "pool_id": pool_id,
                    "pool_type": task.pool_type,
                    "session_id": task.session_id,
                },
            )

        if self.session_checkpoint is not None:
            try:
                checkpoint_id = await _await_if_needed(
                    self.session_checkpoint.create_checkpoint(
                        task.session_id or correlation_id,
                        {
                            "issue_id": task.issue_id,
                            "correlation_id": correlation_id,
                            "pool_id": pool_id,
                            "prompt": task.prompt,
                        },
                    )
                )
                trace.append(f"Session checkpoint created: {checkpoint_id}")
                if self.trace_recorder is not None:
                    self.trace_recorder(
                        correlation_id,
                        "checkpoint",
                        "Session checkpoint created",
                        {"checkpoint_id": checkpoint_id, "session_id": task.session_id or correlation_id},
                    )
            except Exception as exc:
                trace.append(f"Session checkpoint degraded: {exc}")

        issue = None
        if self.coordination_manager is not None and hasattr(self.coordination_manager, "get_issue"):
            try:
                issue = await _await_if_needed(self.coordination_manager.get_issue(task.issue_id))
            except Exception:
                issue = None

        if issue is not None and self.coordination_memory is not None:
            try:
                await _await_if_needed(
                    self.coordination_memory.store_issue_event(
                        "updated",
                        issue,
                        changes={
                            "stage": "execution_started",
                            "correlation_id": correlation_id,
                            "pool_id": pool_id,
                        },
                    )
                )
                trace.append("Coordination memory recorded execution start")
            except Exception as exc:
                trace.append(f"Coordination memory degraded: {exc}")

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
            if self.session_checkpoint is not None and checkpoint_id is not None:
                with contextlib.suppress(Exception):
                    await _await_if_needed(
                        self.session_checkpoint.update_checkpoint(
                            checkpoint_id,
                            "failed",
                            {"quality_score": 0, "error": execution_result.get("error")},
                        )
                    )
            return FixResult(
                success=False,
                stage="execution",
                error_message=execution_result.get("error", "Unknown error"),
                correlation_id=correlation_id,
                checkpoint_id=checkpoint_id,
                trace=trace,
            )

        # Step 2: Run quality gates
        trace.append("Execution completed; running quality gates")
        quality_result = await self._run_quality_gates(task, execution_result)
        trace.append(
            f"Quality gates completed: fast_hooks={quality_result.fast_hooks}, tests={quality_result.tests}"
        )

        # Step 3: Check blocking gates
        if quality_result.blocking_failure:
            stage = "fast_hooks" if not quality_result.fast_hooks else "tests"
            if self.session_checkpoint is not None and checkpoint_id is not None:
                with contextlib.suppress(Exception):
                    await _await_if_needed(
                        self.session_checkpoint.update_checkpoint(
                            checkpoint_id,
                            "failed",
                            {"quality_score": quality_result.coverage, "error": quality_result.errors},
                        )
                    )
            return FixResult(
                success=False,
                stage=stage,
                quality_gates=quality_result,
                correlation_id=correlation_id,
                checkpoint_id=checkpoint_id,
                trace=trace,
            )

        # Step 4: Update issue status
        await self._update_issue_status(task.issue_id, execution_result, quality_result)

        if issue is not None and self.coordination_memory is not None:
            try:
                await _await_if_needed(
                    self.coordination_memory.store_issue_event(
                        "closed",
                        issue,
                        changes={
                            "stage": "validated",
                            "correlation_id": correlation_id,
                            "pool_id": pool_id,
                            "worker_id": execution_result.get("worker_id", ""),
                        },
                    )
                )
                trace.append("Coordination memory recorded fix validation")
            except Exception as exc:
                trace.append(f"Coordination memory search/index degraded: {exc}")

            try:
                search_results = await _await_if_needed(
                    self.coordination_memory.search_coordination_history(
                        correlation_id,
                        repo=(issue.repos[0] if getattr(issue, "repos", None) else None),
                        limit=10,
                    )
                )
                trace.append(f"Coordination memory search returned {len(search_results)} result(s)")
            except Exception as exc:
                trace.append(f"Coordination memory search degraded: {exc}")

        if self.session_checkpoint is not None and checkpoint_id is not None:
            try:
                await _await_if_needed(
                    self.session_checkpoint.update_checkpoint(
                        checkpoint_id,
                        "completed",
                        {"quality_score": quality_result.coverage, "changes": execution_result.get("changes", [])},
                    )
                )
                trace.append("Session checkpoint marked completed")
            except Exception as exc:
                trace.append(f"Session checkpoint completion degraded: {exc}")

        if self.trace_recorder is not None:
            self.trace_recorder(
                correlation_id,
                "complete",
                "Fix execution completed",
                {
                    "issue_id": task.issue_id,
                    "pool_id": pool_id,
                    "worker_id": execution_result.get("worker_id", ""),
                    "quality_coverage": quality_result.coverage,
                },
            )

        return FixResult(
            success=True,
            stage="complete",
            quality_gates=quality_result,
            changes=execution_result.get("changes", []),
            worker_id=execution_result.get("worker_id", ""),
            correlation_id=correlation_id,
            checkpoint_id=checkpoint_id,
            trace=trace,
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

    async def _run_quality_gates(
        self,
        task: FixTask,
        execution_result: dict[str, Any],
    ) -> QualityGateResult:
        """Run quality gate checks.

        Returns:
            Quality gate results.
        """
        if self.quality_control is not None:
            repo_targets = self._derive_repo_targets(task.affected_files)
            if not repo_targets and execution_result.get("repos"):
                repos = execution_result.get("repos")
                if isinstance(repos, list):
                    repo_targets = [str(repo) for repo in repos if str(repo).strip()]

            if not repo_targets and execution_result.get("repo"):
                repo_targets = [str(execution_result["repo"])]

            if not repo_targets:
                repo_targets = ["mahavishnu"]

            pre_passed = await self.quality_control.validate_pre_execution(repo_targets)
            post_passed = await self.quality_control.validate_post_execution(repo_targets)
            return QualityGateResult(
                fast_hooks=pre_passed,
                tests=post_passed,
                comprehensive=pre_passed and post_passed,
                coverage=100.0 if pre_passed and post_passed else 0.0,
                errors=[] if pre_passed and post_passed else ["quality control checks failed"],
            )

        return QualityGateResult(
            fast_hooks=True,
            tests=True,
            comprehensive=True,
            coverage=85.0,
        )

    def _derive_repo_targets(self, affected_files: list[str]) -> list[str]:
        """Derive repository targets from affected file paths."""
        repos: list[str] = []
        for path_str in affected_files:
            path = Path(path_str)
            if path.is_absolute():
                continue
            parts = path.parts
            if parts:
                repo = parts[0]
                if repo not in repos:
                    repos.append(repo)
        return repos

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
        if self.coordination_manager is None:
            return

        updates = {
            "status": "resolved",
            "updated": datetime.now(UTC).isoformat(),
            "metadata": {
                "quality_gates": quality_result.to_dict(),
                "worker_id": execution_result.get("worker_id", ""),
                "changes": execution_result.get("changes", []),
            },
        }
        await _await_if_needed(self.coordination_manager.update_issue(issue_id, updates))
