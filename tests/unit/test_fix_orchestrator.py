"""Tests for the fix orchestrator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.fix_orchestrator import (
    FixOrchestrator,
    FixResult,
    FixTask,
    QualityGateResult,
)


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

    def test_create_fix_task_with_defaults(self) -> None:
        """Test creating a fix task with default values."""
        task = FixTask(
            issue_id="MHV-002",
            pool_type="python",
            prompt="Fix another issue",
        )

        assert task.issue_id == "MHV-002"
        assert task.affected_files == []


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

    def test_to_dict(self) -> None:
        """Test converting to dictionary."""
        result = QualityGateResult(
            fast_hooks=True,
            tests=True,
            comprehensive=False,
            coverage=90.5,
            errors=["mypy warning"],
        )

        d = result.to_dict()

        assert d["fast_hooks"] is True
        assert d["tests"] is True
        assert d["comprehensive"] is False
        assert d["coverage"] == 90.5
        assert d["all_passed"] is False
        assert d["blocking_failure"] is False
        assert d["errors"] == ["mypy warning"]


class TestFixResult:
    """Test FixResult model."""

    def test_success_result(self) -> None:
        """Test successful fix result."""
        result = FixResult(
            success=True,
            stage="complete",
            changes=["app.py:707", "config.py:42"],
            worker_id="worker-001",
        )

        assert result.success is True
        assert result.stage == "complete"
        assert len(result.changes) == 2
        assert result.worker_id == "worker-001"
        assert result.error_message == ""

    def test_failure_result(self) -> None:
        """Test failed fix result."""
        result = FixResult(
            success=False,
            stage="execution",
            error_message="Worker crashed",
        )

        assert result.success is False
        assert result.stage == "execution"
        assert "Worker crashed" in result.error_message


class TestFixOrchestrator:
    """Test FixOrchestrator class."""

    @pytest.fixture
    def mock_pool_manager(self) -> MagicMock:
        """Create mock pool manager."""
        manager = MagicMock()
        manager.execute_on_pool = AsyncMock(
            return_value={
                "success": True,
                "worker_id": "worker-001",
                "changes": ["app.py:707"],
            }
        )
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

    @pytest.mark.asyncio
    async def test_execute_batch_handles_exceptions(
        self,
        orchestrator: FixOrchestrator,
        mock_pool_manager: MagicMock,
    ) -> None:
        """Test batch execution handles exceptions gracefully."""
        tasks = [
            FixTask(issue_id="MHV-010", pool_type="python", prompt="Fix 1", affected_files=[]),
            FixTask(issue_id="MHV-011", pool_type="python", prompt="Fix 2", affected_files=[]),
        ]

        call_count = 0

        async def side_effect(pool_id: str, task: FixTask) -> FixResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Unexpected error")
            return FixResult(success=True, stage="complete")

        with patch.object(orchestrator, "execute_fix", side_effect=side_effect):
            results = await orchestrator.execute_batch("pool-001", tasks)

        assert len(results) == 2
        assert results[0].success is False
        assert results[0].stage == "execution"
        assert "Unexpected error" in results[0].error_message
        assert results[1].success is True

    @pytest.mark.asyncio
    async def test_execute_fix_tests_failure(
        self,
        orchestrator: FixOrchestrator,
        mock_pool_manager: MagicMock,
    ) -> None:
        """Test fix execution when tests fail."""
        task = FixTask(
            issue_id="MHV-004",
            pool_type="python",
            prompt="Fix the issue",
            affected_files=["app.py"],
        )

        with patch.object(orchestrator, "_run_quality_gates") as mock_gates:
            mock_gates.return_value = QualityGateResult(
                fast_hooks=True,
                tests=False,
                comprehensive=True,
                coverage=65.0,
                errors=["3 tests failed"],
            )

            result = await orchestrator.execute_fix("pool-001", task)

        assert result.success is False
        assert result.stage == "tests"
        assert result.quality_gates is not None
        assert result.quality_gates.errors == ["3 tests failed"]
