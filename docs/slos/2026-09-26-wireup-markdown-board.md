# SLO: Markdown Board Watcher (C-11)

## Service

`mahavishnu.jot.markdown_watcher` — file watcher that consumes `.mahavishnu/board.md` (our jot files only, per niche filter) and dispatches cards via `pool_route_execute`.

The watcher uses `async with asyncio.timeout(...)` (NOT `wait_for(async_generator)`) around `awatch()`. State is persisted via `fcntl.flock` in `state_persistence.py`. Per round-5 fix, state is saved inside the try block (after successful dispatch).

## SLI

### Availability SLI

`markdown_board_watcher_up` gauge (1 = alive, 0 = dead):

- **Up >99.5% over 30-day rolling window**
- `markdown_board_watcher_restarts_total` rate \<0.1/s sustained
- Watch must NOT enter restart loop (round-5 devops finding)

### Latency SLI

Card age in `ready` section:

- **`markdown_board_card_age_seconds{section="ready"}` p99 < 120s**: cards dispatch within 2 minutes of `ready` placement
- **`markdown_board_card_age_seconds{section="backlog"}` p99 < 600s**: cards in backlog may wait longer

### Correctness SLI

State sidecar consistency:

- **Sidecar drift = 0**: state file matches board's expected dispatch state
- **`markdown_board_conflict_total` rate < 0.01/s**: CAS conflicts (CAS conflicts indicate human-edit races; rate >0.01/s suggests human-edit collision patterns)
- **`markdown_board_parse_errors_total` rate < 0.05/s**: malformed markdown in our jot files

## SLO Targets

| Metric | Target | Burn-rate alert |
|---|---|---|
| `markdown_board_watcher_up` | 1 (gauge) | gauge = 0 for 2m → page (per round-4 ops gap-fix) |
| `markdown_board_watcher_restarts_total` rate | \<0.1/s | >0.5/s for 5m → page |
| `markdown_board_card_age_seconds{section="ready"}` p99 | \<120s | >300s for 5m → warn; >600s for 10m → page |
| `markdown_board_dispatch_total{section="ready", result="error"}` rate | \<0.05/s | >0.1/s for 5m → page |
| `markdown_board_conflict_total` rate | \<0.01/s | >0.05/s for 5m → warn (CAS conflicts suggest human-edit races) |
| `markdown_board_parse_errors_total` rate | \<0.05/s | >0.1/s for 5m → page |

## Critical alerts (round-4 ops gap-fix)

1. **`markdown_board_watcher_up == 0 for 2m`** → page (per spec)
1. **`markdown_board_watcher_restarts_total` rate climbing** (3+ restarts in 5m) → warn
1. **`markdown_board_card_age_seconds{section="ready"} > 600 for 10m`** → warn (cards stuck in ready)
1. **`markdown_board_dispatch_total{section="ready", result="error"}` rate > 0.1/s for 5m** → page

## macOS flock caveat

`fcntl.flock` on macOS is per-fd, not per-path. Cross-tool coordination (e.g., `git checkout` of the board file) does NOT see the lock. **Operators on macOS must rely on atomic rename or external coordination, not on flock alone.**

## Error Budget

- **30-day budget**: 0.5% × 30 days = 3.6 hours of downtime allowed
- **Burn-rate policy**:
  - 1h burn rate >14.4× → page
  - 6h burn rate >6× → page
  - 24h burn rate >3× → ticket

## Page-after field

- **Initial response**: 5 minutes (watch-down is P0 because dispatch is blocked)
- **Update frequency**: every 15 minutes until resolved
- **Resolution target**: 30 minutes for P0; 4 hours for P1

## Runbooks

- [docs/runbooks/markdown-watcher.md](../runbooks/markdown-watcher.md) — markdown-watcher scenarios
- [docs/runbooks/on_call_handbook.md](../runbooks/on_call_handbook.md) — escalation procedures

## Related

- [docs/plans/2026-09-26-impl-C-11-markdown-board-watcher.md](../plans/2026-09-26-impl-C-11-markdown-board-watcher.md)
- [docs/adr/0001-mahavishnu-niche.md](../adr/0001-mahavishnu-niche.md)
