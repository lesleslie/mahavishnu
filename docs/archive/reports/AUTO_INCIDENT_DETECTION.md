# Auto-Incident Detection and Response System

## Overview

The Auto-Incident Detection and Response System provides comprehensive incident management with automatic detection, correlation, remediation, and notification capabilities.

## Features

### Core Capabilities

- **Automatic Incident Detection**: Detect incidents from ecosystem events within 30 seconds
- **20+ Predefined Detection Rules**: Out-of-the-box rules for common incidents
- **Event Correlation**: Group related events and identify root causes
- **Auto-Remediation**: Automatically fix common incidents
- **Multi-Channel Notifications**: Email, Slack, PagerDuty, and phone alerts
- **Real-Time Streaming**: WebSocket support for live incident updates
- **MTTD/MTTR Tracking**: Track Mean Time To Detect and Resolve

### Performance Targets

- Detect incidents within 30 seconds
- Auto-resolve simple incidents within 2 minutes
- Handle 100+ incidents/hour

## Architecture

### Components

1. **IncidentDetector**: Main detection engine
   - Processes events for incident detection
   - Manages detection rules
   - Coordinates with other components

2. **IncidentCorrelator**: Event correlation and analysis
   - Groups related events by correlation ID and time
   - Detects root cause patterns
   - Identifies affected systems
   - Generates incident timelines

3. **AutoResponder**: Automatic remediation
   - Executes predefined remediation actions
   - Safe mode for critical actions
   - Tracks remediation history

4. **IncidentNotifier**: Multi-channel alerts
   - Routes notifications based on severity
   - Supports Email, Slack, PagerDuty, phone

5. **DetectionRule**: Configurable detection patterns
   - Event pattern matching
   - Confirmation thresholds
   - Time windows
   - Auto-remediation flags

### Data Models

```python
class Incident(BaseModel):
    incident_id: str
    timestamp: datetime
    title: str
    description: str
    severity: IncidentSeverity  # LOW, MEDIUM, HIGH, CRITICAL
    status: IncidentStatus  # DETECTED, INVESTIGATING, MITIGATING, RESOLVED, FALSE_POSITIVE
    source_events: list[str]
    affected_systems: list[str]
    correlation_id: str | None
    root_cause: str | None
    mitigation_actions: list[str]
    assigned_to: str | None
    resolution_time: datetime | None
    mttd_seconds: int | None  # Mean Time To Detect
    mttr_seconds: int | None  # Mean Time To Resolve
    tags: list[str]
    metadata: dict[str, Any]
```

## Usage

### Basic Usage

```python
from mahavishnu.integrations.auto_incident import IncidentDetector
from mahavishnu.integrations.event_collector import EcosystemEvent

# Initialize detector
detector = IncidentDetector(
    event_collector_url="http://localhost:8000",
    mahavishnu_url="http://localhost:8678",
    auto_remediation_enabled=True,
    notifications_enabled=True,
)
await detector.start()

# Process event for detection
event = EcosystemEvent(
    source_system="crackerjack",
    event_type="quality_check_failed",
    severity="critical",
    data={"score": 45, "threshold": 80}
)
incident = await detector.process_event(event)

# Get active incidents
active_incidents = await detector.get_active_incidents()

# Update incident status
await detector.update_incident_status(
    incident.incident_id,
    IncidentStatus.INVESTIGATING
)

# Assign incident
await detector.assign_incident(
    incident.incident_id,
    "team@example.com"
)

# Add mitigation action
await detector.add_mitigation_action(
    incident.incident_id,
    "Restarted failing service"
)

# Get statistics
stats = await detector.get_stats()

# Shutdown
await detector.stop()
```

### Convenience Function

```python
from mahavishnu.integrations.auto_incident import detect_incidents
from mahavishnu.integrations.event_collector import EcosystemEvent

events = [
    EcosystemEvent(
        source_system="mahavishnu",
        event_type="workflow_failed",
        severity="error",
        data={"workflow_id": "abc123"}
    )
]

incidents = await detect_incidents(events)
```

## Detection Rules

### Predefined Rules (20 total)

