#!/usr/bin/env python3
"""
Complete OTLP client example for Python
Demonstrates traces, metrics, and logs ingestion into Mahavishnu OTel stack

Usage:
    # Primary collector
    python python-otlp-client.py --endpoint http://localhost:4317 --service my-app

    # Claude-specific
    python python-otlp-client.py --endpoint http://localhost:4319 --service claude-integration --source claude

    # Qwen-specific
    python python-otlp-client.py --endpoint http://localhost:4321 --service qwen-integration --source qwen

Requirements:
    pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc
"""

import argparse
import logging
import random
import time
from typing import Optional

from opentelemetry import trace, metrics, logs
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter
from opentelemetry.sdk.logs import LoggerProvider
from opentelemetry.sdk.logs.export import BatchLogRecordProcessor, ConsoleLogRecordExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.log_exporter import OTLPLogExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry import context


def setup_telemetry(
    endpoint: str,
    service_name: str,
    source: Optional[str] = None,
    environment: str = "development",
    console_export: bool = False
) -> tuple:
    """
    Setup complete OpenTelemetry instrumentation

    Args:
        endpoint: OTLP endpoint (e.g., http://localhost:4317)
        service_name: Service name for telemetry
        source: Source identifier (e.g., claude, qwen, custom)
        environment: Deployment environment
        console_export: Also export to console for debugging

    Returns:
        Tuple of (tracer, meter, logger)
    """

    # Create resource with service metadata
    resource_attributes = {
        SERVICE_NAME: service_name,
        "deployment.environment": environment,
        "telemetry.sdk.language": "python",
        "telemetry.sdk.name": "opentelemetry",
    }

    if source:
        resource_attributes["telemetry.source"] = source
        resource_attributes["telemetry.source.type"] = "ai_assistant" if source in ["claude", "qwen"] else "custom"

    resource = Resource.create(resource_attributes)

    # ==============================================================================
    # TRACE SETUP
    # ==============================================================================
    trace_provider = TracerProvider(resource=resource)

    # OTLP exporter
    trace_exporter = OTLPSpanExporter(
        endpoint=endpoint,
        insecure=True,
        timeout=10,
    )

    # Add batch processor
    trace_provider.add_span_processor(BatchSpanProcessor(trace_exporter))

    # Optional: Console exporter for debugging
    if console_export:
        trace_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(trace_provider)
    tracer = trace.get_tracer(__name__)

    # ==============================================================================
    # METRICS SETUP
    # ==============================================================================
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(
            endpoint=endpoint,
            insecure=True,
            timeout=10,
        ),
        export_interval_millis=15000,  # Export every 15 seconds
    )

    metrics_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(metrics_provider)
    meter = metrics.get_meter(__name__)

    # ==============================================================================
    # LOGS SETUP
    # ==============================================================================
    logger_provider = LoggerProvider(resource=resource)

    log_exporter = OTLPLogExporter(
        endpoint=endpoint,
        insecure=True,
        timeout=10,
    )

    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))

    # Optional: Console exporter for debugging
    if console_export:
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(ConsoleLogRecordExporter()))

    logs.set_logger_provider(logger_provider)
    logger = logging.getLogger(service_name)

    # Add OTLP handler to Python logging
    handler = logs.LoggingHandler(logger_provider=logger_provider)
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    return tracer, meter, logger, (trace_provider, metrics_provider, logger_provider)


def generate_example_traces(tracer, count: int = 5):
    """Generate example trace spans"""
    print(f"\n🔍 Generating {count} example traces...")

    for i in range(count):
        with tracer.start_as_current_span(f"example-operation-{i}") as parent:
            parent.set_attribute("operation.index", i)
            parent.set_attribute("operation.type", random.choice(["read", "write", "compute", "query"]))
            parent.set_attribute("operation.duration_ms", random.randint(10, 500))

            # Simulate nested spans
            with tracer.start_as_current_span("child-operation") as child:
                child.set_attribute("child.depth", 1)
                child.set_attribute("child.value", random.randint(1, 100))

                # Add another level
                with tracer.start_as_current_span("grandchild-operation") as grandchild:
                    grandchild.set_attribute("grandchild.depth", 2)
                    time.sleep(0.01)  # Simulate work

            time.sleep(0.01)  # Simulate work

        print(f"  ✓ Generated trace {i+1}/{count}")

    print(f"✅ Generated {count} traces successfully!")


