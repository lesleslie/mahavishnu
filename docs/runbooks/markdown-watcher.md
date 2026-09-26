# Runbook: Markdown Board Watcher (C-11)

Operational guide for the file watcher that consumes `.mahavishnu/board.md` and dispatches cards. Per niche filter: scoped to our own jot files only — not a generic markdown-board engine. Per ADR 0001.

The watcher uses `async with asyncio.timeout(...)` (NOT `wait_for(async_generator)`) around `awatch()` to avoid deadlocks. State is persisted via `fcntl.flock` in `state_persistence.py`. Per round-5 fix, state is saved inside the try block (after successful dispatch).

## Scenario 1: `markdown_board_watcher_up` gauge = 0

**Symptoms:**
- `markdown_board_watcher_up == 0` for >30s
- `/health` returns degraded for the watcher component
- No cards dispatched despite board modifications
- Akosha receives `anomaly.detected` events with `anomaly_type: markdown_watcher_died`

**Diagnosis:**
1. Check whether the watcher process is running: `ps aux | grep markdown_watcher`
2. Check the supervisor's logs: `journalctl -u mahavishnu-markdown-watcher --since "10 min ago"`
3. Check whether the timeout is too short for the workload:
   ```bash
   # Default: watcher_lag_seconds=30, timeout = 30 * 3 = 90s
   cat settings/mahavishnu.yaml | grep -A1 markdown_board
   ```
4. Check whether `awatch()` raised an unhandled exception: `grep "watcher crashed" /var/log/mahavishnu/watcher.log`

**Recovery:**
1. **If process is dead**: the supervisor should restart it automatically (launchd plist / systemd unit). If not, file a supervisor bug.
2. **If timeout is too short** (file modifications faster than 90s): increase `markdown_board.watcher_lag_seconds`. **Do not multiply by 3** — the round-4 fix uses `* 3` but for hot files a different multiplier or a separate `processing_timeout_seconds` is more correct.
3. **If exception in awatch()**: file a bug with the trace. The watcher should restart cleanly on `Exception`.

**Verification:**
- `markdown_board_watcher_up == 1` within 1 minute
- `markdown_board_watcher_restarts_total` rate <0.1/s
- Cards dispatch on subsequent file modifications

## Scenario 2: `markdown_board_watcher_restarts_total` climbing

**Symptoms:**
- `markdown_board_watcher_restarts_total` rate >0.5/s for 5m
- Watcher appears to thrash (restart every 30-90s)
- Akosha receives frequent `anomaly.detected` events

**Diagnosis:**
1. Check the restart interval: `grep "watcher timeout" /var/log/mahavishnu/watcher.log | tail -10`
2. Check whether the file is being modified too frequently:
   ```bash
   inotifywait -t 30 .mahavishnu/board.md
   ```
3. If modifications >1/s, the watcher's processing loop cannot keep up with file churn.

**Recovery:**
1. **Add exponential backoff** to the restart loop (round-5 devops finding, not yet implemented):
   ```python
   backoff = min(60, 2 ** consecutive_timeouts)
   await asyncio.sleep(backoff)
   ```
2. **Reduce file modification frequency** at the source: if a script writes the board every second, throttle to once per minute
3. **Increase `watcher_lag_seconds`** so the timeout accommodates longer processing cycles
4. **If the watcher is genuinely broken**: `kill -9 <pid>` and let the supervisor restart with a fresh process

**Verification:**
- `markdown_board_watcher_restarts_total` rate <0.1/s within 10 minutes
- Watcher remains up (`markdown_board_watcher_up == 1`) for 30+ minutes

## Scenario 3: Cards stuck in `ready` section

**Symptoms:**
- `markdown_board_card_age_seconds{section="ready"}` >600s (10 minutes) for any card
- Cards in the board's `ready` section are not being dispatched
- `markdown_board_dispatch_total{section="ready", result="error"}` rate elevated

**Diagnosis:**
1. Check the card's `expected_revision`: if it doesn't match the current state, the CAS conflict prevents dispatch
2. Check the LLM upstream: is the configured provider reachable?
3. Check whether the dispatch path is blocked by C-9's concurrency gate (over-limit for the card's TaskCategory)
4. Check the dispatch queue depth: `markdown_board_queue_depth` (if metric exists)

**Recovery:**
1. **If CAS conflict**: bump `expected_revision` in the board file to match the current state (or remove the field for human-edited cards)
2. **If LLM unreachable**: check Bifrost or the configured LLM provider; restart if needed
3. **If concurrency gate**: see `docs/runbooks/concurrency-limit-storm.md`
4. **If queue backed up**: increase worker concurrency or reduce board size

**Verification:**
- `markdown_board_card_age_seconds{section="ready"}` <120s within 10 minutes
- All cards in `ready` section dispatch within 30s

## Scenario 4: Sidecar drift (`state_sidecar.json` doesn't match board)

**Symptoms:**
- Cards dispatched but state sidecar shows them as PENDING
- Re-dispatch on next file modification (duplicate work)
- `markdown_board_conflict_total` rate elevated

**Diagnosis:**
1. Read both files:
   ```bash
   cat .mahavishnu/board.md
   cat .mahavishnu/board.md.state.json  # or wherever state_sidecar is configured
   ```
2. Check `markdown_board.state_sidecar_suffix` setting: `cat settings/mahavishnu.yaml | grep sidecar`
3. Check whether `fcntl.flock` is functioning: `python -c "import fcntl; print('ok')"`
4. Check whether macOS flock semantics differ (round-5 finding): flock is per-fd on macOS, so cross-tool coordination is advisory-only.

**Recovery:**
1. **If sidecar is corrupted**: delete it; the watcher rebuilds state on next file modification
2. **If lock contention**: check whether other processes are reading the sidecar without flock; coordinate via `flocked_file()` helper
3. **If macOS-specific flock issue**: do not rely on cross-tool coordination via flock; use an external lock file or atomic rename

**Verification:**
- Sidecar content matches the board's expected dispatch state
- No re-dispatch on idempotent re-runs (per C-6's `IdempotencyOptions`)

## macOS flock caveat

`fcntl.flock` on macOS is per-fd, not per-path. Cross-tool coordination (e.g., `git checkout` of the board file, another CLI reading the sidecar) does NOT see the lock and may race. **Operators on macOS must rely on atomic rename or external coordination, not on flock alone.**

## Related

- [docs/plans/2026-09-26-impl-C-11-markdown-board-watcher.md](../plans/2026-09-26-impl-C-11-markdown-board-watcher.md) — implementation plan
- [docs/slos/2026-09-26-wireup-markdown-board.md](../slos/2026-09-26-wireup-markdown-board.md) — SLO targets
