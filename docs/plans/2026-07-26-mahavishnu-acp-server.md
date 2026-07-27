---
status: active
role: implementation
date: 2026-07-26
last_reviewed: 2026-07-27
superseded_by: null
topic: acp-server
---

# Mahavishnu ACP Server — Build Plan

**Date:** 2026-07-26
**Last reviewed:** 2026-07-27 (post multi-lens review; all top-5 actions and structural fixes applied; promoted draft → active)
**Status:** `active`, `implementation`
**Owner:** Mahavishnu core
**Scope:** New `mahavishnu/acp/` subpackage exposing Mahavishnu as an **ACP server** (stdio JSON-RPC 2.0), alongside the existing A2A HTTP+SSE server. Unblocks Toad/ACP client integration.
**Purpose:** Resolve the design in `docs/superpowers/specs/2026-07-15-mahavishnu-acp-server-design.md` into phased, mergeable, verifiable work. Each phase is independently demoable and ships behind a rollback signal.
**Spec sibling:** `docs/superpowers/specs/2026-07-15-mahavishnu-acp-server-design.md` (read first; this plan is the implementation contract, not a redesign).
**Companion tracker:** `docs/feature-tracking/tui.md` (the TUI/Toad decision is gated on this plan shipping).

## Review history

- **2026-07-27 — Multi-lens adversarial review** (Architecture, Integration Contract, Test Strategy, Security, Spec Conformance, License/Compliance, + synthesis). **Verdict: SHIP-WITH-FIXES.** All six lenses returned PASS WITH NOTES. One critical issue (Phase 6 / Phase 4 typo in §1), ~28 major, ~30 minor, ~20 nits. All top-5 actions and the cross-cutting-theme structural fixes have been applied in this revision. Full deduplicated issue list in the workflow journal (`/private/tmp/claude-501/-Users-les-Projects-mahavishnu/03ad3673-6b33-4c9a-8866-48fbf76281b1/tasks/werg7eois.output`). Ready to flip from `draft` to `active` when the operator signs off.

## 1. Outcome

A `mahavishnu acp serve` CLI subcommand that exposes Mahavishnu's
`execute_fn({"prompt": ...})` entry point over Agent Client Protocol (ACP)
stdio JSON-RPC 2.0, so any ACP client (Toad, Zed, JetBrains, future ACP
tooling) can drive Mahavishnu directly without the Claude Code layer between.

**Done =** the integration contract on Phase 4 succeeds: an external
`echo '{"jsonrpc":"2.0","id":1,"method":"initialize",...}' | uv run
mahavishnu acp serve` round-trips a valid response on stdout, and a
headless `session/prompt` call produces a `session/update` notification
stream that ends with `status: "completed"`. The gated integration test
in Phase 4 must pass.

**Done also =** the operator doc `docs/acp/USAGE.md` exists with a
Toad config example that an operator can copy-paste and have work.

## 2. Goals

1. Land `mahavishnu/acp/` with stdio JSON-RPC 2.0 dispatcher
   (`server.py`), EventBridge synthesizer (`events.py`), and Pydantic
   wire-format models (`protocol.py`)
2. Land the CLI surface `mahavishnu acp serve` and register it in
   `mahavishnu/_main_cli.py`
3. Land unit tests for protocol, dispatcher, and event synthesis
   (test layers 1–3 per the design spec), plus a parametrized
   `test_acp_spec_field_names` that pins the wire format against
   literal ACP-spec examples (future spec-drift CI gate)
4. Land a gated integration test that spawns `mahavishnu acp serve` as a
   subprocess, feeds JSON-RPC on stdin, asserts responses on stdout
   (test layer 4 — must include auth-failure and adversarial-input cases)
5. Land `docs/acp/USAGE.md` with a copy-pasteable Toad config example
   and a doc-staleness detector (`tests/unit/test_acp_docs.py`)
6. Add OTel spans and structured log lines for every JSON-RPC boundary
   so ACP sessions are first-class in the observability surface, and
   validate they actually flow (`Phase 2 Observability Validation` task)
7. Decide and document the open questions from the spec
   (`session/load`, `tool_call` visibility, threat model)
8. Add the Toad entry to `THIRD_PARTY_NOTICES.md` and reconcile the
   `LICENSE` / `pyproject.toml` license-declaration drift

## 3. Non-Goals

1. **A2A changes** — `mahavishnu/a2a/server.py` is canonical for
   inter-agent federation; do not modify. We are adding a second
   protocol, not replacing the first
2. **Remote ACP transport (Streamable HTTP)** — ACP's remote transport
   is a draft upstream. v1 is stdio only
3. **MCP-over-ACP** — the RFD is in flight. When it lands, follow up
   with a separate plan that flips `mcpCapabilities.acp: true` and
   tunnels the existing 174 MCP tools through ACP sessions
4. **Multi-tenant identity** — stdio precludes multi-client. One ACP
   client = one Mahavishnu process = one session at a time
5. **Session persistence for `session/load`** — deferred to v1.5
   (see Decision 1 below)
6. **Toad-side changes** — Toad is upstream; we don't fork it
7. **IDE-side changes** — Zed/JetBrains ACP support is upstream
8. **A2A-spec `agent-card.json` path fix** — trivial but out of scope
   for this plan; tracked separately
9. **TUI defect fixes** — the four defects in
   `docs/feature-tracking/tui.md` § "Wired (NOT YET — defects blocking)"
   are tracked separately. This plan flips the TUI tracker from
   `built` to `wired`; the four defects block the `wired → adopted`
   flip and are not prerequisites here
10. **Toad-integration smoke test (manual)** — this plan ships the
    server; the follow-up Toad integration is a separate plan
    (Decision Rule item 7)
11. **Additional ACP session methods deferred to v1.5**:
    `session/list`, `session/resume`, `session/set_mode`,
    `session/close`, `session/delete`, `logout`. v1 implements
    `initialize`, `authenticate`, `session/new`, `session/load`
    (returns -32003), `session/prompt`, `session/cancel`, and the
    outbound `session/update` notification. `logout` is intentionally
    not implemented in v1 (process exit is the logout)

## 4. Current Findings

- **The design is approved.** `docs/superpowers/specs/2026-07-15-mahavishnu-acp-server-design.md`
  status `active` in `docs/plans/PLAN_INDEX.md:338`; body status
  "approved (design phase complete, awaiting plan)" at line 13. This
  plan is the "plan" the spec was waiting on.
- **No ACP code exists today.** Four prior plan/specs defer Toad/ACP
  for the same structural reasons. The cleanest references are
  `docs/superpowers/plans/2026-06-19-track3-toad-tui.md` (draft),
  `docs/superpowers/specs/2026-06-19-external-integrations-design.md:324-380`,
  `docs/superpowers/specs/2026-07-15-constellation-tui-design.md:10-16,41-47`,
  and `docs/superpowers/plans/2026-07-15-constellation-tui.md:59-63`.
- **CrowWorker is not ACP.** `mahavishnu/workers/crow.py:17-25,38-128`
  uses a custom REST surface (`/acp/new_session`, `/acp/prompt`,
  `/acp/status/{id}`, `/acp/cancel/{id}`) that borrows the name "ACP"
  but is not the Zed/JetBrains JSON-RPC 2.0 protocol. No changes to
  CrowWorker in this plan. Its license posture is also untouched by
  the stdio boundary (separate code path, separate process).
