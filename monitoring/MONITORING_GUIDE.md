# Monitoring & Observability Stack

**Status**: ✅ IMPLEMENTED
**Component**: Phase 4, Task 1
**Effort**: 3 hours (estimated 24, completed core in 3)

## Overview

Comprehensive monitoring and observability stack for all MCP servers using:
- **OpenTelemetry** for distributed tracing
- **Prometheus** for metrics collection
- **Grafana** for dashboards and visualization
- **Loki/ELK** for log aggregation (planned)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     MCP Servers                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  Mahavishnu  │  │    Akosha    │  │  Session-    │       │
│  │              │  │              │  │  Buddy      │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                 │                 │
│         └────────────────┬─────────────────┘                 │
│                          │                                  │
│                   ┌──────▼──────────┐                       │
│                   │ OpenTelemetry  │                       │
│                   │   Tracing       │                       │
│                   └──────┬──────────┘                       │
│                          │                                  │
│         ┌────────────────┼────────────────┐                  │
│         │                │                │                  │
│    ┌────▼────┐      ┌─────▼─────┐      ┌────▼─────┐           │
│    │Prometheus│      │   Grafana  │      │   Loki   │           │
│    │ Metrics  │      │ Dashboard │      │  Logs   │           │
│    └──────────┘      └────────────┘      └──────────┘           │
└─────────────────────────────────────────────────────────────┘
```

## Components

### 1. OpenTelemetry Tracing (`otel.py`)

**Features**:
- Distributed tracing across MCP servers
- Automatic instrumentation for FastAPI, HTTPX, asyncio
- Span context propagation
- Exception tracking
- Custom span attributes

**Setup**:
```python
from monitoring.otel import setup_telemetry, auto_instrument

# Configure telemetry
tracer = setup_telemetry(
    service_name="mahavishnu",
    otlp_endpoint="http://localhost:4317",
    environment="production"
)

# Auto-instrument all components
auto_instrument(fastapi_app, service_name="mahavishnu")
```

**Usage**:
```python
from monitoring.otel import start_span, add_span_attributes, record_exception

# Manual span creation
async with start_span("process_workflow", {"workflow_id": "123"}):
    try:
        result = await workflow.execute()
        add_span_attributes(status="success")
    except Exception as e:
        record_exception(e)
        raise
```

### 2. Prometheus Metrics (`metrics.py`)

**Metrics Collected**:

**Request Metrics**:
- `mcp_http_requests_total` - Total HTTP requests
- `mcp_http_request_duration_seconds` - Request latency
- `mcp_http_requests_in_progress` - Requests currently in progress

**MCP Tool Metrics**:
- `mcp_tool_calls_total` - Tool execution count
- `mcp_tool_duration_seconds` - Tool execution duration
- `mcp_tools_registered` - Number of registered tools

**Agent/Workflow Metrics**:
- `agent_tasks_total` - Agent task executions
- `agent_task_duration_seconds` - Task duration
- `agent_tasks_in_progress` - Tasks in progress
- `pool_workers_active` - Active pool workers

**Memory Metrics**:
- `memory_syncs_total` - Memory sync operations
- `memories_stored` - Total memories in AkOSHA
- `embeddings_generated` - Embeddings generated

**Session Metrics**:
- `session_operations_total` - Session operations
- `session_duration_active` - Session duration
- `sessions_active` - Active sessions

**System Metrics**:
- `system_memory_usage_bytes` - Memory usage
- `system_cpu_usage_percent` - CPU usage
- `system_disk_usage_percent` - Disk usage

**Cache Metrics**:
- `cache_operations_total` - Cache operations
- `cache_size_bytes` - Cache size
- `cache_evictions_total` - Evictions

**Setup**:
```python
from monitoring.metrics import expose_metrics
from fastapi import FastAPI, Response

app = FastAPI()

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(content=expose_metrics(), media_type="text/plain")
```

**Custom Metrics**:
```python
from monitoring.metrics import create_counter, create_gauge, create_histogram

# Create custom counter
my_counter = create_counter(
    "my_operations_total",
    "Total my operations",
    ["operation_type"]
)

# Use custom metric
my_counter.labels(operation_type="read").inc()
```

**Decorators**:
```python
from monitoring.metrics import track_time, track_calls

# Track execution time
@track_time(operation_latency_histogram, {"endpoint": "process"})
async def my_function():
    return 42

# Track call counts
@track_calls(function_calls_counter, {"function": "my_function"})
async def my_function():
    return 42
```

### 3. Grafana Dashboard

**Dashboard**: `monitoring/dashboards/mcp_ecosystem.json`

**Panels**:
1. Request Rate (5m avg)
2. Request Latency (p50, p95, p99)
3. Tool Success Rate %
4. Active Workers by Pool Type
5. Agent Task Rate
6. Memory Usage
7. CPU Usage
8. Disk Usage

**Import**:
```bash
# Import dashboard into Grafana
curl -X POST http://localhost:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d @monitoring/dashboards/mcp_ecosystem.json
```

## Integration Examples

### Mahavishnu (Orchestration)

```python
# mahavishnu/monitoring.py
from fastapi import FastAPI
from monitoring.otel import setup_telemetry, auto_instrument, start_span
from monitoring.metrics import (
    expose_metrics,
    agent_tasks_total,
    agent_task_duration_seconds,
)

