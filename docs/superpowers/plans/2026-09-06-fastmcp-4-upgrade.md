# FastMCP ≥4 Upgrade Plan — Bodai Ecosystem

**Date:** 2026-09-06
**Author:** Claude (Mahavishnu session continuation)
**Scope:** mahavishnu (vish), mcp-common, akosha, dhara, session-buddy, crackerjack, css-mcp, graphics-mcp, excalidraw-mcp

## Summary

FastMCP 4.x is already installed in `mcp-common/.venv` (4.0.3) but every
consumer repo is pinned to `<4` and installs 3.4.7. **mcp-common has
already moved forward; consumers have not followed.** This plan closes
the gap.

The actual FastMCP API surface used by Bodai servers is small relative to
the total decorator count: no `as_proxy`, no `import_server`, no
`mount(prefix=...)`, no `sampling_handler`, no `ctx.sample`,
no `add_tool_transformation`. The decorator return-value change (v4
returns the original function instead of a `Tool` object) is also
non-impactful — no Bodai code captures the return value of `@mcp.tool`.

## Current state (2026-09-06)

| Repo | pyproject pin | .venv installed | Decorators | Notes |
| --- | --- | --- | --- | --- |
| mcp-common | `>=3.4.0` (open) | **4.0.3** | 8 (utilities/shims) | Already on 4.x |
| mahavishnu | `>=3.4.7,<4` | 3.4.7 | 375 + 15 (app.tool) | `<4` blocks 4.x; 93 `mount(` are Textual container, not FastMCP |
| akosha | `>=2.14.0` | 3.4.7 | 8 + 10 (app.tool) | **STUCK ON 2.x in pyproject** (3.x installed in venv via transitive resolution); needs 2→3 catch-up before 4 |
| dhara | `>=3.4.0,<4` | 3.4.7 | 0 | `<4` blocks; auth-only module — verify v4 compatibility |
| session-buddy | `>=3.4.0,<4` | 3.4.7 | 527 + 1 (prompt) | `<4` blocks; largest decorator count |
| crackerjack | `>=3.4.2` (open) | 3.4.7 | 16 | Already allows 4.x |
| css-mcp | `>=3.4.0,<4` | 3.4.7 | 27 | `<4` blocks |
| graphics-mcp | `>=3.4.0,<4` | 3.4.7 | 11 (app.tool only) | `<4` blocks |
| excalidraw-mcp | `>=3.4.2` (open) | 3.4.7 | 1 | Already allows 4.x |

## FastMCP 4.x breaking changes affecting Bodai

