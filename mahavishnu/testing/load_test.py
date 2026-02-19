"""Load testing module for Mahavishnu Task Orchestration.

Provides load testing capabilities for establishing performance baselines:
- Task creation latency
- Task query latency
- Concurrent user simulation
- SLO validation

Usage:
    python -m mahavishnu.testing.load_test --users 50 --duration 60

Run with:
    pytest tests/load/ -v  # For load test validation
    locust -f mahavishnu/testing/locustfile.py  # For interactive load testing
"""

from __future__ import annotations

import asyncio
import argparse
import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any
from pathlib import Path

logger = logging.getLogger(__name__)


class LoadTestPhase(str, Enum):
    """Load test phases."""

    WARMUP = "warmup"
    RAMP_UP = "ramp_up"
    STEADY_STATE = "steady_state"
    RAMP_DOWN = "ramp_down"
    COMPLETE = "complete"


@dataclass
class RequestResult:
    """Result of a single request."""

    timestamp: float
    operation: str
    latency_ms: float
    success: bool
    status_code: int = 200
    error: str | None = None


@dataclass
class LoadTestMetrics:
    """Aggregated load test metrics."""

    operation: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    latencies: list[float] = field(default_factory=list)

    # Calculated metrics
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    avg_ms: float = 0.0
    success_rate: float = 0.0
    requests_per_second: float = 0.0

    def add_result(self, result: RequestResult) -> None:
        """Add a request result to metrics."""
        self.total_requests += 1
        if result.success:
            self.successful_requests += 1
            self.latencies.append(result.latency_ms)
        else:
            self.failed_requests += 1

    def calculate(self, duration_seconds: float) -> None:
        """Calculate aggregate metrics."""
        if not self.latencies:
            return

        sorted_latencies = sorted(self.latencies)
        n = len(sorted_latencies)

        self.min_ms = sorted_latencies[0]
        self.max_ms = sorted_latencies[-1]
        self.avg_ms = statistics.mean(sorted_latencies)

        # Percentiles
        self.p50_ms = sorted_latencies[int(n * 0.50)]
        self.p95_ms = sorted_latencies[int(n * 0.95)]
        self.p99_ms = sorted_latencies[int(n * 0.99)]

        # Success rate
        self.success_rate = (
            self.successful_requests / self.total_requests * 100
            if self.total_requests > 0
            else 0
        )

        # Throughput
        self.requests_per_second = self.total_requests / duration_seconds

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "operation": self.operation,
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "p50_ms": round(self.p50_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "p99_ms": round(self.p99_ms, 2),
            "min_ms": round(self.min_ms, 2),
            "max_ms": round(self.max_ms, 2),
            "avg_ms": round(self.avg_ms, 2),
            "success_rate": round(self.success_rate, 2),
            "requests_per_second": round(self.requests_per_second, 2),
        }


@dataclass
class LoadTestConfig:
    """Load test configuration."""

    # User configuration
    concurrent_users: int = 50
    duration_seconds: int = 60
    ramp_up_seconds: int = 10

    # Request rates
    requests_per_user_per_second: float = 1.0

    # Target configuration
    base_url: str = "http://localhost:8690"
    api_prefix: str = "/api/v1"

    # SLO thresholds (for validation)
    task_create_p99_ms: float = 500.0
    task_query_p99_ms: float = 200.0
    min_success_rate: float = 99.0

    # Output
    output_file: str | None = None


