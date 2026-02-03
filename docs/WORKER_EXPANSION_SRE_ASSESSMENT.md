# Worker Expansion Plan - SRE Operational Assessment

**Date**: 2025-02-03
**Assessor**: SRE Engineer (Claude Sonnet 4.5)
**Assessment Score**: 5.5/10 (NOT PRODUCTION READY)
**Status**: CRITICAL GAPS IDENTIFIED - Mitigation Required

---

## Executive Summary

The worker expansion plan introduces **6 new workers** with significant operational complexity and multiple single points of failure. While the plan mentions ADR 003 integration, it lacks concrete implementation details for connection pooling, resource limits, monitoring, and disaster recovery specific to these new workers.

**CRITICAL CONCERNS:**
- SSH connection pool exhaustion (100 concurrent connections)
- MQTT broker single point of failure
- No worker-level SLOs defined
- Missing resource limits and quotas
- Insufficient monitoring for worker-specific failures

**RECOMMENDATION:** Do NOT proceed to production until critical gaps are addressed.

---

## 1. Operational Readiness Score

### Overall Score: 5.5/10

| Category | Score | Status | Notes |
|----------|-------|--------|-------|
| **Reliability Architecture** | 4/10 | CRITICAL | Missing circuit breakers, no connection pool limits |
| **Resource Management** | 3/10 | CRITICAL | No quotas, no backpressure, unlimited growth risk |
| **Monitoring & Alerting** | 5/10 | WARNING | Metrics mentioned but no SLOs or alerting defined |
| **Error Recovery** | 7/10 | GOOD | ADR 003 exists but worker-specific patterns missing |
| **Disaster Recovery** | 6/10 | WARNING | Generic DR exists, worker-specific recovery missing |
| **Security** | 7/10 | GOOD | Secrets management addressed, audit logging mentioned |
| **Testing Strategy** | 6/10 | WARNING | No chaos engineering, no failure injection tests |

### Production Readiness Criteria

- [ ] SLOs defined for all workers
- [ ] Error budgets allocated
- [ ] Resource limits enforced
- [ ] Monitoring dashboards created
- [ ] Alerting rules defined
- [ ] Runbooks written
- [ ] Disaster recovery tested
- [ ] Load testing completed
- [ ] Chaos engineering performed
- [ ] On-call documentation complete

**Result**: 3/10 criteria met - NOT PRODUCTION READY

---

## 2. Single Points of Failure (Critical)

### 2.1 SSH Worker - CRITICAL

**Failure Mode**: Connection Pool Exhaustion

```
Risk: HIGH
Impact: ALL SSH operations blocked
MTTR: 15-30 minutes (manual pool restart)
Mitigation: NOT ADDRESSED
```

**Problem:**
- Plan mentions "connection pooling" but no limits defined
- 100 concurrent SSH connections will consume significant memory (~1-2GB)
- No backpressure mechanism when pool exhausted
- No connection drain/eviction policy

**Evidence from plan:**
> "Connection Pooling - Re-use SSH connections for multiple commands" (line 225)
> "connection_pool_size: 5" (line 166) - DEFAULT ONLY, NO MAX LIMIT

**Mitigation Required:**
```yaml
ssh:
  # REQUIRED: Hard limits
  max_connections: 50              # Hard ceiling
  max_connections_per_host: 10     # Per-host limit
  connection_ttl: 300              # Evict after 5min idle
  pool_backpressure: "reject_new"  # Fail fast when full
  connection_health_check: 60      # Check every 60s

  # REQUIRED: Circuit breaker per host
  circuit_breaker:
    failure_threshold: 5
    recovery_timeout: 300
    half_open_max_calls: 3
```

**Metrics Required:**
- `ssh_connection_pool_active` (gauge)
- `ssh_connection_pool_idle` (gauge)
- `ssh_connection_pool_exhausted` (counter)
- `ssh_connection_creation_duration_seconds` (histogram)
- `ssh_connection_errors_total{error_type}` (counter)

**SLO Recommendation:**
- SSH command success rate: >99.5% (allow 0.5% error budget)
- SSH connection latency: p95 < 5s
- SSH connection pool availability: >99.9%

---

### 2.2 MQTT Worker - HIGH RISK

**Failure Mode**: Broker Unavailability

```
Risk: HIGH
Impact: ALL IoT messaging blocked
MTTR: 5-60 minutes (depends on broker)
Mitigation: PARTIALLY ADDRESSED (offline buffering mentioned)
```

**Problem:**
- Single broker configuration (no HA mentioned)
- No fallback to secondary broker
- QoS 1/2 guarantees delivery but not availability
- No circuit breaker for broker connection failures
- Will message (LWT) configured but no recovery procedure

**Evidence from plan:**
> "default_broker: 'mqtt.example.com'" (line 383) - SINGLE BROKER
> "will_topic, will_message" (line 373-374) - LWT but no recovery

**Mitigation Required:**
```yaml
mqtt:
  # REQUIRED: HA configuration
  brokers:
    primary: "mqtt-primary.example.com"
    secondary: "mqtt-secondary.example.com"
  broker_switch_threshold: 3  # Fail after 3 failures

  # REQUIRED: Circuit breaker
  circuit_breaker:
    failure_threshold: 10
    recovery_timeout: 60
    half_open_max_calls: 5

  # REQUIRED: Offline buffer
  offline_buffer:
    enabled: true
    max_size: 10000
    persist_to_disk: true
    disk_path: "/var/lib/mahavishnu/mqp_buffer"

  # REQUIRED: Subscription health
  subscription_health_check: 30
  resubscribe_on_reconnect: true
```

