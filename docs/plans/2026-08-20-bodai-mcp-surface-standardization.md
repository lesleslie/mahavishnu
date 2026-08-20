---
status: active
role: implementation
date: 2026-08-20
last_reviewed: 2026-08-20
superseded_by: null
topic: bodai-mcp-surface-standardization
---

# Bodai Core MCP Surface Standardization

> **Companion to:** [`2026-08-20-mahavishnu-lifespan-health-bypass.md`](./2026-08-20-mahavishnu-lifespan-health-bypass.md)
> Phase 4 of that plan was promoted to this standalone plan during review on 2026-08-20.
> **Lifecycle:** This plan is non-blocking on Phases 1-3 of the lifespan plan; ships in
> Session-Buddy + mcp-common as a follow-up commit on the same plan branch.

## 1. Outcome

Every Bodai core MCP server exposes the same baseline tool surface so a
client performing tool discovery across the ecosystem sees a uniform
shape. Specifically:

- `discover_tools(query)` — list registered tools with optional filter
- `get_liveness()` — return `{status, service, version, uptime}`
- `get_readiness()` — return readiness probe result
- `health_check_all()` — return dependency health summary

After this plan ships, calling `discover_tools()` against any of
`mahavishnu`, `akosha`, `dhara`, `crackerjack`, `session-buddy` returns
the same baseline 4-tool list plus that server's domain-specific tools.

This unblocks automation that assumes the baseline (the `bodai-radar`
skill, the `ecosystem-awareness` skill, Claude Code's cross-server
introspection) and prevents drift.

**Success metric:** `pytest mcp-common/tests/test_baseline_surface.py`
passes with all 5 Bodai core servers green.

## 2. Goals

1. Session-Buddy exposes `discover_tools`, `get_liveness`,
   `get_readiness`, `health_check_all` — matching the other 4 core
   servers' baseline.
2. `ping` is preserved as a deprecated alias delegating to
   `get_liveness` for one release, giving the 3 confirmed consumers
   (Akosha, Mahavishnu, Crackerjack) a migration window. The alias
   is removed in the next release.
3. mcp-common pins the 4-tool baseline with a regression test that
   fails CI if any Bodai core server drops a baseline tool.

## 3. Non-Goals

- Adding tools beyond the 4-tool baseline (this plan establishes the
  baseline, not a comprehensive surface list).
- Changing the response shape of `get_liveness` or `discover_tools`
  on the 4 already-conforming servers (mahavishnu, akosha, dhara,
  crackerjack).
- Standardizing non-core `*-mcp` standalone servers (e.g. css-mcp,
  graphics-mcp, opera-cloud-mcp) — those are out of scope for the
  "Bodai core" invariant.
- Performance work on the baseline tools themselves (they're
  metadata operations, not hot paths).

## 4. Current Findings

**Smoke test on 2026-08-20** — invoked `discover_tools()` against each
Bodai core MCP server. Results:

| Server | `discover_tools` | `get_liveness` | `get_readiness` | `health_check_all` | Notes |
|---|:---:|:---:|:---:|:---:|---|
| mahavishnu | ✅ | ✅ | ✅ | ✅ | Reference implementation (98 baseline + domain tools) |
| akosha | ✅ | ✅ | ✅ | ✅ | 24 tools total |
| crackerjack | ✅ | ✅ | ✅ | ✅ | 40 tools total |
| dhara | ✅ | ✅ | ✅ | ✅ | 7 tools total (lean by design) |
| **session-buddy** | **❌** | **❌** | **✅** | **❌** | Uses one-off `ping` ("Pong! MCP server is responding"); `server_info` instead of structured `discover_tools`; no `health_check_all` |

**Confirmed `ping` callers** (verified via `git grep -rn 'tool.*ping\|"ping"\|call_tool.*ping'`
against the Bodai core repos on 2026-08-20):

- `akosha/mcp/server.py:run_fitness_analysis` — calls Session-Buddy
  via BodaiComponentMCPClient with `ping` for liveness before
  polling OTel traces.
- `mahavishnu/mcp/tools/session_buddy_tools.py` — pre-flight `ping`
  check on every session-buddy tool invocation.
- `crackerjack/services/otel_ingester.py` — pings Session-Buddy
  before opening an OTel stream.

These call sites need the alias during the migration window (Task 4
of Phase 2 below).

