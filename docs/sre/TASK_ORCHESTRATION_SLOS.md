# Task Orchestration SLI/SLO Definitions

**Service**: Mahavishnu Task Orchestration System (MTOS)
**Version**: 1.0
**Last Updated**: 2026-02-18
**Next Review**: 2026-03-18

---

## Overview

This document defines the Service Level Indicators (SLIs) and Service Level Objectives (SLOs) for the Mahavishnu Task Orchestration System. These targets are based on industry best practices and aligned with business requirements for developer productivity and workflow reliability.

**Key Principles**:
- SLOs are **targets**, not guarantees
- Error budgets enable **risk-aware innovation**
- SLIs are **measured**, not guessed
- SLO breaches trigger **incident response**

---

## Service Level Indicators (SLIs)

### 1. Task Creation Latency

**Description**: Time from receiving task creation request to successful database commit.

**Measurement**:
```python
# Client-side timing
start_time = time.time()
task = await task_orchestrator.create_task(description)
latency_ms = (time.time() - start_time) * 1000

# Metric: task_creation_duration_seconds
labels = {
    "status": "success" | "error",
    "repository": "session-buddy" | "mahavishnu" | ...,
    "priority": "low" | "medium" | "high" | "critical",
    "source": "manual" | "github" | "gitlab",
}
```

**Data Sources**:
- Prometheus histogram metric: `task_creation_duration_seconds`
- OpenTelemetry span: `task_orchestrator.create_task`
- Query: `histogram_quantile(0.99, sum(rate(task_creation_duration_seconds_bucket[5m])) by (le))`

**SLO Targets**:

| Percentile | Target | Rationale |
|-----------|--------|-----------|
| **p50** | <50ms | Median user experience |
| **p95** | <100ms | 95% of users see this performance |
| **p99** | <500ms | Nearly all users, allows for occasional complex NLP parsing |

---

### 2. Task Query Latency

**Description**: Time from receiving task query request to returning results.

**Measurement**:
```python
# Query methods
await task_store.list_tasks(filters)      # List operations
await task_store.get_task(task_id)        # Get single task
await akosha.semantic_search(query)       # Semantic search
```

**Data Sources**:
- Prometheus histogram metric: `task_query_duration_seconds`
- OpenTelemetry span: `task_store.{list,get,search}`
- Query by method: `sum(rate(task_query_duration_seconds_bucket{method="semantic"}[5m])) by (le)`

**SLO Targets**:

| Percentile | Target | Rationale |
|-----------|--------|-----------|
| **p50** | <20ms | Fast queries for single task retrieval |
| **p95** | <100ms | Acceptable for complex filtered queries |
| **p99** | <200ms | Semantic search with embedding similarity |

---

### 3. Task Service Availability

**Description**: Percentage of successful task operations (create, read, update, delete).

**Measurement**:
```python
# Success rate calculation
success_count = task_operations_total{status="success"}
total_count = task_operations_total
availability = success_count / total_count * 100

# Metric: task_availability_percent
# Query: sum(rate(task_operations_total{status="success"}[5m])) /
#        sum(rate(task_operations_total[5m])) * 100
```

**Data Sources**:
- Prometheus counter metric: `task_operations_total{status, operation}`
- OpenTelemetry span status
- Health check endpoint: `/health` (200 OK)

**SLO Targets**:

| Time Window | Target | Allowable Downtime | Rationale |
|------------|--------|-------------------|-----------|
| **Monthly** | 99.9% | 43 minutes/month | Balances reliability with development velocity |
| **Weekly** | 99.95% | 10 minutes/week | Tighter window for faster feedback |
| **Daily** | 99.98% | 1.7 minutes/day | Very high daily reliability |

**Error Budget**:
- Monthly budget: **43 minutes**
- Burn rate alerting:
  - **Warning** at 2x burn rate (86 minutes/month used)
  - **Critical** at 5x burn rate (215 minutes/month used)
- **Feature freeze** when budget <10% (4.3 minutes remaining)

---

### 4. Data Durability

**Description**: Probability of permanently losing task data.

**Measurement**:
```python
# Measured via backup/restore testing
- Backup success rate: 100% (all backups complete successfully)
- Backup integrity: 100% (all backups pass PRAGMA integrity_check)
- Restore testing: 100% (weekly automated restore tests pass)

# Metric: backup_success_total, restore_test_success_total
```

