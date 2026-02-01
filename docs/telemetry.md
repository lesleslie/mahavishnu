# Mahavishnu Observability Documentation Index

Complete guide to OpenTelemetry and observability in Mahavishnu.

## Quick Links

- [Quick Start Guide](#quick-start) - Get started in 5 minutes
- [Main Documentation](#main-documentation) - Comprehensive guides
- [Configuration Files](#configuration-files) - All config files
- [Client Examples](#client-examples) - Code examples and tools
- [Troubleshooting](#troubleshooting) - Problem-solving guide

## Quick Start

```bash
# Option 1: Standalone test stack (fastest)
cd /Users/les/Projects/mahavishnu/config/clients
./quickstart.sh

# Option 2: Full Mahavishnu stack
docker-compose -f /Users/les/Projects/mahavishnu/docker-compose.buildpacks.yml up -d

# Send test telemetry
python python-otlp-client.py --endpoint http://localhost:4317 --service test-app

# View telemetry
open http://localhost:16686  # Jaeger
open http://localhost:9090   # Prometheus
open http://localhost:3000   # Grafana
```

## Main Documentation

### 1. [OTLP Setup Guide](OTLP_SETUP_GUIDE.md)

**Complete guide for OTLP telemetry ingestion**

- Quick start instructions
- Architecture overview
- Ingestion methods (OTLP, file logs, hybrid)
- Claude-specific integration
- Qwen-specific integration
- Python client configuration
- Testing and validation
- Production deployment checklist

**Best for:** First-time setup, understanding architecture, production deployment

### 2. [OTLP Troubleshooting Guide](OTLP_TROUBLESHOOTING.md)

**Solve common OTLP issues**

- Quick diagnostic script
- 8 common issues with solutions:
  1. No traces in Jaeger
  2. Connection refused
  3. Metrics not in Prometheus
  4. Logs not in Elasticsearch
  5. File log receiver issues
  6. High memory usage
  7. Mixed telemetry sources
  8. Batch delays
- Debugging tools (Zpages, metrics, pprof)
- Performance tuning
- Health check scripts

**Best for:** Debugging issues, optimizing performance

### 3. [OTLP Architecture](OTLP_ARCHITECTURE.md)

**Visual architecture diagrams**

- Overview diagram
- Telemetry flow diagrams (traces, file logs)
- Source identification strategy
- Pipeline processing flow
- Network architecture
- Production HA architecture

**Best for:** Understanding system design, planning deployments

### 4. [OTLP Documentation Summary](OTLP_DOCUMENTATION_SUMMARY.md)

**Quick reference and file inventory**

- All created files
- Port reference
- Quick start commands
- Testing checklist
- Production deployment checklist

**Best for:** Quick lookups, file references

## Configuration Files

### Main Configuration

| File | Purpose | Lines |
|------|---------|-------|
| [`config/otel-collector-config.yaml`](../config/otel-collector-config.yaml) | Production OTel collector config | 380 |
| [`config/prometheus.yml`](../config/prometheus.yml) | Prometheus scraping config | 30 |

### Grafana Configuration

| File | Purpose |
|------|---------|
| [`config/grafana/datasources/datasources.yml`](../config/grafana/datasources/datasources.yml) | Prometheus + Jaeger datasources |
| [`config/grafana/dashboards/dashboards.yml`](../config/grafana/dashboards/dashboards.yml) | Dashboard provisioning |
| [`config/grafana/dashboards/otlp-overview-dashboard.json`](../config/grafana/dashboards/otlp-overview-dashboard.json) | Pre-built dashboard |

## Client Examples

### Python Client

**File:** [`config/clients/python-otlp-client.py`](../config/clients/python-otlp-client.py) (450 lines)

Complete Python OTLP client with:

- Traces, metrics, and logs instrumentation
- Support for all OTLP endpoints
- Claude and Qwen workflow simulation
- Command-line interface

**Usage:**
```bash
# Primary endpoint
python python-otlp-client.py --endpoint http://localhost:4317 --service my-app

# Claude endpoint
python python-otlp-client.py --endpoint http://localhost:4319 --source claude --ai-workflow

# Qwen endpoint
python python-otlp-client.py --endpoint http://localhost:4321 --source qwen --ai-workflow
```

### Testing Tools

| File | Purpose |
|------|---------|
| [`config/clients/docker-compose.otlp.yml`](../config/clients/docker-compose.otlp.yml) | Standalone OTel test stack |
| [`config/clients/quickstart.sh`](../config/clients/quickstart.sh) | Automated testing script |
| [`config/clients/Makefile`](../config/clients/Makefile) | Convenience commands |
| [`config/clients/diagnose.sh`](../config/clients/diagnose.sh) | System health check |
| [`config/clients/README.md`](../config/clients/README.md) | Client examples guide |

## Port Reference

| Service | Port | Protocol | Purpose |
|---------|------|----------|---------|
| **Primary OTLP** | | | |
| OTLP gRPC | 4317 | gRPC | Primary telemetry ingestion |
| OTLP HTTP | 4318 | HTTP | Primary telemetry ingestion |
| **Claude OTLP** | | | |
| Claude gRPC | 4319 | gRPC | Claude-specific ingestion |
| Claude HTTP | 4320 | HTTP | Claude-specific ingestion |
| **Qwen OTLP** | | | |
| Qwen gRPC | 4321 | gRPC | Qwen-specific ingestion |
| Qwen HTTP | 4322 | HTTP | Qwen-specific ingestion |
| **Collector** | | | |
| Health | 13133 | HTTP | Health checks |
| Metrics | 8888 | HTTP | Collector metrics |
| Zpages | 9464 | HTTP | Trace debugging |
| **Backends** | | | |
| Jaeger UI | 16686 | HTTP | Trace visualization |
| Prometheus | 9090 | HTTP | Metrics query |
| Grafana | 3000 | HTTP | Dashboards |
| Elasticsearch | 9200 | HTTP | Log storage |
| Kibana | 5601 | HTTP | Log visualization |

## Common Tasks

### Start the OTel Stack

```bash
# Full Mahavishnu stack
docker-compose -f /Users/les/Projects/mahavishnu/docker-compose.buildpacks.yml up -d

# Standalone test stack
cd /Users/les/Projects/mahavishnu/config/clients
docker-compose -f docker-compose.otlp.yml up -d
```

### Send Test Telemetry

```bash
cd /Users/les/Projects/mahavishnu/config/clients

# All sources
python python-otlp-client.py --endpoint http://localhost:4317 --service test-app

# Claude only
python python-otlp-client.py --endpoint http://localhost:4319 --source claude --ai-workflow

# Qwen only
python python-otlp-client.py --endpoint http://localhost:4321 --source qwen --ai-workflow
```

### View Telemetry

| Telemetry Type | URL | Notes |
|----------------|-----|-------|
| **Traces** | http://localhost:16686 | Jaeger UI |
| **Metrics** | http://localhost:9090 | Prometheus UI |
| **Dashboards** | http://localhost:3000 | Grafana (admin/admin) |
| **Logs** | http://localhost:5601 | Kibana |

### Health Check

```bash
cd /Users/les/Projects/mahavishnu/config/clients
./diagnose.sh
```

### Troubleshooting

1. Check collector health: `curl http://localhost:13133/healthy`
2. View collector logs: `docker logs otel-collector`
3. Run diagnostics: `./diagnose.sh`
4. See [OTLP Troubleshooting Guide](OTLP_TROUBLESHOOTING.md)

## Architecture Overview

```
┌──────────────┐     OTLP      ┌──────────────────┐     Export     ┌──────────┐
│   Claude     │──────────────▶│                  │───────────────▶│ Jaeger   │
│   Qwen       │   (gRPC/HTTP) │   OTel Collector │                │ Prometheus│
│   Custom App │               │                  │───────────────▶│ Elastic  │
└──────────────┘               └──────────────────┘                │ Search   │
                                      │                            └──────────┘
                                      ▼
                               ┌──────────────┐
                               │ File Log     │
                               │ Receiver     │
                               │ (optional)   │
                               └──────────────┘
```

**Key Features:**

- **Multi-endpoint ingestion**: Separate endpoints for primary, Claude, and Qwen
- **File log fallback**: Automatic log file ingestion for offline scenarios
- **Source identification**: Resource attributes distinguish telemetry sources
- **Separate pipelines**: Isolated processing per source type
- **Production-ready**: Complete monitoring, alerting, and HA support

## Integration Examples

### Python Application

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

# Setup
resource = Resource.create({
    "service.name": "my-app",
    "telemetry.source": "custom"
})
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(
    OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
))
trace.set_tracer_provider(provider)

# Use
tracer = trace.get_tracer(__name__)
with tracer.start_as_current_span("operation"):
    # Your code here
    pass
```

See [OTLP Setup Guide](OTLP_SETUP_GUIDE.md) for Flask, FastAPI, and more examples.

## Production Checklist

- [ ] Update deployment environment in config
- [ ] Configure TLS for production endpoints
- [ ] Adjust batch sizes for load
- [ ] Configure log rotation
- [ ] Set up volume mounts
- [ ] Enable security features
- [ ] Configure high availability
- [ ] Set up data retention policies
- [ ] Configure monitoring and alerts
- [ ] Document custom attributes

See [OTLP Setup Guide - Production Checklist](OTLP_SETUP_GUIDE.md#production-checklist) for details.

## Support

### Documentation

- [OTLP Setup Guide](OTLP_SETUP_GUIDE.md) - Main documentation
- [OTLP Troubleshooting](OTLP_TROUBLESHOOTING.md) - Problem-solving
- [OTLP Architecture](OTLP_ARCHITECTURE.md) - Visual diagrams
- [OTLP Summary](OTLP_DOCUMENTATION_SUMMARY.md) - Quick reference

### Tools

```bash
# Diagnostics
./config/clients/diagnose.sh

# Quick start
./config/clients/quickstart.sh

# Make commands
cd config/clients && make help
```

### External Resources

- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [OpenTelemetry Python](https://opentelemetry.io/docs/instrumentation/python/)
- [Jaeger Documentation](https://www.jaegertracing.io/docs/)
- [Prometheus Documentation](https://prometheus.io/docs/)

---

**Last Updated:** 2025-01-31
**Version:** 1.0.0
**Status:** Production Ready
