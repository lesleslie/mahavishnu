# Production Deployment

This guide covers deploying Mahavishnu in production environments.

## Environment Preparation

### System Requirements

- Python 3.13 or higher
- At least 2GB RAM (4GB recommended for heavy workloads)
- Sufficient disk space for repository clones and logs
- Network access to LLM providers (if using AI features)

### Virtual Environment

Create and activate a virtual environment:

```bash
python -m venv production-env
source production-env/bin/activate
```

## Installation

Install Mahavishnu in production mode:

```bash
pip install -e .
```

For specific adapter support:

```bash
# For LangGraph workflows
pip install -e .[langgraph]

# For Prefect workflows
pip install -e .[prefect]

# For all adapters
pip install -e .[all]
```

## Configuration

### Production Configuration

Create a production configuration in `settings/production.yaml`:

```yaml
server_name: "Mahavishnu Production"
cache_root: /var/cache/mahavishnu
health_ttl_seconds: 30.0
log_level: INFO

adapters:
  airflow: false  # Migrate to Prefect
  crewai: false   # Use LangGraph instead
  langgraph: true
  agno: false     # Experimental
  prefect: true

qc:
  enabled: true
  min_score: 85

auth:
  enabled: true
  algorithm: "HS256"
  expire_minutes: 30

# Observability
metrics_enabled: true
tracing_enabled: true
otlp_endpoint: "http://otel-collector:4317"

# Resilience
retry_max_attempts: 5
retry_base_delay: 2.0
circuit_breaker_threshold: 10
timeout_per_repo: 600

# Concurrency
max_concurrent_workflows: 20
```

### Environment Variables

Set required environment variables:

```bash
export MAHAVISHNU_AUTH_SECRET="your-production-jwt-secret"
export MAHAVISHNU_LLM_API_KEY="your-production-llm-key"
export MAHAVISHNU_REPOS_PATH="/etc/mahavishnu/repos.yaml"
```

## Deployment Strategies

### Container Deployment

Create a Dockerfile for container deployment:

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY mahavishnu ./mahavishnu

RUN pip install -e .

EXPOSE 8000

CMD ["mahavishnu", "mcp-serve"]
```

### Process Management

Use a process manager like systemd or supervisord to manage the MCP server:

Example systemd service file (`/etc/systemd/system/mahavishnu.service`):

```ini
[Unit]
Description=Mahavishnu MCP Server
After=network.target

[Service]
Type=simple
User=mahavishnu
WorkingDirectory=/opt/mahavishnu
Environment=MAHAVISHNU_AUTH_SECRET=your-secret
Environment=MAHAVISHNU_LLM_API_KEY=your-key
ExecStart=/opt/mahavishnu/venv/bin/python -m mahavishnu mcp-serve
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Monitoring and Observability

### Metrics Collection

Configure OpenTelemetry to export metrics to your preferred backend:

```yaml
observability:
  metrics_enabled: true
  tracing_enabled: true
  otlp_endpoint: "http://otel-collector:4317"
  metrics_export_interval: 30
```

### Health Checks

Implement health checks for your deployment:

```bash
# Check if the service is running
curl -X GET http://localhost:3000/health

# Or use the CLI
mahavishnu health
```

## Backup and Recovery

### Configuration Backup

Regularly backup configuration files:

```bash
tar -czf mahavishnu-config-backup-$(date +%Y%m%d).tar.gz \
  settings/production.yaml \
  repos.yaml
```

### Rollback Plan

Maintain a rollback plan:

1. Keep previous version artifacts
1. Document the rollback procedure
1. Test the rollback process in staging
1. Have a communication plan for users

## Security Hardening

### Network Security

- Use a reverse proxy (nginx, Apache) in front of the MCP server
- Enable HTTPS/TLS termination
- Implement IP whitelisting for sensitive endpoints
- Use firewall rules to restrict access

### Secrets Management

Use a secrets management solution:

- Hashicorp Vault
- AWS Secrets Manager
- Azure Key Vault
- Kubernetes secrets

## Performance Tuning

### Concurrency Settings

Adjust concurrency based on your hardware:

```yaml
# For high-performance servers
max_concurrent_workflows: 50
timeout_per_repo: 1200

# For resource-constrained environments
max_concurrent_workflows: 5
timeout_per_repo: 300
```

### Resource Limits

Set appropriate resource limits in containers or process managers:

```yaml
# Memory and CPU limits
memory_limit: "4G"
cpu_limit: "2.0"
```

## Troubleshooting

### Common Issues

See the [Troubleshooting](troubleshooting.md) guide for common production issues.

### Log Analysis

Monitor logs for errors and performance issues:

```bash
# View recent logs
journalctl -u mahavishnu -n 100

# Follow logs in real-time
journalctl -u mahavishnu -f
``
```