**Data Sources**:
- Backup system logs
- Automated restore test results
- Database integrity checks

**SLO Targets**:

| Metric | Target | Rationale |
|--------|--------|-----------|
| **Annual durability** | 99.999% | 5 minutes data loss/year (industry standard) |
| **Backup success** | 100% | All backups must complete |
| **Restore testing** | 100% | Weekly tests must pass |

---

### 5. Task Workflow Success Rate

**Description**: Percentage of task workflows that complete successfully (from "start" to "complete").

**Measurement**:
```python
# Workflow lifecycle tracking
started_tasks = task_workflow_stage_total{stage="started"}
completed_tasks = task_workflow_stage_total{stage="completed"}
success_rate = completed_tasks / started_tasks * 100

# Metric: task_workflow_success_rate
```

**Data Sources**:
- Task status transitions in SQLite
- Workflow state machine events
- Quality gate results

**SLO Targets**:

| Metric | Target | Rationale |
|--------|--------|-----------|
| **Workflow completion** | 95% | Allow for cancellations and failures |
| **Quality gate pass** | 90% | Crackerjack gates may fail legitimately |

---

### 6. External Sync Availability

**Description**: Availability of GitHub/GitLab webhook processing and approval queue.

**Measurement**:
```python
# Webhook processing
webhooks_received = webhooks_received_total{source="github"}
webhooks_processed = webhooks_processed_total{source="github",status="success"}
availability = webhooks_processed / webhooks_received * 100

# Approval queue processing
queue_depth = task_approval_queue_depth
queue_processing_time = task_approval_queue_duration_seconds
```

**Data Sources**:
- Webhook endpoint metrics
- Approval queue depth gauge
- Processing time histograms

**SLO Targets**:

| Metric | Target | Rationale |
|--------|--------|-----------|
| **Webhook processing** | 99.5% | Allow for transient failures (retries) |
| **Queue depth** | <100 | Prevent overwhelming approval workflow |
| **Queue processing time** | <1 hour | Process approvals within business day |

---

### 7. Semantic Search Accuracy

**Description**: Relevance of semantic search results (user satisfaction proxy).

**Measurement**:
```python
# User feedback on search results
search_total = semantic_search_total
search_with_results = semantic_search_total{results>0}
result_rate = search_with_results / search_total * 100

# User feedback (click-through rate)
search_clicked = semantic_search_result_clicked_total
ctr = search_clicked / search_total * 100
```

**Data Sources**:
- Search result counts
- User interaction telemetry (clicks on results)
- Search refinement rate (users searching again immediately)

**SLO Targets**:

| Metric | Target | Rationale |
|--------|--------|-----------|
| **Results returned** | 95% | Most searches should find relevant tasks |
| **Click-through rate** | 50% | Half of searches result in user interaction |

---

## Service Level Objectives (SLOs) Summary

| SLI | Time Window | SLO | Error Budget | Burn Rate Alert |
|-----|-------------|-----|--------------|-----------------|
| **Task creation latency (p99)** | Rolling 28 days | <500ms | N/A (latency) | 10% of requests >500ms |
| **Task query latency (p95)** | Rolling 28 days | <100ms | N/A (latency) | 10% of requests >100ms |
| **Task availability** | Calendar month | 99.9% | 43 min/month | Warning: 2x, Critical: 5x |
| **Data durability** | Calendar year | 99.999% | 5 min/year | Any data loss = P0 incident |
| **Workflow success rate** | Rolling 28 days | 95% | 5% failure rate | <90% = investigate |
| **Webhook availability** | Calendar month | 99.5% | 3.6 hours/month | Warning: 2x, Critical: 5x |

---

## Error Budget Policy

### Error Budget Calculation

**Monthly Availability Budget**:
- Target: 99.9% availability
- Allowable downtime: 43 minutes/month
- Budget calculation: `43 minutes - (actual_downtime_in_minutes)`

**Example**:
```
Month: February 2026 (28 days)
Total minutes: 40,320 minutes
Allowable downtime: 40,320 * (1 - 0.999) = 40.32 minutes
Actual downtime: 25 minutes
Remaining budget: 40.32 - 25 = 15.32 minutes
Status: ✓ Within budget
```

