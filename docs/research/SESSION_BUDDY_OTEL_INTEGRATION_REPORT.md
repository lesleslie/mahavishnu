# Session-Buddy OpenTelemetry Integration Research Report

**Date**: 2026-01-31
**Researcher**: Claude (Research Analyst Agent)
**Status**: ✅ Research Complete

---

## Executive Summary

Session-Buddy has **no native OpenTelemetry (OTel) instrumentation** but provides extensive monitoring and analytics capabilities through custom implementations. Mahavishnu has **complete OTel support** with OTLP export capabilities already configured. Integration requires bridging Session-Buddy's custom metrics to Mahavishnu's OTel infrastructure.

**Key Findings:**
- ✅ Mahavishnu has full OTel/OTLP support with OpenTelemetry Collector
- ❌ Session-Buddy uses custom analytics (DuckDB) instead of OTel
- ✅ Both systems have complementary monitoring capabilities
- ⚠️ Integration requires Session-Buddy → OTel adapter or direct Mahavishnu polling

---

## Table of Contents

1. [Session-Buddy Current Capabilities](#session-buddy-current-capabilities)
2. [Mahavishnu OTel Infrastructure](#mahavishnu-otel-infrastructure)
3. [Integration Options](#integration-options)
4. [Configuration Requirements](#configuration-requirements)
5. [Recommendations](#recommendations)
6. [Implementation Roadmap](#implementation-roadmap)

---

## 1. Session-Buddy Current Capabilities

### 1.1 Existing Monitoring Infrastructure

Session-Buddy has extensive monitoring but **no OTel instrumentation**:

#### **Workflow Metrics Engine**
- **Location**: `/Users/les/Projects/session-buddy/session_buddy/core/workflow_metrics.py`
- **Purpose**: Track development velocity and quality trends
- **Storage**: DuckDB database (`~/.claude/data/workflow_metrics.db`)
- **Metrics Collected**:

```python
SessionMetrics:
  - session_id: str
  - project_path: str
  - started_at/ended_at: datetime
  - duration_minutes: float
  - checkpoint_count: int
  - commit_count: int
  - quality_start/quality_end/quality_delta: float
  - avg_quality: float
  - files_modified: int
  - tools_used: list[str]
  - primary_language: str | None
  - time_of_day: str  # "morning", "afternoon", "evening", "night"
```

**Aggregated Metrics**:
- `avg_velocity_commits_per_hour`: Development speed
- `quality_trend`: "improving", "stable", "declining"
- `most_productive_time_of_day`: Best working hours
- `most_used_tools`: Tool usage frequency
- `active_projects`: List of projects with activity

#### **Usage Analytics Tracker**
- **Location**: `/Users/les/Projects/session-buddy/session_buddy/analytics/usage_tracker.py`
- **Purpose**: Adaptive result ranking based on user interaction patterns
- **Tracking Data**:

```python
ResultInteraction:
  - query: str
  - result_id: str
  - result_type: "conversation" | "reflection" | "insight"
  - position: int
  - similarity_score: float
  - clicked: bool
  - dwell_time_ms: int
  - timestamp: datetime
  - session_id: str | None
```

**Usage Metrics**:
- Click-through rate
- Average dwell time
- Average position clicked
- Type preference (by content type)
- Success threshold (minimum similarity for useful results)

#### **Application Monitoring**
- **Location**: `/Users/les/Projects/session-buddy/session_buddy/app_monitor.py`
- **Purpose**: IDE activity tracking and browser documentation monitoring
- **Features**:
  - File system monitoring via watchdog
  - Application focus detection via psutil
  - Browser documentation site tracking
  - SQLite activity database (`~/.claude/data/activity.db`)

**Activity Events Tracked**:
```python
ActivityEvent:
  - timestamp: str
  - event_type: "file_change" | "app_focus" | "browser_nav"
  - application: str
  - details: dict[str, Any]
  - project_path: str | None
  - relevance_score: float
```

### 1.2 MCP Tools for Monitoring

Session-Buddy exposes monitoring via **MCP tools** (not OTel):

#### **Workflow Metrics Tools**
- **Location**: `/Users/les/Projects/session-buddy/session_buddy/mcp/tools/monitoring/workflow_metrics_tools.py`

**Available MCP Tools**:
```python
@mcp.tool()
async def get_workflow_metrics(
    project_path: str | None = None,
    days_back: int = 30
) -> dict[str, Any]:
    """Get comprehensive workflow metrics."""
    # Returns: total_sessions, avg_session_duration_minutes,
    #          avg_checkpoints_per_session, avg_commits_per_session,
    #          avg_quality_score, quality_trend, etc.

@mcp.tool()
async def get_session_analytics(
    limit: int = 20,
    sort_by: str = "duration"
) -> dict[str, Any]:
    """Get detailed session-level analytics."""
```

#### **Application Monitoring Tools**
- **Location**: `/Users/les/Projects/session-buddy/session_buddy/mcp/tools/monitoring/monitoring_tools.py`

**Available MCP Tools**:
```python
@mcp.tool()
async def start_app_monitoring(project_paths: list[str] | None = None) -> str:
    """Start monitoring IDE activity and browser documentation."""

@mcp.tool()
async def get_activity_summary(hours: int = 2) -> str:
    """Get activity summary for specified hours."""

@mcp.tool()
async def get_context_insights(hours: int = 1) -> str:
    """Get contextual insights from recent activity."""

@mcp.tool()
async def get_active_files(minutes: int = 60) -> str:
    """Get list of actively edited files."""
```

### 1.3 Dependencies Analysis

**Session-Buddy `pyproject.toml`** (lines 1-254):
```toml
dependencies = [
    "aiofiles>=25.1.0",
    "fastmcp>=2.14.4",
    "numpy>=2.4.1",
    "onnxruntime>=1.23.2",
    "oneiric>=0.3.12",
    "transformers>=4.57.6",
    "pydantic>=2.12.5",
    "duckdb>=1.4.3",           # Analytics database
    "tiktoken>=0.12.0",
    "aiohttp>=3.13.3",
    "rich>=14.2.0",
    "structlog>=25.5.0",       # Structured logging
    "typer>=0.21.1",
    "psutil>=7.2.1",           # System monitoring
    "crackerjack>=0.49.8",
]
```

**❌ NO OpenTelemetry dependencies detected**

### 1.4 Configuration Analysis

**Session-Buddy Configuration** (`settings/session-buddy.yaml`):
```yaml
# === Logging Settings ===
log_format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
enable_file_logging: true
log_file_path: "~/.claude/logs/session-buddy.log"
enable_performance_logging: false
log_slow_queries: true
slow_query_threshold: 1.0

# === Monitoring Settings ===
# NO OTEL/OTLP CONFIGURATION DETECTED
```

**Oneiric Integration** (from documentation):
- Session-Buddy uses Oneiric for configuration management
- Oneiric has `otlp` monitoring adapter available but **not configured in Session-Buddy**
- Reference: `/Users/les/Projects/session-buddy/docs/ONEIRIC_MCP_ANALYSIS.md` line 88

---

## 2. Mahavishnu OTel Infrastructure

### 2.1 OpenTelemetry Implementation

Mahavishnu has **complete OTel support** with OTLP export:

#### **Core Observability Module**
- **Location**: `/Users/les/Projects/mahavishnu/mahavishnu/core/observability.py`
- **Implementation**: Full OpenTelemetry SDK with OTLP exporters

**Key Components**:
```python
class ObservabilityManager:
    """Centralized observability manager for metrics, tracing, and logging."""

    def __init__(self, config: MahavishnuSettings):
        # OpenTelemetry imports with fallback
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
```

**Metrics Instruments Created**:
```python
self.workflow_counter = self.meter.create_counter(
    "mahavishnu.workflows.executed",
    description="Number of workflows executed"
)

self.repo_counter = self.meter.create_counter(
    "mahavishnu.repositories.processed",
    description="Number of repositories processed"
)

self.error_counter = self.meter.create_counter(
    "mahavishnu.errors.count",
    description="Number of errors occurred"
)

self.workflow_duration_histogram = self.meter.create_histogram(
    "mahavishnu.workflow.duration",
    description="Duration of workflow execution in seconds",
    unit="s"
)

self.repo_processing_duration_histogram = self.meter.create_histogram(
    "mahavishnu.repo.processing.duration",
    description="Duration of repository processing in seconds",
    unit="s"
)
```

**Tracing Capabilities**:
```python
def start_workflow_trace(self, workflow_id: str, adapter: str, task_type: str):
    """Start a trace for a workflow execution."""
    span_attributes = {
        "workflow.id": workflow_id,
        "workflow.adapter": adapter,
        "workflow.task_type": task_type,
        "workflow.start_time": datetime.now(tz=UTC).isoformat()
    }
    span = self.tracer.start_as_current_span(
        f"workflow.{workflow_id}",
        attributes=span_attributes
    )
    return span

def start_repo_trace(self, repo_path: str, workflow_id: str):
    """Start a trace for repository processing."""
    span_attributes = {"repo.path": repo_path, "workflow.id": workflow_id}
    span = self.tracer.start_as_current_span(
        f"repo.process.{repo_path.split('/')[-1]}",
        attributes=span_attributes
    )
    return span
```

### 2.2 Configuration

**Mahavishnu Configuration** (`mahavishnu/core/config.py`):
```python
class MahavishnuSettings(BaseSettings):
    # Observability configuration
    metrics_enabled: bool = Field(
        default=True,
        description="Enable OpenTelemetry metrics",
    )
    otlp_endpoint: str = Field(
        default="http://localhost:4317",
        description="OTLP endpoint for metrics/traces",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )
```

**Configuration Loading Order**:
1. Default values (in code)
2. `settings/mahavishnu.yaml` (committed)
3. `settings/local.yaml` (gitignored)
4. Environment variables: `MAHAVISHNU_{FIELD}`

### 2.3 OpenTelemetry Collector

**OTel Collector Configuration** (`config/otel-collector-config.yaml`):
```yaml
receivers:
  # OTLP receiver (gRPC) - for Mahavishnu application
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 80
    spike_limit_percentage: 25

exporters:
  # Export traces to Jaeger
  jaeger:
    endpoint: jaeger:14250
    tls:
      insecure: true

  # Export metrics to Prometheus
  prometheusremotewrite:
    endpoint: 'http://prometheus:9090/api/v1/write'

  # Export logs to Elasticsearch
  elasticsearch:
    endpoints:
      - http://elasticsearch:9200
    index: 'mahavishnu-logs'

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [jaeger, logging]

    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheusremotewrite, logging]

    logs:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [elasticsearch, logging]
```

**Docker Compose Integration** (`docker-compose.buildpacks.yml`):
```yaml
services:
  # OpenTelemetry Collector
  otel-collector:
    image: otel/opentelemetry-collector-contrib:latest
    command: --config=/etc/otel-collector-config.yaml
    volumes:
      - ./config/otel-collector-config.yaml:/etc/otel-collector-config.yaml
    ports:
      - "4317:4317"  # OTLP gRPC receiver
      - "4318:4318"  # OTLP HTTP receiver
      - "8888:8888"  # Prometheus exporter metrics
      - "13133:13133"  # health check

  # Jaeger for trace visualization
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"  # Jaeger UI
      - "14250:14250"  # OTLP receiver

  # Prometheus for metrics
  prometheus:
    image: prom/prometheus:latest
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
    volumes:
      - ./config/prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"  # Prometheus UI

  # Elasticsearch for logs
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.11.0
    environment:
      - discovery.type=single-node
      - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
    ports:
      - "9200:9200"
```

### 2.3 Dependencies

**Mahavishnu `pyproject.toml`**:
```toml
dependencies = [
    # ... other dependencies ...
    "opentelemetry-api>=1.38.0",
    "opentelemetry-sdk>=1.38.0",
    "opentelemetry-instrumentation>=0.59b0",
    "opentelemetry-exporter-otlp-proto-grpc>=1.38.0",
]
```

**✅ Full OpenTelemetry SDK present**

### 2.4 Session-Buddy Integration Points

Mahavishnu has Session-Buddy integration tools:

**Session-Buddy MCP Tools** (`mahavishnu/mcp/tools/session_buddy_tools.py`):
```python
@mcp.tool()
async def index_code_graph(project_path: str, include_docs: bool = True) -> dict[str, Any]:
    """Index codebase structure for better context in Session Buddy."""

@mcp.tool()
async def get_function_context(project_path: str, function_name: str) -> dict[str, Any]:
    """Get caller/callee context for a function for Session Buddy."""

@mcp.tool()
async def search_documentation(query: str) -> dict[str, Any]:
    """Search through indexed documentation in Session Buddy."""

@mcp.tool()
async def send_project_message(
    from_project: str,
    to_project: str,
    subject: str,
    message: str,
    priority: str = "NORMAL"
) -> dict[str, Any]:
    """Send message between projects for Session Buddy."""
```

**Pool Management with Session-Buddy**:
- **Location**: `mahavishnu/pools/session_buddy_pool.py`
- **Purpose**: Delegates worker management to Session-Buddy instances
- **Integration**: Session-Buddy manages exactly 3 workers per instance

---

## 3. Integration Options

### 3.1 Option A: OTLP Push from Session-Buddy (Recommended)

**Approach**: Add OpenTelemetry SDK to Session-Buddy and push metrics directly to Mahavishnu's OTel Collector.

**Architecture**:
```
Session-Buddy → OTLP Exporter → Otel Collector → Jaeger/Prometheus
                                              ↓
                                         Mahavishnu (consumer)
```

**Pros**:
- ✅ Real-time metrics streaming
- ✅ Native OTel support (standard protocol)
- ✅ No polling overhead
- ✅ Automatic trace correlation
- ✅ Unified observability stack

**Cons**:
- ⚠️ Requires OpenTelemetry dependencies in Session-Buddy
- ⚠️ Configuration changes required
- ⚠️ Network dependency on OTel Collector

**Implementation Effort**: **Medium** (2-3 days)

**Required Changes**:

1. **Add OpenTelemetry dependencies** to Session-Buddy `pyproject.toml`:
```toml
dependencies = [
    # ... existing ...
    "opentelemetry-api>=1.38.0",
    "opentelemetry-sdk>=1.38.0",
    "opentelemetry-instrumentation>=0.59b0",
    "opentelemetry-exporter-otlp-proto-grpc>=1.38.0",
]
```

2. **Create OTel module** in Session-Buddy:
```python
# session_buddy/observability/otel.py
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

def init_otel(otlp_endpoint: str = "http://localhost:4317"):
    """Initialize OpenTelemetry for Session-Buddy."""
    resource = Resource.create({
        "service.name": "session-buddy",
        "service.version": "0.13.0"
    })

    # Metrics
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=otlp_endpoint)
    )
    meter_provider = MeterProvider(metric_readers=[metric_reader], resource=resource)
    metrics.set_meter_provider(meter_provider)

    # Traces
    trace_provider = TracerProvider(resource=resource)
    processor = BatchSpanProcessor(
        OTLPSpanExporter(endpoint=otlp_endpoint)
    )
    trace_provider.add_span_processor(processor)
    trace.set_tracer_provider(trace_provider)

    return meter_provider, trace_provider
```

3. **Bridge existing metrics to OTel**:
```python
# session_buddy/observability/metrics_bridge.py
from opentelemetry import metrics

class WorkflowMetricsBridge:
    """Bridge workflow metrics to OpenTelemetry."""

    def __init__(self):
        meter = metrics.get_meter(__name__)

        # Create OTel instruments
        self.session_counter = meter.create_counter(
            "session_buddy.sessions.total",
            description="Total number of sessions"
        )
        self.session_duration = meter.create_histogram(
            "session_buddy.session.duration_seconds",
            description="Session duration in seconds",
            unit="s"
        )
        self.quality_score = meter.create_gauge(
            "session_buddy.session.quality_score",
            description="Current session quality score"
        )
        self.commit_counter = meter.create_counter(
            "session_buddy.session.commits",
            description="Number of git commits per session"
        )

    def record_session_metrics(self, session_metrics: SessionMetrics):
        """Record session metrics to OTel."""
        # Convert duration to seconds
        duration_seconds = session_metrics.duration_minutes * 60

        # Record metrics
        self.session_counter.add(1, {
            "project_path": session_metrics.project_path,
            "time_of_day": session_metrics.time_of_day
        })

        self.session_duration.record(duration_seconds, {
            "project_path": session_metrics.project_path
        })

        self.quality_score.record(session_metrics.avg_quality, {
            "session_id": session_metrics.session_id,
            "project_path": session_metrics.project_path
        })

        self.commit_counter.add(session_metrics.commit_count, {
            "session_id": session_metrics.session_id
        })
```

4. **Configuration** (`settings/session-buddy.yaml`):
```yaml
# === OpenTelemetry Settings ===
otel_enabled: true
otlp_endpoint: "http://localhost:4317"  # Mahavishnu's OTel Collector
otel_service_name: "session-buddy"
otel_metrics_export_interval: 60  # seconds
```

---

### 3.2 Option B: MCP Polling (Quick Start)

**Approach**: Mahavishnu polls Session-Buddy's MCP tools for metrics and converts to OTel format.

**Architecture**:
```
Mahavishnu → MCP Client → Session-Buddy MCP Server → Metrics
                                              ↓
                                         OTel conversion → OTel Collector
```

**Pros**:
- ✅ No changes to Session-Buddy required
- ✅ Uses existing MCP tools
- ✅ Faster to implement (1 day)

**Cons**:
- ⚠️ Polling overhead (network latency)
- ⚠️ Not real-time (polling interval)
- ⚠️ Tighter coupling (MCP dependency)
- ⚠️ Misses granular tracing data

**Implementation Effort**: **Low** (1 day)

**Implementation Example**:

```python
# mahavishnu/observability/session_buddy_metrics.py
from opentelemetry import metrics
import httpx

class SessionBuddyMetricsPoller:
    """Poll Session-Buddy MCP for metrics and publish to OTel."""

    def __init__(self, mcp_url: str = "http://localhost:8678/mcp"):
        self.mcp_url = mcp_url
        self.meter = metrics.get_meter(__name__)

        # Create OTel instruments
        self.workflow_counter = self.meter.create_counter(
            "mahavishnu.session_buddy.workflows.total"
        )

    async def poll_and_publish(self):
        """Poll Session-Buddy and publish metrics."""
        async with httpx.AsyncClient() as client:
            # Call Session-Buddy MCP tool
            response = await client.post(
                f"{self.mcp_url}/tools/call",
                json={
                    "name": "get_workflow_metrics",
                    "arguments": {"days_back": 7}
                }
            )

            metrics_data = response.json()

            # Convert to OTel metrics
            self.workflow_counter.add(
                metrics_data["total_sessions"],
                {
                    "source": "session_buddy",
                    "period_days": 7
                }
            )
```

---

### 3.3 Option C: Database Polling (Bridge Pattern)

**Approach**: Mahavishnu reads Session-Buddy's DuckDB database directly and converts to OTel format.

**Architecture**:
```
Mahavishnu → DuckDB Reader → Session-Buddy DuckDB → Metrics
                                              ↓
                                         OTel conversion → OTel Collector
```

**Pros**:
- ✅ No Session-Buddy code changes
- ✅ Direct database access (no network latency)
- ✅ Historical data access

**Cons**:
- ⚠️ Tightly coupled to database schema
- ⚠️ Requires file system access
- ⚠️ Schema changes break integration
- ⚠️ No real-time data

**Implementation Effort**: **Low-Medium** (1-2 days)

**Implementation Example**:

```python
# mahavishnu/observability/session_buddy_db_reader.py
import duckdb
from opentelemetry import metrics

class SessionBuddyDBReader:
    """Read Session-Buddy DuckDB and publish to OTel."""

    def __init__(self, db_path: str = "~/.claude/data/workflow_metrics.db"):
        self.db_path = db_path
        self.meter = metrics.get_meter(__name__)

        # Create OTel instruments
        self.session_duration = self.meter.create_histogram(
            "mahavishnu.session_buddy.session_duration_hours"
        )

    def read_and_publish(self):
        """Read from DuckDB and publish metrics."""
        conn = duckdb.connect(self.db_path)

        # Query session metrics
        result = conn.execute("""
            SELECT
                project_path,
                AVG(duration_minutes) / 60 as avg_duration_hours,
                COUNT(*) as session_count
            FROM session_metrics
            WHERE started_at >= NOW() - INTERVAL '7 days'
            GROUP BY project_path
        """).fetchall()

        for row in result:
            project_path, avg_duration, count = row

            # Publish to OTel
            for _ in range(count):
                self.session_duration.record(
                    avg_duration,
                    {"project_path": project_path, "source": "session_buddy_db"}
                )
```

---

### 3.4 Option D: Hybrid Approach (Recommended Production)

**Approach**: Combine Option A (OTLP push) for critical metrics + Option B (MCP polling) for supplemental data.

**Architecture**:
```
┌─────────────────────────────────────────────────────────┐
│                    Session-Buddy                        │
│  ┌──────────────┐         ┌────────────────────────┐  │
│  │ Core Metrics │─OTLP───→│ Otel Collector          │  │
│  │ (Real-time)  │         │  (Mahavishnu managed)   │  │
│  └──────────────┘         └────────────────────────┘  │
│  ┌──────────────┐                                    │
│  │ Analytics    │─MCP Poll──→ Mahavishnu (supplemental)
│  │ (Historical) │                                    │
│  └──────────────┘                                    │
└─────────────────────────────────────────────────────────┘
```

**Pros**:
- ✅ Best of both worlds (real-time + historical)
- ✅ Resilient (fallback to polling if OTLP fails)
- ✅ Comprehensive observability

**Cons**:
- ⚠️ Higher implementation effort
- ⚠️ Two integration paths to maintain

**Implementation Effort**: **Medium** (3-4 days)

---

## 4. Configuration Requirements

### 4.1 Session-Buddy Configuration Changes

**Add to `settings/session-buddy.yaml`**:
```yaml
# === OpenTelemetry Integration ===
otel_enabled: true
otlp_endpoint: "http://localhost:4317"  # Mahavishnu OTel Collector
otel_service_name: "session-buddy"
otel_service_version: "0.13.0"
otel_metrics_enabled: true
otel_traces_enabled: true
otel_logs_enabled: false  # Optional: Structlog can bridge logs
otel_export_interval_seconds: 60
otel_batch_size: 512

# OTel Resource Attributes
otel_resource_attributes:
  deployment.environment: "${ENV:production}"
  service.namespace: "mcp"
  service.instance.id: "${HOSTNAME}"

# Metrics to Export
otel_metrics_whitelist:
  - "session_buddy.session.*"
  - "session_buddy.workflow.*"
  - "session_buddy.memory.*"
  - "session_buddy.cache.*"

# Traces Sampling
otel_trace_sampler: "parentbased_trace_id_ratio"  # or "always_on", "always_off"
otel_trace_sampler_ratio: 0.1  # 10% sampling for production
```

### 4.2 Mahavishnu Configuration Changes

**Add to `settings/mahavishnu.yaml`**:
```yaml
# === Session-Buddy Integration ===
session_buddy:
  # OTLP Collector (already configured)
  otlp_collector_enabled: true
  otlp_endpoint: "http://localhost:4317"

  # MCP Polling (fallback/supplemental)
  mcp_polling_enabled: true
  mcp_polling_interval_seconds: 300  # 5 minutes
  session_buddy_mcp_url: "http://localhost:8678/mcp"

  # Database Polling (optional)
  db_polling_enabled: false  # Requires filesystem access
  session_buddy_db_path: "~/.claude/data/workflow_metrics.db"
  db_polling_interval_seconds: 600  # 10 minutes

  # Metrics Mapping
  metrics_prefix: "mahavishnu.session_buddy"
  import_quality_metrics: true
  import_workflow_metrics: true
  import_activity_metrics: true
```

### 4.3 OpenTelemetry Collector Configuration

**Update `config/otel-collector-config.yaml`** (add Session-Buddy receiver):
```yaml
receivers:
  # Existing Mahavishnu OTLP receiver
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

  # Session-Buddy dedicated receiver (optional - can use same)
  session_buddy_otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4319  # Separate port for SB

processors:
  batch:

  # Add Session-Buddy specific attributes
  session_buddy_attrs:
    actions:
      - key: service.namespace
        value: session_buddy
        action: insert

exporters:
  # Existing exporters work for Session-Buddy too
  jaeger:
    endpoint: jaeger:14250
    tls:
      insecure: true

  prometheusremotewrite:
    endpoint: 'http://prometheus:9090/api/v1/write'

service:
  pipelines:
    # Mahavishnu traces
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [jaeger]

    # Session-Buddy traces (separate pipeline)
    traces/session_buddy:
      receivers: [session_buddy_otlp]
      processors: [batch, session_buddy_attrs]
      exporters: [jaeger]

    # Unified metrics pipeline
    metrics:
      receivers: [otlp, session_buddy_otlp]
      processors: [batch]
      exporters: [prometheusremotewrite]
```

### 4.4 Environment Variables

**Session-Buddy**:
```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
export OTEL_SERVICE_NAME="session-buddy"
export OTEL_RESOURCE_ATTRIBUTES="deployment.environment=development"
```

**Mahavishnu**:
```bash
export MAHAVISHNU_OTLP_ENDPOINT="http://localhost:4317"
export MAHAVISHNU_METRICS_ENABLED="true"
export MAHAVISHNU_SESSION_BUDDY_MCP_URL="http://localhost:8678/mcp"
```

---

## 5. Recommendations

### 5.1 Recommended Integration Strategy

**Phase 1: Quick Win (Week 1)**
- ✅ Implement **Option B (MCP Polling)** for immediate visibility
- ✅ Add Session-Buddy metrics to Mahavishnu dashboards
- ✅ Validate data flow and quality

**Phase 2: Production Integration (Week 2-3)**
- ✅ Implement **Option A (OTLP Push)** for real-time metrics
- ✅ Add OpenTelemetry dependencies to Session-Buddy
- ✅ Deploy OTLP instrumentation in Session-Buddy core modules
- ✅ Configure sampling and resource attributes

**Phase 3: Optimization (Week 4)**
- ✅ Implement **Hybrid Approach (Option D)** for resilience
- ✅ Add correlation IDs for distributed tracing
- ✅ Optimize metrics cardinality
- ✅ Create unified dashboards (Jaeger + Grafana)

### 5.2 Priority Metrics to Export

**Session Metrics (High Priority)**:
```yaml
session_buddy.session.duration_seconds:
  type: histogram
  description: Session duration
  unit: s
  labels: [project_path, time_of_day, primary_language]

session_buddy.session.quality_score:
  type: gauge
  description: Current quality score
  labels: [session_id, project_path]

session_buddy.session.commits_total:
  type: counter
  description: Total commits per session
  labels: [project_path]

session_buddy.session.checkpoints_total:
  type: counter
  description: Total checkpoints per session
  labels: [project_path]
```

**Workflow Metrics (High Priority)**:
```yaml
session_buddy.workflow.velocity_commits_per_hour:
  type: gauge
  description: Development velocity
  unit: commits/hour
  labels: [project_path]

session_buddy.workflow.quality_trend:
  type: gauge
  description: Quality trend direction
  labels: [project_path, trend]  # trend: improving|stable|declining
```

**Memory/Cache Metrics (Medium Priority)**:
```yaml
session_buddy.memory.usage_bytes:
  type: gauge
  description: Memory usage
  unit: By
  labels: [component]

session_buddy.cache.hit_rate:
  type: gauge
  description: Cache hit rate
  unit: %
  labels: [cache_type]  # embedding, query, etc.
```

**Activity Metrics (Low Priority)**:
```yaml
session_buddy.activity.files_modified_total:
  type: counter
  description: Total files modified
  labels: [project_path, file_extension]

session_buddy.activity.context_switches_total:
  type: counter
  description: Application context switches
  labels: [from_app, to_app]
```

### 5.3 Distributed Tracing Strategy

**Trace Context Propagation**:
```python
# Session-Buddy should inject trace context
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

def start_session_trace(session_id: str, project_path: str):
    """Start a distributed trace for session."""
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span(
        "session_buddy.session",
        attributes={
            "session.id": session_id,
            "session.project_path": project_path,
            "session.start_time": datetime.now().isoformat()
        }
    ) as span:
        # This span will be parent for all operations
        return span

# Mahavishnu can continue the trace
def continue_session_trace(session_id: str, operation: str):
    """Continue Session-Buddy trace in Mahavishnu."""
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span(
        f"mahavishnu.{operation}",
        attributes={
            "linked.session_id": session_id,
            "mahavishnu.operation": operation
        }
    ) as span:
        # Add link to Session-Buddy span
        span.add_link(
            context=TraceContext(
                trace_id=extract_trace_id(session_id),
                span_id=extract_span_id(session_id)
            )
        )
        return span
```

### 5.4 Dashboard Recommendations

**Grafana Dashboard Panels**:

1. **Session Overview**:
   - Total sessions (grouped by project)
   - Average session duration (heatmap by time of day)
   - Quality score trend (time series)
   - Top projects by activity

2. **Workflow Velocity**:
   - Commits per hour (gauge)
   - Checkpoints per session (histogram)
   - Files modified rate (counter)
   - Language distribution (pie chart)

3. **Quality Metrics**:
   - Quality score distribution (histogram)
   - Quality trend direction (stat panel)
   - Most productive time of day (heatmap)
   - Tool usage frequency (bar chart)

4. **Distributed Traces** (Jaeger):
   - Session lifecycle traces
   - Mahavishnu workflow traces
   - Cross-service trace correlation
   - Error/failure traces

---

## 6. Implementation Roadmap

### 6.1 Week 1: Foundation

**Day 1-2: MCP Polling Integration**
- [ ] Create `mahavishnu/observability/session_buddy_poller.py`
- [ ] Implement `get_workflow_metrics` polling
- [ ] Create OTel metric instruments
- [ ] Add Mahavishnu configuration
- [ ] Test polling end-to-end

**Day 3: Dashboard Setup**
- [ ] Create Grafana dashboard
- [ ] Add Session-Buddy panels
- [ ] Import sample metrics
- [ ] Validate data visualization

**Day 4-5: Documentation & Testing**
- [ ] Write integration documentation
- [ ] Create integration tests
- [ ] Performance testing (polling overhead)
- [ ] Error handling validation

**Deliverable**: Working MCP polling with dashboard

---

### 6.2 Week 2-3: OTLP Implementation

**Day 6-8: Session-Buddy OTel Setup**
- [ ] Add OpenTelemetry dependencies to Session-Buddy
- [ ] Create `session_buddy/observability/` module
- [ ] Implement `init_otel()` function
- [ ] Add OTLP configuration
- [ ] Test OTLP connection to Mahavishnu collector

**Day 9-11: Metrics Instrumentation**
- [ ] Instrument `WorkflowMetricsEngine` with OTel
- [ ] Instrument `UsageTracker` with OTel
- [ ] Instrument `ApplicationMonitor` with OTel
- [ ] Add custom metrics converters
- [ ] Validate metric export

**Day 12-15: Tracing Instrumentation**
- [ ] Add tracing to session lifecycle
- [ ] Add tracing to workflow operations
- [ ] Implement trace context propagation
- [ ] Configure sampling strategy
- [ ] Test distributed traces in Jaeger

**Deliverable**: Full OTLP instrumentation in Session-Buddy

---

### 6.3 Week 3-4: Production Readiness

**Day 16-18: Hybrid Integration**
- [ ] Implement fallback to MCP polling
- [ ] Add health checks for OTLP exporter
- [ ] Create unified metrics aggregator
- [ ] Test failover scenarios

**Day 19-21: Optimization**
- [ ] Analyze metrics cardinality
- [ ] Implement metrics whitelisting
- [ ] Optimize batch sizes
- [ ] Tune sampling rates
- [ ] Performance benchmarking

**Day 22-25: Documentation & Deployment**
- [ ] Write deployment guide
- [ ] Create runbooks for common issues
- [ ] Document metric semantics
- [ ] Deploy to production (staged rollout)
- [ ] Monitor and validate

**Deliverable**: Production-ready OTel integration

---

## 7. Risk Assessment

### 7.1 Technical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **OTLP Collector downtime** | High (metrics loss) | Medium | Implement MCP polling fallback |
| **High metrics cardinality** | High (performance degradation) | Medium | Implement metrics whitelisting |
| **Network latency** | Medium (delayed metrics) | Low | Batch metrics, use async export |
| **Schema changes** | Medium (integration breaks) | Low | Version database schema, adapter pattern |
| **OpenTelemetry dependency conflicts** | Medium | Low | Use compatible versions, test thoroughly |

### 7.2 Operational Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| **Configuration drift** | Medium | Medium | Centralized config management |
| **Dashboard overload** | Low | Medium | Careful panel design, aggregation |
| **Retention costs** | Medium | Low | Implement data retention policies |
| **Monitoring blindness** | High | Low | Alert on export failures, health checks |

---

## 8. Success Criteria

### 8.1 Technical Metrics

- ✅ **99.9%** OTLP export success rate
- ✅ **<500ms** metric export latency (p95)
- ✅ **<100ms** tracing overhead per span
- ✅ **<10%** CPU overhead from OTel instrumentation
- ✅ **<50MB** additional memory footprint

### 8.2 Functional Requirements

- ✅ All Session-Buddy metrics exported to OTLP
- ✅ Distributed traces span Session-Buddy → Mahavishnu
- ✅ Real-time metrics visible in Grafana < 1s after collection
- ✅ Fallback to MCP polling if OTLP fails
- ✅ No breaking changes to existing Session-Buddy APIs

### 8.3 Observability Outcomes

- ✅ Unified dashboard for Mahavishnu + Session-Buddy metrics
- ✅ Correlated traces across both services
- ✅ Alert on quality score degradation
- ✅ Alert on workflow velocity drop
- ✅ Historical trend analysis (30+ days)

---

## 9. Code Examples

### 9.1 Session-Buddy OTel Initialization

```python
# session_buddy/__init__.py
from .observability.otel import init_otel

def initialize_session_buddy():
    """Initialize Session-Buddy with OpenTelemetry."""
    from session_buddy.settings import get_settings

    settings = get_settings()

    # Initialize OTel if enabled
    if settings.otel_enabled:
        init_otel(
            otlp_endpoint=settings.otlp_endpoint,
            service_name=settings.otel_service_name,
            metrics_enabled=settings.otel_metrics_enabled,
            traces_enabled=settings.otel_traces_enabled
        )

    # ... rest of initialization
```

### 9.2 Workflow Metrics to OTel

```python
# session_buddy/observability/metrics_bridge.py
from opentelemetry import metrics
from .workflow_metrics import SessionMetrics

class WorkflowMetricsBridge:
    """Bridge workflow metrics to OpenTelemetry."""

    def __init__(self):
        self.meter = metrics.get_meter(__name__)

        # Create instruments
        self.session_counter = self.meter.create_counter(
            "session_buddy.sessions.total",
            description="Total number of sessions"
        )

        self.session_duration = self.meter.create_histogram(
            "session_buddy.session.duration_seconds",
            unit="s",
            description="Session duration in seconds"
        )

        self.quality_gauge = self.meter.create_gauge(
            "session_buddy.session.quality_score",
            description="Session quality score (0-100)"
        )

        self.commit_counter = self.meter.create_counter(
            "session_buddy.session.commits",
            description="Number of git commits per session"
        )

    def record_session(self, session: SessionMetrics):
        """Record session metrics to OTel."""
        attributes = {
            "session.id": session.session_id,
            "session.project_path": session.project_path,
            "session.time_of_day": session.time_of_day,
            "session.primary_language": session.primary_language or "unknown"
        }

        # Count session
        self.session_counter.add(1, attributes)

        # Record duration (convert to seconds)
        duration_seconds = session.duration_minutes * 60 if session.duration_minutes else 0
        self.session_duration.record(duration_seconds, attributes)

        # Record quality
        self.quality_gauge.record(session.avg_quality, attributes)

        # Count commits
        self.commit_counter.add(session.commit_count, attributes)
```

### 9.3 Mahavishnu Metrics Poller

```python
# mahavishnu/observability/session_buddy_poller.py
import asyncio
import httpx
from opentelemetry import metrics

class SessionBuddyMetricsPoller:
    """Poll Session-Buddy MCP for metrics."""

    def __init__(self, mcp_url: str, interval: int = 300):
        self.mcp_url = mcp_url
        self.interval = interval
        self.meter = metrics.get_meter(__name__)

        # Create OTel instruments
        self.sb_session_counter = self.meter.create_counter(
            "mahavishnu.session_buddy.sessions.total",
            description="Sessions from Session-Buddy"
        )

    async def start(self):
        """Start polling loop."""
        while True:
            try:
                await self._poll_and_publish()
            except Exception as e:
                print(f"Polling error: {e}")

            await asyncio.sleep(self.interval)

    async def _poll_and_publish(self):
        """Poll Session-Buddy and publish metrics."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.mcp_url}/tools/call",
                json={
                    "name": "get_workflow_metrics",
                    "arguments": {"days_back": 1}
                },
                timeout=10.0
            )

            data = response.json()

            if data.get("success"):
                self.sb_session_counter.add(
                    data["total_sessions"],
                    {"source": "mcp_poll"}
                )
```

---

## 10. References

### 10.1 File References

**Session-Buddy Files**:
- `/Users/les/Projects/session-buddy/session_buddy/core/workflow_metrics.py` - Workflow metrics engine
- `/Users/les/Projects/session-buddy/session_buddy/analytics/usage_tracker.py` - Usage analytics
- `/Users/les/Projects/session-buddy/session_buddy/app_monitor.py` - Application monitoring
- `/Users/les/Projects/session-buddy/session_buddy/mcp/tools/monitoring/workflow_metrics_tools.py` - MCP tools
- `/Users/les/Projects/session-buddy/session_buddy/mcp/tools/monitoring/monitoring_tools.py` - Monitoring MCP tools
- `/Users/les/Projects/session-buddy/settings/session-buddy.yaml` - Configuration
- `/Users/les/Projects/session-buddy/pyproject.toml` - Dependencies

**Mahavishnu Files**:
- `/Users/les/Projects/mahavishnu/mahavishnu/core/observability.py` - OTel implementation
- `/Users/les/Projects/mahavishnu/mahavishnu/core/config.py` - Configuration
- `/Users/les/Projects/mahavishnu/config/otel-collector-config.yaml` - OTel Collector config
- `/Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/session_buddy_tools.py` - SB integration tools
- `/Users/les/Projects/mahavishnu/pyproject.toml` - Dependencies

### 10.2 Documentation References

- [OpenTelemetry Python Documentation](https://opentelemetry.io/docs/instrumentation/python/)
- [OTLP Specification](https://opentelemetry.io/docs/reference/specification/protocol/otlp/)
- [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)
- [Session-Buddy Architecture](/Users/les/Projects/session-buddy/docs/developer/ARCHITECTURE.md)
- [Mahavishnu Architecture](/Users/les/Projects/mahavishnu/ARCHITECTURE.md)

### 10.3 Standards and Protocols

- **OpenTelemetry Protocol (OTLP)**: v1.2.0
- **OpenTelemetry Semantic Conventions**: v1.23.0
- **Prometheus Remote Write Protocol**: v2.1.0
- **Model Context Protocol (MCP)**: FastMCP v2.14.4

---

## 11. Conclusion

Session-Buddy has **no native OpenTelemetry support** but provides comprehensive monitoring through custom implementations. Mahavishnu has **full OTel support** with OTLP exporters configured. Integration requires bridging Session-Buddy's DuckDB-based analytics to Mahavishnu's OTel infrastructure.

**Recommended Approach**: Hybrid implementation combining OTLP push (for real-time metrics) and MCP polling (for resilience and historical data).

**Key Benefits**:
- ✅ Unified observability stack
- ✅ Distributed tracing across services
- ✅ Real-time metrics in dashboards
- ✅ Historical trend analysis
- ✅ Production-ready monitoring

**Implementation Timeline**: 3-4 weeks for full production deployment

---

**Report Status**: ✅ Complete
**Next Steps**: Review with stakeholders, approve Phase 1 (MCP polling), begin implementation