def generate_example_metrics(meter, count: int = 10):
    """Generate example metrics"""
    print(f"\n📊 Generating {count} example metrics...")

    # Create instruments
    counter = meter.create_counter(
        "operations.total",
        description="Total number of operations performed"
    )

    histogram = meter.create_histogram(
        "operation.duration",
        description="Operation duration in milliseconds",
        unit="ms"
    )

    gauge = meter.create_up_down_counter(
        "active.connections",
        description="Number of active connections"
    )

    for i in range(count):
        # Counter
        counter.add(
            random.randint(1, 10),
            {
                "operation.type": random.choice(["read", "write", "compute"]),
                "operation.status": random.choice(["success", "error"])
            }
        )

        # Histogram
        histogram.record(
            random.randint(10, 500),
            {
                "operation.type": random.choice(["read", "write", "compute"]),
            }
        )

        # Gauge
        gauge.add(
            random.randint(-5, 5),
            {
                "connection.type": random.choice(["http", "grpc", "websocket"])
            }
        )

        print(f"  ✓ Generated metric batch {i+1}/{count}")
        time.sleep(0.1)

    print(f"✅ Generated {count} metric batches successfully!")


def generate_example_logs(logger, count: int = 5):
    """Generate example log records"""
    print(f"\n📝 Generating {count} example logs...")

    log_levels = [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR]

    for i in range(count):
        level = random.choice(log_levels)
        message = f"Example log message {i+1} - {random.choice(['Success', 'Warning', 'Error', 'Debug info'])}"

        logger.log(level, message, extra={
            "log.index": i,
            "log.type": random.choice(["system", "application", "audit"]),
            "log.user_id": f"user-{random.randint(1000, 9999)}"
        })

        print(f"  ✓ Generated log {i+1}/{count}")

    print(f"✅ Generated {count} logs successfully!")


def simulate_ai_assistant_workflow(tracer, meter, logger, source: str):
    """
    Simulate an AI assistant workflow (Claude or Qwen)
    Demonstrates realistic telemetry for AI interactions
    """
    print(f"\n🤖 Simulating {source} assistant workflow...")

    with tracer.start_as_current_span(f"{source}.interaction") as span:
        # Input
        prompt = "Explain distributed tracing in simple terms"
        prompt_tokens = len(prompt.split()) * 1.3  # Approximate tokenization

        span.set_attribute("ai.prompt", prompt)
        span.set_attribute("ai.prompt.length", len(prompt))
        span.set_attribute("ai.prompt.tokens", int(prompt_tokens))
        span.set_attribute("ai.model", "claude-sonnet-4" if source == "claude" else "qwen-max")

        logger.info(f"Received prompt: {prompt[:50]}...")

        # Simulate processing
        with tracer.start_as_current_span(f"{source}.processing") as processing_span:
            time.sleep(random.uniform(0.1, 0.5))

            # Metrics for processing
            meter.create_counter(
                f"{source}.requests.total"
            ).add(1, {"model": processing_span.attributes.get("ai.model")})

        # Generate response
        response = "Distributed tracing is a method used to track requests..."
        response_tokens = len(response.split()) * 1.3

        span.set_attribute("ai.response", response)
        span.set_attribute("ai.response.length", len(response))
        span.set_attribute("ai.response.tokens", int(response_tokens))
        span.set_attribute("ai.total_tokens", int(prompt_tokens + response_tokens))
        span.set_attribute("ai.duration_ms", random.randint(500, 2000))

        # Metrics for tokens
        meter.create_counter(
            f"{source}.tokens.total"
        ).add(
            int(prompt_tokens + response_tokens),
            {"token_type": "total"}
        )

        logger.info(f"Generated response: {response[:50]}...")

    print(f"✅ Simulated {source} workflow successfully!")


