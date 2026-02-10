# Grafana Dashboard Quick Start

**Time to Complete**: 5 minutes
**Difficulty**: Beginner
**Last Updated**: 2025-02-05

## Overview

Get up and running with Mahavishnu monitoring dashboards in 5 minutes. This guide covers the fastest path to visualize your MCP ecosystem metrics.

---

## Prerequisites Check (30 seconds)

Verify you have the required tools:

```bash
# Check Docker
docker --version
# Expected: Docker version 20.10+ or docker-compose version 2.0+

# Check ports are available
nc -zv localhost 3000 && echo "Port 3000 in use" || echo "Port 3000 available"
nc -zv localhost 9090 && echo "Port 9090 in use" || echo "Port 9090 available"

# Check Mahavishnu is running
mahavishnu mcp status
# Expected: Mahavishnu MCP server running on port 8680
```

**If any check fails**, resolve before continuing:
- Install Docker Desktop from https://www.docker.com/products/docker-desktop/
- Stop conflicting services on ports 3000, 9090
- Start Mahavishnu: `mahavishnu mcp start`

---

## Quick Start Option 1: Full Stack (3 minutes)

### Step 1: Start Monitoring Stack (1 minute)

```bash
# Navigate to project
cd /Users/les/Projects/mahavishnu

# Start all monitoring services
docker-compose -f monitoring/docker-compose.yml up -d

# Wait for services to be healthy
sleep 30

# Verify services are running
docker-compose -f monitoring/docker-compose.yml ps
```

**Expected output**:
```
NAME                STATUS              PORTS
prometheus          Up (healthy)        0.0.0.0:9090->9090/tcp
grafana             Up (healthy)        0.0.0.0:3000->3000/tcp
otel-collector      Up (healthy)        0.0.0.0:4317-4318->4317-4318/tcp
jaeger              Up (healthy)        0.0.0.0:16686->16686/tcp
```

**Troubleshooting**:
- If services don't start: `docker-compose -f monitoring/docker-compose.yml logs`
- If port conflicts: Edit `monitoring/docker-compose.yml` to change ports

---

### Step 2: Access Grafana (30 seconds)

1. Open browser: **http://localhost:3000**

2. Login with credentials:
   - Username: `admin`
   - Password: `admin`

3. Change password when prompted (choose a secure password)

---

### Step 3: View Dashboard (30 seconds)

Dashboards are automatically provisioned. Navigate to:

1. **Dashboards** → **Browse**
2. Find folder: **Mahavishnu**
3. Open dashboard: **MCP Ecosystem**

**Alternative**:
- Direct link: http://localhost:3000/d/mcp-ecosystem-overview/mcp-ecosystem

---

### Step 4: Verify Data (1 minute)

Check that dashboard shows data (not "No Data"):

1. **Check time range**: Top-right corner → Select "Last 15 minutes"
2. **Refresh**: Click refresh button (top-right)
3. **Verify panels**: Look for graphs with data

**If panels show "No Data"**:
```bash
# Verify Prometheus is scraping Mahavishnu
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="mahavishnu") | {health: .health}'

# Expected output:
# {"health": "up"}

# If health is "down", check Mahavishnu is running
mahavishnu mcp status
```

---

## Quick Start Option 2: Existing Grafana (2 minutes)

Use this if you already have Grafana and Prometheus running.

### Step 1: Add Prometheus Data Source (1 minute)

**Via Grafana UI**:

1. **Configuration** → **Data Sources** → **Add data source**
2. Select **Prometheus**
3. Configure:
   - **Name**: `Mahavishnu-Prometheus`
   - **URL**: `http://localhost:9090` (adjust if needed)
   - **Access**: Server (default)
4. Click **Save & Test**

**Expected**: "Data source is working" green message

---

### Step 2: Configure Prometheus (30 seconds)

Add Mahavishnu to `prometheus.yml`:

```yaml
# Add to scrape_configs section
scrape_configs:
  - job_name: 'mahavishnu'
    static_configs:
      - targets: ['host.docker.internal:8680']  # or 'localhost:8680'
    metrics_path: '/metrics'
    scrape_interval: 10s
```

Reload Prometheus:

```bash
# Reload config
curl -X POST http://localhost:9090/-/reload

# Verify
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="mahavishnu")'
```

---

### Step 3: Import Dashboard (30 seconds)

