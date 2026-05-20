# Adaptive Routing System

Mahavishnu implements intelligent adaptive routing with statistical learning and cost optimization.

## Routing Components

**StatisticalRouter**: Analyzes adapter performance and generates preference orders based on historical data.

**CostOptimizer**: Pareto frontier analysis for multi-objective optimization (cost vs latency vs success rate).

**TaskRouter**: Coordinates adapters with fallback chains and graceful degradation when primary adapters fail.

**ExecutionTracker**: Storage-agnostic metrics collection with batch writes and TTL cleanup.

**Lazy metric initialization**: Prevents duplicate Prometheus registration errors by deferring metric setup.

## Monitoring & Alerting

**Routing Metrics** (`mahavishnu/core/routing_metrics.py`):

- Prometheus metrics on port 9091 (configurable via `monitoring.routing_metrics_port`)
- Counter metrics: decisions, executions, fallbacks, costs, budget alerts, A/B test events
- Histogram metrics: routing latency, adapter latency, fallback chain length, cost distribution
- Gauge metrics: current costs, active experiments

**Alerting System** (`mahavishnu/core/routing_alerts.py`):

- Adapter degradation detection (success rate < 95%)
- Cost spike detection (2x multiplier triggers alert)
- Excessive fallback detection (> 10% rate)
- Alert handlers: Logging, Webhook (Slack/PagerDuty/etc.)
- Background evaluation loop (60s intervals)

## Grafana Dashboard

Pre-built dashboard at `docs/grafana/Routing_Monitoring.json`:

1. Open Grafana: `http://localhost:3000`
1. Dashboards → Import → Upload `Routing_Monitoring.json`
1. Select Prometheus datasource: `http://localhost:9091`
1. View 12 panels: routing decisions, success rates, latency percentiles, fallbacks, costs, budgets, A/B tests

## Metrics API

```python
from mahavishnu.core.routing_metrics import get_routing_metrics

metrics = get_routing_metrics()  # Lazy singleton pattern

# Metrics server starts automatically with MahavishnuApp
# Available at: http://localhost:9091
```

## Routing Configuration

Enable in `settings/mahavishnu.yaml`:

```yaml
routing:
  enabled: true
  cost_budget_type: "daily"
  cost_limit: 100
  optimization_strategy: "cost"  # cost, latency, or balanced
```

See `docs/plans/2026-05-10-minimax27-provider-migration.md` for task-to-model routing details.