**Metrics Required:**
- `mqtt_broker_connected` (gauge)
- `mqtt_broker_switches_total` (counter)
- `mqtt_messages_published_total{status}` (counter)
- `mqtt_messages_received_total{status}` (counter)
- `mqtt_subscription_errors_total` (counter)
- `mqtt_offline_buffer_size` (gauge)
- `mqtt_qos_delivery_failures_total{qos}` (counter)

**SLO Recommendation:**
- MQTT publish success rate: >99.9% (QoS 1/2 only)
- MQTT broker connection uptime: >99.5%
- MQTT message delivery latency: p95 < 1s

---

### 2.3 Cloud Run Worker - MEDIUM RISK

**Failure Mode**: Deployment Pipeline Stuck

```
Risk: MEDIUM
Impact: No new deployments
MTTR: 30-60 minutes (manual rollback)
Mitigation: PARTIALLY ADDRESSED (rollback mentioned)
```

**Problem:**
- No deployment queue (concurrent deployments not rate-limited)
- No deployment verification (health checks mentioned but no SLO)
- No automatic rollback on failure detection
- gcloud API rate limits not addressed

**Evidence from plan:**
> "async def rollback(...)" (line 745-750) - MANUAL ONLY
> "health_check(...)" (line 738-743) - NO AUTOMATED ROLLBACK

**Mitigation Required:**
```yaml
cloud_run:
  # REQUIRED: Deployment throttling
  deployment:
    max_concurrent: 3
    queue_size: 100
    timeout: 1800  # 30 minutes max
    auto_rollback_on_failure: true
    rollback_health_check_threshold: 5

  # REQUIRED: Deployment verification
  verification:
    enabled: true
    health_check_path: "/health"
    health_check_timeout: 60
    health_check_interval: 10
    min_success_count: 3

  # REQUIRED: gcloud API rate limiting
  gcloud_api:
    rate_limit: 10  # requests per second
    burst: 20
    retry_on_quota: true
```

**Metrics Required:**
- `cloud_run_deployments_total{status}` (counter)
- `cloud_run_deployment_duration_seconds` (histogram)
- `cloud_run_rollback_total{reason}` (counter)
- `cloud_run_health_check_failures_total` (counter)
- `cloud_run_build_with_pack_duration_seconds` (histogram)

**SLO Recommendation:**
- Cloud Run deployment success rate: >99%
- Cloud Run deployment latency: p95 < 5min
- Cloud Run service health: >99.9%

---

### 2.4 Database Worker - MEDIUM RISK

**Failure Mode**: Migration Rollback Failure

```
Risk: MEDIUM
Impact: Data inconsistency, application broken
MTTR: 1-4 hours (manual data repair)
Mitigation: NOT ADDRESSED
```

**Problem:**
- No automatic rollback on migration failure
- No migration verification step
- No dry-run mode
- No migration locking (concurrent migrations possible)
- Backup mentioned but no automated restore test

**Evidence from plan:**
> "async def run_migration(...)" (line 906-923) - NO ROLLBACK
> "to_version: str | None = None" - NO VERIFICATION

**Mitigation Required:**
```yaml
database:
  # REQUIRED: Migration safety
  migration:
    dry_run_by_default: true
    require_confirmation: true
    auto_rollback_on_failure: false  # Too dangerous, manual only
    verify_after_migration: true
    lock_timeout: 300  # 5 minutes

  # REQUIRED: Pre-migration backup
  backup:
    auto_backup_before_migration: true
    backup_retention_days: 30
    backup_verification: true  # Test restore

  # REQUIRED: Migration verification
  verification:
    enabled: true
    checks:
      - row_count
      - schema_integrity
      - foreign_keys
      - sample_query
```

**Metrics Required:**
- `database_migrations_total{status}` (counter)
- `database_migration_duration_seconds` (histogram)
- `database_migration_rollback_total` (counter)
- `database_backup_duration_seconds` (histogram)
- `database_backup_verification_failures_total` (counter)

**SLO Recommendation:**
- Database migration success rate: 100% (manual intervention required)
- Database backup success rate: >99.9%
- Database backup restore test: 100% (weekly)

---

## 3. Resource Usage Analysis

### 3.1 SSH Worker Resource Model

**Assumptions:**
- 100 concurrent SSH connections
- Average command duration: 30s
- Average connection lifetime: 5min
- Memory per connection: ~10-20MB

**Resource Projection:**

```
Memory Usage:
- 100 connections × 15MB avg = 1.5GB
- asyncssh overhead: ~200MB
- Worker process: ~100MB
- Total: ~1.8GB memory

CPU Usage:
- 100 connections × 5% CPU avg = 500% CPU (5 cores)
- Crypto operations (SSH handshake): CPU spike
- Total: 6-8 cores recommended

Network Usage:
- 100 connections × 1Mbps avg = 100Mbps
- Burst during file transfers: 1Gbps
- Total: 1Gbps network recommended
```

**CRITICAL GAPS:**
1. No memory limit enforcement (can OOM host)
2. No CPU request/limit defined (can starve other workers)
3. No network throttling (can saturate interface)
4. No connection admission control

**Mitigation Required:**
```yaml
ssh:
  # REQUIRED: Resource limits
  resources:
    memory_limit: "2Gi"
    memory_request: "512Mi"
    cpu_limit: "6"
    cpu_request: "2"
    network_max_bandwidth: "1Gbps"

  # REQUIRED: Admission control
  admission_control:
    max_concurrent_executions: 100
    queue_size: 1000
    reject_when_full: true
    priority_classes: ["critical", "normal", "low"]
```

---

### 3.2 MQTT Worker Resource Model

