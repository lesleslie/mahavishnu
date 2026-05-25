"""Tests for load_test module."""

from __future__ import annotations

import asyncio
from io import StringIO
import sys

import pytest

from mahavishnu.testing.load_test import (
    LoadTestConfig,
    LoadTestMetrics,
    LoadTestPhase,
    LoadTestRunner,
    MockTaskClient,
    RequestResult,
    print_report,
)


class TestLoadTestPhase:
    """Tests for LoadTestPhase enum."""

    def test_all_five_values_exist(self):
        """Test all 5 phase values are defined."""
        assert LoadTestPhase.WARMUP.value == "warmup"
        assert LoadTestPhase.RAMP_UP.value == "ramp_up"
        assert LoadTestPhase.STEADY_STATE.value == "steady_state"
        assert LoadTestPhase.RAMP_DOWN.value == "ramp_down"
        assert LoadTestPhase.COMPLETE.value == "complete"

    def test_count(self):
        """Test exactly 5 phases."""
        assert len(list(LoadTestPhase)) == 5

    def test_values_are_strings(self):
        """Test values are string-based (StrEnum)."""
        for phase in LoadTestPhase:
            assert isinstance(phase.value, str)


class TestRequestResult:
    """Tests for RequestResult dataclass."""

    def test_field_access(self):
        """Test RequestResult fields can be accessed."""
        result = RequestResult(
            timestamp=1000.0,
            operation="create_task",
            latency_ms=45.5,
            success=True,
            status_code=201,
            error=None,
        )
        assert result.timestamp == 1000.0
        assert result.operation == "create_task"
        assert result.latency_ms == 45.5
        assert result.success is True
        assert result.status_code == 201
        assert result.error is None

    def test_default_values(self):
        """Test RequestResult default values."""
        result = RequestResult(
            timestamp=1000.0,
            operation="get_task",
            latency_ms=10.0,
            success=False,
        )
        assert result.status_code == 200  # default
        assert result.error is None  # default

    def test_error_field(self):
        """Test RequestResult with error."""
        result = RequestResult(
            timestamp=1000.0,
            operation="create_task",
            latency_ms=0,
            success=False,
            status_code=500,
            error="Internal server error",
        )
        assert result.success is False
        assert result.error == "Internal server error"


class TestLoadTestMetrics:
    """Tests for LoadTestMetrics dataclass."""

    def test_add_result_success(self):
        """Test add_result increments counters for success."""
        metrics = LoadTestMetrics(operation="create_task")
        result = RequestResult(
            timestamp=1000.0,
            operation="create_task",
            latency_ms=45.0,
            success=True,
        )
        metrics.add_result(result)

        assert metrics.total_requests == 1
        assert metrics.successful_requests == 1
        assert metrics.failed_requests == 0
        assert 45.0 in metrics.latencies

    def test_add_result_failure(self):
        """Test add_result increments counters for failure."""
        metrics = LoadTestMetrics(operation="create_task")
        result = RequestResult(
            timestamp=1000.0,
            operation="create_task",
            latency_ms=0,
            success=False,
            error="Timeout",
        )
        metrics.add_result(result)

        assert metrics.total_requests == 1
        assert metrics.successful_requests == 0
        assert metrics.failed_requests == 1
        assert len(metrics.latencies) == 0

    def test_calculate_empty(self):
        """Test calculate handles empty latencies."""
        metrics = LoadTestMetrics(operation="create_task")
        metrics.calculate(60.0)

        assert metrics.p50_ms == 0.0
        assert metrics.p95_ms == 0.0
        assert metrics.p99_ms == 0.0

    def test_calculate_percentiles(self):
        """Test calculate computes percentiles correctly."""
        metrics = LoadTestMetrics(operation="create_task")

        # Add 100 results with latencies 1-100
        for i in range(1, 101):
            result = RequestResult(
                timestamp=float(i),
                operation="create_task",
                latency_ms=float(i),
                success=True,
            )
            metrics.add_result(result)

        metrics.calculate(60.0)

        # Percentiles use int(n * p), so for 100 items:
        # p50 = index 50 (0-indexed) = 51.0
        # p95 = index 95 = 96.0
        # p99 = index 99 = 100.0
        assert metrics.p50_ms == 51.0
        assert metrics.p95_ms == 96.0
        assert metrics.p99_ms == 100.0

    def test_calculate_success_rate(self):
        """Test calculate computes success rate."""
        metrics = LoadTestMetrics(operation="create_task")

        # 80 successes, 20 failures
        for i in range(80):
            result = RequestResult(
                timestamp=float(i),
                operation="create_task",
                latency_ms=10.0,
                success=True,
            )
            metrics.add_result(result)

        for i in range(80, 100):
            result = RequestResult(
                timestamp=float(i),
                operation="create_task",
                latency_ms=0,
                success=False,
            )
            metrics.add_result(result)

        metrics.calculate(60.0)
        assert metrics.success_rate == 80.0

    def test_calculate_throughput(self):
        """Test calculate computes requests per second."""
        metrics = LoadTestMetrics(operation="create_task")

        for i in range(60):
            result = RequestResult(
                timestamp=float(i),
                operation="create_task",
                latency_ms=10.0,
                success=True,
            )
            metrics.add_result(result)

        metrics.calculate(60.0)
        assert metrics.requests_per_second == 1.0

    def test_to_dict(self):
        """Test to_dict returns correct structure."""
        metrics = LoadTestMetrics(operation="create_task")
        result = RequestResult(
            timestamp=1000.0,
            operation="create_task",
            latency_ms=50.0,
            success=True,
        )
        metrics.add_result(result)
        metrics.calculate(1.0)

        result_dict = metrics.to_dict()

        assert result_dict["operation"] == "create_task"
        assert result_dict["total_requests"] == 1
        assert result_dict["successful_requests"] == 1
        assert result_dict["failed_requests"] == 0
        assert result_dict["p50_ms"] == 50.0
        assert result_dict["p95_ms"] == 50.0
        assert result_dict["p99_ms"] == 50.0
        assert result_dict["min_ms"] == 50.0
        assert result_dict["max_ms"] == 50.0
        assert result_dict["avg_ms"] == 50.0
        assert result_dict["success_rate"] == 100.0
        assert result_dict["requests_per_second"] == 1.0

    def test_to_dict_rounds_values(self):
        """Test to_dict rounds float values."""
        metrics = LoadTestMetrics(operation="create_task")
        result = RequestResult(
            timestamp=1000.0,
            operation="create_task",
            latency_ms=33.333333,
            success=True,
        )
        metrics.add_result(result)
        metrics.calculate(1.0)

        result_dict = metrics.to_dict()
        assert result_dict["p50_ms"] == 33.33
        assert result_dict["avg_ms"] == 33.33


