"""Observability implementation for Mahavishnu using OpenTelemetry."""
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
try:
    from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
except ImportError:
    # SystemMetricsInstrumentor may not be available in all versions
    SystemMetricsInstrumentor = None
import logging
from typing import Optional


class ObservabilityManager:
    """Manages OpenTelemetry tracing and metrics for Mahavishnu."""
    
    def __init__(self, config):
        """Initialize observability manager with configuration.
        
        Args:
            config: MahavishnuSettings configuration object
        """
        self.config = config
        self.tracer = None
        self.meter = None
        self.logger = logging.getLogger(__name__)
        
    def setup_telemetry(self):
        """Initialize OpenTelemetry based on configuration."""
        if not self.config.metrics_enabled and not self.config.tracing_enabled:
            self.logger.info("Observability disabled by configuration")
            return
        
        # Create resource with service info
        resource = Resource.create({
            "service.name": "mahavishnu",
            "service.version": "1.0.0",
        })
        
        # Setup tracing if enabled
        if self.config.tracing_enabled:
            try:
                tracer_provider = TracerProvider(resource=resource)
                
                # Add OTLP exporter if endpoint is configured
                if self.config.otlp_endpoint:
                    otlp_exporter = OTLPSpanExporter(endpoint=self.config.otlp_endpoint)
                    span_processor = BatchSpanProcessor(otlp_exporter)
                    tracer_provider.add_span_processor(span_processor)
                
                trace.set_tracer_provider(tracer_provider)
                self.tracer = trace.get_tracer(__name__)
                
                self.logger.info("Tracing initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize tracing: {e}")
        
        # Setup metrics if enabled
        if self.config.metrics_enabled:
            try:
                metric_reader = None
                if self.config.otlp_endpoint:
                    otlp_exporter = OTLPMetricExporter(endpoint=self.config.otlp_endpoint)
                    metric_reader = PeriodicExportingMetricReader(otlp_exporter)
                
                meter_provider = MeterProvider(
                    resource=resource,
                    metric_readers=[metric_reader] if metric_reader else []
                )
                
                metrics.set_meter_provider(meter_provider)
                self.meter = metrics.get_meter(__name__)
                
                # Instrument system metrics
                if SystemMetricsInstrumentor:
                    SystemMetricsInstrumentor().instrument()
                
                self.logger.info("Metrics initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize metrics: {e}")
    
    def get_tracer(self):
        """Get tracer instance."""
        return self.tracer
    
    def get_meter(self):
        """Get meter instance."""
        return self.meter
    
    def create_workflow_counter(self):
        """Create counter for workflow executions."""
        if self.meter:
            return self.meter.create_counter(
                "workflows.executed",
                description="Number of workflows executed"
            )
        return None
    
    def create_repo_counter(self):
        """Create counter for repositories processed."""
        if self.meter:
            return self.meter.create_counter(
                "repositories.processed",
                description="Number of repositories processed"
            )
        return None
    
    def create_error_counter(self):
        """Create counter for errors."""
        if self.meter:
            return self.meter.create_counter(
                "errors.count",
                description="Number of errors occurred"
            )
        return None


# Global instance
observability_manager: Optional[ObservabilityManager] = None


def init_observability(config):
    """Initialize the global observability manager."""
    global observability_manager
    observability_manager = ObservabilityManager(config)
    observability_manager.setup_telemetry()


def get_observability_manager() -> Optional[ObservabilityManager]:
    """Get the global observability manager instance."""
    return observability_manager