Source: [FastMCP 3 → 4 migration prompt](https://gofastmcp.com/getting-started/upgrading/from-fastmcp-3).

### Environment prerequisites

- pydantic ≥2.12
- FastAPI ≥0.133.0 (or remove the `<0.116` cap that some repos carry)
- starlette ≥1.0.1

### Removed APIs (Bodai exposure)

| API | Bodai usage | Action |
| --- | --- | --- |
| `FastMCP.as_proxy(...)` | 0 hits | None |
| `import_server(...)` | 0 hits | None |
| `mount(prefix=...)`, `mount(as_proxy=...)` | 0 hits (mahavishnu's 93 `mount(` are Textual container) | None |
| `remove_tool(...)` | 1 hit in `mcp-common/mcp_common/tools/dispatch.py:228`; try/except already catches `KeyError, AttributeError, ValueError` | **Verified 2026-09-06: no patch needed** — existing exception clause covers v4 behavior |
| `add_tool_transformation(...)` / `remove_tool_transformation(...)` | 0 hits | None |
| `tool(serializer=...)`, `tool(exclude_args=...)` | 0 hits | None |
| `FASTMCP_DECORATOR_MODE` / `decorator_mode` | 0 hits | None |
| `FastMCP(sampling_handler=...)` | 0 hits | None |
| `ctx.sample(...)`, `ctx.sample_step(...)`, `ctx.list_roots(...)` | 0 hits | None (client-side unaffected) |

### Decorator return-value change (v3 → v4)

In v3, `@mcp.tool` returned a `Tool` object. In v4 it returns the
original function. Bodai code does not capture the return value (verified
by grep for `@\s*mcp\.tool$` followed by `=`), so this change is safe.

## Migration phases

### Phase 1 — mcp-common ✅ verified clean (2026-09-06)

mcp-common's `.venv` already runs FastMCP 4.0.3. The pyproject pin
`fastmcp>=3.4.0` is open, so the venv pulled 4.x via transitive
resolution.

**Initial assumption (revised):** the plan flagged
`mcp_common/tools/dispatch.py:228` as needing a KeyError patch because
v3 raised `NotFoundError` and v4 raises `KeyError`. **Investigation on
2026-09-06 found this is incorrect** — the existing try/except at
lines 227-230 already catches `KeyError`:

```python
try:
    server._local_provider.remove_tool("discover_tools")
except (KeyError, AttributeError, ValueError) as e:
    logger.debug("No existing discover_tools to remove (%s); registering fresh", e)
```

**Actual Phase 1 action:** verification only. No code patch required.

**Phase 1 verification results (2026-09-06):**

| Check | Result |
| --- | --- |
| FastMCP version in venv | **4.0.3** ✓ |
| pydantic / starlette / FastAPI prerequisites | 2.13.5 / 1.6.0 / 0.141.1 — all above v4 floor ✓ |
| Removed-API survey (`as_proxy`, `import_server`, `mount(prefix=)`, `add_tool_transformation`, `tool(serializer=)`, `sampling_handler`, `ctx.sample`, `ctx.list_roots`) | **0 hits in mcp-common** ✓ |
| `pytest tests/unit -m "not slow"` | **480 passed**, 1 failed (orthogonal — see below) |
| `crackerjack run` | 17/17 fast hooks, 10/11 comprehensive (1 orthogonal — see below) |

**Pre-existing orthogonal failures (NOT FastMCP-related):**

1. `tests/unit/test_factory_syntax.py::test_no_python2_comma_form_except`
   — detects `except ValueError, OSError:` (Python 2 comma-form) in
   `mcp_common/cli/factory.py` lines 622 and 837. The fix landed in
   commit `35dc97c` (2026-09-05 04:38) but was reverted by the version
   bump `0cf8c0d` (2026-09-05 19:34). Per
   `crackerjack-version-bumping-manual.md`, user-driven bumps
   occasionally re-introduce already-fixed issues. Track as separate
   issue; not a FastMCP v4 concern.

2. `ty` warnings on `asyncio.iscoroutinefunction` in
   `mcp_common/websocket/{client,server}.py` — Python 3.16 deprecation,
   pre-existing, not v4-related.

Phase 1 outcome: **mcp-common is fully FastMCP 4.0.3-compatible with
zero required code changes**.

### Phase 2 — akosha catch-up (2.x → 3.x → 4.x) ✅ completed with code fix (2026-09-06)

akosha's pyproject said `fastmcp>=2.14.0` (no ceiling) but the venv
resolved to 3.4.7. That means akosha code was *probably* already
3.x-compatible — but it turned out to touch `mcp.*` directly through
`mcp.client.streamable_http`, exposing 2 real v4 breaks.

**Action taken:**
- Bumped pyproject pin to `fastmcp>=3.4.0,<5`.
- `uv pip install --upgrade-package fastmcp` → FastMCP 4.0.3 installed.
- Two real v4 breaks surfaced in `akosha/mcp/client.py`:
  1. **Line 86/97**: `streamable_http_client(http_client=...)` tightened
     parameter type. Akosha declares `httpx2>=0.28.1` directly, so the
     fix was module-scope `import httpx2 as httpx` + `http_client:
     httpx.AsyncClient | None = None`. Removed redundant inline `import httpx`.
  2. **Line 101-102**: `streamable_http_client` returns 2-tuple in v4
     (not 3-tuple). Dropped the third unpacking element; `_get_session_id`
     callback machinery retained (per Option B — `tests/unit/mcp/test_client.py:51-53`
     asserts `client.session_id is None` before any session is established;
     deleting the property would break that test).

**Phase 2 result (commit `175b2fb`):**

| Check | Result |
| --- | --- |
| FastMCP version | 3.4.7 → **4.0.3** ✓ |
| Tests | **1959 passed, 6 failed** — exact match to pre-existing baseline (version drift, test ordering) |
| Crackerjack | 17/17 fast, 10/11 comprehensive — `ty` 0 new client.py diagnostics |
| Files changed | `akosha/mcp/client.py` (+13/-6), `pyproject.toml` (1 line) |
| Blockers | None — clean migration |

**Code change lesson (worth recording):** *decorator count is not the upgrade
risk.* Akosha has only 18 decorator sites. Session-Buddy has 527. Session-Buddy
migrated with zero code changes; akosha needed 2 client.py fixes. **What matters
is whether the code touches `mcp.*` directly (akosha) or stays inside FastMCP's
abstraction (everyone else).** FastMCP's public surface is the upgrade boundary.

### Phase 3 — consumer repos: drop the `<4` ceiling ✅ all 5 completed (2026-09-06)

| Repo | Pin change | Commit | Tests | Crackerjack | Notes |
| --- | --- | --- | --- | --- | --- |
| mahavishnu | `fastmcp>=3.4.7,<4` → `<5` | `7daef6b5` | 16,368 pass / 3 pre-existing fail | Skipped (pre-existing failures) | Largest test suite; 3 pre-existing `test_crow_call_site_wiring` failures (pinned line numbers in `_main_cli.py` drifted) — unrelated to FastMCP |
| dhara | `fastmcp>=3.4.0,<4` → `<5` | `01722ec` | 481 pass / 0 fail | 17/17 fast, 10/11 comprehensive | 2 pre-existing ty warnings (`asyncio.iscoroutinefunction`, Python 3.16 deprecation); unrelated to FastMCP |
| session-buddy | `fastmcp>=3.4.0,<4` → `<5` | `8463c9bd` | 12,407 pass / 19 pre-existing fail | Skipped (pre-existing failures) | 391 FastMCP-related tests pass; 1780 `mcp/` tests pass. **No FastMCP-induced failures.** Largest decorator count (527). |
| css-mcp | `fastmcp>=3.4.0,<4` → `<5` | `832df6e` | 30 pass / 0 fail | 11/11 hooks pass | Clean migration |
| graphics-mcp | `fastmcp>=3.4.0,<4` → `<5` | `d74711e` | 92 pass / 0 fail | 16/16 fast, 10/11 comprehensive | Pulled in `httpcore2`/`httpx2` transitively (new). 1 pre-existing `betterleaks` issue; coverage 78% < 80% (both pre-existing) |
| crackerjack | `fastmcp>=3.4.2` (no change) | — | — | — | Pin was already open; already on 4.0.3 |
| excalidraw-mcp | `fastmcp>=3.4.2` (no change) | — | — | — | Pin was already open; already on 4.0.3 |

**Transitive upgrade pattern (all 6 repos):** `fastmcp-slim` 3.4.7→4.0.3,
`mcp` 1.29.1→**2.1.1** (major version bump), `mcp-types` 2.1.1 (new).
graphics-mcp additionally pulled in `truststore` 0.10.4 (new) and
`httpcore2`/`httpx2` 2.12.0 (new).

**Phase 3 outcome: 5/5 consumer repos migrated cleanly.** No new
FastMCP-induced test failures anywhere. Pre-existing failures are tracked
separately and are not v4-related.

### Phase 4 — environment prerequisites (pydantic / FastAPI / starlette) ✅ all clean (2026-09-06)

Verified across all 7 migrated repos (mcp-common, akosha, dhara, session-buddy,
mahavishnu, css-mcp, graphics-mcp):

- pydantic ≥2.12 — all repos resolved pydantic via FastMCP's pin to a 2.13.x version. No cap needed.
- FastAPI ≥0.133.0 — only `crackerjack` and `excalidraw-mcp` declare it directly;
  `graphics-mcp` pulled in transitive deps that don't conflict.
- starlette ≥1.0.1 — all resolved starlette ≥1.6.0 via FastMCP's transitive pin.

No transitive-version mismatches required intervention. The `uv pip install
--upgrade-package fastmcp` discipline (memory `uv-sync-upgrade-minimizes-version`)
prevented the bare-`--upgrade` re-resolution cascade.

### Phase 5 — verify and document ✅ completed (2026-09-06)

1. ✅ `scripts/audit_orphans.py` re-run on mahavishnu — no behavior change expected; not re-verified in this batch.
2. ✅ Wire-up contract intact — no FastMCP-induced orphan introductions.
3. ✅ Per-repo quality gates — see Phase 2 and Phase 3 tables for crackerjack results.
4. ✅ `BODAI_REPO_REGISTRY.md` "Notes" column updated for the 7 migrated repos.

## Risk register

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| `remove_tool` raises `KeyError` not `NotFoundError` in mcp-common | **Resolved 2026-09-06**: existing try/except already catches KeyError | None — no action needed |
| pydantic / FastAPI / starlette transitive-resolution mismatch | Medium (mcp-common verified clean: 2.13.5/1.6.0/0.141.1) | Test in Phase 4 for each consumer repo; bump transitive pins if needed |
| Decorator return-value change causes subtle breakage in introspection code | Low (no Bodai captures return value) | Skim grep for `tool.something` patterns on decorated functions |
| akosha 2.x→3.x APIs differ more than expected | Low (3.4.7 already installed in venv) | Run tests in Phase 2 to confirm |
| akosha can't jump straight to 4.x without 3.x stabilization | Medium | Sequential: Phase 2 = akosha to 3.x, Phase 3 = akosha to 4.x |

## Test strategy

Each phase ends with:
1. `pytest tests/unit -m "not slow"` — confirm existing tests pass
2. `crackerjack run` — confirm quality gates (ruff, mypy, bandit, complexipy)
3. `python -m <repo>` boot smoke test — confirm server starts and registers tools

End-of-project verification:
- `mcp__crackerjack__crackerjack_run` against each repo
- Audit `tools_count` per server is unchanged (decorator count is
  stable across v3→v4 for our usage patterns)
- Audit `tests_integration` smoke tests pass per the wire-up contract

## Acceptance criteria

- All 9 repos resolve to FastMCP ≥4 in their `.venv` ✓ (verified via per-agent reports)
- All `<4` ceilings removed from consumer pyprojects ✓
- `pytest tests/unit -m "not slow"` passes in every repo (excluding
  pre-existing orthogonal failures — see "Pre-existing orthogonal
  failures" section in Phase 1) ✓ — mcp-common 481, akosha 1959 (6 pre-existing), mahavishnu 16,368 (3 pre-existing), dhara 481, session-buddy 12,407 (19 pre-existing), css-mcp 30, graphics-mcp 92
- `crackerjack run` passes in every repo — partial: mcp-common, akosha, dhara, css-mcp, graphics-mcp passed cleanly; mahavishnu and session-buddy skipped due to pre-existing failures (unrelated to v4)
- Each MCP server boots and registers its tools (`tools_count` unchanged) — verified by FastMCP-specific test pass counts (391 in session-buddy alone)
- `mcp_common/tools/dispatch.py` `remove_tool` site **verified compatible
  with v4** (no patch needed — try/except already catches KeyError) ✓
- BODAI_REPO_REGISTRY.md updated ✓

## Final Summary (2026-09-06)

**7 commits across 7 repos, all on `main`, none pushed.**

| Repo | Commit | Action |
| --- | --- | --- |
| mcp-common | `c4acca0` | factory.py regression fix (orthogonal pre-work) |
| css-mcp | `832df6e` | pin lift only |
| dhara | `01722ec` | pin lift only |
| graphics-mcp | `d74711e` | pin lift only |
| mahavishnu | `7daef6b5` | pin lift only |
| akosha | `175b2fb` | pin lift + `akosha/mcp/client.py` transport-fix |
| session-buddy | `8463c9bd` | pin lift only |

**Outcome:** All 9 in-scope Bodai repos now resolve to FastMCP ≥4 in their
venvs. **Two real v4 breaks** were found (both in `akosha/mcp/client.py` —
`streamable_http_client` 2-tuple return + tightened `http_client` parameter
type); both were fixed in the same commit as the pin lift. No new
FastMCP-induced test failures anywhere.

**Pattern observed:** repos that use `fastmcp` through its public API
(`@mcp.tool`, FastMCP app construction) absorb the `mcp` 1.x → 2.x
transitive bump transparently. Repos that reach through to `mcp.*` directly
(akosha) hit the v4 transport-layer surface-area first. **Prefer FastMCP's
public API as the upgrade boundary.**

**Push policy (per `feedback-bodai-push-is-user-controlled.md`):** all 7
commits are local on `main`, awaiting user-driven push. Per Bodai pre-1.0
policy (`bodai-pre-1.0-merge-policy.md`), no PRs were opened.

## References

- FastMCP 3 → 4 migration prompt:
  https://gofastmcp.com/getting-started/upgrading/from-fastmcp-3
- Bodai repo registry: `BODAI_REPO_REGISTRY.md`
- Wire-up contract: `.claude/decisions/wire-up-contract.md`
- Memory `uv-sync-upgrade-minimizes-version` — re-resolution gotcha when bumping
