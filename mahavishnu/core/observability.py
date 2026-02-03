"""Enhanced observability module for Mahavishnu."""

from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from enum import Enum
import logging
import time
from typing import Any

from ..core.config import MahavishnuSettings

# Try to import OpenTelemetry components
try:
    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
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
        def add(self, amount: int, attributes: dict[str, str] = None):
            pass

    class MockHistogram:
        def record(self, amount: float, attributes: dict[str, str] = None):
            pass

    class MockUpDownCounter:
        def add(self, amount: int, attributes: dict[str, str] = None):
            pass

    class MockTracer:
        def start_as_current_span(self, name: str, attributes: dict[str, str] = None):
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
            processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=self.config.observability.otlp_endpoint))
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

        except Exception as e:
            self.logger.warning(f"Failed to initialize OpenTelemetry: {e}")
            self._init_fallback_components()

    def _init_fallback_components(self):
        """Initialize fallback components when OpenTelemetry is not available."""
        self.tracer = MockTracer() if OTEL_AVAILABLE else MockTracer()
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
        self, level: LogLevel, message: str, attributes: dict[str, Any] = None, trace_id: str = None
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

    def log_debug(self, message: str, attributes: dict[str, Any] = None, trace_id: str = None):
        """Log a debug message."""
        self.log(LogLevel.DEBUG, message, attributes, trace_id)

    def log_info(self, message: str, attributes: dict[str, Any] = None, trace_id: str = None):
        """Log an info message."""
        self.log(LogLevel.INFO, message, attributes, trace_id)

    def log_warning(self, message: str, attributes: dict[str, Any] = None, trace_id: str = None):
        """Log a warning message."""
        self.log(LogLevel.WARNING, message, attributes, trace_id)

    def log_error(self, message: str, attributes: dict[str, Any] = None, trace_id: str = None):
        """Log an error message."""
        self.log(LogLevel.ERROR, message, attributes, trace_id)

    def log_critical(self, message: str, attributes: dict[str, Any] = None, trace_id: str = None):
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
        self, limit: int = 100, level: LogLevel = None, since: datetime = None
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

    async def flush_metrics(self):
        """Flush any pending metrics to exporters."""
        if OTEL_AVAILABLE:
            try:
                # Force flush metrics
                from opentelemetry.metrics import get_meter_provider

                get_meter_provider().force_flush()

                # Force flush traces
                from opentelemetry.trace import get_tracer_provider

                get_tracer_provider().force_flush()
            except Exception as e:
                self.logger.warning(f"Failed to flush metrics: {e}")

    def shutdown(self):
        """Shutdown observability components."""
        if OTEL_AVAILABLE:
            try:
                # Shutdown providers
                from opentelemetry.metrics import get_meter_provider
                from opentelemetry.trace import get_tracer_provider

                get_meter_provider().shutdown()
                get_tracer_provider().shutdown()
            except Exception as e:
                self.logger.warning(f"Error during observability shutdown: {e}")


def init_observability(config: MahavishnuSettings) -> ObservabilityManager:
    """Initialize the observability system."""
    return ObservabilityManager(config)


def get_observability_manager() -> ObservabilityManager | None:
    """Get the global observability manager instance."""
    # This would typically return a singleton instance
    # For now, returning None as we don't have a global registry
    return None