#### Error Detection
1. **error_burst_detection** - Rapid increase in errors (>10/min for 5 min)
2. **critical_error_pattern** - Security-related errors (path_traversal, hardcoded_secrets)

#### Availability
3. **service_down_detection** - System stops emitting events (heartbeat timeout)

#### Quality
4. **quality_drop_detection** - Quality score drops >20 points in 5 minutes

#### Workflow
5. **workflow_failure_spike** - Workflow failure rate >20% for 10 minutes

#### Resource
6. **memory_exhaustion_detection** - Memory usage >90% for 3+ systems
7. **disk_space_exhaustion** - Disk usage >95% across systems

#### Performance
8. **performance_degradation** - p95 latency >10 seconds for 5 minutes

#### Database
9. **database_connection_issues** - Database connection failures
10. **deadlock_detected** - Database or application deadlocks

#### Security
11. **security_incident_pattern** - Suspicious activity (multiple auth failures)
12. **certificate_expiration** - SSL/TLS certificates nearing expiration

#### API
13. **api_rate_limit_exceeded** - API rate limits exceeded

#### Cache
14. **cache_failure_spike** - High cache failure rates

#### Queue
15. **queue_backlog** - Message queue backlog exceeds threshold

#### Data Integrity
16. **data_corruption_detected** - Data corruption or consistency issues

#### Network
17. **network_partition** - Network connectivity issues

#### Kubernetes
18. **pod_crash_loop** - Pods in crash loop backoff

#### Deployment
19. **deployment_failure** - Deployment or rollout failures

#### ML Anomaly
20. **anomaly_detection** - Anomalies detected by Akosha (ML-based)

### Custom Rules

```python
from mahavishnu.integrations.auto_incident import DetectionRule, IncidentSeverity

custom_rule = DetectionRule(
    name="custom_high_latency",
    description="Detect when API latency exceeds threshold",
    severity=IncidentSeverity.HIGH,
    event_pattern="latency_measurement",
    severity_filter="warning",
    confirmation_threshold=5,
    time_window_seconds=300,
    affected_systems=["api_gateway"],
    auto_remediation=True,
    remediation_actions=["scale_up", "clear_cache"],
    enabled=True,
    metadata={"category": "performance"}
)

await detector.add_detection_rule(custom_rule)
```

## Auto-Remediation

### Supported Actions

- `restart_service` - Restart affected services
- `scale_up` - Scale up resources
- `clear_cache` - Clear application caches
- `kill_queries` - Kill long-running database queries
- `pause_workflows` - Pause workflow execution
- `scale_workers` - Scale up worker pools
- `rebuild_cache` - Rebuild caches
- `cleanup_logs` - Cleanup old log files
- `restart_pod` - Restart Kubernetes pods
- `rollback_deployment` - Rollback recent deployment
- `escalate` - Escalate to on-call engineer
- `notify_team` - Notify team about incident

### Safe Mode

Safe mode requires approval for critical actions:
- `kill_queries`
- `rollback_deployment`
- `escalate`

```python
responder = AutoResponder(
    mahavishnu_url="http://localhost:8678",
    safe_mode=True  # Enable safe mode
)

actions_taken = await responder.attempt_auto_remediation(incident)
```

## Notifications

### Severity-Based Routing

- **LOW**: Log only
- **MEDIUM**: Email + Slack
- **HIGH**: PagerDuty + Slack + Email
- **CRITICAL**: Phone call + PagerDuty + Slack + Email

### Configuration

```python
from mahavishnu.integrations.auto_incident import IncidentNotifier

notifier = IncidentNotifier(
    slack_webhook_url="https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
    pagerduty_api_key="your_pagerduty_api_key",
    email_from="incidents@example.com",
    email_recipients={
        "high": ["oncall@example.com"],
        "critical": ["oncall@example.com", "manager@example.com"]
    }
)

await notifier.notify(incident)
```

## FastAPI Endpoints

The detector provides a REST API on port 8000:

### Incident Management

