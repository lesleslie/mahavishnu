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

            # Tier 1 Phase 8: drift detection counter + detector-age gauge.
            # REQ-005. Without these the §7 stage-1 gate has no
            # source-of-truth metric to query. See audit CRITICAL #1 /
            # observability CRITICAL #1.
            self.drift_detected_counter = self.meter.create_counter(
                "mahavishnu.observability.drift_detected_total",
                description="CUSUM/Page-Hinkley drift detection events (per metric, detector, severity)",
            )
            self.detector_age_gauge = self.meter.create_up_down_counter(
                "mahavishnu.observability.detector_age_samples_total",
                description="Cumulative sample-age-at-fire across all fires, per metric and detector (R3-H2: renamed from detector_age_samples for cumulative semantic clarity)",
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
        # Tier 1 Phase 8: drift detection counter + detector-age gauge.
        # REQ-005. Without these the §7 stage-1 gate has no source-of-truth
        # metric to query. See audit CRITICAL #1 / observability CRITICAL #1.
        self.drift_detected_counter = self.meter.create_counter(
            "mahavishnu.observability.drift_detected_total"
        )
        self.detector_age_gauge = self.meter.create_up_down_counter(
            "mahavishnu.observability.detector_age_samples_total"
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

    def _get_metric_sampler(self) -> MetricSampler:
        """Return the per-instance MetricSampler, creating it on first use."""
        from mahavishnu.observability.sampler import MetricSampler

        sampler = getattr(self, "_metric_sampler", None)
        if sampler is None:
            cadence = 60.0
            try:
                changepoint_cfg = getattr(self.config, "changepoint", None)
                if changepoint_cfg is not None:
                    cadence = float(getattr(changepoint_cfg, "sampler_cadence_seconds", 60.0))
            except Exception:  # noqa: BLE001 - config may not have changepoint
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
        if detector is None:
            # R3-M2: target_mean_auto=True with insufficient warmup.
            # Return a synthetic "no-op" result so the call path
            # works without firing.
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
        result = detector.update(value)

        if result.detected:
            # C4: pass current_value so the OTel span can carry it.
            self._on_drift_detected(metric_name, value, result)
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
        # as the sliding window, EXCLUDING the current value.
        # Including the current value in the baseline inflates the
        # std in proportion to the spike size and masks true 3-σ
        # events. R3-M-1 (round-3 review): this was flagged in
        # round-1 and not addressed in round-2. Fixed by slicing
        # values[-61:-1] so the current observation is compared
        # against the in-control regime, not part of it.
        window = values[-61:-1]
        window_mean = sum(window) / len(window)
        if len(window) < 2:
            return AnomalyResult(
                detected=False,
                z_score=0.0,
                current_value=value,
                window_mean=window_mean,
                window_std=0.0,
            )
        window_std = math.sqrt(sum((v - window_mean) ** 2 for v in window) / (len(window) - 1))
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
            changepoint_cfg = getattr(self.config, "changepoint", None)
            if changepoint_cfg is None:
                return False
            return bool(getattr(changepoint_cfg, "enabled", False))
        except Exception:  # noqa: BLE001
            return False

    def _changepoint_reference_mode(self) -> str:
        try:
            changepoint_cfg = getattr(self.config, "changepoint", None)
            if changepoint_cfg is None:
                return "none"
            return str(getattr(changepoint_cfg, "reference_detector", "three_sigma"))
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
            changepoint_cfg = getattr(self.config, "changepoint", None)
            # R3-M1: import the production defaults from the Pydantic
            # model rather than duplicating literals. A trimmed config
            # object (e.g. a test stub with only a few attributes) used
            # to silently fall back to the LEGACY threshold=8.0 — the
            # 30x-too-sensitive value the round-2 sweep explicitly
            # replaced. ChangepointConfig() defaults are the same as
            # the documented production values.
            from mahavishnu.core.config import ChangepointConfig

            defaults = ChangepointConfig()
            slack = float(getattr(changepoint_cfg, "slack", defaults.slack))
            threshold = float(
                getattr(changepoint_cfg, "threshold", defaults.threshold)
            )
            algo = str(getattr(changepoint_cfg, "detector", defaults.detector))
            explicit_target = float(
                getattr(changepoint_cfg, "target_mean", defaults.target_mean)
            )
            use_auto = bool(
                getattr(changepoint_cfg, "target_mean_auto", defaults.target_mean_auto)
            )
            auto_window = int(
                getattr(
                    changepoint_cfg,
                    "target_mean_auto_window",
                    defaults.target_mean_auto_window,
                )
            )
        except Exception:  # noqa: BLE001
            from mahavishnu.core.config import ChangepointConfig

            defaults = ChangepointConfig()
            slack, threshold, algo = (
                defaults.slack,
                defaults.threshold,
                defaults.detector,
            )
            explicit_target, use_auto, auto_window = 0.0, False, 60

        # CUSUM's ``target_mean`` is the in-control process mean, not
        # a running estimate. If ``target_mean_auto=True`` and the
        # sampler has accumulated enough samples, prefer the rolling
        # baseline (slowly-drifting in-control mean). Otherwise honour
        # the operator's explicit value (default 0.0 — only valid for
        # normalized metrics; raw counts like pool_queue_depth need an
        # explicit per-deployment value). See the changepoint config
        # docstring and docs/runbooks/mahavishnu-drift-detection.md.
        target_mean = explicit_target
        if use_auto:
            try:
                sampler = self._get_metric_sampler()
                metric_name = self._get_changepoint_target_metric()
                recent = sampler.values(metric_name)[-auto_window:]
                if len(recent) >= max(10, auto_window // 2):
                    target_mean = sum(recent) / len(recent)
                else:
                    # R3-M2: when target_mean_auto=True and the
                    # sampler hasn't accumulated enough samples, defer
                    # detector construction entirely. Without this
                    # guard the detector was created on the first
                    # sample with target_mean=0.0 (the auto-bootstrap
                    # guard at len(recent) >= max(10, auto_window//2)
                    # fails with only 1 sample), then cached forever.
                    # Operators who set target_mean_auto=True got a
                    # permanently-broken detector with no warning.
                    self._log_warning(
                        "target_mean_auto=True but sampler has only %d "
                        "samples (need %d). Deferring detector creation; "
                        "the §7 gate is silent until the warmup window fills.",
                        len(recent),
                        max(10, auto_window // 2),
                    )
                    return None
            except Exception:  # noqa: BLE001 - sampler may not be initialized
                return None

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
            changepoint_cfg = getattr(self.config, "changepoint", None)
            if changepoint_cfg is None:
                return "pool_queue_depth"
            return str(getattr(changepoint_cfg, "target_metric", "pool_queue_depth"))
        except Exception:  # noqa: BLE001
            return "pool_queue_depth"

    def _on_drift_detected(self, metric_name: str, value: float, result) -> None:
        """OTel span + Prometheus counter emission for a drift detection.

        C6: increment ``mahavishnu.observability.drift_detected_total``
        with labels ``{metric_name, detector, severity}``. Add
        ``result.samples_since_reset`` to
        ``mahavishnu.observability.detector_age_samples_total``
        (cumulative across fires — the metric name was renamed in
        R3-H2 to make the cumulative semantic explicit).

        C4: OTel span carries the spec §6 Phase 6 attributes:
        metric_name, detector, score_high, score_low, score,
        threshold, samples_since_reset, direction, severity,
        current_value, baseline_mean, baseline_std, host,
        instance_id, trace_id, runbook_url.

        When OTel is unavailable, fall back to a structured log line
        so observability survives without OTel.
        """
        import os
        import socket

        def _resolve_runbook_url() -> str:
            """Resolve the runbook URL for OTel span emission.

            R3-L2 (round-3 review): a repo-relative path is not a
            URL — operators following it from a trace viewer at 3 a.m.
            hit a 404 because the path is not absolute. Operators can
            override via ``settings/mahavishnu.yaml`` under
            ``observability.drift_runbook_url`` or via the
            ``MAHAVISHNU_OBSERVABILITY__DRIFT_RUNBOOK_URL`` env var.
            Defaults to the repo-relative path (kept for offline /
            local-only deployments).
            """
            default = "docs/runbooks/mahavishnu-drift-detection.md"
            try:
                cfg = getattr(self.config, "observability", None)
                override = getattr(cfg, "drift_runbook_url", None)
            except Exception:  # noqa: BLE001
                override = None
            return override or default

        # R3-M5: lowercase detector name so dashboards written against
        # the documented "cusum" / "page_hinkley" tokens work.
        detector_class = type(getattr(self, "_changepoint_detector", None)).__name__
        detector_name = (
            "cusum"
            if detector_class == "CUSUMDetector"
            else "page_hinkley"
            if detector_class == "PageHinkleyDetector"
            else detector_class.lower()
        )
        severity = self._classify_drift_severity(result.score, result.threshold)

        # Compute baseline statistics from the recent sampler window
        # (60-sample default) so the on-call can compare the fire's
        # value against the in-control mean + std without leaving
        # the trace viewer.
        baseline_mean = 0.0
        baseline_std = 0.0
        try:
            recent = self._get_metric_sampler().values(metric_name)[-60:]
            if recent:
                baseline_mean = sum(recent) / len(recent)
                if len(recent) >= 2:
                    variance = sum((v - baseline_mean) ** 2 for v in recent) / (len(recent) - 1)
                    baseline_std = math.sqrt(variance) if variance > 0 else 0.0
        except Exception:  # noqa: BLE001 - boundary handler
            pass

        trace_id_str = ""
        if OTEL_AVAILABLE:
            try:
                from opentelemetry import trace as _otel_trace

                ctx_span = _otel_trace.get_current_span()
                ctx = ctx_span.get_span_context() if ctx_span else None
                if ctx and ctx.trace_id:
                    trace_id_str = _otel_trace.format_trace_id(ctx.trace_id)
            except Exception:  # noqa: BLE001 - OTel not initialized
                pass

        span_attributes = {
            "metric_name": metric_name,
            "detector": detector_name,
            "score_high": float(result.score_high),
            "score_low": float(result.score_low),
            "score": float(result.score),
            "threshold": float(result.threshold),
            "samples_since_reset": int(result.samples_since_reset),
            "direction": str(result.direction),
            "severity": severity,
            # C4 attributes added below
            "current_value": float(value),
            "baseline_mean": float(baseline_mean),
            "baseline_std": float(baseline_std),
            "host": socket.gethostname(),
            "instance_id": os.environ.get("MAHAVISHNU_INSTANCE_ID", "default"),
            "trace_id": trace_id_str,
            "runbook_url": _resolve_runbook_url(),
        }

        # C6: Prometheus counter — the §7 stage-1 gate's source-of-truth.
        # R3-H2 (rename): the gauge is now detector_age_samples_total
        # (cumulative semantic). The original R3-H2 commit left a
        # duplicate except handler below that the round-4 observability
        # review caught as a CRITICAL UnboundLocalError hazard; cleaned
        # up here.
        try:
            counter = getattr(self, "drift_detected_counter", None)
            if counter is not None:
                counter.add(
                    1,
                    attributes={
                        "metric_name": metric_name,
                        "detector": detector_name,
                        "severity": severity,
                    },
                )
            gauge = getattr(self, "detector_age_gauge", None)
            if gauge is not None:
                gauge.add(
                    int(result.samples_since_reset),
                    attributes={
                        "metric_name": metric_name,
                        "detector": detector_name,
                    },
                )
        except Exception as exc:  # noqa: BLE001 - boundary handler
            self._log_debug("drift counter increment failed: %s", exc)

        # S-1 (round-2 review): reset the detector after fire so
        # subsequent samples don't continuously re-fire on the same
        # drift event. Without this, the first drift produces one
        # alert per sampler tick forever (the CUSUM score stays
        # above threshold). The reset mirrors the production
        # §6 Phase 6 "reset_after_fire" semantic.
        try:
            detector_obj = getattr(self, "_changepoint_detector", None)
            if detector_obj is not None and hasattr(detector_obj, "reset"):
                detector_obj.reset()
        except Exception as exc:  # noqa: BLE001 - boundary handler
            self._log_debug("detector reset failed: %s", exc)

        # OTel span emission (best-effort).
        try:
            if OTEL_AVAILABLE and getattr(self, "tracer", None) is not None:
                with self.tracer.start_as_current_span(  # type: ignore[union-attr]
                    "mahavishnu.observability.drift_detected",
                    attributes=span_attributes,
                ):
                    pass
        except Exception as exc:  # noqa: BLE001 - boundary handler
            self._log_debug("OTel span emission failed: %s", exc)

        # Always log a structured event so observability survives
        # even when OTel is disabled.
        self._log_warning(
            "drift_detected metric=%s detector=%s value=%.3f baseline_mean=%.3f baseline_std=%.3f score=%.3f threshold=%.3f severity=%s direction=%s samples=%d trace_id=%s host=%s",
            metric_name,
            detector_name,
            value,
            baseline_mean,
            baseline_std,
            result.score,
            result.threshold,
            severity,
            result.direction,
            result.samples_since_reset,
            trace_id_str or "-",
            span_attributes["host"],
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

    def _log_debug(self, msg: str, *args: Any) -> None:
        if getattr(self, "logger", None) is not None:
            self.logger.debug(msg, *args)  # type: ignore[union-attr]

    def _log_warning(self, msg: str, *args: Any) -> None:
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

    async def start_change_point_tick_loop(
        self,
        metric_source: Any | None = None,
    ) -> Any:
        """Drive the change-point detector on a fixed cadence.

        CAL-2 (round-2 review): the Phase 6 pipeline
        (``MetricSampler.tick()`` → ``_evaluate_change_point``) had
        zero production callers — the wiring path between the
        sampler and the detector ran only in tests. This method
        starts an asyncio task that calls ``_evaluate_change_point``
        on the configured cadence (default 60s) for the configured
        ``changepoint.target_metric``.

        R3-C1+C2 (round-3 review): must be called from a *running*
        asyncio loop (i.e. an async startup path). The synchronous
        ``__init__`` path cannot start the task because
        ``asyncio.get_running_loop()`` raises ``RuntimeError`` when
        no loop is active. Bootstrap callers should defer the call
        to ``MahavishnuApp.start_change_point_tick_loop()`` (the app's
        async lifecycle method) or any other coroutine context.

        Args:
            metric_source: optional callable returning
                ``{metric_name: value}`` for the current tick.
                Defaults to a stub that returns ``0.0`` (the wiring
                path is exercised; operators wanting real data should
                inject a source that reads pool queue depths from
                ``PoolManager.get_pool_queue_depths()``).

        Returns:
            The asyncio.Task (callers can cancel it on shutdown).
        """
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError as exc:
            raise RuntimeError(
                "start_change_point_tick_loop requires a running asyncio loop. "
                "Call this method from an async startup path (e.g. "
                "MahavishnuApp.start_change_point_tick_loop), not from sync __init__."
            ) from exc

        cadence = float(
            getattr(
                getattr(self.config, "changepoint", None),
                "sampler_cadence_seconds",
                60.0,
            )
        )
        target_metric = str(
            getattr(
                getattr(self.config, "changepoint", None),
                "target_metric",
                "pool_queue_depth",
            )
        )
        reference_mode = self._changepoint_reference_mode()
        enabled = self._changepoint_enabled()

        async def _loop() -> None:
            while True:
                # Round-3 H3: drive both the change-point detector AND
                # the 3-sigma reference detector from the same tick so
                # the runbook's "if the reference suddenly starts firing"
                # gate is falsifiable.
                try:
                    snapshot: dict[str, float] = {}
                    if metric_source is not None:
                        snapshot = metric_source()
                    value = float(snapshot.get(target_metric, 0.0))
                    if enabled:
                        self._evaluate_change_point(target_metric, value)
                    if reference_mode != "none":
                        self._evaluate_3sigma(target_metric, value)
                except Exception as exc:  # noqa: BLE001 - boundary handler
                    self._log_debug("change-point tick failed: %s", exc)
                await asyncio.sleep(cadence)

        task = asyncio.create_task(_loop())
        return task

    async def stop_change_point_tick_loop(self, task: Any | None = None) -> None:
        """Cancel the change-point tick loop task if one was started.

        R3-C1 (round-3 review): the bootstrap originally leaked the
        tick task on shutdown. Callers should retain the task and
        cancel it here from ``MahavishnuApp.shutdown()``.
        """
        target = task if task is not None else getattr(self, "_change_point_tick_task", None)
        if target is None:
            return
        try:
            target.cancel()
        except Exception:  # noqa: BLE001 - boundary handler
            pass
        try:
            await target
        except Exception:  # noqa: BLE001 - boundary handler (CancelledError is expected)
            pass

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
