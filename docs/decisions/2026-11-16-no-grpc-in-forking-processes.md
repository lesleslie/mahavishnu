---
status: active
role: canonical
date: 2026-11-16
last_reviewed: 2026-11-16
topic: no-grpc-in-forking-processes
---

# A process that forks must not have grpcio loaded

## Context

On 2026-11-15 a Mahavishnu MCP server began crashing its own children
roughly every 30 seconds. macOS wrote 43 `Python-*.ips` reports with one
signature:

```
EXC_BAD_INSTRUCTION (SIGILL)
BUG IN CLIENT OF LIBDISPATCH: trying to lock recursively
*** multi-threaded process forked ***
crashed on child side of fork pre-exec
```

The faulting thread was always c-ares' DNS resolver
(`ares_init_sysconfig_macos` → `dns_configuration_copy` →
`os_log_type_enabled` → `_dispatch_once_wait`), and the forking thread was
always CPython's `subprocess` fork path
(`subprocess_fork_exec` → `do_fork_exec` → `child_exec` → `execv`).

The MCP server's own log carried the missing link, 212 times:

```
fork_posix.cc:71] Other threads are currently calling into gRPC, skipping fork() handlers
```

### Why the fork is unavoidable

macOS CPython 3.14 cannot use `posix_spawn` for `subprocess` with the
default `close_fds=True`: `os.POSIX_SPAWN_CLOSEFROM` does not exist on
macOS, so CPython's own gate (`not close_fds or _HAVE_POSIX_SPAWN_CLOSEFROM`)
always fails. Measured on this host — bare name, absolute path, `cwd=`, and
`start_new_session` all take the fork path; only `close_fds=False` plus an
absolute path plus no `cwd` reaches `posix_spawn`. macOS also lacks
`POSIX_SPAWN_CLOEXEC_DEFAULT` and `posix_spawn_file_actions_addchdir_np`,
so a hand-rolled fork-free spawn cannot reproduce `close_fds`/`cwd`
semantics without leaking file descriptors to the child.

### Why the fork is fatal

`fork()` copies a libdispatch `dispatch_once` token that may be
mid-initialization in another thread. In the child that thread does not
exist, but the token still reads "in progress", so the child's next
dispatch_once re-entry trips libdispatch's recursion check and aborts the
child with SIGILL. grpcio's c-ares calls `dns_configuration_copy()` — and
therefore that `dispatch_once` — on every DNS re-resolution, so a live
grpcio channel keeps re-arming the window. gRPC's own fork handler is
skipped in exactly that case ("Other threads are currently calling into
gRPC"), which is gRPC reporting that the fork was unsafe.

The caller's symptom was `subprocess.CalledProcessError: ... died with <Signals.SIGILL: 4>` — the `git diff` that builds a merge-review prompt
died before it could produce output.

### Where grpcio came from

Exactly one import: `mahavishnu/core/observability.py` imported the OTLP
**gRPC** exporters at module scope. `lsof` confirmed
`cygrpc.cpython-314-darwin.so` mapped into the running MCP server. Turning
the exporters off stopped the crash reports dead (27 before, 27 after) —
which confirmed the causal chain end to end.

## Decision rule

**A Mahavishnu process that forks must not have grpcio loaded.**

Concretely:

1. The OTLP exporters are imported **lazily**, inside the exporter
   builders — never at module scope. Importing
   `mahavishnu.core.observability` must not put `grpc` in `sys.modules`.

2. The **default OTLP transport is HTTP/protobuf**
   (`OTEL_EXPORTER_OTLP_PROTOCOL` defaults to `http/protobuf`, matching
   `mcp_common.server.producer_telemetry`). The gRPC exporter remains
   reachable for an operator who explicitly asks for it, and the request is
   recorded here as re-arming this hazard.

3. **Traces and metrics have separate destinations**, because the
   substrate's OTLP/HTTP listener serves `/v1/traces` only:

   - traces → the substrate on `:4318` → `spans_substrate`
   - metrics → Alloy on `:14318` → prometheus `:12345` → Grafana

   This restores the `observability.otlp_metrics_endpoint` field that
   `docs/plans/2026-10-27-otel-metrics-service.md` removed. That removal
   was correct **for the gRPC transport**, where the substrate served
   MetricsService and TraceService on one port. Over HTTP the split is
   forced by the receivers, not by a choice.

4. **Fork sites are worth removing anyway.** The plan-index rebuild forked
   once per plan document — 60 forks per cycle, twice at startup. It now
   makes two: one `git ls-tree` for every blob SHA and one
   `git remote get-url` for the repo URL. Fewer forks is less exposure, and
   it is faster.

The generalisation for the fleet: **a process that forks and a runtime that
starts background threads are incompatible on macOS.** Either the forks go
or the threads go.

## Status

Active. The transport change shipped with this record; the plan-index fork
reduction and its `repo:`-fallback fix shipped with it.

Not addressed here, and deliberately:

- The gRPC transport is still *selectable*. An operator who sets
  `OTEL_EXPORTER_OTLP_PROTOCOL=grpc` re-arms the hazard. Removing the
  branch entirely would be safer, but it would take the decision away from
  the operator, and `mcp_common` keeps the same branch.
- `docs/decisions/README.md` does not yet index this file; the entry is
  owed to whichever session next touches that file, because it is being
  edited concurrently elsewhere.