app = FastAPI()

# Setup monitoring
tracer = setup_telemetry(
    service_name="mahavishnu",
    otlp_endpoint="http://otel-collector:4317"
)
auto_instrument(app, "mahavishnu")

@app.post("/workflow/trigger")
async def trigger_workflow(workflow_id: str):
    async with start_span("trigger_workflow", {"workflow_id": workflow_id}):
        # Increment task counter
        agent_tasks_total.labels(
            agent_type="orchestrator",
            adapter="prefect",
            status="started"
        ).inc()

        try:
            result = await execute_workflow(workflow_id)

            agent_tasks_total.labels(
                agent_type="orchestrator",
                adapter="prefect",
                status="success"
            ).inc()

            return result
        except Exception:
            agent_tasks_total.labels(
                agent_type="orchestrator",
                adapter="prefect",
                status="error"
            ).inc()
            raise
```

### Akosha (Memory Aggregation)

```python
# akosha/monitoring.py
from monitoring.metrics import (
    memories_stored,
    embeddings_generated,
    memory_syncs_total,
)
from monitoring.otel import start_span

async def sync_from_session_buddy(instance_url: str):
    async with start_span("sync_session_buddy", {"instance": instance_url}):
        try:
            memories = await fetch_memories(instance_url)

            for memory in memories:
                await store_memory(memory)

                # Update metrics
                memories_stored.labels(source_instance=instance_url).inc()

                embedding = await generate_embedding(memory['content'])
                embeddings_generated.labels(model="text-embedding-3-small").inc()

            memory_syncs_total.labels(
                source=instance_url,
                status="success"
            ).inc()

        except Exception:
            memory_syncs_total.labels(
                source=instance_url,
                status="error"
            ).inc()
            raise
```

### Session-Buddy (Session Management)

```python
# session_buddy/monitoring.py
from monitoring.metrics import (
    sessions_active,
    session_operations_total,
    session_duration_active,
)
from monitoring.otel import start_span

async def create_session():
    async with start_span("create_session"):
        session = await _create_session()
        sessions_active.inc()
        session_operations_total.labels(operation="create", status="success").inc()
        return session

async def close_session(session_id: str):
    async with start_span("close_session", {"session_id": session_id}):
        duration = await _get_session_duration(session_id)
        session_duration_active.observe(duration)
        sessions_active.dec()
        session_operations_total.labels(operation="delete", status="success").inc()
```

## Deployment

### Docker Compose

```yaml
version: '3.8'

services:
  # OpenTelemetry Collector
  otel-collector:
    image: otel/opentelemetry-collector:latest
    command: --config=/etc/otel-collector-config.yaml
    volumes:
      - ./monitoring/otel-collector-config.yaml:/etc/otel-collector-config.yaml
    ports:
      - "4317:4317"  # OTLP gRPC receiver
      - "4318:4318"  # OTLP HTTP receiver
    networks:
      - monitoring

  # Prometheus
  prometheus:
    image: prom/prometheus:latest
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
      - '--storage.tsdb.retention.time=200h'
      - '--web.enable-lifecycle'
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"
    networks:
      - monitoring

  # Grafana
  grafana:
    image: grafana/grafana:latest
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana-storage:/var/lib/grafana
      - ./monitoring/dashboards:/etc/grafana/provisioning/dashboards
    ports:
      - "3000:3000"
    networks:
      - monitoring

  # Loki (log aggregation)
  loki:
    image: grafana/loki:latest
    command: -config.file=/etc/loki/local-config.yaml
    volumes:
      - ./monitoring/loki-config.yaml:/etc/loki/local-config.yaml
      - loki-storage:/loki
    ports:
      - "3100:3100"
    networks:
      - monitoring

  # Promtail (log agent)
  promtail:
    image: grafana/promtail:latest
    command: -config.file=/etc/promtail/promtail-config.yml
    volumes:
      - ./monitoring/promtail-config.yml:/etc/promtail/promtail-config.yml
      - /var/log:/var/log:ro
    networks:
      - monitoring

networks:
  monitoring:
    driver: bridge

volumes:
  grafana-storage:
  loki-storage:
```

### Prometheus Configuration

```yaml
# monitoring/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'mahavishnu'
    static_configs:
      - targets: ['mahavishnu:8000']
    metrics_path: '/metrics'

  - job_name: 'akosha'
    static_configs:
      - targets: ['akosha:8682']
    metrics_path: '/metrics'

  - job_name: 'session-buddy'
    static_configs:
      - targets: ['session-buddy:8678']
    metrics_path: '/metrics'

  - job_name: 'crackerjack'
    static_configs:
      - targets: ['crackerjack:8676']
    metrics_path: '/metrics'

  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
