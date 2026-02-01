# OTLP Documentation Summary

Complete OTLP (OpenTelemetry Protocol) ingestion documentation for Mahavishnu observability stack.

## Documentation Files Created

### 1. Main Setup Guide
**File:** `/Users/les/Projects/mahavishnu/docs/OTLP_SETUP_GUIDE.md`

Comprehensive 500+ line guide covering:
- Quick start instructions
- Architecture overview
- All ingestion methods (OTLP, file logs, hybrid)
- Client configuration examples
- Claude-specific integration
- Qwen-specific integration
- General Python application examples
- Testing and validation procedures
- Complete troubleshooting section
- Production deployment checklist

### 2. Troubleshooting Guide
**File:** `/Users/les/Projects/mahavishnu/docs/OTLP_TROUBLESHOOTING.md`

Dedicated troubleshooting guide with:
- Quick diagnostic script
- 8 common issues with solutions
- Debugging tools (Zpages, Prometheus metrics, pprof)
- Performance tuning guidelines
- Comprehensive health check script

## Configuration Files Created

### 3. Main Collector Configuration
**File:** `/Users/les/Projects/mahavishnu/config/otel-collector-config.yaml`

Updated production configuration with:
- Primary OTLP receiver (ports 4317/4318)
- Claude-specific OTLP receiver (ports 4319/4320)
- Qwen-specific OTLP receiver (ports 4321/4322)
- File log receivers for Claude, Qwen, and general logs
- Separate pipelines for each source
- Resource attributes for source identification
- Exporters to Jaeger, Prometheus, and Elasticsearch

### 4. Grafana Provisioning
**Files:**
- `/Users/les/Projects/mahavishnu/config/grafana/datasources/datasources.yml`
- `/Users/les/Projects/mahavishnu/config/grafana/dashboards/dashboards.yml`
- `/Users/les/Projects/mahavishnu/config/grafana/dashboards/otlp-overview-dashboard.json`

Pre-configured Grafana with:
- Prometheus datasource
- Jaeger datasource
- OTLP overview dashboard with 4 panels

## Client Examples and Testing Tools

### 5. Python OTLP Client
**File:** `/Users/les/Projects/mahavishnu/config/clients/python-otlp-client.py`

Full-featured Python client with:
- Complete instrumentation (traces, metrics, logs)
- Command-line interface with multiple options
- Support for all collector endpoints
- AI workflow simulation (Claude/Qwen)
- Debug console export option
- Comprehensive examples

**Usage:**
```bash
# Primary collector
python python-otlp-client.py --endpoint http://localhost:4317 --service test-app

# Claude-specific
python python-otlp-client.py --endpoint http://localhost:4319 --source claude --ai-workflow

# Qwen-specific
python python-otlp-client.py --endpoint http://localhost:4321 --source qwen --ai-workflow
```

### 6. Standalone Test Stack
**File:** `/Users/les/Projects/mahavishnu/config/clients/docker-compose.otlp.yml`

Lightweight OTel stack for testing:
- OTel Collector (test configuration)
- Jaeger (tracing)
- Prometheus (metrics)
- Grafana (dashboards)

**Usage:**
```bash
docker-compose -f docker-compose.otlp.yml up -d
```

### 7. Supporting Configuration Files
**Files:**
- `/Users/les/Projects/mahavishnu/config/clients/otel-collector-test-config.yaml`
- `/Users/les/Projects/mahavishnu/config/clients/prometheus.yml`
- `/Users/les/Projects/mahavishnu/config/clients/grafana-datasources.yml`

### 8. Quick Start Script
**File:** `/Users/les/Projects/mahavishnu/config/clients/quickstart.sh`

Automated testing script:
```bash
# Start stack and run all tests
./quickstart.sh

# Options
./quickstart.sh --stack-only   # Start stack only
./quickstart.sh --test-only    # Send test data only
./quickstart.sh --stop         # Stop stack
./quickstart.sh --clean        # Stop and remove volumes
```

### 9. Makefile
**File:** `/Users/les/Projects/mahavishnu/config/clients/Makefile`

Convenience commands:
```bash
make start          # Start test stack
make test           # Run all tests
make test-claude    # Test Claude endpoint
make test-qwen      # Test Qwen endpoint
make stop           # Stop stack
make clean          # Stop and remove volumes
make health         # Check collector health
make logs           # View collector logs
```

### 10. Client README
**File:** `/Users/les/Projects/mahavishnu/config/clients/README.md`

Comprehensive guide for:
- Quick start instructions
- Test stack usage
- Python client examples
- Environment variable configuration
- Integration examples (Flask, FastAPI)
- Troubleshooting tips

## Quick Start

### Option 1: Test with Standalone Stack

```bash
cd /Users/les/Projects/mahavishnu/config/clients
./quickstart.sh
```

### Option 2: Test with Full Mahavishnu Stack

