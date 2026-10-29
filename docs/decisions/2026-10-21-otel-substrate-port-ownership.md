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

- No `otelcol` process is running. The Docker daemon is not running either
  (socket absent), so there is no container roster to inspect.
- Nothing listens on `:14317` / `:14318`.
- Nothing listens on the ports in `config/otel-collector-config.yaml`.
- The 2026-09-28 relay it descends from (`/tmp/otel_relay.py`, documented in
  `settings/local.yaml:4-19`) is gone — `/tmp` cleanup or a reboot removed it,
  and `MAHAVISHNU_OBSERVABILITY__OTLP_ENDPOINT` is unset in the current shell
  and absent from `~/.zshenv`.

The collector actually holding both ports is **Homebrew Grafana Alloy**
(`alloy run`, PID 942, started by
`~/Library/LaunchAgents/sh.brew.grafana-alloy.plist`), configured at
`/usr/local/etc/grafana-alloy/config.alloy`. The spec's consumer table mentions
Alloy only as a relay template to update — it never names Alloy as the port
owner. Following §13.1 as written would move a config that owns nothing and
leave the real conflict untouched.

Two further findings shape the decision:

1. **Alloy's trace pipeline is a dead end.** `config.alloy:58-67` routes
   traces to `otelcol.exporter.debug`, which writes spans to Alloy's own log
   and never persists or forwards them. No span sent to Alloy today reaches
   durable storage. Only *metrics* survive, via `otelcol.exporter.prometheus`
   on `:12345` (confirmed live and serving metrics) feeding Grafana.
2. **Alloy is the designated ingress, not a competitor.** `~/.zshrc:183-196`
   exports **three** OTLP endpoints at it — `CODEX_OTEL_EXPORTER_OTLP_ENDPOINT`
   (:188), `QWEN_TELEMETRY_EXPORTER_OTLP_ENDPOINT` (:191), and the generic
   `OTEL_EXPORTER_OTLP_ENDPOINT` (:193). Claude Code has no endpoint export of
   its own; it reaches `:4318` through the generic variable like any other
   OTel SDK consumer. The two `CLAUDE_CODE_*` lines in the block are
   `CLAUDE_CODE_ENABLE_TELEMETRY=1` (a toggle) and
   `CLAUDE_CODE_PROMETHEUS_PORT=9465` (a **Prometheus scrape** port — nothing
   listens on 9465, and it must not be repointed at an OTLP receiver).

   At survey time there were six established connections from four producers
   (a point-in-time census, not a stable set — see the bifrost risk below):

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
```

The `:4319`-`:4322` claude/qwen receivers are **not** Alloy's — they exist
only in the dead `config/otel-collector-config.yaml`, and nothing listens on
them today. They are untouched by this decision and stay out of scope.

The substrate is the *storage*, not a relay hop. A span should reach durable
storage in one hop; making the substrate a downstream of a collector that never
persists traces would preserve the existing data loss under a new name.

Concretely, at PR-A3:

| Item | Change |
|---|---|
| `/usr/local/etc/grafana-alloy/config.alloy` | `otelcol.receiver.otlp.cli_tools` binds `:14317` gRPC / `:14318` HTTP |
| `~/.zshrc:188,191,193` | 3 OTLP endpoint exports repointed to the substrate (`:4318` stays canonical). **Not** `CLAUDE_CODE_PROMETHEUS_PORT` (:186) — a scrape port, not an endpoint |
| `akosha` | `AKOSHA_OTLP_ENDPOINT` → the substrate receiver, not a collector |
| `mahavishnu` | `MAHAVISHNU_OBSERVABILITY__OTLP_ENDPOINT=http://127.0.0.1:4318` (HTTP port — an `http://` URL must not target `:4317`, which is gRPC) |
| `config/grafana/dashboards/*.json` | no change needed — none reference 4317/4318/12345 |

### Receiver ports must be configurable

Spec §Appendix D declares `PROMETHEUS_PORT = 9464` as a class attribute, but
the gRPC/HTTP ports appear only as literals inside `start()`'s docstring. There
is no seam. PR-A3 must add `GRPC_PORT` / `HTTP_PORT` class attributes and
settings keys alongside `PROMETHEUS_PORT`, so the port assignment above is a
setting rather than a code edit. Without this, any later port change is a
source edit in a receiver that four producers are pointed at.

## Rollback

Reverting is a port move, not a data migration — the substrate's DuckDB file is
independent of the port number.

1. Restore `config.alloy` to `:4317` / `:4318` and restart
   (`brew services restart grafana-alloy`).
2. Restore the 3 OTLP endpoint exports in `~/.zshrc` (lines 188, 191, 193).
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
- **The `:4319`-`:4322` claude/qwen receivers belong to nobody.** They are
  declared only in the dead `config/otel-collector-config.yaml`; Alloy's config
  has no such receivers and nothing listens on them. Out of scope for v7 per
  §13.1, but sub-spec B should decide whether they are revived or deleted —
  the same collision logic will apply if they are revived.

## Status

Active. PR-A3 executes this. Amends spec §13.1 — see the `2026-10-21` edit in
`docs/specs/2026-10-19-bodai-substrate-otel-v7.md`.