### Error Budget Burn Rates

| Burn Rate | Definition | Alert Level | Action |
|-----------|-----------|-------------|--------|
| **1x** | Normal consumption | None | Continue normal operations |
| **2x** | Burning 2x faster than expected | Warning | Investigate reliability issues |
| **5x** | Burning 5x faster than expected | Critical | **Stop feature work**, fix reliability |
| **10x** | Emergency | Page on-call | All-hands-on-deck incident response |

### Error Budget Actions

| Budget Remaining | Status | Action |
|------------------|--------|--------|
| **>50%** (21+ min) | ✓ Healthy | Proceed with all feature work |
| **10-50%** (4-21 min) | ⚠ Warning | Prioritize reliability over features |
| **<10%** (<4 min) | 🛑 Critical | **Feature freeze**, reliability-only work |
| **0%** (0 min) | ❌ Breach | Incident response, postmortem required |

---

## Monitoring & Alerting

### Prometheus Metrics

```yaml
# Task creation latency
task_creation_duration_seconds:
  type: histogram
  buckets: [0.01, 0.05, 0.1, 0.5, 1.0, 5.0]
  labels: [status, repository, priority, source]

# Task query latency
task_query_duration_seconds:
  type: histogram
  buckets: [0.001, 0.01, 0.05, 0.1, 0.5, 1.0]
  labels: [method, status]

# Task operations
task_operations_total:
  type: counter
  labels: [operation, status]  # operation: create, read, update, delete

# Workflow stages
task_workflow_stage_total:
  type: counter
  labels: [stage, status]  # stage: started, completed, failed

# Availability
task_availability_percent:
  type: gauge
  labels: [time_window]  # time_window: daily, weekly, monthly

# Data durability
backup_success_total:
  type: counter
  labels: [status, storage]

restore_test_success_total:
  type: counter
  labels: [status]

# Webhook processing
webhooks_received_total:
  type: counter
  labels: [source, status]

# Approval queue
task_approval_queue_depth:
  type: gauge

task_approval_queue_duration_seconds:
  type: histogram
  buckets: [60, 300, 600, 1800, 3600]
```

### Alerting Rules