**`server_info` in Session-Buddy** returns an ASCII banner, not the
structured envelope `{status, profile, query, capability,
loaded_tools, loaded_count, not_loaded_tools, not_loaded_count,
total_known, hint}` that mahavishnu's `discover_tools` returns. The
shape must be aligned.

## 5. Implementation Phases

### Phase 1: Establish baseline tools in mcp-common

**Goal:** mcp-common provides canonical reference implementations of
the 4 baseline tools, with a testable surface that downstream servers
register directly.

**Tasks:**

1. Create `mcp_common/baseline_tools.py` exporting
   `register_baseline_tools(server: FastMCP) -> None` (single
   registration function that wires all 4 tools at once).
2. `register_baseline_tools` calls `server.tool()(discover_tools)`,
   `server.tool()(get_liveness)`, etc. — the canonical envelope
   shapes are returned by the helper functions.
3. `get_liveness` reads `{status, service, version, uptime}` from a
   standard `LivenessContext` populated at server boot (via
   FastMCP's lifespan hook).
4. Export `register_baseline_tools` from `mcp_common.__init__` so
   consumers do `from mcp_common import register_baseline_tools`.

**Exit criteria:**
- `pytest mcp-common/tests/test_baseline_helpers.py -v` passes.
- `python -c "from mcp_common import register_baseline_tools"` does
  not raise.
- A standalone smoke script
  (`mcp-common/scripts/smoke_baseline.py`) registers the helpers on
  a fresh FastMCP instance and exercises each tool, returning the
  canonical envelope.

#### Integration Contract
- **Triggered from**: any Bodai core server's `mcp/server.py`
  startup path, plus the new mcp-common regression test.
- **Returns to / updates**:
  - `mcp_common/baseline_tools.py` (new) — reference implementations.
  - `mcp_common/__init__.py` — exports `register_baseline_tools`.
  - `mcp-common/tests/test_baseline_helpers.py` (new) — unit tests
    for each helper.
  - `mcp-common/scripts/smoke_baseline.py` (new) — manual smoke
    script.
- **Demonstrable by**:
  ```bash
  python mcp-common/scripts/smoke_baseline.py
  # expected: 4 lines of structured JSON output, one per tool,
  # each matching the canonical envelope shape
  ```
- **Rollback signal**: any of the 4 helpers raises on import →
  revert the mcp-common commit; downstream servers are unaffected
  because they haven't switched to the helpers yet.
- **Observability added**: `get_liveness` writes its `uptime` from
  `LivenessContext.start_time` which logs a single INFO line at
  server boot.

### Phase 2: Migrate Session-Buddy to baseline tools + `ping` alias

**Goal:** Session-Buddy exposes the 4-tool baseline matching every
other Bodai core server, with `ping` preserved as a deprecated alias
for one release.

**Tasks:**

1. **Verify the assumed surface exists.** Before writing code,
   confirm:
   - Session-Buddy's MCP server uses FastMCP (verified by reading
     `session-buddy/mcp/server.py`).
   - Session-Buddy already exposes `get_readiness` (confirmed in
     §4 Current Findings).
   - Session-Buddy does NOT currently import from `mcp_common` —
     confirm by reading `session-buddy/pyproject.toml` and the
     import statements in `mcp/server.py`. Add `mcp-common` as a
     dependency if not present.
   - Session-Buddy's `/mcp` endpoint responds to JSON-RPC
     `tools/list` — confirm with a `curl` smoke check before
     writing the test in Phase 3.
2. **Add `discover_tools`, `get_liveness`, `health_check_all`** to
   `session-buddy/mcp/server.py` by calling
   `register_baseline_tools(server)` from mcp-common. `get_readiness`
   is already present per §4.
3. **Preserve `ping` as a deprecated alias** that delegates to
   `get_liveness`. Add a `DeprecationWarning` log line at WARN level
   on every invocation so consumers see the migration signal.
4. **Update Session-Buddy docs** (`CLAUDE.md`, `README.md`) to list
   `discover_tools`, `get_liveness`, `get_readiness`,
   `health_check_all` in the MCP surface section. Mention `ping` as
   "deprecated alias, will be removed in the next release."
5. **CHANGELOG entry** in Session-Buddy under the next version
   header: "Deprecated `ping` MCP tool; use `get_liveness` instead.
   Removed in <next-next-version>."

