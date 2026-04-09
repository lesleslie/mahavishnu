"""Unit tests for core.observability (fallback mode)."""

from __future__ import annotations

import builtins
from datetime import UTC, datetime, timedelta
import importlib
import runpy
from types import SimpleNamespace
import sys
import types

import pytest

import mahavishnu.core.observability as obs


class _Counter:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict | None]] = []

    def add(self, amount: int, attributes: dict[str, str] = None):  # type: ignore[override]
        self.calls.append((amount, attributes))


class _Histogram:
    def __init__(self) -> None:
        self.calls: list[tuple[float, dict | None]] = []

    def record(self, amount: float, attributes: dict[str, str] = None):  # type: ignore[override]
        self.calls.append((amount, attributes))


class _Tracer:
    def start_as_current_span(self, name: str, attributes: dict[str, str] = None):  # type: ignore[override]
        class _Span:
            def __enter__(self):
                return self

            def __exit__(self, *args):  # noqa: ANN002,ANN003
                return None

        self.last_name = name
        self.last_attributes = attributes
        return _Span()


class _Meter:
    def create_counter(self, name: str, **kwargs):  # noqa: ANN002,ANN003
        return _Counter()

    def create_histogram(self, name: str, **kwargs):  # noqa: ANN002,ANN003
        return _Histogram()

    def create_up_down_counter(self, name: str, **kwargs):  # noqa: ANN002,ANN003
        return _Counter()


class _TraceProvider:
    def __init__(self, resource=None) -> None:
        self.resource = resource
        self.processors: list[object] = []

    def add_span_processor(self, processor: object) -> None:
        self.processors.append(processor)


class _MetricReader:
    def __init__(self, exporter: object) -> None:
        self.exporter = exporter


class _BatchSpanProcessor:
    def __init__(self, exporter: object) -> None:
        self.exporter = exporter


class _Exporter:
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint


class _Resource:
    @staticmethod
    def create(attrs: dict[str, str]) -> dict[str, str]:
        return attrs


class _SystemMetricsInstrumentor:
    called = 0

    def instrument(self) -> None:
        _SystemMetricsInstrumentor.called += 1


class _MetricsAPI:
    def __init__(self) -> None:
        self.provider = None
        self.meter = _Meter()

    def set_meter_provider(self, provider: object) -> None:
        self.provider = provider

    def get_meter(self, _name: str) -> _Meter:
        return self.meter


class _TraceAPI:
    def __init__(self) -> None:
        self.provider = None
        self.tracer = _Tracer()

    def set_tracer_provider(self, provider: object) -> None:
        self.provider = provider

    def get_tracer(self, _name: str) -> _Tracer:
        return self.tracer


@pytest.fixture(autouse=True)
def _force_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(obs, "OTEL_AVAILABLE", False)
    # Ensure fallback classes exist even if OTEL imports succeeded in environment.
    monkeypatch.setattr(obs, "MockTracer", _Tracer, raising=False)
    monkeypatch.setattr(obs, "MockMeter", _Meter, raising=False)
    monkeypatch.setattr(obs, "MockCounter", _Counter, raising=False)
    monkeypatch.setattr(obs, "MockHistogram", _Histogram, raising=False)
    monkeypatch.setattr(obs, "MockUpDownCounter", _Counter, raising=False)


def _config(metrics_enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        observability=SimpleNamespace(metrics_enabled=metrics_enabled, otlp_endpoint="http://otel"),
        log_level="INFO",
    )


def test_fallback_mock_classes_methods_are_executable() -> None:
    counter = obs.MockCounter()
    counter.add(1, {"k": "v"})
    histogram = obs.MockHistogram()
    histogram.record(1.5, {"k": "v"})
    up_down = obs.MockUpDownCounter()
    up_down.add(-1, {"k": "v"})

    tracer = obs.MockTracer()
    with tracer.start_as_current_span("span", attributes={"a": "b"}):
        pass

    meter = obs.MockMeter()
    assert meter.create_counter("c") is not None
    assert meter.create_histogram("h") is not None
    assert meter.create_up_down_counter("u") is not None

    assert obs.MockTraceProvider().get_tracer("x") is not None
    assert obs.MockMeterProvider().get_meter("x") is not None


