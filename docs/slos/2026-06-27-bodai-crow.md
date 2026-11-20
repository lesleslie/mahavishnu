# SLOs: Bodai Crow HTTP MCP Server (Plan 1)

- **Name**: bodai-crow
- **Owner**: mahavishnu-orchestration
- **Plan / RFC**: Plan 1 — Bodai Crow HTTP MCP scaffold + tools (commit `eb47401`)
- **Date ratified**: 2026-06-27

Bodai Crow exposes MCP tools over an HTTP transport. These SLOs cover the
external surface (inbound requests) and the security posture of the
proxy layer.

## SLOs

### SLO 1 — Request success rate

| Field | Value |
|-------|-------|
| SLI | `sum(rate(http_requests_total{service="bodai-crow",code=~"2.."}[5m])) / sum(rate(http_requests_total{service="bodai-crow"}[5m]))` |
| Objective | `>= 99.5%` over rolling 30 days |
| Burn-rate alert | `2%` of budget consumed in `1h` |
| Page after | `15m` of sustained breach |
| Runbook | `docs/runbooks/bodai-crow-5xx.md` (TODO) |

### SLO 2 — p99 latency

| Field | Value |
|-------|-------|
| SLI | `histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{service="bodai-crow"}[5m])))` |
| Objective | `<= 500 ms` over rolling 30 days |
| Burn-rate alert | `1.5%` of budget consumed in `1h` |
| Page after | `15m` of sustained breach |
| Runbook | `docs/runbooks/bodai-crow-latency.md` (TODO) |

### SLO 3 — SSRF block rate

| Field | Value |
|-------|-------|
| SLI | `sum(rate(ssrf_blocks_total{service="bodai-crow"}[5m])) / max(sum(rate(ssrf_probes_total{service="bodai-crow"}[5m])), 1)` |
| Objective | `100%` (every detected SSRF probe is blocked) over rolling 30 days |
| Burn-rate alert | Any single day with `< 100%` block rate |
| Page after | Immediate (security SLO) |
| Runbook | `docs/runbooks/bodai-crow-ssrf.md` (TODO) |

## Rollback

- **Command**: `mahavishnu rollback bodai-crow --to-version <sha>`
- **Selector options**: `--to-version` is a git SHA of the `bodai-crow` artifact
- **What it reverts**: the running Bodai Crow HTTP server to the tagged SHA
- **What it preserves**: request logs, session state in Session-Buddy
- **Average time to complete**: target `< 60s` (operator-initiated)

## Error budget policy

- **Window**: rolling 30 days
- **Actions when exhausted**:
  1. Freeze non-critical deploys to bodai-crow until budget recovers.
  2. File an incident in `docs/incident-response/` if breach is security-related.
  3. Re-baseline SLOs only after a documented post-mortem.

## Change log

| Date | Author | Change |
|------|--------|--------|
| 2026-06-27 | audit-H8 | Initial SLOs added per audit finding H8 |
