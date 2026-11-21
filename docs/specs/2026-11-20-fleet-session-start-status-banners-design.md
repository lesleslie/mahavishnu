---
status: draft
role: canonical
kind: spec
date: 2026-11-20
last_reviewed: 2026-11-21
superseded_by:
blocks_on: []
topic: fleet-session-status
title: "Fleet SessionStart Status Banners"
review:
  - 2026-11-20: authored from the live hook inventory of 2026-11-20
  - 2026-11-21: revised after builder check and live defect verification
---

# Fleet SessionStart Status Banners

## 1. Intent and the why

Les wants to *see* that the Bodai ecosystem components are alive when a Claude
Code session starts, in the same way the Semgrep Guardian plugin announces
itself:

```
○○○ Semgrep Guardian (wedgwoodwebworks): this session is protected, files are scanned as they are written
```

Today the opposite is true. Session-Buddy has a `SessionStart` hook that is
supposed to announce it, and it has been **silently doing nothing at all** —
the whole live integration is broken (Section 6). Mahavishnu ships a
`mahavishnu_ecosystem_status` capability that is supposed to report fleet
health, and it **cannot report a single component** (Section 6.4).

Both failures are the same shape: a capability that reports nothing, failing
silently. This spec defines the convention that makes them visible.

## 2. Goals

1. Session-Buddy announces itself at every session start, in every repository,
   because capturing sessions everywhere is the point.
2. Mahavishnu announces the **whole ecosystem** — active pools, worker counts,
   and per-component health — when working in the Mahavishnu repository, which
   is where most work happens.
3. The lines tell the truth in both directions: a component that is **down** or
   **degraded** says so.
4. The set of hooks in the ecosystem is discoverable and kept honest by a
   **registry plus a drift test**.
5. No hook can block session startup: bounded time, exit 0 on every path.

## 3. Non-goals

- **Not a monitoring dashboard.** A point-in-time snapshot at session start.
  Grafana, the `/health` endpoints, and `bodai-radar` remain the continuous
  surfaces.
- **Not a new daemon or watcher.** No background process, no polling loop.
- **Not a `SessionEnd` banner.**
- **Not a migration of the Kit Personal hooks** (`kit-onboard-inject.sh`,
  `kit-recall-first.sh`, `kit-hard-rules.sh`, `kit-capture.sh`,
  `kit-wake-gate.sh`) or the iTerm2 `cc-status` binary. Separate product
  surface, separate owner.
- **Not a fix for unrelated defects** found during the inventory. Those are
  catalogued in Section 9 and handled by their own plans — except the ones
  Section 7 puts in this plan's scope.
- **Not a push.** Publishing or pushing requires Les's explicit go-ahead.

## 4. Anti-goals

- A banner that says "alive" while the component's own hooks are broken.
- A banner that blocks the first prompt.
- A hand-maintained list of hooks that nobody checks.
- **A second fleet-health implementation.** The fleet view must come from
  Mahavishnu's own ecosystem-status capability, not from a parallel script.

## 5. Constraints (verified against the live Claude Code API)

| Constraint | Consequence |
|---|---|
| `systemMessage` is a **top-level sibling** of `hookSpecificOutput` | A hook that already emits `{"hookSpecificOutput": {...}}` gains a banner by adding one key to the same dict. |
| `systemMessage` → the **user**; `additionalContext` → the **model** | Both can be emitted from one hook. |
| `systemMessage` from an **`async: true`** hook is **not shown** | Every banner hook must be **synchronous**. |
| **`mcp_tool` hooks are skipped at initial launch** | Every banner hook must be a **`command`** hook. |
| stdout is parsed as JSON **only** when it is exactly one JSON object | The hook prints the JSON object and nothing else; diagnostics go to stderr. |
| `systemMessage` capped at 4000 characters (~20 lines) | A one-line banner is far inside. |
| A user-global hook cannot use `$CLAUDE_PROJECT_DIR` | User-global hooks are **stdlib-only**, interpreter-pinned by absolute path. |
| `uv run` wrappers add resolution latency | No `uv run` on the SessionStart critical path. |