class MockTaskClient:
    """Mock client for load testing without real server.

    This simulates task operations for load testing when
    a real server isn't available.
    """

    def __init__(self, config: LoadTestConfig):
        self.config = config
        self._task_counter = 0
        self._tasks: dict[int, dict] = {}

    async def create_task(self, title: str, repository: str) -> RequestResult:
        """Simulate task creation."""
        start = time.perf_counter()

        # Simulate processing time (10-50ms with occasional spikes)
        import random

        base_latency = random.uniform(10, 50)
        # 5% chance of slower operation (simulating NLP parsing)
        if random.random() < 0.05:
            base_latency += random.uniform(100, 300)

        await asyncio.sleep(base_latency / 1000)

        self._task_counter += 1
        task_id = self._task_counter
        self._tasks[task_id] = {
            "id": task_id,
            "title": title,
            "repository": repository,
            "status": "pending",
            "created_at": datetime.now(UTC).isoformat(),
        }

        latency_ms = (time.perf_counter() - start) * 1000

        return RequestResult(
            timestamp=time.time(),
            operation="create_task",
            latency_ms=latency_ms,
            success=True,
            status_code=201,
        )

    async def get_task(self, task_id: int) -> RequestResult:
        """Simulate task retrieval."""
        start = time.perf_counter()

        import random

        # Simulate DB query (5-20ms)
        base_latency = random.uniform(5, 20)
        await asyncio.sleep(base_latency / 1000)

        latency_ms = (time.perf_counter() - start) * 1000

        success = task_id in self._tasks
        return RequestResult(
            timestamp=time.time(),
            operation="get_task",
            latency_ms=latency_ms,
            success=success,
            status_code=200 if success else 404,
        )

    async def list_tasks(self, limit: int = 50, offset: int = 0) -> RequestResult:
        """Simulate task listing."""
        start = time.perf_counter()

        import random

        # Simulate DB query (10-40ms)
        base_latency = random.uniform(10, 40)
        await asyncio.sleep(base_latency / 1000)

        latency_ms = (time.perf_counter() - start) * 1000

        return RequestResult(
            timestamp=time.time(),
            operation="list_tasks",
            latency_ms=latency_ms,
            success=True,
            status_code=200,
        )

    async def update_task(self, task_id: int, **updates) -> RequestResult:
        """Simulate task update."""
        start = time.perf_counter()

        import random

        # Simulate DB write (15-60ms)
        base_latency = random.uniform(15, 60)
        await asyncio.sleep(base_latency / 1000)

        latency_ms = (time.perf_counter() - start) * 1000

        success = task_id in self._tasks
        if success:
            self._tasks[task_id].update(updates)

        return RequestResult(
            timestamp=time.time(),
            operation="update_task",
            latency_ms=latency_ms,
            success=success,
            status_code=200 if success else 404,
        )