```yaml
groups:
  - name: task_slos_alerts
    interval: 30s
    rules:
      # SLO 1: Task creation latency (p99)
      - alert: TaskCreationLatencyHigh
        expr: |
          histogram_quantile(0.99,
            sum(rate(task_creation_duration_seconds_bucket[5m])) by (le)
          ) > 0.5
        for: 5m
        labels:
          severity: P2
          slo: "task_creation_latency_p99"
        annotations:
          summary: "Task creation latency exceeds SLO"
          description: "P99 latency {{ $value }}s exceeds 500ms threshold"

      # SLO 2: Task query latency (p95)
      - alert: TaskQueryLatencyHigh
        expr: |
          histogram_quantile(0.95,
            sum(rate(task_query_duration_seconds_bucket[5m])) by (le)
          ) > 0.1
        for: 5m
        labels:
          severity: P2
          slo: "task_query_latency_p95"
        annotations:
          summary: "Task query latency exceeds SLO"
          description: "P95 latency {{ $value }}s exceeds 100ms threshold"

      # SLO 3: Task availability (monthly)
      - alert: TaskAvailabilityLow
        expr: |
          (
            sum(rate(task_operations_total{status="success"}[30m])) /
            sum(rate(task_operations_total[30m]))
          ) < 0.999
        for: 10m
        labels:
          severity: P1
          slo: "task_availability_monthly"
        annotations:
          summary: "Task availability below SLO"
          description: "Availability {{ $value | humanizePercentage }} below 99.9%"

      # SLO 3: Error budget burn rate (warning)
      - alert: TaskErrorBudgetBurningWarning
        expr: |
          (
            (1 - (
              sum(rate(task_operations_total{status="success"}[30m])) /
              sum(rate(task_operations_total[30m]))
            )) / (1 - 0.999)
          ) > 2
        for: 10m
        labels:
          severity: P2
          slo: "error_budget_burn_rate"
        annotations:
          summary: "Error budget burning at 2x rate"
          description: "Current burn rate: {{ $value }}x normal"

      # SLO 3: Error budget burn rate (critical)
      - alert: TaskErrorBudgetBurningCritical
        expr: |
          (
            (1 - (
              sum(rate(task_operations_total{status="success"}[30m])) /
              sum(rate(task_operations_total[30m]))
            )) / (1 - 0.999)
          ) > 5
        for: 5m
        labels:
          severity: P0
          slo: "error_budget_burn_rate"
        annotations:
          summary: "Error budget burning at 5x rate - FEATURE FREEZE"
          description: "Current burn rate: {{ $value }}x normal. Stop all feature work."

      # SLO 5: Workflow success rate
      - alert: TaskWorkflowSuccessRateLow
        expr: |
          (
            sum(rate(task_workflow_stage_total{stage="completed",status="success"}[30m])) /
            sum(rate(task_workflow_stage_total{stage="started"}[30m]))
          ) < 0.90
        for: 15m
        labels:
          severity: P2
          slo: "workflow_success_rate"
        annotations:
          summary: "Task workflow success rate below 90%"
          description: "Success rate: {{ $value | humanizePercentage }}"

      # SLO 6: Approval queue backlog
      - alert: TaskApprovalQueueBacklog
        expr: task_approval_queue_depth > 100
        for: 15m
        labels:
          severity: P1
          slo: "approval_queue_depth"
        annotations:
          summary: "Task approval queue has large backlog"
          description: "{{ $value }} tasks awaiting approval"

      # Data durability: Backup failure
      - alert: TaskBackupFailed
        expr: |
          sum(rate(task_backup_total{status="failed"}[5m])) > 0
        for: 1m
        labels:
          severity: P0
          slo: "data_durability"
        annotations:
          summary: "Task backup failed"
          description: "Latest backup attempt failed"

      # Data durability: Restore test failure
      - alert: TaskRestoreTestFailed
        expr: |
          sum(rate(task_restore_test_total{status="failed"}[5m])) > 0
        for: 1m
        labels:
          severity: P0
          slo: "data_durability"
        annotations:
          summary: "Task restore test failed"
          description: "Automated restore test failed - data at risk"
```

---

## Dashboards

### Grafana Dashboard: Task SLO Overview

**Panels**:

1. **Task Availability (30d)**
   - Gauge: Current availability % vs 99.9% target
   - Time series: Availability over 30 days
   - Error budget: Remaining minutes

2. **Task Creation Latency (24h)**
   - Heatmap: Latency distribution
   - Percentiles: p50, p95, p99 lines
   - SLO indicator: P99 <500ms

3. **Task Query Latency (24h)**
   - Heatmap: Latency distribution by method
   - Percentiles: p50, p95, p99 lines
   - SLO indicator: P95 <100ms

4. **Workflow Success Rate (7d)**
   - Time series: Success rate % vs 95% target
   - Breakdown: By repository, by priority

5. **Error Budget Burn Rate**
   - Gauge: Current burn rate (1x, 2x, 5x)
   - Time series: Burn rate over 30 days
   - Status: Healthy/Warning/Critical

6. **Data Durability**
   - Backup success rate (30d)
   - Last backup timestamp
   - Restore test status

7. **External Sync**
   - Webhook processing rate
   - Approval queue depth
   - Queue processing time

---

## SLO Review Process

### Monthly SLO Review

**Attendees**: SRE team, Engineering manager, Task orchestration developers

**Agenda**:

1. **SLO Performance** (15 minutes)
   - Review each SLO performance vs target
   - Analyze trends (improving, degrading)
   - Identify outliers and root causes

2. **Error Budget Status** (10 minutes)
   - Current budget remaining
   - Burn rate analysis
   - Feature work impact

3. **Incidents & Breaches** (15 minutes)
   - Review SLO breaches
   - Discuss incidents and MTTR
   - Review postmortems and action items

4. **Adjustments** (10 minutes)
   - Consider SLO target changes
   - Adjust error budget policy
   - Update monitoring/alerting

5. **Action Items** (10 minutes)
   - Assign improvement tasks
   - Schedule follow-ups
   - Document decisions

### Quarterly SLO Calibration

**Attendees**: SRE team, Engineering leadership, Product management

**Agenda**:

1. **Business Requirements Review**
   - Has user base changed?
   - Have usage patterns shifted?
   - Are SLOs still aligned with business needs?

2. **Technical Capabilities Assessment**
   - Can we improve SLOs with architecture changes?
   - Are SLOs too aggressive (too many breaches)?
   - Are SLOs too loose (not driving quality)?

3. **Competitive Analysis**
   - How do our SLOs compare to industry?
   - Are we meeting user expectations?

4. **SLO Adjustments**
   - Adjust targets based on findings
   - Add/remove SLIs as needed
   - Update error budget policy

---

## Runbook: SLO Breach Response

### Immediate Actions (0-15 minutes)

1. **Verify breach**
   ```bash
   # Check current SLO status
   curl http://localhost:9091/metrics | grep task_availability
   ```

2. **Declare incident**
   - Create incident ticket (Linear/Jira)
   - Severity based on breach type:
     - Availability <99%: **P1**
     - Latency >2x SLO: **P2**
     - Error budget exhausted: **P0**

3. **Assess impact**
   ```bash
   # Check affected operations
   mahavishnu task stats --last 1h
   ```

4. **Notify stakeholders**
   - Slack: #sre-incidents
   - Email: eng-manager@example.com
   - Pager: if P0 incident

### Investigation (15-60 minutes)

1. **Identify root cause**
   - Check logs: `tail -f /var/log/mahavishnu/tasks.log`
   - Check metrics: `task_operations_total{status="error"}`
   - Check dependencies: SQLite, Akosha, Session-Buddy health

2. **Mitigate impact**
   - Restart failing services
   - Scale resources if needed
   - Disable problematic features

3. **Implement fix**
   - Deploy hotfix if needed
   - Roll back recent changes
   - Update runbooks

### Post-Incident (1-7 days)

1. **Calculate error budget consumed**
   ```python
   downtime_minutes = incident_duration_minutes / 60
   error_budget_consumed = downtime_minutes
   remaining_budget = 43 - error_budget_consumed
   ```

2. **Determine feature freeze**
   - If remaining_budget < 10%: **Feature freeze**
   - Notify engineering team
   - Cancel non-urgent feature work

3. **Write postmortem**
   - Document timeline
   - Root cause analysis
   - Action items
   - Prevention measures

4. **Update SLOs if needed**
   - Are targets realistic?
   - Do we need different metrics?
   - Should we adjust error budget?

---

## Appendix: SLO Calculation Examples

### Example 1: Monthly Availability Calculation

**February 2026 (28 days)**:

```
Total minutes: 28 * 24 * 60 = 40,320 minutes
SLO target: 99.9%
Allowable downtime: 40,320 * (1 - 0.999) = 40.32 minutes

Actual outages:
- Feb 5: 15 minutes (database restart)
- Feb 15: 8 minutes (deployment rollback)
- Feb 20: 5 minutes (network issue)
Total actual downtime: 28 minutes

Availability: (40,320 - 28) / 40,320 = 99.931%
Error budget remaining: 40.32 - 28 = 12.32 minutes (30.6%)
Status: Within budget ✓
```

### Example 2: Error Budget Burn Rate

**Current 30-minute window**:

```
Normal burn rate: 40.32 minutes / 28 days = 0.0016 minutes/minute
Current downtime rate: 5 minutes / 30 minutes = 0.167 minutes/minute
Burn rate: 0.167 / 0.0016 = 104x

Status: CRITICAL (burning at 104x normal rate)
Action: Page on-call, stop all feature work, investigate immediately
```

### Example 3: Latency SLO Calculation

**Task creation latency (last 28 days)**:

```
P99 latency calculation:
histogram_quantile(0.99,
  sum(rate(task_creation_duration_seconds_bucket[28d])) by (le)
)

Result: 425ms
SLO target: <500ms
Status: Within SLO ✓

P95 latency calculation:
histogram_quantile(0.95,
  sum(rate(task_creation_duration_seconds_bucket[28d])) by (le)
)

Result: 85ms
SLO target: <100ms
Status: Within SLO ✓
```

---

## Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-02-18 | 1.0 | Initial SLO definitions | SRE Team |

---

**Next Review**: 2026-03-18
**SLO Owner**: SRE Team
**Approval**: Engineering Manager
