# Prometheus Metrics Inventory

Maps TUI dashboard screens to canonical Prometheus metric names.
All metrics exposed on port 9091 (see `mahavishnu/core/routing_metrics.py`).

## Overview Screen

| TUI Widget        | Prometheus Metric                          | Type      |
|-------------------|-------------------------------------------|-----------|
| System Status     | `mahavishnu_health_status`                | gauge     |
| Active Workflows   | `mahavishnu_workflows_running`            | gauge     |
| Adapter Count      | `mahavishnu_adapters_registered`          | gauge     |
| Recent Alerts      | `mahavishnu_alerts_active`                | gauge     |

## Sweep Screen

| TUI Widget        | Prometheus Metric                          | Type      |
|-------------------|-------------------------------------------|-----------|
| Sweep Count       | `mahavishnu_sweeps_total`                 | counter   |
| Success Rate       | `mahavishnu_sweeps_success_total`         | counter   |
| Failure Rate       | `mahavishnu_sweeps_failed_total`          | counter   |
| Sweep Duration     | `mahavishnu_sweep_duration_seconds`       | histogram |

## Routing Screen

| TUI Widget        | Prometheus Metric                          | Type      |
|-------------------|-------------------------------------------|-----------|
| Routing Decisions | `mahavishnu_routing_decisions_total`      | counter   |
| Cache Hit Rate     | `mahavishnu_routing_cache_hits_total`     | counter   |
| Cache Miss Rate    | `mahavishnu_routing_cache_misses_total`   | counter   |
| Adapter Latency    | `mahavishnu_adapter_latency_seconds`      | histogram |
| Fallback Count     | `mahavishnu_routing_fallbacks_total`      | counter   |

## Alerts Screen

| TUI Widget        | Prometheus Metric                          | Type      |
|-------------------|-------------------------------------------|-----------|
| Active Alerts      | `mahavishnu_alerts_active`                | gauge     |
| Alert Severity     | `mahavishnu_alerts_total{severity=...}`   | counter   |
| Budget Alerts      | `mahavishnu_cost_budget_alerts_total`     | counter   |

## Grafana Panel Definitions

### Sweep History Panel

```json
{
  "title": "Sweep History",
  "type": "table",
  "datasource": "Prometheus",
  "targets": [
    { "expr": "mahavishnu_sweeps_total" },
    { "expr": "mahavishnu_sweeps_success_total" },
    { "expr": "mahavishnu_sweeps_failed_total" }
  ]
}
```

### Sweep Success Rate Panel

```json
{
  "title": "Sweep Success Rate",
  "type": "stat",
  "datasource": "Prometheus",
  "targets": [
    {
      "expr": "rate(mahavishnu_sweeps_success_total[5m]) / rate(mahavishnu_sweeps_total[5m])"
    }
  ]
}
```

## Stale Assets

The following Grafana dashboard file is corrupted (invalid JSON) and should be
removed:

- `docs/grafana/Pool_Monitoring.json` — JSON parse error at line 10

Valid dashboards:
- `docs/grafana/Routing_Monitoring.json` ✓
- `docs/grafana/Symbiotic-Ecosystem.json` ✓
- `docs/grafana/WebSocket_Monitoring.json` ✓