1. **Dashboards** → **Import**
2. Click **Upload JSON file**
3. Select: `/Users/les/Projects/mahavishnu/monitoring/dashboards/mcp_ecosystem.json`
4. Select data source: **Mahavishnu-Prometheus**
5. Click **Import**

**Done!** Dashboard should now display.

---

## Essential Commands

### Start/Stop Monitoring Stack

```bash
# Start all services
docker-compose -f monitoring/docker-compose.yml up -d

# Stop all services
docker-compose -f monitoring/docker-compose.yml down

# Restart specific service
docker-compose -f monitoring/docker-compose.yml restart grafana

# View logs
docker-compose -f monitoring/docker-compose.yml logs -f grafana

# Check service health
docker-compose -f monitoring/docker-compose.yml ps
```

---

### Verify Metrics

```bash
# Check Mahavishnu metrics endpoint
curl http://localhost:8680/metrics | grep mahavishnu

# Expected output:
# mahavishnu_workflows_executed_total{adapter="prefect",status="success"} 0
# mahavishnu_cpu_usage_percent 15.2
# ...

# Query Prometheus directly
curl 'http://localhost:9090/api/v1/query?query=up' | jq

# Check target health
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'
```

---

### Prometheus Queries

```bash
# All Mahavishnu workflows
curl 'http://localhost:9090/api/v1/query?query=mahavishnu_workflows_executed_total' | jq

# CPU usage
curl 'http://localhost:9090/api/v1/query?query=mahavishnu_cpu_usage_percent' | jq

# Request rate (last 5m)
curl 'http://localhost:9090/api/v1/query?query=rate(mahavishnu_workflows_executed_total[5m])' | jq

# Memory usage in GB
curl 'http://localhost:9090/api/v1/query?query=mahavishnu_memory_usage_bytes/1024/1024/1024' | jq
```

---

### Grafana API

```bash
# Set API key (from UI: Configuration → API Keys)
export GRAFANA_API_KEY="eyJrIjoi..."

# List all dashboards
curl -H "Authorization: Bearer $GRAFANA_API_KEY" \
  http://localhost:3000/api/search?query=&type=dash-db | jq

# Export dashboard by UID
curl -H "Authorization: Bearer $GRAFANA_API_KEY" \
  http://localhost:3000/api/dashboards/uid/mcp-ecosystem-overview | jq

# Check datasource health
curl -H "Authorization: Bearer $GRAFANA_API_KEY" \
  http://localhost:3000/api/datasources | jq '.[] | {name: .name, status: .isDefault}'
```

---

## Common Issues and Fixes

### Issue 1: Port Already in Use

**Symptoms**:
```
Error: bind: address already in use
```

**Fix**:
```bash
# Find process using port
lsof -i :3000

# Kill process (replace PID)
kill -9 <PID>

# Or change port in docker-compose.yml
grafana:
  ports:
    - "3030:3000"  # Use 3030 instead of 3000
```

---

### Issue 2: Dashboard Shows "No Data"

**Symptoms**: Panels are empty or show "No Data"

**Fix**:
```bash
# Step 1: Check Mahavishnu is running
mahavishnu mcp status

# Step 2: Verify metrics endpoint
curl http://localhost:8680/metrics

# Step 3: Check Prometheus is scraping
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="mahavishnu")'

# Step 4: Verify metrics in Prometheus
curl 'http://localhost:9090/api/v1/query?query=mahavishnu_workflows_executed_total' | jq

# Step 5: Wait for scrape interval (default: 15s)
sleep 20

# Step 6: Refresh dashboard
```

---

### Issue 3: Prometheus Can't Reach Mahavishnu

**Symptoms**: Target health shows "down" in Prometheus

**Fix**:
```bash
# Check if Mahavishnu is accessible from Docker container
docker exec prometheus wget -O- http://host.docker.internal:8680/metrics

# If fails, use actual IP address
# Find your IP
ipconfig getifaddr en0  # macOS
# or
hostname -I  # Linux

# Update prometheus.yml with actual IP
- job_name: 'mahavishnu'
  static_configs:
    - targets: ['192.168.1.100:8680']  # Use your IP

# Reload Prometheus
curl -X POST http://localhost:9090/-/reload
```

---

### Issue 4: Grafana Login Failed

**Symptoms**: Can't login with admin/admin

