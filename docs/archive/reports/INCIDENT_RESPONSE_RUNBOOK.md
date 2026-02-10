# Incident Response Runbook

**Version**: 1.0
**Last Updated**: 2026-02-02
**Scope**: Mahavishnu MCP Ecosystem

______________________________________________________________________

## Table of Contents

1. [Incident Classification](#incident-classification)
1. [Escalation Paths](#escalation-paths)
1. [Common Incident Scenarios](#common-incident-scenarios)
1. [Diagnostic Commands](#diagnostic-commands)
1. [Recovery Procedures](#recovery-procedures)
1. [Post-Incident Process](#post-incident-process)

______________________________________________________________________

## Incident Classification

### Severity Levels

| Severity | Name | Response Time | Definition |
|----------|------|---------------|------------|
| **P1** | Critical | 15 minutes | Complete service outage, data loss, security breach |
| **P2** | High | 1 hour | Major feature down, significant degradation |
| **P3** | Medium | 4 hours | Minor feature down, partial degradation |
| **P4** | Low | 1 business day | Cosmetic issues, minor bugs |

### Classification Criteria

**P1 - Critical** 🚨

- Service completely unavailable
- Data corruption or loss
- Security breach or active attack
- Payment processing failure
- > 50% of users affected

**P2 - High** ⚠️

- Major feature non-functional
- Performance degradation > 50%
- Single repository failure
- API error rate > 10%
- > 20% of users affected

**P3 - Medium** ⚡

- Minor feature non-functional
- Performance degradation < 50%
- Worker pool partially degraded
- API error rate 5-10%
- > 5% of users affected

**P4 - Low** 📝

- UI/UX issues
- Typos or documentation errors
- Non-critical bugs
- < 5% of users affected

______________________________________________________________________

## Escalation Paths

### On-Call Structure

**Primary On-Call Engineer**

- **Response Time**: 15 minutes (P1), 1 hour (P2)
- **Authority**: Can execute recovery procedures, restart services
- **Escalation**: Escalates to Tech Lead if unresolved after 1 hour

**Tech Lead**

- **Response Time**: 30 minutes (P1), 2 hours (P2)
- **Authority**: Can approve drastic measures, coordinate team response
- **Escalation**: Escalates to Engineering Manager if business impact > $10k

**Engineering Manager**

- **Response Time**: 1 hour (P1 only)
- **Authority**: Can authorize external communication, customer refunds
- **Escalation**: Escalates to CTO for security incidents

### Contact Information

**On-Call Rotation**

- Schedule: https://on-call.company.com/schedule/mahavishnu
- Phone: +1-XXX-XXX-XXXX (on-call phone)
- Slack: #oncall-mahavishnu

**Escalation Chain**

1. **On-Call Engineer** → Slack: @oncall-mahavishnu
1. **Tech Lead** → Slack: @tech-lead, Phone: +1-XXX-XXXX
1. **Engineering Manager** → Slack: @eng-manager, Phone: +1-XXX-XXXX
1. **CTO** → Slack: @cto (P1 or security only)

### External Communication

**Customer Communication**

- **P1**: Within 30 minutes via status page + email
- **P2**: Within 2 hours via status page
- **P3/P4**: Next release notes or status page update

**Status Page**: https://status.mahavishnu.com
**Incident Blog**: https://blog.mahavishnu.com/incidents

______________________________________________________________________

## Common Incident Scenarios

### Scenario 1: High CPU/Memory Usage

**Symptoms**

- Alerts: CPU > 80%, Memory > 80%
- Slow response times
- Worker pool exhaustion

**Diagnosis**

```bash
# Check system resources
top -o cpu
htop

# Check Mahavishnu process
ps aux | grep mahavishnu
curl http://localhost:8680/health

# Check worker status
mahavishnu pool health
mahavishnu pool list

# Check logs
tail -f /var/log/mahavishnu/mcp.log | grep ERROR
```

**Root Causes**

1. Memory leak in worker
1. Infinite loop in adapter
1. Large request processing
1. Worker pool not scaling

**Recovery**

```bash
# 1. Restart Mahavishnu service
sudo systemctl restart mahavishnu-mcp

# 2. Or scale worker pool
mahavishnu pool scale <pool-id> --target 10

# 3. Clear worker cache
mahavishnu pool flush-cache <pool-id>

# 4. Monitor recovery
watch -n 5 'curl -s http://localhost:8680/health | jq .'
```

**Prevention**

- Set up memory profiling
- Add circuit breakers
- Configure auto-scaling
- Regular load testing

______________________________________________________________________

### Scenario 2: Database Connection Pool Exhausted

**Symptoms**

- Error: "Pool exhausted" in logs
- API errors: 500 Internal Server Error
- Slow database queries

**Diagnosis**

```bash
# Check Session-Buddy database
cd /Users/les/Projects/session-buddy
sqlite3 data/sessions.db "SELECT COUNT(*) FROM sessions"

# Check active connections
lsof -i :8678 | grep ESTABLISHED | wc -l

# Check connection pool status
curl http://localhost:8678/mcp -X POST -H "Content-Type: application/json" -d '{
  "method": "tools/call",
  "params": {"name": "get_statistics"}
}'

# Check slow queries
grep "slow query" /var/log/session-buddy/app.log | tail -20
```

**Root Causes**

1. Too many concurrent requests
1. Queries not releasing connections
1. Connection leaks
1. Database lock contention

**Recovery**

```bash
# 1. Restart Session-Buddy (clears connections)
cd /Users/les/Projects/session-buddy
pkill -f session-buddy
python -m session_buddy.mcp &

# 2. Reduce connection pool size
# Edit settings/local.yaml:
# database:
#   pool_size: 5  # Reduce from 10

# 3. Clear old sessions
sqlite3 data/sessions.db "DELETE FROM sessions WHERE created_at < datetime('now', '-7 days')"

# 4. Restart Mahavishnu
sudo systemctl restart mahavishnu-mcp
```

**Prevention**

- Configure connection pool limits
- Add connection timeout
- Implement connection health checks
- Archive old sessions regularly

______________________________________________________________________

### Scenario 3: MCP Server Not Responding

**Symptoms**

- Error: "Connection refused" to MCP port
- Health check failing
- Tools not accessible

**Diagnosis**

```bash
# Check if MCP server is running
ps aux | grep mahavishnu

# Check MCP port
lsof -i :8680
netstat -an | grep 8680

# Check health endpoint
curl http://localhost:8680/health
curl http://localhost:8680/mcp -X POST -H "Content-Type: application/json" -d '{
  "jsonrpc": "2.0",
  "method": "tools/list",
  "id": 1
}'

# Check logs
tail -100 /var/log/mahavishnu/mcp.log
journalctl -u mahavishnu-mcp -n 100
```

**Root Causes**

1. MCP server crashed
1. Port already in use
1. Configuration error
1. Missing dependencies

**Recovery**

```bash
# 1. Check error logs
tail -50 /var/log/mahavishnu/error.log

# 2. Fix configuration if needed
cd /Users/les/Projects/mahavishnu
python -m mahavishnu.core.config --validate

# 3. Restart MCP server
pkill -f mahavishnu
python -m mahavishnu.mcp start

# 4. Or use systemd
sudo systemctl restart mahavishnu-mcp

# 5. Verify health
curl http://localhost:8680/health
mahavishnu mcp health
```

**Prevention**

- Add process monitoring (monit, supervisord)
- Configure automatic restart
- Add health check alerts
- Validate configuration on startup

______________________________________________________________________

### Scenario 4: Rate Limiting Too Aggressive

**Symptoms**

- Error: "Rate limit exceeded" for legitimate users
- API 429 responses increasing
- User complaints

**Diagnosis**

```bash
# Check rate limit stats
curl http://localhost:8680/mcp -X POST -H "Content-Type: application/json" -d '{
  "method": "tools/call",
  "params": {"name": "get_rate_limit_stats"}
}'

# Check rate limit configuration
grep -A 10 "rate_limit" settings/mahavishnu.yaml

# Check who is being rate limited
grep "rate limit exceeded" /var/log/mahavishnu/access.log | tail -20
```

**Root Causes**

1. Rate limits too strict
1. Burst size too small
1. Shared IP address (NAT, proxy)
1. Bot attack consuming quota

**Recovery**

```bash
# 1. Temporarily disable rate limiting (emergency only)
# Edit settings/mahavishnu.yaml:
# rate_limiting_enabled: false

# 2. Increase rate limits
# Edit settings/mahavishnu.yaml:
# rate_limit:
#   per_minute: 120  # Increase from 60
#   burst_size: 20   # Increase from 10

# 3. Whitelist legitimate IPs
# Edit settings/mahavishnu.yaml:
# rate_limit_whitelist:
#   - 192.168.1.100
#   - 10.0.0.0/8

# 4. Restart Mahavishnu
sudo systemctl restart mahavishnu-mcp
```

**Prevention**

- Monitor rate limit metrics
- Set up alerts for high 429 rate
- Use user-based rate limiting
- Implement rate limit bypass for admin users

______________________________________________________________________

### Scenario 5: Backup Failure

**Symptoms**

- Alert: "Backup failed" from monitoring
- Last successful backup > 24 hours ago
- Backup verification failing

**Diagnosis**

```bash
# Check backup logs
tail -100 /var/log/mahavishnu/backup.log

# Check backup directory
ls -lh /backup/mahavishnu/
du -sh /backup/mahavishnu/*

# Check disk space
df -h /backup

# Verify backup integrity
python -m mahavishnu.scripts.backup_manager --verify latest

# Check backup configuration
cat settings/backup.yaml
```

**Root Causes**

1. Disk full
1. Database locked during backup
1. Backup script permission error
1. Network issue (remote backup)

**Recovery**

```bash
# 1. Clear disk space if needed
sudo rm -rf /backup/mahavishnu/old_*

# 2. Fix permissions
sudo chmod +x /Users/les/Projects/mahavishnu/scripts/backup_manager.py

# 3. Manually trigger backup
cd /Users/les/Projects/mahavishnu
python -m mahavishnu.scripts.backup_manager --backup

# 4. Verify backup
python -m mahavishnu.scripts.backup_manager --verify latest

# 5. Check backup retention
python -m mahavishnu.scripts.backup_manager --list
```

**Prevention**

- Monitor disk space alerts
- Test backup restoration monthly
- Configure multiple backup destinations
- Set up backup failure alerts

______________________________________________________________________

### Scenario 6: Security Incident (Suspected Attack)

**Symptoms**

- Unusual traffic patterns
- Auth failures increasing
- Suspicious log entries
- DDoS attack indicators

**Diagnosis**

```bash
# Check request patterns
tail -10000 /var/log/mahavishnu/access.log | awk '{print $1}' | sort | uniq -c | sort -rn | head -20

# Check auth failures
grep "auth failed" /var/log/mahavishnu/auth.log | tail -50

# Check for SQL injection attempts
grep -i "union select" /var/log/mahavishnu/access.log

# Check rate limit violations
grep "rate limit" /var/log/mahavishnu/access.log | tail -50

# Check for suspicious user agents
grep -E "bot|crawler|spider" /var/log/mahavishnu/access.log | tail -20

# Run security scan
cd /Users/les/Projects/mahavishnu
python monitoring/security_audit.py
```

**Root Causes**

1. Brute force attack
1. DDoS attack
1. SQL injection attempt
1. Unauthorized access attempt

**Recovery**

```bash
# 1. Enable strict rate limiting
# Edit settings/mahavishnu.yaml:
# rate_limit:
#   per_minute: 10
#   per_hour: 100
#   ban_duration: 3600

# 2. Block suspicious IPs
# Edit settings/mahavishnu.yaml:
# blocked_ips:
#   - 192.168.1.100
#   - 10.0.0.0/8

# 3. Enable authentication (if not already)
# Edit settings/mahavishnu.yaml:
# auth_enabled: true

# 4. Alert security team
slack-post "@security-team SUSPICIOUS ACTIVITY DETECTED" \
  --channel "#security-alerts"

# 5. Monitor and log all access
# Edit settings/mahavishnu.yaml:
# log_level: DEBUG
# audit_log_enabled: true

# 6. Restart Mahavishnu
sudo systemctl restart mahavishnu-mcp
```

**Prevention**

- Implement Web Application Firewall (WAF)
- Configure fail2ban for brute force
- Regular security audits
- Monitor for anomalies with ML

______________________________________________________________________

## Diagnostic Commands

### System Health

```bash
# Overall system status
mahavishnu mcp health
mahavishnu pool health

# Resource usage
top -o cpu
htop
df -h
free -h

# Service status
sudo systemctl status mahavishnu-mcp
sudo systemctl status session-buddy
sudo systemctl status akosha

# Port status
lsof -i :8680  # Mahavishnu
lsof -i :8678  # Session-Buddy
lsof -i :8682  # Akosha
```

### Database Health

```bash
# Session-Buddy SQLite
cd /Users/les/Projects/session-buddy
sqlite3 data/sessions.db ".tables"
sqlite3 data/sessions.db "SELECT COUNT(*) FROM sessions"
sqlite3 data/sessions.db "PRAGMA integrity_check"

# Akosha PostgreSQL
psql -h localhost -U akosha -d akosha_db -c "SELECT COUNT(*) FROM memories;"
psql -h localhost -U akosha -d akosha_db -c "SELECT pg_size_pretty(pg_database_size('akosha_db'));"
```

### Log Analysis

```bash
# Recent errors
grep ERROR /var/log/mahavishnu/*.log | tail -50

# Request rate
tail -10000 /var/log/mahavishnu/access.log | awk '{print $4}' | uniq -c

# Slow requests
grep "duration" /var/log/mahavishnu/access.log | awk -F= '{print $2}' | awk '$1 > 1000'

# Auth failures
grep "401\|403" /var/log/mahavishnu/access.log | tail -20

# Rate limit violations
grep "429" /var/log/mahavishnu/access.log | tail -20
```

### MCP Server Diagnostics

```bash
# List available tools
curl http://localhost:8680/mcp -X POST -H "Content-Type: application/json" -d '{
  "jsonrpc": "2.0",
  "method": "tools/list",
  "id": 1
}' | jq .

# Test tool invocation
curl http://localhost:8680/mcp -X POST -H "Content-Type: application/json" -d '{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "list_repos",
    "arguments": {}
  },
  "id": 1
}' | jq .

# Check pool status
mahavishnu pool list
mahavishnu pool health
```

______________________________________________________________________

## Recovery Procedures

### Service Restart

```bash
# 1. Stop Mahavishnu gracefully
mahavishnu mcp stop

# 2. Wait for shutdown (max 30 seconds)
sleep 10

# 3. Check process stopped
ps aux | grep mahavishnu

# 4. Start Mahavishnu
mahavishnu mcp start

# 5. Verify health
curl http://localhost:8680/health

# 6. Check logs
tail -f /var/log/mahavishnu/mcp.log
```

### Database Recovery

```bash
# 1. Stop services using database
sudo systemctl stop session-buddy
sudo systemctl stop akosha

# 2. Backup current database (even if corrupted)
cp data/sessions.db data/sessions.db.corrupted.$(date +%Y%m%d_%H%M%S)

# 3. Restore from backup
python -m mahavishnu.scripts.backup_manager --restore backup_20260201_120000.tar.gz

# 4. Verify integrity
sqlite3 data/sessions.db "PRAGMA integrity_check"

# 5. Start services
sudo systemctl start session-buddy
sudo systemctl start akosha

# 6. Verify operations
curl http://localhost:8678/mcp -X POST -H "Content-Type: application/json" -d '{
  "method": "tools/call",
  "params": {"name": "search_sessions"}
}'
```

### Rollback Deployment

```bash
# Docker rollback
docker stop mahavishnu
docker rm mahavishnu
docker start mahavishnu-old
docker rename mahavishnu-old mahavishnu

# Cloud Run rollback
gcloud run services update-traffic mahavishnu-mcp \
  --to-revisions=REVISION_PREVIOUS \
  --region us-central1

# Kubernetes rollback
kubectl rollout undo deployment/mahavishnu-mcp

# Verify rollback
curl http://localhost:8680/health
```

### Emergency Maintenance Mode

```bash
# 1. Enable maintenance page
# Edit settings/mahavishnu.yaml:
# maintenance_mode: true
# maintenance_message: "System under maintenance. Back in 30 minutes."

# 2. Stop accepting new requests
# (Mahavishnu will return 503 with maintenance message)

# 3. Complete maintenance tasks
# - Apply patches
# - Restart services
# - Restore backups
# etc.

# 4. Disable maintenance mode
# Edit settings/mahavishnu.yaml:
# maintenance_mode: false

# 5. Restart service
sudo systemctl restart mahavishnu-mcp
```

______________________________________________________________________

## Post-Incident Process

### 1. Incident Review Meeting

**Schedule**: Within 1 week of P1/P2 incidents
**Attendees**: On-call engineer, tech lead, engineering manager

**Agenda**:

1. Timeline of events
1. Root cause analysis
1. What went well
1. What could be improved
1. Action items

### 2. Post-Mortem Document

**Template**:

```markdown
# Incident Post-Mortem: [Title]

**Date**: [YYYY-MM-DD]
**Severity**: [P1/P2/P3/P4]
**Duration**: [X hours]
**Impact**: [Description]

## Summary
[Brief 2-3 sentence summary]

## Timeline
| Time (UTC) | Event |
|------------|-------|
| 14:30 | Alert triggered |
| 14:35 | On-call engineer paged |
| ... | ... |

## Root Cause
[Technical root cause]

## Resolution
[Steps taken to resolve]

## Impact
- [ ] Users affected
- [ ] Revenue impact
- [ ] Data loss
- [ ] SLA violation

## Action Items
- [ ] [Owner] Fix immediate issue
- [ ] [Owner] Prevent recurrence
- [ ] [Owner] Update documentation
```

### 3. Action Item Tracking

**Tools**: GitHub Issues, JIRA, Linear

**Categories**:

- **Fix**: Correct the immediate issue
- **Prevent**: Prevent recurrence (process, code, monitoring)
- **Improve**: Enhance detection or response
- **Document**: Update runbooks or documentation

**Follow-up**: Review action items in next sprint retrospective

### 4. Process Improvements

**Common Improvements**:

- Add missing alerts/monitoring
- Update runbook with new scenario
- Improve error messages
- Add automated recovery
- Conduct chaos engineering tests
- Update training materials

______________________________________________________________________

## Appendix

### Useful Tools

- **htop**: Interactive process viewer
- **lsof**: List open files/ports
- **jq**: JSON parser for CLI
- **tmux**: Terminal multiplexer for long-running commands
- **slack-cli**: Post alerts to Slack
- **pgtop**: PostgreSQL monitoring
- **sqlite3**: SQLite database administration

### Emergency Contacts

- **On-Call Phone**: +1-XXX-XXX-XXXX
- **Slack**: #oncall-mahavishnu
- **Incident Command**: #incident-YYYY-MM-DD
- **Status Page**: https://status.mahavishnu.com

### Related Documentation

- [Production Deployment Guide](PRODUCTION_DEPLOYMENT_GUIDE.md)
- [Maintenance Procedures](MAINTENANCE_PROCEDURES.md)
- [Monitoring Guide](../monitoring/MONITORING_GUIDE.md)

______________________________________________________________________

**Last Updated**: 2026-02-02
**Next Review**: 2026-03-02
**Maintained By**: DevOps Team