### 5.1 The mechanism, proven live

Semgrep's own hook binary, run exactly as Claude Code invokes it:

```
$ printf '{"hook_event_name":"SessionStart","source":"startup"}' \
    | hook-darwin-amd64 auto SessionStatus
{"systemMessage":"○○○ Semgrep Guardian is running a one-time setup, and will start automatically when done"}
[exit=0]
```

Claude Code 2.1.330's renderer, extracted from the binary:

```js
function en(e){ return e.replace(/\r\n?|[\v\f\u0085]/g,"\n").split("\n").map(r=>Yn(Ig(Lr(r)))) }
function At(e){ let r=`${en(e.hookName).join(" ")} says: `; return en(e.content).map(o=>r+o).join("\n") }
function Oqo(e){ return {type:"system", subtype:"informational", content:At(e), level:"notice"} }
```

`"SessionStart:startup says: "` is the exact label Claude Code renders —
matching what Les already sees from Semgrep.

**Multi-line payloads survive.** A live isolated session (`claude -p` with
`--setting-sources "" --strict-mcp-config`) ran a hook emitting a five-line
figlet banner plus `○○○` and leading whitespace. The hook exited 0, the
session completed, and the payload arrived byte-for-byte in the
`hook_response`. Because `At()` prefixes **every** line, the ASCII art keeps
its shape (each row is shifted equally); the plain-stdout path, by contrast,
prefixes only the first line and would break the art. **`systemMessage` is the
art-safe channel.**

## 6. Current findings

### 6.1 Live hook inventory (2026-11-20)

**Mahavishnu repo** — `.claude/settings.json`, 11 registrations, all
synchronous, matcher `startup`.

| Event | Hook | Channel |
|---|---|---|
| SessionStart | `worktree-session-isolation.py session-start` | stderr |
| SessionStart | `jot-session-start.py` | `additionalContext` |
| SessionStart | `mahavishnu-pool-bootstrap.py` | `additionalContext` |
| SessionStart | `bodai-agent-mirror.py` | `additionalContext` |
| SessionStart | `bodai-activity-subscriber.py` | side-effect only |
| SessionEnd ×2 | `worktree-session-isolation.py`, `bodai-activity-subscriber.py` | stderr / side-effect |
| SessionEnd | `agent-merge-on-end.py` | plain stdout |
| PostToolUse ×2 | `bodai-activity-post-tool-use.py`, `jot-post-tool-use.py` | plain stdout / `additionalContext` |
| UserPromptSubmit | `jot-capture.py` | raw stdout JSON (not a hook envelope) |

**User-global `~/.claude/settings.json`** — 18 registrations. SessionStart:
`cc-status` (side-effect only) and `kit-onboard-inject.sh`
(`additionalContext`, no matcher).

**User-global `~/.claude/settings.local.json`** — 5 Session-Buddy lifecycle
hooks at `~/.claude/scripts/sb_*.py`, all side-effect only, all silently
failing (Section 6.2).

**Session-Buddy repo** — one `SessionEnd` hook. The plugin at
`plugins/session-buddy/` declares four slash commands and **no
`hooks/hooks.json`**; `hooks/PreCompact.md` is prose describing a hook that
was never wired.

**Akosha / crackerjack** — one `SessionEnd` hook each, byte-identical between
the two repos. **Oneiric / mcp-common** — no hooks.

**No hook anywhere in the ecosystem emits `systemMessage`.** The channel is
greenfield.

### 6.2 The Session-Buddy integration is entirely non-functional

The five hooks in `~/.claude/settings.local.json` call **unprefixed** MCP tool
names. Verified live against session-buddy v0.39.0:

