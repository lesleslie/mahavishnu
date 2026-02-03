# AlertManager Setup Guide

**Purpose**: Production alerting configuration for Mahavishnu MCP Ecosystem
**Last Updated**: 2026-02-02

______________________________________________________________________

## Overview

This directory contains production AlertManager configuration for the Mahavishnu MCP ecosystem, including:

- **production_config.yml**: Main AlertManager configuration (routes, receivers, templates)
- **alert_rules.yml**: Prometheus alert rules (thresholds, conditions, annotations)

______________________________________________________________________

## Quick Start

### 1. Install AlertManager

```bash
# macOS
brew install alertmanager

# Linux
wget https://github.com/prometheus/alertmanager/releases/download/v0.26.0/alertmanager-0.26.0.linux-amd64.tar.gz
tar xvfz alertmanager-0.26.0.linux-amd64.tar.gz
sudo cp alertmanager-0.26.0.linux-amd64/alertmanager /usr/local/bin/
sudo cp alertmanager-0.26.0.linux-amd64/amtool /usr/local/bin/
```

### 2. Configure Environment Variables

```bash
# Create .env file for secrets
cat > /etc/alertmanager/.env << EOF
# Slack webhook URL
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# SMTP credentials
SMTP_PASSWORD=your-smtp-password-here

# PagerDuty integration key
PAGERDUTY_SERVICE_KEY=your-pagerduty-key-here
PAGERDUTY_URL=https://events.pagerduty.com/v2/enqueue
EOF

# Set proper permissions
chmod 600 /etc/alertmanager/.env
```

### 3. Start AlertManager

```bash
# Load environment variables
export $(cat /etc/alertmanager/.env | xargs)

# Start AlertManager
alertmanager \
  --config.file=/Users/les/Projects/mahavishnu/monitoring/alertmanager/production_config.yml \
  --storage.path=/var/lib/alertmanager \
  --web.external-url=http://localhost:9093
```

### 4. Access AlertManager UI

Open browser: http://localhost:9093

______________________________________________________________________

## Configuration Files

### production_config.yml

**Key Sections**:

1. **Global Configuration**

   - SMTP settings (email notifications)
   - Slack webhook URL
   - PagerDuty integration

1. **Routes**

   - Default receiver: `#alerts` Slack channel
   - Critical alerts: PagerDuty + `#critical-incidents`
   - Warning alerts: `#warnings` Slack channel
   - Service-specific routing

1. **Receivers**

   - `default`: Slack + email
   - `critical`: PagerDuty + Slack critical incidents + SMS
   - `warning`: Slack warnings + email
   - `mahavishnu-team`: Mahavishnu team channel
   - `session-buddy-team`: Session-Buddy team channel

1. **Inhibition Rules**

   - Inhibit warnings if critical is firing
   - Inhibit all alerts during maintenance

1. **Time Intervals**

   - Business hours vs off-hours routing
   - Maintenance windows

### alert_rules.yml

**Alert Groups**:

1. **Mahavishnu MCP Server Alerts**

   - Service down (P1)
   - High error rate > 5% (P1)
   - High latency p95 > 1s (P2)
   - High memory usage > 80% (P2)
   - Worker pool exhausted (P3)

1. **Session-Buddy Alerts**

   - Service down (P1)
   - DB pool exhausted (P1)
   - High error rate > 5% (P2)
   - DB size growing > 50%/day (P3)

1. **Akosha Alerts**

   - Service down (P1)
   - PostgreSQL down (P1)
   - High memory usage > 80% (P2)

1. **System Resource Alerts**

   - Disk space < 20% (P1)
   - CPU usage > 80% (P2)
   - Memory usage > 80% (P2)
   - Load average > 2x CPU count (P3)

1. **Backup Alerts**

   - Backup failed (P1)
   - Backup old > 24h (P2)
   - Backup size doubled in 7 days (P3)

1. **Security Alerts**

   - Auth failure rate > 10% (P1)
   - High rate limit violations (P2)
   - Suspicious user agent (P3)

______________________________________________________________________

## Notification Channels

### Slack Integration

