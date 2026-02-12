# WebSocket Production Deployment Guide

**Version:** 0.2.0
**Last Updated:** 2025-02-11
**Status:** Production Ready

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Environment Variables](#2-environment-variables)
3. [Deployment Architecture](#3-deployment-architecture)
4. [TLS/WSS Configuration](#4-tlswss-configuration)
5. [Nginx Reverse Proxy Configuration](#5-nginx-reverse-proxy-configuration)
6. [Health Check Procedures](#6-health-check-procedures)
7. [Prometheus Metrics Integration](#7-prometheus-metrics-integration)
8. [Grafana Dashboard Setup](#8-grafana-dashboard-setup)
9. [Security Hardening Checklist](#9-security-hardening-checklist)
10. [Troubleshooting Common Issues](#10-troubleshooting-common-issues)
11. [Rollback Procedures](#11-rollback-procedures)

---

## 1. Prerequisites

### 1.1 System Requirements

| Component | Minimum Version | Recommended Version |
|-----------|----------------|-------------------|
| **Python** | 3.11+ | 3.13+ |
| **Redis** | 7.0+ | 7.2+ |
| **Nginx** | 1.18+ | 1.25+ |
| **Prometheus** | 2.45+ | 2.50+ |
| **Grafana** | 10.0+ | 10.3+ |
| **Operating System** | Linux (Ubuntu 22.04+, RHEL 9+) | Ubuntu 22.04 LTS |

### 1.2 Python Dependencies

Install required packages:

```bash
# Core dependencies
pip install mahavishnu[dev] mcp-common

# WebSocket support
pip install websockets aiohttp

# TLS and security
pip install cryptography pyopenssl

# Metrics and monitoring
pip install prometheus-client

# Authentication
pip install pyjwt
```

### 1.3 System Dependencies

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y \
    python3.13 \
    python3-pip \
    nginx \
    redis-server \
    prometheus \
    grafana

# RHEL/CentOS
sudo dnf install -y \
    python3.13 \
    python3-pip \
    nginx \
    redis \
    prometheus \
    grafana
```

### 1.4 Network Requirements

| Port | Service | Protocol | Purpose |
|------|---------|----------|---------|
| 8686 | Mahavishnu WebSocket | WS/WSS | Primary WebSocket port |
| 9090 | Prometheus Metrics | HTTP | Metrics scraping |
| 6379 | Redis | TCP | Message queue/state |
| 80 | Nginx (HTTP) | HTTP | Redirect to HTTPS |
| 443 | Nginx (HTTPS) | HTTPS | TLS termination |

**Firewall Configuration:**

```bash
# Allow HTTP/HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Allow metrics scraping (internal only)
sudo ufw allow from 10.0.0.0/8 to any port 9090

# Allow Redis (internal only)
sudo ufw allow from 10.0.0.0/8 to any port 6379
```

---

## 2. Environment Variables

### 2.1 Required Variables

Create `/etc/mahavishnu/production.env`:

```bash
# =============================================================================
# Mahavishnu WebSocket Production Configuration
# =============================================================================

# Server Configuration
MAHAVISHNU_HOST=0.0.0.0
MAHAVISHNU_PORT=8686
MAHAVISHNU_SERVER_NAME=mahavishnu-production

# =============================================================================
# TLS/WSS Configuration
# =============================================================================

# Enable TLS (required for production)
MAHAVISHNU_TLS_ENABLED=true

# Certificate paths (absolute paths)
MAHAVISHNU_CERT_FILE=/etc/ssl/certs/mahavishnu.pem
MAHAVISHNU_KEY_FILE=/etc/ssl/private/mahavishnu-key.pem

# Optional: Client certificate verification
MAHAVISHNU_CA_FILE=/etc/ssl/certs/ca-bundle.crt
MAHAVISHNU_VERIFY_CLIENT=false

# =============================================================================
# JWT Authentication
# =============================================================================

# Enable authentication (required for production)
MAHAVISHNU_AUTH_ENABLED=true

# JWT secret (generate with: openssl rand -base64 32)
MAHAVISHNU_JWT_SECRET=your-generated-secret-key-here

# JWT token expiry (seconds)
MAHAVISHNU_JWT_EXPIRY=3600

# =============================================================================
# Prometheus Metrics
# =============================================================================

# Enable metrics collection
MAHAVISHNU_METRICS_ENABLED=true
MAHAVISHNU_METRICS_PORT=9090

# =============================================================================
# Redis Configuration
# =============================================================================

MAHAVISHNU_REDIS_HOST=localhost
MAHAVISHNU_REDIS_PORT=6379
MAHAVISHNU_REDIS_DB=0
MAHAVISHNU_REDIS_PASSWORD=your-redis-password-here

# =============================================================================
# Security Settings
# =============================================================================

# Rate limiting (requests per minute)
MAHAVISHNU_RATE_LIMIT=100

# Connection limits
MAHAVISHNU_MAX_CONNECTIONS=10000
MAHAVISHNU_CONNECTION_TIMEOUT=300

# =============================================================================
# Logging
# =============================================================================

MAHAVISHNU_LOG_LEVEL=INFO
MAHAVISHNU_LOG_FORMAT=json

# =============================================================================
# Observability
# =============================================================================

# OpenTelemetry (optional)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=mahavishnu-websocket
```

### 2.2 Generating Secrets

```bash
# Generate JWT secret
JWT_SECRET=$(openssl rand -base64 32)
echo "MAHAVISHNU_JWT_SECRET=$JWT_SECRET"

# Generate Redis password
REDIS_PASSWORD=$(openssl rand -base64 24)
echo "MAHAVISHNU_REDIS_PASSWORD=$REDIS_PASSWORD"
```

### 2.3 Variable Reference

All variables use the `MAHAVISHNU_` prefix:

```python
from mahavishnu.core.config import MahavishnuSettings

# Load from environment
settings = MahavishnuSettings()

# Access configuration
print(f"TLS Enabled: {settings.tls_enabled}")
print(f"JWT Secret: {settings.jwt_secret}")
```

---

## 3. Deployment Architecture

### 3.1 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Internet                                │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      Nginx Reverse Proxy                         │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  TLS Termination (Port 443)                               │  │
│  │  WebSocket Upgrade Headers                                  │  │
│  │  Rate Limiting                                             │  │
│  │  Static File Serving                                        │  │
│  └─────────────────────────────────────────────────────────────┘  │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
                    ▼                   ▼
        ┌───────────────────┐   ┌───────────────────┐
        │   Mahavishnu     │   │   Metrics        │
        │   WebSocket      │   │   Server         │
        │   Port 8686     │   │   Port 9090      │
        │                   │   │                   │
        │  ┌───────────┐   │   │  /metrics        │
        │  │  TLS/WSS │   │   │                 │
        │  │  Auth    │   │   └───────────────────┘
        │  │  Pool    │   │           │
        │  │  Manager │   │           │
        │  └───────────┘   │           │
        └─────────┬─────────┘           │
                  │                     │
                  ▼                     ▼
        ┌──────────────────────────────────────────┐
        │           Redis (Port 6379)            │
        │  - Message Queue                       │
        │  - State Management                   │
        │  - Pub/Sub                           │
        │  - Connection Tracking                │
        └──────────────────────────────────────────┘
                          │
                          ▼
        ┌──────────────────────────────────────────┐
        │       Prometheus (Port 9091)            │
        │  - Metrics Scrape                      │
        │  - Time Series DB                     │
        └──────────────────────────────────────────┘
                          │
                          ▼
        ┌──────────────────────────────────────────┐
        │       Grafana (Port 3000)              │
        │  - Dashboard                          │
        │  - Alerting                           │
        └──────────────────────────────────────────┘
```

### 3.2 Deployment Topology

**Single Region Deployment:**

```
                    ┌─────────────────┐
                    │   Load Balancer │
                    │   (AWS ELB/    │
                    │    GCP LB)     │
                    └────────┬────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
    ┌───────▼───────┐ ┌────▼─────┐ ┌─────▼──────┐
    │ Mahavishnu-1  │ │Mahavishnu-2│ │Mahavishnu-3│
    │   (Primary)   │ │ (Standby) │ │ (Standby)  │
    └───────┬───────┘ └────┬─────┘ └─────┬──────┘
            │               │              │
            └───────────────┴──────────────┘
                            │
                    ┌───────▼────────┐
                    │ Redis Cluster  │
                    │  (Primary/     │
                    │   Replicas)    │
                    └────────────────┘
```

### 3.3 Service Dependencies

```
Mahavishnu WebSocket
├── Nginx (reverse proxy)
│   └── TLS termination
├── Redis (state management)
│   ├── Connection tracking
│   ├── Pub/Sub messaging
│   └── Session storage
├── Prometheus (metrics)
│   └── Scrapes :9090/metrics
└── Grafana (visualization)
    └── Queries Prometheus
```

---

## 4. TLS/WSS Configuration

### 4.1 Using Production Certificates

The TLS configuration is handled by `mcp_common.websocket.tls` module.

**Server initialization with TLS:**

```python
from mahavishnu.websocket.server import MahavishnuWebSocketServer
from mcp_common.websocket.tls import create_ssl_context

# Create SSL context
ssl_context = create_ssl_context(
    cert_file="/etc/ssl/certs/mahavishnu.pem",
    key_file="/etc/ssl/private/mahavishnu-key.pem",
    ca_file="/etc/ssl/certs/ca-bundle.crt",  # Optional
    verify_client=False,
)

# Initialize server
server = MahavishnuWebSocketServer(
    pool_manager=pool_mgr,
    host="0.0.0.0",
    port=8686,
    ssl_context=ssl_context,
    enable_metrics=True,
    metrics_port=9090,
)
```

### 4.2 Certificate Formats

**PEM Format (Recommended):**

```bash
# Certificate file (/etc/ssl/certs/mahavishnu.pem)
-----BEGIN CERTIFICATE-----
MIIFXzCCA0egAwIBAgIUH5Eq9b3...
-----END CERTIFICATE-----

# Private key file (/etc/ssl/private/mahavishnu-key.pem)
-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC...
-----END PRIVATE KEY-----
```

### 4.3 Certificate Validation

Use the built-in certificate validator:

```python
from mcp_common.websocket.tls import validate_certificate

result = validate_certificate(
    cert_file="/etc/ssl/certs/mahavishnu.pem",
    check_expiry=True,
    min_days_remaining=30,
)

if not result["valid"]:
    print(f"Certificate invalid: {result['error']}")
    exit(1)

if result["expiring_soon"]:
    print(f"WARNING: {result['error']}")
```

**Command-line validation:**

```bash
# Check certificate expiry
openssl x509 -in /etc/ssl/certs/mahavishnu.pem -noout -dates

# Verify certificate and key match
openssl x509 -noout -modulus -in /etc/ssl/certs/mahavishnu.pem | openssl md5
openssl rsa -noout -modulus -in /etc/ssl/private/mahavishnu-key.pem | openssl md5

# Test TLS connection
openssl s_client -connect localhost:8686 -servername mahavishnu.example.com
```

### 4.4 Development Certificates (Testing Only)

```python
from mcp_common.websocket.tls import create_development_ssl_context

# Auto-generate self-signed certificate
ssl_context, cert_path, key_path = create_development_ssl_context(
    common_name="localhost",
    dns_names=["localhost", "127.0.0.1"],
)

server = MahavishnuWebSocketServer(
    pool_manager=pool_mgr,
    ssl_context=ssl_context,
)
```

### 4.5 Environment-Based Configuration

```python
from mcp_common.websocket.tls import get_tls_config_from_env

# Load TLS config from environment
tls_config = get_tls_config_from_env("MAHAVISHNU")

if tls_config["tls_enabled"]:
    ssl_context = create_ssl_context(
        cert_file=tls_config["cert_file"],
        key_file=tls_config["key_file"],
        ca_file=tls_config["ca_file"],
        verify_client=tls_config["verify_client"],
    )
```

---

## 5. Nginx Reverse Proxy Configuration

### 5.1 Complete Nginx Configuration

Create `/etc/nginx/sites-available/mahavishnu-websocket`:

```nginx
# =============================================================================
# Mahavishnu WebSocket Production Configuration
# =============================================================================

# Upstream WebSocket servers
upstream mahavishnu_websocket_backend {
    # Load balancing algorithm (least_conn recommended for WebSockets)
    least_conn;

    # Backend servers
    server 127.0.0.1:8686 max_fails=3 fail_timeout=30s;
    # Add more servers for HA deployment
    # server 10.0.1.11:8686 max_fails=3 fail_timeout=30s;
    # server 10.0.1.12:8686 max_fails=3 fail_timeout=30s;

    # Keepalive connections
    keepalive 64;
    keepalive_timeout 300s;
    keepalive_requests 10000;
}

# Rate limiting zone
limit_req_zone $binary_remote_addr zone=mahavishnu_limit:10m rate=100r/m;
limit_conn_zone $binary_remote_addr zone=mahavishnu_conn:10m;

# HTTP to HTTPS redirect
server {
    listen 80;
    listen [::]:80;
    server_name mahavishnu.example.com;

    # Allow health checks without redirecting
    location /health {
        proxy_pass http://mahavishnu_websocket_backend;
        access_log off;
    }

    # Redirect all other traffic to HTTPS
    location / {
        return 301 https://$server_name$request_uri;
    }
}

# HTTPS WebSocket server
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name mahavishnu.example.com;

    # =============================================================================
    # TLS Configuration
    # =============================================================================

    # Certificate paths
    ssl_certificate /etc/ssl/certs/mahavishnu.pem;
    ssl_certificate_key /etc/ssl/private/mahavishnu-key.pem;

    # SSL protocols
    ssl_protocols TLSv1.2 TLSv1.3;

    # SSL ciphers (Mozilla Intermediate configuration)
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384';

    # Prefer server ciphers
    ssl_prefer_server_ciphers off;

    # SSL session configuration
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # OCSP stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/ssl/certs/ca-bundle.crt;

    # =============================================================================
    # Security Headers
    # =============================================================================

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;

    # =============================================================================
    # Logging
    # =============================================================================

    access_log /var/log/nginx/mahavishnu-access.log;
    error_log /var/log/nginx/mahavishnu-error.log warn;

    # =============================================================================
    # WebSocket Endpoint
    # =============================================================================

    location / {
        # Rate limiting
        limit_req zone=mahavishnu_limit burst=20 nodelay;
        limit_conn mahavishnu_conn 10;

        # WebSocket upgrade headers (REQUIRED)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Forward headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;

        # Timeouts (important for long-lived connections)
        proxy_connect_timeout 60s;
        proxy_send_timeout 3600s;
        proxy_read_timeout 3600s;

        # Buffering (disable for WebSockets)
        proxy_buffering off;
        proxy_request_buffering off;

        # Backend configuration
        proxy_pass http://mahavishnu_websocket_backend;

        # Keepalive
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # Disable redirect handling
        proxy_redirect off;
    }

    # =============================================================================
    # Health Check Endpoint (no auth required)
    # =============================================================================

    location /health {
        proxy_pass http://mahavishnu_websocket_backend/health;
        access_log off;
        proxy_connect_timeout 5s;
        proxy_send_timeout 5s;
        proxy_read_timeout 5s;
    }

    # =============================================================================
    # Metrics Endpoint (restrict to internal networks)
    # =============================================================================

    location /metrics {
        # Only allow from internal networks
        allow 10.0.0.0/8;
        allow 172.16.0.0/12;
        allow 192.168.0.0/16;
        deny all;

        # Prometheus scraping
        proxy_pass http://127.0.0.1:9090/metrics;
        access_log off;
    }

    # =============================================================================
    # Static Assets (optional)
    # =============================================================================

    location /static/ {
        alias /var/www/mahavishnu/static/;
        expires 1d;
        add_header Cache-Control "public, immutable";
    }

    # =============================================================================
    # Deny access to sensitive files
    # =============================================================================

    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }
}
```

### 5.2 Enable Configuration

```bash
# Create symlink to enable site
sudo ln -s /etc/nginx/sites-available/mahavishnu-websocket \
           /etc/nginx/sites-enabled/mahavishnu-websocket

# Test configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

### 5.3 WebSocket Upgrade Headers

**Critical headers for WebSocket connections:**

```nginx
# Required WebSocket headers
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";

# Disable buffering (required for real-time communication)
proxy_buffering off;
proxy_request_buffering off;
```

### 5.4 Nginx Tuning for WebSockets

Edit `/etc/nginx/nginx.conf`:

```nginx
user www-data;
worker_processes auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 10000;
    use epoll;
    multi_accept on;
}

http {
    # Basic settings
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;

    # WebSocket limits
    map $http_upgrade $connection_upgrade {
        default upgrade;
        '' close;
    }

    # Logging
    log_format websocket '$remote_addr - $remote_user [$time_local] '
                       '"$request" $status $body_bytes_sent '
                       '"$http_referer" "$http_user_agent" '
                       'upgrade=$http_upgrade connection=$connection_upgrade';

    # Include sites
    include /etc/nginx/sites-enabled/*;
}
```

---

## 6. Health Check Procedures

### 6.1 Health Check Endpoint

The health check endpoint is available at `/health`:

```python
# Built-in health check
GET /health HTTP/1.1
Host: mahavishnu.example.com

# Response (200 OK)
{
    "status": "healthy",
    "server": "mahavishnu-production",
    "timestamp": "2025-02-11T10:30:00Z",
    "checks": {
        "websocket": "passing",
        "redis": "passing",
        "pools": "passing",
        "metrics": "passing"
    },
    "metrics": {
        "active_connections": 42,
        "total_connections": 1583,
        "uptime_seconds": 86400
    }
}
```

### 6.2 Health Check Scripts

Create `/usr/local/bin/check-mahavishnu-health.sh`:

```bash
#!/usr/bin/env bash
# Mahavishnu WebSocket Health Check Script

set -euo pipefail

HEALTH_URL="${HEALTH_URL:-http://localhost:8686/health}"
TIMEOUT="${HEALTH_TIMEOUT:-5}"
EXPECTED_STATUS="${EXPECTED_STATUS:-200}"

# Perform health check
response=$(curl -s -o /dev/null -w "%{http_code}" \
    --max-time "$TIMEOUT" \
    "$HEALTH_URL" 2>/dev/null || echo "000")

# Check response
if [ "$response" = "$EXPECTED_STATUS" ]; then
    echo "✓ Health check passed (HTTP $response)"
    exit 0
else
    echo "✗ Health check failed (HTTP $response, expected $EXPECTED_STATUS)"
    exit 1
fi
```

**Make executable:**

```bash
sudo chmod +x /usr/local/bin/check-mahavishnu-health.sh
```

### 6.3 Monitoring Health with Cron

```bash
# Add to crontab
*/5 * * * * /usr/local/bin/check-mahavishnu-health.sh >> /var/log/mahavishnu-health.log 2>&1
```

### 6.4 Load Balancer Health Checks

**For AWS ELB/ALB:**

```json
{
    "TargetGroupAttributes": [
        {
            "Key": "health_check_path",
            "Value": "/health"
        },
        {
            "Key": "health_check_interval_seconds",
            "Value": "30"
        },
        {
            "Key": "health_check_timeout_seconds",
            "Value": "5"
        },
        {
            "Key": "healthy_threshold_count",
            "Value": "2"
        },
        {
            "Key": "unhealthy_threshold_count",
            "Value": "3"
        },
        {
            "Key": "health_check_protocol",
            "Value": "HTTP"
        }
    ]
}
```

**For HAProxy:**

```
backend mahavishnu_websocket
    balance leastconn
    option httpchk GET /health
    http-check expect status 200
    default-server inter 2s rise 2 fall 3
    server web1 10.0.1.10:8686 check
    server web2 10.0.1.11:8686 check backup
```

---

## 7. Prometheus Metrics Integration

### 7.1 Prometheus Configuration

Create `/etc/prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    cluster: 'mahavishnu-production'
    replica: '1'

# AlertManager configuration (optional)
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - localhost:9093

# Rule files
rule_files:
  - 'alerts/mahavishnu.yml'

# Scrape configurations
scrape_configs:
  # Mahavishnu WebSocket metrics
  - job_name: 'mahavishnu_websocket'
    static_configs:
      - targets:
          - localhost:9090
        labels:
          service: 'mahavishnu-websocket'
          env: 'production'

  # Additional WebSocket services
  - job_name: 'websocket_services'
    static_configs:
      - targets:
          - localhost:9091  # Crackerjack
          - localhost:9096  # Fastblocks
          - localhost:9097  # Excalidraw
          - localhost:9098  # Dhruva
        labels:
          env: 'production'

  # Nginx metrics (with nginx-prometheus-exporter)
  - job_name: 'nginx'
    static_configs:
      - targets:
          - localhost:9113
        labels:
          service: 'nginx'
```

### 7.2 Metrics Available

The following metrics are exposed on port 9090:

| Metric Name | Type | Labels | Description |
|------------|------|--------|-------------|
| `websocket_connections_total` | Counter | server, tls_mode | Total connections |
| `websocket_connections_active` | Gauge | server | Current connections |
| `websocket_messages_total` | Counter | server, message_type, direction | Total messages |
| `websocket_broadcast_total` | Counter | server, channel | Total broadcasts |
| `websocket_broadcast_duration_seconds` | Histogram | server, channel | Broadcast latency |
| `websocket_connection_errors_total` | Counter | server, error_type | Connection errors |
| `websocket_message_errors_total` | Counter | server, error_type | Message errors |
| `websocket_latency_seconds` | Histogram | server, message_type | Processing latency |

### 7.3 Test Metrics Endpoint

```bash
# Scrape metrics
curl http://localhost:9090/metrics

# Expected output
# HELP websocket_connections_total Total number of WebSocket connections established
# TYPE websocket_connections_total counter
websocket_connections_total{server="mahavishnu",tls_mode="wss"} 1583

# HELP websocket_connections_active Current number of active WebSocket connections
# TYPE websocket_connections_active gauge
websocket_connections_active{server="mahavishnu"} 42
```

### 7.4 Alert Rules

Create `/etc/prometheus/alerts/mahavishnu.yml`:

```yaml
groups:
  - name: mahavishnu_websocket_alerts
    interval: 30s
    rules:
      # High connection count
      - alert: HighConnectionCount
        expr: websocket_connections_active{server="mahavishnu"} > 10000
        for: 5m
        labels:
          severity: warning
          service: mahavishnu-websocket
        annotations:
          summary: "High number of WebSocket connections"
          description: "{{ $value }} connections on {{ $labels.server }}"

      # Connection errors
      - alert: HighConnectionErrorRate
        expr: rate(websocket_connection_errors_total[5m]) > 10
        for: 5m
        labels:
          severity: critical
          service: mahavishnu-websocket
        annotations:
          summary: "High WebSocket connection error rate"
          description: "{{ $value }} errors/sec on {{ $labels.server }}"

      # Message errors
      - alert: HighMessageErrorRate
        expr: rate(websocket_message_errors_total[5m]) > 50
        for: 5m
        labels:
          severity: warning
          service: mahavishnu-websocket
        annotations:
          summary: "High WebSocket message error rate"
          description: "{{ $value }} errors/sec on {{ $labels.server }}"

      # High latency
      - alert: HighMessageLatency
        expr: histogram_quantile(0.95, websocket_latency_seconds) > 1.0
        for: 10m
        labels:
          severity: warning
          service: mahavishnu-websocket
        annotations:
          summary: "High WebSocket message latency (P95)"
          description: "{{ $value }}s latency on {{ $labels.server }}"

      # Server down
      - alert: WebSocketServerDown
        expr: up{job="mahavishnu_websocket"} == 0
        for: 1m
        labels:
          severity: critical
          service: mahavishnu-websocket
        annotations:
          summary: "WebSocket server is down"
          description: "Server {{ $labels.instance }} is not responding"
```

---

## 8. Grafana Dashboard Setup

### 8.1 Import Dashboard

The dashboard JSON is available at `/docs/grafana/WebSocket_Monitoring.json`.

**Steps to import:**

1. Open Grafana: `http://your-grafana:3000`
2. Navigate to **Dashboards** -> **Import**
3. Upload `WebSocket_Monitoring.json` or paste JSON
4. Select data source: `Prometheus`
5. Click **Import**

### 8.2 Configure Data Source

1. Go to **Configuration** -> **Data Sources**
2. Add **Prometheus** data source
3. Configure:

```yaml
Name: Prometheus
Type: Prometheus
URL: http://localhost:9090
Access: Server (default)
Basic Auth: Disabled
```

4. Click **Save & Test**

### 8.3 Dashboard Variables

The dashboard includes the following variables:

| Variable | Type | Description |
|----------|------|-------------|
| `Server` | Multi-select | Filter by server name |
| `Interval` | Interval | Time range for queries |

### 8.4 Dashboard Panels

1. **Active Connections** - Real-time connection count
2. **Message Rate (Sent)** - Messages sent per second
3. **Message Rate (Received)** - Messages received per second
4. **Broadcast Rate** - Broadcast operations per second
5. **Broadcast Latency** - P50, P95, P99 percentiles
6. **Message Latency** - Processing latency by type
7. **Connection Error Rate** - Errors by type
8. **Message Error Rate** - Processing errors

### 8.5 Set Up Alerts

1. Click on any panel
2. Select **Set alert rule**
3. Configure alert conditions
4. Set notification channel

---

## 9. Security Hardening Checklist

### 9.1 Pre-Deployment Security

- [ ] **TLS/WSS Enabled**: All WebSocket connections use WSS
- [ ] **Valid Certificates**: Production certificates from trusted CA
- [ ] **Certificate Expiry**: Certificates valid for >30 days
- [ ] **Strong Cipher Suites**: Only TLS 1.2+ with secure ciphers
- [ ] **JWT Authentication**: Authentication enabled with strong secret
- [ ] **JWT Secret**: Generated with `openssl rand -base64 32`
- [ ] **Rate Limiting**: Configured (100 req/min per IP)
- [ ] **Connection Limits**: Max connections configured
- [ ] **Firewall Rules**: Only necessary ports exposed
- [ ] **Nginx Headers**: Security headers configured

### 9.2 Network Security

```bash
# Check listening ports
sudo netstat -tlnp | grep mahavishnu

# Expected output
tcp  0  0  0.0.0.0:8686  0.0.0.0:*  LISTEN  12345/python
tcp  0  0  0.0.0.0:9090  0.0.0.0:*  LISTEN  12345/python
```

### 9.3 JWT Security

**Token generation example:**

```python
import jwt
import time

# Generate token with proper claims
payload = {
    "user_id": "user123",
    "permissions": ["read", "write"],
    "iat": int(time.time()),
    "exp": int(time.time()) + 3600,  # 1 hour
    "nbf": int(time.time()),
}

token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
```

**Token validation:**

```python
try:
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    print(f"User: {payload['user_id']}")
except jwt.ExpiredSignatureError:
    print("Token expired")
except jwt.InvalidTokenError:
    print("Invalid token")
```

### 9.4 Rate Limiting Configuration

```python
# In server configuration
from starlette.middleware.rate_limit import RateLimiter

# Apply rate limiting
app.add_middleware(
    RateLimiter,
    times=100,  # 100 requests
    seconds=60,  # per 60 seconds
)
```

### 9.5 DDoS Protection

**Nginx configuration:**

```nginx
# Limit connections per IP
limit_conn_zone $binary_remote_addr zone=addr:10m;

limit_conn addr 10;

# Rate limiting
limit_req_zone $binary_remote_addr zone=one:10m rate=10r/s;

limit_req zone=one burst=20 nodelay;
```

### 9.6 Security Headers

Verify headers with:

```bash
curl -I https://mahavishnu.example.com

# Expected headers
Strict-Transport-Security: max-age=31536000
X-Frame-Options: SAMEORIGIN
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
```

---

## 10. Troubleshooting Common Issues

### 10.1 Connection Issues

**Problem: Clients cannot connect**

```bash
# Check if server is listening
sudo netstat -tlnp | grep 8686

# Check firewall rules
sudo ufw status

# Check Nginx is proxying
sudo nginx -t && sudo systemctl status nginx

# Test from localhost
curl -v http://localhost:8686/health

# Test through Nginx
curl -v https://mahavishnu.example.com/health
```

### 10.2 TLS Certificate Errors

**Problem: Certificate validation fails**

```bash
# Check certificate dates
openssl x509 -in /etc/ssl/certs/mahavishnu.pem -noout -dates

# Verify certificate chain
openssl s_client -connect mahavishnu.example.com:443 -showcerts

# Check if certificate and key match
diff \
    <(openssl x509 -noout -modulus -in /etc/ssl/certs/mahavishnu.pem | openssl md5) \
    <(openssl rsa -noout -modulus -in /etc/ssl/private/mahavishnu-key.pem | openssl md5)

# Check file permissions
ls -la /etc/ssl/certs/mahavishnu.pem
ls -la /etc/ssl/private/mahavishnu-key.pem
```

### 10.3 WebSocket Upgrade Failures

**Problem: WebSocket handshake fails**

Check Nginx headers:

```nginx
# Verify these headers are present
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
proxy_http_version 1.1;
```

Test with `wscat`:

```bash
# Test WS connection
wscat -c "ws://localhost:8686"

# Test WSS connection
wscat -c "wss://mahavishnu.example.com" --no-check

# With authentication
wscat -c "wss://mahavishnu.example.com" \
    -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### 10.4 High Memory Usage

**Problem: Memory usage grows over time**

```bash
# Monitor connections
curl http://localhost:9090/metrics | grep websocket_connections_active

# Check for connection leaks
watch -n 5 'curl -s http://localhost:9090/metrics | grep connections_active'

# Restart server (graceful)
systemctl reload mahavishnu-websocket
```

### 10.5 Metrics Not Available

**Problem: Prometheus cannot scrape metrics**

```bash
# Check metrics port is listening
sudo netstat -tlnp | grep 9090

# Test metrics endpoint
curl http://localhost:9090/metrics

# Check Prometheus logs
sudo journalctl -u prometheus -f

# Verify Prometheus configuration
sudo promtool check config /etc/prometheus/prometheus.yml
```

### 10.6 Redis Connection Issues

**Problem: Cannot connect to Redis**

```bash
# Check Redis is running
sudo systemctl status redis-server

# Test connection
redis-cli ping

# Check Redis logs
sudo journalctl -u redis-server -f

# Monitor Redis connections
redis-cli info clients
```

---

## 11. Rollback Procedures

### 11.1 Service Rollback

**Quick rollback to previous version:**

```bash
# Stop current service
sudo systemctl stop mahavishnu-websocket

# Restore previous binary
sudo cp /opt/mahavishnu/bin/mahavishnu.previous \
        /opt/mahavishnu/bin/mahavishnu

# Restart service
sudo systemctl start mahavishnu-websocket

# Verify health
/usr/local/bin/check-mahavishnu-health.sh
```

### 11.2 Configuration Rollback

```bash
# List previous configurations
ls -lth /etc/mahavishnu/config.*

# Restore previous config
sudo cp /etc/mahavishnu/config.20250210 \
        /etc/mahavishnu/production.env

# Reload service
sudo systemctl reload mahavishnu-websocket
```

### 11.3 Database Migration Rollback

```bash
# Run down migrations
mahavishnu migrate down

# Verify database state
mahavishnu migrate status

# Restart service
sudo systemctl restart mahavishnu-websocket
```

### 11.4 Full System Rollback

**Using systemd snapshot:**

```bash
# Create snapshot before upgrade
sudo systemd-run --unit=mahavishnu-backup \
    /bin/bash -c "systemctl snapshot mahavishnu-websocket"

# Restore from snapshot
sudo systemctl revert mahavishnu-backup
```

**Using Docker (if containerized):**

```bash
# List previous images
docker images | grep mahavishnu

# Stop current container
docker stop mahavishnu-websocket

# Start previous version
docker run -d \
    --name mahavishnu-websocket \
    --network host \
    mahavishnu:v0.1.9
```

### 11.5 Rollback Verification

```bash
# Health check
curl -f http://localhost:8686/health || exit 1

# Metrics endpoint
curl -f http://localhost:9090/metrics || exit 1

# WebSocket connection test
wscat -c "ws://localhost:8686" --connect-timeout 5
```

---

## Appendix

### A. Systemd Service File

Create `/etc/systemd/system/mahavishnu-websocket.service`:

```ini
[Unit]
Description=Mahavishnu WebSocket Server
After=network.target redis.service
Wants=redis.service

[Service]
Type=exec
User=mahavishnu
Group=mahavishnu
WorkingDirectory=/opt/mahavishnu
Environment="PYTHONUNBUFFERED=1"
EnvironmentFile=/etc/mahavishnu/production.env

# Main service
ExecStart=/opt/mahavishnu/bin/mahavishnu websocket start

# Reload configuration
ExecReload=/bin/kill -HUP $MAINPID

# Graceful shutdown
ExecStop=/opt/mahavishnu/bin/mahavishnu websocket stop

# Restart policy
Restart=always
RestartSec=10
StartLimitInterval=60
StartLimitBurst=3

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/mahavishnu /var/lib/mahavishnu

# Resource limits
LimitNOFILE=65536
LimitNPROC=4096

# Logging
StandardOutput=append:/var/log/mahavishnu/websocket.log
StandardError=append:/var/log/mahavishnu/websocket-error.log

[Install]
WantedBy=multi-user.target
```

**Enable and start service:**

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service
sudo systemctl enable mahavishnu-websocket

# Start service
sudo systemctl start mahavishnu-websocket

# Check status
sudo systemctl status mahavishnu-websocket
```

### B. Log Rotation

Create `/etc/logrotate.d/mahavishnu`:

```
/var/log/mahavishnu/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 mahavishnu mahavishnu
    sharedscripts
    postrotate
        systemctl reload mahavishnu-websocket > /dev/null 2>&1 || true
    endscript
}
```

### C. Quick Reference

| Command | Purpose |
|---------|---------|
| `sudo systemctl start mahavishnu-websocket` | Start service |
| `sudo systemctl stop mahavishnu-websocket` | Stop service |
| `sudo systemctl restart mahavishnu-websocket` | Restart service |
| `sudo systemctl reload mahavishnu-websocket` | Reload config |
| `sudo systemctl status mahavishnu-websocket` | Check status |
| `journalctl -u mahavishnu-websocket -f` | View logs |
| `curl http://localhost:8686/health` | Health check |
| `curl http://localhost:9090/metrics` | View metrics |
| `wscat -c "ws://localhost:8686"` | Test WebSocket |

---

## Support and Documentation

- **Project Documentation:** `/docs`
- **API Reference:** `/docs/WEBSOCKET_API_REFERENCE.md`
- **Implementation Guide:** `/docs/WEBSOCKET_INTEGRATION_COMPLETE.md`
- **Grafana Dashboard:** `/docs/grafana/WebSocket_Monitoring.json`

---

**Document Version:** 1.0.0
**Last Updated:** 2025-02-11
**Maintained By:** Mahavishnu Development Team
