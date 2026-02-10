# OTLP Architecture Diagrams

Visual representations of the Mahavishnu OTLP ingestion architecture.

## Overview Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EXTERNAL SOURCES                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                 │
│  │   Claude     │    │    Qwen      │    │  Custom App  │                 │
│  │  (AI Assist) │    │  (AI Assist) │    │   (Python)   │                 │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘                 │
│         │                   │                   │                          │
│         │ OTLP              │ OTLP              │ OTLP                     │
│         │                   │                   │                          │
└─────────┼───────────────────┼───────────────────┼──────────────────────────┘
          │                   │                   │
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────┴───────────────────┴───────────────────┴───────────────────────────┐
│                         OTLP ENDPOINTS                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐            │
│  │  Primary OTLP   │  │  Claude OTLP    │  │   Qwen OTLP     │            │
│  │  :4317 (gRPC)   │  │  :4319 (gRPC)   │  │  :4321 (gRPC)   │            │
│  │  :4318 (HTTP)   │  │  :4320 (HTTP)   │  │  :4322 (HTTP)   │            │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘            │
│           │                     │                     │                     │
│           │                     │                     │                     │
└───────────┼─────────────────────┼─────────────────────┼────────────────────┘
            │                     │                     │
            │                     │                     │
            ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      OPENTELEMETRY COLLECTOR                                │
│                    (otel-collector:4317-4322)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        RECEIVERS                                    │   │
│  │  • otlp (primary)       • otlp/claude        • otlp/qwen           │   │
│  │  • filelog/claude       • filelog/qwen       • filelog/general     │   │
│  │  • prometheus           • hostmetrics                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                   │                                         │
│                                   ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        PROCESSORS                                   │   │
│  │  • batch                   • memory_limiter   • resource            │   │
│  │  • attributes/claude       • attributes/qwen                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                   │                                         │
│                                   ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        PIPELINES                                    │   │
│  │  Traces:     otlp → batch → jaeger                                  │   │
│  │  Traces/C:   otlp/claude → batch → jaeger                           │   │
│  │  Traces/Q:   otlp/qwen → batch → jaeger                             │   │
│  │  Metrics:    otlp → batch → prometheus                              │   │
│  │  Metrics/C:  otlp/claude → batch → prometheus                       │   │
│  │  Metrics/Q:  otlp/qwen → batch → prometheus                         │   │
│  │  Logs:       otlp + filelog → batch → elasticsearch                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
            │                     │                     │
            │                     │                     │
            ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          BACKEND STORAGE                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌───────────────┐    ┌──────────────────┐            │
│  │    Jaeger    │    │  Prometheus   │    │  Elasticsearch    │            │
│  │  (Traces)    │    │  (Metrics)    │    │     (Logs)        │            │
│  │   :14250     │    │   :9090       │    │     :9200         │            │
│  └──────┬───────┘    └───────┬───────┘    └────────┬─────────┘            │
│         │                    │                     │                       │
│         ▼                    ▼                     ▼                       │
│  ┌──────────────┐    ┌───────────────┐    ┌──────────────────┐            │
│  │ Jaeger UI    │    │   Grafana     │    │     Kibana       │            │
│  │   :16686     │    │    :3000      │    │     :5601        │            │
│  └──────────────┘    └───────────────┘    └──────────────────┘            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Telemetry Flow: Traces

```
┌─────────────┐                                                     ┌──────────────┐
│   Claude    │                                                     │   Jaeger     │
│   Client    │                                                     │     UI       │
└──────┬──────┘                                                     └──────▲───────┘
       │                                                                   │
       │ 1. Create Span                                                    │
       │    with tracer.start_as_current_span("operation")                 │
       │                                                                   │
       ▼                                                                   │
┌──────────────────────────────────────────────────────────────────────────┐
│                    OpenTelemetry Python SDK                              │
│                                                                          │
│  resource = Resource.create({                                            │
│      "service.name": "claude-integration",                               │
│      "telemetry.source": "claude",                                       │
│  })                                                                      │
│                                                                          │
│  span.set_attribute("ai.prompt.length", 150)                             │
│  span.set_attribute("ai.model", "claude-sonnet-4")                       │
└──────────────────────────────────────────────────────────────────────────┘
       │
       │ 2. Export via OTLP
       │    BatchSpanProcessor → OTLPSpanExporter
       │
       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                    OTLP Endpoint (:4319)                                 │
│                    Claude-specific receiver                              │
└──────────────────────────────────────────────────────────────────────────┘
       │
       │ 3. Process
       │
       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                    Collector Pipeline: traces/claude                     │
│                                                                          │
│  Receiver: otlp/claude                                                   │
│  Processors: memory_limiter → batch → resource → attributes/claude       │
│  Exporters: jaeger + logging                                             │
└──────────────────────────────────────────────────────────────────────────┘
       │
       │ 4. Export
       │    gRPC to jaeger:14250
       │
       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     Jaeger Collector (:14250)                            │
└──────────────────────────────────────────────────────────────────────────┘
       │
       │ 5. Store
       │
       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     Jaeger Storage                                       │
└──────────────────────────────────────────────────────────────────────────┘
       │
       │ 6. Query
       │
       └───────────────────────────────────────────────────────────────┘
```