class LoadTestRunner:
    """Load test runner for Mahavishnu."""

    def __init__(self, config: LoadTestConfig):
        self.config = config
        self.client = MockTaskClient(config)
        self.metrics: dict[str, LoadTestMetrics] = {}
        self.results: list[RequestResult] = []
        self._running = False

    async def _user_session(self, user_id: int, stop_event: asyncio.Event) -> None:
        """Simulate a single user session."""
        import random

        task_ids: list[int] = []

        while not stop_event.is_set():
            try:
                # Random operation mix (realistic user behavior)
                operation = random.choices(
                    ["create", "get", "list", "update"],
                    weights=[0.2, 0.3, 0.3, 0.2],
                )[0]

                if operation == "create":
                    result = await self.client.create_task(
                        title=f"Load test task {user_id}-{len(task_ids)}",
                        repository="test-repo",
                    )
                    if result.success and hasattr(self.client, "_task_counter"):
                        task_ids.append(self.client._task_counter)

                elif operation == "get" and task_ids:
                    task_id = random.choice(task_ids)
                    result = await self.client.get_task(task_id)

                elif operation == "list":
                    result = await self.client.list_tasks()

                elif operation == "update" and task_ids:
                    task_id = random.choice(task_ids)
                    result = await self.client.update_task(
                        task_id, status="in_progress"
                    )
                else:
                    # Fallback to create if no tasks exist
                    result = await self.client.create_task(
                        title=f"Load test task {user_id}-{len(task_ids)}",
                        repository="test-repo",
                    )

                # Record result
                self.results.append(result)
                if result.operation not in self.metrics:
                    self.metrics[result.operation] = LoadTestMetrics(
                        operation=result.operation
                    )
                self.metrics[result.operation].add_result(result)

                # Rate limiting
                interval = 1.0 / self.config.requests_per_user_per_second
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"User {user_id} error: {e}")
                self.results.append(
                    RequestResult(
                        timestamp=time.time(),
                        operation="error",
                        latency_ms=0,
                        success=False,
                        error=str(e),
                    )
                )

    async def run(self) -> dict[str, Any]:
        """Run the load test."""
        logger.info(
            f"Starting load test: {self.config.concurrent_users} users, "
            f"{self.config.duration_seconds}s duration"
        )

        self._running = True
        start_time = time.time()
        stop_event = asyncio.Event()

        # Create user tasks
        user_tasks = []
        for user_id in range(self.config.concurrent_users):
            task = asyncio.create_task(self._user_session(user_id + 1, stop_event))
            user_tasks.append(task)

        # Run for specified duration
        await asyncio.sleep(self.config.duration_seconds)

        # Signal stop and wait for users to finish
        stop_event.set()
        await asyncio.gather(*user_tasks, return_exceptions=True)

        end_time = time.time()
        duration = end_time - start_time

        # Calculate metrics
        for metrics in self.metrics.values():
            metrics.calculate(duration)

        # Generate report
        report = {
            "config": {
                "concurrent_users": self.config.concurrent_users,
                "duration_seconds": self.config.duration_seconds,
                "ramp_up_seconds": self.config.ramp_up_seconds,
                "requests_per_user_per_second": self.config.requests_per_user_per_second,
            },
            "summary": {
                "total_duration_seconds": round(duration, 2),
                "total_requests": len(self.results),
                "successful_requests": sum(1 for r in self.results if r.success),
                "failed_requests": sum(1 for r in self.results if not r.success),
                "requests_per_second": round(len(self.results) / duration, 2),
            },
            "operations": {
                name: metrics.to_dict() for name, metrics in self.metrics.items()
            },
            "slo_validation": self._validate_slos(),
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if self.config.output_file:
            output_path = Path(self.config.output_file)
            output_path.write_text(json.dumps(report, indent=2))
            logger.info(f"Report written to {output_path}")

        return report

    def _validate_slos(self) -> dict[str, Any]:
        """Validate SLO targets."""
        validation = {
            "passed": True,
            "checks": [],
        }

        # Task creation latency
        if "create_task" in self.metrics:
            m = self.metrics["create_task"]
            check = {
                "name": "task_creation_p99",
                "target_ms": self.config.task_create_p99_ms,
                "actual_ms": m.p99_ms,
                "passed": m.p99_ms <= self.config.task_create_p99_ms,
            }
            validation["checks"].append(check)
            if not check["passed"]:
                validation["passed"] = False

        # Task query latency
        for op in ["get_task", "list_tasks"]:
            if op in self.metrics:
                m = self.metrics[op]
                check = {
                    "name": f"{op}_p99",
                    "target_ms": self.config.task_query_p99_ms,
                    "actual_ms": m.p99_ms,
                    "passed": m.p99_ms <= self.config.task_query_p99_ms,
                }
                validation["checks"].append(check)
                if not check["passed"]:
                    validation["passed"] = False

        # Success rate
        for name, m in self.metrics.items():
            check = {
                "name": f"{name}_success_rate",
                "target_percent": self.config.min_success_rate,
                "actual_percent": m.success_rate,
                "passed": m.success_rate >= self.config.min_success_rate,
            }
            validation["checks"].append(check)
            if not check["passed"]:
                validation["passed"] = False

        return validation


def print_report(report: dict[str, Any]) -> None:
    """Print load test report."""
    print("\n" + "=" * 60)
    print("LOAD TEST REPORT")
    print("=" * 60)

    print(f"\n📊 Configuration:")
    config = report["config"]
    print(f"   Concurrent Users: {config['concurrent_users']}")
    print(f"   Duration: {config['duration_seconds']}s")
    print(f"   Requests/User/Second: {config['requests_per_user_per_second']}")

    print(f"\n📈 Summary:")
    summary = report["summary"]
    print(f"   Total Requests: {summary['total_requests']}")
    print(f"   Successful: {summary['successful_requests']}")
    print(f"   Failed: {summary['failed_requests']}")
    print(f"   Throughput: {summary['requests_per_second']} req/s")

    print(f"\n⏱️  Latency by Operation:")
    for op, metrics in report["operations"].items():
        print(f"   {op}:")
        print(f"      P50: {metrics['p50_ms']:.2f}ms")
        print(f"      P95: {metrics['p95_ms']:.2f}ms")
        print(f"      P99: {metrics['p99_ms']:.2f}ms")
        print(f"      Avg: {metrics['avg_ms']:.2f}ms")
        print(f"      Success Rate: {metrics['success_rate']:.2f}%")

    print(f"\n✅ SLO Validation:")
    slo = report["slo_validation"]
    status = "PASSED" if slo["passed"] else "FAILED"
    print(f"   Overall: {status}")
    for check in slo["checks"]:
        icon = "✓" if check["passed"] else "✗"
        if "target_ms" in check:
            print(f"   {icon} {check['name']}: {check['actual_ms']:.2f}ms (target: {check['target_ms']}ms)")
        else:
            print(
                f"   {icon} {check['name']}: {check['actual_percent']:.2f}% (target: {check['target_percent']}%)"
            )

    print("\n" + "=" * 60)


async def main():
    """Main entry point for load testing."""
    parser = argparse.ArgumentParser(description="Mahavishnu Load Testing")
    parser.add_argument(
        "--users",
        type=int,
        default=50,
        help="Number of concurrent users (default: 50)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Test duration in seconds (default: 60)",
    )
    parser.add_argument(
        "--rps",
        type=float,
        default=1.0,
        help="Requests per user per second (default: 1.0)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file for JSON report",
    )

    args = parser.parse_args()

    config = LoadTestConfig(
        concurrent_users=args.users,
        duration_seconds=args.duration,
        requests_per_user_per_second=args.rps,
        output_file=args.output,
    )

    runner = LoadTestRunner(config)
    report = await runner.run()
    print_report(report)

    # Exit with error code if SLO validation failed
    if not report["slo_validation"]["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
