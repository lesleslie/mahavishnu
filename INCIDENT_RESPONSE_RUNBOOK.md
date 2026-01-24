# Mahavishnu Incident Response Runbook

## Overview

This runbook provides guidance for responding to incidents involving the Mahavishnu orchestrator system.

## Incident Classification

### Critical (P0)
- Complete system outage
- Security breach
- Data corruption
- Response time: Immediate (within 15 minutes)

### High (P1)
- Partial system degradation
- Performance issues affecting multiple users
- Failed workflows affecting business operations
- Response time: Within 1 hour

### Medium (P2)
- Minor functionality issues
- Single-user impacting problems
- Response time: Within 4 hours

### Low (P3)
- Cosmetic issues
- Feature requests
- Response time: Within 24 hours

## Common Incidents and Remediation

### Authentication Failures
**Symptoms**: Users unable to authenticate via JWT
**Causes**: 
- Expired or invalid JWT tokens
- Incorrect JWT secret configuration
- Clock skew between systems

**Remediation Steps**:
1. Check `MAHAVISHNU_AUTH_SECRET` environment variable
2. Verify JWT token validity and expiration
3. Restart services if configuration was updated
4. Clear user authentication caches

### Workflow Failures
**Symptoms**: Workflows failing to execute or hanging
**Causes**:
- Circuit breaker tripped
- Rate limiting from LLM providers
- Resource exhaustion
- Network connectivity issues

**Remediation Steps**:
1. Check circuit breaker status in logs
2. Verify LLM API keys and quotas
3. Review resource utilization (CPU, memory, disk)
4. Check network connectivity to external services
5. Restart workflow processing if needed

### Performance Degradation
**Symptoms**: Slow response times, timeouts
**Causes**:
- High concurrent workload exceeding limits
- Large repository processing
- External service delays

**Remediation Steps**:
1. Check `max_concurrent_workflows` setting
2. Review repository sizes being processed
3. Monitor external service response times
4. Scale resources if needed

### MCP Server Issues
**Symptoms**: MCP server unavailable or rejecting connections
**Causes**:
- Port conflicts
- Network configuration issues
- Authentication problems

**Remediation Steps**:
1. Check if port 3000 is available
2. Verify network configuration
3. Check authentication settings
4. Restart MCP server

## Escalation Procedures

### Level 1 Support
- Basic troubleshooting
- Configuration verification
- Standard restart procedures

### Level 2 Support
- Advanced debugging
- Log analysis
- Performance tuning

### Level 3 Support
- Architecture-level issues
- Security incidents
- Data recovery

## Communication Templates

### Outage Notification
```
Subject: Mahavishnu Service Outage - P0 Incident

We are experiencing a complete outage of the Mahavishnu orchestrator service.
Estimated time to resolution: [TIME]
Status page: [LINK]
```

### Resolution Notification
```
Subject: Mahavishnu Service Restored - P0 Incident Resolved

The Mahavishnu orchestrator service has been restored.
Root cause: [CAUSE]
Resolution: [SOLUTION]
```

## Post-Incident Procedures

1. Document the incident in the tracking system
2. Conduct a post-mortem analysis
3. Update runbook with lessons learned
4. Implement preventive measures
5. Communicate findings to stakeholders