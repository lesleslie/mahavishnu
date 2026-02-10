# Distributed Tracing Guide

**Integration #24: OpenTelemetry Distributed Tracing for Mahavishnu Ecosystem**

Table of Contents:
- [Overview](#overview)
- [Architecture](#architecture)
- [OpenTelemetry Integration](#opentelemetry-integration)
- [Context Propagation](#context-propagation)
- [Span Creation](#span-creation)
- [Trace Analysis](#trace-analysis)
- [Visualization](#visualization)
- [Setup Guides](#setup-guides)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)
- [API Reference](#api-reference)

## Overview

The Distributed Tracing integration provides comprehensive observability for debugging complex request flows across multiple services and repositories in the Mahavishnu ecosystem using OpenTelemetry standards.

### Key Features

- **OpenTelemetry SDK**: Industry-standard tracing instrumentation
- **Automatic Span Creation**: FastAPI, HTTPX auto-instrumentation
- **Context Propagation**: W3C Trace Context across A2A protocol
- **Trace Storage**: In-memory and file-based archival
- **Trace Analysis**: Performance profiling, bottleneck detection
- **Multiple Backends**: Jaeger, OTLP, custom storage
- **FastAPI Endpoints**: Query and analyze traces via REST API

### Why Distributed Tracing Matters

- **Debugging**: Trace requests across service boundaries
- **Performance**: Identify slow operations and bottlenecks
- **Dependency Analysis**: Understand service communication patterns
- **Compliance**: Meet audit and monitoring requirements
- **MTTR Improvement**: Reduce mean time to resolution

## Architecture

### Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  Distributed Tracing System                  │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Application Services                     │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ Mahavishnu│  │  Service A│  │  Service B│          │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘          │   │
│  │       │             │             │                   │   │
│  └───────┼─────────────┼─────────────┼───────────────────┘   │
│          │             │             │                       │
│          ▼             ▼             ▼                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              OpenTelemetry SDK                       │   │
│  │  ┌──────────────────────────────────────────────┐  │   │
│  │  │  Tracer Provider                              │  │   │
│  │  │  - Span Processors                             │  │   │
│  │  │  - BatchSpanProcessor (OTLP export)           │  │   │
│  │  │  - CollectorProcessor (in-memory)             │  │   │
│  │  └──────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                          │                                │
│          ┌───────────────┴────────────────┐               │
│          ▼                                ▼               │
│  ┌──────────────┐              ┌──────────────┐            │
│  │  Span        │              │  Trace       │            │
│  │  Collector   │              │  Storage     │            │
│  └──────────────┘              └──────────────┘            │
│          │                                │              │
│          └──────────────┬─────────────────┘              │
│                         ▼                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Trace Backend                         │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │  │
│  │  │  Jaeger    │  │  OTLP       │  │  File       │     │  │
│  │  │  (Temp)    │  │  (Prod)     │  │  (Archive)  │     │  │
│  │  └────────────┘  └────────────┘  └────────────┘     │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────┘
```

### Trace Flow

```
1. Service A receives request
   ↓
2. Service A creates root span
   Span(name: "process_request", kind: SERVER)
   ↓
3. Service A calls Service B
   ↓
4. Service A creates client span
   Span(name: "call_service_b", kind: CLIENT, parent: root)
   │
   ├─→ Extract trace context
   │   traceparent: "00-4bf92f...-00f067...-01"
   │   tracestate: "vendor=..."
   │
   └─→ Send HTTP request with headers
       traceparent, tracestate
   ↓
5. Service B receives request
   ↓
6. Service B extracts trace context
   ↓
7. Service B creates child span
   Span(name: "handle_request", kind: SERVER, parent: client_span_id)
   ↓
8. Service B processes request
   ↓
9. Service B returns response
   ↓
10. Both spans exported to OpenTelemetry backend
    ↓
11. Span collector aggregates spans by trace ID
    ↓
12. Complete trace built with span tree
    ↓
13. Trace stored and available for analysis
```

## OpenTelemetry Integration

### Setup

**1. Install Dependencies**:
```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-fastapi opentelemetry-instrumentation-httpx opentelemetry-exporter-otlp
```

**2. Initialize Distributed Tracing**:
```python
from mahavishnu.integrations.distributed_tracing import setup_distributed_tracing

# Set up distributed tracing
tracer = setup_distributed_tracing(
    service_name="mahavishnu",
    otlp_endpoint="http://localhost:4317",  # OTel Collector
    sample_rate=1.0,  # 100% sampling for debugging
    instrument_http=True,
)

print("✅ Distributed tracing initialized")
```

**3. Instrument FastAPI**:
```python
from fastapi import FastAPI
from mahavishnu.integrations.distributed_tracing import instrument_fastapi

app = FastAPI()

# Auto-instrument FastAPI
instrument_fastapi(
    app,
    service_name="mahavishnu",
    excluded_paths=["/health", "/metrics"],
)
```

**4. Create Spans Manually**:
```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def process_workflow(workflow_id: str):
    with tracer.start_as_current_span(
        "process_workflow",
        attributes={"workflow.id": workflow_id},
    ) as span:
        # Add event
        span.add_event(
            "workflow_started",
            attributes={"workflow.id": workflow_id, "timestamp": time.time()},
        )

        # Process workflow
        result = await execute_workflow(workflow_id)

        # Set status
        span.set_status(Status(StatusCode.OK))

        return result
```

### Configuration

**settings/mahavishnu.yaml**:
```yaml
distributed_tracing:
  enabled: true

  # OpenTelemetry configuration
  service_name: "mahavishnu"
  otlp_endpoint: "http://localhost:4317"

  # Sampling
  sample_rate: 0.1  # 10% sampling in production

  # Span storage
  max_memory_traces: 1000
  archive_path: "data/traces"
  retention_days: 30
```

**Environment Variables**:
```bash
export MAHAVISHNU_DISTRIBUTED_TRACING__ENABLED="true"
export MAHAVISHNU_DISTRIBUTED_TRACING__OTLP_ENDPOINT="http://localhost:4317"
export MAHAVISHNU_DISTRIBUTED_TRACING__SERVICE_NAME="mahavishnu"
export MAHAVISHNU_DISTRIBUTED_TRACING__SAMPLE_RATE="0.1"
```

### Exporter Configuration

**OTLP Exporter** (Recommended):
```python
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

exporter = OTLPSpanExporter(
    endpoint="http://localhost:4317",
    insecure=True,  # Development only
)
```

**Jaeger Exporter** (Legacy):
```python
from opentelemetry.exporter.jaeger.thrift import JaegerExporter

exporter = JaegerExporter(
    agent_host_name="localhost",
    agent_port=6831,
)
```

**Batch vs Simple Processor**:
```python
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

# Batch processor (recommended for production)
processor = BatchSpanProcessor(
    exporter,
    max_queue_size=2048,
    schedule_delay_millis=5000,  # Export every 5 seconds
    max_export_batch_size=512,
)

# Simple processor (for debugging)
processor = SimpleSpanProcessor(exporter)
```

## Context Propagation

### W3C Trace Context

The tracing system uses W3C Trace Context standard for distributed tracing.

**traceparent Header Format**:
```
version-trace_id-parent_id-flags

Example:
00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
││     │                               │                  │
││     └─ 64-bit parent span ID        └─ Trace flags (01 = sampled)
│
└─ 128-bit trace ID
```

**tracestate Header Format**:
```
vendor1=key1=value1,key2=value2,vendor2=key3=value3

Example:
mahavishnu=user:123,session:abc,tenant:456
```

### Context Propagation in A2A Protocol

**Send Trace Context**:
```python
from mahavishnu.integrations.distributed_tracing import TraceContext

async def call_remote_service(service_name: str, payload: dict):
    # Get current trace context
    ctx = TraceContext.get_current()

    # Create A2A metadata with trace context
    metadata = {
        "trace_id": str(ctx.trace_id),
        "parent_span_id": str(ctx.parent_span_id) if ctx.parent_span_id else None,
        "span_id": str(ctx.span_id),
        "baggage": ctx.baggage,
        "trace_state": ctx.trace_state,
    }

    # Send A2A request
    response = await a2a_client.call(
        service_name=service_name,
        method="process_request",
        params=payload,
        metadata=metadata,  # Include trace context
    )

    return response
```

**Receive Trace Context**:
```python
async def handle_a2a_request(params: dict, metadata: dict):
    # Extract trace context from A2A metadata
    ctx = TraceContext.from_a2a_metadata(metadata)

    if ctx:
        # Make context available
        async with ctx.use_context():
            # Process request with trace context
            return await process_request(params)
    else:
        # No trace context, create new
        ctx = TraceContext.create_new()
        async with ctx.use_context():
            return await process_request(params)
```

### HTTP Context Propagation

**Outgoing HTTP Request**:
```python
import httpx
from mahavishnu.integrations.distributed_tracing import add_trace_headers

async def http_call_with_tracing(url: str):
    # Add trace context to headers
    headers = add_trace_headers({
        "Authorization": "Bearer token",
        "Content-Type": "application/json",
    })

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response
```

**Incoming HTTP Request**:
```python
from fastapi import Request

@app.get("/api/resource")
async def get_resource(request: Request):
    # Trace context is automatically extracted by middleware
    trace_ctx = request.state.trace_context

    # Use trace context for manual spans
    with tracer.start_as_current_span("database_query"):
        result = await db.query("SELECT * FROM resources")
```

## Span Creation

### Span Attributes

**Best Practices for Span Attributes**:
```python
with tracer.start_as_current_span("process_payment") as span:
    # Add attributes
    span.set_attribute("payment.id", payment_id)
    span.set_attribute("payment.amount", amount)
    span.set_attribute("payment.currency", "USD")
    span.set_attribute("user.id", user_id)

    # Add events
    span.add_event(
        "payment_validated",
        attributes={
            "validation.method": "stripe",
            "validation.duration_ms": 123,
        },
    )

    # Process payment
    result = await process_payment(payment_id, amount)

    # Set status
    span.set_status(Status(StatusCode.OK))
```

**Semantic Attributes**:
```python
# Use OpenTelemetry semantic conventions
span.set_attribute("http.method", "GET")
span.set_attribute("http.url", "https://api.example.com/users")
span.set_attribute("http.status_code", 200)
span.set_attribute("http.route", "/api/users")

# Database attributes
span.set_attribute("db.system", "postgresql")
span.set_attribute("db.name", "production")
span.set_attribute("db.statement", "SELECT * FROM users")

# RPC attributes
span.set_attribute("rpc.system", "grpc")
span.set_attribute("rpc.service", "user.UserService")
span.set_attribute("rpc.method", "GetUser")
```

### Span Kinds

**SERVER Span**:
```python
@app.post("/api/users")
async def create_user(request: Request):
    # Automatically created by FastAPI instrumentation
    # Span(kind=SERVER, name="POST /api/users")
    return await create_user_logic(request.data)
```

**CLIENT Span**:
```python
async def call_external_api():
    with tracer.start_as_current_span(
        "external_api_call",
        kind=SpanKind.CLIENT,
    ) as span:
        span.set_attribute("http.method", "POST")
        span.set_attribute("http.url", "https://api.example.com")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.example.com/data",
                json={"data": "value"},
                headers=add_trace_headers({}),
            )

        return response
```

**INTERNAL Span**:
```python
async def process_data(data: list):
    with tracer.start_as_current_span(
        "data_processing",
        kind=SpanKind.INTERNAL,
    ) as span:
        span.set_attribute("data.count", len(data))

        # Process data
        result = await heavy_computation(data)

        return result
```

**PRODUCER/CONSUMER Span** (Message Queues):
```python
async def publish_message(queue: str, message: dict):
    with tracer.start_as_current_span(
        "publish_message",
        kind=SpanKind.PRODUCER,
    ) as span:
        span.set_attribute("messaging.system", "redis")
        span.set_attribute("messaging.destination", queue)
        span.set_attribute("messaging.message_id", message["id"])

        await redis.rpush(queue, json.dumps(message))
```

### Span Events

**Add Events to Timeline**:
```python
with tracer.start_as_current_span("order_processing") as span:
    # Event 1: Order received
    span.add_event(
        "order_received",
        attributes={
            "order.id": order_id,
            "order.amount": amount,
        },
    )

    # Event 2: Payment processed
    payment_result = await process_payment(order_id)

    span.add_event(
        "payment_processed",
        attributes={
            "payment.success": payment_result.success,
            "payment.duration_ms": payment_result.duration_ms,
        },
    )

    # Event 3: Order shipped
    await ship_order(order_id)

    span.add_event(
        "order_shipped",
        attributes={
            "shipping.carrier": "fedex",
            "shipping.tracking_number": tracking_number,
        },
    )
```

**Span Links**:
```python
# Link to related traces
with tracer.start_as_current_span("main_workflow") as main_span:
    main_span.add_link(
        link_context=LinkContext(
            trace_id=other_trace_id,
            span_id=other_span_id,
        ),
        attributes={
            "link.type": "related_workflow",
            "relationship": "caused_by",
        },
    )
```

## Trace Analysis

### Performance Profiling

**Find Slow Operations**:
```python
from mahavishnu.integrations.distributed_tracing import TraceAnalyzer

analyzer = TraceAnalyzer()

# Get trace
trace = await trace_storage.get_trace(trace_id)

# Analyze trace
insights = analyzer.analyze_trace(trace)

# Find slow spans
for span in insights["slow_spans"]:
    print(f"{span['name']}: {span['duration_ms']:.2f}ms")

# Output:
# database_query: 523.45ms
# external_api_call: 234.12ms
# data_processing: 123.67ms
```

**Identify Bottlenecks**:
```python
# Find performance bottlenecks
bottlenecks = analyzer._find_bottlenecks(trace, threshold_pct=10.0)

for bottleneck in bottlenecks:
    print(f"{bottleneck['name']}")
    print(f"  Duration: {bottleneck['duration_ms']:.2f}ms")
    print(f"  Parent: {bottleneck['parent_duration_ms']:.2f}ms")
    print(f"  Percentage: {bottleneck['percentage']:.1f}%")
```

**Critical Path Analysis**:
```python
# Find critical path (longest path through trace)
critical_path = analyzer._find_critical_path(trace)

print("Critical Path:")
for span in critical_path:
    print(f"  → {span['name']}: {span['duration_ms']:.2f}ms")
```

### Error Tracking

**Find Error Spans**:
```python
# Get all error spans
error_spans = trace.get_error_spans()

for span in error_spans:
    print(f"❌ {span['name']}")
    print(f"   Error: {span['status_description']}")
    print(f"   Duration: {span['duration_ms']:.2f}ms")
    print(f"   Parent: {span['parent_span_id']}")
```

**Trace Errors by Service**:
```python
# Group errors by service
errors_by_service = {}
for span in trace.spans:
    if span.status == StatusCode.ERROR:
        service = span.service_name
        if service not in errors_by_service:
            errors_by_service[service] = []
        errors_by_service[service].append(span)

# Print summary
for service, errors in errors_by_service.items():
    print(f"{service}: {len(errors)} errors")
```

### Dependency Analysis

**Service Communication Map**:
```python
# Analyze service dependencies
dependencies = analyzer._analyze_dependencies(trace)

print("Service Dependencies:")
for caller, callees in dependencies.items():
    print(f"{caller} → {', '.join(callees)}")
```

**Dependency Graph** (Mermaid):
```python
def generate_dependency_graph(traces: list[TraceModel]):
    """Generate Mermaid dependency graph."""

    all_dependencies = {}

    for trace in traces:
        deps = analyzer._analyze_dependencies(trace)

        for caller, callees in deps.items():
            if caller not in all_dependencies:
                all_dependencies[caller] = set()
            all_dependencies[caller].update(callees)

    # Generate Mermaid
    print("graph TD")
    for caller, callees in all_dependencies.items():
        for callee in callees:
            print(f"  {caller} --> {callee}")
```

## Trace Storage

### In-Memory Storage

**Configure In-Memory Storage**:
```python
from mahavishnu.integrations.distributed_tracing import TraceStorage, SpanCollector

# Create span collector
collector = SpanCollector(max_traces=1000)

# Create trace storage
storage = TraceStorage(
    archive_path="data/traces",
    retention_days=30,
    max_memory_traces=1000,
)

# Store trace
await storage.store_trace(trace)
```

**Query Traces**:
```python
from mahavishnu.integrations.distributed_tracing import TraceQuery

# Build query
query = TraceQuery(
    service_name="mahavishnu",
    min_duration_ms=1000,  # Slower than 1 second
    has_errors=True,  # Only errors
    limit=50,
)

# Query traces
traces = await storage.query_traces(query)

for trace in traces:
    print(f"{trace.trace_id}: {trace.duration_ms:.2f}ms")
```

### File-Based Archival

**Archive to File**:
```python
await storage._archive_trace(trace)

# Creates: data/traces/YYYY/MM/DD/{trace_id}.json
```

**Archive Structure**:
```
data/traces/
├── 2024/
│   ├── 01/
│   │   ├── 31/
│   │   │   └── 4bf92f3577b34da6a3ce929d0e0e4736.json
│   │   └── 30/
│   │       └── abc123...json
│   └── 02/
│       └── 01/
│           └── def456...json
```

**Cleanup Old Traces**:
```python
# Remove traces older than retention period
removed_count = await storage.cleanup_old_traces()

print(f"Removed {removed_count} old trace files")
```

### Export Formats

**Export to Jaeger JSON**:
```python
import json
from pathlib import Path

# Export trace to Jaeger format
output_path = Path("/tmp/trace.json")

await storage.export_jaeger(
    trace_id=trace_id,
    output_path=output_path,
)

# View file
jaeger-ui --trace=/tmp/trace.json
```

**Export to Jaeger UI**:
```bash
# Start Jaeger UI
docker run -d -p 16686:16686 -p 14268:14268 \
  -e COLLECTOR_ZIPKIN_HOST_PORT=zipkin:9411 \
  jaegertracing/all-in-one:latest

# Open UI
open http://localhost:16686
```

## Visualization

### Jaeger UI

**Setup Jaeger**:
```bash
# Using Docker
docker run -d --name jaeger \
  -e COLLECTOR_OTLP_ENABLED=true \
  -p 4317:4317 \
  -p 16686:16686 \
  jaegertracing/all-in-one:latest
```

**Query Traces**:
```bash
# Open Jaeger UI
open http://localhost:16686

# Search traces by:
# - Service name
# - Operation name
# - Tags
# - Duration
# - Time range
```

**Trace Waterfall View**:
```
Service A ──────┐
               │
Service B ──────┤
               │
Service C ──────┘

Timeline:
┌─ Service A ────────┐
│ ├─ Process      │
│ └─ Call B       │
└─────────────────┘
     │
     ▼
┌─ Service B ────────┐
│ ├─ Query DB      │
│ └─ Return A      │
└─────────────────┘
```

### Grafana Dashboard

**Setup Grafana Tempo**:
```bash
docker run -d -p 3100:3100 \
  -e TEMPO_QUERY_TEMPORAL_QUERY_URL=http://tempo:3200 \
  grafana/tempo:latest
```

**Data Source Configuration**:
```json
{
  "name": "Tempo",
  "type": "tempo",
  "url": "http://tempo:3200"
}
```

**Trace Query**:
```templo
{
  search: {
    query: "",
    filters: [
      {name: "Service", value: "mahavishnu", operator: "="},
      {name: "Name", value: "process_workflow", operator: "!="}
    ],
    limit: 100,
    range: 3600  # Last hour
  }
}
```

### Custom Visualizations

**Flamegraph**:
```python
import matplotlib.pyplot as plt

def create_flamegraph(trace: TraceModel, output_path: Path):
    """Create flamegraph visualization."""

    # Build hierarchical data
    def build_hierarchy(spans: list, parent_id=None, level=0):
        children = [s for s in spans if s.parent_span_id == parent_id]

        if not children:
            return []

        result = []
        for span in sorted(children, key=lambda s: s.start_time):
            node = {
                "name": span.name,
                "value": span.duration_ms,
                "children": build_hierarchy(spans, span.span_id, level + 1),
            }
            result.append(node)

        return result

    # Build hierarchy from root span
    data = {
        "name": "root",
        "value": trace.duration_ms,
        "children": build_hierarchy(trace.spans, trace.root_span.parent_span_id),
    }

    # Plot with plotly
    import plotly.express as px

    fig = px.icicle(
        data,
        maxdepth=10,
        title=f"Trace Flamegraph: {trace.trace_id}",
    )

    fig.write_image(output_path, width=1920, height=1080)
```

## Setup Guides

### Development Setup

**1. Install Dependencies**:
```bash
cd /path/to/mahavishnu
pip install -e ".[dev]"
```

**2. Enable Tracing**:
```yaml
# settings/mahavishnu.yaml
distributed_tracing:
  enabled: true
  service_name: "mahavishnu-dev"
  otlp_endpoint: "http://localhost:4317"
  sample_rate: 1.0  # 100% sampling for development
```

**3. Start Jaeger**:
```bash
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  jaegertracing/all-in-one:latest
```

**4. Initialize Tracing**:
```python
from mahavishnu.integrations.distributed_tracing import setup_distributed_tracing

tracer = setup_distributed_tracing(
    service_name="mahavishnu-dev",
    otlp_endpoint="http://localhost:4317",
    sample_rate=1.0,
)
```

**5. Test Tracing**:
```python
# Create manual span
with tracer.start_as_current_span("test_operation"):
    # View in Jaeger UI
    # http://localhost:16686/search
    pass
```

### Production Setup

**1. Install OpenTelemetry Collector**:
```bash
# Download OTel Collector
wget https://github.com/open-telemetry/opentelemetry-collector-releases/latest/download/otelcol_${VERSION}_linux_amd64.tar.gz
tar xvfz otelcol_${VERSION}_linux_amd64.tar.gz
```

**2. Configure Collector** (`otel-collector-config.yaml`):
```yaml
receivers:
  otlp:
    protocols:
      - grpc
      - http

exporters:
  jaeger:
    endpoint: jaeger:14250
    tls:
      insecure: true

  logging:
    loglevel: info

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [jaeger, logging]
```

**3. Start Collector**:
```bash
./otelcol --config otel-collector-config.yaml
```

**4. Configure Mahavishnu**:
```yaml
# settings/mahavice_number.yaml
distributed_tracing:
  enabled: true
  service_name: "mahavishnu-prod"
  otlp_endpoint: "http://otel-collector:4317"
  sample_rate: 0.1  # 10% sampling in production

  # Storage
  archive_path: "data/traces"
  retention_days: 90
  max_memory_traces: 10000
```

### AWS Distro for OpenTelemetry

**1. Create AWS ADOT Collector**:
```bash
# Using AWS Distro for OpenTelemetry Collector
docker run -d --name adot \
  -v $(pwd)/adot-config.yaml:/etc/otelcol-contrib.yaml \
  -p 4317:4317 \
  -p 4318:4318 \
  -e AWS_REGION=us-east-1 \
  amazon/aws-distro-opentelemetry-collector:latest
```

**2. Configure X-Ray Tracing** (`adot-config.yaml`):
```yaml
extensions:
  awsxray:
    region: us-east-1

receivers:
  otlp:
    protocols:
      - grpc
      - http

exporters:
  awsxray:
    region: us-east-1

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [awsxray]
```

**3. Configure Mahavishnu**:
```yaml
distributed_tracing:
  otlp_endpoint: "http://adot:4317"
  sample_rate: 0.05  # 5% sampling
```

## Best Practices

### Span Naming

**Good Names**:
```python
# ✅ Specific and actionable
"process_payment"
"database_query_select_users"
"external_api_call_stripe"
```

**Bad Names**:
```python
# ❌ Vague and generic
"function"
"do_work"
"handle_it"
```

### Attribute Best Practices

**Use Semantic Conventions**:
```python
# ✅ Follow semantic conventions
span.set_attribute("http.method", "GET")
span.set_attribute("http.url", "/api/users")
span.set_attribute("http.status_code", 200)
span.set_attribute("db.system", "postgresql")
span.set_attribute("db.statement", "SELECT * FROM users")

# ❌ Custom attributes
span.set_attribute("method", "GET")
span.set_attribute("path", "/api/users")
span.set_attribute("status", "200")
span.set_attribute("database", "postgres")
```

**Attribute Cardinality**:
```python
# ✅ Low cardinality (good for grouping)
span.set_attribute("service.name", "mahavishnu")
span.set_attribute("deployment.environment", "production")

# ❌ High cardinality (avoid)
span.set_attribute("user.id", "user_12345")  # Too many unique values
span.set_attribute("request.id", "req_abc123")  # Unique for each request
```

### Sampling Strategies

**Static Sampling**:
```python
# Sample 10% of traces
tracer = setup_distributed_tracing(
    service_name="mahavishnu",
    sample_rate=0.1,  # 10% sampling
)
```

**Dynamic Sampling** (Advanced):
```python
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

# Sample based on trace ID
sampler = TraceIdRatioBased(0.1)  # 10% sampling

# Adjust sampling based on traffic
def get_sample_rate(trace_id: int) -> float:
    # Sample error traces at 100%
    if is_error_trace(trace_id):
        return 1.0

    # Sample slow traces at 50%
    if is_slow_trace(trace_id):
        return 0.5

    # Sample normal traces at 1%
    return 0.01
```

### Performance Considerations

**Batch Span Processing**:
```python
# Export in batches (default)
processor = BatchSpanProcessor(
    exporter,
    max_queue_size=2048,
    schedule_delay_millis=5000,  # Export every 5 seconds
    max_export_batch_size=512,
)
```

**Async Span Processing**:
```python
# CollectorProcessor runs asynchronously
class CollectorProcessor(SpanProcessor):
    def on_end(self, span: ReadableSpan):
        # Forward to collector asynchronously
        asyncio.create_task(self.collector.add_span(span))
```

## Troubleshooting

### Common Issues

**Issue: "No traces appearing in Jaeger"**

**Cause**: OTel endpoint misconfigured

**Solution**:
```bash
# Check OTel Collector is running
curl http://localhost:4317/

# Check Mahavishnu configuration
echo $MAHAVISHNU_DISTRIBUTED_TRACING__OTLP_ENDPOINT

# Check sample rate (might be 0!)
echo $MAHAVISHISHNU_DISTRIBUTED_TRACING__SAMPLE_RATE
```

**Issue: "Spans not connected in trace tree"**

**Cause**: Context propagation not working

**Solution**:
```python
# Verify trace context is being propagated
print(f"Trace ID: {trace_context.trace_id}")
print(f"Parent Span: {trace_context.parent_span_id}")

# Check traceparent header
traceparent = trace_context.to_traceparent_header()
print(f"traceparent: {traceparent}")

# Should be in format: 00-trace_id-parent_id-flags
```

**Issue: "High memory usage from trace storage"**

**Cause**: Too many traces stored in memory

**Solution**:
```python
# Reduce max memory traces
storage = TraceStorage(
    max_memory_traces=1000,  # Down from 10000
)

# Or disable in-memory storage entirely
# Use only archival storage
```

### Debug Mode

**Enable Verbose Logging**:
```yaml
# settings/mahavishnu.yaml
log_level: "DEBUG"
```

**Debug Span Creation**:
```python
import logging

logging.basicConfig(level=logging.DEBUG)

# Enable OpenTelemetry logging
import opentelemetry.sdk._logs as otel_logs
otel_logs.set_logger_level(logging.DEBUG)
```

## API Reference

### Core Classes

#### `TraceContext`

Distributed trace context for propagation.

**Methods**:

##### `create_new()`
Create new trace context with new trace ID.

##### `from_headers()`
Extract trace context from HTTP headers.

##### `to_headers()`
Convert to HTTP headers for propagation.

##### `to_a2a_metadata()`
Convert to A2A protocol metadata format.

#### `TraceModel`

Complete trace with all spans.

**Methods**:

##### `get_span_tree()`
Build span tree organized by parent.

##### `get_slowest_spans()`
Get N slowest spans in the trace.

##### `get_error_spans()`
Get all spans with error status.

##### `get_service_breakdown()`
Get performance breakdown by service.

#### `TraceStorage`

Trace storage and querying.

**Methods**:

##### `store_trace()`
Store trace in memory and optionally archive.

##### `get_trace()`
Get trace by ID.

##### `query_traces()`
Query traces with filters.

##### `export_jaeger()`
Export trace to Jaeger JSON format.

---

**Next**: [Configuration Management Guide](CONFIGURATION_MANAGEMENT_GUIDE.md)