**Exit criteria:**
- `pytest session-buddy/tests/test_mcp_baseline.py -v` passes (new
  test, see Phase 3).
- Session-Buddy `tools/list` JSON-RPC call returns all 4 baseline
  tool names plus `ping` (the deprecated alias).
- Session-Buddy `ping` JSON-RPC call returns the same envelope as
  `get_liveness` plus a `DeprecationWarning` in the log.
- `git grep -rn ping -- 'session-buddy/mcp/'` returns ONLY the
  alias registration and the deprecation log line.

#### Integration Contract
- **Triggered from**: Session-Buddy server startup path
  (`session-buddy/mcp/server.py:create_app` or equivalent).
- **Returns to / updates**:
  - `session-buddy/mcp/server.py` — adds 3 baseline tools + 1
    deprecated alias.
  - `session-buddy/CLAUDE.md` + `README.md` — MCP surface docs.
  - `session-buddy/CHANGELOG.md` — deprecation notice.
  - `session-buddy/pyproject.toml` — adds `mcp-common` dep if not
    already present.
- **Demonstrable by**:
  ```bash
  # 1. Tool list shows baseline + alias
  curl -sf http://localhost:8678/mcp \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
    | jq '.result.tools[].name' \
    | grep -E '^(discover_tools|get_liveness|get_readiness|health_check_all|ping)$'
  # expected: all 5 names present (4 baseline + 1 deprecated alias)

  # 2. ping still works but logs a deprecation warning
  curl -sf http://localhost:8678/mcp \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"ping","arguments":{}}}' \
    | jq '.result'
  # expected: same envelope as get_liveness
  # AND: a WARN log line "ping is deprecated, use get_liveness"
  ```
- **Rollback signal**: any of the 4 baseline tools raises OR `ping`
  alias returns a different envelope than `get_liveness` → revert
  via `git revert` of the Session-Buddy commit. Consumers (Akosha,
  Mahavishnu, Crackerjack) see no breakage because `ping` still
  works.
- **Observability added**: WARN-level `DeprecationWarning` log on
  every `ping` invocation. Log line includes the consumer's caller
  info (best-effort, from the FastMCP Context).

### Phase 3: Cross-server regression test in mcp-common

**Goal:** The baseline is enforced by CI — any future commit that
removes a baseline tool from any Bodai core server fails the build.

**Tasks:**

1. Create `mcp_common/testing/baseline_surface.py` exporting
   `assert_baseline_surface(server_url: str) -> list[str]` — opens
   a JSON-RPC connection to the given server, calls `tools/list`,
   asserts all 4 baseline tools are present, returns the loaded
   tool list.
2. Create `mcp-common/tests/test_baseline_surface.py` parametrized
   over the 5 Bodai core servers (`mahavishnu:8680`, `akosha:8682`,
   `dhara:8683`, `crackerjack:8676`, `session-buddy:8678`). Each
   parametrize case calls `assert_baseline_surface` and asserts
   pass. Mark with `pytest.mark.requires_network` so it skips in
   offline CI.
3. Add a Session-Buddy-specific test
   `session-buddy/tests/test_mcp_baseline.py` that imports
   `assert_baseline_surface` and runs it against
   `http://localhost:8678/mcp`. This is the per-repo gate that
   runs in Session-Buddy's own CI.
4. Add `docs/feature-tracking/2026-08-20-bodai-mcp-surface-standardization.md`
   tracking entry with `{built, wired, adopted}` states per the
   wire-up-contract policy.
5. Run `python scripts/audit_orphans.py` (in mcp-common) before
   declaring complete — confirm the new baseline helpers have
   callers in every consumer that adopts them.

**Exit criteria:**
- `pytest mcp-common/tests/test_baseline_surface.py -v` passes
  when all 5 servers are running.
- `pytest session-buddy/tests/test_mcp_baseline.py -v` passes
  when Session-Buddy is running.
- Feature-tracking entry exists and shows
  `{built: true, wired: true, adopted: pending}`.
- `audit_orphans.py` reports no zero-caller symbols for
  `mcp_common.baseline_tools.*` exports.

#### Integration Contract
- **Triggered from**: CI on every PR to mcp-common, Session-Buddy,
  or any Bodai core consumer repo.