```bash
# Start full stack
docker-compose -f /Users/les/Projects/mahavishnu/docker-compose.buildpacks.yml up -d

# Send test telemetry
cd /Users/les/Projects/mahavishnu/config/clients
python python-otlp-client.py --endpoint http://localhost:4317 --service test-app
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         OTLP Endpoints                              │
├──────────┬──────────┬──────────┬──────────┬──────────┬─────────────┤
│ Primary  │ Claude   │ Qwen     │ Primary  │ Claude   │ Qwen        │
│ gRPC     │ gRPC     │ gRPC     │ HTTP     │ HTTP     │ HTTP        │
│ 4317     │ 4319     │ 4321     │ 4318     │ 4320     │ 4322        │
└──────────┴──────────┴──────────┴──────────┴──────────┴─────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      OpenTelemetry Collector                        │
│  • Separate pipelines for each source                              │
│  • Resource attributes for identification                          │
│  • Batch processing with memory limiter                            │
└─────────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│    Jaeger     │    │   Prometheus  │    │ Elasticsearch │
│  (Traces)     │    │   (Metrics)   │    │    (Logs)     │
│  :16686       │    │   :9090       │    │    :9200      │
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │     Grafana     │
                    │   :3000         │
                    │  (Dashboards)   │
                    └─────────────────┘
```

## Key Features

### Source Identification

Each telemetry source is identified via resource attributes:

```python
Resource.create({
    "service.name": "claude-integration",
    "telemetry.source": "claude",
    "telemetry.source.type": "ai_assistant"
})
```

This enables:
- Filtering in Jaeger
- Label-based queries in Prometheus
- Index separation in Elasticsearch
- Dashboard segmentation in Grafana

### Separate Pipelines

Dedicated pipelines for each source:
- Prevents cross-contamination
- Enables per-source rate limiting
- Allows independent scaling
- Simplifies debugging

### File Log Fallback

Automatic file log ingestion for:
- Offline scenarios
- High-volume logging
- Legacy integration
- Audit trail

## Port Reference

| Service | Port | Purpose |
|---------|------|---------|
| **OTLP (Primary gRPC)** | 4317 | Primary OTLP ingestion |
| **OTLP (Primary HTTP)** | 4318 | Primary OTLP HTTP |
| **OTLP (Claude gRPC)** | 4319 | Claude-specific OTLP |
| **OTLP (Claude HTTP)** | 4320 | Claude-specific HTTP |
| **OTLP (Qwen gRPC)** | 4321 | Qwen-specific OTLP |
| **OTLP (Qwen HTTP)** | 4322 | Qwen-specific HTTP |
| **Collector Health** | 13133 | Health checks |
| **Collector Metrics** | 8888 | Collector metrics |
| **Jaeger UI** | 16686 | Trace visualization |
| **Prometheus** | 9090 | Metrics query |
| **Grafana** | 3000 | Dashboards (admin/admin) |
| **Elasticsearch** | 9200 | Log storage API |
| **Kibana** | 5601 | Log visualization |

## Testing Checklist

- [ ] Start OTel stack (test or full)
- [ ] Verify collector health: `curl http://localhost:13133/healthy`
- [ ] Send test telemetry to primary endpoint
- [ ] Send test telemetry to Claude endpoint
- [ ] Send test telemetry to Qwen endpoint
- [ ] Verify traces in Jaeger (http://localhost:16686)
- [ ] Verify metrics in Prometheus (http://localhost:9090)
- [ ] Verify metrics in Grafana (http://localhost:3000)
- [ ] Verify logs in Elasticsearch/Kibana (http://localhost:5601)
- [ ] Test file log ingestion (if applicable)

## Production Deployment

See `OTLP_SETUP_GUIDE.md` for complete production checklist:

- [ ] Update deployment environment
- [ ] Configure TLS for all endpoints
- [ ] Adjust batch sizes for production load
- [ ] Configure log rotation
- [ ] Set up volume mounts
- [ ] Enable security features
- [ ] Configure high availability
- [ ] Set up data retention policies
- [ ] Configure monitoring and alerts
- [ ] Document custom attributes

## Additional Resources

- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [OpenTelemetry Python SDK](https://opentelemetry.io/docs/instrumentation/python/)
- [OTel Collector Configuration](https://opentelemetry.io/docs/collector/configuration/)
- [Jaeger Documentation](https://www.jaegertracing.io/docs/)
- [Prometheus Documentation](https://prometheus.io/docs/)

## Support

For issues or questions:
1. Check `OTLP_TROUBLESHOOTING.md`
2. Run diagnostic script
3. Review collector logs: `docker logs otel-collector`
4. Check configuration: `docker exec otel-collector cat /etc/otel-collector-config.yaml`

---

**Documentation Version:** 1.0.0
**Last Updated:** 2025-01-31
**Status:** Production Ready
