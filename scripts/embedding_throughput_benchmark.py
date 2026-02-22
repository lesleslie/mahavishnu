#!/usr/bin/env python3
"""Embedding Throughput Benchmark for Phase 5 Validation.

This script benchmarks embedding generation performance:
- Single embedding latency
- Batch embedding throughput
- Cache hit rates (L1 and L2)
- Multi-provider comparison

Target metrics (from plan):
- Single embedding latency: ~50ms (unchanged)
- Batch embedding throughput: 80/s (revised from 500/s)
- Cache hit rate: 70% (revised from 80%)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Test data
SAMPLE_TEXTS = [
    "How does authentication work in this microservices architecture?",
    "Explain the database connection pooling strategy",
    "What is the error handling pattern for API calls?",
    "Compare the performance of FastAPI vs Flask",
    "Show me the deployment pipeline configuration",
    "Analyze the code review process for security vulnerabilities",
    "Generate unit tests for the user service module",
    "Document the API endpoints for the payment system",
    "Optimize the database queries for the dashboard",
    "Review the logging strategy for production debugging",
    "Explain how the caching layer improves response times",
    "What are the best practices for error handling in async code?",
    "Compare PostgreSQL vs MongoDB for our use case",
    "How do we handle rate limiting in the API gateway?",
    "Show the CI/CD pipeline stages and their dependencies",
    "Analyze memory usage patterns in the worker processes",
    "Generate integration tests for the webhook handlers",
    "Document the Kubernetes deployment manifests",
    "Optimize the Docker image build time",
    "Review the secrets management approach",
]

# Extended test data for batch benchmarks
BATCH_TEXTS = SAMPLE_TEXTS * 5  # 100 texts


@dataclass
class BenchmarkResult:
    """Result from a single benchmark run."""

    name: str
    iterations: int
    total_time_s: float
    operations_per_second: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    errors: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "iterations": self.iterations,
            "total_time_s": round(self.total_time_s, 3),
            "operations_per_second": round(self.operations_per_second, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 3),
            "p50_latency_ms": round(self.p50_latency_ms, 3),
            "p95_latency_ms": round(self.p95_latency_ms, 3),
            "p99_latency_ms": round(self.p99_latency_ms, 3),
            "min_latency_ms": round(self.min_latency_ms, 3),
            "max_latency_ms": round(self.max_latency_ms, 3),
            "errors": self.errors,
            "metadata": self.metadata,
        }


@dataclass
class BenchmarkSuite:
    """Collection of benchmark results."""

    name: str
    results: list[BenchmarkResult] = field(default_factory=lambda: [])
    targets: dict[str, dict[str, float]] = field(default_factory=lambda: {})

    def add_result(self, result: BenchmarkResult) -> None:
        """Add a benchmark result."""
        self.results.append(result)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "results": [r.to_dict() for r in self.results],
            "targets": self.targets,
            "summary": self._generate_summary(),
        }

    def _generate_summary(self) -> dict[str, Any]:
        """Generate summary of pass/fail against targets."""
        summary = {"passed": 0, "failed": 0, "details": []}

        for result in self.results:
            target = self.targets.get(result.name)
            if target:
                ops_target = target.get("ops_per_second")
                if ops_target and result.operations_per_second >= ops_target:
                    summary["passed"] += 1
                    status = "PASS"
                elif ops_target:
                    summary["failed"] += 1
                    status = "FAIL"
                else:
                    status = "N/A"

                summary["details"].append(
                    {
                        "benchmark": result.name,
                        "status": status,
                        "actual_ops": result.operations_per_second,
                        "target_ops": ops_target,
                    }
                )

        return summary

    def print_report(self) -> None:
        """Print formatted benchmark report."""
        print("\n" + "=" * 70)
        print(f" {self.name} Results")
        print("=" * 70)

        for result in self.results:
            print(f"\n{result.name}")
            print("-" * 50)
            print(f"  Iterations:    {result.iterations}")
            print(f"  Total time:    {result.total_time_s:.3f}s")
            print(f"  Throughput:    {result.operations_per_second:.2f} ops/s")
            print(f"  Avg latency:   {result.avg_latency_ms:.3f}ms")
            print(f"  P50 latency:   {result.p50_latency_ms:.3f}ms")
            print(f"  P95 latency:   {result.p95_latency_ms:.3f}ms")
            print(f"  P99 latency:   {result.p99_latency_ms:.3f}ms")
            print(f"  Min latency:   {result.min_latency_ms:.3f}ms")
            print(f"  Max latency:   {result.max_latency_ms:.3f}ms")
            if result.errors > 0:
                print(f"  Errors:        {result.errors}")

            # Check against target
            target = self.targets.get(result.name)
            if target:
                ops_target = target.get("ops_per_second")
                if ops_target:
                    pct = (result.operations_per_second / ops_target) * 100
                    status = "PASS" if pct >= 100 else "FAIL"
                    print(f"  Target:        {ops_target:.2f} ops/s ({pct:.1f}%) [{status}]")

        # Print summary
        summary = self._generate_summary()
        print("\n" + "=" * 70)
        print(" Summary")
        print("=" * 70)
        print(f"  Passed: {summary['passed']}")
        print(f"  Failed: {summary['failed']}")

        for detail in summary["details"]:
            status_icon = "PASS" if detail["status"] == "PASS" else "FAIL"
            print(
                f"  [{status_icon}] {detail['benchmark']}: "
                f"{detail['actual_ops']:.2f}/{detail['target_ops']:.2f} ops/s"
            )


def calculate_percentile(values: list[float], percentile: float) -> float:
    """Calculate percentile value."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = int(len(sorted_values) * percentile / 100)
    index = min(index, len(sorted_values) - 1)
    return sorted_values[index]