**Setup**:

1. Create Slack app: https://api.slack.com/apps
1. Enable Incoming Webhooks
1. Create webhooks for:
   - `#alerts`: General alerts
   - `#critical-incidents`: Critical alerts only
   - `#warnings`: Warning alerts only
   - `#mahavishnu-team`: Mahavishnu-specific
   - `#session-buddy-team`: Session-Buddy-specific

**Configure**:

```bash
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

### Email Notifications

**Setup**:

1. Configure SMTP credentials in `.env`
1. Set notification email addresses
1. Test email delivery

**Test**:

```bash
echo "Test alert" | mail -s "AlertManager Test" oncall@example.com
```

### PagerDuty Integration

**Setup**:

1. Create PagerDuty account: https://www.pagerduty.com/
1. Create service: "Mahavishnu MCP"
1. Get integration key
1. Configure in `.env`

**Configure**:

```bash
export PAGERDUTY_SERVICE_KEY=your-integration-key
export PAGERDUTY_URL=https://events.pagerduty.com/v2/enqueue
```

______________________________________________________________________

## Alert Testing

### Test Slack Notifications

```bash
# Using curl
curl -X POST $SLACK_WEBHOOK_URL \
  -H 'Content-Type: application/json' \
  -d '{"text": "Test alert from Mahavishnu"}'

# Using amtool
amtool alert add test_alert \
  alertname=test_alert \
  severity=warning \
  --sender=http://localhost:9093
```

### Test Email Notifications

```bash
# Send test email
echo "Test alert from Mahavishnu" | \
  mail -s "AlertManager Test" \
  -S smtp="smtp://smtp.gmail.com:587" \
  -S smtp-use-starttls \
  -S smtp-auth=login \
  -S smtp-auth-user="alerts@mahavishnu.com" \
  -S smtp-auth-password="$SMTP_PASSWORD" \
  oncall@example.com
```

### Test PagerDuty Integration

```bash
# Send test event to PagerDuty
curl -X POST "$PAGERDUTY_URL" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json' \
  -d '{
    "routing_key": "'"$PAGERDUTY_SERVICE_KEY"'",
    "event_action": "trigger",
    "payload": {
      "summary": "Test alert from Mahavishnu",
      "severity": "info",
      "source": "mahavishnu-mcp",
      "custom_details": {
        "test": true
      }
    }
  }'
```

______________________________________________________________________

## Alert Rules Management

### Reload AlertManager Configuration

```bash
# Reload without restart
kill -HUP $(pgrep alertmanager)

# Or use amtool
amtool config reload \
  --url=http://localhost:9093 \
  --config.file=/Users/les/Projects/mahavishnu/monitoring/alertmanager/production_config.yml
```

### Validate Alert Rules

```bash
# Using promtool
promtool check rules /Users/les/Projects/mahavishnu/monitoring/alertmanager/alert_rules.yml

# Check syntax
amtool check-config /Users/les/Projects/mahavishnu/monitoring/alertmanager/production_config.yml
```

### View Active Alerts

```bash
# List all alerts
amtool alert query \
  --url=http://localhost:9093

# Filter by severity
amtool alert query --alertmanager.url=http://localhost:9093 severity=critical

# Filter by service
amtool alert query --alertmanager.url=http://localhost:9093 service=mahavishnu-mcp
```

______________________________________________________________________

## Maintenance Mode

### Enable Maintenance Mode

**Option 1: Via API**

```bash
# Set maintenance label
amtool alert add maintenance_mode \
  alertname=maintenance_mode \
  maintenance=true \
  --sender=http://localhost:9093
```

**Option 2: Via AlertManager config**

```yaml
# Add to production_config.yml
mute_time_intervals:
  - name: 'maintenance-window'
    time_intervals:
      - start_time: '2026-02-03T02:00:00Z'
        end_time: '2026-02-03T06:00:00Z'
```

**Option 3: Via Mahavishnu CLI**

```bash
mahavishnu maintenance enable \
  --message "Scheduled maintenance" \
  --duration 4h