```
start                    -> isError=True  Unknown tool: 'start'
checkpoint               -> isError=True  Unknown tool: 'checkpoint'
end                      -> isError=True  Unknown tool: 'end'
pre_compact_sync         -> isError=True  Unknown tool: 'pre_compact_sync'
_code_ingest_file_impl   -> isError=True  Unknown tool: '_code_ingest_file_impl'
store_reflection         -> isError=True  Unknown tool: 'store_reflection'
```

**Six** names, not five — `sb_post_tool.py` makes two calls. The real names
are `session_buddy_start`, `session_buddy_checkpoint`, `session_buddy_end`,
`session_buddy_pre_compact_sync`, `session_buddy_store_reflection` and
`session_buddy__code_ingest_file_impl` (double underscore).

The hooks discard the response and exit 0, so **every one is a silent no-op**.
No session is registered, no checkpoint taken, no reflection stored.

`session_buddy_enable_hook` and `session_buddy_disable_hook` are literal
stubs touching no files, while their help text describes a working feature.

### 6.3 The Session-Buddy memory-health tools are broken

`session_buddy_get_reflection_health` and `session_buddy_get_error_hotspots`
both fail live with `'Service not registered: session_buddy.core.memory_health.MemoryHealthAnalyzer'`.

```python
# session_buddy/core/memory_health.py:530
def get_memory_health_analyzer() -> MemoryHealthAnalyzer:
    analyzer = depends.get_sync(MemoryHealthAnalyzer)   # RAISES KeyError when unregistered
    if analyzer is None:                                 # DEAD CODE: never returns None
        analyzer = MemoryHealthAnalyzer()
    return analyzer
```

`depends.get_sync` **raises**; it never returns `None`, so the fallback is
unreachable. The class is fully implemented (21 KB module) — only the
registration is missing. `tests/unit/test_memory_health.py:312` monkeypatches
the container, so the unit test exercises a path production never takes; that
is why it survived.

### 6.4 `mahavishnu_ecosystem_status` can never report service health

Live output:

```json
{"status":"unknown","services":{},"adapters":{},"capabilities":{},
 "recommendations":[{"severity":"degraded","message":"No adapters registered."}]}
```

Three stacked causes:

1. **Four of five call sites never pass `service_configs`**
   (`mcp/tools/ecosystem_tools.py` ×3, `ecosystem_cli.py:379`). The
   constructor default is `{}`, so `services` is always empty.
2. **The one site that tries — `mahavishnu/tui/app.py:80` — raises.**
   It reads `settings.session_buddy_url`, but those fields live on
   `PoolConfig` (`settings.pools.session_buddy_url`). Live check:
   `session_buddy_url -> <<MISSING>>`. The access sits outside the
   try/except, so it is an uncaught `AttributeError`. The
   `# ty: ignore[missing-attribute]` comments were the type checker
   reporting the truth.
3. **The URL would still be wrong.** The defaults are MCP URLs
   (`http://localhost:8678/mcp`) and the service appends `/health`, giving
   `http://localhost:8678/mcp/health` — a 404.

No `services:` block exists in `settings/mahavishnu.yaml`,
`settings/local.yaml` or `settings/ecosystem.yaml`.

### 6.5 Mahavishnu pool data

`mahavishnu_pool_bootstrap` already reads `health_check()` and spawns a
default pool when `pools_active == 0`; it never raises. It does not return the
pool list. `mahavishnu_pool_health` returns it in full:

```json
{"status":"healthy","pools_active":2,"pools":[
  {"name":"merge-review","status":"running","workers":0,"min_workers":1,"max_workers":10,"worker_type":"terminal-claude"},
  {"name":"test-pool","status":"running","workers":1,"min_workers":1,"max_workers":10,"worker_type":"shepherd"}]}
```

The bootstrap snapshots health **before** spawning, so on the spawn path the
new pool is not in the returned list.

### 6.6 Health surfaces and latency