**Assumptions:**
- 1000 subscriptions (wildcards)
- 100 messages/second publish rate
- 10000 messages/second subscribe rate
- Message size: 1KB avg

**Resource Projection:**

```
Memory Usage:
- 1000 subscriptions × 10KB = 10MB
- Message buffers (10000 msg × 1KB): 10MB
- gmqtt client: ~50MB
- Worker process: ~100MB
- Total: ~170MB memory

CPU Usage:
- Message processing: 20% CPU
- TLS encryption/decryption: 30% CPU
- Total: 2-3 cores

Network Usage:
- 100 msg/s × 1KB = 100KB/s upstream
- 10000 msg/s × 1KB = 10MB/s downstream
- Total: 10Mbps (asymmetric)
```

**CRITICAL GAPS:**
1. No subscription limit (unbounded memory growth)
2. No message rate limiting (can flood broker)
3. No buffer size limits (memory exhaustion risk)
4. No QoS-specific throttling

**Mitigation Required:**
```yaml
mqtt:
  # REQUIRED: Resource limits
  resources:
    memory_limit: "512Mi"
    memory_request: "256Mi"
    cpu_limit: "3"
    cpu_request: "1"

  # REQUIRED: Throttling
  throttling:
    max_publish_rate: 100  # per second
    max_subscription_count: 1000
    max_message_size: "1MB"
    buffer_size: 10000
    drop_oldest_when_full: true
```

---

### 3.3 Combined Resource Impact

**Total Resource Requirements (All Workers):**

```
Memory: 1.8GB (SSH) + 512MB (MQTT) + 512MB (Cloud Run) + 256MB (DB) = 3GB
CPU: 8 cores (SSH) + 3 cores (MQTT) + 2 cores (Cloud Run) + 1 core (DB) = 14 cores
Network: 1Gbps (SSH) + 10Mbps (MQTT) + 100Mbps (Cloud Run) = ~1.2Gbps
```

**CRITICAL QUESTION:**
Can the infrastructure handle 14 CPU cores and 3GB memory for JUST these workers?

**Recommendation:**
- Run workers in separate processes/containers
- Enforce per-worker resource quotas
- Implement worker priority classes
- Kill low-priority workers under resource pressure

---

## 4. Monitoring Recommendations

### 4.1 Required Metrics (Worker-Specific)

**SSH Worker Metrics:**
```python
# Connection pool metrics
ssh_connection_pool_active_connections = Gauge(
    'ssh_connection_pool_active_connections',
    'Active SSH connections in pool',
    ['host', 'state']  # state: idle, active, error
)

ssh_connection_pool_exhausted_total = Counter(
    'ssh_connection_pool_exhausted_total',
    'Connection pool exhaustion events',
    ['host']
)

# Execution metrics
ssh_command_duration_seconds = Histogram(
    'ssh_command_duration_seconds',
    'SSH command execution duration',
    ['host', 'exit_code'],
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 300]
)

ssh_command_errors_total = Counter(
    'ssh_command_errors_total',
    'SSH command execution errors',
    ['host', 'error_type']  # timeout, auth_failure, connection_lost
)

# File transfer metrics
ssh_sftp_transfer_duration_seconds = Histogram(
    'ssh_sftp_transfer_duration_seconds',
    'SFTP transfer duration',
    ['host', 'direction', 'status'],
    buckets=[1, 5, 10, 30, 60, 300, 600]
)

ssh_sftp_bytes_transferred_total = Counter(
    'ssh_sftp_bytes_transferred_total',
    'Total bytes transferred via SFTP',
    ['host', 'direction']
)
```

**MQTT Worker Metrics:**
```python
# Connection metrics
mqtt_broker_connected = Gauge(
    'mqtt_broker_connected',
    'MQTT broker connection status',
    ['broker_url']
)

mqtt_broker_switches_total = Counter(
    'mqtt_broker_switches_total',
    'MQTT broker failover events',
    ['from_broker', 'to_broker']
)

# Messaging metrics
mqtt_messages_published_total = Counter(
    'mqtt_messages_published_total',
    'MQTT messages published',
    ['topic', 'qos', 'status']  # status: success, failed, timeout
)

mqtt_messages_received_total = Counter(
    'mqtt_messages_received_total',
    'MQTT messages received',
    ['topic', 'qos']
)

mqtt_message_delivery_latency_seconds = Histogram(
    'mqtt_message_delivery_latency_seconds',
    'Time from publish to broker ACK',
    ['qos'],
    buckets=[0.001, 0.01, 0.1, 0.5, 1, 5]
)

# Subscription metrics
mqtt_subscriptions_active = Gauge(
    'mqtt_subscriptions_active',
    'Active MQTT subscriptions',
    ['topic_pattern']
)

mqtt_subscription_errors_total = Counter(
    'mqtt_subscription_errors_total',
    'MQTT subscription errors',
    ['topic_pattern', 'error_type']
)

# Buffer metrics
mqtt_offline_buffer_size = Gauge(
    'mqtt_offline_buffer_size',
    'Offline buffer size',
    ['state']  # state: memory, disk
)

mqtt_offline_buffer_dropped_total = Counter(
    'mqtt_offline_buffer_dropped_total',
    'Messages dropped from offline buffer',
    ['reason']
)
```