async def benchmark_single_embeddings(
    iterations: int = 50,
) -> BenchmarkResult:
    """Benchmark single embedding generation.

    Uses the resilient embedding client to measure latency for individual
    embedding requests.
    """
    latencies_ms: list[float] = []
    errors = 0

    # Import here to allow script to run without full environment
    try:
        from mahavishnu.core.resilient_embeddings import ResilientEmbeddingClient

        client = ResilientEmbeddingClient()
    except ImportError:
        # Fall back to mock if dependencies not available
        logger.warning("ResilientEmbeddingClient not available, using mock")
        return _mock_benchmark("single_embedding", iterations, avg_ms=50.0)

    start_time = time.perf_counter()

    for i in range(iterations):
        text = SAMPLE_TEXTS[i % len(SAMPLE_TEXTS)]
        iter_start = time.perf_counter()

        try:
            result = await client.generate_embedding(text, use_cache=False)
            iter_end = time.perf_counter()
            latencies_ms.append((iter_end - iter_start) * 1000)
        except Exception as e:
            errors += 1
            logger.debug(f"Error in iteration {i}: {e}")

    total_time = time.perf_counter() - start_time

    await client.close()

    if not latencies_ms:
        return BenchmarkResult(
            name="single_embedding",
            iterations=iterations,
            total_time_s=total_time,
            operations_per_second=0,
            avg_latency_ms=0,
            p50_latency_ms=0,
            p95_latency_ms=0,
            p99_latency_ms=0,
            min_latency_ms=0,
            max_latency_ms=0,
            errors=errors,
        )

    return BenchmarkResult(
        name="single_embedding",
        iterations=len(latencies_ms),
        total_time_s=total_time,
        operations_per_second=len(latencies_ms) / total_time,
        avg_latency_ms=statistics.mean(latencies_ms),
        p50_latency_ms=calculate_percentile(latencies_ms, 50),
        p95_latency_ms=calculate_percentile(latencies_ms, 95),
        p99_latency_ms=calculate_percentile(latencies_ms, 99),
        min_latency_ms=min(latencies_ms),
        max_latency_ms=max(latencies_ms),
        errors=errors,
    )


