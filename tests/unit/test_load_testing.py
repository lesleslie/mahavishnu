"""Tests for Load Testing Framework - k6 integration and benchmarks."""

import pytest
import asyncio
from datetime import datetime, UTC
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any

from mahavishnu.core.load_testing import (
    LoadTestRunner,
    LoadTestConfig,
    LoadTestResult,
    BenchmarkSuite,
    BenchmarkResult,
    PerformanceMetric,
    MetricType,
)


@pytest.fixture
def sample_config() -> LoadTestConfig:
    """Create a sample load test configuration."""
    return LoadTestConfig(
        name="test_benchmark",
        vus=10,
        duration_seconds=30,
        ramp_up_seconds=5,
        target_url="http://localhost:8080/api/tasks",
    )


@pytest.fixture
def sample_metrics() -> list[PerformanceMetric]:
    """Create sample performance metrics."""
    return [
        PerformanceMetric(
            metric_type=MetricType.LATENCY,
            name="http_req_duration",
            value=50.0,
            timestamp=datetime.now(UTC),
        ),
        PerformanceMetric(
            metric_type=MetricType.THROUGHPUT,
            name="http_reqs",
            value=100.0,
            timestamp=datetime.now(UTC),
        ),
    ]


class TestMetricType:
    """Tests for MetricType enum."""

    def test_metric_types(self) -> None:
        """Test available metric types."""
        assert MetricType.LATENCY.value == "latency"
        assert MetricType.THROUGHPUT.value == "throughput"
        assert MetricType.ERROR_RATE.value == "error_rate"
        assert MetricType.P50.value == "p50"
        assert MetricType.P95.value == "p95"
        assert MetricType.P99.value == "p99"


class TestPerformanceMetric:
    """Tests for PerformanceMetric class."""

    def test_create_metric(self) -> None:
        """Create a performance metric."""
        metric = PerformanceMetric(
            metric_type=MetricType.LATENCY,
            name="response_time",
            value=100.0,
            timestamp=datetime.now(UTC),
        )

        assert metric.metric_type == MetricType.LATENCY
        assert metric.name == "response_time"
        assert metric.value == 100.0

    def test_metric_with_tags(self) -> None:
        """Create metric with tags."""
        metric = PerformanceMetric(
            metric_type=MetricType.LATENCY,
            name="response_time",
            value=100.0,
            timestamp=datetime.now(UTC),
            tags={"endpoint": "/api/tasks", "method": "GET"},
        )

        assert metric.tags["endpoint"] == "/api/tasks"
        assert metric.tags["method"] == "GET"

    def test_metric_to_dict(self) -> None:
        """Convert metric to dictionary."""
        metric = PerformanceMetric(
            metric_type=MetricType.P95,
            name="latency_p95",
            value=150.0,
            timestamp=datetime.now(UTC),
        )

        d = metric.to_dict()

        assert d["metric_type"] == "p95"
        assert d["name"] == "latency_p95"
        assert d["value"] == 150.0


class TestLoadTestConfig:
    """Tests for LoadTestConfig class."""

    def test_create_config(self) -> None:
        """Create a load test configuration."""
        config = LoadTestConfig(
            name="stress_test",
            vus=100,
            duration_seconds=60,
            target_url="http://localhost:8080/api",
        )

        assert config.name == "stress_test"
        assert config.vus == 100
        assert config.duration_seconds == 60

    def test_config_defaults(self) -> None:
        """Test configuration defaults."""
        config = LoadTestConfig(
            name="test",
            vus=10,
            duration_seconds=30,
            target_url="http://localhost",
        )

        assert config.ramp_up_seconds == 0
        assert config.timeout_seconds == 30

    def test_config_to_k6_script(self) -> None:
        """Generate k6 script from config."""
        config = LoadTestConfig(
            name="api_test",
            vus=50,
            duration_seconds=120,
            ramp_up_seconds=10,
            target_url="http://localhost:8080/api/tasks",
        )

        script = config.to_k6_script()

        assert "import http from 'k6/http'" in script
        assert "vus: 50" in script
        assert "duration: '120s'" in script
        assert "ramp-up: ['10s']" in script or "stages" in script

    def test_config_with_headers(self) -> None:
        """Config with custom headers."""
        config = LoadTestConfig(
            name="auth_test",
            vus=10,
            duration_seconds=30,
            target_url="http://localhost:8080/api",
            headers={"Authorization": "Bearer token123"},
        )

        assert config.headers["Authorization"] == "Bearer token123"


