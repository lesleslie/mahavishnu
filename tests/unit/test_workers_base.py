# tests/unit/test_workers_base.py
"""Unit tests for mahavishnu.workers.base module."""

from __future__ import annotations

import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.base import BaseWorker, WorkerResult


class TestWorkerResult:
    """Unit tests for WorkerResult dataclass."""

    def test_worker_result_success(self):
        """Test WorkerResult for successful execution."""
        result = WorkerResult(
            worker_id="worker-1",
            status=WorkerStatus.COMPLETED,
            output="Task completed successfully",
            duration_seconds=1.5,
        )

        assert result.worker_id == "worker-1"
        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "Task completed successfully"
        assert result.error is None
        assert result.exit_code is None
        assert result.duration_seconds == 1.5
        assert result.is_success() is True
        assert result.has_output() is True

    def test_worker_result_failure(self):
        """Test WorkerResult for failed execution."""
        result = WorkerResult(
            worker_id="worker-2",
            status=WorkerStatus.FAILED,
            error="Connection refused",
            exit_code=1,
            duration_seconds=0.5,
        )

        assert result.status == WorkerStatus.FAILED
        assert result.output is None
        assert result.error == "Connection refused"
        assert result.exit_code == 1
        assert result.is_success() is False
        assert result.has_output() is False

    def test_worker_result_timeout(self):
        """Test WorkerResult for timed out execution."""
        result = WorkerResult(
            worker_id="worker-timeout",
            status=WorkerStatus.TIMEOUT,
            error="Task timed out after 300 seconds",
        )

        assert result.status == WorkerStatus.TIMEOUT
        assert "timed out" in result.error

    def test_worker_result_to_dict(self):
        """Test WorkerResult serialization to dictionary."""
        result = WorkerResult(
            worker_id="worker-dict",
            status=WorkerStatus.COMPLETED,
            output="output data",
            duration_seconds=2.0,
            metadata={"key": "value"},
        )

        result_dict = result.to_dict()

        assert result_dict["worker_id"] == "worker-dict"
        assert result_dict["status"] == "completed"
        assert result_dict["output"] == "output data"
        assert result_dict["duration_seconds"] == 2.0
        assert result_dict["metadata"] == {"key": "value"}
        assert result.timestamp is not None

    def test_worker_result_from_dict(self):
        """Test WorkerResult deserialization from dictionary."""
        data = {
            "worker_id": "worker-parse",
            "status": "completed",
            "output": "parsed output",
            "duration_seconds": 3.0,
            "metadata": {"parsed": True},
        }

        result = WorkerResult.from_dict(data)

        assert result.worker_id == "worker-parse"
        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "parsed output"
        assert result.duration_seconds == 3.0
        assert result.metadata == {"parsed": True}

    def test_worker_result_from_dict_with_string_status(self):
        """Test WorkerResult handles string status in from_dict."""
        data = {
            "worker_id": "worker-str-status",
            "status": "failed",
        }

        result = WorkerResult.from_dict(data)
        assert result.status == WorkerStatus.FAILED

    def test_worker_result_get_summary_success(self):
        """Test WorkerResult summary generation for success."""
        result = WorkerResult(
            worker_id="worker-summary",
            status=WorkerStatus.COMPLETED,
            output="Short output",
        )

        summary = result.get_summary()
        assert "worker-summary" in summary
        # Check for the checkmark emoji since "completed" isn't in the lowercased output
        assert "✅" in summary

    def test_worker_result_get_summary_failure(self):
        """Test WorkerResult summary generation for failure."""
        result = WorkerResult(
            worker_id="worker-fail",
            status=WorkerStatus.FAILED,
            error="Something went wrong",
        )

        summary = result.get_summary()
        assert "worker-fail" in summary
        # Failure uses X emoji
        assert "❌" in summary

    def test_worker_result_empty_output(self):
        """Test WorkerResult with empty output string."""
        result = WorkerResult(
            worker_id="worker-empty",
            status=WorkerStatus.COMPLETED,
            output="",
        )

        assert result.has_output() is False  # Empty string is falsy

    def test_worker_result_with_metadata(self):
        """Test WorkerResult with rich metadata."""
        result = WorkerResult(
            worker_id="worker-meta",
            status=WorkerStatus.COMPLETED,
            metadata={
                "model": "MiniMax-M2.7",
                "tokens_used": 1500,
                "latency_ms": 450,
            },
        )

        assert result.metadata["model"] == "MiniMax-M2.7"
        assert result.metadata["tokens_used"] == 1500

    def test_worker_result_pending_status(self):
        """Test WorkerResult with PENDING status."""
        result = WorkerResult(
            worker_id="worker-pending",
            status=WorkerStatus.PENDING,
        )

        assert result.status == WorkerStatus.PENDING
        assert result.is_success() is False

    def test_worker_result_cancelled_status(self):
        """Test WorkerResult with CANCELLED status."""
        result = WorkerResult(
            worker_id="worker-cancelled",
            status=WorkerStatus.CANCELLED,
            error="User cancelled",
        )

        assert result.status == WorkerStatus.CANCELLED


class TestBaseWorker:
    """Unit tests for BaseWorker abstract class."""

    def test_base_worker_is_abc(self):
        """Test that BaseWorker is an abstract base class."""
        assert issubclass(BaseWorker, __import__("abc").ABC)

    def test_base_worker_has_required_abstract_methods(self):
        """Test that BaseWorker defines required abstract methods."""

        # These are the 5 abstract methods defined in BaseWorker
        required_methods = [
            "start",
            "execute",
            "stop",
            "status",
            "get_progress",
        ]

        for method_name in required_methods:
            method = getattr(BaseWorker, method_name, None)
            assert method is not None, f"Missing method: {method_name}"
            # Check if it's marked as abstract
            assert getattr(method, "__isabstractmethod__", False), (
                f"Method {method_name} should be abstract"
            )

    def test_base_worker_instantiation_fails(self):
        """Test that BaseWorker cannot be instantiated directly."""
        with pytest.raises(TypeError, match="abstract"):
            BaseWorker(worker_type="test")

    def test_base_worker_init_sets_type(self):
        """Test that BaseWorker.__init__ sets worker_type via direct assignment."""

        # Create a minimal concrete subclass for this test
        class ConcreteWorker(BaseWorker):
            async def start(self) -> str:
                return "test-id"

            async def execute(self, task):
                pass

            async def stop(self) -> None:
                pass

            async def status(self) -> WorkerStatus:
                return WorkerStatus.PENDING

            async def get_progress(self) -> dict:
                return {}

        worker = ConcreteWorker(worker_type="cloud")
        assert worker.worker_type == "cloud"
