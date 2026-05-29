"""Tests for fitness analyzer signal computation and buffering."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

import mahavishnu.pools.fitness_analyzer as fitness_analyzer_module
from mahavishnu.pools.fitness_analyzer import (
    FitnessAnalyzer,
    _BufferEntry,
    _sanitize_key_component,
)
from mahavishnu.pools.routing_fitness import FitnessSignal


class FakeClient:
    """Small stand-in for BodaiComponentMCPClient."""

    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = base_url
        self.timeout = timeout
        self.closed = False
        self.traces: list[dict] = []
        self.raise_error: Exception | None = None

    async def query_local_traces(self, task_class: str, time_range_minutes: int):
        if self.raise_error is not None:
            raise self.raise_error
        return self.traces

    async def aclose(self):
        self.closed = True


class FakeCircuitBreaker:
    """Minimal circuit-breaker stand-in that awaits the provided coroutine."""

    def __init__(self):
        self.calls = 0

    async def call(self, awaitable):
        self.calls += 1
        return await awaitable


@dataclass
class FakeDharaState:
    """Simple async key-value store for analyzer tests."""

    should_fail: bool = False
    writes: list[tuple[str, dict, int]] = field(default_factory=list)

    async def put(self, key: str, value: dict, ttl: int = 0):
        if self.should_fail:
            raise RuntimeError("write failed")
        self.writes.append((key, value, ttl))
        return True


class TestKeySanitization:
    """Tests for Dhara key sanitization."""

    def test_sanitize_key_component_keeps_safe_values(self):
        assert _sanitize_key_component("least_loaded") == "least_loaded"

    def test_sanitize_key_component_rewrites_unsafe_values(self):
        assert _sanitize_key_component("task/class:bad") == "task_class_bad"

    def test_sanitize_key_component_falls_back_to_placeholder(self):
        assert _sanitize_key_component("") == "unknown"


class TestFitnessAnalyzer:
    """Tests for the analyzer's core behavior."""

    def test_constructor_clamps_poll_interval_and_dedupes_components(self):
        analyzer = FitnessAnalyzer(
            poll_interval_seconds=0,
            component_endpoints=[("a", "http://one"), ("a", "http://one")],
        )

        assert analyzer._poll_interval == 1
        assert analyzer._component_endpoints == [("a", "http://one"), ("a", "http://one")]

        analyzer.add_component("a", "http://one")
        analyzer.add_component("b", "http://two")

        assert analyzer._component_endpoints == [
            ("a", "http://one"),
            ("a", "http://one"),
            ("b", "http://two"),
        ]

    def test_compute_signal_handles_empty_trace_list(self):
        analyzer = FitnessAnalyzer()

        assert analyzer._compute_signal("code_generation", "least_loaded", []) == FitnessSignal()

    def test_compute_signal_calculates_rollup_metrics(self):
        analyzer = FitnessAnalyzer()
        before = datetime.now(UTC)
        signal = analyzer._compute_signal(
            "code_generation",
            "least_loaded",
            [
                {
                    "outcome": "ok",
                    "duration_ms": 10,
                    "component_name": "alpha",
                },
                {
                    "outcome": "error",
                    "duration_ms": 50,
                    "component_name": "beta",
                },
                {
                    "outcome": "ok",
                    "duration_ms": 100,
                    "component_name": "beta",
                },
            ],
        )
        after = datetime.now(UTC)
        updated_at = datetime.fromisoformat(signal.updated_at)

        assert signal.samples == 3
        assert signal.failure_rate == pytest.approx(1 / 3)
        assert signal.score == pytest.approx(2 / 3)
        assert signal.p99_latency_ms == 100.0
        assert signal.component_count == 2
        assert before <= updated_at <= after

    @pytest.mark.asyncio
    async def test_fetch_traces_from_component_closes_client_on_success(self, monkeypatch):
        fake_client = FakeClient("http://component")
        fake_client.traces = [{"selector": "least_loaded"}]
        monkeypatch.setattr(
            fitness_analyzer_module, "BodaiComponentMCPClient", lambda **kwargs: fake_client
        )
        analyzer = FitnessAnalyzer()

        traces = await analyzer._fetch_traces_from_component(
            "component-a",
            "http://component",
            "code_generation",
        )

        assert traces == [{"selector": "least_loaded"}]
        assert fake_client.closed is True

    @pytest.mark.asyncio
    async def test_fetch_traces_from_component_returns_empty_on_failure(self, monkeypatch):
        fake_client = FakeClient("http://component")
        fake_client.raise_error = RuntimeError("unavailable")
        monkeypatch.setattr(
            fitness_analyzer_module, "BodaiComponentMCPClient", lambda **kwargs: fake_client
        )
        analyzer = FitnessAnalyzer()

        traces = await analyzer._fetch_traces_from_component(
            "component-a",
            "http://component",
            "code_generation",
        )

        assert traces == []
        assert fake_client.closed is True

    @pytest.mark.asyncio
    async def test_collect_traces_filters_failed_fetches(self, monkeypatch):
        analyzer = FitnessAnalyzer(
            component_endpoints=[
                ("component-a", "http://one"),
                ("component-b", "http://two"),
            ]
        )

        async def fake_fetch(component_name, mcp_url, task_class, time_range_minutes=60):
            if component_name == "component-a":
                return [{"selector": "least_loaded", "duration_ms": 5}]
            raise RuntimeError("boom")

        monkeypatch.setattr(analyzer, "_fetch_traces_from_component", fake_fetch)

        traces = await analyzer._collect_traces("code_generation")

        assert traces == [{"selector": "least_loaded", "duration_ms": 5}]

    @pytest.mark.asyncio
    async def test_analyze_and_persist_collects_and_flushes_signals(self, monkeypatch):
        dhara_state = FakeDharaState()
        analyzer = FitnessAnalyzer(
            dhara_state=dhara_state,
            component_endpoints=[("component-a", "http://one")],
        )

        async def fake_collect(task_class):
            if task_class == "code_generation":
                return [
                    {
                        "selector": "least_loaded",
                        "outcome": "ok",
                        "duration_ms": 10,
                        "component_name": "alpha",
                    }
                ]
            return []

        monkeypatch.setattr(analyzer, "_collect_traces", fake_collect)

        await analyzer._analyze_and_persist()

        assert dhara_state.writes
        assert dhara_state.writes[0][0] == "routing_fitness/code_generation/least_loaded"
        assert not analyzer._buffer

    @pytest.mark.asyncio
    async def test_run_fitness_analysis_returns_buffered_signals_when_flush_is_skipped(
        self, monkeypatch
    ):
        analyzer = FitnessAnalyzer(component_endpoints=[("component-a", "http://one")])

        async def fake_collect(task_class):
            return (
                [
                    {
                        "selector": "least_loaded",
                        "outcome": "ok",
                        "duration_ms": 15,
                        "component_name": "alpha",
                    }
                ]
                if task_class == "code_generation"
                else []
            )

        async def fake_flush():
            return None

        monkeypatch.setattr(analyzer, "_collect_traces", fake_collect)
        monkeypatch.setattr(analyzer, "_flush_buffer", fake_flush)

        signals = await analyzer.run_fitness_analysis()

        assert "code_generation" in signals
        assert "least_loaded" in signals["code_generation"]
        assert signals["code_generation"]["least_loaded"].samples == 1
        assert len(analyzer._buffer) == 1

    @pytest.mark.asyncio
    async def test_run_loop_logs_and_continues_after_cycle_error(self, monkeypatch):
        analyzer = FitnessAnalyzer(poll_interval_seconds=1)
        analyzer._running = True
        calls = {"count": 0}

        async def failing_cycle():
            calls["count"] += 1
            analyzer._running = False
            raise RuntimeError("cycle failed")

        async def fake_sleep(seconds):
            return None

        monkeypatch.setattr(analyzer, "_analyze_and_persist", failing_cycle)
        monkeypatch.setattr(fitness_analyzer_module.asyncio, "sleep", fake_sleep)

        await analyzer._run_loop()

        assert calls["count"] == 1

    @pytest.mark.asyncio
    async def test_start_and_stop_manage_background_task(self, monkeypatch):
        analyzer = FitnessAnalyzer()
        started = asyncio.Event()

        async def fake_run_loop():
            started.set()
            await asyncio.sleep(0)

        monkeypatch.setattr(analyzer, "_run_loop", fake_run_loop)

        await analyzer.start()
        assert analyzer._running is True
        assert analyzer._task is not None

        await started.wait()
        first_task = analyzer._task

        await analyzer.start()
        assert analyzer._task is first_task

        await analyzer.stop()
        assert analyzer._running is False
        assert analyzer._task is None

    @pytest.mark.asyncio
    async def test_flush_buffer_writes_to_dhara_and_clears_buffer(self):
        dhara_state = FakeDharaState()
        analyzer = FitnessAnalyzer(dhara_state=dhara_state)
        analyzer._buffer.append(
            _BufferEntry(
                task_class="code_generation",
                selector="least_loaded",
                signal=FitnessSignal(score=0.8, samples=4, failure_rate=0.2),
            )
        )

        await analyzer._flush_buffer()

        assert not analyzer._buffer
        assert dhara_state.writes == [
            (
                "routing_fitness/code_generation/least_loaded",
                {
                    "score": 0.8,
                    "samples": 4,
                    "failure_rate": 0.2,
                    "p99_latency_ms": 0.0,
                    "updated_at": "",
                    "window_start": "",
                    "component_count": 0,
                },
                7200,
            )
        ]

    @pytest.mark.asyncio
    async def test_flush_buffer_returns_immediately_when_empty(self):
        analyzer = FitnessAnalyzer(dhara_state=FakeDharaState())

        await analyzer._flush_buffer()

        assert not analyzer._buffer
        assert analyzer._dlq_failures == {}

    @pytest.mark.asyncio
    async def test_flush_buffer_uses_circuit_breaker(self):
        dhara_state = FakeDharaState()
        breaker = FakeCircuitBreaker()
        analyzer = FitnessAnalyzer(dhara_state=dhara_state, circuit_breaker=breaker)
        analyzer._buffer.append(
            _BufferEntry(
                task_class="reasoning",
                selector="random",
                signal=FitnessSignal(score=0.6, samples=2, failure_rate=0.4),
            )
        )

        await analyzer._flush_buffer()

        assert breaker.calls == 1
        assert dhara_state.writes[0][0] == "routing_fitness/reasoning/random"

    @pytest.mark.asyncio
    async def test_flush_buffer_drops_after_dlq_threshold(self):
        dhara_state = FakeDharaState(should_fail=True)
        analyzer = FitnessAnalyzer(dhara_state=dhara_state)
        analyzer._buffer.append(
            _BufferEntry(
                task_class="swarm",
                selector="bad/selector",
                signal=FitnessSignal(score=0.1, samples=1, failure_rate=0.9),
            )
        )

        await analyzer._flush_buffer()

        assert not analyzer._buffer
        assert analyzer._dlq_failures == {}
        assert len(dhara_state.writes) == 0

    @pytest.mark.asyncio
    async def test_analyze_and_persist_noop_without_components(self):
        analyzer = FitnessAnalyzer()

        await analyzer._analyze_and_persist()

        assert not analyzer._buffer

    @pytest.mark.asyncio
    async def test_analyze_and_persist_returns_when_no_traces_collected(self, monkeypatch):
        analyzer = FitnessAnalyzer(
            dhara_state=FakeDharaState(),
            component_endpoints=[("component-a", "http://one")],
        )

        async def fake_collect(task_class):
            return []

        monkeypatch.setattr(analyzer, "_collect_traces", fake_collect)

        await analyzer._analyze_and_persist()

        assert not analyzer._buffer