class TestLoadTestResult:
    """Tests for LoadTestResult class."""

    def test_create_result(self) -> None:
        """Create a load test result."""
        result = LoadTestResult(
            test_name="benchmark",
            passed=True,
            total_requests=1000,
            failed_requests=5,
            avg_latency_ms=50.0,
            p95_latency_ms=150.0,
            p99_latency_ms=200.0,
            requests_per_second=100.0,
        )

        assert result.test_name == "benchmark"
        assert result.passed is True
        assert result.total_requests == 1000

    def test_result_error_rate(self) -> None:
        """Calculate error rate."""
        result = LoadTestResult(
            test_name="test",
            passed=True,
            total_requests=1000,
            failed_requests=50,
            avg_latency_ms=50.0,
            p95_latency_ms=100.0,
            p99_latency_ms=150.0,
            requests_per_second=100.0,
        )

        assert result.error_rate == 0.05  # 5%

    def test_result_with_no_requests(self) -> None:
        """Result with no requests."""
        result = LoadTestResult(
            test_name="empty_test",
            passed=False,
            total_requests=0,
            failed_requests=0,
            avg_latency_ms=0.0,
            p95_latency_ms=0.0,
            p99_latency_ms=0.0,
            requests_per_second=0.0,
        )

        assert result.error_rate == 0.0

    def test_result_to_dict(self) -> None:
        """Convert result to dictionary."""
        result = LoadTestResult(
            test_name="test",
            passed=True,
            total_requests=100,
            failed_requests=0,
            avg_latency_ms=50.0,
            p95_latency_ms=100.0,
            p99_latency_ms=150.0,
            requests_per_second=100.0,
        )

        d = result.to_dict()

        assert d["test_name"] == "test"
        assert d["passed"] is True
        assert "error_rate" in d


class TestBenchmarkResult:
    """Tests for BenchmarkResult class."""

    def test_create_result(self) -> None:
        """Create a benchmark result."""
        result = BenchmarkResult(
            name="task_list_benchmark",
            baseline_value=100.0,
            current_value=95.0,
            unit="ms",
        )

        assert result.name == "task_list_benchmark"
        assert result.baseline_value == 100.0
        assert result.current_value == 95.0

    def test_improvement_percentage(self) -> None:
        """Calculate improvement percentage."""
        improved = BenchmarkResult(
            name="test",
            baseline_value=100.0,
            current_value=80.0,  # 20% faster
            unit="ms",
        )

        degraded = BenchmarkResult(
            name="test",
            baseline_value=100.0,
            current_value=120.0,  # 20% slower
            unit="ms",
        )

        assert improved.improvement_percent == 20.0
        assert degraded.improvement_percent == -20.0

    def test_is_regression(self) -> None:
        """Check for regression."""
        improved = BenchmarkResult(
            name="test",
            baseline_value=100.0,
            current_value=80.0,
            unit="ms",
        )

        degraded = BenchmarkResult(
            name="test",
            baseline_value=100.0,
            current_value=120.0,
            unit="ms",
        )

        assert improved.is_regression is False
        assert degraded.is_regression is True

    def test_is_regression_with_threshold(self) -> None:
        """Check for regression with threshold."""
        slight_degradation = BenchmarkResult(
            name="test",
            baseline_value=100.0,
            current_value=105.0,  # 5% slower
            unit="ms",
        )

        # With 10% threshold, 5% is not a regression
        assert slight_degradation.is_regression_with_threshold(0.1) is False

        # With 1% threshold, 5% is a regression
        assert slight_degradation.is_regression_with_threshold(0.01) is True


