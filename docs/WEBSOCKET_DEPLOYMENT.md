# WebSocket Production Deployment Guide

**Last Updated:** 2026-02-11
**Status:** Production Ready
**Version:** 1.0.0

---

## Executive Summary

This guide provides comprehensive instructions for deploying and maintaining WebSocket servers across the 7-service Bodhisattva ecosystem in production environments. It covers prerequisites, security hardening, performance tuning, high availability, monitoring, and troubleshooting.

### Service Inventory

| Service | WebSocket Port | HTTP Port | Purpose | Status |
|---------|---------------|-----------|---------|--------|
| **session-buddy** | 8765 | 8678 | Session management | Production Ready |
| **mahavishnu** | 8690 | 8680 | Orchestration | Production Ready |
| **crackerjack** | 8686 | 8676 | Quality control | Production Ready |
| **akosha** | 8692 | 8682 | Analytics | Production Ready |
| **dhruva** | 8693 | 8683 | Adapter distribution | Production Ready |
| **excalidraw-mcp** | 3042 | 3032 | Diagram collaboration | Production Ready |
| **fastblocks** | 8684 | - | UI updates | Production Ready |

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Environment Setup](#environment-setup)
3. [Certificate Management](#certificate-management)
4. [Service Configuration](#service-configuration)
5. [Security Hardening](#security-hardening)
6. [Deployment Steps](#deployment-steps)
7. [Docker Deployment](#docker-deployment)
8. [Kubernetes Deployment](#kubernetes-deployment)
9. [Performance Tuning](#performance-tuning)
10. [High Availability](#high-availability)
11. [Monitoring & Alerting](#monitoring--alerting)
12. [Backup & Recovery](#backup--recovery)
13. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### System Requirements

**Hardware:**
- CPU: 4+ cores recommended
- RAM: 8GB minimum, 16GB recommended for production
- Storage: 50GB+ for logs and metrics

**Software:**
```bash
# Python version
Python 3.11+   # Required for all services

# OpenSSL for certificates
OpenSSL 3.0+   # For TLS certificate generation

# System packages
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y \
    python3.11 \
    python3.11-venv \
    openssl \
    nginx \
    redis-server \
    git

# macOS
brew install python@3.11 openssl redis nginx
```

### Network Requirements

**Port Allocation:**
- WebSocket ports: 8600-8800 range (8684, 8686, 8690, 8692, 8693, 8765, 3042)
- HTTP ports: 8600-8800 range (8678, 8680, 8682, 8683, 8676, 3032)
- Metrics ports: 9090-9099 (Prometheus metrics)

**Firewall Configuration:**
```bash
# Allow WebSocket ports (adjust for your security requirements)
sudo ufw allow 8684/tcp  # fastblocks
sudo ufw allow 8686/tcp  # crackerjack
sudo ufw allow 8690/tcp  # mahavishnu
sudo ufw allow 8692/tcp  # akosha
sudo ufw allow 8693/tcp  # dhruva
sudo ufw allow 8765/tcp  # session-buddy
sudo ufw allow 3042/tcp  # excalidraw-mcp

# Allow HTTP/HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Allow SSH
sudo ufw allow 22/tcp
```

### DNS Configuration

Configure DNS records for each service:

```dns
# Example DNS records
ws-session-buddy.example.com.    A    192.0.2.10
ws-mahavishnu.example.com.       A    192.0.2.10
ws-crackerjack.example.com.      A    192.0.2.10
ws-akosha.example.com.          A    192.0.2.10
ws-dhruva.example.com.          A    192.0.2.10
ws-excalidraw.example.com.       A    192.0.2.10
ws-fastblocks.example.com.       A    192.0.2.10
```

---

## Environment Setup

### Directory Structure

```bash
/opt/bodhisattva/
├── services/
│   ├── session-buddy/
│   ├── mahavishnu/
│   ├── crackerjack/
│   ├── akosha/
│   ├── dhruva/
│   ├── excalidraw-mcp/
│   └── fastblocks/
├── certificates/
│   ├── session-buddy/
│   ├── mahavishnu/
│   └── ...
├── logs/
│   ├── websocket/
│   └── metrics/
├── config/
│   ├── mahavishnu.yaml
│   └── local.yaml
└── venv/
    └── python3.11/
```

### Virtual Environment Setup

```bash
# Create shared virtual environment
cd /opt/bodhisattva
python3.11 -m venv venv
source venv/bin/activate

# Upgrade pip and build tools
pip install --upgrade pip setuptools wheel

# Install dependencies
pip install -e ./services/session-buddy
pip install -e ./services/mahavishnu
pip install -e ./services/crackerjack
pip install -e ./services/akosha
pip install -e ./services/dhruva
pip install -e ./services/excalidraw-mcp
pip install -e ./services/fastblocks

# Install production dependencies
pip install gunicorn uvicorn prometheus-client redis
```

### Environment Variables

Create `/opt/bodhisattva/config/env`:

```bash
# Common settings
export PYTHONUNBUFFERED="1"
export PYTHONPATH="/opt/bodhisattva/services"

# JWT Secrets (generate unique secrets for each service)
export MAHAVISHNU_JWT_SECRET="$(openssl rand -base64 32)"
export SESSION_BUDDY_JWT_SECRET="$(openssl rand -base64 32)"
export CRACKERJACK_JWT_SECRET="$(openssl rand -base64 32)"
export AKOSHA_JWT_SECRET="$(openssl rand -base64 32)"
export DHRUVA_JWT_SECRET="$(openssl rand -base64 32)"
export EXCALIDRAW_JWT_SECRET="$(openssl rand -base64 32)"
export FASTBLOCKS_JWT_SECRET="$(openssl rand -base64 32)"

# TLS Certificate Paths
export MAHAVISHNU_CERT_FILE="/opt/bodhisattva/certificates/mahavishnu/cert.pem"
export MAHAVISHNU_KEY_FILE="/opt/bodhisattva/certificates/mahavishnu/key.pem"

# Redis (for shared state in HA deployments)
export REDIS_URL="redis://localhost:6379/0"

# Monitoring
export PROMETHEUS_METRICS_PORT="9090"
export PROMETHEUS_MULTIPROC_DIR="/tmp/prometheus"
```

Load environment variables:
```bash
source /opt/bodhisattva/config/env
```

---

## Certificate Management

### Development Certificates (Self-Signed)

For development, WebSocket servers can auto-generate self-signed certificates:

```python
# In server initialization
from mahavishnu.websocket.server import MahavishnuWebSocketServer

server = MahavishnuWebSocketServer(
    host="127.0.0.1",
    port=8690,
    tls_enabled=True,
    auto_cert=True,  # Auto-generate self-signed certificate
)
```

### Production Certificates (Let's Encrypt)

**Generate certificates using Certbot:**

```bash
# Install Certbot
sudo apt-get install certbot

# Obtain certificates for each service
sudo certbot certonly --standalone \
    -d ws-mahavishnu.example.com \
    -d ws-session-buddy.example.com \
    -d ws-crackerjack.example.com \
    -d ws-akosha.example.com \
    -d ws-dhruva.example.com \
    -d ws-excalidraw.example.com \
    -d ws-fastblocks.example.com

# Certificates will be stored in:
# /etc/letsencrypt/live/ws-mahavishnu.example.com/fullchain.pem
# /etc/letsencrypt/live/ws-mahavishnu.example.com/privkey.pem
```

**Link certificates to service directory:**

```bash
# Create certificate directory
sudo mkdir -p /opt/bodhisattva/certificates

# Link Let's Encrypt certificates
for service in mahavishnu session-buddy crackerjack akosha dhruva excalidraw fastblocks; do
    sudo mkdir -p /opt/bodhisattva/certificates/$service
    sudo ln -s /etc/letsencrypt/live/ws-$service.example.com/fullchain.pem \
              /opt/bodhisattva/certificates/$service/cert.pem
    sudo ln -s /etc/letsencrypt/live/ws-$service.example.com/privkey.pem \
              /opt/bodhisattva/certificates/$service/key.pem
done
```

### Certificate Renewal

**Setup automatic renewal:**

```bash
# Test renewal
sudo certbot renew --dry-run

# Create systemd timer for auto-renewal
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer

# Verify
sudo systemctl status certbot.timer
```

**Reload services after renewal:**

Create `/opt/bodhisattva/scripts/reload-after-renewal.sh`:

```bash
#!/bin/bash
# Reload WebSocket services after certificate renewal

echo "Reloading services for new certificates..."

# Reload each service
for service in mahavishnu session-buddy crackerjack akosha dhruva excalidraw fastblocks; do
    echo "Reloading $service..."
    sudo systemctl reload $service-websocket
done

echo "All services reloaded successfully"
```

Add to Certbot renewal hook:
```bash
echo "/opt/bodhisattva/scripts/reload-after-renewal.sh" | sudo tee -a /etc/letsencrypt/renewal-hooks/post/reload-services.sh
sudo chmod +x /etc/letsencrypt/renewal-hooks/post/reload-services.sh
```

### Certificate Validation

**Check certificate validity:**

```bash
# Check expiration date
openssl x509 -in /opt/bodhisattva/certificates/mahavishnu/cert.pem -noout -dates

# Verify certificate chain
openssl s_client -connect ws-mahavishnu.example.com:8690 -showcerts

# Check certificate details
openssl x509 -in /opt/bodhisattva/certificates/mahavishnu/cert.pem -text -noout
```

**Setup monitoring for certificate expiration:**

```bash
# Check all certificates
for cert in /opt/bodhisattva/certificates/*/cert.pem; do
    echo "Checking $cert"
    openssl x509 -in "$cert" -noout -checkend 2592000  # 30 days
    if [ $? -ne 0 ]; then
        echo "WARNING: Certificate expiring soon: $cert"
    fi
done
```

---

## Service Configuration

### Mahavishnu Configuration

`/opt/bodhisattva/config/mahavishnu.yaml`:

```yaml
# Server configuration
server_name: "Mahavishnu Orchestrator"
environment: "production"
debug: false

# WebSocket server configuration
websocket:
  enabled: true
  host: "0.0.0.0"  # Bind to all interfaces
  port: 8690
  tls_enabled: true
  cert_file: "/opt/bodhisattva/certificates/mahavishnu/cert.pem"
  key_file: "/opt/bodhisattva/certificates/mahavishnu/key.pem"
  auto_cert: false  # Use real certificates in production
  verify_client: false  # Set to true for mTLS
  require_auth: true  # Require JWT authentication
  max_connections: 1000
  message_rate_limit: 100  # messages per second per connection
  ping_interval: 20  # seconds
  ping_timeout: 20  # seconds
  close_timeout: 10  # seconds

# JWT authentication
jwt:
  secret: "${MAHAVISHNU_JWT_SECRET}"
  algorithm: "HS256"
  token_expiry: 3600  # 1 hour

# Pool configuration
pools:
  enabled: true
  default_type: "mahavishnu"
  routing_strategy: "least_loaded"

# Adapter configuration
adapters:
  prefect:
    enabled: true
  llamaindex:
    enabled: true
  agno:
    enabled: true

# Logging
logging:
  level: "INFO"
  format: "json"
  file: "/opt/bodhisattva/logs/mahavishnu/websocket.log"
  rotation: "10 MB"
  retention: 30  # days
```

### Session-Buddy Configuration

`/opt/bodhisattva/config/session-buddy.yaml`:

```yaml
server_name: "Session-Buddy Manager"
environment: "production"

websocket:
  enabled: true
  host: "0.0.0.0"
  port: 8765
  tls_enabled: true
  cert_file: "/opt/bodhisattva/certificates/session-buddy/cert.pem"
  key_file: "/opt/bodhisattva/certificates/session-buddy/key.pem"
  require_auth: true
  max_connections: 500
  message_rate_limit: 50

# Session management
sessions:
  storage_path: "/opt/bodhisattva/data/sessions"
  max_sessions: 10000
  checkpoint_interval: 300  # 5 minutes

# Memory aggregation
memory:
  enabled: true
  sync_interval: 60
  akosha_url: "http://localhost:8682/mcp"

logging:
  level: "INFO"
  file: "/opt/bodhisattva/logs/session-buddy/websocket.log"
```

### Crackerjack Configuration

`/opt/bodhisattva/config/crackerjack.yaml`:

```yaml
server_name: "Crackerjack Inspector"
environment: "production"

websocket:
  enabled: true
  host: "0.0.0.0"
  port: 8686
  tls_enabled: true
  cert_file: "/opt/bodhisattva/certificates/crackerjack/cert.pem"
  key_file: "/opt/bodhisattva/certificates/crackerjack/key.pem"
  require_auth: true
  max_connections: 200
  message_rate_limit: 100

# Quality control
qc:
  enabled: true
  min_score: 80
  auto_fix: false  # Disable auto-fix in production

logging:
  level: "INFO"
  file: "/opt/bodhisattva/logs/crackerjack/websocket.log"
```

### Akosha Configuration

`/opt/bodhisattva/config/akosha.yaml`:

```yaml
server_name: "Akosha Diviner"
environment: "production"

websocket:
  enabled: true
  host: "0.0.0.0"
  port: 8692
  tls_enabled: true
  cert_file: "/opt/bodhisattva/certificates/akosha/cert.pem"
  key_file: "/opt/bodhisattva/certificates/akosha/key.pem"
  require_auth: true
  max_connections: 300
  message_rate_limit: 100

# Analytics
analytics:
  hotstore_path: "/opt/bodhisattva/data/akosha/hotstore.duckdb"
  aggregation_interval: 60

logging:
  level: "INFO"
  file: "/opt/bodhisattva/logs/akosha/websocket.log"
```

### Dhruva Configuration

`/opt/bodhisattva/config/dhruva.yaml`:

```yaml
server_name: "Dhruva Curator"
environment: "production"

websocket:
  enabled: true
  host: "0.0.0.0"
  port: 8693
  tls_enabled: true
  cert_file: "/opt/bodhisattva/certificates/dhruva/cert.pem"
  key_file: "/opt/bodhisattva/certificates/dhruva/key.pem"
  require_auth: true
  max_connections: 200
  message_rate_limit: 100

# Adapter distribution
distribution:
  registry_path: "/opt/bodhisattva/data/dhruva/registry"
  sync_interval: 300

logging:
  level: "INFO"
  file: "/opt/bodhisattva/logs/dhruva/websocket.log"
```

### Excalidraw-MCP Configuration

`/opt/bodhisattva/config/excalidraw.yaml`:

```yaml
server_name: "Excalidraw MCP Visualizer"
environment: "production"

websocket:
  enabled: true
  host: "0.0.0.0"
  port: 3042
  tls_enabled: true
  cert_file: "/opt/bodhisattva/certificates/excalidraw/cert.pem"
  key_file: "/opt/bodhisattva/certificates/excalidraw/key.pem"
  require_auth: true
  max_connections: 500
  message_rate_limit: 100

# Diagram collaboration
collaboration:
  max_users_per_room: 50
  cursor_throttle_ms: 50
  auto_save_interval: 30

logging:
  level: "INFO"
  file: "/opt/bodhisattva/logs/excalidraw/websocket.log"
```

### Fastblocks Configuration

`/opt/bodhisattva/config/fastblocks.yaml`:

```yaml
server_name: "Fastblocks Builder"
environment: "production"

websocket:
  enabled: true
  host: "0.0.0.0"
  port: 8684
  tls_enabled: true
  cert_file: "/opt/bodhisattva/certificates/fastblocks/cert.pem"
  key_file: "/opt/bodhisattva/certificates/fastblocks/key.pem"
  require_auth: true
  max_connections: 300
  message_rate_limit: 100

# UI framework
ui:
  hot_reload:
    enabled: true
    debounce_ms: 100
  render_timeout: 5  # seconds

logging:
  level: "INFO"
  file: "/opt/bodhisattva/logs/fastblocks/websocket.log"
```

---

## Security Hardening

### Authentication Checklist

- [ ] JWT secrets are unique for each service
- [ ] JWT secrets are stored in environment variables (not in config files)
- [ ] JWT token expiry is set to reasonable value (1 hour or less)
- [ ] `require_auth: true` is set in all production configs
- [ ] Token validation is implemented on all connection handlers
- [ ] Token refresh mechanism is implemented
- [ ] Rate limiting is enabled on authentication endpoints

### Authorization Checklist

- [ ] Permission-based access control is implemented
- [ ] Channel-level authorization is enforced
- [ ] Admin-only channels are properly restricted
- [ ] Cross-service communication uses mutual authentication
- [ ] User permissions are validated on every subscription request

### TLS/WSS Checklist

- [ ] TLS is enabled for all services (`tls_enabled: true`)
- [ ] Valid certificates are installed (not self-signed in production)
- [ ] Certificate paths are correctly configured
- [ ] Certificate renewal is automated
- [ ] Only secure cipher suites are enabled
- [ ] HTTP/1 is disabled, only WSS is allowed
- [ ] Certificate validation is tested

### Network Security Checklist

- [ ] Firewall rules restrict access to WebSocket ports
- [ ] Only necessary ports are exposed
- [ ] WebSocket servers bind to `0.0.0.0` behind reverse proxy
- [ ] Reverse proxy (nginx) handles SSL termination
- [ ] DDoS protection is enabled (rate limiting, connection limits)
- [ ] IP whitelisting is configured for admin endpoints
- [ ] Network segmentation isolates services

### Data Security Checklist

- [ ] Sensitive data is never logged
- [ ] Message payloads are validated and sanitized
- [ ] Message size limits are enforced
- [ ] Rate limiting prevents message flood attacks
- [ ] Input validation prevents injection attacks
- [ ] Secrets are never transmitted in WebSocket messages

### Monitoring Security Checklist

- [ ] Failed authentication attempts are logged and alerted
- [ ] Unauthorized access attempts are monitored
- [ ] Unusual connection patterns trigger alerts
- [ ] Security events are sent to SIEM
- [ ] Regular security audits are scheduled
- [ ] Intrusion detection is enabled

---

## Deployment Steps

### Step 1: Prepare Deployment Environment

```bash
# Create deployment directory
sudo mkdir -p /opt/bodhisattva
sudo chown -R $USER:$USER /opt/bodhisattva

# Create subdirectories
mkdir -p /opt/bodhisattva/{services,certificates,logs,config,data}
mkdir -p /opt/bodhisattva/logs/{websocket,metrics}
mkdir -p /opt/bodhisattva/data/{sessions,akosha,dhruva}

# Clone repositories
cd /opt/bodhisattnu/services
git clone https://github.com/yourorg/session-buddy.git
git clone https://github.com/yourorg/mahavishnu.git
git clone https://github.com/yourorg/crackerjack.git
git clone https://github.com/yourorg/akosha.git
git clone https://github.com/yourorg/dhruva.git
git clone https://github.com/yourorg/excalidraw-mcp.git
git clone https://github.com/yourorg/fastblocks.git

# Checkout production branches
for repo in */; do
    cd $repo
    git checkout main
    cd ..
done
```

### Step 2: Install Dependencies

```bash
# Create virtual environment
cd /opt/bodhisattnu
python3.11 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel

# Install all services
for service in session-buddy mahavishnu crackerjack akosha dhruva excalidraw-mcp fastblocks; do
    echo "Installing $service..."
    cd /opt/bodhisattnu/services/$service
    pip install -e ".[prod]" || pip install -e .
    cd /opt/bodhisattnu
done

# Install shared dependencies
pip install prometheus-client redis redis-msgpack
```

### Step 3: Generate Certificates

```bash
# Install Certbot
sudo apt-get install certbot

# Obtain certificates for all services
sudo certbot certonly --standalone \
    -d ws-mahavishnu.example.com \
    -d ws-session-buddy.example.com \
    -d ws-crackerjack.example.com \
    -d ws-akosha.example.com \
    -d ws-dhruva.example.com \
    -d ws-excalidraw.example.com \
    -d ws-fastblocks.example.com \
    --email admin@example.com \
    --agree-tos \
    --non-interactive

# Link certificates
for service in mahavishnu session-buddy crackerjack akosha dhruva excalidraw fastblocks; do
    sudo mkdir -p /opt/bodhisattnu/certificates/$service
    sudo ln -s /etc/letsencrypt/live/ws-$service.example.com/fullchain.pem \
              /opt/bodhisattnu/certificates/$service/cert.pem
    sudo ln -s /etc/letsencrypt/live/ws-$service.example.com/privkey.pem \
              /opt/bodhisattnu/certificates/$service/key.pem
    sudo chown -h $USER:$USER /opt/bodhisattnu/certificates/$service/*
done

# Verify certificates
for cert in /opt/bodhisattnu/certificates/*/cert.pem; do
    openssl x509 -in "$cert" -noout -dates
done
```

### Step 4: Configure Services

```bash
# Copy configuration files
for service in mahavishnu session-buddy crackerjack akosha dhruva excalidraw fastblocks; do
    cp /opt/bodhisattnu/services/$service/settings/$service.yaml \
       /opt/bodhisattnu/config/$service.yaml
done

# Create environment file
cat > /opt/bodhisattnu/config/env << 'EOF'
export PYTHONUNBUFFERED="1"
export PYTHONPATH="/opt/bodhisattnu/services"

# Generate JWT secrets
export MAHAVISHNU_JWT_SECRET="$(openssl rand -base64 32)"
export SESSION_BUDDY_JWT_SECRET="$(openssl rand -base64 32)"
export CRACKERJACK_JWT_SECRET="$(openssl rand -base64 32)"
export AKOSHA_JWT_SECRET="$(openssl rand -base64 32)"
export DHRUVA_JWT_SECRET="$(openssl rand -base64 32)"
export EXCALIDRAW_JWT_SECRET="$(openssl rand -base64 32)"
export FASTBLOCKS_JWT_SECRET="$(openssl rand -base64 32)"
EOF

# Source environment
source /opt/bodhisattnu/config/env
```

### Step 5: Create Systemd Services

**Mahavishnu WebSocket Service:**

Create `/etc/systemd/system/mahavishnu-websocket.service`:

```ini
[Unit]
Description=Mahavishnu WebSocket Server
After=network.target

[Service]
Type=simple
User=bodhisattva
Group=bodhisattva
WorkingDirectory=/opt/bodhisattnu/services/mahavishnu
Environment="PATH=/opt/bodhisattnu/venv/bin"
EnvironmentFile=/opt/bodhisattnu/config/env
ExecStart=/opt/bodhisattnu/venv/bin/python -m mahavishnu.websocket
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=10
StandardOutput=append:/opt/bodhisattnu/logs/mahavishnu/websocket.log
StandardError=append:/opt/bodhisattnu/logs/mahavishnu/websocket-error.log

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/bodhisattnu

[Install]
WantedBy=multi-user.target
```

**Repeat for other services** (session-buddy-websocket, crackerjack-websocket, etc.)

### Step 6: Enable and Start Services

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable services (start on boot)
for service in mahavishnu session-buddy crackerjack akosha dhruva excalidraw fastblocks; do
    sudo systemctl enable ${service}-websocket
done

# Start services
for service in mahavishnu session-buddy crackerjack akosha dhruva excalidraw fastblocks; do
    sudo systemctl start ${service}-websocket
    echo "Started $service"
done

# Check status
for service in mahavishnu session-buddy crackerjack akosha dhruva excalidraw fastblocks; do
    echo "=== $service status ==="
    sudo systemctl status ${service}-websocket --no-pager
    echo ""
done
```

### Step 7: Verify Deployment

```bash
# Check all WebSocket ports
for port in 8684 8686 8690 8692 8693 8765 3042; do
    echo "Checking port $port..."
    nc -z localhost $port && echo "✓ Listening" || echo "✗ Not listening"
done

# Test TLS connections
for service in mahavishnu session-buddy crackerjack akosha dhruva excalidraw fastblocks; do
    echo "Testing $service WSS connection..."
    openssl s_client -connect localhost:8690 -servername ws-$service.example.com < /dev/null
done

# Check logs
sudo journalctl -u mahavishnu-websocket -n 50 --no-pager

# Run health checks
source /opt/bodhisattnu/venv/bin/activate
python -m mahavishnu.websocket.health_check
```

---

## Docker Deployment

### Docker Compose Configuration

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  # Redis for shared state (HA deployments)
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    restart: unless-stopped

  # Mahavishnu WebSocket
  mahavishnu-ws:
    build:
      context: ./services/mahavishnu
      dockerfile: Dockerfile.websocket
    ports:
      - "8690:8690"
      - "9090:9090"  # Metrics
    environment:
      - PYTHONUNBUFFERED=1
      - MAHAVISHNU_JWT_SECRET=${MAHAVISHNU_JWT_SECRET}
      - REDIS_URL=redis://redis:6379/0
      - MAHAVISHNU_CERT_FILE=/certs/cert.pem
      - MAHAVISHNU_KEY_FILE=/certs/key.pem
    volumes:
      - ./certificates/mahavishnu:/certs:ro
      - ./config/mahavishnu.yaml:/config/mahavishnu.yaml:ro
      - ./logs/mahavishnu:/logs
    depends_on:
      - redis
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-m", "mahavishnu.websocket.health_check"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Session-Buddy WebSocket
  session-buddy-ws:
    build:
      context: ./services/session-buddy
      dockerfile: Dockerfile.websocket
    ports:
      - "8765:8765"
    environment:
      - PYTHONUNBUFFERED=1
      - SESSION_BUDDY_JWT_SECRET=${SESSION_BUDDY_JWT_SECRET}
      - SESSION_BUDDY_CERT_FILE=/certs/cert.pem
      - SESSION_BUDDY_KEY_FILE=/certs/key.pem
    volumes:
      - ./certificates/session-buddy:/certs:ro
      - ./config/session-buddy.yaml:/config/session-buddy.yaml:ro
      - ./logs/session-buddy:/logs
      - session_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-m", "session_buddy.websocket.health_check"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Crackerjack WebSocket
  crackerjack-ws:
    build:
      context: ./services/crackerjack
      dockerfile: Dockerfile.websocket
    ports:
      - "8686:8686"
    environment:
      - PYTHONUNBUFFERED=1
      - CRACKERJACK_JWT_SECRET=${CRACKERJACK_JWT_SECRET}
      - CRACKERJACK_CERT_FILE=/certs/cert.pem
      - CRACKERJACK_KEY_FILE=/certs/key.pem
    volumes:
      - ./certificates/crackerjack:/certs:ro
      - ./config/crackerjack.yaml:/config/crackerjack.yaml:ro
      - ./logs/crackerjack:/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-m", "crackerjack.websocket.health_check"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Akosha WebSocket
  akosha-ws:
    build:
      context: ./services/akosha
      dockerfile: Dockerfile.websocket
    ports:
      - "8692:8692"
    environment:
      - PYTHONUNBUFFERED=1
      - AKOSHA_JWT_SECRET=${AKOSHA_JWT_SECRET}
      - AKOSHA_CERT_FILE=/certs/cert.pem
      - AKOSHA_KEY_FILE=/certs/key.pem
    volumes:
      - ./certificates/akosha:/certs:ro
      - ./config/akosha.yaml:/config/akosha.yaml:ro
      - ./logs/akosha:/logs
      - akosha_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-m", "akosha.websocket.health_check"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Dhruva WebSocket
  dhruva-ws:
    build:
      context: ./services/dhruva
      dockerfile: Dockerfile.websocket
    ports:
      - "8693:8693"
    environment:
      - PYTHONUNBUFFERED=1
      - DHRUVA_JWT_SECRET=${DHRUVA_JWT_SECRET}
      - DHRUVA_CERT_FILE=/certs/cert.pem
      - DHRUVA_KEY_FILE=/certs/key.pem
    volumes:
      - ./certificates/dhruva:/certs:ro
      - ./config/dhruva.yaml:/config/dhruva.yaml:ro
      - ./logs/dhruva:/logs
      - dhruva_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-m", "dhruva.websocket.health_check"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Excalidraw-MCP WebSocket
  excalidraw-ws:
    build:
      context: ./services/excalidraw-mcp
      dockerfile: Dockerfile.websocket
    ports:
      - "3042:3042"
    environment:
      - PYTHONUNBUFFERED=1
      - EXCALIDRAW_JWT_SECRET=${EXCALIDRAW_JWT_SECRET}
      - EXCALIDRAW_CERT_FILE=/certs/cert.pem
      - EXCALIDRAW_KEY_FILE=/certs/key.pem
    volumes:
      - ./certificates/excalidraw:/certs:ro
      - ./config/excalidraw.yaml:/config/excalidraw.yaml:ro
      - ./logs/excalidraw:/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-m", "excalidraw_mcp.websocket.health_check"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Fastblocks WebSocket
  fastblocks-ws:
    build:
      context: ./services/fastblocks
      dockerfile: Dockerfile.websocket
    ports:
      - "8684:8684"
    environment:
      - PYTHONUNBUFFERED=1
      - FASTBLOCKS_JWT_SECRET=${FASTBLOCKS_JWT_SECRET}
      - FASTBLOCKS_CERT_FILE=/certs/cert.pem
      - FASTBLOCKS_KEY_FILE=/certs/key.pem
    volumes:
      - ./certificates/fastblocks:/certs:ro
      - ./config/fastblocks.yaml:/config/fastblocks.yaml:ro
      - ./logs/fastblocks:/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-m", "fastblocks.websocket.health_check"]
      interval: 30s
      timeout: 10s
      retries: 3

  # Prometheus for metrics collection
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9091:9090"
    volumes:
      - ./config/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
    restart: unless-stopped

  # Grafana for visualization
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana_data:/var/lib/grafana
      - ./config/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
      - ./config/grafana/datasources:/etc/grafana/provisioning/datasources:ro
    restart: unless-stopped

volumes:
  redis_data:
  session_data:
  akosha_data:
  dhruva_data:
  prometheus_data:
  grafana_data:

networks:
  default:
    name: bodhisattva-network
```

### Dockerfile for WebSocket Services

Create `Dockerfile.websocket` in each service:

```dockerfile
# Mahavishnu WebSocket Server Dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 bodhisattva && \
    chown -R bodhisattva:bodhisattva /app
USER bodhisattva

# Expose WebSocket port
EXPOSE 8690

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -m mahavishnu.websocket.health_check || exit 1

# Run WebSocket server
CMD ["python", "-m", "mahavishnu.websocket"]
```

### Deploy with Docker Compose

```bash
# Build images
docker-compose build

# Generate JWT secrets
cat > .env << EOF
MAHAVISHNU_JWT_SECRET=$(openssl rand -base64 32)
SESSION_BUDDY_JWT_SECRET=$(openssl rand -base64 32)
CRACKERJACK_JWT_SECRET=$(openssl rand -base64 32)
AKOSHA_JWT_SECRET=$(openssl rand -base64 32)
DHRUVA_JWT_SECRET=$(openssl rand -base64 32)
EXCALIDRAW_JWT_SECRET=$(openssl rand -base64 32)
FASTBLOCKS_JWT_SECRET=$(openssl rand -base64 32)
EOF

# Start services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f mahavishnu-ws

# Stop services
docker-compose down

# Scale services (for load testing)
docker-compose up -d --scale mahavishnu-ws=3
```

---

## Kubernetes Deployment

### Namespace and Resource Configuration

Create `k8s/namespace.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: bodhisattva
  labels:
    name: bodhisattva
    environment: production
```

### ConfigMap for Configuration

Create `k8s/configmap.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: websocket-config
  namespace: bodhisattva
data:
  mahavishnu.yaml: |
    server_name: "Mahavishnu Orchestrator"
    environment: "production"
    websocket:
      enabled: true
      host: "0.0.0.0"
      port: 8690
      tls_enabled: true
      require_auth: true
      max_connections: 1000
    jwt:
      algorithm: "HS256"
      token_expiry: 3600
```

### Secret for JWT and TLS

```bash
# Create TLS secrets
kubectl create secret tls mahavishnu-tls \
  --cert=/opt/bodhisattnu/certificates/mahavishnu/cert.pem \
  --key=/opt/bodhisattnu/certificates/mahavishnu/key.pem \
  --namespace=bodhisattva

# Create JWT secrets
kubectl create secret generic mahavishnu-jwt \
  --from-literal=secret=$(openssl rand -base64 32) \
  --namespace=bodhisattva
```

### Deployment Manifest

Create `k8s/mahavishnu-websocket-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mahavishnu-websocket
  namespace: bodhisattva
  labels:
    app: mahavishnu-websocket
spec:
  replicas: 3
  selector:
    matchLabels:
      app: mahavishnu-websocket
  template:
    metadata:
      labels:
        app: mahavishnu-websocket
    spec:
      containers:
      - name: mahavishnu-websocket
        image: bodhisattva/mahavishnu-websocket:latest
        imagePullPolicy: Always
        ports:
        - containerPort: 8690
          name: websocket
          protocol: TCP
        - containerPort: 9090
          name: metrics
          protocol: TCP
        env:
        - name: MAHAVISHNU_JWT_SECRET
          valueFrom:
            secretKeyRef:
              name: mahavishnu-jwt
              key: secret
        - name: MAHAVISHNU_CERT_FILE
          value: /certs/tls.crt
        - name: MAHAVISHNU_KEY_FILE
          value: /certs/tls.key
        - name: PYTHONUNBUFFERED
          value: "1"
        volumeMounts:
        - name: config
          mountPath: /config
        - name: certs
          mountPath: /certs
          readOnly: true
        - name: logs
          mountPath: /logs
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          tcpSocket:
            port: 8690
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          tcpSocket:
            port: 8690
          initialDelaySeconds: 5
          periodSeconds: 5
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 15"]
      volumes:
      - name: config
        configMap:
          name: websocket-config
      - name: certs
        secret:
          secretName: mahavishnu-tls
      - name: logs
        emptyDir: {}
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app
                  operator: In
                  values:
                  - mahavishnu-websocket
              topologyKey: kubernetes.io/hostname
```

### Service Manifest

Create `k8s/mahavishnu-websocket-service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: mahavishnu-websocket
  namespace: bodhisattva
  labels:
    app: mahavishnu-websocket
spec:
  type: ClusterIP
  ports:
  - port: 8690
    targetPort: 8690
    protocol: TCP
    name: websocket
  - port: 9090
    targetPort: 9090
    protocol: TCP
    name: metrics
  selector:
    app: mahavishnu-websocket

---
apiVersion: v1
kind: Service
metadata:
  name: mahavishnu-websocket-external
  namespace: bodhisattva
  labels:
    app: mahavishnu-websocket
spec:
  type: LoadBalancer
  externalTrafficPolicy: Local
  ports:
  - port: 8690
    targetPort: 8690
    protocol: TCP
    name: websocket
  selector:
    app: mahavishnu-websocket
```

### HorizontalPodAutoscaler

Create `k8s/mahavishnu-websocket-hpa.yaml`:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: mahavishnu-websocket-hpa
  namespace: bodhisattva
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: mahavishnu-websocket
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
      - type: Percent
        value: 100
        periodSeconds: 30
      - type: Pods
        value: 2
        periodSeconds: 30
      selectPolicy: Max
```

### Deploy to Kubernetes

```bash
# Create namespace
kubectl apply -f k8s/namespace.yaml

# Create configmaps
kubectl apply -f k8s/configmap.yaml

# Create secrets
kubectl create secret generic mahavishnu-jwt \
  --from-literal=secret=$(openssl rand -base64 32) \
  --namespace=bodhisattva

kubectl create secret tls mahavishnu-tls \
  --cert=certificates/mahavishnu/cert.pem \
  --key=certificates/mahavishnu/key.pem \
  --namespace=bodhisattva

# Deploy all services
kubectl apply -f k8s/mahavishnu-websocket-deployment.yaml
kubectl apply -f k8s/mahavishnu-websocket-service.yaml
kubectl apply -f k8s/mahavishnu-websocket-hpa.yaml

# Check deployment
kubectl get pods -n bodhisattva
kubectl get services -n bodhisattva
kubectl get hpa -n bodhisattva

# View logs
kubectl logs -f deployment/mahavishnu-websocket -n bodhisattva

# Scale manually
kubectl scale deployment mahavishnu-websocket --replicas=5 -n bodhisattva
```

---

## Performance Tuning

### Connection Tuning

**System-level tuning:**

```bash
# /etc/sysctl.conf
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 8192
net.core.netdev_max_backlog = 16384
net.ipv4.ip_local_port_range = 10000 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 30
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3

# Apply changes
sudo sysctl -p
```

**Service-level tuning:**

```yaml
# In service configuration
websocket:
  max_connections: 10000  # Increase for high-traffic scenarios
  message_rate_limit: 1000  # Adjust based on requirements
  ping_interval: 30  # Reduce ping frequency for less overhead
  ping_timeout: 30
  close_timeout: 5  # Faster cleanup of dead connections
```

### Broadcast Optimization

**Batch broadcast messages:**

```python
# Instead of broadcasting immediately, batch messages
class BroadcastBatcher:
    def __init__(self, server, batch_size=100, max_wait=0.1):
        self.server = server
        self.batch_size = batch_size
        self.max_wait = max_wait
        self.queue = []
        self.lock = asyncio.Lock()

    async def add(self, room_id, message):
        async with self.lock:
            self.queue.append((room_id, message))
            if len(self.queue) >= self.batch_size:
                await self._flush()

    async def _flush(self):
        if not self.queue:
            return

        # Group by room
        rooms = {}
        for room_id, message in self.queue:
            if room_id not in rooms:
                rooms[room_id] = []
            rooms[room_id].append(message)

        # Broadcast to each room
        tasks = [
            self.server.broadcast_to_room(room_id, msg)
            for room_id, messages in rooms.items()
            for msg in messages
        ]
        await asyncio.gather(*tasks)

        self.queue.clear()
```

### Memory Optimization

**Limit message retention:**

```python
# Don't store old messages
class MessageHistory:
    def __init__(self, max_size=1000):
        self.history = {}
        self.max_size = max_size

    async def add(self, room_id, message):
        if room_id not in self.history:
            self.history[room_id] = []

        self.history[room_id].append(message)

        # Trim old messages
        if len(self.history[room_id]) > self.max_size:
            self.history[room_id] = self.history[room_id][-self.max_size:]

    async def get_recent(self, room_id, count=100):
        if room_id not in self.history:
            return []
        return self.history[room_id][-count:]
```

### Throughput Tuning

**Adjust worker threads:**

```python
# In service startup
import asyncio

# Increase event loop workers
loop = asyncio.get_event_loop()
loop.set_default_executor(
    ThreadPoolExecutor(max_workers=50)  # Increase for more concurrent operations
)
```

---

## High Availability

### Load Balancing with Nginx

**Nginx configuration for WebSocket load balancing:**

```nginx
# /etc/nginx/nginx.conf

upstream mahavishnu_websocket_backend {
    least_conn;  # Load balancing strategy
    server backend1:8690 weight=1;
    server backend2:8690 weight=1;
    server backend3:8690 weight=1;
}

upstream session_buddy_websocket_backend {
    least_conn;
    server backend1:8765 weight=1;
    server backend2:8765 weight=1;
    server backend3:8765 weight=1;
}

# Mahavishnu WebSocket
server {
    listen 443 ssl http2;
    server_name ws-mahavishnu.example.com;

    ssl_certificate /etc/letsencrypt/live/ws-mahavishnu.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ws-mahavishnu.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256';

    location / {
        proxy_pass http://mahavishnu_websocket_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket timeout settings
        proxy_connect_timeout 7d;
        proxy_send_timeout 7d;
        proxy_read_timeout 7d;
    }
}

# Session-Buddy WebSocket
server {
    listen 443 ssl http2;
    server_name ws-session-buddy.example.com;

    ssl_certificate /etc/letsencrypt/live/ws-session-buddy.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ws-session-buddy.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://session_buddy_websocket_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_connect_timeout 7d;
        proxy_send_timeout 7d;
        proxy_read_timeout 7d;
    }
}
```

### Redis for Shared State

**Setup Redis for cross-instance room management:**

```python
import aioredis
import json

class RedisRoomManager:
    """Manage room subscriptions across multiple instances."""

    def __init__(self, redis_url):
        self.redis = aioredis.from_url(redis_url)
        self.instance_id = str(uuid.uuid4())
        self.pubsub = self.redis.pubsub()

    async def join_room(self, room_id, connection_id):
        """Add connection to room (Redis-backed)."""
        await self.redis.sadd(f"room:{room_id}", f"{self.instance_id}:{connection_id}")
        await self.redis.publish(f"room:{room_id}:joined", json.dumps({
            "instance": self.instance_id,
            "connection": connection_id
        }))

    async def leave_room(self, room_id, connection_id):
        """Remove connection from room."""
        await self.redis.srem(f"room:{room_id}", f"{self.instance_id}:{connection_id}")
        await self.redis.publish(f"room:{room_id}:left", json.dumps({
            "instance": self.instance_id,
            "connection": connection_id
        }))

    async def broadcast_to_room(self, room_id, message):
        """Broadcast message to all connections in room (across instances)."""
        await self.redis.publish(f"room:{room_id}:broadcast", json.dumps(message))

    async def listen_for_broadcasts(self, callback):
        """Listen for broadcast messages from other instances."""
        await self.pubsub.psubscribe(f"room:*:broadcast")
        async for message in self.pubsub.listen():
            if message['type'] == 'pmessage':
                data = json.loads(message['data'])
                await callback(data)
```

### Health Checks and Failover

**Implement graceful degradation:**

```python
class HealthChecker:
    """Monitor health of backend instances."""

    def __init__(self):
        self.healthy_instances = set()
        self.unhealthy_instances = set()

    async def check_instance(self, instance_url):
        """Check if instance is healthy."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{instance_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        self.healthy_instances.add(instance_url)
                        self.unhealthy_instances.discard(instance_url)
                        return True
        except Exception:
            pass

        self.unhealthy_instances.add(instance_url)
        self.healthy_instances.discard(instance_url)
        return False

    async def get_healthy_instance(self, instances):
        """Get a healthy instance for routing."""
        available = set(instances) & self.healthy_instances
        if available:
            return random.choice(list(available))
        # Fallback to any instance if all are unhealthy
        return random.choice(instances)
```

---

## Monitoring & Alerting

### Prometheus Metrics

**Key metrics to track:**

```python
from prometheus_client import Counter, Gauge, Histogram

# Connection metrics
websocket_connections = Gauge(
    'websocket_connections_current',
    'Current number of WebSocket connections',
    ['service', 'server']
)

websocket_connections_total = Counter(
    'websocket_connections_total',
    'Total WebSocket connections established',
    ['service', 'server']
)

# Message metrics
websocket_messages_sent = Counter(
    'websocket_messages_sent_total',
    'Total messages sent',
    ['service', 'server', 'message_type']
)

websocket_messages_received = Counter(
    'websocket_messages_received_total',
    'Total messages received',
    ['service', 'server', 'message_type']
)

# Performance metrics
websocket_message_duration = Histogram(
    'websocket_message_duration_seconds',
    'Message processing duration',
    ['service', 'server'],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

websocket_broadcast_duration = Histogram(
    'websocket_broadcast_duration_seconds',
    'Broadcast duration',
    ['service', 'server', 'channel']
)

# Error metrics
websocket_errors = Counter(
    'websocket_errors_total',
    'Total WebSocket errors',
    ['service', 'server', 'error_type']
)
```

### Grafana Dashboards

**Key dashboard panels:**

1. **Connections Overview**
   - Current connections (by service)
   - Connection rate (connections/sec)
   - Disconnection rate
   - Average connection duration

2. **Message Throughput**
   - Messages sent per second
   - Messages received per second
   - Message size distribution
   - Broadcast queue size

3. **Performance Metrics**
   - Message processing latency (P50, P95, P99)
   - Broadcast duration
   - Room join/leave latency

4. **Error Tracking**
   - Connection errors by type
   - Authentication failures
   - Message decode errors
   - Rate limit violations

### Alerting Rules

**Prometheus alert rules:**

```yaml
groups:
- name: websocket_alerts
  interval: 30s
  rules:
  # High connection error rate
  - alert: HighConnectionErrorRate
    expr: rate(websocket_errors_total{error_type="connection_error"}[5m]) > 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High connection error rate on {{ $labels.service }}"
      description: "Connection error rate is {{ $value }} errors/sec"

  # Too many connections
  - alert: TooManyConnections
    expr: websocket_connections_current > 900
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "High connection count on {{ $labels.service }}"
      description: "Connection count is {{ $value }} (limit: 1000)"

  # High message latency
  - alert: HighMessageLatency
    expr: histogram_quantile(0.95, rate(websocket_message_duration_seconds_bucket[5m])) > 1
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "High message latency on {{ $labels.service }}"
      description: "P95 latency is {{ $value }}s"

  # Service down
  - alert: WebSocketServiceDown
    expr: up{job=~".*websocket.*"} == 0
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "WebSocket service {{ $labels.instance }} is down"
      description: "Service has been down for more than 2 minutes"
```

---

## Backup & Recovery

### Configuration Backups

```bash
#!/bin/bash
# Backup WebSocket configurations

BACKUP_DIR="/backup/websocket/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# Backup configuration files
cp -r /opt/bodhisattnu/config "$BACKUP_DIR/"

# Backup certificates
cp -r /opt/bodhisattnu/certificates "$BACKUP_DIR/"

# Create tarball
tar -czf "$BACKUP_DIR.tar.gz" "$BACKUP_DIR"
rm -rf "$BACKUP_DIR"

# Keep last 30 days of backups
find /backup/websocket -name "*.tar.gz" -mtime +30 -delete
```

### Data Backups

```bash
#!/bin/bash
# Backup service data

# Backup session data
rsync -av /opt/bodhisattnu/data/sessions/ /backup/sessions/

# Backup Akosha hotstore
cp /opt/bodhisattnu/data/akosha/hotstore.duckdb /backup/akosha/

# Backup Dhruva registry
rsync -av /opt/bodhisattnu/data/dhruva/ /backup/dhruva/
```

### Disaster Recovery

**Recovery procedure:**

1. **Restore configurations:**
   ```bash
   tar -xzf /backup/websocket/20260210.tar.gz -C /
   ```

2. **Restore data:**
   ```bash
   rsync -av /backup/sessions/ /opt/bodhisattnu/data/sessions/
   cp /backup/akosha/hotstore.duckdb /opt/bodhisattnu/data/akosha/
   ```

3. **Restart services:**
   ```bash
   for service in mahavishnu session-buddy crackerjack akosha dhruva excalidraw fastblocks; do
       sudo systemctl restart ${service}-websocket
   done
   ```

---

## Troubleshooting

### Common Issues and Solutions

#### Issue: Cannot connect to WebSocket server

**Symptoms:**
- Client connection timeouts
- "Connection refused" errors

**Diagnosis:**
```bash
# Check if service is running
sudo systemctl status mahavishnu-websocket

# Check if port is listening
sudo netstat -tlnp | grep 8690

# Check firewall rules
sudo ufw status

# Check service logs
sudo journalctl -u mahavishnu-websocket -n 50
```

**Solutions:**
- Start service: `sudo systemctl start mahavishnu-websocket`
- Open firewall: `sudo ufw allow 8690/tcp`
- Check configuration for errors
- Verify certificate paths are correct

#### Issue: TLS/WSS handshake fails

**Symptoms:**
- "SSL handshake failed" errors
- Certificate validation errors

**Diagnosis:**
```bash
# Test TLS connection
openssl s_client -connect localhost:8690 -showcerts

# Check certificate validity
openssl x509 -in /opt/bodhisattnu/certificates/mahavishnu/cert.pem -noout -dates

# Check certificate chain
openssl s_client -connect ws-mahavishnu.example.com:8690 -verify_return_error
```

**Solutions:**
- Renew certificate: `sudo certbot renew`
- Restart service after certificate update
- Verify certificate paths in config
- Check certificate is not expired

#### Issue: High memory usage

**Symptoms:**
- Service OOM killed
- Memory usage constantly growing

**Diagnosis:**
```bash
# Check memory usage
ps aux | grep websocket

# Monitor memory over time
watch -n 5 'ps aux | grep mahavishnu'

# Check for memory leaks
valgrind --leak-check=full python -m mahavishnu.websocket
```

**Solutions:**
- Reduce max_connections limit
- Implement connection recycling
- Clear old message history
- Add memory limits in systemd/Kubernetes
- Restart service periodically

#### Issue: No events received after subscription

**Symptoms:**
- Client connects successfully
- Subscribes to channel
- No events received

**Diagnosis:**
```bash
# Check room subscriptions
curl http://localhost:9090/metrics | grep room_subscriptions

# Check server logs
sudo journalctl -u mahavishnu-websocket -f

# Test event generation
# Trigger an event manually and verify it's broadcast
```

**Solutions:**
- Verify subscribed to correct channel
- Check events are being generated
- Verify broadcast methods are called
- Check for errors in broadcast logic

### Debug Mode

**Enable debug logging:**

```yaml
# In service configuration
logging:
  level: "DEBUG"
  format: "json"
```

**Enable verbose mode:**

```bash
# Start with verbose logging
python -m mahavishnu.websocket --verbose --debug
```

### Performance Profiling

**Profile WebSocket performance:**

```python
import cProfile
import pstats

# Add to server startup
profiler = cProfile.Profile()
profiler.enable()

# ... run server ...

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 functions
```

---

## Appendices

### A. Port Reference

| Service | WebSocket Port | HTTP Port | Metrics Port |
|---------|---------------|-----------|--------------|
| session-buddy | 8765 | 8678 | 9091 |
| mahavishnu | 8690 | 8680 | 9090 |
| crackerjack | 8686 | 8676 | 9092 |
| akosha | 8692 | 8682 | 9093 |
| dhruva | 8693 | 8683 | 9094 |
| excalidraw-mcp | 3042 | 3032 | 9095 |
| fastblocks | 8684 | - | 9096 |

### B. Environment Variable Reference

| Variable | Description | Example |
|----------|-------------|---------|
| `MAHAVISHNU_JWT_SECRET` | JWT signing secret | `$(openssl rand -base64 32)` |
| `MAHAVISHNU_CERT_FILE` | TLS certificate path | `/opt/bodhisattnu/certificates/mahavishnu/cert.pem` |
| `MAHAVISHNU_KEY_FILE` | TLS private key path | `/opt/bodhisattnu/certificates/mahavishnu/key.pem` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `PYTHONUNBUFFERED` | Disable output buffering | `1` |

### C. Useful Commands

```bash
# Check all WebSocket server status
for service in mahavishnu session-buddy crackerjack akosha dhruva excalidraw fastblocks; do
    echo "=== $service ==="
    sudo systemctl status ${service}-websocket --no-pager -l
done

# View all logs in real-time
tail -f /opt/bodhisattnu/logs/*/websocket.log

# Restart all WebSocket services
for service in mahavishnu session-buddy crackerjack akosha dhruva excalidraw fastblocks; do
    sudo systemctl restart ${service}-websocket
done

# Check certificate expiration
for cert in /opt/bodhisattnu/certificates/*/cert.pem; do
    echo "$cert:"
    openssl x509 -in "$cert" -noout -dates
done
```

---

**Document Version:** 1.0.0
**Last Updated:** 2026-02-11
**Next Review:** 2026-03-11