**Cloud Run Worker Metrics:**
```python
# Deployment metrics
cloud_run_deployments_total = Counter(
    'cloud_run_deployments_total',
    'Cloud Run deployments',
    ['service_name', 'region', 'status']  # status: success, failed, rolled_back
)

cloud_run_deployment_duration_seconds = Histogram(
    'cloud_run_deployment_duration_seconds',
    'Cloud Run deployment duration',
    ['service_name', 'region', 'stage'],  # stage: build, deploy, verify
    buckets=[60, 180, 300, 600, 1800, 3600]
)

# Build metrics
cloud_run_build_with_pack_duration_seconds = Histogram(
    'cloud_run_build_with_pack_duration_seconds',
    'Buildpack build duration',
    ['service_name', 'builder_image'],
    buckets=[60, 180, 300, 600, 1200]
)

# Health check metrics
cloud_run_health_check_duration_seconds = Histogram(
    'cloud_run_health_check_duration_seconds',
    'Health check duration',
    ['service_name', 'status'],
    buckets=[0.1, 0.5, 1, 2, 5, 10]
)

cloud_run_health_check_failures_total = Counter(
    'cloud_run_health_check_failures_total',
    'Health check failures',
    ['service_name', 'failure_reason']
)

# Rollback metrics
cloud_run_rollback_total = Counter(
    'cloud_run_rollback_total',
    'Cloud Run rollbacks',
    ['service_name', 'trigger', 'reason']
    # trigger: manual, automatic, health_check
)
```

**Database Worker Metrics:**
```python
# Migration metrics
database_migrations_total = Counter(
    'database_migrations_total',
    'Database migrations',
    ['db_type', 'tool', 'status']  # tool: alembic, flyway, migrate
)

database_migration_duration_seconds = Histogram(
    'database_migration_duration_seconds',
    'Database migration duration',
    ['db_type', 'tool'],
    buckets=[1, 5, 10, 30, 60, 300, 600]
)

database_migration_rollback_total = Counter(
    'database_migration_rollback_total',
    'Database migration rollbacks',
    ['db_type', 'reason']
)

# Backup metrics
database_backup_duration_seconds = Histogram(
    'database_backup_duration_seconds',
    'Database backup duration',
    ['db_type', 'format'],
    buckets=[60, 300, 600, 1800, 3600]
)

database_backup_size_bytes = Gauge(
    'database_backup_size_bytes',
    'Database backup size',
    ['db_type']
)

database_backup_verification_failures_total = Counter(
    'database_backup_verification_failures_total',
    'Backup verification failures',
    ['db_type', 'verification_type']
)
```

---

### 4.2 Alerting Rules

**CRITICAL Alerts (P1 - Page Immediately):**

```yaml
# SSH connection pool exhausted
- alert: SSHConnectionPoolExhausted
  expr: ssh_connection_pool_active_connections{state="active"} >= ssh_max_connections * 0.9
  for: 2m
  labels:
    severity: critical
    worker: ssh
  annotations:
    summary: "SSH connection pool nearly exhausted on {{ $labels.host }}"
    description: "Active connections: {{ $value }}/{{ $labels.ssh_max_connections }}"

# SSH command error rate high
- alert: SSHCommandErrorRateHigh
  expr: rate(ssh_command_errors_total[5m]) > 0.1  # >10% error rate
  for: 5m
  labels:
    severity: critical
    worker: ssh
  annotations:
    summary: "SSH command error rate >10% on {{ $labels.host }}"

# MQTT broker disconnected
- alert: MQTTBrokerDisconnected
  expr: mqtt_broker_connected == 0
  for: 1m
  labels:
    severity: critical
    worker: mqtt
  annotations:
    summary: "MQTT broker {{ $labels.broker_url }} disconnected"
    description: "No connection to MQTT broker for >1 minute"

# MQTT subscription buffer full
- alert: MQTTOfflineBufferFull
  expr: mqtt_offline_buffer_size / mqtt_offline_buffer_max_size > 0.9
  for: 5m
  labels:
    severity: critical
    worker: mqtt
  annotations:
    summary: "MQTT offline buffer 90% full - dropping messages"

# Cloud Run deployment failures
- alert: CloudRunDeploymentFailureRate
  expr: rate(cloud_run_deployments_total{status="failed"}[10m]) > 0.05  # >5% failure rate
  for: 10m
  labels:
    severity: critical
    worker: cloud_run
  annotations:
    summary: "Cloud Run deployment failure rate >5%"

# Database migration failure
- alert: DatabaseMigrationFailed
  expr: increase(database_migrations_total{status="failed"}[1m]) > 0
  labels:
    severity: critical
    worker: database
  annotations:
    summary: "Database migration failed for {{ $labels.db_type }}"
    description: "Manual intervention required"
```

**WARNING Alerts (P2 - Investigate within 1 hour):**

```yaml
# SSH connection latency high
- alert: SSHConnectionLatencyHigh
  expr: histogram_quantile(0.95, rate(ssh_command_duration_seconds_bucket[5m])) > 30
  for: 10m
  labels:
    severity: warning
    worker: ssh
  annotations:
    summary: "SSH p95 latency >30s on {{ $labels.host }}"

# MQTT message delivery latency
- alert: MQTTMessageDeliveryLatencyHigh
  expr: histogram_quantile(0.95, rate(mqtt_message_delivery_latency_seconds_bucket[5m])) > 5
  for: 10m
  labels:
    severity: warning
    worker: mqtt
  annotations:
    summary: "MQTT p95 delivery latency >5s for QoS {{ $labels.qos }}"

# Cloud Run deployment slow
- alert: CloudRunDeploymentSlow
  expr: histogram_quantile(0.95, rate(cloud_run_deployment_duration_seconds_bucket[10m])) > 600
  for: 15m
  labels:
    severity: warning
    worker: cloud_run
  annotations:
    summary: "Cloud Run p95 deployment time >10 minutes"

# Database backup failed
- alert: DatabaseBackupFailed
  expr: increase(database_backup_duration_seconds_count[1h]) == 0
  for: 2h
  labels:
    severity: warning
    worker: database
  annotations:
    summary: "No database backup in >2 hours for {{ $labels.db_type }}"
```