class TestLoadTestRunner:
    """Tests for LoadTestRunner class."""

    def test_create_runner(self) -> None:
        """Create a load test runner."""
        runner = LoadTestRunner()

        assert runner is not None
        assert len(runner.results) == 0

    def test_create_runner_with_config(
        self,
        sample_config: LoadTestConfig,
    ) -> None:
        """Create runner with config."""
        runner = LoadTestRunner(config=sample_config)

        assert runner.config.name == "test_benchmark"
        assert runner.config.vus == 10

    @pytest.mark.asyncio
    async def test_run_test(
        self,
        sample_config: LoadTestConfig,
    ) -> None:
        """Run a load test."""
        runner = LoadTestRunner(config=sample_config)

        # Mock the k6 execution
        with patch.object(runner, '_execute_k6', new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {
                "http_reqs": {"count": 1000, "rate": 100.0},
                "http_req_duration": {"avg": 50.0, "p(95)": 150.0, "p(99)": 200.0},
                "http_req_failed": {"value": 0.01},
            }

            result = await runner.run()

            assert result is not None
            assert result.total_requests == 1000

    @pytest.mark.asyncio
    async def test_run_test_with_failure(
        self,
        sample_config: LoadTestConfig,
    ) -> None:
        """Run test that fails."""
        runner = LoadTestRunner(config=sample_config)

        with patch.object(runner, '_execute_k6', new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = Exception("k6 not found")

            result = await runner.run()

            assert result.passed is False

    def test_get_last_result(
        self,
        sample_config: LoadTestConfig,
    ) -> None:
        """Get last test result."""
        runner = LoadTestRunner(config=sample_config)

        # Add mock result
        runner.results.append(LoadTestResult(
            test_name="test1",
            passed=True,
            total_requests=100,
            failed_requests=0,
            avg_latency_ms=50.0,
            p95_latency_ms=100.0,
            p99_latency_ms=150.0,
            requests_per_second=100.0,
        ))

        result = runner.get_last_result()

        assert result is not None
        assert result.test_name == "test1"

    def test_parse_k6_output(self) -> None:
        """Parse k6 JSON output."""
        runner = LoadTestRunner()

        k6_output = """
        {"type":"Point","data":{"time":"2024-01-01T00:00:00Z","value":50},"metric":"http_req_duration"}
        {"type":"Point","data":{"time":"2024-01-01T00:00:00Z","value":1},"metric":"http_reqs"}
        """

        metrics = runner.parse_k6_output(k6_output)

        assert len(metrics) == 2
        assert metrics[0].metric_type == MetricType.LATENCY
        assert metrics[1].metric_type == MetricType.THROUGHPUT


class TestBenchmarkSuite:
    """Tests for BenchmarkSuite class."""

    def test_create_suite(self) -> None:
        """Create a benchmark suite."""
        suite = BenchmarkSuite(name="api_benchmarks")

        assert suite.name == "api_benchmarks"
        assert len(suite.benchmarks) == 0

    def test_add_benchmark(self) -> None:
        """Add a benchmark to suite."""
        suite = BenchmarkSuite(name="api_benchmarks")

        suite.add_benchmark(
            name="list_tasks",
            baseline_value=100.0,
            current_value=95.0,
            unit="ms",
        )

        assert len(suite.benchmarks) == 1
        assert suite.benchmarks[0].name == "list_tasks"

    def test_run_suite(self) -> None:
        """Run all benchmarks in suite."""
        suite = BenchmarkSuite(name="api_benchmarks")

        suite.add_benchmark("test1", baseline=100.0, current=80.0, unit="ms")
        suite.add_benchmark("test2", baseline=100.0, current=120.0, unit="ms")

        results = suite.run()

        assert len(results) == 2
        assert results[0].is_regression is False
        assert results[1].is_regression is True

    def test_suite_summary(self) -> None:
        """Get suite summary."""
        suite = BenchmarkSuite(name="api_benchmarks")

        suite.add_benchmark("test1", baseline=100.0, current=80.0, unit="ms")
        suite.add_benchmark("test2", baseline=100.0, current=120.0, unit="ms")
        suite.add_benchmark("test3", baseline=100.0, current=90.0, unit="ms")

        summary = suite.get_summary()

        assert summary["total_benchmarks"] == 3
        assert summary["regressions"] == 1
        assert summary["improvements"] == 2

    def test_has_regression(self) -> None:
        """Check if suite has regression."""
        suite_no_regression = BenchmarkSuite(name="good")
        suite_no_regression.add_benchmark("test", baseline=100.0, current=80.0, unit="ms")

        suite_with_regression = BenchmarkSuite(name="bad")
        suite_with_regression.add_benchmark("test", baseline=100.0, current=120.0, unit="ms")

        assert suite_no_regression.has_regression is False
        assert suite_with_regression.has_regression is True

    def test_compare_baselines(self) -> None:
        """Compare with saved baselines."""
        suite = BenchmarkSuite(name="api_benchmarks")

        # Load baselines from previous run
        baselines = {
            "list_tasks": 100.0,
            "get_task": 50.0,
        }

        suite.set_baselines(baselines)

        assert suite.get_baseline("list_tasks") == 100.0
        assert suite.get_baseline("get_task") == 50.0

    def test_save_results(self) -> None:
        """Save benchmark results."""
        suite = BenchmarkSuite(name="api_benchmarks")
        suite.add_benchmark("test", baseline=100.0, current=80.0, unit="ms")

        results_json = suite.to_json()

        assert '"name": "test"' in results_json
        assert '"baseline_value": 100.0' in results_json

    def test_load_results(self) -> None:
        """Load benchmark results."""
        suite = BenchmarkSuite(name="api_benchmarks")

        results_json = '{"name": "loaded", "baseline_value": 100.0, "current_value": 80.0, "unit": "ms"}'
        suite.add_benchmark_from_json(results_json)

        assert len(suite.benchmarks) == 1
        assert suite.benchmarks[0].name == "loaded"