**Fix**:
```bash
# Reset admin password
docker-compose -f monitoring/docker-compose.yml exec grafana \
  grafana-cli admin reset-admin-password admin newpassword

# Or set specific password in docker-compose.yml
grafana:
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=your-secure-password
```

---

### Issue 5: Dashboard Queries Too Slow

**Symptoms**: Dashboard takes > 10s to load

**Fix**:
```bash
# Increase refresh interval
# Dashboard settings (gear icon) → Refresh → 30s or 1m

# Reduce time range
# Top-right corner → Select "Last 1 hour" instead of "Last 7 days"

# Check query performance
# Open panel → Query Inspector (top-right of panel)
# Look for: "Query execution time"
```

---

### Issue 6: Docker Out of Memory

**Symptoms**: Grafana/Prometheus containers crash

**Fix**:
```bash
# Increase Docker memory limit
# Docker Desktop → Settings → Resources → Memory → 8GB+

# Or add limits to docker-compose.yml
grafana:
  deploy:
    resources:
      limits:
        memory: 2G
      reservations:
        memory: 1G

prometheus:
  deploy:
    resources:
      limits:
        memory: 4G
      reservations:
        memory: 2G
```

---

## Quick Reference: Dashboard Panels

| Panel | Metric | Purpose |
|-------|--------|---------|
| Request Rate | `rate(mcp_http_requests_total[5m])` | Traffic volume |
| P95 Latency | `histogram_quantile(0.95, ...)` | Performance |
| Success Rate | `success/total * 100` | Reliability |
| Active Workers | `pool_workers_active` | Capacity |
| Memory Usage | `mahavishnu_memory_usage_bytes` | Resources |
| CPU Usage | `mahavishnu_cpu_usage_percent` | Resources |

---

## Quick Reference: Important URLs

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin/admin (change on first login) |
| Prometheus | http://localhost:9090 | None (public) |
| Jaeger (traces) | http://localhost:16686 | None (public) |
| Mahavishnu Metrics | http://localhost:8680/metrics | Requires auth (if configured) |

---

## Next Steps

After successful setup:

1. **Explore dashboards**: Browse all panels and filters
2. **Set up alerts**: Configure alert rules in Prometheus
3. **Customize queries**: Modify panels for your needs
4. **Add more metrics**: Instrument your code with custom metrics
5. **Read full guide**: See `docs/GRAFANA_DASHBOARD_GUIDE.md` for advanced features

---

## Quick Test Workflow

Verify entire stack in 30 seconds:

```bash
# 1. Check services
docker-compose -f monitoring/docker-compose.yml ps | grep "Up"

# 2. Check Prometheus targets
curl -s http://localhost:9090/api/v1/targets | jq -r '.data.activeTargets[] | select(.labels.job=="mahavishnu") | .health'

# 3. Check metrics
curl -s http://localhost:8680/metrics | grep -c "mahavishnu"

# 4. Check Grafana
curl -s http://localhost:3000/api/health | jq -r '.database'

# Expected outputs:
# 1. List of "Up" services
# 2. "up"
# 3. Number > 0
# 4. "ok"
```

If all checks pass, your monitoring stack is working!

---

## Need Help?

- **Full Documentation**: `/Users/les/Projects/mahavishnu/docs/GRAFANA_DASHBOARD_GUIDE.md`
- **Troubleshooting**: See Common Issues above
- **Logs**: `docker-compose -f monitoring/docker-compose.yml logs -f [service-name]`
- **Grafana Docs**: https://grafana.com/docs/
- **Prometheus Docs**: https://prometheus.io/docs/

---

## Checklist

Use this checklist to verify setup:

- [ ] Docker and Docker Compose installed
- [ ] Ports 3000, 9090 available
- [ ] Mahavishnu MCP server running
- [ ] Started monitoring stack: `docker-compose -f monitoring/docker-compose.yml up -d`
- [ ] Accessed Grafana: http://localhost:3000
- [ ] Logged in with admin/admin
- [ ] Found "MCP Ecosystem" dashboard
- [ ] Verified panels show data (not "No Data")
- [ ] Adjusted time range to "Last 15 minutes"
- [ ] Tested refresh button

**All checked?** Congratulations, you're monitoring! 🎉

---

**File**: `/Users/les/Projects/mahavishnu/docs/GRAFANA_QUICKSTART.md`
**Version**: 1.0.0
**Last Updated**: 2025-02-05
