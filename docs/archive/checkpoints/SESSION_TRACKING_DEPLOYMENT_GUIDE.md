# Session Tracking Deployment Guide

**Version**: 1.0.0
**Date**: 2026-02-06
**Status**: Production Ready
**Deployment Time**: < 30 minutes

---

## Table of Contents

1. [Pre-Deployment Checklist](#1-pre-deployment-checklist)
2. [Environment Configuration](#2-environment-configuration)
3. [Step-by-Step Deployment](#3-step-by-step-deployment)
4. [Verification Commands](#4-verification-commands)
5. [Monitoring Setup](#5-monitoring-setup)
6. [Troubleshooting Guide](#6-troubleshooting-guide)
7. [Rollback Plan](#7-rollback-plan)
8. [Production Runbook](#8-production-runbook)
9. [Architecture Reference](#9-architecture-reference)
10. [Appendix: Quick Reference Cards](#10-appendix-quick-reference-cards)

---

## 1. Pre-Deployment Checklist

### 1.1 System Requirements

- **Python**: 3.13+ (required for Session-Buddy)
- **Operating System**: Linux, macOS, or Windows with WSL2
- **Memory**: Minimum 2GB RAM (4GB recommended)
- **Disk**: 500MB free space for Session-Buddy database
- **Network**: Localhost access (127.0.0.1) for MCP server

### 1.2 Dependency Installation

**Install Mahavishnu**:
```bash
cd /path/to/mahavishnu
uv sync --group dev
# OR
pip install -e ".[dev]"
```

**Install Session-Buddy**:
```bash
cd /path/to/session-buddy
uv sync --group dev
# OR
pip install -e ".[dev]"
```

**Verify Installations**:
```bash
# Check Mahavishnu
mahavishnu --version

# Check Session-Buddy
session-buddy --help

# Check Python version
python --version  # Should be 3.13+
```

### 1.3 Security Configuration

**Generate JWT Secret** (Required):
```bash
# Generate secure 32-character secret
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Set Environment Variables**:
```bash
# Mahavishnu authentication (REQUIRED for production)
export MAHAVISHNU_AUTH_ENABLED=true
export MAHAVISHNU_AUTH_SECRET="<your-32-char-secret>"

# Session-Buddy secret (if using authentication)
export SESSION_BUDDY_SECRET="<your-32-char-secret>"
```

### 1.4 Integration Tests

**Run Mahavishnu Tests**:
```bash
cd /path/to/mahavishnu
pytest tests/unit/test_app.py -v
pytest tests/integration/test_session_tracking.py -v
```

**Run Session-Buddy Tests**:
```bash
cd /path/to/session-buddy
pytest tests/unit/test_session.py -v
pytest tests/integration/test_mcp_server.py -v
```

### 1.5 MCP Configuration

**Verify `.mcp.json` Configuration**:
```json
{
  "mcpServers": {
    "session-buddy": {
      "command": "python",
      "args": ["-m", "session_buddy.server"],
      "cwd": "/path/to/session-buddy",
      "env": {
        "PYTHONPATH": "/path/to/session-buddy",
        "SESSION_BUDDY_SECRET": "your-secret-here"
      }
    }
  }
}
```

### 1.6 Pre-Deployment Checklist

Use this checklist before deploying:

- [ ] Python 3.13+ installed
- [ ] Mahavishnu installed and tests passing
- [ ] Session-Buddy installed and tests passing
- [ ] JWT secret generated (32+ characters)
- [ ] `MAHAVISHNU_AUTH_ENABLED=true` set
- [ ] `MAHAVISHNU_AUTH_SECRET` set
- [ ] MCP server configured in `.mcp.json`
- [ ] Integration tests passing
- [ ] Monitoring configured (optional but recommended)
- [ ] Rollback plan reviewed
- [ ] Team notified of deployment

---

## 2. Environment Configuration

### 2.1 Required Environment Variables

**Mahavishnu Configuration**:
```bash
# Authentication (REQUIRED in production)
export MAHAVISHNU_AUTH_ENABLED=true
export MAHAVISHNU_AUTH_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

# Server configuration
export MAHAVISHNU_HOST="127.0.0.1"  # Local only for security
export MAHAVISHNU_PORT=3000

# Session tracking (auto-enabled via Oneiric)
export ONEIRIC_EVENT_BUFFER_ENABLED=true
export ONEIRIC_EVENT_BUFFER_MAX_SIZE=1000
```

**Session-Buddy Configuration**:
```bash
# Database location
export SESSION_BUDDY_DB_PATH="$HOME/.session-buddy/sessions.db"

# Optional: Authentication
export SESSION_BUDDY_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

# Optional: Semantic search
export SESSION_BUDDY_SEMANTIC_SEARCH=true
export SESSION_BUDDY_EMBEDDING_MODEL="all-MiniLM-L6-v2"
```

### 2.2 Optional Environment Variables

**Prometheus Metrics** (Optional):
```bash
export PROMETHEUS_METRICS_ENABLED=true
export PROMETHEUS_METRICS_PORT=9090
export PROMETHEUS_METRICS_PATH="/metrics"
```

**OpenTelemetry Tracing** (Optional):
```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
export OTEL_SERVICE_NAME="mahavishnu"
export OTEL_TRACES_EXPORTER="otlp"
```

**Debug Mode** (Development only):
```bash
export MAHAVISHNU_LOG_LEVEL="DEBUG"
export SESSION_BUDDY_LOG_LEVEL="DEBUG"
export MAHAVISHNU_DEBUG=true
```

### 2.3 Configuration Files

**Mahavishnu Configuration** (`settings/mahavishnu.yaml`):
```yaml
# Session management
session:
  enabled: true
  checkpoint_interval: 60  # seconds (10-600)

# Observability
observability:
  metrics_enabled: true
  tracing_enabled: true
  otlp_endpoint: "http://localhost:4317"

# Terminal management (for admin shells)
terminal:
  enabled: false  # Enable if using admin shells
  default_columns: 120
  default_rows: 40
```

**Session-Buddy Configuration** (`~/.session-buddy/config.yaml`):
```yaml
# Semantic search
semantic_search:
  enabled: true
  model: "all-MiniLM-L6-v2"
  similarity_threshold: 0.7

# Session tracking
session_tracking:
  auto_init: true  # Auto-initialize for git repos
  auto_cleanup: true  # Auto-cleanup on disconnect
```

### 2.4 Environment File Template

Create `.env` file for easy configuration:
```bash
# .env template for Mahavishnu + Session-Buddy

# Authentication (REQUIRED)
MAHAVISHNU_AUTH_ENABLED=true
MAHAVISHNU_AUTH_SECRET="change-me-in-production"
SESSION_BUDDY_SECRET="change-me-in-production"

# Servers
MAHAVISHNU_HOST="127.0.0.1"
MAHAVISHNU_PORT=3000
SESSION_BUDDY_HOST="127.0.0.1"
SESSION_BUDDY_PORT=8678

# Features
ONEIRIC_EVENT_BUFFER_ENABLED=true
PROMETHEUS_METRICS_ENABLED=true

# Paths
SESSION_BUDDY_DB_PATH="$HOME/.session-buddy/sessions.db"

# Logging
MAHAVISHNU_LOG_LEVEL="INFO"
SESSION_BUDDY_LOG_LEVEL="INFO"
```

Load environment variables:
```bash
source .env
# OR
export $(cat .env | xargs)
```

---

## 3. Step-by-Step Deployment

### Step 1: Install Dependencies

**1.1 Install System Dependencies**:
```bash
# On macOS
brew install python@3.13

# On Ubuntu/Debian
sudo apt update
sudo apt install python3.13 python3.13-venv

# On Windows (WSL2)
sudo apt update && sudo apt install python3.13 python3.13-venv
```

**1.2 Create Virtual Environments**:
```bash
# Mahavishnu virtual environment
cd /path/to/mahavishnu
python3.13 -m venv .venv
source .venv/bin/activate

# Session-Buddy virtual environment (if separate)
cd /path/to/session-buddy
python3.13 -m venv .venv
source .venv/bin/activate
```

**1.3 Install Python Packages**:
```bash
# Install Mahavishnu
cd /path/to/mahavishnu
source .venv/bin/activate
uv sync --group dev
# OR
pip install -e ".[dev]"

# Install Session-Buddy
cd /path/to/session-buddy
source .venv/bin/activate
uv sync --group dev
# OR
pip install -e ".[dev]"
```

### Step 2: Generate JWT Secrets

**2.1 Generate Secrets**:
```bash
# Generate Mahavishnu JWT secret
MAHAVISHNU_SECRET=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
echo "Mahavishnu Secret: $MAHAVISHNU_SECRET"

# Generate Session-Buddy JWT secret
SESSION_BUDDY_SECRET=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')
echo "Session-Buddy Secret: $SESSION_BUDDY_SECRET"
```

**2.2 Store Secrets Securely**:
```bash
# Add to .bashrc, .zshrc, or .env
echo "export MAHAVISHNU_AUTH_SECRET='$MAHAVISHNU_SECRET'" >> ~/.bashrc
echo "export SESSION_BUDDY_SECRET='$SESSION_BUDDY_SECRET'" >> ~/.bashrc

# Reload shell
source ~/.bashrc
```

**2.3 Verify Secrets**:
```bash
# Verify secrets are set
echo $MAHAVISHNU_AUTH_SECRET  # Should show 32-char string
echo $SESSION_BUDDY_SECRET    # Should show 32-char string

# Verify length (should be 43+ characters)
echo -n $MAHAVISHNU_AUTH_SECRET | wc -c
```

### Step 3: Start Session-Buddy MCP Server

**3.1 Test Session-Buddy CLI**:
```bash
session-buddy --help
session-buddy --version
```

**3.2 Start MCP Server** (Foreground for testing):
```bash
# Start in foreground
session-buddy mcp start

# Expected output:
# [INFO] Starting Session-Buddy MCP server on 127.0.0.1:8678
# [INFO] Session tracking enabled
# [INFO] Ready to accept connections
```

**3.3 Test MCP Server Health**:
```bash
# In another terminal
curl http://127.0.0.1:8678/health

# Expected output:
# {"status": "healthy", "version": "0.x.x"}
```

**3.4 Start MCP Server** (Background for production):
```bash
# Start with nohup
nohup session-buddy mcp start > /tmp/session-buddy.log 2>&1 &

# Save PID for later management
echo $! > /tmp/session-buddy.pid

# Verify it's running
ps aux | grep session-buddy
```

### Step 4: Test Session Tracking Integration

**4.1 Create Test Session**:
```bash
# Start Mahavishnu admin shell
mahavishnu shell

# In the shell, run:
ps()  # Show workflows (if any)
%repos  # List repositories
exit  # Exit shell
```

**4.2 Verify Session Captured**:
```bash
# Check Session-Buddy for captured session
session-buddy list-sessions --type admin_shell --limit 5

# Expected output:
# ┌────────────┬──────────────┬──────────┬─────────────┐
# │ Session ID │ Component    │ Duration │ Events      │
# ├────────────┼──────────────┼──────────┼─────────────┤
# │ abc123     │ mahavishnu   │ 0:02:15  │ 12          │
# └────────────┴──────────────┴──────────┴─────────────┘
```

**4.3 View Session Details**:
```bash
# Get session details
session-buddy get-session abc123

# View session events
session-buddy list-events --session-id abc123
```

### Step 5: Configure Monitoring (Optional)

**5.1 Enable Prometheus Metrics**:
```bash
# Set environment variables
export PROMETHEUS_METRICS_ENABLED=true
export PROMETHEUS_METRICS_PORT=9090

# Restart Mahavishnu with metrics
mahavishnu mcp start --metrics-enabled
```

**5.2 Test Metrics Endpoint**:
```bash
# Scrape metrics
curl http://127.0.0.1:9090/metrics

# Expected output:
# # HELP mahavishnu_sessions_total Total number of sessions
# # TYPE mahavishnu_sessions_total counter
# mahavishnu_sessions_total{component="mahavishnu"} 42
```

**5.3 Configure Prometheus Scrape** (Optional):
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'mahavishnu'
    static_configs:
      - targets: ['localhost:9090']
    scrape_interval: 15s
```

### Step 6: Deploy Admin Shells (Optional)

**6.1 Enable Terminal Management**:
```bash
# Edit settings/mahavishnu.yaml
terminal:
  enabled: true
  default_columns: 120
  default_rows: 40
```

**6.2 Start Admin Shell**:
```bash
mahavishnu shell

# In shell:
ps()          # Show workflows
top()         # Show active workflows
errors(10)    # Show recent errors
sync()        # Sync workflow state
%repos        # List repositories
exit          # Exit shell (session auto-captured)
```

**6.3 Verify Session Tracking**:
```bash
# Check that admin shell session was captured
session-buddy list-sessions --type admin_shell

# View session analytics
session-buddy analytics sessions
```

### Step 7: Production Hardening

**7.1 Enable Authentication**:
```bash
# Verify authentication is enabled
export MAHAVISHNU_AUTH_ENABLED=true
export MAHAVISHNU_AUTH_SECRET="your-secret"
export MAHAVISHNU_AUTH_ALGORITHM="HS256"
export MAHAVISHNU_AUTH_EXPIRE_MINUTES="60"
```

**7.2 Enable Secrets Rotation**:
```bash
# Set up automatic secret rotation
export MAHAVISHNU_SECRETS__ENABLED=true
export MAHAVISHNU_SECRETS__DEFAULT_PROVIDER="file"
export MAHAVISHNU_SECRETS__STORAGE_PATH="data/secrets"
export MAHAVISHNU_SECRETS__ROTATION_INTERVAL_DAYS="90"
```

**7.3 Enable Runtime Monitoring**:
```bash
# Enable Falco integration (Linux only)
export MAHAVISHNU_RUNTIME_MONITORING__ENABLED=true
export MAHAVISHNU_RUNTIME_MONITORING__FALCO_ENABLED=true
```

**7.4 Configure Rate Limiting**:
```bash
# Already enabled by default
# Review settings in mahavishnu.yaml
rate_limit:
  enabled: true
  user_requests_per_minute: 60
  ip_requests_per_minute: 30
  ip_ban_enabled: true
  ip_ban_threshold: 5
  ip_ban_duration: 300
```

---

## 4. Verification Commands

### 4.1 Health Checks

**Mahavishnu Health Check**:
```bash
# Check Mahavishnu MCP server
mahavishnu mcp health

# Expected output:
# ✓ Mahavishnu MCP server: healthy
# ✓ Authentication: enabled
# ✓ Session tracking: enabled
# ✓ Adapters: prefect (active), llamaindex (disabled), agno (active)
```

**Session-Buddy Health Check**:
```bash
# Check Session-Buddy MCP server
session-buddy health

# Expected output:
# ✓ Session-Buddy MCP server: healthy
# ✓ Database: connected
# ✓ Session tracking: enabled
# ✓ Semantic search: enabled
```

**Integration Health Check**:
```bash
# Test Mahavishnu → Session-Buddy connection
mahavishnu test-session-tracking

# Expected output:
# ✓ Session-Buddy MCP: connected
# ✓ Session tracking: operational
# ✓ Event capture: working
```

### 4.2 Functional Verification

**Test Session Creation**:
```bash
# Start admin shell
mahavishnu shell

# In shell, run command and exit
%repos
exit

# Verify session was created
session-buddy list-sessions --type admin_shell --limit 1
```

**Test Event Capture**:
```bash
# Start shell
mahavishnu shell

# Run multiple commands
ps()
top()
errors(5)
exit

# Check session events
SESSION_ID=$(session-buddy list-sessions --type admin_shell --limit 1 --format json | jq -r '.[0].session_id')
session-buddy list-events --session-id $SESSION_ID

# Expected: 4 events (start, ps, top, errors, exit)
```

**Test Metadata Capture**:
```bash
# Get session with metadata
session-buddy get-session $SESSION_ID --format json

# Check for:
# - component: "mahavishnu"
# - session_type: "admin_shell"
# - start_time, end_time
# - command_count
# - metadata.env, metadata.git_branch
```

### 4.3 Performance Verification

**Test Session Latency**:
```bash
# Time session creation
time mahavishnu shell -c "exit"

# Expected: < 1 second
```

**Test Query Performance**:
```bash
# Time session list query
time session-buddy list-sessions --limit 100

# Expected: < 500ms for 100 sessions
```

**Test Search Performance**:
```bash
# Time semantic search
time session-buddy search "workflow orchestration"

# Expected: < 200ms for semantic search
```

### 4.4 Integration Tests

**Run Mahavishnu Integration Tests**:
```bash
cd /path/to/mahavishnu
pytest tests/integration/test_session_tracking.py -v

# Expected: All tests passing
```

**Run Session-Buddy Integration Tests**:
```bash
cd /path/to/session-buddy
pytest tests/integration/test_admin_shell_tracking.py -v

# Expected: All tests passing
```

**End-to-End Test**:
```bash
# Complete workflow test
mahavishnu shell -c "ps(); top(); sync()" && \
session-buddy list-sessions --type admin_shell --limit 1 && \
echo "✓ E2E test passed"

# Expected: ✓ E2E test passed
```

### 4.5 Security Verification

**Test Authentication**:
```bash
# Test with valid token
TOKEN=$(mahavishnu generate-token)
mahavishnu list-repos --token $TOKEN

# Test without token (should fail)
mahavishnu list-repos  # Should return 401 Unauthorized

# Test with invalid token (should fail)
mahavishnu list-repos --token "invalid"  # Should return 401 Unauthorized
```

**Test Rate Limiting**:
```bash
# Make rapid requests (should trigger rate limit)
for i in {1..100}; do
  mahavishnu list-repos --token $TOKEN
done

# Expected: 429 Too Many Requests after threshold
```

**Test IP Ban**:
```bash
# Check IP ban status
mahavishnu rate-limit check-ip --ip 127.0.0.1

# Expected: not_banned (or banned if threshold exceeded)
```

---

## 5. Monitoring Setup

### 5.1 Prometheus Configuration

**Install Prometheus**:
```bash
# On macOS
brew install prometheus

# On Ubuntu/Debian
sudo apt install prometheus

# Start Prometheus
prometheus --config.file=prometheus.yml
```

**Configure Prometheus Scrape** (`prometheus.yml`):
```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'mahavishnu'
    static_configs:
      - targets: ['localhost:9090']
    metrics_path: '/metrics'

  - job_name: 'session_buddy'
    static_configs:
      - targets: ['localhost:8678']]
    metrics_path: '/metrics'
```

**Verify Metrics**:
```bash
# Query Prometheus
curl http://localhost:9090/api/v1/query?query=mahavishnu_sessions_total

# Expected output with session count
```

### 5.2 Grafana Dashboard

**Install Grafana**:
```bash
# On macOS
brew install grafana

# On Ubuntu/Debian
sudo apt install grafana

# Start Grafana
sudo systemctl start grafana
```

**Import Dashboard**:
1. Open Grafana: http://localhost:3000
2. Navigate to Dashboards → Import
3. Use Dashboard ID: `mahavishnu-session-tracking` (create from JSON below)

**Dashboard JSON** (`grafana-dashboard.json`):
```json
{
  "dashboard": {
    "title": "Mahavishnu Session Tracking",
    "panels": [
      {
        "title": "Total Sessions",
        "targets": [
          {
            "expr": "mahavishnu_sessions_total"
          }
        ]
      },
      {
        "title": "Session Duration",
        "targets": [
          {
            "expr": "mahavishnu_session_duration_seconds"
          }
        ]
      },
      {
        "title": "Active Sessions",
        "targets": [
          {
            "expr": "mahavishnu_sessions_active"
          }
        ]
      }
    ]
  }
}
```

### 5.3 Alert Rules

**Configure Alerts** (`alerts.yml`):
```yaml
groups:
  - name: mahavishnu_alerts
    rules:
      - alert: HighSessionFailureRate
        expr: |
          rate(mahavishnu_sessions_failed_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High session failure rate"
          description: "Session failure rate is {{ $value }} errors/sec"

      - alert: SessionTrackingDown
        expr: |
          up{job="session_buddy"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Session tracking down"
          description: "Session-Buddy MCP server is down"

      - alert: TooManyActiveSessions
        expr: |
          mahavishnu_sessions_active > 100
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Too many active sessions"
          description: "{{ $value }} active sessions (threshold: 100)"
```

**Load Alert Rules**:
```bash
# Add to prometheus.yml
rule_files:
  - 'alerts.yml'

# Reload Prometheus
kill -HUP $(pidof prometheus)
```

### 5.4 Log Aggregation

**Configure Structlog** (already enabled):
```python
# Mahavishnu log configuration
import structlog

logger = structlog.get_logger(__name__)
logger.info("session_started", session_id="abc123", component="mahavishnu")
```

**View Logs**:
```bash
# View Mahavishnu logs
tail -f /var/log/mahavishnu/mahavishnu.log

# View Session-Buddy logs
tail -f ~/.session-buddy/logs/session-buddy.log

# Filter by session
grep "session_id=abc123" /var/log/mahavishnu/mahavishnu.log
```

---

## 6. Troubleshooting Guide

### 6.1 Common Issues and Solutions

**Issue 1: Sessions Not Being Captured**

**Symptoms**:
- Admin shell sessions not appearing in Session-Buddy
- `session-buddy list-sessions` returns empty list

**Diagnosis**:
```bash
# Check Session-Buddy MCP server status
session-buddy health

# Check Mahavishnu session tracking config
mahavishnu config | grep session

# Check if MCP server is running
ps aux | grep session-buddy
```

**Solutions**:
1. **Session-Buddy MCP not running**:
   ```bash
   # Start Session-Buddy MCP server
   session-buddy mcp start

   # Or start in background
   nohup session-buddy mcp start > /tmp/session-buddy.log 2>&1 &
   ```

2. **Session tracking disabled**:
   ```bash
   # Enable session tracking
   export ONEIRIC_EVENT_BUFFER_ENABLED=true
   export MAHAVISHNU_SESSION_ENABLED=true
   ```

3. **MCP configuration incorrect**:
   ```bash
   # Verify .mcp.json configuration
   cat ~/.claude/.mcp.json | grep session-buddy

   # Should have correct cwd and PYTHONPATH
   ```

**Issue 2: Authentication Failures**

**Symptoms**:
- `401 Unauthorized` errors
- "Invalid token" messages

**Diagnosis**:
```bash
# Check if authentication is enabled
mahavishnu config | grep auth_enabled

# Check JWT secret is set
echo $MAHAVISHNU_AUTH_SECRET | wc -c  # Should be 43+

# Test token generation
mahavishnu generate-token
```

**Solutions**:
1. **Generate new JWT secret**:
   ```bash
   # Generate new secret
   export MAHAVISHNU_AUTH_SECRET=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')

   # Add to .bashrc
   echo "export MAHAVISHNU_AUTH_SECRET='$MAHAVISHNU_AUTH_SECRET'" >> ~/.bashrc
   source ~/.bashrc
   ```

2. **Enable authentication**:
   ```bash
   export MAHAVISHNU_AUTH_ENABLED=true
   ```

3. **Regenerate token**:
   ```bash
   # Generate new token
   TOKEN=$(mahavishnu generate-token)

   # Use token
   mahavishnu list-repos --token $TOKEN
   ```

**Issue 3: MCP Server Connection Refused**

**Symptoms**:
- "Connection refused" errors
- MCP tools not available

**Diagnosis**:
```bash
# Check if MCP server is running
ps aux | grep session-buddy
netstat -an | grep 8678  # Should show LISTEN

# Check MCP server logs
tail -f /tmp/session-buddy.log
```

**Solutions**:
1. **Start MCP server**:
   ```bash
   session-buddy mcp start

   # Or in background
   nohup session-buddy mcp start > /tmp/session-buddy.log 2>&1 &
   ```

2. **Check port conflicts**:
   ```bash
   # Check if port is in use
   lsof -i :8678

   # Kill conflicting process
   kill -9 $(lsof -ti :8678)

   # Restart MCP server
   session-buddy mcp start
   ```

3. **Verify firewall**:
   ```bash
   # Allow localhost (should be allowed by default)
   sudo iptables -A INPUT -p tcp --dport 8678 -s 127.0.0.1 -j ACCEPT
   ```

**Issue 4: Slow Session Queries**

**Symptoms**:
- `session-buddy list-sessions` takes > 1 second
- UI is sluggish

**Diagnosis**:
```bash
# Check database size
ls -lh ~/.session-buddy/sessions.db

# Check query performance
time session-buddy list-sessions --limit 100
```

**Solutions**:
1. **Vacuum database**:
   ```bash
   # Open SQLite database
   sqlite3 ~/.session-buddy/sessions.db

   # Vacuum and reindex
   sqlite> VACUUM;
   sqlite> REINDEX;
   sqlite> .quit
   ```

2. **Archive old sessions**:
   ```bash
   # Archive sessions older than 30 days
   session-buddy archive-sessions --days 30

   # This moves old sessions to archive table
   ```

3. **Increase cache**:
   ```bash
   export SESSION_BUDDY_CACHE_SIZE=10000
   ```

**Issue 5: Semantic Search Not Working**

**Symptoms**:
- Semantic search returns no results
- "Model not found" errors

**Diagnosis**:
```bash
# Check if semantic search is enabled
session-buddy config | grep semantic

# Check if model is downloaded
ls -lh ~/.session-buddy/models/
```

**Solutions**:
1. **Download semantic model**:
   ```bash
   python /path/to/session-buddy/scripts/download_embedding_model.py

   # Model will be downloaded to ~/.session-buddy/models/
   ```

2. **Enable semantic search**:
   ```bash
   export SESSION_BUDDY_SEMANTIC_SEARCH=true
   ```

3. **Use text search** (fallback):
   ```bash
   # Use text search instead
   session-buddy search "workflow orchestration" --search-type text
   ```

### 6.2 Debug Commands

**Enable Debug Logging**:
```bash
# Enable verbose logging
export MAHAVISHNU_LOG_LEVEL="DEBUG"
export SESSION_BUDDY_LOG_LEVEL="DEBUG"

# Restart servers
mahavishnu mcp restart
session-buddy mcp restart
```

**Trace Session Lifecycle**:
```bash
# Enable session tracing
export MAHAVISHNU_TRACE_SESSIONS=true

# Start shell and exit
mahavishnu shell -c "exit"

# Check logs for trace
grep "TRACE" /var/log/mahavishnu/mahavishnu.log
```

**Database Inspection**:
```bash
# Open Session-Buddy database
sqlite3 ~/.session-buddy/sessions.db

# List tables
.tables

# Inspect sessions
SELECT * FROM sessions ORDER BY start_time DESC LIMIT 5;

# Inspect events
SELECT * FROM session_events WHERE session_id = 'abc123';

# Check indexes
.indices

# .quit
```

**MCP Tool Testing**:
```bash
# Test MCP tool directly
mahavishnu mcp call-tool list_sessions

# Test with arguments
mahavishnu mcp call-tool list_sessions '{"limit": 5, "session_type": "admin_shell"}'
```

### 6.3 Error Messages Reference

| Error Message | Cause | Solution |
|--------------|-------|----------|
| `401 Unauthorized` | Missing or invalid JWT token | Generate new token with `mahavishnu generate-token` |
| `Connection refused` | MCP server not running | Start with `session-buddy mcp start` |
| `Database locked` | Another process using database | Wait or restart Session-Buddy |
| `Invalid session ID` | Session not found | Verify session ID with `list-sessions` |
| `Rate limit exceeded` | Too many requests | Wait or configure higher limits |
| `IP banned` | Too many violations | Wait or unban with `rate-limit unban-ip` |

---

## 7. Rollback Plan

### 7.1 Disabling Session Tracking

**Quick Disable** (without restart):
```bash
# Disable session tracking temporarily
export MAHAVISHNU_SESSION_ENABLED=false

# Continue working (sessions won't be tracked)
mahavishnu shell
```

**Complete Disable** (requires restart):
```bash
# Stop MCP server
session-buddy mcp stop

# Disable in configuration
# Edit settings/mahavishnu.yaml:
# session:
#   enabled: false

# Restart Mahavishnu
mahavishnu mcp start
```

### 7.2 Reverting to Previous Version

**Using Git**:
```bash
# Checkout previous version
cd /path/to/mahavishnu
git log --oneline -10  # Find commit hash
git checkout <previous-commit-hash>

# Reinstall
pip install -e ".[dev]"

# Restart services
mahavishnu mcp restart
```

**Using Backup**:
```bash
# Restore from backup
cd /path/to/mahavishnu
cp -r backup/mahavishnu-2025-02-05/* .

# Reinstall
pip install -e ".[dev]"

# Restart services
mahavishnu mcp restart
```

### 7.3 Data Backup Procedures

**Backup Session-Buddy Database**:
```bash
# Create backup directory
mkdir -p ~/.session-buddy/backups

# Backup database
cp ~/.session-buddy/sessions.db ~/.session-buddy/backups/sessions-$(date +%Y%m%d-%H%M%S).db

# Optional: Compress
gzip ~/.session-buddy/backups/sessions-$(date +%Y%m%d-%H%M%S).db
```

**Automated Backup Script** (`backup-sessions.sh`):
```bash
#!/bin/bash
# Backup Session-Buddy database

BACKUP_DIR="$HOME/.session-buddy/backups"
DB_PATH="$HOME/.session-buddy/sessions.db"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

mkdir -p "$BACKUP_DIR"
cp "$DB_PATH" "$BACKUP_DIR/sessions-$TIMESTAMP.db"
gzip "$BACKUP_DIR/sessions-$TIMESTAMP.db"

# Keep last 30 days of backups
find "$BACKUP_DIR" -name "sessions-*.db.gz" -mtime +30 -delete

echo "Backup created: sessions-$TIMESTAMP.db.gz"
```

**Schedule Automatic Backups** (cron):
```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * /path/to/backup-sessions.sh
```

### 7.4 Disaster Recovery

**Restore from Backup**:
```bash
# Stop services
session-buddy mcp stop
mahavishnu mcp stop

# Restore database
gunzip ~/.session-buddy/backups/sessions-20250205-020000.db.gz
cp ~/.session-buddy/backups/sessions-20250205-020000.db ~/.session-buddy/sessions.db

# Start services
session-buddy mcp start
mahavishnu mcp start

# Verify
session-buddy list-sessions --limit 5
```

**Complete Reinstall**:
```bash
# Stop all services
session-buddy mcp stop
mahavishnu mcp stop

# Uninstall
pip uninstall mahavishnu session-buddy

# Reinstall
cd /path/to/mahavishnu
pip install -e ".[dev]"

cd /path/to/session-buddy
pip install -e ".[dev]"

# Restore database
cp ~/.session-buddy/backups/sessions-latest.db ~/.session-buddy/sessions.db

# Start services
session-buddy mcp start
mahavishnu mcp start
```

---

## 8. Production Runbook

### 8.1 Daily Operations

**Morning Checks**:
```bash
# Check service health
mahavishnu mcp health
session-buddy health

# Check active sessions
session-buddy list-sessions --status active

# Check error rate
mahavishnu logs --level ERROR --since 24h

# Check disk space
df -h ~/.session-buddy/
```

**Weekly Maintenance**:
```bash
# Backup database
backup-sessions.sh

# Archive old sessions
session-buddy archive-sessions --days 30

# Vacuum database
sqlite3 ~/.session-buddy/sessions.db "VACUUM;"

# Review metrics
mahavishnu metrics --range 7d
```

**Monthly Review**:
```bash
# Review session analytics
session-buddy analytics sessions --range 30d

# Review security logs
mahavishnu audit-log --range 30d

# Review rate limiting
mahavishnu rate-limit stats --range 30d

# Generate report
mahavishnu report --range 30d --output report.html
```

### 8.2 Monitoring Checks

**Health Check Script** (`health-check.sh`):
```bash
#!/bin/bash
# Health check for Mahavishnu + Session-Buddy

echo "=== Mahavishnu Health Check ==="
mahavishnu mcp health

echo ""
echo "=== Session-Buddy Health Check ==="
session-buddy health

echo ""
echo "=== MCP Server Status ==="
ps aux | grep -E "mahavishnu|mcp" | grep -v grep

echo ""
echo "=== Disk Space ==="
df -h ~/.session-buddy/

echo ""
echo "=== Recent Errors ==="
mahavishnu logs --level ERROR --limit 10
```

**Schedule Health Checks** (cron):
```bash
# Run every 5 minutes
*/5 * * * * /path/to/health-check.sh > /var/log/mahavishnu/health.log 2>&1
```

### 8.3 Incident Response

**Incident: Session Tracking Down**

**Severity**: P1 - Critical

**Detection**:
```bash
# Alert triggered
session-buddy health
# Returns: unhealthy
```

**Response**:
1. **Verify incident**:
   ```bash
   session-buddy health
   ps aux | grep session-buddy
   ```

2. **Restart service**:
   ```bash
   session-buddy mcp restart

   # Check logs
   tail -f ~/.session-buddy/logs/session-buddy.log
   ```

3. **Verify recovery**:
   ```bash
   session-buddy health
   session-buddy list-sessions --limit 1
   ```

4. **Post-incident review**:
   - Check logs for root cause
   - Document incident
   - Create action item to prevent recurrence

**Incident: High Session Failure Rate**

**Severity**: P2 - High

**Detection**:
```bash
# Alert: failure rate > 10%
mahavishnu metrics --metric session_failure_rate
```

**Response**:
1. **Verify incident**:
   ```bash
   mahavishnu logs --level ERROR --since 1h
   ```

2. **Identify pattern**:
   ```bash
   # Check for common errors
   mahavishnu logs --grep "ConnectionRefusedError" --since 1h
   mahavishnu logs --grep "TimeoutError" --since 1h
   ```

3. **Mitigation**:
   - If database issue: restart Session-Buddy
   - If network issue: check connectivity
   - If resource issue: scale up resources

4. **Verify recovery**:
   ```bash
   mahavishnu metrics --metric session_failure_rate
   # Should be < 1%
   ```

**Incident: IP Ban False Positives**

**Severity**: P3 - Medium

**Detection**:
```bash
# Legitimate user IP banned
mahavishnu rate-limit check-ip --ip 192.168.1.100
# Returns: banned
```

**Response**:
1. **Verify IP**:
   ```bash
   # Check ban history
   mahavishnu rate-limit ban-history --ip 192.168.1.100
   ```

2. **Unban IP**:
   ```bash
   mahavishnu rate-limit unban-ip --ip 192.168.1.100
   ```

3. **Add to exemption list**:
   ```bash
   # Edit settings/mahavishnu.yaml
   rate_limit:
     exempt_ips:
       - "192.168.1.100"
   ```

4. **Monitor**:
   ```bash
   # Watch for recurrence
   mahavishnu rate-limit stats --ip 192.168.1.100
   ```

### 8.4 On-Call Procedures

**Escalation Matrix**:
| Severity | Response Time | Escalation |
|----------|---------------|------------|
| P1 - Critical | 15 minutes | On-call engineer → Engineering manager → CTO |
| P2 - High | 1 hour | On-call engineer → Engineering manager |
| P3 - Medium | 4 hours | On-call engineer (next business day) |
| P4 - Low | 1 week | Backlog grooming |

**On-Call Checklist**:
- [ ] PagerDuty/alert received
- [ ] Acknowledge alert
- [ ] Verify incident (health checks)
- [ ] Create incident channel (Slack)
- [ ] Document incident (Google Doc)
- [ ] Implement fix
- [ ] Verify recovery
- [ ] Post-mortem (within 5 business days)

---

## 9. Architecture Reference

### 9.1 System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Mahavishnu CLI                      │
│                  (Orchestrator Interface)               │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐      ┌──────────────┐               │
│  │ Typer CLI    │      │ IPython      │               │
│  │ (Automation) │      │ Admin Shell  │               │
│  └──────┬───────┘      └──────┬───────┘               │
│         │                     │                        │
│         └──────────┬──────────┘                        │
│                    │                                   │
│         ┌──────────▼──────────┐                        │
│         │  MahavishnuApp      │                        │
│         │  (Core Logic)       │                        │
│         └──────────┬──────────┘                        │
│                    │                                   │
│  ┌─────────────────┼─────────────────┐                │
│  │                 │                 │                │
│ ▼▼▼               ▼▼▼               ▼▼▼               │
│ ┌─────┐        ┌──────┐        ┌────────┐            │
│ │Pool │        │Worker│        │Adapter │            │
│ │Mgr  │        │Mgr   │        │Factory │            │
│ └──┬──┘        └───┬──┘        └────┬───┘            │
│    │               │                │                 │
└────┼───────────────┼────────────────┼─────────────────┘
     │               │                │
     │               │                │
     └───────────────┴────────────────┘
                     │
         ┌───────────▼────────────┐
         │ SessionEventEmitter    │
         │ (Oneiric Integration)  │
         └───────────┬────────────┘
                     │
         ┌───────────▼────────────┐
         │ Session-Buddy MCP      │
         │ (Session Manager)      │
         └───────────┬────────────┘
                     │
         ┌───────────▼────────────┐
         │ SQLite Database        │
         │ (~/.session-buddy/)    │
         └────────────────────────┘
```

### 9.2 Data Flow

**Session Creation Flow**:
```
1. User runs: mahavishnu shell
   ↓
2. MahavishnuShell.__init__() called
   ↓
3. SessionEventEmitter.session_started() emitted
   ↓
4. Oneiric buffers event
   ↓
5. Event sent to Session-Buddy MCP
   ↓
6. Session record created in SQLite
   ↓
7. Session ID returned to Mahavishnu
   ↓
8. Shell starts with session_id attached
```

**Event Capture Flow**:
```
1. User runs command in shell (e.g., ps())
   ↓
2. Command executed
   ↓
3. SessionEventEmitter.command_executed() emitted
   ↓
4. Event buffered (batching for performance)
   ↓
5. Batch sent to Session-Buddy MCP
   ↓
6. Event records created in session_events table
   ↓
7. Metadata captured (timestamp, exit_code, etc.)
```

**Session Cleanup Flow**:
```
1. User exits shell (exit or Ctrl+D)
   ↓
2. MahavishnuShell cleanup triggered
   ↓
3. SessionEventEmitter.session_ended() emitted
   ↓
4. Final stats captured (duration, command_count)
   ↓
5. Session record updated in Session-Buddy
   ↓
6. Shell exits
   ↓
7. Session complete and queryable
```

### 9.3 Database Schema

**Session Table**:
```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    component TEXT NOT NULL,  -- 'mahavishnu'
    session_type TEXT NOT NULL,  -- 'admin_shell'
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_seconds REAL,
    command_count INTEGER DEFAULT 0,
    metadata TEXT,  -- JSON-encoded metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Session Events Table**:
```sql
CREATE TABLE session_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- 'command', 'error', 'checkpoint'
    timestamp TIMESTAMP NOT NULL,
    data TEXT,  -- JSON-encoded event data
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);
CREATE INDEX idx_session_events_session_id ON session_events(session_id);
```

### 9.4 MCP Tools

**Session Tracking Tools** (exposed by Session-Buddy):
```python
@mcp.tool()
async def list_sessions(
    limit: int = 100,
    offset: int = 0,
    session_type: str | None = None,
    component: str = "mahavishnu",
) -> list[dict]:
    """List sessions with filtering."""

@mcp.tool()
async def get_session(session_id: str) -> dict:
    """Get session details."""

@mcp.tool()
async def list_events(session_id: str) -> list[dict]:
    """List events for a session."""

@mcp.tool()
async def analytics_sessions(
    range_days: int = 7,
) -> dict:
    """Get session analytics."""
```

### 9.5 Configuration Reference

**Mahavishnu Settings** (`settings/mahavishnu.yaml`):
```yaml
# Session management
session:
  enabled: true
  checkpoint_interval: 60  # seconds (10-600)

# Observability
observability:
  metrics_enabled: true
  tracing_enabled: true
  otlp_endpoint: "http://localhost:4317"

# Terminal management (for admin shells)
terminal:
  enabled: false  # Enable if using admin shells
  adapter_preference: "auto"  # auto, iterm2, mcpretentious
```

**Oneiric Settings** (global, affects all components):
```yaml
# Event buffering (for session tracking)
event_buffer:
  enabled: true
  max_size: 1000
  flush_interval: 5  # seconds
```

---

## 10. Appendix: Quick Reference Cards

### 10.1 Commands Quick Reference

**Mahavishnu Commands**:
```bash
# Admin shell
mahavishnu shell                    # Start IPython admin shell

# MCP server
mahavishnu mcp start                # Start MCP server
mahavishnu mcp stop                 # Stop MCP server
mahavishnu mcp restart              # Restart MCP server
mahavishnu mcp health               # Health check

# Session tracking
mahavishnu test-session-tracking    # Test integration
mahavishnu sessions                 # List local sessions
```

**Session-Buddy Commands**:
```bash
# MCP server
session-buddy mcp start             # Start MCP server
session-buddy mcp stop              # Stop MCP server
session-buddy health                # Health check

# Sessions
session-buddy list-sessions         # List all sessions
session-buddy get-session <id>      # Get session details
session-buddy analytics sessions    # Session analytics

# Events
session-buddy list-events           # List events
session-buddy list-events --session-id <id>  # Events for session
```

### 10.2 Environment Variables Quick Reference

**Required**:
```bash
MAHAVISHNU_AUTH_ENABLED=true
MAHAVISHNU_AUTH_SECRET="<32-char-secret>"
```

**Optional (Recommended)**:
```bash
# Session tracking
ONEIRIC_EVENT_BUFFER_ENABLED=true
ONEIRIC_EVENT_BUFFER_MAX_SIZE=1000

# Metrics
PROMETHEUS_METRICS_ENABLED=true
PROMETHEUS_METRICS_PORT=9090

# Tracing
OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"
OTEL_SERVICE_NAME="mahavishnu"
```

**Debug**:
```bash
MAHAVISHNU_LOG_LEVEL="DEBUG"
SESSION_BUDDY_LOG_LEVEL="DEBUG"
MAHAVISHNU_DEBUG=true
```

### 10.3 Troubleshooting Quick Reference

| Problem | Command | Solution |
|---------|---------|----------|
| Sessions not captured | `session-buddy health` | Start MCP server |
| Auth failures | `echo $MAHAVISHNU_AUTH_SECRET \| wc -c` | Generate new secret |
| Connection refused | `ps aux \| grep session-buddy` | Start Session-Buddy |
| Slow queries | `time session-buddy list-sessions` | Vacuum database |
| Search not working | `ls ~/.session-buddy/models/` | Download model |

### 10.4 Monitoring Quick Reference

**Prometheus Queries**:
```promql
# Total sessions
mahavishnu_sessions_total

# Active sessions
mahavishnu_sessions_active

# Session duration (p95)
histogram_quantile(0.95, mahavishnu_session_duration_seconds)

# Session failure rate
rate(mahavishnu_sessions_failed_total[5m])
```

**Grafana Panels**:
```json
{
  "title": "Total Sessions",
  "targets": [{"expr": "mahavishnu_sessions_total"}]
}
```

### 10.5 Deployment Timeline

**30-Minute Deployment**:
| Time | Task | Command |
|------|------|---------|
| 0-5 min | Install dependencies | `pip install -e ".[dev]"` |
| 5-10 min | Generate JWT secret | `python -c 'import secrets; print(secrets.token_urlsafe(32))'` |
| 10-15 min | Configure environment | Edit `.env` file |
| 15-20 min | Start Session-Buddy | `session-buddy mcp start` |
| 20-25 min | Verify integration | `mahavishnu test-session-tracking` |
| 25-30 min | Test admin shell | `mahavishnu shell` |

**Verification**:
```bash
# Complete verification in < 5 minutes
mahavishnu mcp health && \
session-buddy health && \
mahavishnu test-session-tracking && \
echo "✓ Deployment verified"
```

---

## Additional Resources

- **Mahavishnu Documentation**: `/Users/les/Projects/mahavishnu/docs/`
- **Session-Buddy Documentation**: `/Users/les/Projects/session-buddy/docs/`
- **Oneiric Documentation**: `/Users/les/Projects/oneiric/docs/`
- **Architecture Decisions**: `/Users/les/Projects/mahavishnu/docs/adr/`
- **Security Checklist**: `/Users/les/Projects/mahavishnu/SECURITY_CHECKLIST.md`

---

**Deployment Guide Version**: 1.0.0
**Last Updated**: 2026-02-06
**Maintained By**: Mahavishnu Development Team
**Support**: Create GitHub issue for questions or problems

---

## Success Criteria

Your deployment is successful when:

- [ ] All pre-deployment checks passed
- [ ] JWT secret generated and configured
- [ ] Session-Buddy MCP server running
- [ ] Mahavishnu admin shell starts without errors
- [ ] Sessions are captured in Session-Buddy
- [ ] Health checks return "healthy"
- [ ] Metrics are being collected (if enabled)
- [ ] Monitoring alerts configured (if enabled)
- [ ] Rollback plan documented and tested
- [ ] Team trained on runbook procedures

**Estimated Time to Production**: < 30 minutes
**Maintenance Overhead**: < 1 hour/week
**Monitoring Overhead**: < 30 minutes/day

---

**End of Deployment Guide**