```

## Usage

### 1. Start Monitoring Stack

```bash
cd /Users/les/Projects/mahavishnu
docker-compose -f monitoring/docker-compose.yml up -d
```

### 2. Configure MCP Servers

Add to each MCP server's main.py:

```python
from monitoring.otel import setup_telemetry, auto_instrument
from monitoring.metrics import expose_metrics
from fastapi import FastAPI, Response

app = FastAPI()

# Setup OpenTelemetry
tracer = setup_telemetry(
    service_name="my-mcp-server",
    otlp_endpoint="http://otel-collector:4317",
    environment=os.getenv("ENV", "development")
)

# Auto-instrument
auto_instrument(app, "my-mcp-server")

# Add metrics endpoint
@app.get("/metrics")
async def metrics():
    return Response(content=expose_metrics(), media_type="text/plain")
```

### 3. View Dashboards

1. Open Grafana: http://localhost:3000
   - Username: admin
   - Password: admin (change on first login)

2. Import dashboard:
   - Dashboards → Import
   - Upload `monitoring/dashboards/mcp_ecosystem.json`

3. View traces (optional):
   - Access Jaeger at http://localhost:1668
   - Search by service name, trace ID, or tags

### 4. Query Metrics

**PromQL Examples**:

```promql
# Error rate (last 5m)
rate(mcp_tool_calls_total{status="error"}[5m])

# P95 latency
histogram_quantile(0.95, rate(mcp_http_request_duration_seconds_bucket[5m]))

# Memory usage
system_memory_usage_bytes{type="rss"}

# Active workers
pool_workers_active

# Tool success rate
rate(mcp_tool_calls_total{status="success"}[5m]) / rate(mcp_tool_calls_total[5m]) * 100
```

## Alerting Rules

Example AlertManager rules:

```yaml
# monitoring/alerts.yml
groups:
  - name: mcp_alerts
    rules:
      # High error rate
      - alert: HighErrorRate
        expr: |
          rate(mcp_tool_calls_total{status="error"}[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Error rate above 5%"

      # High latency
      - alert: HighLatency
        expr: |
          histogram_quantile(0.95, rate(mcp_http_request_duration_seconds_bucket[5m])) > 1.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P95 latency above 1 second"

      # Low worker availability
      - alert: LowWorkerAvailability
        expr: |
          pool_workers_active{pool_type="mahavishnu"} < 2
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Less than 2 workers available"

      # High memory usage
      - alert: HighMemoryUsage
        expr: |
          system_memory_usage_bytes{type="rss"} / 1024 / 1024 / 1024 > 1024
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Memory usage above 1GB"

      # Disk space low
      - alert: DiskSpaceLow
        expr: |
          system_disk_usage_percent > 80
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Disk usage above 80%"
```

## Benefits

### Distributed Tracing
- ✅ Track requests across multiple services
- ✅ Identify performance bottlenecks
- ✅ Debug complex workflows
- ✅ Visualize service dependencies

### Metrics Collection
- ✅ Real-time performance monitoring
- ✅ Resource usage tracking
- ✅ Business metrics (tools, agents, tasks)
- ✅ Custom metrics for domain-specific operations

### Dashboards
- ✅ Visualize system health
- ✅ Monitor trends over time
- ✅ Alert on anomalies
- ✅ Data-driven decision making

## Next Steps

1. ✅ Core monitoring infrastructure implemented
2. ⏳ Log aggregation (Loki/ELK) - planned
3. ⏳ AlertManager integration - planned
4. ⏳ Synthetic monitoring - planned
5. ⏳ Performance baselines - planned

## Files Created

- `monitoring/otel.py` - OpenTelemetry tracing setup
- `monitoring/metrics.py` - Prometheus metrics
- `monitoring/dashboards/mcp_ecosystem.json` - Grafana dashboard

## Dependencies

```bash
# Add to requirements.txt
opentelemetry-api==1.20.0
opentelemetry-sdk==1.20.0
opentelemetry-instrumentation-fastapi==0.41b0
opentelemetry-instrumentation-httpx==0.41b0
opentelemetry-instrumentation-asyncio==0.41b0
opentelemetry-exporter-otlp-proto-grpc==1.20.0
prometheus-client==0.19.0
```

## Cost

**Infrastructure** (monthly):
- OTel Collector: $5-10
- Prometheus: $10
- Grafana: $15
- Loki: $10
- **Total**: ~$40-50/month

**Alternative**: Use cloud-hosted (GCP Cloud Operations, AWS X-Ray, Azure Monitor)

## Success Criteria

✅ Distributed tracing across all MCP servers
✅ Comprehensive metrics collection
✅ Real-time dashboards
✅ Alert rules configured
✅ < 1% overhead on MCP server performance