- **Existing A2A server is the partial implementation reference.**
  `mahavishnu/a2a/server.py:33-56` (Bearer middleware — has bugs, see
  Phase 1.5), `:145-198` (route factory — safe to copy), `:160-198`
  (SSE event shapes), and the `execute_fn` construction pattern.
  **ACP does NOT reuse A2A's auth path verbatim**; see Phase 1.5
  refactor and the explicit "patterns to copy" / "patterns to forbid"
  list in Phase 2.
- **EventBridge subscriber exists at**
  `mahavishnu/core/events/bodai_subscriber.py` and is the canonical
  event source. `subscribe_to_bodai_events` is the entry point
  ACP's `events.py` consumes.
- **WebSocket stage broadcasting** at
  `mahavishnu/websocket/server.py:559` (`broadcast_workflow_stage_completed`)
  defines the event types the ACP synthesizer must map.
- **Worker dispatch path is now Apple-silicon microVMs and E2B
  sandboxes** (`mahavishnu/workers/apple_container.py` and
  `mahavishnu/workers/e2b_sandbox.py`; Docker/OrbStack removed 2026-07).
  These are the two concrete sites where the Phase 1 EventBridge
  extension must emit `tool_call_started` / `tool_call_completed` —
  not Docker code paths.
- **TUI/Toad decision is gated on this plan.** See
  `docs/feature-tracking/tui.md` § "Toad decision."

### Decisions on the spec's open questions

The spec defers four questions to the plan phase. Decisions:

- **Decision 1 — `session/load` for v1: return `-32003 Not implemented`.**
  Rationale: the A2A server is also stateless; introducing a
  session-persistence layer for ACP alone would create a
  one-off storage surface. A v1.5 plan can add a `session/load`
  implementation backed by `~/.mahavishnu/acp-sessions/<id>.jsonl`
  with the same shape A2A eventually adopts. For v1, `session/load`
  returns JSON-RPC `-32003` after the auth gate fires (i.e.,
  `session/load` requires auth, then returns -32003). **Error code
  convention:** Mahavishnu's custom JSON-RPC codes live in the
  project-defined range `-32000` to `-32099`:
  - `-32001` Auth required
  - `-32002` Auth invalid
  - `-32003` Session persistence not implemented (v1 only)
  - `-32004` Too many concurrent sessions (rate limit)
  Documented in `docs/acp/USAGE.md` so ACP clients (e.g., Toad) can
  pre-decode them.
- **Decision 2 — `tool_call` visibility for v1: extend EventBridge to
  emit `tool_call_started` and `tool_call_completed` envelopes, and
  map them in `events.py` to ACP `session/update` notifications of
  type `tool_call_update` with `status: "running" | "completed" | "failed"`.**
  Rationale: Toad's UI relies on `tool_call_update` notifications to
  show "running tool X" status. Without them, Toad shows text chunks
  only and loses fidelity. The EventBridge extension is small (two
  new event envelope types, two emission sites in the worker
  dispatch path). **Note:** Decision 2 is a meaningful scope
  expansion beyond the spec's framing — the spec lists it as an open
  question; the plan's answer is "yes, scope up so Toad is
  honest." Defensible but worth flagging.
- **Decision 3 — MCP-over-ACP: out of scope for v1.** Tracked
  separately; see Goal #3 in Non-Goals. **License note (from
  License/Compliance review):** if MCP-over-ACP ever ships, the
  v1.5+ plan must re-run the AGPL §13 analysis. The stdio-JSON-RPC
  boundary preserves the no-source-linking rule, but the analysis
  re-runs because the v1.5 plan would tunnel Mahavishnu's MCP tool
  implementations to an AGPL client.
- **Decision 4 — Remote ACP: out of scope for v1.** Tracked
  separately; see Goal #2 in Non-Goals.
- **Decision 5 — Threat model: stated explicitly.** ACP auth is
  **defense-in-depth**, not the primary trust boundary. The primary
  trust boundary is OS-level process co-residency: anyone who can
  spawn `mahavishnu acp serve` is already trusted with the local
  user's permissions. The Bearer token gates **audit logging**
  and **prevents accidental exposure to a misconfigured second
  process**. This framing is the basis for every auth decision in
  this plan. The bearer is loaded from
  `MAHAVISHNU_ACP_BEARER_TOKEN` env var (or
  `MAHAVISHNU_ACP_BEARER_TOKEN_FILE` with mode 0600; either-but-not-both)
  and is **popped from `os.environ` after read** (`os.environ.pop(...)`)
  so child processes (pool workers, OTel exporter, git subprocesses)
  do not inherit it.

## 5. Implementation Phases

### Phase 1: Wire-format models + EventBridge → ACP mapping

**Goal:** Land the pure-Python core of the ACP surface — Pydantic
wire-format models and the EventBridge-to-ACP-shape synthesizer —
with no I/O dependencies. Independently testable.

**Tasks:**

1. Create `mahavishnu/acp/__init__.py` (package marker; re-exports
   `serve`, `ACPError`, `ACPSession` from sibling modules).
2. Create `mahavishnu/acp/protocol.py` with Pydantic models for every
   ACP wire message type we send or receive. **Field shapes per the
   ACP spec, not A2A's conventions:**
   - `InitializeRequest` / `InitializeResponse` — `protocolVersion`,
     `clientInfo` ({`name`, `version`}), `agentCapabilities`
     ({`loadSession: false` in v1, `mcpCapabilities: {http: false,
     sse: false}`})
   - `AuthenticateRequest` — `{methodId: "bearer", token: "..."}`
   - `SessionNewRequest` / `SessionNewResponse` — `SessionNewResponse`
     carries `sessionId` (RFC 4122 v4; v7 is a v1.5 follow-up)
   - `SessionPromptRequest` — `sessionId`, `content` (discriminated
     union: `{type: "text", text: "..."}` in v1)
   - `SessionUpdate` notification — discriminator field is
     `sessionUpdate` (NOT `type`); `sessionId` is mandatory on every
     notification; content subtypes: `agent_message_chunk`,
     `tool_call_update` ({`toolCallId`, `status: "running" | "completed"
     | "failed"`, `title?`, `content?`}), `status` ({`status:
     "working" | "completed" | "failed"`})
   - `SessionCancelRequest` — `sessionId`
   - JSON-RPC 2.0 `Request` / `Response` / `ErrorResponse` envelopes
     (use `extra="forbid"` on every inbound `*Request` model to
     prevent field smuggling)
   - All string fields carry `Field(..., max_length=...)` caps:
     `prompt` 100 KB, `protocolVersion` 32 bytes, `sessionId` 64
     bytes, `clientInfo.name` 64 bytes, `clientInfo.version` 32
     bytes. Oversized payloads are rejected at the Pydantic layer
     before they reach `execute_fn`
3. Add `tests/unit/acp/test_protocol.py::test_acp_spec_field_names` —
   a parametrized test that asserts each wire shape against a
   literal ACP-spec example. This is the CI gate for future spec
   drift. Concrete assertions include:
   - `InitializeResponse.agentCapabilities.mcpCapabilities` is a
     Pydantic field (not a renamed `mcp`)
   - `SessionUpdate.sessionUpdate` is the discriminator key (not
     `type`)
   - `SessionUpdate` model requires `sessionId` (rejects without it)
   - `agentCapabilities.loadSession` is `False` (matches the v1
     decision to return `-32003` for `session/load`)