## Telemetry Flow: File Log Ingestion

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           APPLICATION                                      │
│                                                                             │
│  logger = logging.getLogger("claude")                                      │
│  log_entry = {                                                              │
│      "timestamp": "2025-01-31T12:00:00Z",                                  │
│      "session_id": "session-123",                                          │
│      "source": "claude",                                                   │
│      "level": "info",                                                      │
│      "message": "Processing request"                                       │
│  }                                                                          │
│                                                                             │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                             │ 1. Write to file
                             │    JSON log format
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       FILE SYSTEM                                          │
│                                                                             │
│  /var/log/mahavishnu/sessions/claude/session-123.log                       │
│                                                                             │
│  {"timestamp": "...", "source": "claude", "message": "..."}                 │
│  {"timestamp": "...", "source": "claude", "message": "..."}                 │
│  {"timestamp": "...", "source": "claude", "message": "..."}                 │
│                                                                             │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                             │ 2. Poll and read
                             │    filelog/claude receiver
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    COLLECTOR FILELOG RECEIVER                              │
│                                                                             │
│  filelog/claude:                                                           │
│    include: /var/log/mahavishnu/sessions/claude/*.log                      │
│    operators:                                                              │
│      - json_parser                                                         │
│      - move session_id → resource.session_id                               │
│      - move source → resource.source                                       │
│                                                                             │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                             │ 3. Parse and transform
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    COLLECTOR LOGS/CLAUDE PIPELINE                          │
│                                                                             │
│  Receiver: filelog/claude                                                   │
│  Processors: memory_limiter → batch → resource → attributes/claude         │
│  Exporters: elasticsearch + logging                                        │
│                                                                             │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                             │ 4. Export
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       ELASTICSEARCH (:9200)                                │
│                                                                             │
│  Index: mahavishnu-logs-*                                                  │
│  Document: {                                                               │
│    "resource.session_id": "session-123",                                   │
│    "resource.source": "claude",                                            │
│    "body": "Processing request"                                            │
│  }                                                                          │
│                                                                             │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                             │ 5. Query
                             └─────────────────────────────────────────────────┐
                                                                             │
┌─────────────────────────────────────────────────────────────────────────────┤
│                           KIBANA (:5601)                                   │
│                                                                             │
│  Discover → Index: mahavishnu-logs*                                        │
│  Filter: resource.source: "claude"                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Source Identification Strategy

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         RESOURCE ATTRIBUTES                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Primary (Mahavishnu):                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  service.name: "mahavishnu"                                         │  │
│  │  telemetry.source: (not set)                                        │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Claude Integration:                                                       │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  service.name: "claude-integration"                                 │  │
│  │  telemetry.source: "claude"                                          │  │
│  │  telemetry.source.type: "ai_assistant"                               │  │
│  │  ai.model: "claude-sonnet-4"                                         │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Qwen Integration:                                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  service.name: "qwen-integration"                                   │  │
│  │  telemetry.source: "qwen"                                            │  │
│  │  telemetry.source.type: "ai_assistant"                               │  │
│  │  ai.model: "qwen-max"                                                │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                              │
                              │ Used for filtering
                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BACKEND QUERIES                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Jaeger:                                                                    │
│    • Filter by service name                                                │
│    • Filter by tags: telemetry.source=claude                               │
│                                                                             │
│  Prometheus:                                                                │
│    operations_total{telemetry_source="claude"}                              │
│    ai_tokens_total{telemetry_source="qwen"}                                 │
│                                                                             │
│  Elasticsearch:                                                             │
│    resource.source: "claude"                                               │
│    resource.telemetry.source.type: "ai_assistant"                          │
│                                                                             │
│  Grafana:                                                                   │
│    • Variables: $telemetry_source (all, claude, qwen)                      │
│    • Panel filters: telemetry_source="$telemetry_source"                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Pipeline Processing Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TRACE PIPELINE FLOW                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. RECEIVER (otlp/claude)                                                 │
│     ┌───────────────────────────────────────────────────────────────────┐  │
│     │  Incoming Span:                                                   │  │
│     │    trace_id: 0x123...                                             │  │
│     │    span_id: 0x456...                                              │  │
│     │    parent_span_id: 0x789...                                        │  │
│     │    name: "claude.api.call"                                        │  │
│     │    attributes: {                                                   │  │
│     │      "ai.prompt": "..."                                            │  │
│     │      "ai.model": "claude-sonnet-4"                                 │  │
│     │    }                                                                │  │
│     └───────────────────────────────────────────────────────────────────┘  │
│                              │                                             │
│                              ▼                                             │
│  2. MEMORY LIMITER                                                           │
│     ┌───────────────────────────────────────────────────────────────────┐  │
│     │  Check memory usage                                               │  │
│     │  If > 80%: Spike limit check                                     │  │
│     │  If > 105%: Drop data                                            │  │
│     │  Otherwise: Pass through                                         │  │
│     └───────────────────────────────────────────────────────────────────┘  │
│                              │                                             │
│                              ▼                                             │
│  3. BATCH                                                                     │
│     ┌───────────────────────────────────────────────────────────────────┐  │
│     │  Collect spans into batches                                       │  │
│     │  Timeout: 5s                                                     │  │
│     │  Batch size: 10,000                                              │  │
│     │  Send when timeout or full                                       │  │
│     └───────────────────────────────────────────────────────────────────┘  │
│                              │                                             │
│                              ▼                                             │
│  4. RESOURCE                                                                  │
│     ┌───────────────────────────────────────────────────────────────────┐  │
│     │  Add/Update resource attributes:                                  │  │
│     │    deployment.environment: "production"                           │  │
│     │    deployment.platform: "docker-compose"                          │  │
│     │    service.namespace: "mahavishnu"                                │  │
│     └───────────────────────────────────────────────────────────────────┘  │
│                              │                                             │
│                              ▼                                             │
│  5. ATTRIBUTES/CLAUDE                                                         │
│     ┌───────────────────────────────────────────────────────────────────┐  │
│     │  Add source identification:                                       │  │
│     │    telemetry.source: "claude"                                     │  │
│     │    telemetry.source.type: "ai_assistant"                          │  │
│     └───────────────────────────────────────────────────────────────────┘  │
│                              │                                             │
│                              ▼                                             │
│  6. EXPORTERS                                                                 │
│     ┌───────────────────────────────────────────────────────────────────┐  │
│     │  jaeger: Send to jaeger:14250 via gRPC                            │  │
│     │  logging: Write to stdout (debug)                                 │  │
│     └───────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Network Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          HOST NETWORK                                      │
│                                                                             │
│  localhost:4317 ────┐                                                       │
│  localhost:4318 ────┤                                                       │
│  localhost:4319 ────┤                                                       │
│  localhost:4320 ────┼───► Docker Bridge (172.28.0.0/16)                      │
│  localhost:4321 ────┤         │                                             │
│  localhost:4322 ────┘         │                                             │
│                              ▼                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         Docker Network                              │   │
│  │                      (mahavishnu-network)                            │   │
│  │                                                                       │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │   │
│  │  │   Client     │  │   Collector  │  │   Jaeger     │               │   │
│  │  │  Container   │  │   Container  │  │   Container  │               │   │
│  │  │              │  │              │  │              │               │   │
│  │  │ 172.28.0.x   │  │ 172.28.0.y   │  │ 172.28.0.z   │               │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘               │   │
│  │                                                                       │   │
│  │  • Internal communication uses service names                          │   │
│  │  • External communication uses port mappings                          │   │
│  │                                                                       │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Production High Availability Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      LOAD BALANCER (HAProxy/Nginx)                         │
│                  otlp.mahavishnu.example.com:4317                          │
└──────────────────────────────┬─────────────────────────────────────────────┘
                               │
                ┌──────────────┼──────────────┐
                │              │              │
                ▼              ▼              ▼
┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐
│ Collector Node 1  │ │ Collector Node 2  │ │ Collector Node 3  │
│                   │ │                   │ │                   │
│ • Receiver        │ │ • Receiver        │ │ • Receiver        │
│ • Batch           │ │ • Batch           │ │ • Batch           │
│ • Memory Limiter  │ │ • Memory Limiter  │ │ • Memory Limiter  │
│ • Exporter Queue  │ │ • Exporter Queue  │ │ • Exporter Queue  │
└─────────┬─────────┘ └─────────┬─────────┘ └─────────┬─────────┘
          │                     │                     │
          └─────────────────────┼─────────────────────┘
                                │
                ┌───────────────┼───────────────┐
                │               │               │
                ▼               ▼               ▼
┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐
│   Jaeger Cluster  │ │ Prometheus Cluster │ │  Elasticsearch    │
│                   │ │                   │ │      Cluster      │
│ • Collector 1     │ │ • Server 1        │ │ • Node 1          │
│ • Collector 2     │ │ • Server 2        │ │ • Node 2          │
│ • Storage         │ │ • Thanos Sidecar  │ │ • Kibana          │
└───────────────────┘ └───────────────────┘ └───────────────────┘
```

______________________________________________________________________

**Diagrams created:** 2025-01-31
**Architecture version:** 1.0.0
**For questions or updates, see OTLP_SETUP_GUIDE.md**
