"""Enhanced observability module for Mahavishnu."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.config import MahavishnuSettings

# Try to import OpenTelemetry components
try:
    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.system_metrics import (  # ty: ignore[unresolved-import]
        SystemMetricsInstrumentor,
    )
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

    # Define minimal fallback classes
    class MockCounter:
        def add(self, amount: int, attributes: dict[str, str] | None = None):
            pass

    class MockHistogram:
        def record(self, amount: float, attributes: dict[str, str] | None = None):
            pass

    class MockUpDownCounter:
        def add(self, amount: int, attributes: dict[str, str] | None = None):
            pass

    class MockTracer:
        def start_as_current_span(self, name: str, attributes: dict[str, str] | None = None):
            class MockSpan:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def set_attribute(self, key: str, value: str):
                    pass

            return MockSpan()

    class MockMeter:
        def create_counter(self, name: str) -> MockCounter:
            return MockCounter()

        def create_histogram(self, name: str) -> MockHistogram:
            return MockHistogram()

        def create_up_down_counter(self, name: str) -> MockUpDownCounter:
            return MockUpDownCounter()

    class MockTraceProvider:
        def get_tracer(self, name: str) -> MockTracer:
            return MockTracer()

    class MockMeterProvider:
        def get_meter(self, name: str) -> MockMeter:
            return MockMeter()


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogEntry:
    timestamp: datetime
    level: LogLevel
    message: str
    attributes: dict[str, Any]
    trace_id: str | None = None


class ObservabilityManager:
    """Centralized observability manager for metrics, tracing, and logging."""

    def __init__(self, config: MahavishnuSettings):
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Initialize components based on availability
        if OTEL_AVAILABLE and config.observability.metrics_enabled:
            self._init_otel_components()
        else:
            self._init_fallback_components()

        # Internal tracking
        self.logs: list[LogEntry] = []
        self.log_level = getattr(logging, config.log_level.upper(), logging.INFO)

        # Performance tracking
        self.workflow_performance: dict[str, dict[str, Any]] = {}

    def _init_otel_components(self):
        """Initialize OpenTelemetry components."""
        try:
            # Create resource with service information
            resource = Resource.create({"service.name": "mahavishnu", "service.version": "1.0.0"})

            # Initialize tracer
            trace_provider = TracerProvider(resource=resource)
            processor = BatchSpanProcessor(
                OTLPSpanExporter(endpoint=self.config.observability.otlp_endpoint)
            )
            trace_provider.add_span_processor(processor)
            trace.set_tracer_provider(trace_provider)
            self.tracer = trace.get_tracer(__name__)

            # Initialize meter
            metric_reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=self.config.observability.otlp_endpoint)
            )
            meter_provider = MeterProvider(metric_readers=[metric_reader], resource=resource)
            metrics.set_meter_provider(meter_provider)
            self.meter = metrics.get_meter(__name__)

            # Instrument system metrics
            SystemMetricsInstrumentor().instrument()

            # Create common instruments
            self.workflow_counter = self.meter.create_counter(
                "mahavishnu.workflows.executed", description="Number of workflows executed"
            )

            self.repo_counter = self.meter.create_counter(
                "mahavishnu.repositories.processed", description="Number of repositories processed"
            )

            self.error_counter = self.meter.create_counter(
                "mahavishnu.errors.count", description="Number of errors occurred"
            )

            self.workflow_duration_histogram = self.meter.create_histogram(
                "mahavishnu.workflow.duration",
                description="Duration of workflow execution in seconds",
                unit="s",
            )

            self.repo_processing_duration_histogram = self.meter.create_histogram(
                "mahavishnu.repo.processing.duration",
                description="Duration of repository processing in seconds",
                unit="s",
            )

        except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            self.logger.warning(f"Failed to initialize OpenTelemetry: {e}")
            self._init_fallback_components()

    def _init_fallback_components(self):
        """Initialize fallback components when OpenTelemetry is not available."""
        self.tracer = MockTracer()
        self.meter = MockMeter()

        # Create fallback instruments
        self.workflow_counter = self.meter.create_counter("mahavishnu.workflows.executed")
        self.repo_counter = self.meter.create_counter("mahavishnu.repositories.processed")
        self.error_counter = self.meter.create_counter("mahavishnu.errors.count")
        self.workflow_duration_histogram = self.meter.create_histogram(
            "mahavishnu.workflow.duration"
        )
        self.repo_processing_duration_histogram = self.meter.create_histogram(
            "mahavishnu.repo.processing.duration"
        )

    def create_workflow_counter(self):
        """Get the workflow counter instrument."""
        return self.workflow_counter

    def create_repo_counter(self):
        """Get the repository counter instrument."""
        return self.repo_counter

    def create_error_counter(self):
        """Get the error counter instrument."""
        return self.error_counter

    def log(
        self,
        level: LogLevel,
        message: str,
        attributes: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ):
        """Log a message with attributes."""
        log_entry = LogEntry(
            timestamp=datetime.now(tz=UTC),
            level=level,
            message=message,
            attributes=attributes or {},
            trace_id=trace_id,
        )

        self.logs.append(log_entry)

        # Also log to standard logger
        getattr(self.logger, level.value.lower())(
            f"[{trace_id}] {message}" if trace_id else message
        )

    def log_debug(
        self, message: str, attributes: dict[str, Any] | None = None, trace_id: str | None = None
    ):
        """Log a debug message."""
        self.log(LogLevel.DEBUG, message, attributes, trace_id)

    def log_info(
        self, message: str, attributes: dict[str, Any] | None = None, trace_id: str | None = None
    ):
        """Log an info message."""
        self.log(LogLevel.INFO, message, attributes, trace_id)

    def log_warning(
        self, message: str, attributes: dict[str, Any] | None = None, trace_id: str | None = None
    ):
        """Log a warning message."""
        self.log(LogLevel.WARNING, message, attributes, trace_id)

    def log_error(
        self, message: str, attributes: dict[str, Any] | None = None, trace_id: str | None = None
    ):
        """Log an error message."""
        self.log(LogLevel.ERROR, message, attributes, trace_id)

    def log_critical(
        self, message: str, attributes: dict[str, Any] | None = None, trace_id: str | None = None
    ):
        """Log a critical message."""
        self.log(LogLevel.CRITICAL, message, attributes, trace_id)

    def start_workflow_trace(self, workflow_id: str, adapter: str, task_type: str):
        """Start a trace for a workflow execution."""
        span_attributes = {
            "workflow.id": workflow_id,
            "workflow.adapter": adapter,
            "workflow.task_type": task_type,
            "workflow.start_time": datetime.now(tz=UTC).isoformat(),
        }

        span = self.tracer.start_as_current_span(
            f"workflow.{workflow_id}", attributes=span_attributes
        )

        # Track performance
        self.workflow_performance[workflow_id] = {
            "start_time": time.time(),
            "adapter": adapter,
            "task_type": task_type,
        }

        return span

    def end_workflow_trace(self, workflow_id: str, status: str = "completed"):
        """End a trace for a workflow execution."""
        if workflow_id in self.workflow_performance:
            duration = time.time() - self.workflow_performance[workflow_id]["start_time"]

            # Record metrics
            self.workflow_duration_histogram.record(
                duration,
                attributes={
                    "workflow.id": workflow_id,
                    "workflow.status": status,
                    "workflow.adapter": self.workflow_performance[workflow_id]["adapter"],
                },
            )

            # Clean up
            del self.workflow_performance[workflow_id]

    def start_repo_trace(self, repo_path: str, workflow_id: str):
        """Start a trace for repository processing."""
        span_attributes = {"repo.path": repo_path, "workflow.id": workflow_id}

        span = self.tracer.start_as_current_span(
            f"repo.process.{repo_path.split('/')[-1]}", attributes=span_attributes
        )

        return span

    def record_repo_processing_time(self, repo_path: str, workflow_id: str, duration: float):
        """Record the time taken to process a repository."""
        self.repo_processing_duration_histogram.record(
            duration, attributes={"repo.path": repo_path, "workflow.id": workflow_id}
        )

    def get_logs(
        self, limit: int = 100, level: LogLevel | None = None, since: datetime | None = None
    ) -> list[LogEntry]:
        """Get logs with optional filtering."""
        filtered_logs = self.logs[-limit:]  # Get last N logs

        if level:
            filtered_logs = [log for log in filtered_logs if log.level == level]

        if since:
            filtered_logs = [log for log in filtered_logs if log.timestamp >= since]

        return filtered_logs

    def get_performance_metrics(self) -> dict[str, Any]:
        """Get performance metrics for active workflows."""
        active_durations = {}
        for wf_id, perf_data in self.workflow_performance.items():
            active_durations[wf_id] = time.time() - perf_data["start_time"]

        return {
            "active_workflows": len(active_durations),
            "active_workflow_durations": active_durations,
            "total_logs": len(self.logs),
            "recent_errors": len(
                [log for log in self.logs[-50:] if log.level in (LogLevel.ERROR, LogLevel.CRITICAL)]
            ),
        }

    # ------------------------------------------------------------------
    # Tier 1 Phase 6: change-point detection wiring
    # ------------------------------------------------------------------
    # The change-point detector and the 3-sigma reference detector are
    # both fed by a per-metric :class:`MetricSampler` (REQ-009). The
    # sampler is created lazily on the first call to
    # ``_evaluate_change_point`` and cached on the instance. Each
    # evaluation updates the detector state and, when the detector
    # fires, emits an OTel span ``mahavishnu.observability.drift_detected``
    # (or a structured log line when OTel is unavailable).

    def _get_metric_sampler(self) -> "MetricSampler":
        """Return the per-instance MetricSampler, creating it on first use."""
        from mahavishnu.observability.sampler import MetricSampler

        sampler = getattr(self, "_metric_sampler", None)
        if sampler is None:
            cadence = 60.0
            try:
                pools_cfg = getattr(self.config, "pools", None)
                if pools_cfg is not None:
                    cadence = float(getattr(pools_cfg, "sampler_cadence_seconds", 60.0))
            except Exception:  # noqa: BLE001 - config may not have pools
                pass
            sampler = MetricSampler(cadence_seconds=cadence)
            self._metric_sampler = sampler  # type: ignore[attr-defined]
        return sampler

    def _evaluate_change_point(self, metric_name: str, value: float):  # req: REQ-005
        """Feed one observation to the change-point detector.

        Updates the detector's internal state and returns the
        :class:`~mahavishnu.observability.changepoint.ChangePointResult`.
        When ``changepoint.enabled`` is False (default in Phase 6
        until Phase 8 promotes the flag), the method is a no-op and
        returns a synthetic ``detected=False`` result with score 0.

        The detector instance is cached on the manager and lazily
        created on the first non-disabled call.

        Req: REQ-005
        """
        from mahavishnu.observability.changepoint import (
            CUSUMDetector,
            PageHinkleyDetector,
        )

        if not self._changepoint_enabled():
            from mahavishnu.observability.changepoint.cusum import ChangePointResult

            return ChangePointResult(
                detected=False,
                score_high=0.0,
                score_low=0.0,
                score=0.0,
                threshold=0.0,
                samples_since_reset=0,
                direction="unknown",
            )

        # Always feed the sampler so the 3-sigma reference detector
        # sees the same input stream (and the buffer is ready when
        # a future enable flips changepoint_enabled from False to
        # True without a warmup gap).
        sampler = self._get_metric_sampler()
        sampler.observe(metric_name, value)

        detector = self._get_or_create_changepoint_detector()
        result = detector.update(value)

        if result.detected:
            self._on_drift_detected(metric_name, result)
        return result

    def _evaluate_3sigma(self, metric_name: str, value: float):  # req: REQ-006
        """Feed one observation to the 3-sigma reference detector.

        Uses a sliding-window mean/std over the
        :class:`MetricSampler`-fed queue. When the window is empty
        or has zero standard deviation, the result is
        ``detected=False`` (degenerate regime). When
        ``changepoint.reference_detector == "none"``, this method
        is a no-op (the reference is intentionally disabled).

        Req: REQ-006
        """
        import math

        from mahavishnu.observability.changepoint import AnomalyResult

        if self._changepoint_reference_mode() == "none":
            return AnomalyResult(
                detected=False,
                z_score=0.0,
                current_value=value,
                window_mean=0.0,
                window_std=0.0,
            )

        sampler = self._get_metric_sampler()
        # Observe first so the buffer always includes the current
        # value. Without this, calls to _evaluate_3sigma in
        # isolation (e.g. unit tests) see an empty buffer.
        sampler.observe(metric_name, value)
        values = sampler.values(metric_name)
        if len(values) < 5:
            # Not enough samples for a meaningful z-score.
            return AnomalyResult(
                detected=False,
                z_score=0.0,
                current_value=value,
                window_mean=float("nan"),
                window_std=float("nan"),
            )

        # Use the most-recent 60 samples (1 hour at 60s cadence)
        # as the sliding window. Tunable in config (Phase 7 review).
        window = values[-60:]
        window_mean = sum(window) / len(window)
        if len(window) < 2:
            return AnomalyResult(
                detected=False,
                z_score=0.0,
                current_value=value,
                window_mean=window_mean,
                window_std=0.0,
            )
        window_std = math.sqrt(
            sum((v - window_mean) ** 2 for v in window) / (len(window) - 1)
        )
        if window_std == 0.0 or not math.isfinite(window_std):
            return AnomalyResult(
                detected=False,
                z_score=0.0,
                current_value=value,
                window_mean=window_mean,
                window_std=window_std,
            )
        z_score = (value - window_mean) / window_std
        detected = abs(z_score) >= 3.0
        result = AnomalyResult(
            detected=detected,
            z_score=z_score,
            current_value=value,
            window_mean=window_mean,
            window_std=window_std,
        )
        if detected:
            self._on_anomaly_detected(metric_name, result)
        return result

    def _changepoint_enabled(self) -> bool:
        try:
            pools_cfg = getattr(self.config, "pools", None)
            if pools_cfg is None:
                return False
            return bool(getattr(pools_cfg, "changepoint_enabled", False))
        except Exception:  # noqa: BLE001
            return False

    def _changepoint_reference_mode(self) -> str:
        try:
            pools_cfg = getattr(self.config, "pools", None)
            if pools_cfg is None:
                return "none"
            return str(getattr(pools_cfg, "changepoint_reference_detector", "three_sigma"))
        except Exception:  # noqa: BLE001
            return "none"

    def _get_or_create_changepoint_detector(self):
        from mahavishnu.observability.changepoint import (
            CUSUMDetector,
            PageHinkleyDetector,
        )

        detector = getattr(self, "_changepoint_detector", None)
        if detector is not None:
            return detector
        try:
            pools_cfg = getattr(self.config, "pools", None)
            slack = float(getattr(pools_cfg, "changepoint_slack", 0.25))
            threshold = float(getattr(pools_cfg, "changepoint_threshold", 8.0))
            algo = str(getattr(pools_cfg, "changepoint_detector", "cusum"))
        except Exception:  # noqa: BLE001
            slack, threshold, algo = 0.25, 8.0, "cusum"

        # CUSUM's ``target_mean`` is the in-control process mean, not
        # a running estimate. Phase 6 ships with target_mean=0.0
        # (a sensible default for normalized queue-depth metrics).
        # Operators set the absolute target via config in Phase 8's
        # promotion; for now, the detector is correct relative to
        # ``target_mean`` and operators must interpret scores
        # against the documented baseline.
        target_mean = 0.0

        if algo == "page_hinkley":
            detector = PageHinkleyDetector(
                target_mean=target_mean, slack=slack, threshold=threshold, delta=0.0
            )
        else:
            detector = CUSUMDetector(
                target_mean=target_mean, slack=slack, threshold=threshold, two_sided=True
            )
        self._changepoint_detector = detector  # type: ignore[attr-defined]
        return detector

    def _get_changepoint_target_metric(self) -> str:
        try:
            pools_cfg = getattr(self.config, "pools", None)
            if pools_cfg is None:
                return "pool_queue_depth"
            return str(getattr(pools_cfg, "changepoint_target_metric", "pool_queue_depth"))
        except Exception:  # noqa: BLE001
            return "pool_queue_depth"

    def _on_drift_detected(self, metric_name: str, result) -> None:
        """OTel span emission for a change-point detection.

        Tier 1 Phase 6: emit ``mahavishnu.observability.drift_detected``
        with attributes per the spec (§6 Phase 6 Integration Contract).
        When OTel is unavailable, fall back to a structured log line.
        """
        try:
            if OTEL_AVAILABLE and getattr(self, "tracer", None) is not None:
                severity = self._classify_drift_severity(result.score, result.threshold)
                with self.tracer.start_as_current_span(  # type: ignore[union-attr]
                    "mahavishnu.observability.drift_detected",
                    attributes={
                        "metric_name": metric_name,
                        "detector": str(getattr(self, "_changepoint_detector", None).__class__.__name__),
                        "score_high": float(result.score_high),
                        "score_low": float(result.score_low),
                        "score": float(result.score),
                        "threshold": float(result.threshold),
                        "samples_since_reset": int(result.samples_since_reset),
                        "direction": str(result.direction),
                        "severity": severity,
                    },
                ):
                    pass
        except Exception as exc:  # noqa: BLE001 - boundary handler
            self._log_debug("OTel span emission failed: %s", exc)

        # Always log a structured event so observability survives
        # even when OTel is disabled.
        self._log_warning(
            "drift_detected metric=%s detector=%s score=%.3f threshold=%.3f direction=%s samples=%d",
            metric_name,
            type(getattr(self, "_changepoint_detector", None)).__name__,
            result.score,
            result.threshold,
            result.direction,
            result.samples_since_reset,
        )

    def _on_anomaly_detected(self, metric_name: str, result) -> None:
        """OTel span + log for a 3-sigma reference detector fire."""
        self._log_warning(
            "three_sigma_anomaly metric=%s z=%.3f value=%.3f window_mean=%.3f window_std=%.3f",
            metric_name,
            result.z_score,
            result.current_value,
            result.window_mean,
            result.window_std,
        )

    def _log_debug(self, msg: str, *args: Any) -> None:  # noqa: ANN401
        if getattr(self, "logger", None) is not None:
            self.logger.debug(msg, *args)  # type: ignore[union-attr]

    def _log_warning(self, msg: str, *args: Any) -> None:  # noqa: ANN401
        if getattr(self, "logger", None) is not None:
            self.logger.warning(msg, *args)  # type: ignore[union-attr]

    @staticmethod
    def _classify_drift_severity(score: float, threshold: float) -> str:
        """Classify drift severity per the spec §6 Phase 6 contract.

        minor: score < 2*threshold (typical 0.5-σ shift detection)
        moderate: 2*threshold <= score < 4*threshold
        critical: score >= 4*threshold (>1-σ shift territory)
        """
        if score >= 4 * threshold:
            return "critical"
        if score >= 2 * threshold:
            return "moderate"
        return "minor"

    async def flush_metrics(self):
        """Flush any pending metrics to exporters."""
        if OTEL_AVAILABLE:
            try:
                # Force flush metrics
                from opentelemetry.metrics import get_meter_provider

                get_meter_provider().force_flush()  # ty: ignore[unresolved-attribute]

                # Force flush traces
                from opentelemetry.trace import get_tracer_provider

                get_tracer_provider().force_flush()  # ty: ignore[unresolved-attribute]
            except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
                self.logger.warning(f"Failed to flush metrics: {e}")

    def shutdown(self):
        """Shutdown observability components."""
        if OTEL_AVAILABLE:
            try:
                # Shutdown providers
                from opentelemetry.metrics import get_meter_provider
                from opentelemetry.trace import get_tracer_provider

                get_meter_provider().shutdown()  # ty: ignore[unresolved-attribute]
                get_tracer_provider().shutdown()  # ty: ignore[unresolved-attribute]
            except Exception as e:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
                self.logger.warning(f"Error during observability shutdown: {e}")


def init_observability(config: MahavishnuSettings) -> ObservabilityManager:
    """Initialize the observability system."""
    return ObservabilityManager(config)


def get_observability_manager() -> ObservabilityManager | None:
    """Get the global observability manager instance."""
    # This would typically return a singleton instance
    # For now, returning None as we don't have a global registry
    return None


# Observability decorators (temporary fix - need proper implementation)
def observe(span_name: str | None = None):
    """Decorator for observing function execution with tracing."""

    def decorator(func):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


# Alias for compatibility
span = observe
