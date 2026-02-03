"""AlertManager configuration for MCP ecosystem monitoring.

This module provides alert rules for detecting and notifying on:
- High error rates
- High latency
- Low worker availability
- Resource exhaustion (memory, disk)
- System health issues
"""

from __future__ import annotations

# ============================================================================
# Alert Rule Definitions
# ============================================================================

alert_rules = """
groups:
  - name: mcp_alerts
    interval: 30s
    rules:
      # ========================================
      # Error Rate Alerts
      # ========================================

      # Critical: High tool error rate
      - alert: HighToolErrorRate
        expr: |
          (
            rate(mcp_tool_calls_total{status="error"}[5m])
            /
            rate(mcp_tool_calls_total[5m])
          ) > 0.05
        for: 5m
        labels:
          severity: critical
          service: "{{ $labels.job }}"
        annotations:
          summary: "Tool error rate above 5% (service: {{ $labels.job }})"
          description: "Error rate is {{ $value | humanizePercentage }} ({{ $labels.job }})"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/incident-response"

      # Warning: Elevated error rate
      - alert: ElevatedErrorRate
        expr: |
          (
            rate(mcp_tool_calls_total{status="error"}[5m])
            /
            rate(mcp_tool_calls_total[5m])
          ) > 0.02
        for: 5m
        labels:
          severity: warning
          service: "{{ $labels.job }}"
        annotations:
          summary: "Error rate elevated above 2% (service: {{ $labels.job }})"
          description: "Error rate is {{ $value | humanizePercentage }} ({{ $labels.job }})"

      # ========================================
      # Latency Alerts
      # ========================================

      # Critical: P99 latency too high
      - alert: HighP99Latency
        expr: |
          histogram_quantile(0.99, rate(mcp_http_request_duration_seconds_bucket[5m])) > 5.0
        for: 5m
        labels:
          severity: critical
          service: "{{ $labels.job }}"
        annotations:
          summary: "P99 latency above 5 seconds (service: {{ $labels.job }})"
          description: "P99 latency is {{ $value }}s ({{ $labels.job }})"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/performance-tuning"

      # Warning: P95 latency elevated
      - alert: HighP95Latency
        expr: |
          histogram_quantile(0.95, rate(mcp_http_request_duration_seconds_bucket[5m])) > 1.0
        for: 5m
        labels:
          severity: warning
          service: "{{ $labels.job }}"
        annotations:
          summary: "P95 latency above 1 second (service: {{ $labels.job }})"
          description: "P95 latency is {{ $value }}s ({{ $labels.job }})"

      # Warning: Average latency elevated
      - alert: HighAvgLatency
        expr: |
          rate(mcp_http_request_duration_seconds_sum[5m])
          /
          rate(mcp_http_requests_total[5m])
           > 0.5
        for: 10m
        labels:
          severity: warning
          service: "{{ $labels.job }}"
        annotations:
          summary: "Average latency above 500ms (service: {{ $labels.job }})"
          description: "Average latency is {{ $value }}s ({{ $labels.job }})"

      # ========================================
      # Worker Availability Alerts
      # ========================================

      # Critical: Insufficient workers
      - alert: InsufficientWorkers
        expr: |
          pool_workers_active{pool_type="mahavishnu"} < 2
        for: 5m
        labels:
          severity: critical
        service: "mahavishnu"
        annotations:
          summary: "Less than 2 workers available (pool: mahavishnu)"
          description: "Only {{ $value }} workers active (minimum: 2)"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/worker-scaling"

      # Warning: Worker shortage
      - alert: LowWorkerCount
        expr: |
          pool_workers_active{pool_type="mahavishnu"} < 3
        for: 5m
        labels:
          severity: warning
          service: "mahavishnu"
        annotations:
          summary: "Worker count below 3 (pool: mahavishnu)"
          description: "Only {{ $value }} workers active (recommended: 3-5)"

      # ========================================
      # Task Queue Alerts
      # ========================================

      # Critical: Excessive queue backlog
      - alert: HighQueueBacklog
        expr: |
          pool_tasks_queued{pool_type="mahavishnu"} > 100
        for: 5m
        labels:
          severity: critical
          service: "mahavishnu"
        annotations:
          summary: "Task queue backlog > 100 (pool: mahavishnu)"
          description: "{{ $value }} tasks waiting in queue"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/scale-horizontally"

      # Warning: Building queue
      - alert: BuildingQueue
        expr: |
          pool_tasks_queued{pool_type="mahavishu"} > 50
        for: 10m
        labels:
          severity: warning
          service: "mahavishnu"
        annotations:
          summary: "Task queue building up (pool: mahavishnu)"
          description: "{{ $value }} tasks waiting in queue"

      # ========================================
      # Memory Alerts
      # ========================================

      # Critical: High memory usage
      - alert: HighMemoryUsage
        expr: |
          (
            system_memory_usage_bytes{type="rss"}
            /
            system_memory_usage_bytes{type="rss"}
          ) > 1024 * 1024 * 1024  # 1GB
        for: 5m
        labels:
          severity: critical
          annotations:
          summary: "Memory usage above 1GB"
          description: "RSS memory is {{ $value | humanize }} (type: {{ $labels.type }})"

      # Warning: Memory usage elevated
      - alert: ElevatedMemoryUsage
        expr: |
          (
            system_memory_usage_bytes{type="rss"}
            /
            system_memory_usage_bytes{type="rss"}
          ) > 512 * 1024 * 1024  # 512MB
        for: 10m
        labels:
          severity: warning
          annotations:
          summary: "Memory usage above 512MB"
          description: "RSS memory is {{ $value | humanize }} (type: {{ $labels.type }})"

      # ========================================
      # CPU Alerts
      # ========================================

      # Critical: High CPU usage
      - alert: HighCPUUsage
        expr: |
          avg_over_time(system_cpu_usage_percent[5m]) > 80
        for: 10m
        labels:
          severity: critical
          annotations:
          summary: "Average CPU usage above 80%"
          description: "CPU usage is {{ $value }}% over 5 minutes"

      # Warning: CPU usage elevated
      - alert: ElevatedCPUUsage
        expr: |
          avg_over_time(system_cpu_usage_percent[10m]) > 60
        for: 15m
        labels:
          severity: warning
          annotations:
          summary: "Average CPU usage above 60%"
          description: "CPU usage is {{ $value }}% over 10 minutes"

      # ========================================
      # Disk Alerts
      # ========================================

      # Critical: Disk space low
      - alert: DiskSpaceCritical
        expr: |
          system_disk_usage_percent > 90
        for: 5m
        labels:
          severity: critical
          annotations:
          summary: "Disk space critically low (>90% used)"
          description: "Disk usage is {{ $value }}% on mount {{ $labels.mount_point }}"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/disk-cleanup"

      # Warning: Disk space low
      - alert: DiskSpaceLow
        expr: |
          system_disk_usage_percent > 80
        for: 10m
        labels:
          severity: warning
          annotations:
          summary: "Disk space low (>80% used)"
          description: "Disk usage is {{ $value }}% on mount {{ $labels.mount_point }}"

      # ========================================
      # Cache Alerts
      # ========================================

      # Warning: High cache eviction rate
      - alert: HighCacheEvictionRate
        expr: |
          rate(cache_evictions_total[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Cache eviction rate high (>10/sec)"
          description: "Evicting {{ $value | humanize }} items/sec"

      # Warning: Cache hit rate low
      - alert: LowCacheHitRate
        expr: |
          (
            rate(cache_operations_total{result="hit"}[5m])
            /
            rate(cache_operations_total[5m])
          ) < 0.5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Cache hit rate below 50%"
          description: "Hit rate is {{ $value | humanizePercentage }}"

      # ========================================
      # Service Health Alerts
      # ========================================

      # Critical: Service down
      - alert: ServiceDown
        expr: |
          up{job=~"mahavishnu|akosha|session-buddy|crackerjack"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "MCP service down (job: {{ $labels.job }})"
          description: "{{ $labels.job }} has been down for > 2 minutes"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/service-recovery"

      # Warning: Service restarting
      alert: ServiceRestarting
        expr: |
          changes(kubernetes_pod_name{namespace=~"mcp-.+"}, [5m])
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Service restarting frequently"
          description: "{{ $value }} restarts in 10 minutes"

      # ========================================
      # Session Management Alerts
      # ========================================

      # Warning: Too many active sessions
      - alert: ExcessiveActiveSessions
        expr: |
          sessions_active > 1000
        for: 5m
        labels:
          severity: warning
          service: "session-buddy"
        annotations:
          summary: "Over 1000 active sessions"
          description: "{{ $value }} sessions currently active"

      # Warning: Session operation errors
      - alert: SessionOperationErrors
        expr: |
          (
            rate(session_operations_total{status="error"}[5m])
            /
            rate(session_operations_total[5m])
          ) > 0.01
        for: 10m
        labels:
          severity: warning
          service: "session-buddy"
        annotations:
          summary: "Session operation error rate above 1%"
          description: "Error rate is {{ $value | humanizePercentage }}"

      # ========================================
      # Memory Aggregation Alerts
      # ========================================

      # Warning: Memory sync failures
      - alert: MemorySyncFailures
        expr: |
          (
            rate(memory_syncs_total{status="error"}[10m])
            /
            rate(memory_syncs_total[10m])
          ) > 0.1
        for: 10m
        labels:
          severity: warning
          service: "akosha"
        annotations:
          summary: "Memory sync error rate above 10%"
          description: "Error rate is {{ $value | humanizePercentage }}"

      # Info: Memory sync stalled
      - alert: MemorySyncStalled
        expr: |
          rate(memory_syncs_total[15m]) == 0
        for: 15m
        labels:
          severity: info
          service: "akosha"
        annotations:
          summary: "No memory syncs in 15 minutes"
          description: "Memory aggregation may be stalled"

      # ========================================
      # File Descriptor Alerts
      # ========================================

      # Warning: High file descriptor usage
      - alert: HighFDUsage
        expr: |
          system_file_descriptors_open > 8000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "File descriptor count high (>8000)"
          description: "{{ $value }} file descriptors open"

      # Critical: Approaching FD limit
      - alert: ApproachingFDLimit
        expr: |
          system_file_descriptors_open > 9000
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "File descriptor count critically high (>9000)"
          description: "{{ $value }} file descriptors open (risk of hitting limit)"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/investigate-fd-leak"

  - name: agent_alerts
    interval: 1m
    rules:
      # ========================================
      # Agent Task Alerts
      # ========================================

      # Warning: High agent task failure rate
      - alert: HighAgentTaskFailureRate
        expr: |
          (
            rate(agent_tasks_total{status="error"}[10m])
            /
            rate(agent_tasks_total[10m])
          ) > 0.1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Agent task failure rate above 10%"
          description: "{{ $labels.agent_type }}/{{ $labels.adapter }} failure rate: {{ $value | humanizePercentage }}"

      # Warning: Long-running agent tasks
      - alert: LongRunningAgentTask
        expr: |
          agent_task_duration_seconds{quantile="0.99"} > 1800  # 30 minutes
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P99 agent task duration > 30 minutes"
          description: "{{ $labels.agent_type }}/{{ $labels.adapter }} P99 duration: {{ $value }}s"

      # Info: No agent tasks running
      - alert: NoAgentTasks
        expr: |
          rate(agent_tasks_total[15m]) == 0
        for: 15m
        labels:
          severity: info
        annotations:
          summary: "No agent tasks in 15 minutes"
          description: "Agent system may be idle or misconfigured"

  - name: database_alerts
    interval: 1m
    rules:
      # ========================================
      # Database Connection Alerts
      # ========================================

      # Critical: Database connection failures
      - alert: DatabaseConnectionFailures
        expr: |
          up{job="postgres",instance=".*:5432"} == 0
        for: 1m
        labels:
          severity: critical
          annotations:
          summary: "PostgreSQL database unreachable"
          description: "Cannot connect to PostgreSQL at {{ $labels.instance }}"
          runbook_url: "https://github.com/your-org/mahavishnu/wiki/database-recovery"

      # Warning: Many database connections
      - alert: TooManyDatabaseConnections
        expr: |
          pg_stat_database_numbackends{datname="session_buddy"} > 80
        for: 5m
        labels:
          severity: warning
          annotations:
          summary: "PostgreSQL connection count high"
          description: "{{ $value }} connections (max: 100)"

      # Critical: Database replication lag
      - alert: DatabaseReplicationLag
        expr: |
          pg_stat_replication_lag_seconds > 30
        for: 5m
        labels:
          severity: critical
          annotations:
          summary: "Database replication lag high"
          description: "Replication lag is {{ $value }}s"
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

    # Database alerts to email only
    - match:
        - alertname: "DatabaseConnectionFailures"
      receiver: 'email-notifications'

inhibit_rules:
  # Don't alert on high latency if there's also high error rate
  - source_match:
      - alertname: "HighP95Latency"
    target_match:
      - alertname: "HighToolErrorRate"
    equal: ['severity', 'service']
  # Inhibit high latency alert if error rate is also high
"""

# ============================================================================
# Alert Templates
# ============================================================================

alert_templates = """
templates:
  - '/etc/alertmanager/templates/*.tmpl'
"""
