## Task 20 (W4.7): Adopt apply_tool_profile() in raindropio-mcp (Tier-A)

**CRITICAL BRIEF CORRECTION:** The plan listed raindropio-mcp as "0 tools (MANDATORY opt-out)". **That was stale reconnaissance.** The actual repo has **30 tools** registered through a custom `FastMCPToolRegistry` wrapper, NOT 0. The "MANDATORY opt-out" assumption is therefore invalid. Adopt the **standard pattern** with backend-lambda adapters (W3.1 lesson) to fit the custom registry.

This is the SEVENTH of 10 Tier-A repos. Tier-A trivial mapping: `MINIMAL=health, STANDARD/FULL=all`.

**Key facts about raindropio-mcp (verified in pre-flight):**

- Package: `raindropio_mcp/` (underscore)
- Main entrypoint: `server.py` — sync `create_app()` function
- Version: 0.3.1 (per pyproject.toml)
- **Custom registry wrapper**: `raindropio_mcp/tools/tool_registry.py` defines `FastMCPToolRegistry` which wraps `self._app.tool(name=..., description=...)(func)`. All 10 register fns in `raindropio_mcp/tools/*.py` take `(registry: FastMCPToolRegistry, client: RaindropClient)` — they DON'T take `(server, settings)`. **Backend-lambda adapter required** (W3.1 lesson).
- **30 actual tools** (count from `grep -cE "ToolMetadata\(" raindropio_mcp/tools/`):
  - account.py: 1, batch.py: 5, bookmarks.py: 6, collections.py: 5, filters.py: 2, highlights.py: 5, import_export.py: 2, system.py: 1, tags.py: 3
  - **Total: 30 ToolMetadata instantiations**
