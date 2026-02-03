# OTLP Ingestion Setup Guide

Complete guide for configuring OTLP (OpenTelemetry Protocol) ingestion from external sources into Mahavishnu's observability stack.

## Table of Contents

1. [Quick Start](#quick-start)
1. [Architecture Overview](#architecture-overview)
1. [Ingestion Methods](#ingestion-methods)
1. [Client Configuration](#client-configuration)
1. [Claude-Specific Setup](#claude-specific-setup)
1. [Qwen-Specific Setup](#qwen-specific-setup)
1. [General Python Applications](#general-python-applications)
1. [Testing and Validation](#testing-and-validation)
1. [Troubleshooting](#troubleshooting)
1. [Production Checklist](#production-checklist)

______________________________________________________________________

## Quick Start

### 1. Start the OTel Stack

```bash
cd /Users/les/Projects/mahavishnu
docker-compose -f docker-compose.buildpacks.yml up -d otel-collector jaeger prometheus elasticsearch
```

### 2. Verify the Collector is Running

```bash
# Health check
curl http://localhost:13133/healthy

# Check configuration (requires curl with JSON formatting)
curl http://localhost:4318/v1/metrics
```

### 3. Send Test Telemetry

```python
# Quick test with Python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Setup
provider = TracerProvider()
processor = BatchSpanProcessor(
    OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)

# Create a test span
tracer = trace.get_tracer(__name__)
with tracer.start_as_current_span("test-span"):
    print("OTLP is working!")
```

______________________________________________________________________

## Architecture Overview

### Available Endpoints

| Source Type | gRPC Endpoint | HTTP Endpoint | Purpose |
|-------------|---------------|---------------|---------|
| **Primary** | `localhost:4317` | `localhost:4318` | Mahavishnu application |
| **Claude** | `localhost:4319` | `localhost:4320` | Claude AI assistant |
| **Qwen** | `localhost:4321` | `localhost:4322` | Qwen AI assistant |

### Telemetry Flow

```
┌─────────────┐     OTLP      ┌──────────────────┐     Export     ┌──────────┐
│   Claude    │──────────────▶│                  │───────────────▶│ Jaeger   │
│   Qwen      │   (gRPC/HTTP) │   OTel Collector │                │ Prometheus│
│   Python    │               │                  │───────────────▶│ Elastic  │
│   Custom    │               │                  │                │ Search   │
└─────────────┘               └──────────────────┘                └──────────┘
                                      │
                                      ▼
                               ┌──────────────┐
                               │ File Log     │
                               │ Receiver     │
                               │ (optional)   │
                               └──────────────┘
```

### Pipeline Architecture

Each source has dedicated pipelines for traces, metrics, and logs:

- **Traces**: Application → Collector → Jaeger
- **Metrics**: Application → Collector → Prometheus
- **Logs**: Application → Collector → Elasticsearch

______________________________________________________________________

## Ingestion Methods

### Method 1: Direct OTLP (Recommended)

Send telemetry directly via OTLP protocol using OpenTelemetry SDKs.

**Pros:**

- Real-time streaming
- Full telemetry support (traces, metrics, logs)
- Automatic retries and batching
- Standard protocol

**Cons:**

- Requires OpenTelemetry SDK integration
- Network dependency on collector

### Method 2: File Log Ingestion

Write logs to files that the collector monitors.

**Pros:**

- Simple integration
- No network dependency during write
- Works with any logging format

**Cons:**

- Polling-based (not real-time)
- Logs only (no traces/metrics)
- Requires proper log formatting

### Method 3: Hybrid Approach

Combine OTLP for traces/metrics with file logging for logs.

**Recommended for:**

- High-volume logging
- Offline scenarios
- Legacy application integration

______________________________________________________________________

## Client Configuration

### Python OTLP Client

Complete example for sending all telemetry types:

```python
"""
Complete OTLP client example for Python
Sends traces, metrics, and logs to Mahavishnu OTel collector
"""

from opentelemetry import trace, metrics, logs
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.logs import LoggerProvider
from opentelemetry.sdk.logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.log_exporter import OTLPLogExporter
from opentelemetry.sdk.resources import Resource

# Create resource with service metadata
resource = Resource.create({
    "service.name": "my-python-app",
    "service.namespace": "my-team",
    "deployment.environment": "production",
    "telemetry.source": "custom"  # Custom identifier
})

# ==============================================================================
# TRACE SETUP
# ==============================================================================
trace_provider = TracerProvider(resource=resource)
trace_exporter = OTLPSpanExporter(
    endpoint="http://localhost:4317",  # Or :4319 for Claude, :4321 for Qwen
    insecure=True
)
trace_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
trace.set_tracer_provider(trace_provider)

# ==============================================================================
# METRICS SETUP
# ==============================================================================
metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(
        endpoint="http://localhost:4317",  # Or :4319 for Claude, :4321 for Qwen
        insecure=True
    ),
    export_interval_millis=15000,  # Export every 15 seconds
)
metrics_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(metrics_provider)

# ==============================================================================
# LOGS SETUP
# ==============================================================================
logger_provider = LoggerProvider(resource=resource)
log_exporter = OTLPLogExporter(
    endpoint="http://localhost:4317",  # Or :4319 for Claude, :4321 for Qwen
    insecure=True
)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
logs.set_logger_provider(logger_provider)

# ==============================================================================
# USAGE EXAMPLES
# ==============================================================================
from opentelemetry import metrics
import logging

# Get instrumentation
tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)
logger = logging.getLogger(__name__)

# Add OTLP handler to Python logging
handler = logs.LoggingHandler(logger_provider=logger_provider)
logger.addHandler(handler)

# Example: Create a span
with tracer.start_as_current_span("example-operation") as span:
    span.set_attribute("operation.type", "example")
    span.set_attribute("operation.value", 42)

    # Example: Create a metric
    counter = meter.create_counter(
        "operations.completed",
        description="Number of operations completed"
    )
    counter.add(1, {"operation.type": "example"})

    # Example: Log a message
    logger.info("Operation completed successfully")

print("Telemetry sent! Check Jaeger (http://localhost:16686) for traces")
```

### Environment Variable Configuration

Simpler approach using environment variables (works with auto-instrumentation):

```bash
# Export to primary collector
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
export OTEL_SERVICE_NAME=my-app
export OTEL_RESOURCE_ATTRIBUTES=telemetry.source=custom,deployment.environment=production

# Export to Claude-specific collector
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4319
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
export OTEL_SERVICE_NAME=claude-integration
export OTEL_RESOURCE_ATTRIBUTES=telemetry.source=claude

# Export to Qwen-specific collector
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4321
export OTEL_EXPORTER_OTLP_PROTOCOL=grpc
export OTEL_SERVICE_NAME=qwen-integration
export OTEL_RESOURCE_ATTRIBUTES=telemetry.source=qwen
```

### Docker Integration

Add to your Dockerfile or docker-compose:

```yaml
version: '3.9'
services:
  my-app:
    image: my-app:latest
    environment:
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
      - OTEL_SERVICE_NAME=my-app
      - OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production
      - OTEL_EXPORTER_OTLP_PROTOCOL=grpc
    networks:
      - mahavishnu-network

networks:
  mahavishnu-network:
    external: true
```

______________________________________________________________________

## Claude-Specific Setup

### Option 1: Direct OTLP Integration

If you have access to Claude's internals or can instrument calls:

```python
"""
Claude OTLP integration example
Monitors Claude API calls and responses
"""

import time
from typing import Dict, Any
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

# Setup Claude-specific tracer
resource = Resource.create({
    "service.name": "claude-integration",
    "telemetry.source": "claude",
    "telemetry.source.type": "ai_assistant",
    "ai.model": "claude-sonnet-4"
})

provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(endpoint="http://localhost:4319", insecure=True)
))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("claude-tracer")

def call_claude(prompt: str, **kwargs) -> Dict[str, Any]:
    """
    Instrumented Claude API call with telemetry
    """
    with tracer.start_as_current_span("claude.api.call") as span:
        # Track request metadata
        span.set_attribute("ai.prompt.length", len(prompt))
        span.set_attribute("ai.model", kwargs.get("model", "claude-sonnet-4"))
        span.set_attribute("ai.max_tokens", kwargs.get("max_tokens", 4096))
        span.set_attribute("ai.temperature", kwargs.get("temperature", 0.7))

        start_time = time.time()

        try:
            # Your actual Claude API call here
            # response = anthropic_client.messages.create(...)
            response = {"completion": "...", "usage": {"input_tokens": 100, "output_tokens": 200}}

            # Track response metadata
            duration = time.time() - start_time
            span.set_attribute("ai.duration.ms", duration * 1000)
            span.set_attribute("ai.response.completion_length", len(response.get("completion", "")))
            span.set_attribute("ai.usage.input_tokens", response["usage"]["input_tokens"])
            span.set_attribute("ai.usage.output_tokens", response["usage"]["output_tokens"])

            return response

        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            raise

# Example usage
response = call_claude("Write a haiku about telemetry")
```

### Option 2: Log File Ingestion

Write Claude session logs to files that the collector monitors:

```python
"""
Claude log file writer
Writes Claude interactions to log files for OTel collector ingestion
"""

import json
import logging
from datetime import datetime
from pathlib import Path

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger("claude-logger")

# Log directory (mapped to collector)
log_dir = Path("/var/log/mahavishnu/sessions/claude")
log_dir.mkdir(parents=True, exist_ok=True)

# Create session-specific log file
session_id = "session-20250131-123456"
log_file = log_dir / f"{session_id}.log"

def log_claude_interaction(
    role: str,
    content: str,
    metadata: dict = None
):
    """
    Log Claude interaction in structured JSON format
    Expected by filelog receiver in otel-collector-config.yaml
    """
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "session_id": session_id,
        "source": "claude",
        "level": "info",
        "role": role,
        "content": content,
        "metadata": metadata or {}
    }

    # Write to log file
    with open(log_file, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    # Also log to console
    logger.info(json.dumps(log_entry))

# Example usage
log_claude_interaction(
    role="user",
    content="Explain OTLP",
    metadata={"model": "claude-sonnet-4", "tokens": 150}
)

log_claude_interaction(
    role="assistant",
    content="OTLP is OpenTelemetry Protocol...",
    metadata={"tokens": 500, "duration_ms": 1234}
)
```

Ensure log directory is mounted in docker-compose:

```yaml
services:
  otel-collector:
    volumes:
      - ./config/otel-collector-config.yaml:/etc/otel-collector-config.yaml:ro
      - /var/log/mahavishnu/sessions:/var/log/mahavishnu/sessions:ro  # Add this
```

______________________________________________________________________

## Qwen-Specific Setup

### Option 1: Direct OTLP Integration

```python
"""
Qwen OTLP integration example
Monitors Qwen API calls and responses
"""

import time
from typing import Dict, Any
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

# Setup Qwen-specific tracer
resource = Resource.create({
    "service.name": "qwen-integration",
    "telemetry.source": "qwen",
    "telemetry.source.type": "ai_assistant",
    "ai.model": "qwen-max"
})

provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(endpoint="http://localhost:4321", insecure=True)
))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("qwen-tracer")

def call_qwen(prompt: str, **kwargs) -> Dict[str, Any]:
    """
    Instrumented Qwen API call with telemetry
    """
    with tracer.start_as_current_span("qwen.api.call") as span:
        # Track request metadata
        span.set_attribute("ai.prompt.length", len(prompt))
        span.set_attribute("ai.model", kwargs.get("model", "qwen-max"))
        span.set_attribute("ai.max_tokens", kwargs.get("max_tokens", 4096))
        span.set_attribute("ai.temperature", kwargs.get("temperature", 0.7))

        start_time = time.time()

        try:
            # Your actual Qwen API call here
            # response = qwen_client.generate(...)
            response = {"text": "...", "usage": {"input_tokens": 100, "output_tokens": 200}}

            # Track response metadata
            duration = time.time() - start_time
            span.set_attribute("ai.duration.ms", duration * 1000)
            span.set_attribute("ai.response.text_length", len(response.get("text", "")))
            span.set_attribute("ai.usage.input_tokens", response["usage"]["input_tokens"])
            span.set_attribute("ai.usage.output_tokens", response["usage"]["output_tokens"])

            return response

        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            raise

# Example usage
response = call_qwen("Explain distributed tracing")
```

### Option 2: Log File Ingestion

Same structure as Claude, but with Qwen-specific paths:

```python
"""
Qwen log file writer
"""

import json
from datetime import datetime
from pathlib import Path

log_dir = Path("/var/log/mahavishnu/sessions/qwen")
log_dir.mkdir(parents=True, exist_ok=True)

session_id = "session-20250131-789012"
log_file = log_dir / f"{session_id}.log"

def log_qwen_interaction(
    role: str,
    content: str,
    metadata: dict = None
):
    """Log Qwen interaction in structured JSON format"""
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "session_id": session_id,
        "source": "qwen",
        "level": "info",
        "role": role,
        "content": content,
        "metadata": metadata or {}
    }

    with open(log_file, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

# Example usage
log_qwen_interaction(
    role="user",
    content="What is OTLP?",
    metadata={"model": "qwen-max", "tokens": 120}
)

log_qwen_interaction(
    role="assistant",
    content="OTLP stands for OpenTelemetry Protocol...",
    metadata={"tokens": 450, "duration_ms": 987}
)
```

______________________________________________________________________

## General Python Applications

### Auto-Instrumentation (Zero Code Changes)

OpenTelemetry can automatically instrument Python applications without code changes:

```bash
# Install auto-instrumentation
pip install opentelemetry-instrumentation
pip install opentelemetry-instrumentation-requests
pip install opentelemetry-instrumentation-flask
pip install opentelemetry-instrumentation-sqlalchemy
# ... add more as needed

# Run with auto-instrumentation
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SERVICE_NAME=my-auto-app
export OTEL_RESOURCE_ATTRIBUTES=telemetry.source=auto-instrumented

opentelemetry-instrument python my_app.py
```

### Manual Instrumentation

See the [Python OTLP Client](#python-otlp-client) section above for complete manual instrumentation example.

### Flask Application Example

```python
"""
Flask application with OTLP integration
"""

from flask import Flask, jsonify
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.flask import FlaskInstrumentor

# Setup tracing
resource = Resource.create({
    "service.name": "flask-app",
    "telemetry.source": "flask"
})

provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
))
trace.set_tracer_provider(provider)

# Create Flask app
app = Flask(__name__)

# Auto-instrument Flask
FlaskInstrumentor().instrument_app(app)

@app.route('/api/hello')
def hello():
    return jsonify({"message": "Hello with telemetry!"})

if __name__ == '__main__':
    app.run(debug=True)
```

### FastAPI Application Example

```python
"""
FastAPI application with OTLP integration
"""

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Setup tracing
resource = Resource.create({
    "service.name": "fastapi-app",
    "telemetry.source": "fastapi"
})

provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
))
trace.set_tracer_provider(provider)

# Create FastAPI app
app = FastAPI()

# Auto-instrument FastAPI
FastAPIInstrumentor.instrument_app(app)

@app.get("/api/hello")
def hello():
    return {"message": "Hello with telemetry!"}
```

______________________________________________________________________

## Testing and Validation

### 1. Verify Collector is Running

```bash
# Health check
curl http://localhost:13133/healthy

# Expected output: {"status":"OK"}
```

### 2. Test Traces

Run the Python test client from [Quick Start](#quick-start):

```bash
python3 -c "
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

provider = TracerProvider()
processor = BatchSpanProcessor(
    OTLPSpanExporter(endpoint='http://localhost:4317', insecure=True)
)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)

tracer = trace.get_tracer('test')
with tracer.start_as_current_span('test-span'):
    print('Trace sent!')
"
```

**Verify in Jaeger:**

- Open http://localhost:16686
- Click "Search"
- Look for service "test-span"
- Click "Find Traces"

### 3. Test Metrics

```bash
python3 -c "
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.resources import Resource

resource = Resource.create({'service.name': 'test-metrics'})
reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint='http://localhost:4317', insecure=True),
    export_interval_millis=5000
)
provider = MeterProvider(resource=resource, metric_readers=[reader])
metrics.set_meter_provider(provider)

meter = metrics.get_meter('test')
counter = meter.create_counter('test.counter')
counter.add(1, {'test': 'value'})
print('Metric sent! Wait 5 seconds for export...')
"
```

**Verify in Prometheus:**

- Open http://localhost:9090
- Query: `test_counter`
- Should see the metric

### 4. Test Logs

```bash
python3 -c "
from opentelemetry import logs
from opentelemetry.sdk.logs import LoggerProvider
from opentelemetry.sdk.logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc.log_exporter import OTLPLogExporter
from opentelemetry.sdk.resources import Resource
import logging

resource = Resource.create({'service.name': 'test-logs'})
provider = LoggerProvider(resource=resource)
provider.add_log_record_processor(BatchLogRecordProcessor(
    OTLPLogExporter(endpoint='http://localhost:4317', insecure=True)
))
logs.set_logger_provider(provider)

logger = logging.getLogger('test')
handler = logs.LoggingHandler(logger_provider=provider)
logger.addHandler(handler)
logger.info('Test log message')
print('Log sent!')
"
```

**Verify in Elasticsearch/Kibana:**

- Open http://localhost:5601
- Go to "Discover"
- Index pattern: `mahavishnu-logs*`
- Search for `Test log message`

### 5. Test Claude-Specific Endpoint

```bash
# Test Claude endpoint
python3 -c "
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

resource = Resource.create({
    'service.name': 'claude-test',
    'telemetry.source': 'claude'
})
provider = TracerProvider(resource=resource)
processor = BatchSpanProcessor(
    OTLPSpanExporter(endpoint='http://localhost:4319', insecure=True)
)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)

tracer = trace.get_tracer('claude-test')
with tracer.start_as_current_span('claude-test-span'):
    print('Claude trace sent!')
"
```

### 6. Test Qwen-Specific Endpoint

```bash
# Test Qwen endpoint
python3 -c "
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

resource = Resource.create({
    'service.name': 'qwen-test',
    'telemetry.source': 'qwen'
})
provider = TracerProvider(resource=resource)
processor = BatchSpanProcessor(
    OTLPSpanExporter(endpoint='http://localhost:4321', insecure=True)
)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)

tracer = trace.get_tracer('qwen-test')
with tracer.start_as_current_span('qwen-test-span'):
    print('Qwen trace sent!')
"
```

### 7. Test File Log Ingestion

```bash
# Create test log file
mkdir -p /var/log/mahavishnu/sessions/claude

cat > /var/log/mahavishnu/sessions/claude/test-session.log <<EOF
{"timestamp": "2025-01-31T12:00:00", "session_id": "test-123", "source": "claude", "level": "info", "message": "Test log from file"}
{"timestamp": "2025-01-31T12:00:01", "session_id": "test-123", "source": "claude", "level": "info", "message": "Another test log"}
EOF

# Check collector logs for ingestion
docker-compose -f docker-compose.buildpacks.yml logs -f otel-collector

# Verify in Kibana (http://localhost:5601)
```

______________________________________________________________________

## Troubleshooting

### Problem: No traces appearing in Jaeger

**Symptoms:**

- Jaeger UI shows no traces
- Test client runs without errors

**Solutions:**

1. **Check collector is receiving data:**

   ```bash
   docker-compose -f docker-compose.buildpacks.yml logs otel-collector | grep -i "span"
   ```

1. **Verify Jaeger exporter configuration:**

   ```bash
   # Check collector config
   cat config/otel-collector-config.yaml | grep -A 5 "jaeger:"
   ```

1. **Test Jaeger connection:**

   ```bash
   docker exec -it $(docker ps -q -f name=jaeger) nc -zv localhost 14250
   ```

1. **Check exporter logs:**

   ```bash
   docker-compose -f docker-compose.buildpacks.yml logs otel-collector | grep -i "exporter"
   ```

### Problem: "Connection refused" errors

**Symptoms:**

- `Error: 14 UNAVAILABLE: Connection refused`
- Client fails to connect

**Solutions:**

1. **Verify collector is running:**

   ```bash
   docker-compose -f docker-compose.buildpacks.yml ps otel-collector
   ```

1. **Check ports are exposed:**

   ```bash
   netstat -tuln | grep 4317  # Should show LISTEN
   netstat -tuln | grep 4318  # Should show LISTEN
   ```

1. **Verify endpoint URL:**

   - Use `http://localhost:4317` (not `https://`)
   - For Docker networking, use service name: `http://otel-collector:4317`

1. **Restart collector:**

   ```bash
   docker-compose -f docker-compose.buildpacks.yml restart otel-collector
   ```

### Problem: Metrics not appearing in Prometheus

**Symptoms:**

- Prometheus UI has no data
- Query returns "no results"

**Solutions:**

1. **Check Prometheus target:**

   ```bash
   curl http://localhost:9090/api/v1/targets
   ```

1. **Verify remote write is working:**

   ```bash
   curl -X POST http://localhost:9090/api/v1/write -d '
     # TYPE test_metric counter
     test_metric{label="value"} 42
   '
   ```

1. **Check collector metrics:**

   ```bash
   curl http://localhost:8888/metrics
   ```

### Problem: Logs not in Elasticsearch

**Symptoms:**

- Kibana shows no data
- Index not created

**Solutions:**

1. **Verify Elasticsearch is running:**

   ```bash
   curl http://localhost:9200/_cluster/health
   ```

1. **Check index exists:**

   ```bash
   curl http://localhost:9200/_cat/indices?v
   ```

1. **Test index creation:**

   ```bash
   curl -X PUT http://localhost:9200/mahavishnu-logs-test
   ```

1. **Check Elasticsearch logs:**

   ```bash
   docker-compose -f docker-compose.buildpacks.yml logs elasticsearch
   ```

### Problem: File log receiver not working

**Symptoms:**

- Log files exist but not appearing in Kibana
- No errors in collector logs

**Solutions:**

1. **Verify file paths in config:**

   ```bash
   cat config/otel-collector-config.yaml | grep -A 5 "filelog:"
   ```

1. **Check file permissions:**

   ```bash
   ls -la /var/log/mahavishnu/sessions/
   ```

1. **Verify volume mount in docker-compose:**

   ```yaml
   services:
     otel-collector:
       volumes:
         - /var/log/mahavishnu/sessions:/var/log/mahavishnu/sessions:ro
   ```

1. **Test file accessibility from container:**

   ```bash
   docker exec -it $(docker ps -q -f name=otel-collector) ls -la /var/log/mahavishnu/sessions/
   ```

### Problem: High memory usage

**Symptoms:**

- Collector OOM killed
- High memory consumption

**Solutions:**

1. **Adjust batch processor settings:**

   ```yaml
   processors:
     batch:
       timeout: 10s  # Increase timeout
       send_batch_size: 5000  # Decrease batch size
   ```

1. **Enable memory limiter:**

   ```yaml
   processors:
     memory_limiter:
       check_interval: 1s
       limit_percentage: 70  # Decrease from 80
       spike_limit_percentage: 20
   ```

1. **Increase container memory:**

   ```yaml
   services:
     otel-collector:
       deploy:
         resources:
           limits:
             memory: 1G
   ```

### Problem: Mixed telemetry from different sources

**Symptoms:**

- Can't distinguish Claude vs Qwen traces
- All telemetry appears as one service

**Solutions:**

1. **Use separate endpoints:**

   - Claude: `http://localhost:4319`
   - Qwen: `http://localhost:4321`

1. **Set resource attributes:**

   ```python
   resource = Resource.create({
       "telemetry.source": "claude",  # or "qwen"
       "telemetry.source.type": "ai_assistant"
   })
   ```

1. **Verify in Jaeger:**

   - Search by service name
   - Filter by `telemetry.source` tag

______________________________________________________________________

## Production Checklist

### Configuration

- [ ] Update deployment environment in config: `deployment.environment: production`
- [ ] Configure TLS for production endpoints (set `insecure: false`)
- [ ] Adjust batch sizes for production load
- [ ] Configure log rotation for file logs
- [ ] Set up volume mounts for persistence

### Security

- [ ] Enable TLS on all exporters
- [ ] Configure authentication for OTLP endpoints
- [ ] Set up network policies for inter-service communication
- [ ] Rotate API keys and secrets
- [ ] Enable security groups/firewall rules

### Performance

- [ ] Configure appropriate batch sizes and timeouts
- [ ] Enable memory limiter with appropriate thresholds
- [ ] Set up sending queues for high-throughput scenarios
- [ ] Configure retry policies for failed exports
- [ ] Load test collector with expected traffic

### Monitoring

- [ ] Set up alerts for collector health
- [ ] Monitor exporter success rates
- [ ] Track pipeline processing times
- [ ] Monitor memory usage and OOM kills
- [ ] Set up dashboard for collector metrics

### High Availability

- [ ] Deploy multiple collector instances
- [ ] Configure load balancer for OTLP endpoints
- [ ] Set up collector health checks
- [ ] Configure automatic restarts
- [ ] Set up backup exporters

### Data Retention

- [ ] Configure Elasticsearch index retention
- [ ] Set up Prometheus data retention
- [ ] Configure Jaeger trace sampling
- [ ] Set up log archival for long-term storage
- [ ] Configure data deletion policies

### Documentation

- [ ] Document all custom attributes and labels
- [ ] Create runbooks for common issues
- [ ] Document source-specific configurations
- [ ] Create onboarding documentation for developers
- [ ] Set up API documentation for custom integrations

______________________________________________________________________

## Additional Resources

- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [OpenTelemetry Python SDK](https://opentelemetry.io/docs/instrumentation/python/)
- [OTel Collector Configuration Reference](https://opentelemetry.io/docs/collector/configuration/)
- [Jaeger Documentation](https://www.jaegertracing.io/docs/)
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Elasticsearch Documentation](https://www.elastic.co/guide/en/elasticsearch/reference/current/index.html)

______________________________________________________________________

## Quick Reference

### Port Summary

| Service | Port | Purpose |
|---------|------|---------|
| OTLP (Primary gRPC) | 4317 | Primary OTLP ingestion |
| OTLP (Primary HTTP) | 4318 | Primary OTLP HTTP |
| OTLP (Claude gRPC) | 4319 | Claude-specific OTLP |
| OTLP (Claude HTTP) | 4320 | Claude-specific HTTP |
| OTLP (Qwen gRPC) | 4321 | Qwen-specific OTLP |
| OTLP (Qwen HTTP) | 4322 | Qwen-specific HTTP |
| Jaeger UI | 16686 | Trace visualization |
| Prometheus | 9090 | Metrics query |
| Grafana | 3000 | Metrics dashboards |
| Kibana | 5601 | Log visualization |
| Elasticsearch | 9200 | Log storage API |

### Environment Variables

```bash
# Primary collector
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SERVICE_NAME=my-service

# Claude collector
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4319
export OTEL_SERVICE_NAME=claude-integration
export OTEL_RESOURCE_ATTRIBUTES=telemetry.source=claude

# Qwen collector
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4321
export OTEL_SERVICE_NAME=qwen-integration
export OTEL_RESOURCE_ATTRIBUTES=telemetry.source=qwen
```

### Docker Commands

```bash
# Start stack
docker-compose -f docker-compose.buildpacks.yml up -d

# View logs
docker-compose -f docker-compose.buildpacks.yml logs -f otel-collector

# Restart collector
docker-compose -f docker-compose.buildpacks.yml restart otel-collector

# Stop stack
docker-compose -f docker-compose.buildpacks.yml down

# Stop with volumes
docker-compose -f docker-compose.buildpacks.yml down -v
```

______________________________________________________________________

**Last Updated:** 2025-01-31
**Version:** 1.0.0
**Maintainer:** Mahavishnu Team
