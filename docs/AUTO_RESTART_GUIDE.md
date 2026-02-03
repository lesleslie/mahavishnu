# Auto-Restart Configuration Guide

This guide explains how to configure Mahavishnu for automatic restart on failure using systemd or supervisord.

## Why Auto-Restart?

Auto-restart ensures that Mahavishnu recovers automatically from crashes, failures, or unexpected terminations. This is critical for production deployments where high availability is required.

## Auto-Restart Options

### Option 1: Systemd (Recommended for Linux)

**Pros:**
- Native to modern Linux distributions
- Built-in dependency management
- Journal log integration
- Comprehensive service management

**Installation:**

```bash
# 1. Copy service file to systemd directory
sudo cp mahavishnu.service /etc/systemd/system/

# 2. Reload systemd configuration
sudo systemctl daemon-reload

# 3. Enable service to start on boot
sudo systemctl enable mahavishnu

# 4. Start the service
sudo systemctl start mahavishnu

# 5. Check status
sudo systemctl status mahavishnu
```

**Auto-Restart Configuration:**

The service file includes:
- `Restart=on-failure` - Restart only on failure (not on normal exit)
- `RestartSec=10s` - Wait 10 seconds before restarting
- `StartLimitInterval=60s` - Reset failure count after 60 seconds
- `StartLimitBurst=5` - Maximum 5 restart attempts within interval

**Useful Commands:**

```bash
# Start/stop/restart service
sudo systemctl start mahavishnu
sudo systemctl stop mahavishnu
sudo systemctl restart mahavishnu

# View logs
sudo journalctl -u mahavishnu -f
sudo journalctl -u mahavishnu --since "1 hour ago"

# Check service status
sudo systemctl status mahavishnu

# Enable/disable auto-start on boot
sudo systemctl enable mahavishnu
sudo systemctl disable mahavishnu
```

### Option 2: Supervisord (Cross-Platform)

**Pros:**
- Works on Linux, macOS, and Windows
- Simple configuration
- Built-in log management
- Process group management

**Installation:**

```bash
# 1. Install supervisord
sudo apt-get install supervisor  # Debian/Ubuntu
sudo yum install supervisor      # RHEL/CentOS

# 2. Copy configuration file
sudo cp mahavishnu.supervisord.conf /etc/supervisor/conf.d/mahavishnu.conf

# 3. Reread configuration
sudo supervisorctl reread

# 4. Update supervisord
sudo supervisorctl update

# 5. Start service
sudo supervisorctl start mahavishnu

# 6. Check status
sudo supervisorctl status mahavishnu
```

**Auto-Restart Configuration:**

The supervisord config includes:
- `autorestart=true` - Restart on failure
- `startretries=5` - Maximum restart attempts
- `stopwaitsecs=10` - Wait time for graceful shutdown

**Useful Commands:**

```bash
# Start/stop/restart service
sudo supervisorctl start mahavishnu
sudo supervisorctl stop mahavishnu
sudo supervisorctl restart mahavishnu

# View logs
sudo supervisorctl tail -f mahavishnu

# Check status
sudo supervisorctl status mahavishnu

# Update configuration
sudo supervisorctl reread
sudo supervisorctl update
```

## Health Check Endpoints

Mahavishnu includes health check endpoints for monitoring systems:

### Endpoints

- **GET /health** - Liveness probe (is the server alive?)
  ```bash
  curl http://localhost:8080/health
  ```

- **GET /ready** - Readiness probe (can the server handle requests?)
  ```bash
  curl http://localhost:8080/ready
  ```

- **GET /metrics** - Prometheus metrics
  ```bash
  curl http://localhost:8080/metrics
  ```

### Health Response Format

```json
{
  "status": "healthy",
  "timestamp": "2025-02-03T12:00:00Z",
  "uptime_seconds": 3600.5
}
```

### Readiness Response Format

```json
{
  "ready": true,
  "timestamp": "2025-02-03T12:00:00Z",
  "checks": {
    "server": true,
    "database": true,
    "message_bus": true,
    "adapters": true
  }
}
```