---

### 4.3 Service Level Objectives (SLOs)

**SSH Worker:**
```yaml
slos:
  ssh_command_success_rate:
    target: 0.995  # 99.5%
    window: 30d
    error_budget: 0.005  # 0.5% (~3.6 hours/month)

  ssh_connection_latency:
    target: 5s
    percentile: 95
    window: 7d

  ssh_connection_pool_availability:
    target: 0.999  # 99.9%
    window: 30d
```

**MQTT Worker:**
```yaml
slos:
  mqtt_publish_success_rate:
    target: 0.999  # 99.9% (for QoS 1/2)
    window: 30d
    error_budget: 0.001  # 0.1% (~43 minutes/month)

  mqtt_broker_connection_uptime:
    target: 0.995  # 99.5%
    window: 30d

  mqtt_message_delivery_latency:
    target: 1s
    percentile: 95
    window: 7d
```

**Cloud Run Worker:**
```yaml
slos:
  cloud_run_deployment_success_rate:
    target: 0.99  # 99%
    window: 30d
    error_budget: 0.01  # 1% (~7.2 hours/month)

  cloud_run_deployment_latency:
    target: 300s  # 5 minutes
    percentile: 95
    window: 7d

  cloud_run_service_availability:
    target: 0.999  # 99.9%
    window: 30d
```

**Database Worker:**
```yaml
slos:
  database_migration_success_rate:
    target: 1.0  # 100% - manual intervention required
    window: 90d

  database_backup_success_rate:
    target: 0.999  # 99.9%
    window: 30d

  database_backup_restore_test:
    target: 1.0  # 100% - weekly automated test
    window: 7d
```

---

## 5. Error Recovery Integration (ADR 003)

### 5.1 Current State

**Existing ADR 003 Implementation:**
- ✅ Retry with exponential backoff
- ✅ Error classification (transient, permanent, resource, network, permission)
- ✅ Circuit breaker pattern
- ✅ Dead letter queue
- ✅ Workflow healing

**Plan Integration Status:**
- ✅ Mentions ADR 003 (line 1144-1174)
- ❌ No worker-specific retry policies
- ❌ No worker-specific circuit breaker thresholds
- ❌ No worker-specific DLQ handling

### 5.2 Required Enhancements

**SSH Worker - ADR 003 Integration:**

```python
# mahavishnu/workers/ssh.py

from mahavishnu.core.resilience import (
    ErrorRecoveryManager,
    RecoveryStrategy,
    ErrorCategory
)

class SSHWorker(BaseWorker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.recovery_manager = ErrorRecoveryManager(self.app)

        # SSH-specific recovery patterns
        self.recovery_manager.recovery_actions.update({
            "SSH_CONNECTION_FAILED": RecoveryAction(
                strategy=RecoveryStrategy.RETRY,
                category=ErrorCategory.NETWORK,
                max_attempts=3,
                backoff_factor=2.0,
            ),
            "SSH_AUTH_FAILED": RecoveryAction(
                strategy=RecoveryStrategy.SKIP,  # No point retrying auth
                category=ErrorCategory.PERMISSION,
                max_attempts=1,
                notify_on_failure=True,
            ),
            "SSH_TIMEOUT": RecoveryAction(
                strategy=RecoveryStrategy.RETRY,
                category=ErrorCategory.TRANSIENT,
                max_attempts=2,
                backoff_factor=3.0,
            ),
            "SSH_COMMAND_FAILED": RecoveryAction(
                strategy=RecoveryStrategy.FALLBACK,
                category=ErrorCategory.PERMANENT,
                max_attempts=1,
                fallback_function=self._fallback_to_sftp,
            ),
        })

    async def execute_non_interactive(self, command: str) -> WorkerResult:
        """Execute command with ADR 003 resilience."""
        return await self.recovery_manager.execute_with_resilience(
            self._execute_ssh_command,
            command,
            workflow_id=self.worker_id,
            repo_path=self.host,
        )

    async def _execute_ssh_command(self, command: str) -> WorkerResult:
        """Internal SSH execution with circuit breaker."""
        # Check circuit breaker before attempting
        if self.circuit_breaker.is_open(self.host):
            raise CircuitBreakerError(f"SSH circuit breaker open for {self.host}")

        try:
            result = await self._ssh_connection.run(command)
            self.circuit_breaker.record_success(self.host)
            return result
        except Exception as e:
            self.circuit_breaker.record_failure(self.host)
            raise

    async def _fallback_to_sftp(self, command: str, **kwargs):
        """Fallback: Write command as script, transfer via SFTP, execute."""
        # Create temporary script
        script_path = f"/tmp/mahavishnu_{uuid.uuid4()}.sh"
        await self.sftp_upload(
            local_files=[Path(script_path)],
            remote_dir="/tmp/"
        )
        # Execute via SSH
        return await self._execute_ssh_command(f"bash {script_path}")
```

**MQTT Worker - ADR 003 Integration:**

