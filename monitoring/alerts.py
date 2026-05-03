"""AlertManager configuration for current Mahavishnu monitoring.

This module defines alert rules that align with metrics that are actually
emitted and scraped by the repository's current Prometheus topology.
"""

from __future__ import annotations

# ============================================================================
# Alert Rule Definitions
# ============================================================================

alert_rules = """
groups:
  - name: mahavishnu_core
    interval: 30s
    rules:
      - alert: HighToolErrorRate
        expr: |
          (
            sum(rate(mcp_tool_calls_total{status="error"}[5m]))
            /
            sum(rate(mcp_tool_calls_total[5m]))
          ) > 0.05
        for: 5m
        labels:
          severity: critical
          service: mahavishnu
        annotations:
          summary: "MCP tool error rate above 5%"
          description: "Mahavishnu MCP tool error rate is {{ $value | humanizePercentage }}"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/incident-response"

      - alert: ElevatedToolErrorRate
        expr: |
          (
            sum(rate(mcp_tool_calls_total{status="error"}[5m]))
            /
            sum(rate(mcp_tool_calls_total[5m]))
          ) > 0.02
        for: 5m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "MCP tool error rate above 2%"
          description: "Mahavishnu MCP tool error rate is {{ $value | humanizePercentage }}"

      - alert: HighToolP95Latency
        expr: |
          histogram_quantile(
            0.95,
            sum by (le) (rate(mcp_tool_duration_seconds_bucket[5m]))
          ) > 10
        for: 5m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "MCP tool P95 latency above 10 seconds"
          description: "Mahavishnu MCP tool P95 latency is {{ $value }}s"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/performance-tuning"

      - alert: HighWorkflowFailureRate
        expr: |
          (
            sum(rate(mahavishnu_workflows_total{status="failed"}[10m]))
            /
            sum(rate(mahavishnu_workflows_total{status=~"started|completed|failed|cancelled|timeout"}[10m]))
          ) > 0.10
        for: 10m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "Workflow failure rate above 10%"
          description: "Mahavishnu workflow failure rate is {{ $value | humanizePercentage }}"

      - alert: InsufficientWorkers
        expr: |
          sum(pool_workers_active{pool_type="mahavishnu"}) < 1
        for: 5m
        labels:
          severity: critical
          service: mahavishnu
        annotations:
          summary: "No Mahavishnu pool workers available"
          description: "Mahavishnu pool worker count is {{ $value }}"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/worker-scaling"

      - alert: LowWorkerCount
        expr: |
          sum(pool_workers_active{pool_type="mahavishnu"}) < 2
        for: 5m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "Mahavishnu worker count below 2"
          description: "Mahavishnu pool worker count is {{ $value }}"

      - alert: HighQueueBacklog
        expr: |
          max(mahavishnu_workflow_queue_depth{service="mahavishnu"}) > 25
        for: 5m
        labels:
          severity: critical
          service: mahavishnu
        annotations:
          summary: "Workflow queue depth above 25"
          description: "{{ $value }} workflows are waiting in the in-process queue"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/scale-horizontally"

      - alert: BuildingQueue
        expr: |
          max(mahavishnu_workflow_queue_depth{service="mahavishnu"}) > 10
        for: 10m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "Workflow queue is building"
          description: "{{ $value }} workflows are waiting in the in-process queue"

      - alert: DependencyHealthDegraded
        expr: |
          min(mahavishnu_dependency_health_status) < 1
        for: 10m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "A Mahavishnu dependency is degraded"
          description: "Dependency {{ $labels.dependency }} health gauge is {{ $value }}"

      - alert: SessionBuddyBridgeFailing
        expr: |
          sum(rate(bodai_bridge_poll_errors_total{source_service="session-buddy"}[10m])) > 0
        for: 10m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "Session-Buddy bridge polling is failing"
          description: "Bridge poll errors are occurring for Session-Buddy"

      - alert: SessionBuddyBridgeStale
        expr: |
          max(bodai_bridge_freshness_seconds{source_service="session-buddy"}) > 300
        for: 15m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "Session-Buddy bridge data is stale"
          description: "Last successful Session-Buddy bridge data is {{ $value }} seconds old"

      - alert: HighMemoryUsage
        expr: |
          system_memory_usage_bytes{type="rss"} > 1024 * 1024 * 1024
        for: 5m
        labels:
          severity: critical
          service: mahavishnu
        annotations:
          summary: "Memory usage above 1GB"
          description: "RSS memory is {{ $value | humanize }}"

      - alert: ElevatedMemoryUsage
        expr: |
          system_memory_usage_bytes{type="rss"} > 512 * 1024 * 1024
        for: 10m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "Memory usage above 512MB"
          description: "RSS memory is {{ $value | humanize }}"

      - alert: HighCPUUsage
        expr: |
          avg_over_time(system_cpu_usage_percent[5m]) > 80
        for: 10m
        labels:
          severity: critical
          service: mahavishnu
        annotations:
          summary: "Average CPU usage above 80%"
          description: "CPU usage is {{ $value }}% over 5 minutes"

      - alert: ElevatedCPUUsage
        expr: |
          avg_over_time(system_cpu_usage_percent[10m]) > 60
        for: 15m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "Average CPU usage above 60%"
          description: "CPU usage is {{ $value }}% over 10 minutes"

      - alert: DiskSpaceCritical
        expr: |
          system_disk_usage_percent > 90
        for: 5m
        labels:
          severity: critical
          service: mahavishnu
        annotations:
          summary: "Disk space critically low (>90% used)"
          description: "Disk usage is {{ $value }}% on mount {{ $labels.mount_point }}"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/disk-cleanup"

      - alert: DiskSpaceLow
        expr: |
          system_disk_usage_percent > 80
        for: 10m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "Disk space low (>80% used)"
          description: "Disk usage is {{ $value }}% on mount {{ $labels.mount_point }}"

      - alert: HighCacheEvictionRate
        expr: |
          sum(rate(cache_evictions_total[5m])) > 10
        for: 5m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "Cache eviction rate high (>10/sec)"
          description: "Evicting {{ $value | humanize }} items/sec"

      - alert: LowCacheHitRate
        expr: |
          (
            sum(rate(cache_operations_total{result="hit"}[5m]))
            /
            sum(rate(cache_operations_total[5m]))
          ) < 0.5
        for: 10m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "Cache hit rate below 50%"
          description: "Hit rate is {{ $value | humanizePercentage }}"

      - alert: ServiceDown
        expr: |
          up{job=~"mahavishnu|otel-collector|prometheus"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Monitoring target down (job: {{ $labels.job }})"
          description: "{{ $labels.job }} has been down for more than 2 minutes"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/service-recovery"

      - alert: HighFDUsage
        expr: |
          system_file_descriptors_open > 8000
        for: 5m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "File descriptor count high (>8000)"
          description: "{{ $value }} file descriptors open"

      - alert: ApproachingFDLimit
        expr: |
          system_file_descriptors_open > 9000
        for: 2m
        labels:
          severity: critical
          service: mahavishnu
        annotations:
          summary: "File descriptor count critically high (>9000)"
          description: "{{ $value }} file descriptors open (risk of hitting limit)"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/investigate-fd-leak"

  - name: worker_and_agent_alerts
    interval: 1m
    rules:
      - alert: HighAgentTaskFailureRate
        expr: |
          (
            sum(rate(agent_tasks_total{status=~"failed|timeout|cancelled|error"}[10m]))
            /
            sum(rate(agent_tasks_total[10m]))
          ) > 0.1
        for: 10m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "Agent task failure rate above 10%"
          description: "Agent task failure rate is {{ $value | humanizePercentage }}"

      - alert: LongRunningAgentTask
        expr: |
          histogram_quantile(
            0.99,
            sum by (le, agent_type, adapter) (rate(agent_task_duration_seconds_bucket[10m]))
          ) > 1800
        for: 5m
        labels:
          severity: warning
          service: mahavishnu
        annotations:
          summary: "P99 agent task duration above 30 minutes"
          description: "{{ $labels.agent_type }}/{{ $labels.adapter }} P99 duration is {{ $value }}s"

      - alert: NoAgentTasks
        expr: |
          sum(rate(agent_tasks_total[15m])) == 0
        for: 15m
        labels:
          severity: info
          service: mahavishnu
        annotations:
          summary: "No agent tasks in 15 minutes"
          description: "Agent and worker execution may be idle or misconfigured"
"""

# ============================================================================
# Notification Configuration
# ============================================================================

notification_config = """
receivers:
  - name: 'email-notifications'
    email_configs:
      - to: 'oncall@example.com'
        from: 'alerts@example.com'
        smarthost: 'localhost'
        auth_username: 'alerts'
        auth_password: 'your-password'

  - name: 'slack-notifications'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/WEBHOOK'
        channel: '#alerts'

  - name: 'webhook-notifications'
    webhook_configs:
      - url: 'http://your-webhook-endpoint/alert'
        send_resolved: true

route:
  receiver: 'email-notifications'
  group_by: ['alertname', 'cluster']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h
  receiver: 'email-notifications'

  routes:
    # Critical alerts go to both email and Slack
    - match:
        - severity: critical
      receiver: 'slack-notifications'
      continue: true

inhibit_rules:
  # Inhibit warning alerts when critical alert for same service is firing
  - source_match:
      - severity: critical
    target_match:
      - severity: warning
    equal: ['alertname', 'service']
"""