def test_module_import_success_branch_sets_otel_available(monkeypatch: pytest.MonkeyPatch) -> None:
    opentelemetry_mod = types.ModuleType("opentelemetry")
    metrics_mod = types.ModuleType("opentelemetry.metrics")
    trace_mod = types.ModuleType("opentelemetry.trace")
    metric_exporter_mod = types.ModuleType("opentelemetry.exporter.otlp.proto.grpc.metric_exporter")
    trace_exporter_mod = types.ModuleType("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
    system_metrics_mod = types.ModuleType("opentelemetry.instrumentation.system_metrics")
    sdk_metrics_mod = types.ModuleType("opentelemetry.sdk.metrics")
    sdk_metrics_export_mod = types.ModuleType("opentelemetry.sdk.metrics.export")
    sdk_resources_mod = types.ModuleType("opentelemetry.sdk.resources")
    sdk_trace_mod = types.ModuleType("opentelemetry.sdk.trace")
    sdk_trace_export_mod = types.ModuleType("opentelemetry.sdk.trace.export")

    metric_exporter_mod.OTLPMetricExporter = object
    trace_exporter_mod.OTLPSpanExporter = object
    system_metrics_mod.SystemMetricsInstrumentor = object
    sdk_metrics_mod.MeterProvider = object
    sdk_metrics_export_mod.PeriodicExportingMetricReader = object
    sdk_resources_mod.Resource = object
    sdk_trace_mod.TracerProvider = object
    sdk_trace_export_mod.BatchSpanProcessor = object

    monkeypatch.setitem(sys.modules, "opentelemetry", opentelemetry_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.metrics", metrics_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", trace_mod)
    monkeypatch.setitem(
        sys.modules,
        "opentelemetry.exporter.otlp.proto.grpc.metric_exporter",
        metric_exporter_mod,
    )
    monkeypatch.setitem(
        sys.modules,
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
        trace_exporter_mod,
    )
    monkeypatch.setitem(sys.modules, "opentelemetry.instrumentation.system_metrics", system_metrics_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.metrics", sdk_metrics_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.metrics.export", sdk_metrics_export_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.resources", sdk_resources_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace", sdk_trace_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.export", sdk_trace_export_mod)

    reloaded = importlib.reload(obs)
    assert reloaded.OTEL_AVAILABLE is True

def test_init_uses_fallback_components() -> None:
    manager = obs.ObservabilityManager(_config(metrics_enabled=False))
    assert manager.create_workflow_counter() is not None
    assert manager.create_repo_counter() is not None
    assert manager.create_error_counter() is not None


def test_logging_helpers_and_get_logs_filters() -> None:
    manager = obs.ObservabilityManager(_config())
    manager.log_debug("d")
    manager.log_info("i", {"x": 1}, trace_id="t1")
    manager.log_warning("w")
    manager.log_error("e")
    manager.log_critical("c")

    assert len(manager.logs) == 5
    assert manager.get_logs(limit=2)[0].message in {"e", "c"}
    only_error = manager.get_logs(level=obs.LogLevel.ERROR)
    assert len(only_error) == 1
    assert only_error[0].message == "e"

    future = datetime.now(tz=UTC) + timedelta(days=1)
    assert manager.get_logs(since=future) == []


def test_start_and_end_workflow_trace_records_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = obs.ObservabilityManager(_config())
    histogram = _Histogram()
    manager.workflow_duration_histogram = histogram

    times = iter([100.0, 130.0, 140.0])
    monkeypatch.setattr(obs.time, "time", lambda: next(times))

    span = manager.start_workflow_trace("wf-1", "agno", "workflow")
    assert span is not None
    assert "wf-1" in manager.workflow_performance

    manager.end_workflow_trace("wf-1", status="completed")
    assert "wf-1" not in manager.workflow_performance
    assert histogram.calls
    amount, attrs = histogram.calls[0]
    assert amount == 30.0
    assert attrs["workflow.id"] == "wf-1"
    assert attrs["workflow.status"] == "completed"

    # no-op for missing workflow id
    manager.end_workflow_trace("missing")


def test_repo_trace_and_processing_metric_record() -> None:
    manager = obs.ObservabilityManager(_config())
    histogram = _Histogram()
    manager.repo_processing_duration_histogram = histogram

    span = manager.start_repo_trace("/tmp/myrepo", "wf-2")
    assert span is not None

    manager.record_repo_processing_time("/tmp/myrepo", "wf-2", 4.5)
    assert histogram.calls == [(4.5, {"repo.path": "/tmp/myrepo", "workflow.id": "wf-2"})]


def test_get_performance_metrics_counts_recent_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = obs.ObservabilityManager(_config())
    manager.workflow_performance["wf-a"] = {
        "start_time": 90.0,
        "adapter": "prefect",
        "task_type": "workflow",
    }
    manager.workflow_performance["wf-b"] = {
        "start_time": 95.0,
        "adapter": "agno",
        "task_type": "ai_task",
    }
    monkeypatch.setattr(obs.time, "time", lambda: 100.0)

    manager.log_info("ok")
    manager.log_error("err")
    manager.log_critical("crit")

    metrics = manager.get_performance_metrics()
    assert metrics["active_workflows"] == 2
    assert metrics["active_workflow_durations"]["wf-a"] == 10.0
    assert metrics["active_workflow_durations"]["wf-b"] == 5.0
    assert metrics["total_logs"] == 3
    assert metrics["recent_errors"] == 2


@pytest.mark.asyncio
async def test_flush_metrics_and_shutdown_noop_when_otel_unavailable() -> None:
    manager = obs.ObservabilityManager(_config())
    await manager.flush_metrics()
    manager.shutdown()


def test_init_helper_and_global_getter() -> None:
    manager = obs.init_observability(_config())
    assert isinstance(manager, obs.ObservabilityManager)
    assert obs.get_observability_manager() is None


def test_observe_decorator_and_span_alias() -> None:
    @obs.observe("custom-span")
    def add(a: int, b: int) -> int:
        return a + b

    @obs.span("another-span")
    def mul(a: int, b: int) -> int:
        return a * b

    assert add(2, 3) == 5
    assert mul(2, 3) == 6


def test_init_otel_components_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics_api = _MetricsAPI()
    trace_api = _TraceAPI()

    monkeypatch.setattr(obs, "OTEL_AVAILABLE", True)
    monkeypatch.setattr(obs, "Resource", _Resource, raising=False)
    monkeypatch.setattr(obs, "TracerProvider", _TraceProvider, raising=False)
    monkeypatch.setattr(obs, "BatchSpanProcessor", _BatchSpanProcessor, raising=False)
    monkeypatch.setattr(obs, "OTLPSpanExporter", _Exporter, raising=False)
    monkeypatch.setattr(obs, "PeriodicExportingMetricReader", _MetricReader, raising=False)
    monkeypatch.setattr(obs, "OTLPMetricExporter", _Exporter, raising=False)
    monkeypatch.setattr(obs, "MeterProvider", lambda **kwargs: SimpleNamespace(**kwargs), raising=False)
    monkeypatch.setattr(obs, "SystemMetricsInstrumentor", _SystemMetricsInstrumentor, raising=False)
    monkeypatch.setattr(obs, "metrics", metrics_api, raising=False)
    monkeypatch.setattr(obs, "trace", trace_api, raising=False)

    manager = obs.ObservabilityManager(_config(metrics_enabled=True))
    assert manager.tracer is trace_api.tracer
    assert manager.meter is metrics_api.meter
    assert _SystemMetricsInstrumentor.called >= 1
    assert manager.create_workflow_counter() is not None


def test_init_otel_components_failure_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(obs, "OTEL_AVAILABLE", True)

    class _BadResource:
        @staticmethod
        def create(_attrs: dict[str, str]):
            raise RuntimeError("otel init failed")

    monkeypatch.setattr(obs, "Resource", _BadResource, raising=False)
    monkeypatch.setattr(obs, "MockTracer", _Tracer, raising=False)
    monkeypatch.setattr(obs, "MockMeter", _Meter, raising=False)

    manager = obs.ObservabilityManager(_config(metrics_enabled=True))
    assert manager.create_workflow_counter() is not None
    assert isinstance(manager.meter, _Meter)


@pytest.mark.asyncio
async def test_flush_and_shutdown_otel_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(obs, "OTEL_AVAILABLE", True)
    manager = obs.ObservabilityManager(_config(metrics_enabled=False))

    class _Provider:
        def __init__(self) -> None:
            self.flush_called = 0
            self.shutdown_called = 0

        def force_flush(self) -> None:
            self.flush_called += 1

        def shutdown(self) -> None:
            self.shutdown_called += 1

    meter_provider = _Provider()
    trace_provider = _Provider()

    metrics_mod = types.ModuleType("opentelemetry.metrics")
    metrics_mod.get_meter_provider = lambda: meter_provider  # type: ignore[attr-defined]
    trace_mod = types.ModuleType("opentelemetry.trace")
    trace_mod.get_tracer_provider = lambda: trace_provider  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "opentelemetry.metrics", metrics_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", trace_mod)

    await manager.flush_metrics()
    manager.shutdown()
    assert meter_provider.flush_called == 1
    assert trace_provider.flush_called == 1
    assert meter_provider.shutdown_called == 1
    assert trace_provider.shutdown_called == 1


@pytest.mark.asyncio
async def test_flush_and_shutdown_otel_exception_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(obs, "OTEL_AVAILABLE", True)
    manager = obs.ObservabilityManager(_config(metrics_enabled=False))

    class _BadProvider:
        def force_flush(self) -> None:
            raise RuntimeError("flush failed")

        def shutdown(self) -> None:
            raise RuntimeError("shutdown failed")

    bad_provider = _BadProvider()
    metrics_mod = types.ModuleType("opentelemetry.metrics")
    metrics_mod.get_meter_provider = lambda: bad_provider  # type: ignore[attr-defined]
    trace_mod = types.ModuleType("opentelemetry.trace")
    trace_mod.get_tracer_provider = lambda: bad_provider  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opentelemetry.metrics", metrics_mod)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", trace_mod)

    await manager.flush_metrics()
    manager.shutdown()


def test_import_error_branch_defines_fallback_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError("otel unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    for module_name in [name for name in sys.modules if name == "opentelemetry" or name.startswith("opentelemetry.")]:
        monkeypatch.delitem(sys.modules, module_name, raising=False)
    namespace = runpy.run_module("mahavishnu.core.observability", run_name="__observability_fallback__")

    assert namespace["OTEL_AVAILABLE"] is False
    counter = namespace["MockCounter"]()
    counter.add(1, {"k": "v"})
    histogram = namespace["MockHistogram"]()
    histogram.record(1.5, {"k": "v"})
    up_down = namespace["MockUpDownCounter"]()
    up_down.add(-1, {"k": "v"})

    tracer = namespace["MockTraceProvider"]().get_tracer("x")
    with tracer.start_as_current_span("span", attributes={"a": "b"}) as span:
        span.set_attribute("key", "value")

    meter = namespace["MockMeterProvider"]().get_meter("x")
    assert meter.create_counter("c").__class__.__name__ == "MockCounter"
    assert meter.create_histogram("h").__class__.__name__ == "MockHistogram"
    assert meter.create_up_down_counter("u").__class__.__name__ == "MockUpDownCounter"