def main():
    parser = argparse.ArgumentParser(
        description="OTLP Client for Mahavishnu Observability Stack",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Primary collector
  %(prog)s --endpoint http://localhost:4317 --service my-app

  # Claude-specific collector
  %(prog)s --endpoint http://localhost:4319 --service claude-integration --source claude

  # Qwen-specific collector
  %(prog)s --endpoint http://localhost:4321 --service qwen-integration --source qwen

  # With console debugging
  %(prog)s --endpoint http://localhost:4317 --service my-app --console

  # Generate only traces
  %(prog)s --endpoint http://localhost:4317 --service my-app --traces-only

  # Simulate AI workflow
  %(prog)s --endpoint http://localhost:4319 --service claude --source claude --ai-workflow
        """
    )

    parser.add_argument(
        "--endpoint",
        default="http://localhost:4317",
        help="OTLP endpoint (default: http://localhost:4317)"
    )
    parser.add_argument(
        "--service",
        default="python-otlp-client",
        help="Service name (default: python-otlp-client)"
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Source identifier (e.g., claude, qwen, custom)"
    )
    parser.add_argument(
        "--environment",
        default="development",
        help="Deployment environment (default: development)"
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="Also export to console for debugging"
    )
    parser.add_argument(
        "--traces-only",
        action="store_true",
        help="Only generate traces"
    )
    parser.add_argument(
        "--metrics-only",
        action="store_true",
        help="Only generate metrics"
    )
    parser.add_argument(
        "--logs-only",
        action="store_true",
        help="Only generate logs"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of items to generate (default: 10)"
    )
    parser.add_argument(
        "--ai-workflow",
        action="store_true",
        help="Simulate AI assistant workflow"
    )

    args = parser.parse_args()

    print("=" * 80)
    print("🔧 Mahavishnu OTLP Client")
    print("=" * 80)
    print(f"Endpoint: {args.endpoint}")
    print(f"Service: {args.service}")
    print(f"Source: {args.source or 'default'}")
    print(f"Environment: {args.environment}")
    print("=" * 80)

    # Setup telemetry
    try:
        tracer, meter, logger, providers = setup_telemetry(
            endpoint=args.endpoint,
            service_name=args.service,
            source=args.source,
            environment=args.environment,
            console_export=args.console
        )
        print("✅ Telemetry initialized successfully!")
    except Exception as e:
        print(f"❌ Failed to initialize telemetry: {e}")
        return 1

    try:
        # Generate telemetry based on flags
        if args.ai_workflow and args.source:
            simulate_ai_assistant_workflow(tracer, meter, logger, args.source)
        else:
            if not args.metrics_only and not args.logs_only:
                generate_example_traces(tracer, args.count)

            if not args.traces_only and not args.logs_only:
                generate_example_metrics(meter, args.count)

            if not args.traces_only and not args.metrics_only:
                generate_example_logs(logger, args.count)

        print("\n" + "=" * 80)
        print("✅ Telemetry generation complete!")
        print("=" * 80)
        print("\n📍 View your telemetry:")
        print(f"  • Jaeger (Traces): http://localhost:16686/?service={args.service}")
        print(f"  • Prometheus (Metrics): http://localhost:9090")
        print(f"  • Kibana (Logs): http://localhost:5601")
        print("\n💡 Wait 10-15 seconds for metrics to be exported (batch interval)")
        print("\n🔍 Troubleshooting:")
        print("  • Check collector health: curl http://localhost:13133/healthy")
        print("  • View collector logs: docker-compose logs -f otel-collector")
        print("=" * 80)

        # Give time for exports
        if not args.traces_only:  # Metrics need time to export
            print("\n⏳ Waiting for metric export (15 seconds)...")
            time.sleep(15)

    except Exception as e:
        print(f"\n❌ Error generating telemetry: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # Shutdown providers
        print("\n🧹 Shutting down telemetry providers...")
        trace_provider, metrics_provider, logger_provider = providers
        trace_provider.shutdown()
        metrics_provider.shutdown()
        logger_provider.shutdown()

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