class TestLoadTestConfig:
    """Tests for LoadTestConfig dataclass."""

    def test_default_values(self):
        """Test LoadTestConfig default values."""
        config = LoadTestConfig()

        assert config.concurrent_users == 50
        assert config.duration_seconds == 60
        assert config.ramp_up_seconds == 10
        assert config.requests_per_user_per_second == 1.0
        assert config.base_url == "http://localhost:8690"
        assert config.api_prefix == "/api/v1"
        assert config.task_create_p99_ms == 500.0
        assert config.task_query_p99_ms == 200.0
        assert config.min_success_rate == 99.0
        assert config.output_file is None

    def test_custom_values(self):
        """Test LoadTestConfig with custom values."""
        config = LoadTestConfig(
            concurrent_users=100,
            duration_seconds=120,
            ramp_up_seconds=20,
            requests_per_user_per_second=2.0,
            base_url="http://localhost:9000",
            api_prefix="/api/v2",
            task_create_p99_ms=1000.0,
            task_query_p99_ms=500.0,
            min_success_rate=95.0,
            output_file="/tmp/report.json",
        )

        assert config.concurrent_users == 100
        assert config.duration_seconds == 120
        assert config.ramp_up_seconds == 20
        assert config.requests_per_user_per_second == 2.0
        assert config.base_url == "http://localhost:9000"
        assert config.api_prefix == "/api/v2"
        assert config.task_create_p99_ms == 1000.0
        assert config.task_query_p99_ms == 500.0
        assert config.min_success_rate == 95.0
        assert config.output_file == "/tmp/report.json"


