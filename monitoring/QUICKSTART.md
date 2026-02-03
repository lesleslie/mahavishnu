# Monitoring & Observability Stack - Quick Start

Get full observability for your MCP ecosystem in **5 minutes**.

## Prerequisites

- Docker and Docker Compose installed
- Python 3.10+ (for running MCP servers)
- 4GB RAM minimum, 8GB recommended

## Quick Start (5 Minutes)

### 1. Start Monitoring Stack (2 minutes)

```bash
cd /Users/les/Projects/mahavishnu/monitoring
docker-compose up -d
```

This starts:
- **Prometheus** (metrics): http://localhost:9090
- **Grafana** (dashboards): http://localhost:3000
- **Jaeger** (traces): http://localhost:16686
- **Loki** (logs): http://localhost:3100
- **OTEL Collector** (tracing): localhost:4317

### 2. Install Dependencies (1 minute)

```bash
pip install \
    opentelemetry-api==1.20.0 \
    opentelemetry-sdk==1.20.0 \
    opentelemetry-instrumentation-fastapi==0.41b0 \
    opentelemetry-instrumentation-httpx==0.41b0 \
    opentelemetry-instrumentation-asyncio==0.41b0 \
    opentelemetry-exporter-otlp-proto-grpc==1.20.0 \
    prometheus-client==0.19.0 \
    psutil==5.9.6
```

### 3. Integrate into Your MCP Server (2 minutes)

Add to your MCP server's `main.py`:

```python
# Add imports
from monitoring.otel import setup_telemetry, auto_instrument
from monitoring.metrics import expose_metrics
from fastapi import FastAPI, Response

app = FastAPI()

# Setup OpenTelemetry
tracer = setup_telemetry(
    service_name="my-mcp-server",
    otlp_endpoint="http://localhost:4317",
    environment="production"
)

# Auto-instrument
auto_instrument(app, "my-mcp-server")

# Add metrics endpoint
@app.get("/metrics")
async def metrics():
    return Response(content=expose_metrics(), media_type="text/plain")
```

### 4. Verify Monitoring (instant)

Check your MCP server metrics:
```bash
curl http://localhost:8000/metrics
```

You should see Prometheus metrics output!

## Dashboards

### Grafana (http://localhost:3000)

**Login**:
- Username: `admin`
- Password: `admin`

**Import Dashboard**:
1. Navigate to Dashboards → Import
2. Upload `monitoring/dashboards/mcp_ecosystem.json`
3. View your MCP ecosystem metrics in real-time!

**Dashboard Features**:
- Request rate and latency
- Tool success rate
- Worker pool status
- System resource usage
- CPU, memory, disk trends

### Jaeger (http://localhost:16686)

**Search Traces**:
1. Select your service from the dropdown
2. Search by operation name, trace ID, or tags
3. View detailed trace timeline
4. Identify bottlenecks and errors

### Prometheus (http://localhost:9090)

**Query Metrics**:
```promql
# Error rate
rate(mcp_tool_calls_total{status="error"}[5m])

# P95 latency
histogram_quantile(0.95, rate(mcp_http_request_duration_seconds_bucket[5m]))

# Active workers
pool_workers_active

# Tool success rate
rate(mcp_tool_calls_total{status="success"}[5m]) / rate(mcp_tool_calls_total[5m]) * 100
```

## Environment Variables

```bash
# OpenTelemetry configuration
export OTLP_ENDPOINT="http://localhost:4317"
export OTEL_CONSOLE_DEBUG="false"  # Enable for local debugging
export ENV="production"  # or "staging", "development"

# Grafana (optional)
export GF_SECURITY_ADMIN_PASSWORD="your-secure-password"
```

## Docker Compose Commands

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f grafana

# Stop all services
docker-compose down

# Restart specific service
docker-compose restart prometheus

# Scale services (if needed)
docker-compose up -d --scale grafana=2
```

## Monitoring All MCP Servers

Once your MCP servers have monitoring integrated, Prometheus will automatically scrape metrics from all of them:

| Service | Port | Metrics Path |
|---------|------|---------------|
| Mahavishnu | 8680 | /metrics |
| Akosha | 8682 | /metrics |
| Session-Buddy | 8678 | /metrics |
| Crackerjack | 8676 | /metrics |
| Excalidraw | 3032 | /metrics |
| Mermaid | 3033 | /metrics |
| UniFi | 3038 | /metrics |
| Mailgun | 3039 | /metrics |
| RaindropIO | 3034 | /metrics |

## Troubleshooting

### Metrics not appearing

1. Check Prometheus targets: http://localhost:9090/targets
2. Verify `/metrics` endpoint is accessible
3. Check Docker logs: `docker-compose logs prometheus`

### Traces not appearing

1. Check Jaeger UI: http://localhost:16686
2. Verify OTLP endpoint is correct
3. Check Docker logs: `docker-compose logs otel-collector`

### Grafana can't connect to Prometheus

1. Add Prometheus datasource in Grafana:
   - Configuration → Data Sources → Add data source
   - Select Prometheus
   - URL: `http://prometheus:9090`
   - Save & Test

## Example: Full Integration

See `monitoring/example_integration.py` for a complete working example showing:
- OpenTelemetry span creation
- Prometheus metrics collection
- Custom attributes
- Error tracking
- Background system metrics

## Next Steps

1. **Configure alerting** - Set up AlertManager rules
2. **Add log aggregation** - Configure Promtail for MCP server logs
3. **Create custom dashboards** - Build domain-specific views
4. **Set up synthetic monitoring** - Health checks and uptime monitoring
5. **Performance baselines** - Establish normal operating ranges

## Architecture Overview

```
┌──────────────────────────────────────────────────┐
│                  MCP Servers                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ Mahavishnu│  │  Akosha   │  │Session-  │      │
│  │          │  │          │  │Buddy    │      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘      │
│       │            │            │             │
│       └────────────┼────────────┘             │
│                    │                          │
│              ┌─────▼──────────┐                │
│              │ OpenTelemetry  │                │
│              │   Collector    │                │
│              └─────┬──────────┘                │
│                    │                          │
│        ┌───────────┼───────────────┐            │
│        │           │               │            │
│    ┌───▼──┐   ┌───▼────┐   ┌────▼─────┐        │
│    │Prom  │   │ Grafana│   │  Loki    │        │
│    │etheus│   │        │   │         │        │
│    └──────┘   └────────┘   └─────────┘        │
└──────────────────────────────────────────────────┘
```

## Cost

**Self-hosted** (recommended for development):
- Infrastructure: $0 (your own server)
- Time: 1-2 hours setup
- Maintenance: Low

**Cloud-hosted** (production):
- GCP Cloud Operations: ~$50/month for basic tier
- AWS X-Ray: ~$30/TB traced
- Azure Monitor: ~$25/month

## Support

For issues or questions:
- Check logs: `docker-compose logs -f [service-name]`
- Health check: `curl http://localhost:9090/-/healthy`
- Documentation: `monitoring/MONITORING_GUIDE.md`

## Success Criteria

✅ All MCP servers exporting metrics
✅ Distributed tracing across services
✅ Real-time dashboards operational
✅ Alert rules configured (Phase 4, Task 2)
✅ <1% performance overhead
✅ <5s scrape interval