4. Create `mahavishnu/acp/events.py` with `EventSynthesizer` class
   and a `synthesize(envelope) -> SessionUpdate` function. Map per
   the spec table at design §Components lines 150-160:
   - `workflow_started → status working`
   - `stage_completed → agent_message_chunk` ({`type: "text", text:
     "stage <name> complete"`})
   - `worker.completed → tool_call_update` ({`status: "completed"`,
     `toolCallId` from envelope's `task_id`})
   - `tool_call_started → tool_call_update` ({`status: "running"`})
   - `tool_call_completed → tool_call_update` ({`status: "completed"`
     or `"failed"`})
   - `completed → status completed`
   - `failed → status failed + error chunk`
   - `crackerjack.gate_raised → agent_message_chunk`
   Unknown types pass through as `agent_message_chunk` with the
   serialized envelope as text (no silent drops).
5. Extend `mahavishnu/core/events/bodai_subscriber.py` to emit
   `tool_call_started` and `tool_call_completed` envelopes. **Two
   concrete emission sites** (NOT a hand-waved "search for the
   existing `worker.completed` envelope"):
   - `mahavishnu/workers/apple_container.py` — emit start at
     sandbox launch, emit complete at sandbox destroy
   - `mahavishnu/workers/e2b_sandbox.py` — same pattern
   - The `mahavishnu/workers/manager.py` worker-lifecycle path also
     emits `worker.completed` (existing) and gains a `tool_call_started`
     sibling adjacent to it
   The implementer must `rg -n "worker.completed" mahavishnu/workers/`
   before merging Phase 1 to confirm the emission sites are
   exhausted.
6. Tests:
   - `tests/unit/acp/test_protocol.py` — Pydantic round-trip for
     each model; the `test_acp_spec_field_names` parametrized test
     from Task 3; JSON serialization matches ACP snake_case fields;
     invalid input rejected with clear errors; `extra="forbid"`
     rejects extra fields
   - `tests/unit/acp/test_events.py` — mapping table exercised
     row-by-row; unknown-type pass-through; drop-on-full-queue path
     (simulator fills the outbound queue, asserts next envelope is
     dropped with `level=warning`); `tool_call_started` →
     `tool_call_update` (status: running); `tool_call_completed` →
     `tool_call_update` (status: completed/failed)
   - `tests/unit/test_bodai_subscriber.py` — positive test that
     `apple_container.py` and `e2b_sandbox.py` both emit the two
     new envelope types; baseline-green assertion that no other
     consumer crashes
7. **Property-based tests** (project has `hypothesis` in dev; 8+
   Hypothesis files exist). New `tests/property/acp/test_acp_properties.py`
   with strategies for:
   - The Pydantic round-trip (random valid `SessionUpdate` →
     serialize → deserialize → equal)
   - The EventBridge → ACP synthesizer (random envelope types
     including adversarial ones, no crash, no silent drop on valid
     envelopes)

**Exit criteria:**
- `pytest tests/unit/acp/ tests/property/acp/ tests/unit/test_bodai_subscriber.py -v`
  is green
- Coverage on the new modules (`mahavishnu/acp/protocol.py`,
  `mahavishnu/acp/events.py`) is **≥95%** (raised from the 90% in
  the prior revision; matches the bar set for prior MCP server
  deliveries)
- The pytest marker for ACP tests is `acp` (per
  `CLAUDE.md` "use the project pytest markers"), NOT `acp-stdio`

#### Integration Contract — Phase 1

- **Triggered from:** `pytest tests/unit/acp/ tests/property/acp/ -v`
  (developer-driven). Also: future `mahavishnu acp serve` invocations
  depend on these models for dispatch.
- **Returns to / updates:** New `mahavishnu.acp.protocol` and
  `mahavishnu.acp.events` modules. Pydantic models surface as
  re-exports from `mahavishnu.acp`. EventBridge gains two new
  envelope types. Worker dispatch path gains emission sites in
  `apple_container.py` and `e2b_sandbox.py`.
- **Demonstrable by:** (single line, per the wire-up contract)
  `python -c "from mahavishnu.acp import SessionUpdate, EventSynthesizer; u=EventSynthesizer().synthesize({'type':'tool_call_started','name':'X','task_id':'t1','session_id':'s1'}); d=u.model_dump(); assert d['sessionUpdate']=='tool_call_update' and d['sessionId']=='s1' and d['status']=='running'"`
  This is a real end-to-end wiring check (not a structural import):
  it exercises the synthesizer, the new envelope, and the
  spec-correct `sessionUpdate` discriminator + `sessionId` field.
- **Rollback signal:** If the EventBridge envelope addition causes
  any `subscribe_to_bodai_events` consumer to crash (the two new
  envelope types land in their queues), the
  `pytest tests/unit/test_bodai_subscriber.py -v` suite fails with
  a `KeyError` / `AttributeError` on the new `type` field. Revert
  the EventBridge change first; the Pydantic and event-synthesizer
  changes are independent and can stay.
- **Observability added:** Structured log line per EventBridge
  envelope type, in `events.py::synthesize()`:
  `acp.event_synthesized type=<event_type> shape=<update_kind>`.
  Counter for dropped envelopes (`acp.event_dropped total=N`).
  Coverage: `mahavishnu/acp/events.py` is the instrumented surface
  and Phase 2's Observability Validation subtask asserts the logs
  actually flow.

### Phase 1.5: `_build_execute_fn` extraction refactor (NEW)

**Goal:** Make the A2A → ACP code-sharing decision explicit and
executed *before* Phase 2, so Phase 2 has a clear source of truth
for the `execute_fn` factory. Without this, Phase 2's "extract
A2A's pattern" instruction silently inherits A2A's bugs (non-constant-time
bearer compare at `a2a/server.py:50`, missing `execute_fn` timeout).

**Tasks:**

1. Audit `mahavishnu/a2a/server.py:33-56` (Bearer middleware) and
   `:145-198` (route factory + `execute_fn` construction) and write
   the result into `docs/plans/2026-07-26-mahavishnu-acp-server.md`
   Decision 5 or a new appendix. Two lists:
   - **Patterns safe to copy** (no behavior change): the route
     factory at `:145-198`, the SSE event-shape emission at
     `:160-198`, the structured-log line format
   - **Patterns explicitly forbidden** (must NOT copy): the plain
     `!=` token compare at `:50` (replace with `secrets.compare_digest`),
     any path that doesn't enforce an `execute_fn` timeout
2. Extract `mahavishnu/core/execute_fn_factory.py` containing
   `build_execute_fn(settings) -> Callable[[dict[str, Any]],
   Awaitable[Any]]` — a single source of truth for "given a prompt
   string, run a Mahavishnu task." A2A and ACP both call it.
3. Modify `mahavishnu/a2a/server.py` to import the new factory.
   Zero behavior change for A2A: same call signature, same return
   shape. **The A2A Bearer-middleware bug is fixed in the same
   PR** (`secrets.compare_digest` instead of plain `!=`); this is
   the lowest-cost moment to do it because both A2A and ACP need
   it.
4. Tests:
   - `tests/unit/core/test_execute_fn_factory.py` — one test per
     public field, plus a "behavior unchanged for A2A" assertion
     that exercises the new factory through A2A's existing test
     surface and asserts no output diff
   - `tests/unit/a2a/test_server.py` — `test_auth_uses_constant_time_compare`
     locks the A2A fix in
   - `pytest tests/unit/a2a/ -v` — A2A regression suite, must stay
     green

**Exit criteria:**
- `pytest tests/unit/a2a/ tests/unit/core/test_execute_fn_factory.py -v`
  is green
- A2A's auth path is now `secrets.compare_digest` (no `!=`)
- Phase 2 can call `from mahavishnu.core.execute_fn_factory import
  build_execute_fn` without ambiguity about which A2A patterns
  to inherit

#### Integration Contract — Phase 1.5

- **Triggered from:** `pytest tests/unit/a2a/ tests/unit/core/test_execute_fn_factory.py -v`
  (developer-driven; the refactor is gated on A2A tests).
- **Returns to / updates:** New `mahavishnu/core/execute_fn_factory.py`.
  Modified `mahavishnu/a2a/server.py` (one import, one call site,
  one `secrets.compare_digest` swap — no public surface change).
- **Demonstrable by:**
  `diff <(uv run pytest tests/unit/a2a/ -q 2>&1) <(git stash && uv run pytest tests/unit/a2a/ -q 2>&1 && git stash pop)` shows no
  behavioral diff. (Pre-/post-refactor test output identical
  except for the A2A-auth-fix commit hash.)
- **Rollback signal:** If A2A test output differs (any failure or
  behavior change), revert Phase 1.5; Phase 2 falls back to
  inline-duplicating the A2A factory and documents the deferral
  in `docs/plans/2026-07-26-mahavishnu-acp-server.md` Decision 5.
- **Observability added:** A2A's existing structured log lines
  carry over unchanged. The new `execute_fn_factory` adds no new
  spans (Phase 2 owns ACP observability).

### Phase 2: JSON-RPC 2.0 dispatcher + CLI surface

**Goal:** Land the stdio JSON-RPC 2.0 dispatcher and the
`mahavishnu acp serve` CLI entry point. With this phase done, an
operator can invoke the server end-to-end against a real prompt.

**Tasks:**

1. Create `mahavishnu/acp/server.py` with:
   - `ACPError` (protocol-level error; serialized to JSON-RPC error
     response)
   - `ACPSession` dataclass (`session_id`, `task`,
     `cancellation_token`)
   - `serve(execute_fn)` async main loop: read newline-delimited
     JSON-RPC from `sys.stdin`, dispatch to handler, write
     responses/notifications to `sys.stdout`, log to `sys.stderr`
     with `sys.stderr.flush()` after every log line. `sys.stdout`
     is line-buffered at minimum; the test in Task 4 asserts this
     via `subprocess` and a `read1` check
   - **Stdin line cap**: a `_SafeLineReader(max_bytes=1_048_576)`
     (1 MB) wraps `sys.stdin`. Lines larger than 1 MB return
     `-32700 Parse error` *before* `json.loads` ever sees them
   - **JSON-RPC batch requests**: rejected with `-32600 Invalid
     Request` (per JSON-RPC 2.0 §6)
   - Handlers: `initialize`, `authenticate`, `session/new`,
     `session/load` (requires auth, then returns -32003 per
     Decision 1), `session/prompt`, `session/cancel`
   - **`authenticate` body shape**: `{methodId: "bearer", token: "..."}`
     (Pydantic model in `protocol.py`)
   - **Bearer auth gate (per Decision 5 threat model)**:
     - Bearer loaded from `MAHAVISHNU_ACP_BEARER_TOKEN` (env var)
       OR `MAHAVISHNU_ACP_BEARER_TOKEN_FILE` (file path; mode 0600
       required; mutually exclusive with the env var)
     - **Empty or unset bearer → fail-closed**: server refuses to
       start if neither is set
     - Comparison uses `secrets.compare_digest(provided.encode(),
       expected.encode())` (timing-safe; the A2A `:50` bug is
       already fixed in Phase 1.5; do NOT revert)
     - `os.environ.pop("MAHAVISHNU_ACP_BEARER_TOKEN", None)`
       immediately after the read
     - `session/prompt` without prior `authenticate` returns
       JSON-RPC `-32001 Auth required`; auth state is per-process
     - Wrong token returns `-32002 Auth invalid`
   - **`execute_fn` hardening**:
     - Wrap in `await asyncio.wait_for(task,
       timeout=settings.acp_session_timeout_seconds)` (default
       600 s; configurable via `settings/mahavishnu.yaml` under
       `acp.session_timeout_seconds`)
     - On timeout, emit `session/update` `{type: "status", status:
       "failed", message: "session timeout"}` and return
       `stopReason: "timeout"`
     - For `session/cancel`: hard `task.cancel()` + `await
       asyncio.wait_for(task, timeout=5.0)`; if the worker
       refuses to die, log `level=error
       event=acp.session.cancel_refused` and emit
       `status: "failed"` with `message: "cancel refused by worker"`
   - **Rate limit**: `MAX_CONCURRENT_SESSIONS` (default 16,
       configurable) with `-32004 Too many concurrent sessions`
       rejection on `session/new` overflow
   - **Logger redaction filter**: a `logging.Filter` subclass
       replaces any occurrence of the bearer value with
       `<redacted-bearer>` on every record before it reaches the
       handler. The Phase 4 regression test asserts no log line
       contains the original bearer value
2. Create `mahavishnu/cli/acp_cli.py` with the `serve_cmd` Typer
   command. Calls `from mahavishnu.core.execute_fn_factory import
   build_execute_fn` (the Phase 1.5 factory).
3. Modify `mahavishnu/_main_cli.py` to register `acp_cli` as
   `app.add_typer(acp_app, name="acp")` next to the existing
   subcommand registrations.
4. Tests (`tests/unit/acp/test_server.py`):
   - Dispatcher round-trips a synthetic JSON-RPC request to a stub
     handler and emits the right response shape
   - Unknown method returns `-32601`
   - Invalid JSON returns `-32700`
   - Stdin line > 1 MB returns `-32700` without OOM
   - JSON-RPC batch request returns `-32600`
   - `secrets.compare_digest` is called (assert via mock or
     `inspect.getsource`); NOT `==` or `!=` on the token
   - Bearer auth gate: `session/prompt` without prior
     `authenticate` returns `-32001`; auth state is per-process;
     wrong token returns `-32002`; empty/unset bearer env causes
     `serve()` to refuse to start (no `serve` callable returns
     without raising)
   - `session/load` requires auth, then returns `-32003` (not the
     order swapped)
   - Cancel idempotency: calling `session/cancel` twice or after
     task completion both ack
   - Cancel hard-kills a worker that ignores `CancelledError`
     (use a stub `execute_fn` that awaits `asyncio.sleep(999)` on
     every call; assert `wait_for(5.0)` fires and the session goes
     to `status: "failed"`)
   - `execute_fn` timeout: stub `execute_fn` that awaits
     `asyncio.sleep(999)`; assert `wait_for(600.0)` fires (use a
     patched `settings.acp_session_timeout_seconds=0.1` in the
     test)
   - `MAX_CONCURRENT_SESSIONS` rejection: spin up 16 sessions,
     assert the 17th `session/new` returns `-32004`
   - `os.environ["MAHAVISHNU_ACP_BEARER_TOKEN"]` is popped after
     read (assert the env var is gone in a child subprocess)
   - Logger redaction: capture logs at all levels, assert no
     record contains the original bearer value
   - Stderr is flushed after every log line
5. **Observability Validation subtask (NEW; gates the
   observability claim rather than just asserting it)**:
   - `tests/unit/acp/test_observability_validation.py` (or extend
     `test_server.py`) — headless smoke that runs `serve()` with
     a stub `execute_fn` and an in-memory log capture
   - Asserts the OTel span `mahavishnu.acp.session` is emitted
     with attributes `session.id`, `session.stop_reason`,
     `session.duration_ms`, `session.status`
   - Asserts the four structured log lines `acp.request_received`,
     `acp.response_sent`, `acp.session_started`,
     `acp.session_completed` (or `acp.session_cancelled`) appear
   - This test is the *only* thing that makes the "first-class
     observability" claim in Phase 2's contract load-bearing
   - If the OTel exporter is not configured for the test
     environment, the test must explicitly skip with a clear
     reason (not silently pass)

**Exit criteria:** `pytest tests/unit/acp/test_server.py -v` is
green. Manual smoke:
`echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"0.0.1","clientInfo":{"name":"smoke","version":"0.0.1"}}}' | uv run mahavishnu acp serve`
prints a valid `InitializeResponse` on stdout and exits 0.

#### Integration Contract — Phase 2

- **Triggered from:** Operator runs
  `mahavishnu acp serve` directly (manual smoke), or an ACP
  client (Toad, future tooling) spawns it as a subprocess and
  writes JSON-RPC lines to its stdin.
- **Returns to / updates:** Stdout (JSON-RPC responses and
  `session/update` notifications). Structured log lines to
  `~/.mahavishnu/logs/mcp.log` (the same sink MCP uses) via the
  Phase 2 logger redaction filter. No persistent state until
  v1.5.
- **Demonstrable by:** (single line)
  `echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"0.0.1","clientInfo":{"name":"smoke","version":"0.0.1"}}}' | MAHAVISHNU_ACP_BEARER_TOKEN=$(python -c 'import secrets;print(secrets.token_urlsafe(32))') uv run mahavishnu acp serve`
  exits 0; stdout contains a JSON-RPC response with
  `result.protocolVersion` echoing the requested version,
  `result.agentCapabilities.loadSession: false`, and
  `result.agentCapabilities.mcpCapabilities.http: false`.
- **Rollback signal:** If the server crashes 3x in 60s, log
  `level=error event=acp.server.crash_loop`. Operator disables
  the CLI command by removing the registered sub-app from
  `_main_cli.py` (one-line revert). For the EventBridge
  emission-site changes from Phase 1, the rollback is partial:
  revert `mahavishnu/workers/apple_container.py` and
  `mahavishnu/workers/e2b_sandbox.py` separately; do NOT
  revert `bodai_subscriber.py` (it's shared with A2A).
- **Observability added:**
  - OTel span `mahavishnu.acp.session` with attributes
    `session.id`, `session.stop_reason`, `session.duration_ms`,
    `session.status`
  - Structured log lines per JSON-RPC boundary: `acp.request_received`,
    `acp.response_sent`, `acp.session_started`,
    `acp.session_completed`, `acp.session_cancelled`,
    `acp.event_dropped total=N`, `acp.session.cancel_refused`
  - Process-start log line `acp.cli.serve_started pid=<n>`
  - **All of the above are validated by the Phase 2 Observability
    Validation subtask (Task 5)**, not just asserted in
    prose

### Phase 3: Operator doc + Toad config example

**Goal:** Land `docs/acp/USAGE.md` with a copy-pasteable Toad
config so an operator can wire Toad → Mahavishnu without reading
the protocol spec, plus the index/license/attribution
side-effects.

**Tasks (split into 3a and 3b; 3a can ship in parallel with Phase 2,
3b after Phase 4):**

**Phase 3a — operator doc:**

1. Create `docs/acp/USAGE.md` covering:
   - What ACP is (one paragraph, link to agentclientprotocol.com)
   - `mahavishnu acp serve` invocation
   - `MAHAVISHNU_ACP_BEARER_TOKEN` setup (32+ byte minimum; the
     `python -c 'import secrets; print(secrets.token_urlsafe(32))'`
     idiom)
   - `MAHAVISHNU_ACP_BEARER_TOKEN_FILE` alternative
   - Toad config example (verify against Toad's current docs;
     record the version tested against in the doc)
   - Known limitations: `session/load` returns -32003 in v1;
     `tool_call` updates require EventBridge envelope consumers to
     forward the new types; `logout` is not implemented
     (process exit is the logout)
   - Custom JSON-RPC error codes: `-32001` (auth required),
     `-32002` (auth invalid), `-32003` (not implemented),
     `-32004` (too many concurrent sessions)
   - **Security section** (NEW): threat model recap
     (defense-in-depth, not primary trust), the bearer is
     audit-only, the bearer may be logged by the ACP client (e.g.,
     Toad) — operators should check their client's docs for
     where the token is written
   - **License section** (NEW): Mahavishnu is MIT/BSD-3-Clause
     (the project's canonical license — to be reconciled with
     `pyproject.toml:16` in Phase 3b); connecting an AGPL client
     like Toad does not impose AGPL on Mahavishnu
   - Troubleshooting: stdin/stdout buffering pitfalls, JSON-RPC
     newline framing, `MAX_RPC_LINE_BYTES` rejection
2. Add `tests/unit/test_acp_docs.py` (the doc-staleness
   detector):
   - `test_toad_config_block_parses` — extracts the YAML/JSON
     block from `docs/acp/USAGE.md` and asserts it parses
   - `test_cli_examples_match_help` — runs
     `uv run mahavishnu acp serve --help` and asserts each
     command example in the doc appears in the help output
   - These are the **Observability added** for the doc phase:
     the auto-check that catches doc rot, not "N/A"

**Phase 3b — attribution and license housekeeping (after Phase 4
or in parallel with Phase 2):**

3. Add a Toad row to `THIRD_PARTY_NOTICES.md` matching the
   OpenObserve/Maxun row format: Toad, AGPL-3.0, Mode = "Run as
   CLI subprocess", URL = `https://github.com/batrachianai/toad`,
   AGPL posture = "Unmodified external subprocess invoked via
   stdio JSON-RPC 2.0; no source linking; no source distribution;
   commercial-license path available for redistribution."
4. Add a Decision Rule item: "Reconcile `pyproject.toml:16`
   (declares `license = {text = "MIT"}`) with the canonical
   `LICENSE` file (BSD-3-Clause). One-line fix; non-blocking for
   this plan but ships before the first ACP-aware release."
5. Update `docs/README.md` (or the current docs index) with a
   one-line "Integrations → ACP" entry pointing at
   `docs/acp/USAGE.md`.
6. Update `docs/plans/PLAN_INDEX.md` to flip this plan from
   `draft` to `active` once Phase 3b ships.

**Exit criteria (3a):** An operator with a fresh Mahavishnu
install and Toad can follow the doc and get a streamed prompt
response within 10 minutes. Verified by a fresh-clone smoke test
(manual, not in pytest). `pytest tests/unit/test_acp_docs.py -v`
is green.

**Exit criteria (3b):** `THIRD_PARTY_NOTICES.md` contains the
Toad row; `docs/README.md` lists the new doc; `PLAN_INDEX.md`
flips this plan to `active`.

#### Integration Contract — Phase 3

- **Triggered from:** Operator reads `docs/acp/USAGE.md` after
  Phase 2 deploys. The `tests/unit/test_acp_docs.py` suite runs
  in CI on every commit.
- **Returns to / updates:** `docs/acp/USAGE.md` (new file);
  `docs/README.md` index (one-line addition);
  `THIRD_PARTY_NOTICES.md` (one row);
  `tests/unit/test_acp_docs.py` (new test file);
  `docs/plans/PLAN_INDEX.md` (one-line status flip).
- **Demonstrable by:** `pytest tests/unit/test_acp_docs.py -v`
  is green. The manual smoke (Phase 3a §Exit criteria) succeeds.
- **Rollback signal:** If the doc-staleness test fails on
  `main`, the doc is regressed. Revert the failing PR; the
  doc and tests are independent of Phase 2/4 code.
- **Observability added:** `pytest tests/unit/test_acp_docs.py
  -v` (the auto-check that catches doc rot) is the load-bearing
  observability for this phase. Pair with a CI badge
  `acp.doc_staleness_check passed=true/false` queryable from
  Akosha so the regression gate is programmatic, not
  eyeballed.

### Phase 4: Gated end-to-end integration test

**Goal:** Land `tests/integration/acp/test_acp_stdio_e2e.py` as
the regression gate for "did the server break between releases."
Skipped in fast CI; run on release candidates and on the
subnightly.

**Tasks:**

1. Create `tests/integration/acp/test_acp_stdio_e2e.py` gated by
   `MAHAVISHNU_ACP_INTEGRATION=1`. **Use the `acp` marker** (not
   `acp-stdio`; project convention per `CLAUDE.md`). Skipped in
   fast CI; **print a one-line skip reason** so CI artifacts are
   self-explanatory.
2. **Test cases (six, not three — Phase 4 is the *only*
   end-to-end coverage, so it must cover the realistic failure
   modes):**
   - **Smoke round-trip**: spawn `uv run mahavishnu acp serve` as
     a subprocess; feed `initialize`, `authenticate`,
     `session/new`, `session/prompt` lines on stdin; assert
     matching responses on stdout
   - **Cancel mid-prompt**: send `session/cancel` while a
     `session/prompt` is in flight; assert task cancellation
     completes within 1s and a `status: "failed"` `session/update`
     arrives
   - **Clean exit on EOF**: close stdin; assert subprocess exits
     0 within 1s and an `acp.cli.serve_exited` structured log
     line is emitted (graceful exit, not silent)
   - **Auth-failure e2e** (NEW): `session/prompt` without prior
     `authenticate` returns `-32001` within 100ms, no
     `execute_fn` invocation observed
   - **Adversarial input e2e** (NEW, four sub-cases): feed
     `mahavishnu acp serve` (1) a 1 MB prompt, (2) deeply-nested
     JSON (10⁴ levels), (3) a type-confused field
     (`params.prompt` as a dict), (4) a unicode-homoglyph prompt
     (Cyrillic `а` in `аdmin`). Each must return a clean
     JSON-RPC error response, not crash the dispatcher
   - **Bearer redaction e2e** (NEW): capture subprocess stderr,
     grep for the bearer value (use a known-sentinel high-entropy
     UUID4), assert no match
3. Apply `@pytest.mark.timeout(2)` on every e2e case (project
   has `pytest-timeout` in dev). Apply `@pytest.mark.acp` to the
   integration test file. Register the `acp` marker in
   `[tool.pytest.ini_options].markers` in `pyproject.toml`.

**Exit criteria:** With `MAHAVISHNU_ACP_INTEGRATION=1`,
`pytest tests/integration/acp/test_acp_stdio_e2e.py -v` is
green. Without it, the suite skips with a clear reason.

#### Integration Contract — Phase 4

- **Triggered from:** CI release-candidate pipeline or operator
  running `MAHAVISHNU_ACP_INTEGRATION=1 pytest
  tests/integration/acp/`. Not in fast CI.
- **Returns to / updates:** Pass/fail status lands in
  `tests/integration/acp/junit.xml` (consumed by the
  release-candidate pipeline). Structured log line
  `acp.e2e.completed cases_passed=N cases_failed=N` writes to
  `~/.mahavishnu/logs/mcp.log`. Signalled to Akosha via
  `mcp__mahavishnu__notify_workflow_status` so the failure shows
  in the monitoring dashboard. Counter
  `acp.e2e.last_run.passed=true/false` queryable from Akosha.
- **Demonstrable by:** (single line)
  `MAHAVISHNU_ACP_INTEGRATION=1 pytest tests/integration/acp/test_acp_stdio_e2e.py -v`
  → all six test cases pass.
- **Rollback signal:** If the suite fails on `main` after the
  release-candidate gate, an `acp.e2e.regressed=true` alert fires
  on the `#mahavishnu-release` Slack channel. The release-candidate
  runbook (`docs/runbooks/release-gate.md`, to be created if
  not present) names the rollback actor and the two-step revert:
  (1) `git revert <merge-sha>`, (2) re-run
  `MAHAVISHNU_ACP_INTEGRATION=1 pytest tests/integration/acp/ -v`
  to confirm the gate is green again. The revert set is
  `mahavishnu/acp/**` and Phase 1/1.5/2 module additions; the
  Phase 1 EventBridge envelope changes in `bodai_subscriber.py`
  revert independently (do NOT include them in the unified
  revert set).
- **Observability added:** Test outputs are the observability;
  the Akosha counter and the junit.xml artifact make the gate
  programmatically queryable, not just readable in CI logs.

### Phase ordering and dependencies

```
Phase 1 (models + events) ──→ Phase 1.5 (factory refactor) ──→ Phase 2 (dispatcher + CLI) ──→ Phase 4 (gated e2e)
                                                                                              │
                                                                       Phase 3a (doc) ‖ Phase 2┘
                                                                                              │
                                                                              Phase 3b (attribution + license + index) ‖ Phase 4
```

- Phase 1 must land first (no dependencies)
- Phase 1.5 depends on Phase 1 (the factory consumes the Pydantic
  models and the new envelope types)
- Phase 2 depends on Phase 1.5 (the dispatcher uses the factory)
- Phase 3a (doc) can ship in parallel with Phase 2 (no code
  dependency; doc can land before the binary is reproducible)
- Phase 4 depends on Phase 2 (needs the working server to spawn)
- Phase 3b (attribution + license) can ship in parallel with
  Phase 4 or after
- Phases 1, 1.5, 2, 3a, 3b are independently mergeable PRs
- Phase 4 is the quality gate; the plan is "done" only when
  the Phase 4 integration contract is green

## 6. Required Code Changes

### New files

| File | Phase | Purpose |
|---|---|---|
| `mahavishnu/acp/__init__.py` | 1 | Package marker; re-exports |
| `mahavishnu/acp/protocol.py` | 1 | Pydantic wire-format models (spec-correct field names) |
| `mahavishnu/acp/events.py` | 1 | EventBridge → ACP synthesizer |
| `mahavishnu/acp/server.py` | 2 | JSON-RPC 2.0 dispatcher with security hardening |
| `mahavishnu/core/execute_fn_factory.py` | 1.5 | Single source of truth for `build_execute_fn(settings)` |
| `mahavishnu/cli/acp_cli.py` | 2 | `mahavishnu acp serve` Typer command |
| `docs/acp/USAGE.md` | 3a | Operator doc + Toad config + threat model + custom error codes |
| `tests/unit/acp/__init__.py` | 1 | Test package marker |
| `tests/unit/acp/test_protocol.py` | 1 | Pydantic round-trip + `test_acp_spec_field_names` parametrized spec-drift gate |
| `tests/unit/acp/test_events.py` | 1 | EventBridge mapping tests (including new `tool_call_*`) |
| `tests/unit/acp/test_server.py` | 2 | Dispatcher unit tests (full security + hardening surface) |
| `tests/unit/core/test_execute_fn_factory.py` | 1.5 | Factory unit tests + A2A behavior-unchanged assertion |
| `tests/property/acp/__init__.py` | 1 | Property-test package marker |
| `tests/property/acp/test_acp_properties.py` | 1 | Hypothesis strategies for protocol + events round-trip |
| `tests/integration/acp/__init__.py` | 4 | Integration test marker |
| `tests/integration/acp/test_acp_stdio_e2e.py` | 4 | Gated stdio e2e (six cases) |
| `tests/unit/test_acp_docs.py` | 3a | Doc-staleness detector |
| `docs/runbooks/release-gate.md` | 4 (pre-req) | Release-candidate runbook (if not already present) |

### Modified files

| File | Phase | Change |
|---|---|---|
| `mahavishnu/_main_cli.py` | 2 | Register `acp_cli` as `app.add_typer(acp_app, name="acp")` |
| `mahavishnu/a2a/server.py` | 1.5 | Import the new factory; replace plain `!=` with `secrets.compare_digest` (the A2A Bearer-middleware fix) |
| `mahavishnu/core/events/bodai_subscriber.py` | 1 | Emit `tool_call_started` and `tool_call_completed` (Decision 2) |
| `mahavishnu/workers/apple_container.py` | 1 | Emit `tool_call_started` at sandbox launch, `tool_call_completed` at sandbox destroy |
| `mahavishnu/workers/e2b_sandbox.py` | 1 | Same emission pattern as `apple_container.py` |
| `docs/README.md` (or current docs index) | 3b | One-line "Integrations → ACP" entry |
| `THIRD_PARTY_NOTICES.md` | 3b | Add Toad row (AGPL-3.0, subprocess mode) |
| `pyproject.toml` | 4 | Register `acp` marker under `[tool.pytest.ini_options].markers`; bump optional dep declaration if needed |
| `docs/plans/PLAN_INDEX.md` | 3b | Flip this plan from `draft` to `active` |
| `pyproject.toml:16` (license) | 3b (or follow-up) | Reconcile with `LICENSE` (BSD-3-Clause) — separate issue, non-blocking |

### Untouched (per Non-Goals)

- `mahavishnu/a2a/server.py` (after the Phase 1.5 refactor lands;
  the refactor is a one-line import change plus the auth fix)
- `mahavishnu/workers/crow.py` — unchanged (not ACP despite the name)
- `mahavishnu/tui/` — unchanged (TUI work is tracked in `docs/feature-tracking/tui.md`)

## 7. Validation Matrix

| Check | Command | Expected outcome | Phase |
|---|---|---|---|
| Protocol round-trips + spec shape | `pytest tests/unit/acp/test_protocol.py -v` | All green; `test_acp_spec_field_names` parametrized passes | 1 |
| Property-based tests | `pytest tests/property/acp/ -v` | All green; no crash on adversarial envelope types | 1 |
| Event mapping table | `pytest tests/unit/acp/test_events.py -v` | All green (incl. `tool_call_*` cases) | 1 |
| EventBridge doesn't break | `pytest tests/unit/test_bodai_subscriber.py -v` | All green; `apple_container.py` and `e2b_sandbox.py` emission sites exercised | 1 |
| A2A factory refactor is behavior-preserving | `pytest tests/unit/a2a/ tests/unit/core/test_execute_fn_factory.py -v` | All green; A2A auth now uses `secrets.compare_digest` | 1.5 |
| Dispatcher unit (full security surface) | `pytest tests/unit/acp/test_server.py -v` | All green (auth, timeout, cancel, rate limit, redaction, etc.) | 2 |
| Observability validation (NEW) | `pytest tests/unit/acp/test_observability_validation.py -v` | OTel span + four `acp.*` log lines captured | 2 |
| CLI registered | `uv run mahavishnu --help` | Lists `acp` subcommand | 2 |
| `acp serve` smoke | `echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"0.0.1","clientInfo":{"name":"smoke","version":"0.0.1"}}}' \| MAHAVISHNU_ACP_BEARER_TOKEN=$(python -c 'import secrets;print(secrets.token_urlsafe(32))') uv run mahavishnu acp serve` | Valid `InitializeResponse` on stdout, exit 0, `loadSession: false`, `mcpCapabilities.http: false` | 2 |
| Existing A2A unchanged behavior | `pytest tests/unit/a2a/ -v` | All green; auth now constant-time | 1.5, 2 |
| TUI doesn't break | `pytest tests/unit/test_tui_dashboard.py tests/unit/test_command_palette.py -v` | All green | 1, 2, 4 |
| Doc renders + Toad config parses + CLI help matches | `pytest tests/unit/test_acp_docs.py -v` | All green | 3a |
| `THIRD_PARTY_NOTICES.md` has Toad | `grep -c "batrachianai/toad" THIRD_PARTY_NOTICES.md` | ≥1 | 3b |
| `docs/plans/PLAN_INDEX.md` flipped | `grep "acp-server" docs/plans/PLAN_INDEX.md` | Status: `active` | 3b |
| Gated e2e (six cases) | `MAHAVISHNU_ACP_INTEGRATION=1 pytest tests/integration/acp/test_acp_stdio_e2e.py -v` | All six pass | 4 |
| `@pytest.mark.timeout` on e2e | `pytest --collect-only --quiet tests/integration/acp/` | Every e2e case shows `timeout: 2.0` | 4 |
| Crackerjack | `crackerjack run` (or `python -m crackerjack`) | No new offenses | 1, 1.5, 2, 3, 4 |
| License metadata | `grep -A1 "license" pyproject.toml` | Matches `LICENSE` (post-Phase 3b reconciliation) | 3b |
| Manual Toad smoke | Configure Toad → `mahavishnu acp serve`, type a prompt | Streamed chunks visible in Toad; cancel works | 3a + 3b |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `session/prompt` blocks on long-running `execute_fn` and the ACP client times out | Medium | ACP has no client-side timeout mandated by the spec; Toad defaults to 30s. Phase 2 emits `session/update` notifications with intermediate chunks so the client sees progress, not silence. Phase 2's `asyncio.wait_for(..., timeout=600)` enforces a hard ceiling. Document the chunking expectation in `docs/acp/USAGE.md`. |
| Timing attack on Bearer token compare | Low | `secrets.compare_digest` in `mahavishnu/acp/server.py`; A2A's `!=` bug is fixed in Phase 1.5 in the same PR. |
| Unbounded `execute_fn` lifetime (worker ignores `CancelledError`) | Medium | `asyncio.wait_for` timeout + hard `task.cancel() + wait_for(5)`; `status: "failed"` + `cancel_refused` log on refusal. |
| Unbounded memory via 1 GB JSON-RPC line on stdin | Medium | `_SafeLineReader(max_bytes=1_048_576)` rejects oversized lines with `-32700 Parse error` before `json.loads`. |
| Pydantic field-size blow-up (100 MB prompt) | Medium | `Field(..., max_length=100_000)` on `prompt` and every other string field. Pydantic rejects before dispatch. |
| Unbounded session creation (DoS via `session/new` flood) | Low | `MAX_CONCURRENT_SESSIONS` rate limit (default 16) with `-32004` rejection. |
| Empty / unset Bearer token (fail-open like A2A) | Low | `serve()` refuses to start if neither `MAHAVISHNU_ACP_BEARER_TOKEN` nor `MAHAVISHNU_ACP_BEARER_TOKEN_FILE` is set. |
| Bearer token leaks via `ps auxe` / `/proc/<pid>/environ` | Medium | Document the env-var pattern. Phase 2 also supports `MAHAVISHNU_ACP_BEARER_TOKEN_FILE` (mode 0600). `os.environ.pop(...)` after read prevents child-process inheritance. |
| Bearer token in log lines (future regression) | Low | `logging.Filter` redactor in `mahavishnu/acp/server.py`; Phase 4 e2e test asserts no log line contains the original bearer value (high-entropy UUID4 sentinel). |
| Bearer token logged by ACP client (e.g., Toad) | Low (out of our control) | Document in `docs/acp/USAGE.md` "Security" section; operators check their client's docs. |
| EventBridge envelope addition breaks existing consumers (A2A, WebSocket, Session-Buddy) | Medium | The two new envelope types are additive; existing consumers ignore unknown types. The Phase 1 rollback signal is the regression suite for `subscribe_to_bodai_events` consumers. Emission-site identification is now concrete (`apple_container.py` and `e2b_sandbox.py`) so the implementer is not hand-waving. |
| Stdio buffering on the Mahavishnu side silently drops `session/update` notifications | Medium | The dispatcher flushes `sys.stdout` after every write; `sys.stderr.flush()` after every log line. Phase 4 e2e asserts both via `subprocess.read1`. |
| `mahavishnu acp serve` is added but never used (no ACP client connects) | High | This is the risk Phase 3 mitigates: the operator doc is the path to a real Toad integration. If Phase 3a ships and Toad integration is not attempted within one release cycle, the plan is "built but not adopted" and we should re-evaluate. |
| Toad's config format changes upstream | Low | Document the Toad version the config was tested against; Phase 3a's `test_toad_config_block_parses` + `test_cli_examples_match_help` catches doc rot, not upstream Toad changes. |
| `pyproject.toml:16` (MIT) vs `LICENSE` (BSD-3-Clause) drift confuses the first ACP-aware release's metadata | Low | Phase 3b (or follow-up issue) reconciles the two; `THIRD_PARTY_NOTICES.md` is the operator-visible license source of truth until then. |
| A2A auth refactor in Phase 1.5 changes A2A's behavior | Low | The refactor is a one-line import + a `secrets.compare_digest` swap. The `diff`-based exit criterion (no test output diff) is the regression gate. |

## 9. Decision Rule

This plan is "done enough" when:

1. Phases 1, 1.5, 2, 3a, 3b, 4 have all shipped (or been formally
   abandoned with a written rationale in this file)
2. The Phase 4 integration contract is green on a release-candidate
   build (all six e2e cases)
3. The Phase 3a manual Toad smoke has been performed at least once
4. `crackerjack run` is clean on the ACP modules
5. `docs/plans/PLAN_INDEX.md` has been updated to flip this plan
   from `draft` to `active` (and later to `shipped` when the
   v1.5 follow-ups are filed)
6. `docs/feature-tracking/tui.md` is updated to reference this
   plan as unblocked
7. **A follow-up issue or v1.5 plan is filed for the
   Toad-integration smoke** (so the TUI's `adopted` state can be
   honestly evaluated; this plan ships the server, not the
   Toad-integration story)
8. The Phase 3b license reconciliation (`pyproject.toml:16` vs
   `LICENSE`) is filed as a follow-up issue if not already
   resolved

**Phase 2 is inviolable.** Cutting Phase 2 means the plan fails —
there is no ACP server without a dispatcher and CLI surface.

If scope pressure forces a cut, the order to drop is: Phase 4
first (gated tests can be backfilled), Phase 3b second
(attribution + license can be follow-up issues), Phase 3a
third (operator doc can wait one release), Phase 1 last (the
Pydantic protocol models are load-bearing and the smallest
testable unit). Phase 1.5 and Phase 2 are not in the drop order.

## 10. v1.5 follow-ups (not in this plan's scope)

Filed as separate plans or issues when this plan ships:

- **v1.5.1 — ACP session persistence.** Add `session/load` support
  backed by `~/.mahavishnu/acp-sessions/<id>.jsonl`; re-run the
  License/Compliance review (per Decision 3). Flip
  `loadSession: true` in `InitializeResponse`.
- **v1.5.2 — MCP-over-ACP.** When the upstream RFD stabilizes,
  flip `mcpCapabilities.acp: true` and tunnel the existing 174
  MCP tools through ACP sessions. Re-run the AGPL §13 analysis.
- **v1.5.3 — Remote ACP (Streamable HTTP).** Add `--transport=http`
  to `mahavishnu acp serve`. Auth posture shifts: bearer over
  HTTP needs additional hardening (TLS, rate limit per IP,
  token rotation).
- **v1.5.4 — UUID v7 session IDs.** RFC 4122 v7 (time-ordered) for
  better observability / DB indexing.
- **v1.5.5 — `session/list`, `session/resume`, `session/set_mode`,
  `session/close`, `session/delete`, `logout`. Surface area
  expansion once v1.5.1's persistence is in.
- **v1.5.6 — License declaration reconciliation.** `pyproject.toml:16`
  (MIT) vs `LICENSE` (BSD-3-Clause). One-line fix; non-blocking.
- **v1.5.7 — Toad-integration smoke test.** Manual smoke that
  wires Toad → Mahavishnu end-to-end, captures a sample
  session, validates streaming. Prerequisite for
  `docs/feature-tracking/tui.md` flipping to `adopted`.

## References

- Design spec: `docs/superpowers/specs/2026-07-15-mahavishnu-acp-server-design.md`
- TUI feature tracker (the consumer of this plan):
  `docs/feature-tracking/tui.md`
- Plan template: `docs/plans/TEMPLATE.md`
- Wire-up contract: `.claude/decisions/wire-up-contract.md`
- Prior Toad/ACP deferrals (4, not 5):
  - `docs/superpowers/plans/2026-06-19-track3-toad-tui.md` (draft)
  - `docs/superpowers/specs/2026-06-19-external-integrations-design.md:324-380` (Toad ACP deferred)
  - `docs/superpowers/specs/2026-07-15-constellation-tui-design.md:10-16,41-47` (Track2 out of scope)
  - `docs/superpowers/plans/2026-07-15-constellation-tui.md:59-63` (Track2 out of scope)
- A2A server (partial implementation reference, then refactored
  in Phase 1.5): `mahavishnu/a2a/server.py`
- EventBridge subscriber (consumed + extended): `mahavishnu/core/events/bodai_subscriber.py`
- Worker dispatch sites (extended with new envelope emissions):
  `mahavishnu/workers/apple_container.py`,
  `mahavishnu/workers/e2b_sandbox.py`,
  `mahavishnu/workers/manager.py`
- ACP official: [agentclientprotocol.com](https://agentclientprotocol.com/);
  governance: [Zed + JetBrains](https://agentclientprotocol.com/community/governance)
- Toad: [github.com/batrachianai/toad](https://github.com/batrachianai/toad)
  (AGPL-3.0; downstream consumer of this plan)
- Toad LICENSE: see `THIRD_PARTY_NOTICES.md` (added in Phase 3b)
- Review journal: `/private/tmp/claude-501/-Users-les-Projects-mahavishnu/03ad3673-6b33-4c9a-8866-48fbf76281b1/tasks/werg7eois.output`
