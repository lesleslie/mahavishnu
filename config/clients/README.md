# OTLP Client Examples and Testing Tools

This directory contains example OTLP clients and testing tools for the Mahavishnu observability stack.

## Files

| File | Purpose |
|------|---------|
| `python-otlp-client.py` | Complete Python OTLP client with examples for traces, metrics, and logs |
| `docker-compose.otlp.yml` | Standalone OTel stack for testing without full Mahavishnu |
| `otel-collector-test-config.yaml` | Lightweight collector configuration for testing |
| `prometheus.yml` | Prometheus configuration for test stack |
| `grafana-datasources.yml` | Grafana datasource provisioning |
| `quickstart.sh` | Quick start script to launch test stack and send example telemetry |

## Quick Start

### Option 1: Using the Test Stack (Recommended for Learning)

Launch a standalone OTel stack for testing:

```bash
cd /Users/les/Projects/mahavishnu/config/clients

# Start the test stack
docker-compose -f docker-compose.otlp.yml up -d

# Wait for services to be healthy
sleep 10

# Verify stack is running
curl http://localhost:13133/healthy
```

### Option 2: Using Full Mahavishnu Stack

If you have the full Mahavishnu stack running:

```bash
# The collector is already running
curl http://localhost:13133/healthy
```

## Send Test Telemetry

### Using the Python Client

```bash
cd /Users/les/Projects/mahavishnu/config/clients

# Install dependencies
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc

# Send telemetry to primary collector
python python-otlp-client.py --endpoint http://localhost:4317 --service test-app

# Send Claude-specific telemetry
python python-otlp-client.py --endpoint http://localhost:4319 --service claude-integration --source claude --ai-workflow

# Send Qwen-specific telemetry
python python-otlp-client.py --endpoint http://localhost:4321 --service qwen-integration --source qwen --ai-workflow

# With console debugging (see what's being sent)
python python-otlp-client.py --endpoint http://localhost:4317 --service test-app --console

# Generate only traces
python python-otlp-client.py --endpoint http://localhost:4317 --service test-app --traces-only --count 20

# Generate only metrics
python python-otlp-client.py --endpoint http://localhost:4317 --service test-app --metrics-only --count 50

# Generate only logs
python python-otlp-client.py --endpoint http://localhost:4317 --service test-app --logs-only --count 20
```

### Using cURL (HTTP Only)

```bash
# Send a log via HTTP OTLP
curl -X POST http://localhost:4318/v1/logs \
  -H "Content-Type: application/json" \
  -d '{
    "resourceLogs": [{
      "resource": {
        "attributes": {
          "service.name": "curl-test"
        }
      },
      "scopeLogs": [{
        "scope": {"name": "test"},
        "logRecords": [{
          "timeUnixNano": '$(date +%s)000000000',
          "severityNumber": 9,
          "severityText": "INFO",
          "body": {"stringValue": "Test log from cURL"}
        }]
      }]
    }]
  }'
```

## View Telemetry

Once you've sent telemetry, view it in the UIs:

| UI | URL | Purpose |
|----|-----|---------|
| **Jaeger** | http://localhost:16686 | View distributed traces |
| **Prometheus** | http://localhost:9090 | Query metrics |
| **Grafana** | http://localhost:3000 | Metrics dashboards (admin/admin) |
| **Collector Health** | http://localhost:13133/healthy | Check collector status |

### Viewing Traces in Jaeger

1. Open http://localhost:16686
1. Click "Search" (or select your service from the dropdown)
1. Click "Find Traces"
1. Click on a trace to see details
1. Expand spans to see nested operations

### Viewing Metrics in Prometheus

1. Open http://localhost:9090
1. Enter a query like: `operations_total`
1. Click "Execute"
1. View the graph or table results

### Viewing Metrics in Grafana

1. Open http://localhost:3000
1. Login with `admin` / `admin`
1. Click "Explore" (on the left)
1. Select "Prometheus" datasource
1. Enter query: `operations_total`
1. Click "Run query"

## Environment Variables

The Python client can also be configured using environment variables:

```bash
# Primary collector
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SERVICE_NAME=my-app
export OTEL_RESOURCE_ATTRIBUTES=telemetry.source=custom

# Claude collector
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4319
export OTEL_SERVICE_NAME=claude-integration
export OTEL_RESOURCE_ATTRIBUTES=telemetry.source=claude

# Qwen collector
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4321
export OTEL_SERVICE_NAME=qwen-integration
export OTEL_RESOURCE_ATTRIBUTES=telemetry.source=qwen
```

## Python Client Options

```
usage: python-otlp-client.py [-h] [--endpoint ENDPOINT] [--service SERVICE]
                             [--source SOURCE] [--environment ENVIRONMENT]
                             [--console] [--traces-only] [--metrics-only]
                             [--logs-only] [--count COUNT] [--ai-workflow]

OTLP Client for Mahavishnu Observability Stack

optional arguments:
  -h, --help            show this help message and exit
  --endpoint ENDPOINT   OTLP endpoint (default: http://localhost:4317)
  --service SERVICE     Service name (default: python-otlp-client)
  --source SOURCE       Source identifier (e.g., claude, qwen, custom)
  --environment ENVIRONMENT
                        Deployment environment (default: development)
  --console             Also export to console for debugging
  --traces-only         Only generate traces
  --metrics-only        Only generate metrics
  --logs-only           Only generate logs
  --count COUNT         Number of items to generate (default: 10)
  --ai-workflow         Simulate AI assistant workflow
```

## Testing File Log Ingestion

To test file log ingestion:

```bash
# Create test log directory
sudo mkdir -p /var/log/mahavishnu/sessions/claude

# Write test log entries
cat <<EOF | sudo tee -a /var/log/mahavishnu/sessions/claude/test-session.log
{"timestamp": "2025-01-31T12:00:00Z", "session_id": "test-123", "source": "claude", "level": "info", "message": "Claude started processing"}
{"timestamp": "2025-01-31T12:00:01Z", "session_id": "test-123", "source": "claude", "level": "info", "message": "Prompt received", "metadata": {"prompt_length": 150}}
{"timestamp": "2025-01-31T12:00:02Z", "session_id": "test-123", "source": "claude", "level": "info", "message": "Response generated", "metadata": {"response_length": 500, "duration_ms": 1234}}
EOF

# Check collector logs to see ingestion
docker-compose -f docker-compose.otlp.yml logs -f otel-collector

# Or with full stack
docker-compose -f /Users/les/Projects/mahavishnu/docker-compose.buildpacks.yml logs -f otel-collector
```

## Cleanup

```bash
# Stop test stack
cd /Users/les/Projects/mahavishnu/config/clients
docker-compose -f docker-compose.otlp.yml down

# Stop test stack and remove volumes
docker-compose -f docker-compose.otlp.yml down -v
```

## Integration Examples

### Flask Application

```python
from flask import Flask
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Setup
provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
))
trace.set_tracer_provider(provider)

app = Flask(__name__)

@app.route('/')
def hello():
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("hello-request"):
        return "Hello with telemetry!"
```

### FastAPI Application

```python
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Setup
provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
))
trace.set_tracer_provider(provider)

app = FastAPI()

@app.get("/")
def hello():
    return {"message": "Hello with telemetry!"}
```

## Troubleshooting

### Collector not receiving data

```bash
# Check collector health
curl http://localhost:13133/healthy

# Check collector logs
docker-compose -f docker-compose.otlp.yml logs otel-collector

# Verify port is listening
netstat -tuln | grep 4317
```

### No traces in Jaeger

```bash
# Check Jaeger is running
curl http://localhost:16686

# Check collector to Jaeger connection
docker-compose -f docker-compose.otlp.yml logs otel-collector | grep -i jaeger
```

### No metrics in Prometheus

```bash
# Check Prometheus targets
curl http://localhost:9090/api/v1/targets

# Query all metrics
curl http://localhost:9090/api/v1/label/__name__/values
```

### Connection refused errors

```bash
# Verify OTLP endpoint
curl http://localhost:4317

# Check Docker network
docker network ls
docker network inspect otlp-test-network
```

## Next Steps

- See [OTLP Setup Guide](../../docs/OTLP_SETUP_GUIDE.md) for comprehensive documentation
- Check the main [otel-collector-config.yaml](../otel-collector-config.yaml) for production configuration
- Review [OpenTelemetry Documentation](https://opentelemetry.io/docs/) for more information