```python
# mahavishnu/workers/mqtt.py

class MQTTWorker(BaseWorker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.recovery_manager = ErrorRecoveryManager(self.app)
        self.circuit_breaker = CircuitBreaker(threshold=10, timeout=60)

        # MQTT-specific recovery patterns
        self.recovery_manager.recovery_actions.update({
            "MQTT_BROKER_DISCONNECTED": RecoveryAction(
                strategy=RecoveryStrategy.RETRY,
                category=ErrorCategory.NETWORK,
                max_attempts=5,
                backoff_factor=2.0,
            ),
            "MQTT_PUBLISH_FAILED": RecoveryAction(
                strategy=RecoveryStrategy.FALLBACK,
                category=ErrorCategory.TRANSIENT,
                max_attempts=3,
                fallback_function=self._fallback_to_buffer,
            ),
            "MQTT_SUBSCRIPTION_FAILED": RecoveryAction(
                strategy=RecoveryStrategy.NOTIFY,  # Subscription failures need attention
                category=ErrorCategory.PERMISSION,
                max_attempts=1,
                notify_on_failure=True,
            ),
            "MQTT_QOS_DELIVERY_FAILED": RecoveryAction(
                strategy=RecoveryStrategy.RETRY,
                category=ErrorCategory.TRANSIENT,
                max_attempts=5,
                backoff_factor=1.5,
            ),
        })

    async def publish(self, topic: str, payload: dict, qos: int) -> WorkerResult:
        """Publish with ADR 003 resilience."""
        return await self.recovery_manager.execute_with_resilience(
            self._publish_internal,
            topic, payload, qos,
            workflow_id=self.worker_id,
        )

    async def _publish_internal(self, topic: str, payload: dict, qos: int):
        """Internal publish with circuit breaker."""
        # Check circuit breaker
        if self.circuit_breaker.is_open(self.broker_host):
            # Fallback to offline buffer
            return await self._buffer_message(topic, payload, qos)

        try:
            result = await self.mqtt_client.publish(topic, payload, qos)
            self.circuit_breaker.record_success(self.broker_host)
            return result
        except Exception as e:
            self.circuit_breaker.record_failure(self.broker_host)
            raise

    async def _fallback_to_buffer(self, topic: str, payload: dict, qos: int, **kwargs):
        """Fallback: Buffer message offline."""
        if self.offline_buffer.size() >= self.offline_buffer.max_size:
            # Drop oldest message
            self.offline_buffer.drop_oldest()
            self.metrics.record('mqtt_offline_buffer_dropped_total', reason='full')

        self.offline_buffer.add(topic, payload, qos)
        return WorkerResult(success=True, buffered=True)
```

**Cloud Run Worker - ADR 003 Integration:**

```python
# mahavishnu/workers/cloud_run.py

class CloudRunWorker(BaseWorker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.recovery_manager = ErrorRecoveryManager(self.app)

        # Cloud Run-specific recovery patterns
        self.recovery_manager.recovery_actions.update({
            "CLOUD_RUN_BUILD_FAILED": RecoveryAction(
                strategy=RecoveryStrategy.RETRY,
                category=ErrorCategory.TRANSIENT,
                max_attempts=2,
                backoff_factor=2.0,
            ),
            "CLOUD_RUN_DEPLOYMENT_FAILED": RecoveryAction(
                strategy=RecoveryStrategy.ROLLBACK,  # Automatic rollback
                category=ErrorCategory.PERMANENT,
                max_attempts=1,
            ),
            "CLOUD_RUN_QUOTA_EXCEEDED": RecoveryAction(
                strategy=RecoveryStrategy.NOTIFY,
                category=ErrorCategory.RESOURCE,
                max_attempts=1,
                notify_on_failure=True,
            ),
            "CLOUD_RUN_HEALTH_CHECK_FAILED": RecoveryAction(
                strategy=RecoveryStrategy.ROLLBACK,
                category=ErrorCategory.PERMANENT,
                max_attempts=1,
            ),
        })

    async def deploy_to_cloud_run(self, image_name: str, service_name: str) -> WorkerResult:
        """Deploy with ADR 003 resilience."""
        return await self.recovery_manager.execute_with_resilience(
            self._deploy_internal,
            image_name, service_name,
            workflow_id=self.worker_id,
        )

    async def _deploy_internal(self, image_name: str, service_name: str):
        """Internal deploy with automatic rollback."""
        # Get current revision for rollback
        current_revision = await self._get_current_revision(service_name)

        try:
            # Deploy new revision
            result = await self._gcloud_deploy(image_name, service_name)

            # Verify deployment
            health_result = await self._verify_deployment(service_name)
            if not health_result.healthy:
                # Automatic rollback
                await self.rollback(service_name, current_revision)
                raise DeploymentFailedError("Health check failed, rolled back")

            return result

        except Exception as e:
            # Rollback on any error
            await self.rollback(service_name, current_revision)
            raise
```

**Database Worker - ADR 003 Integration:**

```python
# mahavishnu/workers/database.py

class DatabaseWorker(BaseWorker):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.recovery_manager = ErrorRecoveryManager(self.app)

        # Database-specific recovery patterns
        self.recovery_manager.recovery_actions.update({
            "DATABASE_MIGRATION_FAILED": RecoveryAction(
                strategy=RecoveryStrategy.NOTIFY,  # Manual intervention required
                category=ErrorCategory.PERMANENT,
                max_attempts=1,
                notify_on_failure=True,
            ),
            "DATABASE_BACKUP_FAILED": RecoveryAction(
                strategy=RecoveryStrategy.RETRY,
                category=ErrorCategory.TRANSIENT,
                max_attempts=3,
                backoff_factor=2.0,
            ),
            "DATABASE_CONNECTION_FAILED": RecoveryAction(
                strategy=RecoveryStrategy.RETRY,
                category=ErrorCategory.NETWORK,
                max_attempts=5,
                backoff_factor=1.5,
            ),
            "DATABASE_SCHEMA_CORRUPT": RecoveryAction(
                strategy=RecoveryStrategy.NOTIFY,
                category=ErrorCategory.PERMANENT,
                max_attempts=1,
                notify_on_failure=True,
            ),
        })

    async def run_migration(self, db_url: str, migration_dir: Path) -> WorkerResult:
        """Run migration with ADR 003 resilience."""
        return await self.recovery_manager.execute_with_resilience(
            self._run_migration_internal,
            db_url, migration_dir,
            workflow_id=self.worker_id,
        )

    async def _run_migration_internal(self, db_url: str, migration_dir: Path):
        """Internal migration with backup and verification."""
        # Auto-backup before migration
        backup_path = await self._auto_backup(db_url)

        try:
            # Run migration
            result = await self._run_migrations(migration_dir)

            # Verify migration
            verification = await self._verify_migration(db_url)
            if not verification.success:
                # Rollback migration
                await self.restore_database(db_url, backup_path)
                raise MigrationFailedError("Verification failed, restored from backup")

            return result

        except Exception as e:
            # Restore from backup on any error
            await self.restore_database(db_url, backup_path)
            raise
```

