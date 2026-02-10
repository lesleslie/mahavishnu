# Mahavishnu Service Level Agreement (SLA) & Service Level Objectives (SLO)

**Document Version**: 1.0
**Last Updated**: 2025-02-05
**Owner**: SRE Team
**Review Cycle**: Quarterly

---

## Table of Contents

1. [Overview](#overview)
2. [Service Level Agreement (SLA)](#service-level-agreement-sla)
3. [Service Level Objectives (SLOs)]#service-level-objectives-slos)
4. [Service Level Indicators (SLIs)](#service-level-indicators-slis)
5. [Error Budget Policy](#error-budget-policy)
6. [Monitoring & Alerting](#monitoring--alerting)
7. [Reporting & Review](#reporting--review)
8. [Compensation & Credits](#compensation--credits)
9. [Exclusions & Exceptions](#exclusions--exceptions)

---

## Overview

### Purpose

This document defines the service level commitments for the Mahavishnu Multi-Engine Orchestration Platform, ensuring reliable and predictable performance for production operations.

### Scope

This SLA applies to:
- **Mahavishnu Core Services**: Workflow orchestration, adapter management, pool execution
- **MCP Server Operations**: Session management, tool integration, message handling
- **Data Services**: State management, caching, temporal memory
- **API Endpoints**: REST and gRPC interfaces for external integration

### Service Availability

- **Production Environment**: 24x7x365 monitoring and support
- **Development/Staging**: Best effort, no formal SLA commitment
- **Maintenance Windows**: Scheduled maintenance announced 7 days in advance

---

## Service Level Agreement (SLA)

### 1. Availability Commitment

**Target**: 99.9% monthly uptime

**Calculation**:
```
Availability = (Total Minutes - Downtime Minutes) / Total Minutes × 100
```

**Allowable Downtime**:
- Per Month: 43.2 minutes
- Per Quarter: 129.6 minutes
- Per Year: 8.76 hours

### 2. Support Response Times

| Severity Level | Response Time | Resolution Target | Examples |
|----------------|---------------|-------------------|----------|
| **P1 - Critical** | 1 hour | 4 hours | Complete service outage, data loss |
| **P2 - High** | 4 hours | 1 business day | Major feature degradation, performance impact |
| **P3 - Medium** | 8 hours | 2 business days | Partial feature unavailable, minor bugs |
| **P4 - Low** | 24 hours | 1 week | Cosmetic issues, documentation errors |

**Business Days**: Monday - Friday, 9:00 AM - 5:00 PM UTC

### 3. Scheduled Maintenance

**Notification**: 7 days advance notice via email and status page

**Windows**:
- **Standard Maintenance**: Sundays, 02:00 - 04:00 UTC
- **Emergency Maintenance**: As needed with 2-hour notice (P1 incidents only)

**Maintenance Activities**:
- Database upgrades and migrations
- Security patches
- Infrastructure scaling
- Feature deployments

**Exclusions from Downtime Calculation**:
- Scheduled maintenance windows
- Customer-caused outages
- Third-party service failures outside Mahavishnu control
- Force majeure events

### 4. Data Durability & Recovery

**Durability**: 99.999999999% (11 9's) for stored data

**Backup & Recovery**:
- **Backup Frequency**: Every 15 minutes (point-in-time recovery)
- **Retention**: 30 days for production, 7 days for staging
- **RPO (Recovery Point Objective)**: < 15 minutes
- **RTO (Recovery Time Objective)**: < 1 hour for critical systems

---

## Service Level Objectives (SLOs)

### 1. Availability SLO

**Target**: 99.9% uptime (30-day rolling window)

**Measurement**:
```
Availability = Successful Requests / Total Requests × 100
```

**Status Definitions**:
- **Healthy**: ≥ 99.9% (within error budget)
- **Warning**: 99.5% - 99.9% (error budget depleting)
- **Critical**: < 99.5% (error budget exhausted)

### 2. Latency SLO

**Targets**:
- **p50 (median)**: < 50ms
- **p95**: < 100ms
- **p99**: < 200ms

**Measurement Period**: Rolling 24-hour window

**Request Types**:
- API calls (REST/gRPC)
- MCP tool invocations
- Workflow status queries
- Pool operations

### 3. Error Rate SLO

**Target**: < 0.1% (1 error per 1000 requests)

**Error Definition**:
- HTTP 5xx responses
- gRPC INTERNAL/UNAVAILABLE errors
- Unhandled exceptions
- Workflow execution failures

**Exclusions**:
- Client authentication failures (4xx)
- Rate limit errors (429)
- Malformed requests (400)

### 4. Throughput SLO

**Target**: 1000 requests/second sustained

**Burst Capacity**: 2000 requests/second for 5 minutes

**Measurement**:
```
Throughput = Total Requests / Time Window (seconds)
```

### 5. Data Quality SLO

**Consistency**: 99.99% (eventual consistency within 1 second)

**Integrity**: 100% (no data corruption)

**Freshness**: < 100ms for cached data, < 1s for database queries

---

## Service Level Indicators (SLIs)

### 1. Request Success Rate

**Metric**: `mahavishnu_requests_success_total / mahavishnu_requests_total`

**Labels**:
- `adapter`: {llamaindex, prefect, agno}
- `operation`: {workflow, query, mutation}
- `status`: {success, error}

**Calculation**:
```python
success_rate = successful_requests / total_requests
```

### 2. Request Latency

**Metrics**:
- `mahavishnu_request_duration_seconds` (Histogram)
  - Buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]

**Percentiles**: p50, p95, p99, p99.9

**Query Example** (PromQL):
```promql
histogram_quantile(0.95,
  sum(rate(mahavishnu_request_duration_seconds_bucket[5m])) by (le, adapter)
)
```

### 3. System Availability

**Metric**: `mahavishnu_up` (Gauge)

**Definition**: 1 if service is healthy, 0 if unhealthy

**Health Checks**:
- `/health` - Liveness probe
- `/ready` - Readiness probe
- `/health/components` - Deep component health

### 4. Error Budget Remaining

**Metric**: `mahavishnu_error_budget_remaining_percent` (Gauge)

**Calculation**:
```python
error_budget = (1 - slo_target) * 100
error_budget_remaining = error_budget - (actual_downtime * 100 / total_time)
```

**Example** (99.9% SLO):
```
Error Budget = 0.1% per month = 43.2 minutes
If 10 minutes of downtime occurred: 43.2 - 10 = 33.2 minutes remaining
```

### 5. Data Durability

**Metrics**:
- `mahavishnu_data_objects_total` (Counter)
- `mahavishnu_data_corruption_events_total` (Counter)

**Calculation**:
```python
durability = (1 - corruption_events / total_objects) * 100
```

---

## Error Budget Policy

### 1. Error Budget Calculation

**Monthly Error Budget** (99.9% SLO):
```
30 days × 24 hours × 60 minutes = 43,200 minutes/month
43,200 × 0.001 = 43.2 minutes downtime budget
```

**Real-Time Budget Tracking**:
```python
remaining_budget = max_budget - accumulated_downtime
budget_percent = (remaining_budget / max_budget) * 100
```

### 2. Error Budget Burn Rates

| Burn Rate | Time to Exhaust Budget | Action Required |
|-----------|------------------------|-----------------|
| 1x | 30 days | Normal operations |
| 2x | 15 days | Monitor closely |
| 5x | 6 days | **FREEZE FEATURE DEPLOYMENTS** |
| 10x | 3 days | **ALL HANDS ON DECK** |

**Burn Rate Calculation**:
```python
burn_rate = current_error_rate / slo_error_rate
```

### 3. Error Budget Policy Enforcement

**When Error Budget > 50%**:
- Normal feature deployment pace
- Standard change management
- Innovation encouraged

**When Error Budget 25-50%**:
- Reduce deployment frequency by 50%
- Require additional testing for changes
- Postmortem for all incidents

**When Error Budget < 25%**:
- **FREEZE all non-critical deployments**
- Emergency changes require CTO approval
- Daily reliability standups
- Focus on reliability work only

**When Error Budget = 0% (Exhausted)**:
- **COMPLETE FEATURE FREEZE**
- Only P0/P1 fixes allowed
- Root cause analysis required for all incidents
- Reliability sprint initiated

### 4. Error Budget Recovery

**Recovery Actions**:
1. Identify and fix root cause
2. Implement monitoring and alerts
3. Conduct blameless postmortem
4. Update runbooks and playbooks
5. Verify fix with load testing
6. Gradually resume deployments

**Budget Restoration**:
- Error budget resets at the start of each billing month
- No "carryover" or "banking" of error budget

---

## Monitoring & Alerting

### 1. Monitoring Architecture

**Stack**:
- **Metrics**: Prometheus + OpenTelemetry
- **Visualization**: Grafana dashboards
- **Alerting**: Alertmanager + PagerDuty
- **Logging**: Structured JSON logs + correlation IDs
- **Tracing**: OpenTelemetry distributed tracing

### 2. Critical Alerts (P1)

**Availability Alerts**:
```yaml
- alert: HighErrorRate
  expr: rate(mahavishnu_errors_total[5m]) / rate(mahavishnu_requests_total[5m]) > 0.005
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "Error rate exceeds 0.5% (P1)"
    description: "Error rate is {{ $value | humanizePercentage }}"
```

**Uptime Alerts**:
```yaml
- alert: ServiceDown
  expr: up{job="mahavishnu"} == 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Mahavishnu service is down (P1)"
```

### 3. Warning Alerts (P2)

**Latency Alerts**:
```yaml
- alert: HighLatency
  expr: histogram_quantile(0.95, rate(mahavishnu_request_duration_seconds_bucket[5m])) > 0.2
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "p95 latency exceeds 200ms (P2)"
```

**Memory Alerts**:
```yaml
- alert: HighMemoryUsage
  expr: mahavishnu_memory_usage_bytes / mahavishnu_memory_limit_bytes > 0.85
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Memory usage exceeds 85% (P2)"
```

### 4. Dashboard URLs

- **Overview**: https://grafana.internal/d/overview
- **Performance**: https://grafana.internal/d/performance
- **Reliability**: https://grafana.internal/d/reliability
- **Capacity**: https://grafana.internal/d/capacity

---

## Reporting & Review

### 1. Monthly SLO Report

**Contents**:
- Actual availability vs. target
- Error budget consumption and remaining
- Incident summary (P1, P2, P3)
- MTTR (Mean Time To Recovery)
- Top reliability issues
- Improvement roadmap

**Distribution**:
- Engineering leadership
- Product management
- Customer support
- SRE team

### 2. Quarterly Business Review

**Agenda**:
- SLO performance trends
- Error budget analysis
- Reliability investment ROI
- Customer impact assessment
- SLA adjustments (if needed)

### 3. Annual SLO Calibration

**Review Items**:
- Are SLO targets appropriate?
- Should we increase/decrease availability commitment?
- Are SLIs accurately measuring user experience?
- Industry benchmarking
- Cost/benefit analysis of higher targets

---

## Compensation & Credits

### 1. SLA Credit Calculation

**Credit Tiers**:

| Monthly Availability | Credit Percentage |
|---------------------|-------------------|
| < 99.0% | 25% of monthly fees |
| < 98.0% | 50% of monthly fees |
| < 95.0% | 100% of monthly fees |

**Calculation**:
```python
credit = monthly_fee * credit_percentage
```

### 2. Credit Request Process

1. Customer submits support ticket within 30 days
2. SRE team verifies SLA violation
3. Credits applied within 2 business days
4. Credits applied to future invoices (no cash refunds)

### 3. Exclusions from Credits

- Scheduled maintenance windows
- Third-party service failures
- Customer-caused outages
- Beta/experimental features
- Development/staging environments

---

## Exclusions & Exceptions

### 1. SLA Exclusions

The following are excluded from SLA calculations:

**Planned Downtime**:
- Scheduled maintenance (with 7-day notice)
- Infrastructure upgrades
- Security patches

**Third-Party Failures**:
- Cloud provider outages (AWS, GCP, Azure)
- MCP server failures (external dependencies)
- Network failures outside our control

**Customer Actions**:
- Misconfigured workflows
- Exceeded quota/limits
- Malformed API requests
- Authentication failures

**Force Majeure**:
- Natural disasters
- War, terrorism, civil unrest
- Government actions
- Pandemics

### 2. Exception Process

**Requesting Exception**:
1. Submit written request to SRE team
2. Provide business justification
3. Risk assessment and mitigation plan
4. Approval by engineering leadership

**Exception Criteria**:
- Critical business need
- Temporary workaround available
- Customer impact is minimal
- Clear timeline for resolution

---

## Appendix

### A. Related Documents

- [SRE Runbook](/docs/runbooks/)
- [Incident Management](/docs/incident-management.md)
- [Monitoring Architecture](/docs/monitoring-architecture.md)
- [Capacity Planning](/docs/capacity-planning.md)

### B. Contact Information

**SRE Team**: sre@mahavishnu.internal
**On-Call**: +1-555-SRE-HELP (PagerDuty)
**Status Page**: https://status.mahavishnu.internal

### C. Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2025-02-05 | 1.0 | Initial SLA/SLO definition | SRE Team |

---

**Document Control**: This document is reviewed quarterly and approved by the VP of Engineering. Any changes require approval from both SRE leadership and Engineering management.