class TestMockTaskClient:
    """Tests for MockTaskClient class."""

    @pytest.mark.asyncio
    async def test_create_task(self):
        """Test create_task returns RequestResult."""
        config = LoadTestConfig()
        client = MockTaskClient(config)

        result = await client.create_task("Test Task", "test-repo")

        assert isinstance(result, RequestResult)
        assert result.operation == "create_task"
        assert result.success is True
        assert result.status_code == 201
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_create_task_increments_counter(self):
        """Test create_task increments internal counter."""
        config = LoadTestConfig()
        client = MockTaskClient(config)

        await client.create_task("Task 1", "repo")
        await client.create_task("Task 2", "repo")

        assert client._task_counter == 2

    @pytest.mark.asyncio
    async def test_get_task_existing(self):
        """Test get_task returns success for existing task."""
        config = LoadTestConfig()
        client = MockTaskClient(config)

        # Create a task first
        create_result = await client.create_task("Test Task", "test-repo")
        task_id = client._task_counter

        # Get the task
        get_result = await client.get_task(task_id)

        assert get_result.success is True
        assert get_result.status_code == 200

    @pytest.mark.asyncio
    async def test_get_task_nonexistent(self):
        """Test get_task returns failure for nonexistent task."""
        config = LoadTestConfig()
        client = MockTaskClient(config)

        result = await client.get_task(999)

        assert result.success is False
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_list_tasks(self):
        """Test list_tasks returns RequestResult."""
        config = LoadTestConfig()
        client = MockTaskClient(config)

        result = await client.list_tasks()

        assert isinstance(result, RequestResult)
        assert result.operation == "list_tasks"
        assert result.success is True
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_update_task_existing(self):
        """Test update_task succeeds for existing task."""
        config = LoadTestConfig()
        client = MockTaskClient(config)

        # Create a task first
        await client.create_task("Test Task", "test-repo")
        task_id = client._task_counter

        # Update the task
        result = await client.update_task(task_id, status="in_progress")

        assert result.success is True
        assert result.status_code == 200
        assert client._tasks[task_id]["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_update_task_nonexistent(self):
        """Test update_task fails for nonexistent task."""
        config = LoadTestConfig()
        client = MockTaskClient(config)

        result = await client.update_task(999, status="in_progress")

        assert result.success is False
        assert result.status_code == 404


class TestLoadTestRunner:
    """Tests for LoadTestRunner class."""

    @pytest.mark.asyncio
    async def test_run_short_duration(self):
        """Test run() completes with short duration."""
        config = LoadTestConfig(
            concurrent_users=2,
            duration_seconds=1,  # Very short for tests
            requests_per_user_per_second=1.0,
        )
        runner = LoadTestRunner(config)

        report = await runner.run()

        assert "config" in report
        assert "summary" in report
        assert "operations" in report
        assert "slo_validation" in report
        assert report["config"]["concurrent_users"] == 2
        assert report["config"]["duration_seconds"] == 1
        assert report["summary"]["total_duration_seconds"] > 0

    @pytest.mark.asyncio
    async def test_run_records_results(self):
        """Test run() records request results."""
        config = LoadTestConfig(
            concurrent_users=2,
            duration_seconds=1,
            requests_per_user_per_second=1.0,
        )
        runner = LoadTestRunner(config)

        await runner.run()

        assert len(runner.results) > 0
        assert all(isinstance(r, RequestResult) for r in runner.results)

    @pytest.mark.asyncio
    async def test_run_calculates_metrics(self):
        """Test run() calculates metrics per operation."""
        config = LoadTestConfig(
            concurrent_users=2,
            duration_seconds=1,
            requests_per_user_per_second=1.0,
        )
        runner = LoadTestRunner(config)

        await runner.run()

        for name, metrics in runner.metrics.items():
            assert isinstance(metrics, LoadTestMetrics)
            assert metrics.total_requests > 0

    def test_validate_slos_passes_when_under_threshold(self):
        """Test _validate_slos passes when under SLO threshold."""
        config = LoadTestConfig(
            concurrent_users=1,
            duration_seconds=1,
            task_create_p99_ms=1000.0,  # High threshold
        )
        runner = LoadTestRunner(config)

        # Manually add metrics with low latency
        metrics = LoadTestMetrics(operation="create_task")
        for _ in range(10):
            metrics.add_result(
                RequestResult(
                    timestamp=1000.0,
                    operation="create_task",
                    latency_ms=50.0,
                    success=True,
                )
            )
        metrics.calculate(1.0)
        runner.metrics["create_task"] = metrics

        validation = runner._validate_slos()

        assert validation["passed"] is True

    def test_validate_slos_fails_when_over_threshold(self):
        """Test _validate_slos fails when over SLO threshold."""
        config = LoadTestConfig(
            concurrent_users=1,
            duration_seconds=1,
            task_create_p99_ms=10.0,  # Very low threshold
        )
        runner = LoadTestRunner(config)

        # Add metrics with high latency
        metrics = LoadTestMetrics(operation="create_task")
        for _ in range(10):
            metrics.add_result(
                RequestResult(
                    timestamp=1000.0,
                    operation="create_task",
                    latency_ms=100.0,  # High latency
                    success=True,
                )
            )
        metrics.calculate(1.0)
        runner.metrics["create_task"] = metrics

        validation = runner._validate_slos()

        assert validation["passed"] is False

    def test_validate_slos_checks_success_rate(self):
        """Test _validate_slos checks success rate SLO."""
        config = LoadTestConfig(
            concurrent_users=1,
            duration_seconds=1,
            min_success_rate=95.0,
        )
        runner = LoadTestRunner(config)

        # Add metrics with low success rate
        metrics = LoadTestMetrics(operation="create_task")
        for i in range(20):
            metrics.add_result(
                RequestResult(
                    timestamp=float(i),
                    operation="create_task",
                    latency_ms=50.0,
                    success=i < 10,  # Only 50% success
                )
            )
        metrics.calculate(1.0)
        runner.metrics["create_task"] = metrics

        validation = runner._validate_slos()

        assert validation["passed"] is False
        success_check = next(
            c for c in validation["checks"] if "success_rate" in c["name"]
        )
        assert success_check["passed"] is False


class TestPrintReport:
    """Tests for print_report function."""

    def test_print_report_outputs_to_stdout(self):
        """Test print_report writes to stdout."""
        report = {
            "config": {
                "concurrent_users": 50,
                "duration_seconds": 60,
                "ramp_up_seconds": 10,
                "requests_per_user_per_second": 1.0,
            },
            "summary": {
                "total_duration_seconds": 60.0,
                "total_requests": 100,
                "successful_requests": 99,
                "failed_requests": 1,
                "requests_per_second": 1.67,
            },
            "operations": {
                "create_task": {
                    "p50_ms": 45.0,
                    "p95_ms": 80.0,
                    "p99_ms": 100.0,
                    "avg_ms": 50.0,
                    "success_rate": 99.0,
                }
            },
            "slo_validation": {
                "passed": True,
                "checks": [
                    {
                        "name": "task_creation_p99",
                        "target_ms": 500.0,
                        "actual_ms": 100.0,
                        "passed": True,
                    },
                    {
                        "name": "create_task_success_rate",
                        "target_percent": 99.0,
                        "actual_percent": 99.0,
                        "passed": True,
                    },
                ],
            },
        }

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            print_report(report)
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        assert "LOAD TEST REPORT" in output
        assert "50" in output
        assert "60" in output
        assert "100" in output
        assert "99" in output
        assert "1" in output
        assert "PASSED" in output

    def test_print_report_shows_failed_status(self):
        """Test print_report shows FAILED when SLO validation fails."""
        report = {
            "config": {
                "concurrent_users": 50,
                "duration_seconds": 60,
                "ramp_up_seconds": 10,
                "requests_per_user_per_second": 1.0,
            },
            "summary": {
                "total_duration_seconds": 60.0,
                "total_requests": 100,
                "successful_requests": 90,
                "failed_requests": 10,
                "requests_per_second": 1.67,
            },
            "operations": {
                "create_task": {
                    "p50_ms": 45.0,
                    "p95_ms": 80.0,
                    "p99_ms": 600.0,
                    "avg_ms": 50.0,
                    "success_rate": 90.0,
                }
            },
            "slo_validation": {
                "passed": False,
                "checks": [
                    {
                        "name": "task_creation_p99",
                        "target_ms": 500.0,
                        "actual_ms": 600.0,
                        "passed": False,
                    }
                ],
            },
        }

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            print_report(report)
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        assert "FAILED" in output

    def test_print_report_handles_multiple_operations(self):
        """Test print_report handles multiple operations."""
        report = {
            "config": {
                "concurrent_users": 50,
                "duration_seconds": 60,
                "ramp_up_seconds": 10,
                "requests_per_user_per_second": 1.0,
            },
            "summary": {
                "total_duration_seconds": 60.0,
                "total_requests": 200,
                "successful_requests": 195,
                "failed_requests": 5,
                "requests_per_second": 3.33,
            },
            "operations": {
                "create_task": {
                    "p50_ms": 45.0,
                    "p95_ms": 80.0,
                    "p99_ms": 100.0,
                    "avg_ms": 50.0,
                    "success_rate": 99.0,
                },
                "get_task": {
                    "p50_ms": 10.0,
                    "p95_ms": 20.0,
                    "p99_ms": 30.0,
                    "avg_ms": 12.0,
                    "success_rate": 100.0,
                },
            },
            "slo_validation": {
                "passed": True,
                "checks": [],
            },
        }

        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            print_report(report)
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        assert "create_task" in output
        assert "get_task" in output


class TestMain:
    """Tests for main() async CLI entry point."""

    @pytest.mark.asyncio
    async def test_main_short_run(self):
        """Test main() with short duration for testing."""
        from mahavishnu.testing.load_test import main

        old_argv = sys.argv
        sys.argv = ["load_test", "--users", "2", "--duration", "1"]
        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            try:
                result = await main()
            finally:
                sys.argv = old_argv
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        assert "LOAD TEST REPORT" in output
        # Result depends on SLO validation - short run might fail or pass

    @pytest.mark.asyncio
    async def test_main_with_rps(self):
        """Test main() with custom requests per second."""
        from mahavishnu.testing.load_test import main

        old_argv = sys.argv
        sys.argv = ["load_test", "--users", "1", "--duration", "1", "--rps", "2"]
        captured = StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            try:
                result = await main()
            finally:
                sys.argv = old_argv
        finally:
            sys.stdout = old_stdout

        output = captured.getvalue()
        assert "LOAD TEST REPORT" in output
        assert "2" in output  # rps value