| Component | Endpoint | Observed |
|---|---|---|
| mahavishnu | `http://localhost:8680/health` | healthy, 0.39.0 |
| session-buddy | `http://localhost:8678/health` | healthy, 0.39.0, 2/2 feeds |
| akosha | `http://localhost:8682/health` | `warming_up`, 0.27.0 |
| crackerjack | `http://localhost:8676/health` | healthy, 0.95.0 |
| oneiric | `http://localhost:8681/health` | `warming_up`, **no `version`, no `service`** |

Measured: `GET /health` 58 ms; full MCP handshake plus `tools/call` 37 ms.
Oneiric's latency is bimodal — one probe exceeded 3 s, the next took 0.54 s.

`get_liveness` is **not** an identity source: it answers with mcp-common's
generic `{"service":"mcp-server","version":"0.0.0"}` envelope. The `/health`
document is the truth.

`session_buddy_start` did not return within 8 s. **The banner must not depend
on it**, and session registration should not sit on the critical path.

## 7. The design

### 7.1 Two banners, two homes

The scope decision splits the problem in two, and each part gets the shape
that suits it.

**A. Session-Buddy — user-global, always, standalone.**

Registered once in `~/.claude/settings.local.json` (where the other five
Session-Buddy hooks already live). It runs in **every repository**, because
capturing sessions everywhere is the point, and it must work when Mahavishnu
is down — so it probes Session-Buddy's `/health` directly and never touches
Mahavishnu.

The canonical script lives in the Session-Buddy repo at
`plugins/session-buddy/scripts/session_start_status.py` (already written and
exercised against the live server for the up, down, MCP-down and empty-stdin
paths; stdlib-only, runs on system Python 3.9). The user-global registration
points at it by absolute path.

It replaces `~/.claude/scripts/sb_session_start.py`, whose banner role was
never implemented and whose tool call was wrong.

**B. The fleet — Mahavishnu, project-scoped, from the ecosystem-status
capability.**

Registered in `mahavishnu/.claude/settings.json`. It calls
`mahavishnu_ecosystem_status` and prints the whole fleet plus pool detail.

This requires fixing Section 6.4 first, which is the point: the fleet view
comes from Mahavishnu's own capability rather than a parallel script. The
fix has three parts:

1. Give `EcosystemStatusService` a real `service_configs` source. Add a
   `services:` block to `settings/mahavishnu.yaml` holding **base URLs** (not
   MCP URLs), and pass it from every call site. Fix `tui/app.py` to read
   `settings.pools.session_buddy_url` — or, better, stop deriving service
   URLs from pool config and use the new `services:` block for both.
2. Add a dedicated `mahavishnu_pool_detail` section (or extend `services`)
   so the pool list with worker counts reaches the report.
3. The banner script calls the tool over the MCP wire and formats the result.

**Registration placement summary**

| Hook | Registration | Fires when |
|---|---|---|
| Session-Buddy banner | `~/.claude/settings.local.json` | every repo, every session |
| Fleet banner | `mahavishnu/.claude/settings.json` | mahavishnu sessions |

No suppression logic is needed, and no component other than Session-Buddy
needs to ship a banner script.

### 7.2 Banner format

```
○○○ <Component> (<gateway>): <state>, <detail>
```

States: `alive`, `warming up`, `DEGRADED`, `partially up`, `UNREACHABLE`.

```
○○○ Session-Buddy (wedgwoodwebworks): alive, v0.39.0, 2/2 feeds healthy, uptime 4d 13h
○○○ Mahavishnu (wedgwoodwebworks): alive, v0.39.0, 2 pools active, merge-review 0/10 workers, test-pool 1/10 workers
```

### 7.3 The registry and its drift test

`bodai/config/ecosystem.yaml` gains a `hooks:` block per component, alongside
the `name` / `role` / `port` / `repo` / `status` fields it already carries.
`bodai/tests/test_hook_surface_sync.py` is the enforcement — a sibling of the
existing `bodai/tests/test_portmap_sync.py`.

Two properties the drift test must have, both learned the hard way:

