---
status: draft
role: implementation
kind: reference
date: 2026-04-06
last_reviewed: 2026-11-05
superseded_by: null
topic: observability
title: Prometheus Metrics Inventory
---

# Prometheus Metrics Inventory

**Re-derived 2026-11-05.** The previous revision of this document mapped
four TUI screens onto Prometheus metric names that **have never existed in
this repository**, and it claimed the TUI reads Prometheus. It does not.
This revision records what is actually there.

Verified 2026-11-05 against `mahavishnu/tui/app.py`,
`mahavishnu/core/routing_metrics.py`, and the live metric-name registry
(82 distinct `mahavishnu_*` names).

## The TUI does not read Prometheus

`mahavishnu/tui/app.py` defines **13 screens** and **13 in-process
`fetch_*()` coroutines**. None of them references Prometheus,
`prometheus_client`, the metrics port, or a scrape URL. The TUI renders
data the server process already holds — the mapping the previous revision
described was never implemented, and no screen reads a metric.

The Prometheus surface is separate: `start_routing_metrics_server(port=9091)`
in `mahavishnu/core/routing_metrics.py` exposes the routing metrics for
scraping by Grafana or Prometheus.

## TUI screen → data source

Each screen is listed with the coroutine that feeds it. "Metric backing"
names the closest real Prometheus series, where one exists.

| Screen | Fetch coroutine | Metric backing |
|---|---|---|
| `OverviewScreen` | `fetch_system_overview` | `mahavishnu_health_feed_status`, `mahavishnu_adapter_health_status`, `mahavishnu_workflows_total`, `mahavishnu_active_tasks`, `mahavishnu_budget_alerts_total` |
| `SweepScreen` | `fetch_sweep_history` | none — no sweep series is registered |
| `RoutingScreen` | `fetch_routing_stats` | `mahavishnu_routing_decisions_total`, `mahavishnu_routing_fallbacks_total`, `mahavishnu_routing_latency_seconds`, `mahavishnu_adapter_latency_seconds`, `mahavishnu_routing_cost_usd_current` |
| `AlertsScreen` | `fetch_active_alerts` | `mahavishnu_budget_alerts_total` (budget alerts only — there is no general alert series) |
| `ReviewsScreen` | `fetch_skill_drafts` | none |
| `SessionScreen` | `fetch_session_summary` | none |
| `RecoveryScreen` | `fetch_recovery_summary` | `mahavishnu_resilience_circuit_transitions_total`, `mahavishnu_resilience_retry_attempts_total`, `mahavishnu_resilience_retry_amplification_ratio` |
| `ApprovalsScreen` | `fetch_pending_approvals` | none |
| `FilesScreen` | `fetch_file_views`, `fetch_diff_views` | none |
| `EventStreamScreen` | `fetch_event_activity` | `mahavishnu_eventbridge_publish_total`, `mahavishnu_audit_events_total` |
| `AgnoScreen` | `fetch_agno_activity` | none |
| `TraceScreen` | `fetch_correlation_trace` | none |
| `BodaiComponentScreen` | (uses the ecosystem-status envelope) | `mahavishnu_health_feed_status` |

## The routing-metrics surface (port 9091)

Every series below is declared in `mahavishnu/core/routing_metrics.py`.
Types are the `prometheus_client` constructor used at the declaration site.

| Metric | Type | Labels |
|---|---|---|
| `mahavishnu_routing_decisions_total` | counter | `server`, `adapter`, `task_type` |
| `mahavishnu_adapter_executions_total` | counter | `server`, `adapter`, `status` |
| `mahavishnu_routing_fallbacks_total` | counter | `server`, `original_adapter`, `fallback_adapter` |
| `mahavishnu_routing_cost_usd_total` | counter | `server`, `adapter`, `task_type` |
| `mahavishnu_budget_alerts_total` | counter | `server`, `budget_type`, `severity` |
| `mahavishnu_ab_tests_total` | counter | `server`, `experiment_group`, `event_type` |
| `mahavishnu_rate_limit_rejected_total` | counter | `server`, `model` |
| `mahavishnu_routing_cost_usd_current` | gauge | `server`, `budget_type` |
| `mahavishnu_ab_tests_active` | gauge | `server` |
| `mahavishnu_routing_latency_seconds` | histogram | `server` |
| `mahavishnu_routing_fallback_chain_length` | histogram | `server` |
| `mahavishnu_routing_cost_usd_distribution` | histogram | `server`, `adapter` |
| `mahavishnu_adapter_latency_seconds` | histogram | `server`, `adapter` |