- **Lifespan already W4.3-compliant**: `server.py:64-67` — `finally: await client.close()` on a closure-captured `client`. **No change needed for W4.3.** Verify the regression test still passes after refactor.
- **`/health` already wired**: `server.py:53-57` — `register_http_health_route(app, service_name="raindropio", version=APP_VERSION)`. This stays as-is (always-on, doesn't gate by profile). For the MINIMAL MCP `health_check` tool, use `mcp_common.health.register_health_tools` in a new `register_health_tool` callable.
- **mcp-common dep**: already `mcp-common>=0.17.0`. **Bump to `>=0.18.0`** in pyproject.toml.

**Files:**

- Create: `raindropio_mcp/tools/profiles.py` (dispatch machinery)
- Modify: `raindropio_mcp/server.py` — add async `create_app_async(settings)` OR refactor `create_app` to call `apply_raindropio_tool_profile` before any registration
- Modify: `raindropio_mcp/pyproject.toml` — bump `mcp-common>=0.18.0`
- Create: `tests/unit/test_tool_profile.py`
- Modify: `raindropio_mcp/CLAUDE.md` (add "Tool Profile System" subsection)
- Create: `raindropio_mcp/docs/architecture/tool-profile-rationale.md`

**Standard corrections to apply to all W4 briefs:**

1. `git commit -c user.email=...` is WRONG. Correct: `git -c user.email=les@wedgwoodwebworks.com commit -m "..."`.
1. `crackerjack run --no-publish` doesn't exist — use plain `crackerjack run`. **Revert any version bump**.
1. `.claude/decisions/` is gitignored — put rationale at `docs/architecture/tool-profile-rationale.md`.
1. **W2b.3 lesson** (CRITICAL): production path uses `_apply_tool_profile` (async helper), NOT `apply_tool_profile` (sync wrapper). Add real production-path test.
1. **W2b.2 lesson**: sync `__init__.py` `__version__` to match `pyproject.toml` if they drift (use `importlib.metadata.version()`).
1. **W2b.1 lesson**: audit startup banners; gate behind `RAINDROPIO_TOOL_PROFILE in {"", "full"}` BEFORE the first commit.
1. **W3.2 round 1 fix lesson**: AST guard MUST structurally check for `ast.Await(value=ast.Call(...))`. MANDATORY_TOOLS opt-out justification must be accurate.
1. **W3.2 lesson**: extract `_GROUP_REGISTRY: list[tuple[str, str]]` constant.
1. **W4.1 CRITICAL lesson**: Follow explicit `MINIMAL=health, STANDARD/FULL=all` mapping. Thread caller-supplied `settings` through registration chain. Do NOT re-load from env. Add regression tests for both patterns.
1. **W4.3 CRITICAL lesson**: Lifespan finally block MUST close any clients constructed during dispatch. **(Already done — verify regression test still passes.)**

**NEW W4.7 lesson (this task)**: **MANDATORY opt-out assumption was wrong.** Plan's brief said "0 tools" — actually 30. Don't follow the plan's "MANDATORY opt-out" rationale; adopt the standard pattern with the W3.1 backend-lambda adapter.

**NEW W4.7 lesson**: Custom registry wrapper (`FastMCPToolRegistry`) means the 10 register fns don't match the `(server, settings)` contract. Wrap each in a backend-lambda adapter:

```python
def _register_collection_tools_via_registry(server, settings):
    """Backend adapter: closure over (registry, client)."""
    registry = FastMCPToolRegistry(server)
    client = build_raindrop_client(settings)
    register_collection_tools(registry, client)
```

Or hold `client` in the lifespan closure (W4.3 already does this — `app._raindrop_client`) and reuse it:

```python
def _register_collection_tools_via_registry(server, settings):
    registry = FastMCPToolRegistry(server)
    register_collection_tools(registry, server._raindrop_client)
```

**What this task does:**

raindropio-mcp: Tier-A trivial mapping per the plan: `MINIMAL=health, STANDARD/FULL=all`. Apply ToolProfile dispatch with the W3.1 backend-lambda adapter for the FastMCPToolRegistry wrapper:

1. **Pre-flight audit** (CRITICAL FIRST STEP):

   ```bash
   grep -rEn 'def register_|ToolMetadata\(' raindropio_mcp/tools/ | head -40
   grep -cE 'ToolMetadata\(' raindropio_mcp/tools/*.py
   ```

   Verify the actual count is 30 (NOT 0).

1. **CRITICAL (W4.1)**: extract a `register_health_tool(server, settings)` callable that registers ONLY the MCP `health_check` tool via `mcp_common.health.register_health_tools`. The existing `register_http_health_route` call stays in `create_app` (always-on, not part of the profile dispatch).

1. **CRITICAL (W4.3)**: lifespan already closes client via `await client.close()`. Verify the regression test exists (or add one) that the refactor doesn't break it.

1. Create `raindropio_mcp/tools/profiles.py` with:

   - `PROFILE_REGISTRATIONS`: 3-tier mapping. MINIMAL = `["health_tools"]`, STANDARD = FULL_REGISTRATIONS, FULL = ALL_TOOLS
   - `_GROUP_REGISTRY: list[tuple[str, str]]` constant (SSOT for group keys → register fn attr names)
   - `_build_registration_map(settings)` factory that wraps each `register_*_tools(registry, client)` in a backend-lambda adapter `(server) -> _register_via_registry(server, client)`
   - `register_all_tool_groups(server, settings)` that holds a single `client` and `FastMCPToolRegistry(server)` and calls every register fn
   - `apply_raindropio_tool_profile(server, settings)` wrapper that calls `await _apply_tool_profile(...)` with `essential_tool_names={"health_check"}`

1. Wire the dispatch in `server.py`. The cleanest approach:

   - Make `create_app` async (`async def create_app() -> FastMCP`) OR
   - Keep `create_app` sync and add a private `async def _setup_profile(app, settings)` called inside `create_app` via `_run_async_safely` (ThreadPoolExecutor bridge — W3.4 lesson)
   - **CRITICAL**: production path must use `_apply_tool_profile` (async). Verify with AST keystone test.

1. Set `essential_tool_names={"health_check"}` so the W0 helper's subset check enforces it at runtime.

1. Write tests covering:

   - AST keystone: `await apply_raindropio_tool_profile` in production path
   - MINIMAL profile registers `health_check` (and only that)
   - STD/FULL profiles register all 30 tools
   - Settings preservation: `get_settings()` not re-invoked inside dispatch
   - Lifespan regression: client still closed on shutdown (existing behavior preserved)
   - `_GROUP_REGISTRY` SSOT check
   - MANDATORY subset check

1. Write rationale doc + CLAUDE.md update

1. Run `uv run crackerjack run` to verify full lifecycle (revert any version bump)

1. Commit

**Report contract:**

Write your report to `/Users/les/Projects/mahavishnu/.superpowers/sdd/2026-08-18-mcp-tool-profile-adoption/task-20-report.md` with:

- Status: DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED
- Pre-flight verification output (the register grep + actual count)
- Commit SHAs
- Test summary
- Behavioral parity analysis (30 tools before → MINIMAL=1, STD/FULL=30+health after)
- Concerns
- Notes for the next W4 wave (synxis-pms-mcp)

Then return to me: status, commits, one-line test summary, concerns.

**Self-review before reporting:**

- Re-read your diff.
- **VERIFY MINIMAL REGISTRATION INCLUDES THE HEALTH TOOL** (W4.1 critical lesson).
- **VERIFY caller-supplied settings are preserved** (W4.1 critical lesson).
- **VERIFY LIFESPAN FINALLY STILL CLOSES CLIENT** (W4.3 critical lesson — already there, just don't break it).
- **VERIFY THE PRODUCTION PATH USES `_apply_tool_profile` (async) — NOT `apply_tool_profile` (sync)** (W2b.3 critical lesson).
- Verify all 10 register fns are wired into `_GROUP_REGISTRY`.
- Run `uv run pytest tests/ -v` and confirm all tests pass.
- Run `uv run crackerjack run` and REVERT any version bump.
- **Verify the AST guard would FAIL if `await` is removed**.
- Sync `__init__.py` version to pyproject.toml in the same commit (use `importlib.metadata.version()`).
- Avoid the W1.2/W1.3 Minor issues.

## Erratum: MANDATORY_GROUPS contradiction (post-implementation, 2026-08-19)

This brief is **internally inconsistent** on `MANDATORY_GROUPS`:

- This brief says MANDATORY_GROUPS "should be empty `set()` for trivial Tier-A"
  (under the W4.1 keystone framing — see item 9 above).
- The W4.1 keystone (`task-04-brief.md`) declared
  `RAINDROPIO_MANDATORY_GROUPS={"health_tools"}` for raindropio-mcp specifically
  (Tier-A trivial `MINIMAL=health`, STANDARD/FULL=all).

The W4.1 keystone value is the correct one. The implementer correctly followed
the keystone rather than this brief's prose: `raindropio_mcp/server.py:66`
ships `RAINDROPIO_MANDATORY_GROUPS: set[str] = {"health_tools"}`, and the
`apply_raindropio_tool_profile` wrapper passes `essential_tool_names={"health_check"}`
so the W0 helper's subset check enforces it at runtime. Task-20 report +
review both accepted this — no code change required.

Future W4 briefs: when adding per-repo specifics, prefer the W4.1 keystone as
the source of truth and override only on explicit Tier-B/Tier-C grounds.

**IMPORTANT TOKEN-PLAN NOTE:** A previous subagent (W3.2) was terminated by Token Plan rate limit (429) mid-execution. Be conscious of your token usage. raindropio-mcp scope is non-trivial (Tier-A with custom registry wrapper + 30 tools) but the implementation is templatized — should be quick if you stay focused.