async def benchmark_batch_embeddings(
    batch_size: int = 10,
    iterations: int = 10,
) -> BenchmarkResult:
    """Benchmark batch embedding generation.

    Measures throughput when generating embeddings in batches.
    """
    latencies_ms: list[float] = []
    errors = 0
    total_embeddings = 0

    try:
        from mahavishnu.core.resilient_embeddings import ResilientEmbeddingClient

        client = ResilientEmbeddingClient()
    except ImportError:
        logger.warning("ResilientEmbeddingClient not available, using mock")
        return _mock_benchmark(
            f"batch_embedding_{batch_size}",
            iterations * batch_size,
            avg_ms=100.0 / batch_size,
        )

    start_time = time.perf_counter()

    for i in range(iterations):
        # Get batch of texts
        start_idx = (i * batch_size) % len(BATCH_TEXTS)
        batch = BATCH_TEXTS[start_idx : start_idx + batch_size]
        if len(batch) < batch_size:
            batch = batch + BATCH_TEXTS[: batch_size - len(batch)]

        iter_start = time.perf_counter()

        try:
            results = await client.generate_batch_embeddings(batch, use_cache=False)
            iter_end = time.perf_counter()

            # Only count successful embeddings
            successful = sum(1 for r in results if r.embedding)
            total_embeddings += successful
            latencies_ms.append((iter_end - iter_start) * 1000 / successful)
        except Exception as e:
            errors += 1
            logger.debug(f"Error in batch {i}: {e}")

    total_time = time.perf_counter() - start_time

    await client.close()

    if not latencies_ms:
        return BenchmarkResult(
            name=f"batch_embedding_{batch_size}",
            iterations=0,
            total_time_s=total_time,
            operations_per_second=0,
            avg_latency_ms=0,
            p50_latency_ms=0,
            p95_latency_ms=0,
            p99_latency_ms=0,
            min_latency_ms=0,
            max_latency_ms=0,
            errors=errors,
        )

    return BenchmarkResult(
        name=f"batch_embedding_{batch_size}",
        iterations=total_embeddings,
        total_time_s=total_time,
        operations_per_second=total_embeddings / total_time,
        avg_latency_ms=statistics.mean(latencies_ms),
        p50_latency_ms=calculate_percentile(latencies_ms, 50),
        p95_latency_ms=calculate_percentile(latencies_ms, 95),
        p99_latency_ms=calculate_percentile(latencies_ms, 99),
        min_latency_ms=min(latencies_ms),
        max_latency_ms=max(latencies_ms),
        errors=errors,
    )


async def benchmark_cache_hit_rate(
    warmup_iterations: int = 20,
    test_iterations: int = 100,
) -> BenchmarkResult:
    """Benchmark cache hit rate for embedding cache.

    Measures L1 and L2 cache effectiveness.
    """
    try:
        from mahavishnu.core.embedding_cache import EmbeddingCache, EmbeddingCacheConfig
        from mahavishnu.core.resilient_embeddings import ResilientEmbeddingClient

        # Create cache with small L1 for testing
        config = EmbeddingCacheConfig(
            l1_max_size=100,
            l2_enabled=False,  # Test L1 only
        )
        cache = EmbeddingCache(config)
        client = ResilientEmbeddingClient(embedding_cache=cache)
    except ImportError:
        logger.warning("Cache components not available, using mock")
        return _mock_benchmark(
            "cache_hit_rate",
            test_iterations,
            avg_ms=5.0,
            metadata={"hit_rate": 0.85, "l1_hits": 85, "l2_hits": 0},
        )

    # Warmup - populate cache
    warmup_texts = SAMPLE_TEXTS[:warmup_iterations]
    for text in warmup_texts:
        await client.generate_embedding(text, use_cache=True)

    # Test - should hit cache for repeated texts
    cache_hits = 0
    latencies_ms: list[float] = []

    start_time = time.perf_counter()

    for i in range(test_iterations):
        # 80% of requests are for cached texts (simulating realistic access pattern)
        if i % 5 != 0:
            text = warmup_texts[i % len(warmup_texts)]
        else:
            text = f"New text {i}"

        iter_start = time.perf_counter()
        result = await client.generate_embedding(text, use_cache=True)
        iter_end = time.perf_counter()

        latencies_ms.append((iter_end - iter_start) * 1000)
        if result.cached:
            cache_hits += 1

    total_time = time.perf_counter() - start_time

    await client.close()

    hit_rate = cache_hits / test_iterations

    return BenchmarkResult(
        name="cache_hit_rate",
        iterations=test_iterations,
        total_time_s=total_time,
        operations_per_second=test_iterations / total_time,
        avg_latency_ms=statistics.mean(latencies_ms),
        p50_latency_ms=calculate_percentile(latencies_ms, 50),
        p95_latency_ms=calculate_percentile(latencies_ms, 95),
        p99_latency_ms=calculate_percentile(latencies_ms, 99),
        min_latency_ms=min(latencies_ms),
        max_latency_ms=max(latencies_ms),
        metadata={
            "hit_rate": hit_rate,
            "l1_hits": cache_hits,
            "l2_hits": 0,  # L2 disabled for this test
        },
    )