- **Returns to / updates**:
  - `mcp_common/testing/baseline_surface.py` (new) — the helper.
  - `mcp-common/tests/test_baseline_surface.py` (new) — 5-server
    parametrized test.
  - `session-buddy/tests/test_mcp_baseline.py` (new) — per-repo
    gate.
  - `docs/feature-tracking/2026-08-20-bodai-mcp-surface-standardization.md`
    (new) — tracking entry.
- **Demonstrable by**:
  ```bash
  # 1. Run the cross-server test (requires all 5 servers up)
  pytest mcp-common/tests/test_baseline_surface.py -v
  # expected: 5 passed in <5s

  # 2. Run Session-Buddy's per-repo gate
  pytest session-buddy/tests/test_mcp_baseline.py -v
  # expected: 1 passed

  # 3. Confirm feature tracking exists
  ls docs/feature-tracking/2026-08-20-bodai-mcp-surface-standardization.md
  # expected: file exists

  # 4. Confirm audit_orphans is clean for new symbols
  python scripts/audit_orphans.py --since 2026-08-20
  # expected: no zero-caller hits for mcp_common.baseline_tools
  ```
- **Rollback signal**: any of the 5 parametrized cases fails OR a
  consumer's CI starts failing because the helper was removed →
  revert the mcp-common commit that removed the helper. Consumers
  fall back to their previous behavior because the helpers are
  opt-in registration, not enforced inheritance.
- **Observability added**: CI logs the specific server URL that
  failed the baseline check, plus the list of missing tools.

## 6. Required Code Changes

- [ ] `mcp_common/baseline_tools.py` (new) — reference
      implementations of `discover_tools`, `get_liveness`,
      `get_readiness`, `health_check_all`, plus
      `register_baseline_tools(server)`.
- [ ] `mcp_common/__init__.py` — export `register_baseline_tools`.
- [ ] `mcp_common/testing/baseline_surface.py` (new) —
      `assert_baseline_surface(server_url)` helper.
- [ ] `mcp-common/tests/test_baseline_helpers.py` (new) — unit
      tests for the 4 helpers.
- [ ] `mcp-common/tests/test_baseline_surface.py` (new) —
      5-server parametrized regression test.
- [ ] `mcp-common/scripts/smoke_baseline.py` (new) — manual
      smoke script.
- [ ] `session-buddy/mcp/server.py` — register the 4 baseline
      tools + `ping` deprecated alias.
- [ ] `session-buddy/pyproject.toml` — add `mcp-common` dep if not
      already present.
- [ ] `session-buddy/CLAUDE.md` + `README.md` — update MCP surface
      docs.
- [ ] `session-buddy/CHANGELOG.md` — deprecation notice for
      `ping`.
- [ ] `session-buddy/tests/test_mcp_baseline.py` (new) — per-repo
      gate.
- [ ] `docs/feature-tracking/2026-08-20-bodai-mcp-surface-standardization.md`
      (new) — tracking entry.
- [ ] `git grep -rn ping -- 'session-buddy/mcp/'` (complete
      signal) — must return ONLY the alias registration + the
      deprecation log line, no other uses.

## 7. Validation Matrix

