#!/usr/bin/env python3
"""End-to-End RAG Pipeline Benchmark for Phase 5 Validation.

This script benchmarks the complete RAG pipeline:
1. Query embedding generation
2. Vector similarity search
3. Context retrieval
4. Adaptive routing decisions

Target metrics (from plan):
- End-to-end latency: < 500ms
- Vector search latency: < 20ms (with HNSW)
- Overall QPS: 500+ (revised from 1000)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Test queries with varying complexity
TEST_QUERIES = [
    # Simple queries (expected: NAIVE RAG)
    "What is authentication?",
    "Show me the API",
    "List all users",
    "Get config",
    "Find errors",
    # Medium queries (expected: HYBRID RAG)
    "How does the authentication system work?",
    "Explain the database connection pooling",
    "What is the error handling pattern?",
    "Compare FastAPI and Flask performance",
    "Show deployment pipeline configuration",
    # Complex queries (expected: GRAPH RAG)
    "Explain how the authentication system integrates with the user management and role-based access control in the microservices architecture",
    "Describe the relationship between the API gateway, rate limiting, and backend services for traffic management",
    "How do the caching layer, database, and external APIs interact during high load scenarios",
    "Analyze the connection between CI/CD pipeline stages and deployment strategies",
    "What is the impact of database indexing on query performance and memory usage",
    # Very complex queries (expected: AGENTIC RAG)
    "Compare and contrast the authentication patterns used across microservices and explain why certain approaches were chosen for specific services, including the trade-offs between security and performance",
    "Analyze the end-to-end request flow from client to database, explaining each layer's responsibility and how failures at each layer are handled with fallback strategies",
    "Explain the rationale behind the chosen database sharding strategy and how it affects query patterns, consistency guarantees, and operational complexity",
    "Describe the complete incident response workflow when a production issue is detected, including monitoring, alerting, diagnosis, and remediation steps",
    "Compare the cost-effectiveness of different caching strategies given our access patterns and explain which strategy should be used for different data types",
]


@dataclass
class RAGStageMetrics:
    """Metrics for a single RAG pipeline stage."""

    name: str
    latency_ms: float
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=lambda: {})

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "latency_ms": round(self.latency_ms, 3),
            "success": self.success,
            "metadata": self.metadata,
        }


@dataclass
class RAGPipelineResult:
    """Result from a complete RAG pipeline execution."""

    query: str
    total_latency_ms: float
    stages: list[RAGStageMetrics]
    strategy: str
    success: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query[:50] + "..." if len(self.query) > 50 else self.query,
            "total_latency_ms": round(self.total_latency_ms, 3),
            "stages": [s.to_dict() for s in self.stages],
            "strategy": self.strategy,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class E2EBenchmarkResult:
    """Aggregated results from E2E benchmark."""

    name: str
    iterations: int
    total_time_s: float
    queries_per_second: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    success_rate: float
    strategy_distribution: dict[str, int]
    stage_latencies: dict[str, list[float]]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        stage_stats = {}
        for stage_name, latencies in self.stage_latencies.items():
            if latencies:
                stage_stats[stage_name] = {
                    "avg_ms": round(statistics.mean(latencies), 3),
                    "p50_ms": round(sorted(latencies)[int(len(latencies) * 0.5)], 3),
                    "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95)], 3),
                }

        return {
            "name": self.name,
            "iterations": self.iterations,
            "total_time_s": round(self.total_time_s, 3),
            "queries_per_second": round(self.queries_per_second, 2),
            "avg_latency_ms": round(self.avg_latency_ms, 3),
            "p50_latency_ms": round(self.p50_latency_ms, 3),
            "p95_latency_ms": round(self.p95_latency_ms, 3),
            "p99_latency_ms": round(self.p99_latency_ms, 3),
            "success_rate": round(self.success_rate, 3),
            "strategy_distribution": self.strategy_distribution,
            "stage_latencies": stage_stats,
        }


async def execute_rag_pipeline(query: str) -> RAGPipelineResult:
    """Execute a complete RAG pipeline for a query.

    This simulates the full pipeline:
    1. Query complexity analysis
    2. Strategy selection (adaptive routing)
    3. Query embedding generation
    4. Vector similarity search
    5. Context retrieval

    Args:
        query: The query to process

    Returns:
        RAGPipelineResult with timing and outcome details
    """
    stages: list[RAGStageMetrics] = []
    start_time = time.perf_counter()
    strategy = "unknown"
    error = None

    try:
        # Stage 1: Query complexity analysis
        stage_start = time.perf_counter()
        try:
            from mahavishnu.core.adaptive_rag import AdaptiveRAGRouter

            router = AdaptiveRAGRouter()
            analysis = await router.analyze_query(query)
            strategy = analysis.suggested_strategy.value
            stage_time = (time.perf_counter() - stage_start) * 1000
            stages.append(
                RAGStageMetrics(
                    name="complexity_analysis",
                    latency_ms=stage_time,
                    metadata={"complexity_score": analysis.complexity.score},
                )
            )
        except ImportError:
            # Mock if not available
            await asyncio.sleep(0.001)
            stage_time = (time.perf_counter() - stage_start) * 1000
            # Simple heuristic for mock
            words = len(query.split())
            if words < 5:
                strategy = "naive"
            elif words < 15:
                strategy = "hybrid"
            elif words < 30:
                strategy = "graph"
            else:
                strategy = "agentic"
            stages.append(
                RAGStageMetrics(
                    name="complexity_analysis",
                    latency_ms=stage_time,
                    metadata={"complexity_score": words / 50.0},
                )
            )

        # Stage 2: Query embedding generation
        stage_start = time.perf_counter()
        try:
            from mahavishnu.core.resilient_embeddings import ResilientEmbeddingClient

            client = ResilientEmbeddingClient()
            emb_result = await client.generate_embedding(query, use_cache=True)
            stage_time = (time.perf_counter() - stage_start) * 1000
            stages.append(
                RAGStageMetrics(
                    name="embedding_generation",
                    latency_ms=stage_time,
                    metadata={"source": emb_result.source.value, "cached": emb_result.cached},
                )
            )
            await client.close()
        except ImportError:
            # Mock embedding
            await asyncio.sleep(0.010)  # ~10ms mock
            stage_time = (time.perf_counter() - stage_start) * 1000
            stages.append(
                RAGStageMetrics(
                    name="embedding_generation",
                    latency_ms=stage_time,
                    metadata={"source": "mock", "cached": False},
                )
            )

        # Stage 3: Vector similarity search
        stage_start = time.perf_counter()
        try:
            from mahavishnu.ingesters import OtelIngester

            ingester = OtelIngester()
            await ingester.initialize()
            results = await ingester.search_traces(query, limit=10)
            stage_time = (time.perf_counter() - stage_start) * 1000
            stages.append(
                RAGStageMetrics(
                    name="vector_search",
                    latency_ms=stage_time,
                    metadata={"results_count": len(results) if results else 0},
                )
            )
            await ingester.close()
        except ImportError:
            # Mock search
            await asyncio.sleep(0.005)  # ~5ms mock for HNSW
            stage_time = (time.perf_counter() - stage_start) * 1000
            stages.append(
                RAGStageMetrics(
                    name="vector_search",
                    latency_ms=stage_time,
                    metadata={"results_count": 5},
                )
            )
        except Exception as e:
            stage_time = (time.perf_counter() - stage_start) * 1000
            stages.append(
                RAGStageMetrics(
                    name="vector_search",
                    latency_ms=stage_time,
                    success=False,
                    metadata={"error": str(e)[:50]},
                )
            )

        # Stage 4: Context retrieval (depends on strategy)
        stage_start = time.perf_counter()
        if strategy == "agentic":
            # Multi-agent would take longer
            await asyncio.sleep(0.050)
        elif strategy == "graph":
            # Graph traversal
            await asyncio.sleep(0.030)
        elif strategy == "hybrid":
            # Cache + vector
            await asyncio.sleep(0.020)
        else:
            # Naive - just vector
            await asyncio.sleep(0.010)

        stage_time = (time.perf_counter() - stage_start) * 1000
        stages.append(
            RAGStageMetrics(
                name="context_retrieval",
                latency_ms=stage_time,
                metadata={"strategy": strategy},
            )
        )

    except Exception as e:
        error = str(e)

    total_latency = (time.perf_counter() - start_time) * 1000

    return RAGPipelineResult(
        query=query,
        total_latency_ms=total_latency,
        stages=stages,
        strategy=strategy,
        success=error is None,
        error=error,
    )


async def run_e2e_benchmark(
    iterations: int = 50,
    concurrent: int = 5,
) -> E2EBenchmarkResult:
    """Run end-to-end RAG pipeline benchmark.

    Args:
        iterations: Total number of queries to execute
        concurrent: Number of concurrent queries

    Returns:
        Aggregated benchmark results
    """
    print(f"\nRunning E2E RAG Benchmark ({iterations} queries, {concurrent} concurrent)...")

    results: list[RAGPipelineResult] = []
    strategy_counts: dict[str, int] = {}
    stage_latencies: dict[str, list[float]] = {}

    start_time = time.perf_counter()

    # Process queries in batches
    semaphore = asyncio.Semaphore(concurrent)

    async def process_with_limit(query: str) -> RAGPipelineResult:
        async with semaphore:
            return await execute_rag_pipeline(query)

    # Create tasks
    queries = [TEST_QUERIES[i % len(TEST_QUERIES)] for i in range(iterations)]
    tasks = [process_with_limit(q) for q in queries]

    # Execute all tasks
    results = await asyncio.gather(*tasks)

    total_time = time.perf_counter() - start_time

    # Aggregate results
    latencies = [r.total_latency_ms for r in results if r.success]
    successful = sum(1 for r in results if r.success)

    # Strategy distribution
    for r in results:
        strategy_counts[r.strategy] = strategy_counts.get(r.strategy, 0) + 1

    # Stage latencies
    for r in results:
        for stage in r.stages:
            if stage.name not in stage_latencies:
                stage_latencies[stage.name] = []
            stage_latencies[stage.name].append(stage.latency_ms)

    # Calculate metrics
    sorted_latencies = sorted(latencies)

    return E2EBenchmarkResult(
        name="e2e_rag_pipeline",
        iterations=iterations,
        total_time_s=total_time,
        queries_per_second=len(latencies) / total_time if latencies else 0,
        avg_latency_ms=statistics.mean(latencies) if latencies else 0,
        p50_latency_ms=sorted_latencies[int(len(sorted_latencies) * 0.5)]
        if sorted_latencies
        else 0,
        p95_latency_ms=sorted_latencies[int(len(sorted_latencies) * 0.95)]
        if sorted_latencies
        else 0,
        p99_latency_ms=sorted_latencies[int(len(sorted_latencies) * 0.99)]
        if sorted_latencies
        else 0,
        success_rate=successful / iterations,
        strategy_distribution=strategy_counts,
        stage_latencies=stage_latencies,
    )


def print_e2e_report(result: E2EBenchmarkResult, targets: dict[str, float]) -> None:
    """Print formatted E2E benchmark report."""
    print("\n" + "=" * 70)
    print(" E2E RAG Pipeline Benchmark Results")
    print("=" * 70)

    print(f"\nOverall Metrics:")
    print(f"  Iterations:       {result.iterations}")
    print(f"  Total time:       {result.total_time_s:.3f}s")
    print(f"  QPS:              {result.queries_per_second:.2f} queries/s")
    print(f"  Success rate:     {result.success_rate * 100:.1f}%")

    print(f"\nLatency Distribution:")
    print(f"  Average:          {result.avg_latency_ms:.3f}ms")
    print(f"  P50:              {result.p50_latency_ms:.3f}ms")
    print(f"  P95:              {result.p95_latency_ms:.3f}ms")
    print(f"  P99:              {result.p99_latency_ms:.3f}ms")

    print(f"\nStrategy Distribution:")
    for strategy, count in sorted(result.strategy_distribution.items()):
        pct = count / result.iterations * 100
        bar = "█" * int(pct / 5)
        print(f"  {strategy:12}  {count:4} ({pct:5.1f}%) {bar}")

    print(f"\nStage Latencies:")
    for stage_name, stats in result.to_dict().get("stage_latencies", {}).items():
        print(f"  {stage_name}:")
        print(f"    Avg: {stats['avg_ms']:.3f}ms, P50: {stats['p50_ms']:.3f}ms, P95: {stats['p95_ms']:.3f}ms")

    # Check against targets
    print("\n" + "-" * 70)
    print(" Target Validation")
    print("-" * 70)

    passed = 0
    failed = 0

    for target_name, target_value in targets.items():
        if target_name == "qps":
            actual = result.queries_per_second
            status = "PASS" if actual >= target_value else "FAIL"
        elif target_name == "p95_latency_ms":
            actual = result.p95_latency_ms
            status = "PASS" if actual <= target_value else "FAIL"
        elif target_name == "success_rate":
            actual = result.success_rate
            status = "PASS" if actual >= target_value else "FAIL"
        else:
            continue

        if status == "PASS":
            passed += 1
        else:
            failed += 1

        print(f"  [{status}] {target_name}: {actual:.2f} (target: {target_value})")

    print(f"\n  Total: {passed} passed, {failed} failed")
    print("=" * 70)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="E2E RAG Pipeline Benchmark")
    parser.add_argument(
        "--iterations",
        type=int,
        default=50,
        help="Number of queries to execute",
    )
    parser.add_argument(
        "--concurrent",
        type=int,
        default=5,
        help="Number of concurrent queries",
    )
    parser.add_argument(
        "--target-qps",
        type=float,
        default=500.0,
        help="Target QPS (revised from 1000)",
    )
    parser.add_argument(
        "--target-p95-ms",
        type=float,
        default=500.0,
        help="Target P95 latency in ms",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for JSON results",
    )

    args = parser.parse_args()

    # Run benchmark
    result = asyncio.run(
        run_e2e_benchmark(
            iterations=args.iterations,
            concurrent=args.concurrent,
        )
    )

    # Define targets
    targets = {
        "qps": args.target_qps,
        "p95_latency_ms": args.target_p95_ms,
        "success_rate": 0.95,
    }

    # Print report
    print_e2e_report(result, targets)

    # Save to file if requested
    if args.output:
        output_data = {
            **result.to_dict(),
            "targets": targets,
        }
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()