```

### Disable Maintenance Mode

```bash
# Remove maintenance label
amtool alert delete maintenance_mode \
  --alertmanager.url=http://localhost:9093

# Or via Mahavishnu CLI
mahavishnu maintenance disable
```

______________________________________________________________________

## Monitoring AlertManager

### AlertManager Health

```bash
# Check AlertManager status
curl http://localhost:9093/-/healthy

# Check AlertManager metrics
curl http://localhost:9093/metrics | grep alertmanager_
```

### Key Metrics

- `alertmanager_alerts`: Total number of alerts
- `alertmanager_alerts_received_total`: Alerts received from Prometheus
- `alertmanager_notifications_total`: Notifications sent
- `alertmanager_notification_latency_seconds`: Notification delivery time
- `alertmanager_silences`: Active silences

### Grafana Dashboard

Import AlertManager dashboard: https://grafana.com/grafana/dashboards/9578

______________________________________________________________________

## Troubleshooting

### Alerts Not Firing

**Check**:

1. Prometheus is scraping targets: http://localhost:9090/targets
1. Alert rules are loaded: http://localhost:9090/alerts
1. Rule evaluation interval: `prometheus --enable-feature=promql-experimental-functions`
1. Alert thresholds are appropriate

**Debug**:

```bash
# Query Prometheus directly
promql 'up{job="mahavishnu-mcp"} == 0'

# Check rule evaluation logs
journalctl -u prometheus -f | grep "rule="
```

### Notifications Not Sending

**Check**:

1. AlertManager is receiving alerts: http://localhost:9093/#/alerts
1. Notification channels are configured correctly
1. API keys/webhook URLs are valid
1. Network connectivity to notification service

**Debug**:

```bash
# Check AlertManager logs
journalctl -u alertmanager -f

# Test notification manually
amtool alert add test_alert \
  alertname=test_alert \
  severity=warning \
  --sender=http://localhost:9093
```

### Duplicate Alerts

**Fix**: Adjust `group_by` and `inhibit_rules` in production_config.yml

**Example**:

```yaml
route:
  group_by: ['alertname', 'cluster', 'service']  # More specific grouping

inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname', 'instance']  # More precise matching
```

______________________________________________________________________

## Best Practices

1. **Test Alert Rules Regularly**

   - Use amtool to simulate alerts
   - Verify notifications are received
   - Check alert severity levels

1. **Avoid Alert Fatigue**

   - Tune thresholds based on actual usage
   - Use appropriate severity levels
   - Set reasonable `for` durations

1. **Document Alerts**

   - Update runbook URLs in alert annotations
   - Include troubleshooting steps
   - Document alert conditions clearly

1. **Review and Iterate**

   - Monthly alert rule review
   - Adjust thresholds based on metrics
   - Add new alerts as needed
   - Remove or silence noisy alerts

1. **Use Alert Grouping**

   - Group related alerts together
   - Reduce notification spam
   - Improve visibility

______________________________________________________________________

## On-Call Procedures

### Receiving an Alert

1. **Acknowledge receipt** (respond to notification)
1. **Assess severity** (P1: immediate, P2: 1 hour, P3: 4 hours)
1. **Investigate** (use runbook, check metrics)
1. **Resolve or escalate** (fix issue or escalate to next level)
1. **Document** (update incident log, runbook if needed)

### Alert Silence

**Temporarily silence an alert**:

```bash
# Silence for 2 hours
amtool silence add \
  --alertmanager.url=http://localhost:9093 \
  --author=oncall \
  --comment="Investigating" \
  alertname=MahavishnuMCPHighLatency

# List active silences
amtool silence query --alertmanager.url=http://localhost:9093

# Expire silence
amtool silence expire <silence-id> --alertmanager.url=http://localhost:9093
```

______________________________________________________________________

## Related Documentation

- [Maintenance Procedures](../MAINTENANCE_PROCEDURES.md)
- [Prometheus Documentation](https://prometheus.io/docs/alerting/latest/alertmanager/)

______________________________________________________________________

**Last Updated**: 2026-02-02
**Next Review**: 2026-03-02
**Maintained By**: DevOps Team