| Check | Expected | Evidence |
|---|---|---|
| `pytest mcp-common/tests/test_baseline_helpers.py -v` | PASS | pytest output |
| `python mcp-common/scripts/smoke_baseline.py` | 4 JSON envelopes | script output |
| Session-Buddy `tools/list` returns 4 baseline + `ping` alias (Phase 2 complete signal) | 5 names | `curl ... \| jq` |
| Session-Buddy `get_liveness` envelope shape | `{status, service, version, uptime}` | `curl ... \| jq` |
| Session-Buddy `ping` returns same envelope as `get_liveness` | identical body + WARN log | curl + log |
| `pytest mcp-common/tests/test_baseline_surface.py -v` (all 5 servers) | 5 PASS | pytest output |
| `pytest session-buddy/tests/test_mcp_baseline.py -v` | PASS | pytest output |
| `ls docs/feature-tracking/2026-08-20-bodai-mcp-surface-standardization.md` | file exists | shell output |
| `python scripts/audit_orphans.py --since 2026-08-20` | no zero-caller hits for `mcp_common.baseline_tools` | audit output |
| `git grep -rn ping -- 'session-buddy/mcp/'` (Phase 2 complete signal) | only alias registration + deprecation log | grep output |
| `crackerjack run` (mcp-common + session-buddy, full quality gate) | PASS | crackerjack report |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Session-Buddy doesn't currently depend on mcp-common | Medium | Verified via pyproject read in Phase 2 task 1; add dep if missing |
| Session-Buddy's `/mcp` endpoint doesn't respond to JSON-RPC `tools/list` (different transport or auth) | Low | Smoke check in Phase 2 task 1 before writing the test; if blocked, fall back to FastMCP client SDK call instead of raw JSON-RPC |
| Consumers (Akosha, Mahavishnu, Crackerjack) hard-code the `ping` tool name | Medium | `ping` is preserved as a deprecated alias for one release; CHANGELOG entry gives consumers a migration signal; grep audit in Phase 2 exit criteria confirms no other `ping` references |
| `discover_tools` envelope shape diverges across the 5 servers (mahavishnu's envelope is richer than the others) | Low | Reference implementation in mcp-common (Phase 1) pins the canonical shape; Session-Buddy + any drift-prone server follow the reference; per-repo gate enforces locally |
| CI test (`test_baseline_surface.py`) is flaky in offline CI | Medium | Marked with `pytest.mark.requires_network` so it auto-skips in offline runs; per-repo gate (`session-buddy/tests/test_mcp_baseline.py`) provides local-only enforcement |
| Backward-compat `ping` alias gets forgotten and ships for 2 releases | Low | CHANGELOG entry says "Removed in <next-next-version>"; add a follow-up plan entry to remove `ping` after the deprecation window |
| Cross-repo coordination: mcp-common ships before Session-Buddy switches | Low | mcp-common helpers are opt-in registration (Phase 1 design); consumers can adopt at their own pace |
| New `discover_tools` overloads an existing `discover_tools` already in Session-Buddy under a different name | Low | Verified via `git grep discover_tools -- 'session-buddy/'` in Phase 2 task 1 before adding |

## 9. Decision Rule

**Phase 1 (mcp-common helpers) is the load-bearing deliverable.**
Without it, Phases 2 and 3 have nothing to call. Ship Phase 1 alone
if Phase 2/3 block.

**Phase 2 (Session-Buddy migration) is the user-visible deliverable.**
Ship in Session-Buddy as soon as Phase 1 lands; consumers see no
breakage because `ping` is preserved as an alias.

**Phase 3 (cross-server regression test) is the enforcement gate.**
Ship after Phase 2 lands — the test gates future drift, so it must
exist in the same release as the migration.

**Execution order:** Phase 1 → Phase 2 → Phase 3, each as its own
commit on the same plan branch. Do not squash — reviewers need to
trace each phase independently.

**Relationship to the lifespan plan:** This plan was promoted from
Phase 4 of [`2026-08-20-mahavishnu-lifespan-health-bypass.md`](./2026-08-20-mahavishnu-lifespan-health-bypass.md)
during review on 2026-08-20. It is non-blocking on Phases 1-3 of
that plan and can ship independently in Session-Buddy + mcp-common.

---

## Appendix A: Why preserve `ping` as an alias instead of removing it?

Three reasons:
1. **Three confirmed callers** (§4 Current Findings) — Akosha's
   `run_fitness_analysis`, Mahavishnu's `session_buddy_tools.py`,
   Crackerjack's `otel_ingester.py` all pre-flight `ping`. Removing
   it without a migration window breaks all three.
2. **One release is cheap** — a deprecated alias is ~10 lines of
   code (delegate to `get_liveness`, log a warning) and adds zero
   maintenance overhead.
3. **The deprecation log line is the migration signal** — consumers
   see the warning in their own logs and can plan the migration.
   Without the alias, they'd get hard connection errors with no
   advance notice.

## Appendix B: Why a new mcp-common module instead of inline registration in each server?

Two reasons:
1. **Drift prevention** — if each server hand-rolls the baseline,
   any future change to the canonical shape requires N edits. With
   a shared module, the canonical shape is updated in one place.
2. **Testability** — `mcp_common/testing/baseline_surface.py` can
   assert against the reference implementation, not against N
   divergent copies. Per-repo gates
   (`session-buddy/tests/test_mcp_baseline.py`) consume the helper
   directly.
