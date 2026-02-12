# WebSocket Production Deployment Checklist

**Purpose:** Quick reference guide for deploying Mahavishnu WebSocket server to production.
**Version:** 0.2.0
**Last Updated:** 2025-02-11

---

## Pre-Deployment (Day -1 to Day 0)

### Prerequisites Verification

- [ ] **Python 3.11+ installed**
  ```bash
  python3 --version  # Should be 3.11 or higher
  ```

- [ ] **Required packages installed**
  ```bash
  pip install mahavishnu[dev] mcp-common
  ```

- [ ] **System dependencies**
  ```bash
  sudo apt-get install -y nginx redis-server prometheus grafana
  ```

- [ ] **Network ports open**
  - [ ] Port 443 (HTTPS/WSS)
  - [ ] Port 80 (HTTP redirect)
  - [ ] Port 9090 (metrics, internal only)
  - [ ] Port 6379 (Redis, internal only)

### Security Configuration

- [ ] **TLS certificates obtained**
  - [ ] Production certificate from trusted CA
  - [ ] Private key file
  - [ ] CA bundle (if using client verification)
  - [ ] Certificate valid for >30 days

- [ ] **JWT secret generated**
  ```bash
  openssl rand -base64 32
  ```

- [ ] **Redis password generated**
  ```bash
  openssl rand -base64 24
  ```

- [ ] **File permissions set**
  ```bash
  sudo chmod 644 /etc/ssl/certs/mahavishnu.pem
  sudo chmod 600 /etc/ssl/private/mahavishnu-key.pem
  ```

---

## Deployment Day (Day 0)

### Step 1: Configuration Setup

- [ ] **Environment file created**
  ```bash
  sudo mkdir -p /etc/mahavishnu
  sudo nano /etc/mahavishnu/production.env
  ```

- [ ] **Required variables set**
  - [ ] `MAHAVISHNU_TLS_ENABLED=true`
  - [ ] `MAHAVISHNU_AUTH_ENABLED=true`
  - [ ] `MAHAVISHNU_JWT_SECRET=your-secret`
  - [ ] `MAHAVISHNU_CERT_FILE=/etc/ssl/certs/mahavishnu.pem`
  - [ ] `MAHAVISHNU_KEY_FILE=/etc/ssl/private/mahavishnu-key.pem`
  - [ ] `MAHAVISHNU_METRICS_ENABLED=true`
  - [ ] `MAHAVISHNU_REDIS_HOST=localhost`
  - [ ] `MAHAVISHNU_REDIS_PASSWORD=your-password`

- [ ] **Environment file secured**
  ```bash
  sudo chmod 640 /etc/mahavishnu/production.env
  sudo chown root:mahavishnu /etc/mahavishnu/production.env
  ```

### Step 2: Systemd Service

- [ ] **Service user created**
  ```bash
  sudo useradd -r -s /bin/false mahavishnu
  ```

- [ ] **Directories created**
  ```bash
  sudo mkdir -p /opt/mahavishnu/bin
  sudo mkdir -p /var/log/mahavishnu
  sudo mkdir -p /var/lib/mahavishnu
  sudo chown -R mahavishnu:mahavishnu /var/log/mahavishnu
  sudo chown -R mahavishnu:mahavishnu /var/lib/mahavishnu
  ```

- [ ] **Service file created**
  ```bash
  # See: /docs/WEBSOCKET_PRODUCTION_DEPLOYMENT.md
  sudo nano /etc/systemd/system/mahavishnu-websocket.service
  ```

- [ ] **Service enabled**
  ```bash
  sudo systemctl daemon-reload
  sudo systemctl enable mahavishnu-websocket
  ```

### Step 3: Nginx Configuration

- [ ] **Site configuration created**
  ```bash
  sudo nano /etc/nginx/sites-available/mahavishnu-websocket
  ```

- [ ] **Configuration tested**
  ```bash
  sudo nginx -t
  ```

- [ ] **Site enabled**
  ```bash
  sudo ln -s /etc/nginx/sites-available/mahavishnu-websocket \
             /etc/nginx/sites-enabled/mahavishnu-websocket
  ```

- [ ] **Nginx reloaded**
  ```bash
  sudo systemctl reload nginx
  ```

### Step 4: Monitoring Setup

- [ ] **Prometheus configured**
  ```bash
  sudo nano /etc/prometheus/prometheus.yml
  ```

- [ ] **Alert rules created**
  ```bash
  sudo nano /etc/prometheus/alerts/mahavishnu.yml
  ```

- [ ] **Prometheus restarted**
  ```bash
  sudo systemctl restart prometheus
  ```

- [ ] **Grafana dashboard imported**
  - Upload: `/docs/grafana/WebSocket_Monitoring.json`
  - Configure Prometheus data source
  - Verify panels show data

### Step 5: Deployment

