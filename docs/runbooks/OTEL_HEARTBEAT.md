# Runbook: OTel Heartbeat Watcher

Operational guide for the Bodai span-producer heartbeat. The watcher lives in
`akosha/observability/heartbeat_watcher.py`; it asks the span substrate, once
a minute, "did each rostered service send me a span in the last 60 seconds?"
and counts the ones that did not.

This runbook covers the three alerts the watcher raises, what each one actually
proves, and how to find and fix the cause. It assumes you are at a terminal on
the host and the alert is firing.

**Scope.** The heartbeat proves that *producers report*. It does not prove the
receiver works — the canary (`OtelReceiverCanaryStale`) covers that half. If
you are triaging a span problem and are not sure which half is broken, start
with the [decision matrix](#the-two-halves) below; it tells you which system to
open.

**Prerequisites.** `curl`, `jq`, `plutil`, `launchctl`, and `lsof` (all
present on a Bodai host). The Prometheus UI is on `:9090`; akosha's MCP port is
`:8682`.

---

## One-minute triage

Run these three in order. The first that answers your question ends the triage.

```bash
# 1. What is the watcher actually seeing right now?
curl -fsS http://localhost:8682/metrics | grep -E '^akosha_otlp_heartbeat_'

# 2. Is anyone absent RIGHT NOW? (not "was anyone ever absent")
pq() { curl -fsSG http://localhost:9090/api/v1/query --data-urlencode "query=$1"; }
pq 'increase(akosha_otlp_heartbeat_p0_a_total[5m]) > 0'

# 3. Is the substrate itself readable?
pq 'increase(akosha_otlp_heartbeat_query_failed_total[5m]) > 0'
```

Query 2 returning series is the whole diagnosis: each series names one silent
producer. Query 3 returning series means the substrate is broken and the
P0-A alert is *lying to you* — see
[Scenario 2](#scenario-2-otelheartbeatqueryfailedpersistent).

> **The counter values in step 1 are not an outage indicator.** They are
> cumulative since akosha booted. A producer that was silent for four hours
> last week leaves its counter at 156 forever. Only `increase()` over a recent
> window tells you about *now*. Always use `increase(...)`, never the raw
> counter. See [Gotchas](#gotchas).

---

## The three alerts

| Rule | Counter | `for` | Proves |
|---|---|---|---|
| `OtelHeartbeatProducerSilent` | `akosha_otlp_heartbeat_p0_a_total{exported_service}` | 30s | a rostered producer missed **two consecutive** 60s windows (120s) |
| `OtelHeartbeatQueryFailedPersistent` | `akosha_otlp_heartbeat_query_failed_total{code}` | 2m | the substrate **could not be read** — a closed, locked, or corrupt database |
| `OtelHeartbeatRosterEmpty` | `akosha_otlp_heartbeat_empty_roster_total` | 30s | the roster is **empty**, so nothing is being watched at all |

The rules live in `mahavishnu/config/prometheus/health_aggregator_alerts.yml`,
group `bodai-otel-heartbeat`, and are unit-tested by
`config/prometheus/tests/heartbeat_rules.test.yml`.

### One window earlier than the alert

`akosha_otlp_heartbeat_service_absent_total` increments on **every** missed
window, so it moves one window (60s) before P0-A does. This is the early
warning — use it to catch a producer going quiet before it pages anyone:

```bash
pq 'increase(akosha_otlp_heartbeat_service_absent_total[5m]) > 0'
```

`service_absent_total` also exists for a service that has *never* been absent —
it has no series at all until its first miss. Absence of the series means
"never happened", not "zero".

### The roster

The set of services being watched is **configuration**, not code:

```bash
grep -A 8 'known_mcp_servers' /Users/les/Projects/akosha/settings/akosha.yaml
```

As of 2026-10-28: `mahavishnu`, `akosha`, `session-buddy`, `oneiric`,
`crackerjack`. A service that is not on this list is never checked, so it can
be completely silent forever without any alert.

---

## The two halves

Two independent mechanisms cover the span pipeline, and each proves a
different thing. Knowing which half is broken is most of the diagnosis.

| | Heartbeat watcher | Synthetic canary |
|---|---|---|
| Lives in | `akosha/observability/heartbeat_watcher.py` | akosha's receiver |
| Asks | "did a rostered producer send a span?" | "did the receiver insert a row?" |
| Proves | producers **report** | the receiver **writes** |
| Silently passes when | the producer stopped sending | the receiver accepts OTLP and drops the write |
| Fails on | a *quiet* producer | a *broken* write path |

Read them together with the matrix below.

| Canary | P0-A | P0-B | Diagnosis | Go to |
|---|---|---|---|---|
| fresh | quiet | quiet | healthy | — |
| fresh | **firing** | quiet | **producer-side.** The receiver writes, the substrate is readable, but a rostered service stopped sending. | [Scenario 1](#scenario-1-otelheartbeatproducersilent) |
| fresh | quiet | **firing** | **read path broken.** The substrate cannot be queried. The producers may be perfectly healthy. | [Scenario 2](#scenario-2-otelheartbeatqueryfailedpersistent) |
| stale | **firing** | quiet | **write path broken.** The receiver accepts spans over OTLP and then drops them on insert. | [Scenario 2](#scenario-2-otelheartbeatqueryfailedpersistent), then akosha's `docs/ops/OTEL_TEMPO_HOOK.md` |
| stale | quiet | **firing** | substrate broken both ways. Start with the substrate. | [Scenario 2](#scenario-2-otelheartbeatqueryfailedpersistent) |

Check the canary side with:

```bash
curl -fsS http://localhost:8682/metrics | grep -E '^akosha_otlp_canary_'
```

`akosha_otlp_canary_writes_rejected_total` naming a non-zero `reason` points
straight at the failure.

---

## Scenario 1: `OtelHeartbeatProducerSilent`

A rostered service sent no span for two consecutive minutes.

### Symptoms

- The alert names a producer in `exported_service` (e.g. `session-buddy`).
- `akosha_otlp_heartbeat_p0_a_total{exported_service="<name>"}` is climbing.
- The watcher's log confirms it:

  ```bash
  grep 'heartbeat_watcher.p0_a' ~/.local/state/mcp/logs/akosha.err | tail -5
  # akosha.heartbeat_watcher.p0_a service=session-buddy consecutive_absences=157
  #   window_seconds=60 — no span for 9420s
  ```

  `consecutive_absences` is the streak in 60s windows. `no span for 9420s` is
  the same thing in seconds. A streak of 2 means it just crossed the
  threshold; a streak in the hundreds means it has been down for hours.

### Diagnosis

Work down this list — it is ordered by how often each cause turns out to be
the real one.

**1. Is the service even running?**

```bash
launchctl list | grep com.mcp.session-buddy
```

Three columns: `PID`, `last exit status`, `label`.

- **No PID** → the service is not running at all. That is a *different*
  incident (the service is down), and it will not fix itself by restarting the
  telemetry stack.
- **PID present, exit status non-zero** → the *current* run is fine; the
  *previous* one exited badly. Common after a manual restart. Not necessarily
  your problem.
- **PID present, exit status `1` and the PID keeps changing** → the service is
  in a **restart loop**. Jump to cause 4.

**2. Does the running process have the OTLP endpoint?**

This is the most common cause: the service starts, but nothing tells it where
to send spans, so it emits them into a void.

```bash
svc=session-buddy
pid=$(launchctl list | awk -v s="com.mcp.$svc" '$3==s{print $1}')
child=$(pgrep -P "$pid" | head -1)
ps eww -p "$child" | tr ' ' '\n' | grep OTEL_EXPORTER
```

> **The launchd PID is the bash wrapper, not Python.** `launchctl list` gives
> you `launch_with_healthcheck.sh`; the Python process that actually holds the
> environment is its **child**. Checking the wrapper's environment will make
> you conclude the env var is missing when it is present. Always `pgrep -P`.

Expected:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

**3. Does the plist still carry them?**

The env var lives in the launchd plist. If it is missing there, the service
silently goes quiet on the next restart — with no code change to blame.

```bash
plutil -p ~/Library/LaunchAgents/com.mcp.session-buddy.plist | grep -i otel
```

If the key is absent, the fix is to add it back to the plist's
`EnvironmentVariables` and restart the service.

> **Use `plutil`, not Python's `plistlib`, to read these plists.** Two of the
> LaunchAgent plists on this host contain `--` inside an XML comment, which is
> illegal XML, so `plistlib.load()` raises on them. `plutil` uses Apple's own
> parser and handles them fine. See [Gotchas](#gotchas).

**4. Is the service being killed before it becomes healthy?**

The launchd wrapper polls `/health` for `--timeout` seconds and then kills the
process, so launchd restarts it, so it is killed again. The service never
reaches the point of emitting a liveness span, and P0-A fires forever.

```bash
plutil -p ~/Library/LaunchAgents/com.mcp.session-buddy.plist | grep -A1 '"--timeout"'
```

Measured real boot times on this host: akosha ~55s, session-buddy ~34–60s,
crackerjack ~68s, oneiric ~22s, mahavishnu ~90s. **The timeout must exceed
the boot time with margin.** 300s is the safe value; 60s and 120s have both
been too short in practice. A service in this loop shows a churning PID in
`launchctl list` and a log full of the wrapper's own timeout message:

```bash
grep -iE "timeout|healthcheck" ~/.local/state/mcp/logs/session-buddy.err | tail -10
```

**5. Is anything listening on the OTLP port?**

```bash
lsof -nP -iTCP:4318 -sTCP:LISTEN
```

Nothing listening means the producer has nowhere to send spans. The receiver
should be owned by akosha's process. Note the PID here is a *child* of
akosha's launchd wrapper, not the wrapper itself.

**6. Is the producer's telemetry code actually in place?**

Every Bodai MCP server reports through one shared seam: `mcp_common`'s
`launcher.launch()`. If the service's venv has a **stale mcp-common** without
the producer-telemetry code, the service starts happily and emits nothing.

```bash
/Users/les/Projects/mcp-common/.venv/bin/python -c \
  "import mcp_common.server as s; print(s.__version__, hasattr(s, 'run_liveness_emitter'))"
```

`hasattr` must be `True`. If it is `False`, the venv has an mcp-common
without the producer telemetry — reinstall it.

**7. Is the endpoint URL semantically right?**

`OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` are
**not** interchangeable:

| Variable | `http://127.0.0.1:4318` means |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://127.0.0.1:4318/v1/traces` (path appended) |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | `http://127.0.0.1:4318` (used verbatim) |

Setting the *traces* variable to a bare host:port sends spans to a URL with no
signal path, and the receiver never sees them. The generic variable is the
one to use for a bare `host:port`.

### Recovery

| Cause | Fix |
|---|---|
| Service not running | `launchctl kickstart -k gui/$(id -u)/com.mcp.<svc>` |
| Missing env var in the running process | Restart the service after confirming the plist has the key |
| Missing env var in the plist | Add `OTEL_EXPORTER_OTLP_ENDPOINT` + `OTEL_EXPORTER_OTLP_PROTOCOL` to `EnvironmentVariables`, then restart |
| Boot timeout too short | Raise `--timeout` to 300 in the plist's `ProgramArguments`, then restart |
| Nothing on port 4318 | Restart akosha — it owns the receiver |
| Stale mcp-common in the venv | Redeploy the built mcp-common into that service's venv, then restart |
| Wrong endpoint variable | Set `OTEL_EXPORTER_OTLP_ENDPOINT`, remove the traces-specific one, restart |

Restart one service at a time and let it settle before moving on:

```bash
launchctl kickstart -k gui/$(id -u)/com.mcp.session-buddy
sleep 30
launchctl list | grep com.mcp.session-buddy
```

Give it a full boot plus a heartbeat window (≈60–90s) before judging it.

### Verification

```bash
# 1. The early-warning query is quiet again.
pq 'increase(akosha_otlp_heartbeat_service_absent_total[5m]) > 0'   # -> 0 series

# 2. The alert's own expression is quiet.
pq 'increase(akosha_otlp_heartbeat_p0_a_total[5m]) > 0'             # -> 0 series

# 3. The producer is genuinely reporting.
curl -fsS http://localhost:8682/metrics \
  | grep 'akosha_otlp_heartbeat_service_absent_total'
```

Verification 3 is the one that matters most: the counter for that service
should be **flat** — present, but not increasing. A counter that is absent
entirely means the service has not been absent even once.

---

## Scenario 2: `OtelHeartbeatQueryFailedPersistent`

The watcher's query **raised** rather than returning no rows.

### Symptoms

- The alert carries a `code` label: `catalog`, `connection`, `io`,
  `operational`, `runtime`, `timeout`, or `not_initialized`.
- `akosha_otlp_heartbeat_query_failed_total{code="..."}` is climbing.

### Why this is a different incident

**A query that ran and found no rows is evidence about a producer. A query
that could not run is evidence about the substrate.** While a query is
failing, the watcher **suppresses P0-A entirely** — it returns before applying
any streak update. So during a P0-B episode the fleet looks perfect: no
producer is ever marked absent, because nobody could ask.

**Paging on P0-B sends you to the wrong system.** Do not start restarting
producers.

### Diagnosis

```bash
# 1. What kind of failure?
curl -fsS http://localhost:8682/metrics | grep -E '^akosha_otlp_heartbeat_query_failed_total'

# 2. The full exception is in the log, with a traceback.
grep -A 20 'heartbeat_watcher.query_failed' ~/.local/state/mcp/logs/akosha.err | tail -30
```

| `code` | Usual cause |
|---|---|
| `connection` | the substrate file is locked by another process |
| `catalog` | the DuckDB catalog is unreadable — the file is corrupt or the schema is wrong |
| `io` | the substrate file is missing or unreadable on disk |
| `timeout` | a long-running query held the read lock past the deadline |
| `operational` / `runtime` | a DuckDB-internal error; the traceback names it |

Check the substrate file and who holds it:

```bash
ls -la ~/.local/state/mcp/ | grep -i span
lsof ~/.local/state/mcp/*spans* 2>/dev/null
```

A `connection` error with a second process holding the file usually means
**two akosha instances are running** — a leftover from a bad restart. Find the
second one and stop it.

### Recovery

1. If a second akosha holds the lock, stop it (`launchctl bootout
   gui/$(id -u)/com.mcp.akosha` for the wrong one, then re-bootstrap the
   right one).
2. If the file is corrupt, akosha's substrate-lift path rebuilds it — see
   the spec §8 (retention and rollover) and akosha's
   `docs/ops/OTEL_TEMPO_HOOK.md`.
3. Restart akosha once the substrate is readable.

### Verification

```bash
pq 'increase(akosha_otlp_heartbeat_query_failed_total[5m]) > 0'  # -> 0 series
pq 'increase(akosha_otlp_heartbeat_p0_a_total[5m]) > 0'            # -> 0 series
```

Both must be quiet. The second one matters: while P0-B was firing, P0-A was
suppressed, so **producers that went silent during the outage will surface
now**. Expect a P0-A alert immediately after a P0-B clears — that is correct
behaviour, not a second fault. Check each producer against Scenario 1.

---

## Scenario 3: `OtelHeartbeatRosterEmpty`

The roster is empty, so the watcher is checking nothing.

### Symptoms

- `akosha_otlp_heartbeat_empty_roster_total` is climbing.
- The counter fires **every cycle** while the roster is empty.

### Why this is a P0 and not a non-event

An empty roster means the watcher cannot detect a dead producer **at all**.
"Everything is fine" is the one answer it must never give: a registry wipe, or
a substrate lift that dropped every entry, is indistinguishable from a healthy
system until somebody looks. The other two rules are silent in this state —
P0-A cannot fire because there is no roster to miss.

### Diagnosis

```bash
grep -A 8 'known_mcp_servers' /Users/les/Projects/akosha/settings/akosha.yaml
```

The roster is read at **lifespan startup**. An empty roster means either the
settings key is empty or missing, or akosha started before the settings were
readable.

```bash
# Is the key present but empty, or absent entirely?
grep -n -A 8 'known_mcp_servers' /Users/les/Projects/akosha/settings/akosha.yaml
grep -i 'known_mcp_servers\|roster' ~/.local/state/mcp/logs/akosha.err | tail -10
```

### Recovery

1. Restore the roster in `akosha/settings/akosha.yaml`.
2. Restart akosha — the roster is boot-populated, so editing the file alone
   changes nothing.
3. Verify the roster took effect **before** declaring victory: the absence
   counters for every service should reappear, because the watcher starts
   asking about them again.

### Verification

```bash
pq 'increase(akosha_otlp_heartbeat_empty_roster_total[5m]) > 0'   # -> 0 series
curl -fsS http://localhost:8682/metrics \
  | grep 'akosha_otlp_heartbeat_service_absent_total'              # -> one series per rostered service
```

The second check is the real one. A quiet empty-roster counter with no
absence counters at all means the roster is *still* empty and the watcher
still has nothing to check.

---

## Gotchas

**Cumulative counters are not outage indicators.** `p0_a_total` and
`service_absent_total` only ever go up, and they reset when akosha restarts.
A value of 156 means "156 windows were missed, at some point, since boot" —
possibly last week. Always ask about a window:

```bash
pq 'increase(akosha_otlp_heartbeat_p0_a_total[5m]) > 0'
```

**The producer is `exported_service`, never `service`.** The scrape config
labels the *target* — akosha's receiver at `:8682` — with `service: akosha`,
and Prometheus renames the counter's own `service` label to
`exported_service`. Every series carries both. An alert that read
`{{ $labels.service }}` would announce "akosha" for every producer in the
fleet: an alert that fires correctly and points at the wrong service is worse
than one that does not fire, because it looks like it works.

**The alert lingers ~5 minutes after recovery.** The expression uses
`increase(...[5m])`, so the window still contains the last increment for five
minutes. The alert clears when the window is entirely after the last
increment. This is deliberate: it gives the operator time to see the alert
rather than missing a blip. Do not restart a service because the alert is
still firing ten seconds after it started reporting.

**The launchd PID is a wrapper.** `launchctl list` shows
`launch_with_healthcheck.sh`. The Python process is its child. Anything you
want to read from the process's environment — the OTLP endpoint above all —
lives on the child.

**XML comments in a plist may not contain `--`.** The XML spec forbids a
double hyphen anywhere inside a comment, and a plist that uses one as an em
dash is not well-formed XML. `plutil` and launchd use Apple's own parser and
accept it; Python's `plistlib` and any strict XML tool reject the whole file.
Two LaunchAgent plists carried this defect until 2026-10-28
(`com.mcp.mahavishnu.plist` and `com.bodai.llama-server.plist`). **Read these
files with `plutil -p` or `grep` anyway** — they are the plists most likely to
be hand-edited, and `plistlib` is what finds the problem. If you add a comment
to a plist, write an em dash (`—`), not `--`.

**`OTEL_EXPORTER_OTLP_ENDPOINT` vs `..._TRACES_ENDPOINT`.** The generic
variable appends `/v1/traces` to a bare `host:port`; the traces-specific
variable is used verbatim. Only the generic one works with a bare port.

---

## Where things live

| Thing | Path |
|---|---|
| The watcher | `akosha/observability/heartbeat_watcher.py` |
| The roster | `akosha/settings/akosha.yaml` → `otel.receiver.known_mcp_servers` |
| The alert rules | `mahavishnu/config/prometheus/health_aggregator_alerts.yml` → group `bodai-otel-heartbeat` |
| The rule unit test | `mahavishnu/config/prometheus/tests/heartbeat_rules.test.yml` |
| The rule test runner | `mahavishnu/tests/unit/test_prometheus_alert_rules.py` |
| The producer seam | `mcp_common/server/producer_telemetry.py` |
| The launcher wiring | `mcp_common/server/launcher.py` |
| The spec | `mahavishnu/docs/specs/2026-10-19-bodai-substrate-otel-v7.md` §11 |
| The launchd plists | `~/Library/LaunchAgents/com.mcp.<service>.plist` |
| The logs | `~/.local/state/mcp/logs/<service>.err` |
| The boot-budget wrapper | `~/.local/state/mcp/scripts/launch_with_healthcheck.sh` |