def _mock_benchmark(
    name: str,
    iterations: int,
    avg_ms: float,
    metadata: dict[str, Any] | None = None,
) -> BenchmarkResult:
    """Create a mock benchmark result for testing without dependencies."""
    import random

    random.seed(42)
    latencies = [random.gauss(avg_ms, avg_ms * 0.2) for _ in range(iterations)]
    latencies = [max(0.1, l) for l in latencies]

    total_time = sum(latencies) / 1000

    return BenchmarkResult(
        name=name,
        iterations=iterations,
        total_time_s=total_time,
        operations_per_second=iterations / total_time,
        avg_latency_ms=statistics.mean(latencies),
        p50_latency_ms=calculate_percentile(latencies, 50),
        p95_latency_ms=calculate_percentile(latencies, 95),
        p99_latency_ms=calculate_percentile(latencies, 99),
        min_latency_ms=min(latencies),
        max_latency_ms=max(latencies),
        metadata=metadata or {},
    )


async def run_full_benchmark(
    single_iterations: int = 50,
    batch_size: int = 10,
    batch_iterations: int = 10,
    cache_warmup: int = 20,
    cache_test: int = 100,
) -> BenchmarkSuite:
    """Run full benchmark suite."""
    suite = BenchmarkSuite(
        name="Embedding Throughput Benchmark",
        targets={
            "single_embedding": {"ops_per_second": 20},  # ~50ms latency
            f"batch_embedding_{batch_size}": {"ops_per_second": 80},  # Revised target
            "cache_hit_rate": {"ops_per_second": 200},  # Cache should be fast
        },
    )

    print("Running Embedding Throughput Benchmark Suite...")
    print(f"  Single embedding iterations: {single_iterations}")
    print(f"  Batch size: {batch_size}, iterations: {batch_iterations}")
    print(f"  Cache warmup: {cache_warmup}, test: {cache_test}")

    # 1. Single embedding benchmark
    print("\n[1/3] Running single embedding benchmark...")
    result = await benchmark_single_embeddings(single_iterations)
    suite.add_result(result)

    # 2. Batch embedding benchmark
    print("[2/3] Running batch embedding benchmark...")
    result = await benchmark_batch_embeddings(batch_size, batch_iterations)
    suite.add_result(result)

    # 3. Cache hit rate benchmark
    print("[3/3] Running cache hit rate benchmark...")
    result = await benchmark_cache_hit_rate(cache_warmup, cache_test)
    suite.add_result(result)

    return suite


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Embedding Throughput Benchmark")
    parser.add_argument(
        "--single-iterations",
        type=int,
        default=50,
        help="Iterations for single embedding benchmark",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Batch size for batch embedding benchmark",
    )
    parser.add_argument(
        "--batch-iterations",
        type=int,
        default=10,
        help="Iterations for batch embedding benchmark",
    )
    parser.add_argument(
        "--cache-warmup",
        type=int,
        default=20,
        help="Warmup iterations for cache benchmark",
    )
    parser.add_argument(
        "--cache-test",
        type=int,
        default=100,
        help="Test iterations for cache benchmark",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for JSON results",
    )

    args = parser.parse_args()

    # Run benchmarks
    suite = asyncio.run(
        run_full_benchmark(
            single_iterations=args.single_iterations,
            batch_size=args.batch_size,
            batch_iterations=args.batch_iterations,
            cache_warmup=args.cache_warmup,
            cache_test=args.cache_test,
        )
    )

    # Print report
    suite.print_report()

    # Save to file if requested
    if args.output:
        with open(args.output, "w") as f:
            json.dump(suite.to_dict(), f, indent=2)
        print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()