---

## 6. Disaster Recovery Considerations

### 6.1 Worker-Specific Recovery Procedures

**SSH Worker Recovery:**

```yaml
disaster_recovery:
  ssh_worker:
    # Recovery Time Objective (RTO)
    rto: 15  # minutes

    # Recovery Point Objective (RPO)
    rpo: 0  # minutes (stateless)

    # Backup requirements
    backup:
      - SSH keys (encrypted)
      - Known hosts file
      - Connection pool state (optional)

    # Recovery procedure
    steps:
      1. Verify SSH key access
      2. Restore known_hosts from backup
      3. Drain existing connections gracefully
      4. Restart SSH worker process
      5. Verify connection pool health
      6. Test command execution on known-good host

    # Rollback procedure
    rollback:
      - Kill new SSH worker process
      - Restore previous SSH worker binary
      - Restart with previous configuration

    # Validation
    validation:
      - Test SSH connection to 3 random hosts
      - Verify connection pool metrics
      - Check for leaked connections
```

**MQTT Worker Recovery:**

```yaml
disaster_recovery:
  mqtt_worker:
    rto: 10  # minutes
    rpo: 5  # minutes (offline buffer)

    backup:
      - Offline buffer (on disk)
      - Subscription list
      - QoS 2 message state (if supported)

    steps:
      1. Verify broker connectivity
      2. Drain offline buffer (if exists)
      3. Re-establish subscriptions
      4. Replay buffered messages
      5. Verify QoS delivery
      6. Clear offline buffer

    rollback:
      - Disconnect from new broker
      - Reconnect to previous broker
      - Restore subscription state

    validation:
      - Verify broker connection
      - Test publish to known-good topic
      - Verify subscription received
      - Check offline buffer size
```

**Cloud Run Worker Recovery:**

```yaml
disaster_recovery:
  cloud_run_worker:
    rto: 30  # minutes
    rpo: 0  # minutes (stateless)

    backup:
      - gcloud credentials
      - Deployment history
      - Service configuration

    steps:
      1. Verify gcloud authentication
      2. List active Cloud Run services
      3. Identify stuck deployments (if any)
      4. Rollback stuck services to last stable revision
      5. Verify service health
      6. Clear deployment queue

    rollback:
      - gcloud run services revert [SERVICE]

    validation:
      - Test deployment to test service
      - Verify health check passes
      - Check service URL accessible
      - Verify no stuck deployments
```

**Database Worker Recovery:**

```yaml
disaster_recovery:
  database_worker:
    rto: 60  # minutes
    rpo: 1440  # minutes (24 hours - last daily backup)

    backup:
      - Database dumps (automated daily)
      - Migration history
      - Backup verification logs

    steps:
      1. Identify corruption scope
      2. Stop all database operations
      3. Select appropriate backup (pre-incident)
      4. Restore database from backup
      5. Verify data integrity
      6. Re-run migrations since backup
      7. Verify application connectivity

    rollback:
      - Stop database operations
      - Restore pre-recovery backup
      - Re-investigate root cause

    validation:
      - PRAGMA integrity_check
      - Record count verification
      - Sample data verification
      - Application smoke test
```

### 6.2 Backup Integration

**Required Backup Components:**

```python
# mahavishnu/workers/backup.py (Priority 3 worker)

class BackupWorker(BaseWorker):
    """Backup coordination for all workers."""

    async def backup_ssh_worker_state(self):
        """Backup SSH worker state."""
        return {
            "ssh_keys": await self._backup_ssh_keys(),
            "known_hosts": await self._backup_known_hosts(),
            "connection_pool_state": await self._dump_connection_pool(),
        }

    async def backup_mqtt_worker_state(self):
        """Backup MQTT worker state."""
        return {
            "offline_buffer": await self._backup_offline_buffer(),
            "subscriptions": await self._backup_subscriptions(),
            "qos_state": await self._backup_qos_state(),
        }

    async def backup_cloud_run_worker_state(self):
        """Backup Cloud Run worker state."""
        return {
            "gcloud_credentials": await self._backup_gcloud_creds(),
            "deployment_history": await self._fetch_deployment_history(),
            "service_configs": await self._fetch_service_configs(),
        }

    async def backup_database_worker_state(self):
        """Backup database worker state."""
        return {
            "databases": await self._backup_all_databases(),
            "migration_history": await self._backup_migration_history(),
        }
```

---

## 7. Deployment Risks & Mitigations

### 7.1 Risk Register