## Kubernetes Deployment

For Kubernetes deployments, use the following pod configuration:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: mahavishnu
spec:
  containers:
  - name: mahavishnu
    image: mahavishnu:latest
    ports:
    - containerPort: 8678  # MCP server
    - containerPort: 8080  # Health check
    livenessProbe:
      httpGet:
        path: /health
        port: 8080
      initialDelaySeconds: 30
      periodSeconds: 10
      timeoutSeconds: 5
      failureThreshold: 3
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 10
      periodSeconds: 5
      timeoutSeconds: 3
      failureThreshold: 3
    resources:
      limits:
        memory: "2Gi"
        cpu: "2000m"
      requests:
        memory: "1Gi"
        cpu: "1000m"
```

## Testing Auto-Restart

To test auto-restart functionality:

```bash
# 1. Start service
sudo systemctl start mahavishnu

# 2. Kill the process (simulates crash)
sudo pkill -f mahavishnu

# 3. Wait 10 seconds and check status
sudo systemctl status mahavishnu
# Service should be running (auto-restarted)

# 4. View logs
sudo journalctl -u mahavishnu --since "1 minute ago"
# Should see restart messages
```

## Monitoring

Monitor auto-restart events using:

1. **Journalctl (systemd):**
   ```bash
   sudo journalctl -u mahavishnu -f
   ```

2. **Supervisorctl (supervisord):**
   ```bash
   sudo supervisorctl tail -f mahavishnu
   ```

3. **SLO Metrics:**
   - Track uptime percentage
   - Monitor restart frequency
   - Alert on excessive restarts (>5 per hour)

## Troubleshooting

### Service fails to start

```bash
# Check service status
sudo systemctl status mahavishnu

# View recent logs
sudo journalctl -u mahavishnu --since "10 minutes ago"

# Check configuration
sudo systemd-analyze verify /etc/systemd/system/mahavishnu.service
```

### Service keeps restarting

```bash
# Check restart count
systemctl show mahavishnu -p NRestarts

# View logs for errors
sudo journalctl -u mahavishnu -n 100

# Temporarily disable auto-restart for debugging
sudo systemctl stop mahavishnu
# Run manually
cd /opt/mahavishnu
.venv/bin/python -m mahavishnu.cli mcp start
```

### Health check failing

```bash
# Test health endpoint
curl http://localhost:8080/health
curl http://localhost:8080/ready

# Check if health service is running
sudo systemctl status mahavishnu-health

# View health service logs
sudo journalctl -u mahavishnu-health -f
```

## Best Practices

1. **Set appropriate resource limits** - Prevent memory leaks from affecting the host
2. **Monitor restart frequency** - Excessive restarts indicate application issues
3. **Use health checks** - Integrate with monitoring systems (Prometheus, Grafana)
4. **Log everything** - Centralized logging helps diagnose issues
5. **Test crash recovery** - Verify auto-restart works before production deployment

## Integration with Monitoring

### Prometheus Alert Example

```yaml
groups:
- name: mahavishnu
  rules:
  - alert: MahavishnuServiceDown
    expr: up{job="mahavishnu"} == 0
    for: 5m
    annotations:
      summary: "Mahavishnu service is down"
      description: "Mahavishnu has been down for more than 5 minutes"

  - alert: MahavishnuHighRestartRate
    expr: rate(process_restart_total{job="mahavishnu"}[1h]) > 5
    annotations:
      summary: "Mahavishnu restarting frequently"
      description: "Mahavishnu has restarted more than 5 times in the last hour"
```

## Security Considerations

1. **Run as non-root user** - Service files use dedicated `mahavishnu` user
2. **Restrict file permissions** - Only user can write to application directory
3. **Enable NoNewPrivileges** - Prevent privilege escalation
4. **Use PrivateTmp** - Isolate /tmp directory
5. **Protect system directories** - Read-only access to critical paths

## Conclusion

Auto-restart is critical for production deployments. Choose systemd for Linux-native deployments or supervisord for cross-platform compatibility. Always test auto-restart functionality before deploying to production.