- [ ] **Mahavishnu installed/updated**
  ```bash
  pip install --upgrade mahavishnu
  ```

- [ ] **Service started**
  ```bash
  sudo systemctl start mahavishnu-websocket
  ```

- [ ] **Service status verified**
  ```bash
  sudo systemctl status mahavishnu-websocket
  ```

---

## Post-Deployment (Day 0 to Day 1)

### Verification

- [ ] **Health check passes**
  ```bash
  curl http://localhost:8686/health
  ```

- [ ] **WebSocket connection works**
  ```bash
  wscat -c "ws://localhost:8686"
  ```

- [ ] **WSS connection works** (if TLS enabled)
  ```bash
  wscat -c "wss://your-domain.com" --no-check
  ```

- [ ] **Metrics endpoint accessible**
  ```bash
  curl http://localhost:9090/metrics
  ```

- [ ] **Prometheus scraping metrics**
  - Check Prometheus UI: `http://your-server:9090`
  - Query: `websocket_connections_active`
  - Verify data appears

- [ ] **Grafana dashboard shows data**
  - Check active connections panel
  - Check message rate panels
  - Check error rate panels

- [ ] **Run verification script**
  ```bash
  python scripts/verify_deployment.py
  ```

### Monitoring Verification

- [ ] **Log files exist**
  ```bash
  ls -la /var/log/mahavishnu/
  ```

- [ ] **No errors in logs**
  ```bash
  sudo journalctl -u mahavishnu-websocket -n 100
  ```

- [ ] **Nginx access logs show traffic**
  ```bash
  sudo tail -f /var/log/nginx/mahavishnu-access.log
  ```

### Performance Baseline

- [ ] **Baseline metrics recorded**
  - Active connections: ______
  - Message rate: ______ msg/sec
  - P95 latency: ______ ms
  - P99 latency: ______ ms

---

## Ongoing Operations (Day 1+)

### Daily Checks

- [ ] **Service status**
  ```bash
  sudo systemctl status mahavishnu-websocket
  ```

- [ ] **Log errors**
  ```bash
  sudo journalctl -u mahavishnu-websocket --since "24 hours ago" | grep -i error
  ```

- [ ] **Certificate expiry**
  ```bash
  openssl x509 -in /etc/ssl/certs/mahavishnu.pem -noout -dates
  ```

### Weekly Checks

- [ ] **Metrics review**
  - Check Grafana dashboard
  - Identify trends
  - Look for anomalies

- [ ] **Performance review**
  - Compare to baseline
  - Investigate degradation

- [ ] **Security scan**
  ```bash
  sudo ufw status
  sudo nmap -sV your-server-ip
  ```

### Monthly Tasks

- [ ] **Security updates**
  ```bash
  sudo apt-get update
  sudo apt-get upgrade
  ```

- [ ] **Log rotation verification**
  ```bash
  ls -la /var/log/mahavishnu/
  cat /etc/logrotate.d/mahavishnu
  ```

- [ ] **Certificate renewal check**
  - Renew if expiring within 30 days
  - Test new certificates
  - Deploy updated certificates

---

## Rollback Procedures

If deployment fails:

### Quick Rollback (< 5 minutes)

- [ ] **Stop current service**
  ```bash
  sudo systemctl stop mahavishnu-websocket
  ```

- [ ] **Restore previous version**
  ```bash
  sudo cp /opt/mahavishnu/bin/mahavishnu.previous \
          /opt/mahavishnu/bin/mahavishnu
  ```

- [ ] **Restart service**
  ```bash
  sudo systemctl start mahavishnu-websocket
  ```

- [ ] **Verify health**
  ```bash
  curl http://localhost:8686/health
  ```

### Full Rollback (< 15 minutes)

- [ ] **Restore previous configuration**
  ```bash
  sudo cp /etc/mahavishnu/config.previous \
          /etc/mahavishnu/production.env
  ```

- [ ] **Reload service**
  ```bash
  sudo systemctl reload mahavishnu-websocket
  ```

- [ ] **Verify all checks pass**
  ```bash
  python scripts/verify_deployment.py
  ```

---

## Emergency Contacts

| Role | Name | Contact |
|------|------|---------|
| **DevOps Lead** | | |
| **Security Lead** | | |
| **On-Call Engineer** | | |

---

## Support Resources

| Resource | Location |
|----------|----------|
| **Full Documentation** | `/docs/WEBSOCKET_PRODUCTION_DEPLOYMENT.md` |
| **API Reference** | `/docs/WEBSOCKET_API_REFERENCE.md` |
| **Grafana Dashboard** | `/docs/grafana/WebSocket_Monitoring.json` |
| **Verification Script** | `/scripts/verify_deployment.py` |

---

**Checklist Version:** 1.0.0
**Last Updated:** 2025-02-11
**Maintained By:** Mahavishnu Development Team