| Risk | Likelihood | Impact | Score | Mitigation |
|------|------------|--------|-------|------------|
| SSH connection pool OOM | HIGH | HIGH | 15 | Enforce memory limits, connection caps |
| MQTT broker downtime | MEDIUM | HIGH | 12 | Offline buffer, multi-broker config |
| Cloud Run deployment stuck | MEDIUM | MEDIUM | 8 | Deployment queue, auto-rollback |
| Database migration rollback failure | LOW | CRITICAL | 10 | Pre-migration backup, verification |
| Worker resource starvation | HIGH | MEDIUM | 10 | Per-worker resource quotas |
| Concurrent migration conflicts | LOW | HIGH | 8 | Migration locking mechanism |
| SSH host key mismatch | LOW | MEDIUM | 6 | Host key verification, manual approval |
| MQTT subscription explosion | LOW | MEDIUM | 6 | Subscription limit enforcement |
| gcloud API quota exceeded | MEDIUM | MEDIUM | 8 | Rate limiting, retry with backoff |

### 7.2 Pre-Deployment Checklist

**Infrastructure Preparation:**
- [ ] Resource quotas created (CPU, memory, network)
- [ ] Monitoring dashboards created for all workers
- [ ] Alerting rules configured (P1 and P2)
- [ ] SLOs defined and tracked
- [ ] Error budgets calculated
- [ ] Circuit breaker thresholds configured
- [ ] Connection pool limits enforced
- [ ] Backup system tested
- [ ] Disaster recovery runbooks written
- [ ] On-call documentation complete

**Testing Completed:**
- [ ] Unit tests pass (>80% coverage)
- [ ] Integration tests pass (all workers)
- [ ] Load testing completed (100 concurrent SSH, 1000 MQTT subscriptions)
- [ ] Chaos engineering performed (kill broker, network partition)
- [ ] Failure injection tested (circuit breaker, DLQ)
- [ ] Backup/restore tested (all workers)
- [ ] Rollback procedure tested
- [ ] Resource limit testing (OOM, CPU starvation)

**Security Validation:**
- [ ] Secrets management integrated
- [ ] Audit logging enabled
- [ ] Host key verification enforced
- [ ] TLS/SSL validated
- [ ] ACL enforcement tested
- [ ] Command injection prevention tested

---

## 8. Recommendations

### 8.1 Critical (Must Fix Before Production)

1. **Define and enforce connection pool limits** - SSH worker must have hard connection caps to prevent OOM
2. **Implement worker-level resource quotas** - CPU, memory, network limits per worker
3. **Create worker-specific SLOs** - Success rate, latency, availability for each worker
4. **Add circuit breakers for all external dependencies** - MQTT broker, SSH hosts, Cloud Run API
5. **Implement offline buffering for MQTT** - Handle broker disconnections gracefully
6. **Add pre-migration backup verification** - Test restore before running migration
7. **Create worker-specific runbooks** - Step-by-step procedures for common failures
8. **Implement deployment queuing for Cloud Run** - Rate limit concurrent deployments
9. **Add connection admission control** - Backpressure when pools full
10. **Test disaster recovery procedures** - Verify backup/restore for all workers

### 8.2 High Priority (Should Fix Before Production)

1. **Add multi-broker MQTT configuration** - High availability for MQTT
2. **Implement automatic rollback on health check failure** - Cloud Run deployments
3. **Add migration locking** - Prevent concurrent migrations
4. **Create worker-specific monitoring dashboards** - Grafana dashboards for each worker
5. **Implement graceful shutdown** - Drain connections before shutdown
6. **Add worker health endpoints** - /health for each worker
7. **Implement retry with jitter** - Prevent thundering herd on failures
8. **Add worker startup ordering** - Dependencies must start before dependents
9. **Create on-call rotation** - Define on-call responsibilities and escalation
10. **Implement chaos engineering** - Regular failure injection tests

### 8.3 Medium Priority (Nice to Have)

1. **Add worker performance benchmarking** - Baseline performance metrics
2. **Implement worker auto-scaling** - Scale workers based on load
3. **Add worker versioning** - Support multiple worker versions
4. **Implement worker telemetry** - Detailed tracing for worker operations
5. **Add worker sandboxing** - Isolate worker failures
6. **Create worker performance SLAs** - Internal team agreements
7. **Implement worker cost monitoring** - Track GCP costs for Cloud Run
8. **Add worker compliance logging** - Audit trail for all operations
9. **Implement worker rate limiting per tenant** - Multi-tenant support
10. **Create worker capacity planning** - Forecast resource needs

---

## 9. Conclusion

The worker expansion plan has a **solid foundation** with ADR 003 integration and mentions of security, testing, and monitoring. However, **critical operational gaps** must be addressed before production deployment:

**CRITICAL GAPS:**
1. No connection pool limits (SSH OOM risk)
2. No resource quotas (unbounded growth)
3. No worker-specific SLOs (no success criteria)
4. No multi-broker MQTT (single point of failure)
5. No automatic rollback (manual intervention required)
6. No chaos engineering (untested failure modes)

**RECOMMENDED TIMELINE:**
- **Week 1-2**: Address critical gaps (connection limits, resource quotas, SLOs)
- **Week 3-4**: Implement high-priority items (multi-broker, auto-rollback, dashboards)
- **Week 5-6**: Load testing, chaos engineering, disaster recovery testing
- **Week 7-8**: On-call training, runbook finalization, production deployment

**FINAL VERDICT:**
❌ **NOT PRODUCTION READY** - Score 5.5/10
✅ **PRODUCTION READY** after critical gaps addressed - Estimated Score 8.5/10

**Next Steps:**
1. Review this assessment with engineering team
2. Prioritize critical gaps based on risk
3. Create mitigation tickets with clear acceptance criteria
4. Re-assess after critical gaps addressed
5. Conduct production readiness review (PRR)
6. Obtain explicit approval for production deployment

---

**Assessment Completed**: 2025-02-03
**Next Review**: After critical mitigation completed
**Assessor**: SRE Engineer (Claude Sonnet 4.5)
**Approved By**: [PENDING]