Two naming traps worth recording: `mahavishnu_routing_fallback_chain_length`
is a **histogram**, not a gauge; and `mahavishnu_budget_alerts_total` is
labelled by `budget_type` and `severity` — it is the budget-alert series,
not a general alert series.

## Other metric families

The routing server is not the only source of `mahavishnu_*` series. The
registry holds 82 distinct names across these modules:

| Module | Family |
|---|---|
| `mahavishnu/core/task_metrics.py` | `mahavishnu_task_operations_total`, `mahavishnu_task_errors_total`, `mahavishnu_task_duration_seconds`, `mahavishnu_task_domain_queue_depth`, `mahavishnu_task_domain_concurrency`, `mahavishnu_task_domain_throughput`, `mahavishnu_task_domain_rate_limited_total`, `mahavishnu_task_domain_concurrency_drift_total` |
| `mahavishnu/core/health_integration.py` | `mahavishnu_adapter_health_status`, `mahavishnu_health_checks_total`, `mahavishnu_health_state_changes_total` |
| `mahavishnu/core/goal_team_metrics.py` | `mahavishnu_goal_teams_*` (created, parsed, active, errors, learning, skill usage) |
| `mahavishnu/core/dlq_integration.py`, `mahavishnu/core/dead_letter_queue.py` | `mahavishnu_dlq_*` |
| `mahavishnu/observability/prometheus_metrics.py` | `mahavishnu_health_feed_status` |
| `mahavishnu/metrics_cli.py` | `mahavishnu_workflows_total` |

## Grafana dashboards

Three dashboard files exist under `docs/grafana/`, and all three parse as
valid JSON:

| File | Status |
|---|---|
| `docs/grafana/Routing_Monitoring.json` | valid |
| `docs/grafana/Symbiotic-Ecosystem.json` | valid |
| `docs/grafana/WebSocket_Monitoring.json` | valid |

`docs/grafana/Pool_Monitoring.json` was listed here as a corrupted file to
remove. It has since been deleted, so there is nothing left to remove.

## Metric names that never existed

The 2026-04-06 revision listed the names below. **None of them was ever
registered in this repository** — they appeared only in this document. They
are recorded here so nobody re-adds them to a dashboard or a query.

| Name | Nearest real series |
|---|---|
| `mahavishnu_health_status` | `mahavishnu_health_feed_status` |
| `mahavishnu_workflows_running` | `mahavishnu_workflows_total` / `mahavishnu_active_tasks` |
| `mahavishnu_adapters_registered` | `mahavishnu_adapter_health_status` |
| `mahavishnu_alerts_active` | `mahavishnu_budget_alerts_total` |
| `mahavishnu_alerts_total{severity=...}` | `mahavishnu_budget_alerts_total{severity=...}` |
| `mahavishnu_cost_budget_alerts_total` | `mahavishnu_budget_alerts_total` |
| `mahavishnu_sweeps_total` | none |
| `mahavishnu_sweeps_success_total` | none |
| `mahavishnu_sweeps_failed_total` | none |
| `mahavishnu_sweep_duration_seconds` | none |
| `mahavishnu_routing_cache_hits_total` | none — there is no routing-cache series |
| `mahavishnu_routing_cache_misses_total` | none — there is no routing-cache series |

The `Sweep History` and `Sweep Success Rate` Grafana panel definitions in
the previous revision were built on `mahavishnu_sweeps_*` and have been
removed for the same reason: their queries would have returned nothing.

## Still to do

- Nothing in the sweep family is instrumented. If the sweep screen needs
  series, they have to be registered before a dashboard can plot them.
- There is no general alert series. `AlertsScreen` reads live alert state
  from the server, and `mahavishnu_budget_alerts_total` covers only the
  budget subset.