- **It must scan both trees.** `~/.claude/settings.json` is tracked in a
  **separate git repository rooted at `~/.claude`**, which is *not* under
  `~/Projects`. A portmap-style test that only walks sibling repos would
  never see the actual registration and could pass while nothing is wired.
  The test scans `~/Projects/*` for repo-side hooks **and** `~/.claude` for
  user-side registrations.
- **The invariant is two-way.** One-way ("every registry entry exists") is
  nearly a no-op and cannot catch a hook that was added and never
  registered. Two-way is required, which means the registry records **all**
  fleet hooks, not only banner hooks. That in turn means the registry also
  has to cover the `sb_*` hooks and the Kit Personal hooks — which Section 3
  excluded. Resolution: the registry records the **fleet's own** hooks
  (repo-side plus the Session-Buddy user-side set), and the Kit Personal
  hooks are recorded as an explicitly excluded group so the test can assert
  they stay excluded rather than silently ignoring them.

### 7.4 The Session-Buddy hook-name fix

Six renames in `~/.claude/scripts/sb_*.py`. Each must be verified against a
live `tools/list`, and each hook must stop discarding its MCP response: a
hook that exits 0 while ignoring an error is the mechanism that hid this for
long enough to survive.

### 7.5 Bounding the work

- Probe budget: 1.5 s per endpoint; probes run concurrently under one shared
  deadline. The Session-Buddy probe is two sequential MCP round trips plus a
  health call, so the worst case is 4.5 s as written — it must be concurrent
  with a shared budget, not sequential.
- One JSON object on stdout; diagnostics to stderr.
- Exit 0 on every path.
- The banner hook calls no state-mutating MCP tool.

## 8. Requirements

`REQ-FLEETHOOK-001` … `-007`, declared in the plan frontmatter.

1. Every fleet component's health appears in a user-visible `systemMessage`
   banner at session start.
2. The Mahavishnu banner names active pools and their worker counts, and a
   default pool is spawned when none are running.
3. `mahavishnu_ecosystem_status` reports real per-service health.
4. `bodai/config/ecosystem.yaml` carries a hooks registry; a drift test in
   bodai fails when the registry and the live trees disagree.
5. The Session-Buddy lifecycle hooks call correctly-named MCP tools and stop
   discarding their errors.
6. The Session-Buddy memory-health tools resolve their service and work.
7. No banner hook can block session startup.

## 9. Defects catalogued, out of scope

1. `mahavishnu pool list` / `pool health` crash — `asyncio.run()` inside a
   running event loop (`mahavishnu/_main_cli.py:2436`, `:2681`).
2. `session_buddy_enable_hook` / `disable_hook` are stubs whose help text
   describes a working feature. **Les's decision: review for removal**
   (Session-Buddy is 0.39.0, pre-1.0, and the fleet carries a no-back-compat
   pre-1.0 policy).
3. `jot-capture.py` writes a raw JSON blob to stdout, which is not a hook
   output envelope, so it reaches the model as plain text.
4. `mahavishnu/.claude/hooks/bifrost-anthropic-probe-guard.py` is an
   unregistered orphan, byte-identical to the copy that *is* registered
   user-globally.
5. `session_buddy_get_knowledge_graph_stats` exceeded an 8 s timeout — a
   performance characteristic, and a constraint on probe selection.
6. `session_buddy.get_reflection_health` and `get_error_hotspots` — **in
   scope** (Section 7, requirement 6).
7. `mahavishnu_ecosystem_status` reporting no services — **in scope**
   (Section 7.1B, requirement 3).

## 10. What is left for the builder

- The `services:` block shape in `settings/mahavishnu.yaml`, and the wiring
  at all five `EcosystemStatusService` call sites.
- The pool-detail section, and whether the banner reads it from the same
  report or from a separate `pool_health` call.
- The exact wording of the Session-Buddy banner states.
- The plan, in `docs/plans/`, with an Integration Contract per phase.
