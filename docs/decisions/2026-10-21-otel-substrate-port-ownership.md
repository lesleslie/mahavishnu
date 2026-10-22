---
status: active
role: canonical
date: 2026-10-21
last_reviewed: 2026-10-21
topic: otel-port-ownership
---
# OTel substrate owns the canonical OTLP ports

## Context

v7 spec §13.1 planned to resolve the `:4317` / `:4318` collision by moving
the collector configured in `config/otel-collector-config.yaml` (`:4317`
→ `:14317`, `:4318` → `:14318`) and giving the ports to Akosha's
`OTLPReceiver`.

That plan targets a process that does not exist. Verified 2026-10-21:

- No `otelcol` process is running; no Docker containers are up.
- Nothing listens on `:14317` / `:14318`.
- Nothing listens on the ports in `config/otel-collector-config.yaml`.
- The 2026-09-28 relay it descends from (`/tmp/otel_relay.py`, documented in
  `settings/local.yaml:4-8`) is gone — `/tmp` cleanup or a reboot removed it,
  and `MAHAVISHNU_OBSERVABILITY__OTLP_ENDPOINT` is unset in the current shell.

The collector actually holding both ports is **Homebrew Grafana Alloy**
(`alloy run`, PID 942, started by `sh.brew.grafana-alloy.plist`), configured at
`/usr/local/etc/grafana-alloy/config.alloy`. The spec's consumer table mentions
Alloy only as a relay template to update — it never names Alloy as the port
owner. Following §13.1 as written would move a config that owns nothing and
leave the real conflict untouched.

Two further findings shape the decision:

1. **Alloy's trace pipeline is a dead end.** `config.alloy:58-67` routes
   traces to `otelcol.exporter.debug`. Every span sent to Alloy today is
   discarded after a 2 s batch. Only *metrics* survive, via
   `otelcol.exporter.prometheus` on `:12345` (confirmed live, 608 metric
   lines) feeding Grafana.
2. **Alloy is the designated ingress, not a competitor.** `~/.zshrc:183-195`
   points every producer at it: Claude Code, Codex CLI, Qwen Code, plus the
   generic `OTEL_EXPORTER_OTLP_ENDPOINT`. At survey time there were six live
   connections (a point-in-time census, not a stable set — see the bifrost
   risk below):

   | Producer | Transport | Destination |
   |---|---|---|
   | `akosha mcp start` | HTTP | `:4318` |
   | `claude` (2 sessions) | HTTP | `:4318` |
   | `bifrost-http` (2 conns) | HTTP | `:4318` |
   | `scripts/launch_mcp.py` | gRPC | `:4317` |

## Decision rule

**The canonical OTLP ports belong to the substrate. Alloy keeps a
non-canonical port pair for metrics.**

```
producers ──> :4317 gRPC / :4318 HTTP ──> Akosha OTLPReceiver
                                                │
                                                └──> spans_substrate (DuckDB)

:14317 / :14318 ──> Alloy  (metrics ──> :12345 ──> Grafana)
:4319 - :4322     ──> Alloy  (claude/qwen receivers, unchanged)
```

The substrate is the *storage*, not a relay hop. A span should reach durable
storage in one hop; making the substrate a downstream of a collector that
discards traces would preserve the existing data loss under a new name.

Concretely, at PR-A3:

| Item | Change |
|---|---|
| `/usr/local/etc/grafana-alloy/config.alloy` | `otelcol.receiver.otlp.cli_tools` binds `:14317` gRPC / `:14318` HTTP |
| `~/.zshrc:183-195` | 4 exports repointed to the substrate (`:4318` stays canonical) |
| `akosha` | `AKOSHA_OTLP_ENDPOINT` → the substrate receiver, not a collector |
| `mahavishnu` | `MAHAVISHNU_OBSERVABILITY__OTLP_ENDPOINT=http://127.0.0.1:4317` |
| Alloy `:4319`-`:4322` | untouched — reclassified out-of-scope by spec §13.1 |

### Receiver ports must be configurable

Spec §Appendix D declares `PROMETHEUS_PORT = 9464` as a class attribute, but
the gRPC/HTTP ports appear only as literals inside `start()`'s docstring. There
is no seam. PR-A3 must add `GRPC_PORT` / `HTTP_PORT` class attributes and
settings keys alongside `PROMETHEUS_PORT`, so the port assignment above is a
setting rather than a code edit. Without this, any later port change is a
source edit in a receiver that has five live producers pointed at it.

## Rollback

Reverting is a port move, not a data migration — the substrate's DuckDB file is
independent of the port number.

1. Restore `config.alloy` to `:4317` / `:4318` and restart
   (`brew services restart grafana-alloy`).
2. Restore the 4 exports in `~/.zshrc`.
3. Stop the substrate receiver.

Spans written to `spans_substrate` during the window stay readable via
`search_spans` / `spans_summary` regardless of who is bound to the port.

## Risks

- **`bifrost-http` endpoint is not configured anywhere we can find.** Its
  `~/.config/bifrost/config.json` has no otlp/telemetry key, its process
  environment carries no `OTEL_*` variable, and its binary contains no
  `localhost:4318` literal (only UI placeholder strings and unrelated digits
  inside big-integer constants). Yet at survey time it held two established
  connections to `:4318`. Whatever supplies that endpoint is outside the files
  we can read, so bifrost's cutover target cannot be confirmed by inspection —
  it must be observed at cutover. If bifrost is using the OTel SDK default, its
  spans begin landing in the substrate immediately and with no error, which is
  the intended outcome; if it is not, it may stop reporting with no local
  signal. Verify bifrost traces after the swap rather than assuming.
- **bifrost is an intermittent producer, not a persistent one.** Its
  connections to `:4318` were gone when re-checked ~50 minutes later, and the
  `bifrost-http` process itself (PID 76284) had exited. This is consistent
  with a batching exporter that flushes on an interval. Two consequences: a
  single point-in-time `lsof` sweep is an unreliable producer census (the
  same sweep missed bifrost entirely on the second pass), and a post-cutover
  check must observe bifrost *across at least one flush interval* or it will
  declare success against a producer that never ran.
- **Two `claude` sessions and `akosha` itself are live producers.** A bad
  cutover degrades telemetry silently rather than erroring at the socket.
- **The 2026-09-28 relay regression is a live trap.** `settings/local.yaml:4-19`
  still documents a relay topology that no longer exists. PR-A3 must update
  that file's comment block or delete it, or the next operator will follow a
  dead path.
- **Alloy's `:4319`-`:4322` receivers are a second, unresolved port cluster.**
  Out of scope for v7 per §13.1, but the same collision logic will apply to
  them when sub-spec B decides their fate.

## Status

Active. PR-A3 executes this. Amends spec §13.1 — see the `2026-10-21` edit in
`docs/specs/2026-10-19-bodai-substrate-otel-v7.md`.