- `POST /incidents/detect` - Manually trigger detection
- `GET /incidents` - List all incidents (with filters)
- `GET /incidents/{incident_id}` - Get incident details
- `PUT /incidents/{incident_id}/status` - Update status
- `PUT /incidents/{incident_id}/assign` - Assign incident
- `POST /incidents/{incident_id}/mitigate` - Add mitigation action
- `GET /incidents/{incident_id}/timeline` - Get incident timeline

### Rule Management

- `POST /incidents/rules` - Add detection rule
- `GET /incidents/rules` - List all rules
- `DELETE /incidents/rules/{rule_id}` - Delete rule

### Monitoring

- `GET /incidents/stats` - Get incident statistics
- `GET /health` - Health check

### WebSocket

- `WS /incidents/stream` - Real-time incident updates

## Statistics

Track incident metrics:

```python
stats = await detector.get_stats()

print(f"Total incidents: {stats['total_incidents']}")
print(f"Active incidents: {stats['active_incidents']}")
print(f"Resolved incidents: {stats['resolved_incidents']}")
print(f"Incidents detected: {stats['incidents_detected']}")
print(f"Auto-resolved: {stats['incidents_auto_resolved']}")
print(f"Events processed: {stats['events_processed']}")
print(f"Avg MTTD: {stats['avg_mttd_seconds']}s")
print(f"Avg MTTR: {stats['avg_mttr_seconds']}s")
```

## Testing

### Run Tests

```bash
# Run all auto-incident tests
pytest tests/unit/test_integrations/test_auto_incident.py -v

# Run specific test class
pytest tests/unit/test_integrations/test_auto_incident.py::TestIncidentDetector -v

# Run without performance tests
pytest tests/unit/test_integrations/test_auto_incident.py -v -k "not slow and not performance"
```

### Test Coverage

- 52 unit tests covering all components
- Tests for models, rules, correlator, responder, notifier, detector
- Integration tests for end-to-end workflows
- Performance tests for high-volume processing

## File Locations

- **Implementation**: `/Users/les/Projects/mahavishnu/mahavishnu/integrations/auto_incident.py`
- **Tests**: `/Users/les/Projects/mahavishnu/tests/unit/test_integrations/test_auto_incident.py`
- **Documentation**: `/Users/les/Projects/mahavishnu/docs/AUTO_INCIDENT_DETECTION.md`

## Integration with Ecosystem

### Event Collector Integration

```python
# Subscribe to event collector stream
# Events automatically processed for incident detection
```

### Mahavishnu Integration

```python
# Trigger workflows for remediation
# Scale pools based on incidents
# Query incident status from workflows
```

### Akosha Integration

```python
# ML-based anomaly detection rule
# Correlate anomalies across systems
```

## Best Practices

1. **Start with Predefined Rules**: Use the 20 built-in rules before creating custom ones
2. **Tune Thresholds**: Adjust confirmation_threshold and time_window_seconds for your environment
3. **Enable Safe Mode**: Keep safe mode enabled for production deployments
4. **Monitor MTTD/MTTR**: Track these metrics to improve detection and response times
5. **Test Auto-Remediation**: Validate remediation actions in staging before production
6. **Set Up Notifications**: Configure all notification channels for critical incidents
7. **Review Incidents Regularly**: Analyze resolved incidents to improve detection rules

## Troubleshooting

### Incident Not Detected

1. Check if detection rule is enabled
2. Verify event pattern matches event type
3. Confirm confirmation_threshold is met
4. Check time_window_seconds setting

### Auto-Remediation Not Working

1. Verify auto_remediation_enabled=True
2. Check if rule has auto_remediation=True
3. Confirm remediation_actions are configured
4. Check if safe mode is blocking critical actions

### Notifications Not Sent

1. Verify notifications_enabled=True
2. Check webhook URLs and API keys
3. Confirm severity routing is configured
4. Check notification history

## Future Enhancements

- [ ] Machine learning-based incident prediction
- [ ] Integration with more notification services (Opsgenie, VictorOps)
- [ ] Incident templates and runbooks
- [ ] Post-incident analysis reports
- [ ] Integration with incident management platforms (ServiceNow, Jira)
- [ ] Custom remediation scripts
- [ ] Incident similarity detection
- [ ] Automated root cause analysis
