# Crackerjack C-WIRE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve six Crackerjack quality and wiring gaps identified in `docs/superpowers/specs/2026-08-03-bodai-openclaw-hermes-inspired-portfolio-design.md` §"C-WIRE", add per-task observability so each task reaches the `wired` state, and satisfy the portfolio's 5-field integration contract template at plan level.

**Architecture:** Five independent tasks (Tasks 1, 3, 5 ship first as small additive fixes; Tasks 2 and 4 ship last because they are contract changes, not additive fixes). Task 6 (C-ASYNC-DURABILITY) is gated on D-LOCK from the Dhara substrate and ships as Phase 1.5. Each task follows strict TDD and emits a metric/log line so a smoke command can prove the change took effect.

**Tech Stack:** Python 3.13, pytest 9.x, asyncio, Pydantic v2, mcp-common auth primitives, pathlib (Python 3.9+ `is_relative_to`), crackerjack existing test infrastructure.

## Global Constraints

Inherited from `crackerjack/CLAUDE.md` and `crackerjack/pyproject.toml`:

- `from __future__ import annotations` is **not** mandated by crackerjack's CLAUDE.md; omit unless a target file already imports it (the prior plan mandated it incorrectly — it is now removed). The remaining `crackerjack/**` files that start with `from __future__ import annotations` are following a local convention; new files may match or omit.
- Imports sorted within each section (stdlib → third-party → first-party, with `known-first-party = ["crackerjack"]`).
- Modern type syntax: `X | None` (not `Optional[X]`), `list[str]` (not `List[str]`), `pathlib.Path` for filesystem paths.
- No `assert` in production code (`crackerjack/**`). Use the `crackerjack/exceptions/` hierarchy. Enforced by bandit B101.
- All first-party imports use `from crackerjack.X import Y` form.
- Tests live under `/Users/les/Projects/crackerjack/tests/` mirroring package structure.
- Use existing pytest markers `unit`, `integration`; `asyncio_mode = "auto"` means no `@pytest.mark.asyncio` decorator.
- Per-test timeout ceiling is 300 s; mark slow tests with `@pytest.mark.slow`.
- Run commands from `/Users/les/Projects/crackerjack/`. Use `uv run pytest <path> -v`, `uv run ruff check <path>`, `uv run ruff format <path>`.

## Working Directory

Every task runs from `/Users/les/Projects/crackerjack/`. The plan file lives in the mahavishnu repo by authoring convention only.

## Plan-Level Integration Contract

Per `docs/superpowers/specs/2026-08-03-bodai-openclaw-hermes-inspired-portfolio-design.md` §"Integration contract (template)" the C-WIRE plan declares:

- **Triggered from:** any `crackerjack run` invocation, `crackerjack publish` flow, MCP `search_skills` tool call, WebSocket subscription request, security audit invocation.
- **Returns to / updates:** `SkillMetadata.success_rate` (per skill), `QualityGateReport.required_check_failures` (per gate), `HookPluginBase.metadata` (per plugin), WebSocket subscription allow-list, `SecurityAuditor.CRITICAL_HOOKS` lookup table, `crackerjack/skills_tracking.py::SessionBuddyMCPTracker.mcp_server_url` default.
- **Demonstrable by:** `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/skills/ tests/unit/mcp/tools/test_skill_tools.py tests/models/ tests/test_plugins_coverage.py tests/integration/test_skills_tracking.py tests/test_websocket_auth.py tests/test_security_audit.py -q` plus `curl :8686/metrics | grep -E 'crackerjack_skill_outcome|crackerjack_ws_subscribe|crackerjack_security_critical'` shows the new observability surface.
- **Rollback signal:** `crackerjack_skill_outcome_total{outcome="failure"}` rate climbing > 50 % post-rollout (suggests the new metric is double-counting or a regression); `crackerjack_security_critical` report count drops to zero (suggests the dict lookup silently regressed); manual rollback via `git revert` on the per-task commit.
- **Observability added (per task, listed in each task's "Observability added" section):** `crackerjack.skill.outcome{outcome}` counter (Task 1); `crackerjack.gate.required_check_failure{name}` counter (Task 2); `crackerjack.plugin.trust_check_failed{plugin_type}` counter (Task 3); `crackerjack.ws.subscribe.denied{channel,reason}` counter (Task 4); `crackerjack.security.critical_hooks{hook}` gauge size (Task 5). Task 6 (when unblocked) emits `crackerjack.async_task.persisted{task_id,status}` audit event.

## Dependency Graph Within This Plan

Tasks 1, 3, 5 are additive and can ship in any order; recommended order is 1 → 3 → 5. Tasks 2 and 4 are contract changes; ship after 1, 3, 5 to land additive fixes first. Task 6 is gated on D-LOCK.

```
Task 1 (C-SKILL-METRICS)   ─┐
Task 3 (C-PLUGIN-TRUST)     ─┼─ additive, ship first
Task 5 (C-HOOKS-LIST)       ─┘
                            ↓
Task 2 (C-OUTCOME-CONTRACT) ─┐ contract changes, ship last
Task 4 (C-WEBSOCKET-AUTH)   ─┘
                            ↓
                    D-LOCK ships
                            ↓
                Task 6 (C-ASYNC-DURABILITY)
```

---

### Task 1: Wire skill-metrics for failure/timeout + repair skill-tools kwarg (C-SKILL-METRICS)

Two defects in the skill-metrics path. The first affects every skill execution metric (failure/timeout never lower the success rate); the second raises `TypeError` from every MCP skill search.

**Files:**
- Modify: `crackerjack/skills/agent_skills.py:130, 142, 148, 218-224` (call sites + `_update_success_rate` body)
- Modify: `crackerjack/mcp/tools/skill_tools.py:180-188` (`_search_mcp_skills` call site)
- Test: `tests/unit/skills/test_agent_skills.py` (extend `TestAgentSkill`)
- Test: `tests/unit/mcp/tools/test_skill_tools.py` (new file — sibling of existing `test_git_metrics_mcp_tools.py`)

**Interfaces:**
- Consumes: `AgentSkill` (line 92 of `crackerjack/skills/agent_skills.py`); `AgentSkill.execute(issue, timeout)` returning `SkillExecutionResult` (lines 68-89); `MCPSkillRegistry.search_skills` (line 138 of `crackerjack/skills/mcp_skills.py`) accepting `search_tool_names`, `search_tags`, `search_descriptions`, `search_domains`.
- Produces: `_update_success_rate(self, outcome: str)` accepting `"success" | "failure" | "timeout"`, applying the EMA (`alpha = 0.1`) with score 1.0 for success and 0.0 otherwise; raises `ValueError` on unknown outcome.
- Produces: `_search_mcp_skills` calls `mcp_skills.search_skills(query, search_names=..., search_tags=..., search_descriptions=...)` without `TypeError`. The kwarg names are preserved (the `search_names` flag here is the local boolean, distinct from `MCPSkillRegistry.search_skills.search_tool_names`).
- Observability added: counter `crackerjack.skill.outcome{skill_name, outcome}` incremented once per `execute()` call (in each of the three branches).

- [ ] **Step 1: Write failing test for failure/timeout EMA**

Open `tests/unit/skills/test_agent_skills.py`. Locate `TestAgentSkill` (around line 142). Add:

```python
@pytest.mark.asyncio
async def test_execute_lowers_success_rate_on_timeout(self, monkeypatch) -> None:
    """Timeout path must lower skill.metadata.success_rate below 1.0."""
    from crackerjack.agents.base import AgentContext, Issue
    from crackerjack.skills.agent_skills import AgentSkill, SkillMetadata, SkillCategory
    from crackerjack.agents.base import IssueType

    md = SkillMetadata(
        name="timeout_skill",
        description="times out",
        category=SkillCategory.CODE_QUALITY,
        supported_types={IssueType.LINTING},
    )

    class SlowAgent:
        async def execute(self, issue):
            import asyncio
            await asyncio.sleep(10)
            return None
        async def can_handle(self, issue):
            return 0.9

    skill = AgentSkill(agent=SlowAgent(), metadata=md)
    issue = Issue(type=IssueType.LINTING, message="x", file_path="x.py")
    with pytest.raises(Exception):
        await skill.execute(issue, timeout=0)
    assert skill.metadata.success_rate < 1.0
```

Adjust the `Issue` constructor signature to match the real one in `crackerjack/agents/base.py` if it differs. The assertion `skill.metadata.success_rate < 1.0` is the contract under test.

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/skills/test_agent_skills.py::TestAgentSkill::test_execute_lowers_success_rate_on_timeout -v`
Expected: FAIL with `success_rate == 1.0` (current code never lowers it on TimeoutError).

- [ ] **Step 3: Add failing test for skill-tools `TypeError`**

Create `tests/unit/mcp/tools/test_skill_tools.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_search_mcp_skills_does_not_raise_typeerror() -> None:
    """_search_mcp_skills must not raise TypeError when calling search_skills."""
    from crackerjack.mcp.tools import skill_tools

    # Build a fake registry whose search_skills accepts **only** the known kwargs.
    fake_registry = MagicMock()
    fake_skill = MagicMock()
    fake_skill.to_dict.return_value = {"name": "x", "tags": [], "description": "x"}
    fake_registry.search_skills.return_value = [fake_skill]

    with patch.object(skill_tools, "_skill_registries", {"mcp_skills": fake_registry}):
        result = skill_tools._search_mcp_skills("query", "names")

    assert result == [{"name": "x", "tags": [], "description": "x"}]
    fake_registry.search_skills.assert_called_once()
```

The test asserts the call does not raise `TypeError`. Read `crackerjack/mcp/tools/skill_tools.py` to confirm `_search_mcp_skills` and `_skill_registries` exist and match this signature.

- [ ] **Step 4: Run the test and verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/mcp/tools/test_skill_tools.py::test_search_mcp_skills_does_not_raise_typeerror -v`
Expected: FAIL with `TypeError: search_skills() got an unexpected keyword argument 'search_names'`.

- [ ] **Step 5: Fix `_update_success_rate` and wire the failure/timeout branches**

Open `crackerjack/skills/agent_skills.py`. Three edits:

**Edit 5a** — change the method body at lines 218-224:

```python
def _update_success_rate(self, outcome: str) -> None:
    """Update the EMA success rate based on outcome.

    Args:
        outcome: One of "success", "failure", "timeout".
    """
    if outcome not in {"success", "failure", "timeout"}:
        msg = f"Unknown skill outcome: {outcome!r}"
        raise ValueError(msg)
    score = 1.0 if outcome == "success" else 0.0
    alpha = 0.1
    self.metadata.success_rate = (
        alpha * score + (1 - alpha) * self.metadata.success_rate
    )
```

**Edit 5b** — change line 130 from `self._update_success_rate(success)` to `self._update_success_rate("success")` (assuming `success` is the bool extracted on line 127; if `success` is False the new code will lower the rate — but the original code only reaches line 130 in the try-success path, so the bool is effectively always True here).

**Edit 5c** — add a call in each except branch:

In the `except TimeoutError` block (line 142-146), before the `_failure_result(...)` return:

```python
self.metadata.execution_count += 1
self._update_success_rate("timeout")
```

In the `except Exception as e` block (line 148-152), before the `_failure_result(...)` return:

```python
self.metadata.execution_count += 1
self._update_success_rate("failure")
```

Add the observability counter at each of the three branches. Find the crackerjack metrics emitter (search `crackerjack` for an OTel counter or a `prometheus_client.Counter` registration); if none exists, emit a structured log line via the module logger:

```python
logger.info(
    "skill.outcome",
    extra={"skill_name": self.metadata.name, "outcome": outcome},
)
```

Replace the literal `"timeout"` / `"failure"` / `"success"` strings with the corresponding outcome name. Do this in all three places.

- [ ] **Step 6: Fix the skill-tools kwarg mismatch**

Open `crackerjack/mcp/tools/skill_tools.py:180-188`. The current code calls:

```python
mcp_skills.search_skills(
    query,
    search_names=search_in in ("all", "names"),
    search_tags=search_in in ("all", "tags"),
    search_descriptions=search_in in ("all", "descriptions"),
)
```

But `MCPSkillRegistry.search_skills` (line 138 of `crackerjack/skills/mcp_skills.py`) only accepts `search_domains`, `search_tags`, `search_descriptions`, `search_tool_names`. The `search_names` kwarg is not declared and raises `TypeError`.

Two valid fixes; pick one and document the choice in the commit message:

**Option A (minimal)**: rename `search_names` to `search_tool_names` in the call site. Local flag is renamed to match the registry's parameter.

**Option B (broader)**: add `search_names` to `MCPSkillRegistry.search_skills` as an alias for `search_tool_names`. This requires editing `crackerjack/skills/mcp_skills.py:138-168`.

Pick Option A unless the implementer has a reason to add the alias. Update the test in Step 3 to assert the renamed kwarg (`fake_registry.search_skills.assert_called_once_with(query, search_tool_names=..., search_tags=..., search_descriptions=...)`).

- [ ] **Step 7: Re-run both tests and verify they pass**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/skills/test_agent_skills.py::TestAgentSkill::test_execute_lowers_success_rate_on_timeout tests/unit/mcp/tools/test_skill_tools.py::test_search_mcp_skills_does_not_raise_typeerror -v`
Expected: PASS, PASS.

- [ ] **Step 8: Run the broader skill + MCP test suites for regressions**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/skills/ tests/unit/mcp/ -q`
Expected: no new failures. Pre-existing failures are out of scope.

- [ ] **Step 9: Lint, format, commit**

```bash
cd /Users/les/Projects/crackerjack
uv run ruff check crackerjack/skills/agent_skills.py crackerjack/mcp/tools/skill_tools.py tests/unit/skills/test_agent_skills.py tests/unit/mcp/tools/test_skill_tools.py
uv run ruff format crackerjack/skills/agent_skills.py crackerjack/mcp/tools/skill_tools.py tests/unit/skills/test_agent_skills.py tests/unit/mcp/tools/test_skill_tools.py
git add crackerjack/skills/agent_skills.py crackerjack/mcp/tools/skill_tools.py tests/unit/skills/test_agent_skills.py tests/unit/mcp/tools/test_skill_tools.py
git commit -m "fix(skills): wire failure/timeout EMA + repair skill-tools kwarg

- _update_success_rate now takes an outcome (\"success\" | \"failure\"
  | \"timeout\"), applies the EMA on all three paths, and raises
  ValueError on unknown outcomes.
- The two except branches in AgentSkill.execute now bump
  execution_count and call _update_success_rate, so the success
  metric actually reflects reality.
- _search_mcp_skills passes search_tool_names (matching the registry
  signature), eliminating the TypeError raised on every MCP skill
  search through the agent-skills / hybrid paths.
- Adds structured log line skill.outcome for observability.

C-SKILL-METRICS from the Bodai OpenClaw/Hermes portfolio.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Crackerjack plugin-trust fixes (C-PLUGIN-TRUST)

Three trust defects. The assert in production code is a bandit B101 violation; the malformed URL and python-specifier are silent foot-guns; the `_get_test_status` placeholder is in the websocket server (covered in Task 4).

**Files:**
- Modify: `crackerjack/plugins/hooks.py:42` (replace `assert metadata.plugin_type == PluginType.HOOK` inside `HookPluginBase.__init__`)
- Modify: `crackerjack/plugins/base.py:26` (fix `requires_python` default)
- Modify: `crackerjack/integration/skills_tracking.py:253, 443` (fix `mcp_server_url` defaults; both occurrences)
- Create: `crackerjack/exceptions/plugin_trust_error.py` (new exception class)
- Modify: `crackerjack/exceptions/__init__.py` (re-export the new class)
- Modify: `tests/integration/test_skills_tracking.py` (update line 452 assertion that encodes the URL bug)
- Test: `tests/test_plugins_coverage.py` (extend existing — likely `TestPluginBase` or `TestPluginSecurity`)

**Interfaces:**
- Consumes: `HookPluginBase(PluginMetadata)` constructor (line 39-44 of `crackerjack/plugins/hooks.py`); `PluginMetadata.requires_python: str` (line 26 of `crackerjack/plugins/base.py`); `SessionBuddyMCPTracker(session_id, mcp_server_url)` (line 251-254 of `crackerjack/integration/skills_tracking.py`); `create_skills_tracker(session_id, ..., mcp_server_url)` (line 438-443 of same file).
- Produces: `HookPluginBase.__init__` raises `PluginTrustError` instead of asserting on wrong `plugin_type`.
- Produces: `PluginMetadata.requires_python` default is `"">=3.11"` (no spaces; valid PEP 440).
- Produces: Both URL defaults are `"http://localhost:8678"` (no space).
- Observability added: counter `crackerjack.plugin.trust_check_failed{plugin_type}` incremented each time `HookPluginBase.__init__` rejects a metadata.

- [ ] **Step 1: Add failing test for the plugin-trust assert**

Open `tests/test_plugins_coverage.py`. Locate `TestPluginSecurity` (around line 367). Add:

```python
def test_hook_plugin_base_rejects_wrong_plugin_type(self) -> None:
    from crackerjack.exceptions import PluginTrustError
    from crackerjack.plugins.base import PluginBase, PluginMetadata, PluginType
    from crackerjack.plugins.hooks import HookPluginBase

    md = PluginMetadata(
        name="bad",
        version="0.0.1",
        plugin_type=PluginType.TOOL,  # not HOOK
        description="not a hook",
    )

    class _Stub(HookPluginBase):
        def get_hook_definitions(self):  # pragma: no cover - not reached
            return []
        def execute_hook(self, *args, **kwargs):  # pragma: no cover - not reached
            return None

    with pytest.raises(PluginTrustError):
        _Stub(metadata=md)
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/test_plugins_coverage.py::TestPluginSecurity::test_hook_plugin_base_rejects_wrong_plugin_type -v`
Expected: FAIL with `ImportError` on `crackerjack.exceptions.PluginTrustError` (the class doesn't exist yet).

- [ ] **Step 3: Create `PluginTrustError`**

Create `crackerjack/exceptions/plugin_trust_error.py`:

```python
"""Raised when plugin metadata fails a trust check."""


class PluginTrustError(Exception):
    """Plugin metadata violated a trust invariant (e.g. wrong plugin_type for a HookPluginBase)."""
```

Modify `crackerjack/exceptions/__init__.py`:

```python
from .plugin_trust_error import PluginTrustError
from .tool_execution_error import ToolExecutionError

__all__ = ["PluginTrustError", "ToolExecutionError"]
```

- [ ] **Step 4: Replace the assert in `HookPluginBase.__init__`**

Open `crackerjack/plugins/hooks.py:40-44`. Replace:

```python
class HookPluginBase(PluginBase, abc.ABC):
    def __init__(self, metadata: PluginMetadata) -> None:
        super().__init__(metadata)
        assert metadata.plugin_type == PluginType.HOOK
        self.console: Console | None = None
        self.pkg_path: Path | None = None
```

with:

```python
from crackerjack.exceptions import PluginTrustError

class HookPluginBase(PluginBase, abc.ABC):
    def __init__(self, metadata: PluginMetadata) -> None:
        super().__init__(metadata)
        if metadata.plugin_type != PluginType.HOOK:
            logger.warning(
                "plugin.trust_check_failed",
                extra={"plugin_type": str(metadata.plugin_type)},
            )
            msg = (
                f"HookPluginBase requires PluginType.HOOK, got "
                f"{metadata.plugin_type!r}"
            )
            raise PluginTrustError(msg)
        self.console: Console | None = None
        self.pkg_path: Path | None = None
```

Add the observability log line at the rejection site. If the module already has a `logger` from the top of `hooks.py`, reuse it; otherwise add `logger = logging.getLogger(__name__)` to the top of the file. Place the import for `PluginTrustError` near the top of `hooks.py` with the other imports.

- [ ] **Step 5: Re-run the failing test and verify it passes**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/test_plugins_coverage.py::TestPluginSecurity::test_hook_plugin_base_rejects_wrong_plugin_type -v`
Expected: PASS.

- [ ] **Step 6: Fix `requires_python` and the two URL defaults**

Open `crackerjack/plugins/base.py:26`. Change:

```python
requires_python: str = "> = 3.11"
```

to:

```python
requires_python: str = "">=3.11"
```

(No spaces inside `>=`. This is a valid PEP 440 specifier.)

Open `crackerjack/integration/skills_tracking.py`. Make two edits:

**Edit 6a** at line 253: change `"http://localhost: 8678"` → `"http://localhost:8678"`.

**Edit 6b** at line 443: change `"http://localhost: 8678"` → `"http://localhost:8678"`.

- [ ] **Step 7: Update the test that encodes the URL bug**

Open `tests/integration/test_skills_tracking.py:452` (per the security review). Locate the line `assert settings.mcp_server_url == "http://localhost: 8678"` (or similar — read the file to confirm the exact assertion). Change the literal to `"http://localhost:8678"`.

Search the file for any other occurrences of the malformed URL string and update them. Search the whole crackerjack repo for `"http://localhost: 8678"` and fix all hits in one commit:

Run: `cd /Users/les/Projects/crackerjack && grep -rn '"http://localhost: 8678"' --include='*.py'`
Expected: at minimum the two known sites and possibly a test fixture or two. Fix all of them.

- [ ] **Step 8: Run plugin + integration test suites**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/test_plugins_coverage.py tests/integration/test_skills_tracking.py -q`
Expected: no new failures. Pre-existing failures are out of scope.

- [ ] **Step 9: Lint, format, commit**

```bash
cd /Users/les/Projects/crackerjack
uv run ruff check crackerjack/plugins/hooks.py crackerjack/plugins/base.py crackerjack/integration/skills_tracking.py crackerjack/exceptions/ tests/test_plugins_coverage.py tests/integration/test_skills_tracking.py
uv run ruff format crackerjack/plugins/hooks.py crackerjack/plugins/base.py crackerjack/integration/skills_tracking.py crackerjack/exceptions/ tests/test_plugins_coverage.py tests/integration/test_skills_tracking.py
git add crackerjack/plugins/hooks.py crackerjack/plugins/base.py crackerjack/integration/skills_tracking.py crackerjack/exceptions/ tests/test_plugins_coverage.py tests/integration/test_skills_tracking.py
git commit -m "fix(plugins): trust invariants + URL and python-spec defaults

- HookPluginBase.__init__ now raises PluginTrustError (new class in
  crackerjack/exceptions/) instead of asserting; bandit B101 violation
  removed.
- PluginMetadata.requires_python default corrected to '>=3.11'
  (PEP 440 valid; previous literal '> = 3.11' had whitespace inside
  the operator and was invalid).
- SessionBuddyMCPTracker.mcp_server_url and create_skills_tracker
  default both fixed to 'http://localhost:8678' (no space). The
  malformed URL silently propagated through every backend='auto'
  call.
- Tests that previously encoded the URL bug are updated to the
  no-space form.

C-PLUGIN-TRUST from the Bodai OpenClaw/Hermes portfolio.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Expand SecurityAuditor.CRITICAL_HOOKS (C-HOOKS-LIST)

`SecurityAuditor.CRITICAL_HOOKS` is a `dict[str, str]` mapping hook name → human reason. Adding entries (not converting to a frozenset) extends the security-critical set. The new hook names must be lowercase since `_get_hook_security_level` does case-insensitive lookup.

**Files:**
- Modify: `crackerjack/security/audit.py:44-48` (extend the dict)
- Test: `tests/test_security_audit.py` (extend existing)

**Interfaces:**
- Consumes: existing `SecurityAuditor.CRITICAL_HOOKS` consumer at line 131 (`_get_hook_security_level`) and line 152 (`_generate_security_warnings`).
- Produces: `CRITICAL_HOOKS` includes `bandit`, `pyright`, `gitleaks` (existing), plus `semgrep` (static analysis) and a secrets scanner. Pick the scanner that exists in `crackerjack/hooks/`; if none, add `trufflehog` as the planned scanner and document the wiring gap.
- Observability added: gauge `crackerjack.security.critical_hooks` set to `len(CRITICAL_HOOKS)` after audit runs (read by operators to confirm the allow-list size).

- [ ] **Step 1: Inspect existing hook names**

Run: `cd /Users/les/Projects/crackerjack && ls crackerjack/hooks/ && grep -rn "HookDefinition\|HookStage\|stage=" crackerjack/hooks/ crackerjack/config/hooks.py 2>&1 | head -20`
Expected: identifies which hook names actually appear as registered hooks. If `semgrep` or a secrets scanner (trufflehog, gitleaks) does NOT exist as a hook, the audit still benefits from the entry — the dict lookup at line 131 won't promote an unknown hook, but the entry is in place for when the hook is wired.

- [ ] **Step 2: Add failing test**

Open `tests/test_security_audit.py`. Locate any test that asserts `CRITICAL_HOOKS` membership. Add:

```python
def test_critical_hooks_includes_semgrep_and_secrets_scanner(self) -> None:
    from crackerjack.security.audit import SecurityAuditor

    expected = {"bandit", "pyright", "gitleaks", "semgrep"}
    assert expected.issubset(SecurityAuditor.CRITICAL_HOOKS.keys())
```

If `trufflehog` (or another secrets scanner) exists as a real hook, add it to `expected` as well. If no secrets scanner is wired, document this in the test's docstring as a known gap.

- [ ] **Step 3: Run the test and verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/test_security_audit.py::test_critical_hooks_includes_semgrep_and_secrets_scanner -v`
Expected: FAIL with the missing-key assertion.

- [ ] **Step 4: Extend `CRITICAL_HOOKS` (preserving dict shape)**

Open `crackerjack/security/audit.py:44-48`. Extend the dict:

```python
CRITICAL_HOOKS = {
    "bandit": "Security vulnerability detection (OWASP A09)",
    "pyright": "Type safety prevents runtime security holes (OWASP A04)",
    "gitleaks": "Secret/credential detection (OWASP A07)",
    "semgrep": "Multi-language static analysis for security patterns (OWASP A03/A05)",
    # TODO: wire trufflehog or betterleaks as a real hook; entry added
    # so the lookup at line 131 promotes it once the hook is registered.
    "trufflehog": "Secret/credential scanning against git history (OWASP A07)",
}
```

Replace `trufflehog` with whatever scanner the implementer confirmed in Step 1 (or omit if it would create a phantom entry without a follow-up plan).

Do NOT convert to a frozenset — line 152 calls `.get()` on it.

- [ ] **Step 5: Re-run tests and verify they pass**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/test_security_audit.py -v`
Expected: PASS plus any pre-existing tests still passing.

- [ ] **Step 6: Lint, format, commit**

```bash
cd /Users/les/Projects/crackerjack
uv run ruff check crackerjack/security/audit.py tests/test_security_audit.py
uv run ruff format crackerjack/security/audit.py tests/test_security_audit.py
git add crackerjack/security/audit.py tests/test_security_audit.py
git commit -m "fix(security): add semgrep and secrets-scanner to CRITICAL_HOOKS

Extend SecurityAuditor.CRITICAL_HOOKS with semgrep (static
analysis) and trufflehog (secret scanning) so the line-131 lookup
flags them as SecurityLevel.CRITICAL once the hooks are wired.
Dict shape preserved (line 152 uses .get()).

C-HOOKS-LIST from the Bodai OpenClaw/Hermes portfolio.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Complete QualityGateReport outcome contract (C-OUTCOME-CONTRACT) — CONTRACT CHANGE

`QualityGateReport.passed` (line 270) returns `self.fast_hooks and self.tests and self.comprehensive`. It ignores `self.checks` entirely. The intended contract per the portfolio spec is that REQUIRED-severity check failures also drive the gate. This is a contract change — ship after Tasks 1, 3, 5 land.

The minimal-risk approach: keep `passed` and `blocking_failure` semantics unchanged (callers depend on them). Add a NEW severity-aware computed field that surfaces the gap. Wire it through `to_dict()` for downstream consumers.

**Files:**
- Modify: `crackerjack/models/validation_contracts.py` (add `required_check_failures` property + thread it through `to_dict()`)
- Test: `tests/models/test_validation_contracts.py` (extend existing)

**Interfaces:**
- Consumes: `QualityGateReport` at line 254; `QualityGateCheck` at line 190; `GateSeverity` enum (REQUIRED / WARNING / OPTIONAL).
- Produces: `QualityGateReport.required_check_failures: list[str]` — names of all `REQUIRED`-severity checks where `passed is False`. Empty list when all REQUIRED checks pass.
- Produces: `to_dict()` includes the new field under key `required_check_failures`.
- Observability added: counter `crackerjack.gate.required_check_failure{name}` incremented once per failed REQUIRED check at report-creation time.

- [ ] **Step 1: Add failing test**

Open `tests/models/test_validation_contracts.py`. Add:

```python
def test_required_check_failures_lists_failed_required(self) -> None:
    from crackerjack.models.validation_contracts import (
        GateSeverity,
        QualityGateCheck,
        QualityGateReport,
    )

    failing = QualityGateCheck(
        name="lint.required",
        passed=False,
        severity=GateSeverity.REQUIRED,
    )
    warning = QualityGateCheck(
        name="lint.warning",
        passed=False,
        severity=GateSeverity.WARNING,
    )
    report = QualityGateReport(
        fast_hooks=True,
        tests=True,
        comprehensive=True,
        coverage=1.0,
        checks=[failing, warning],
    )

    assert report.required_check_failures == ["lint.required"]
    assert "required_check_failures" in report.to_dict()
```

If the test fails with `AttributeError: 'QualityGateReport' object has no attribute 'required_check_failures'`, that is the expected pre-fix failure.

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/models/test_validation_contracts.py::test_required_check_failures_lists_failed_required -v`
Expected: FAIL with `AttributeError` on `required_check_failures`.

- [ ] **Step 3: Add the new property and dict field**

Open `crackerjack/models/validation_contracts.py`. Add a property to `QualityGateReport` (after the `warnings` property at line 282-287):

```python
@property
def required_check_failures(self) -> list[str]:
    """Names of REQUIRED-severity checks that did not pass.

    This is additive to ``passed`` / ``blocking_failure``: it surfaces
    severity-aware failure information without changing the existing
    boolean contract consumed by ``from_result`` callers.
    """
    return [
        check.name
        for check in self.checks
        if not check.passed and check.severity == GateSeverity.REQUIRED
    ]
```

In `to_dict()` (line 289-295), add the new field:

```python
def to_dict(self) -> dict[str, t.Any]:
    data = self.model_dump(mode="json")
    data["passed"] = self.passed
    data["all_passed"] = self.all_passed
    data["blocking_failure"] = self.blocking_failure
    data["warnings"] = self.warnings
    data["required_check_failures"] = self.required_check_failures
    return data
```

- [ ] **Step 4: Add the observability counter**

Find crackerjack's metric emitter (search `crackerjack` for `prometheus_client.Counter` or a custom emitter; if neither exists, emit a structured log via `logging.getLogger(__name__)`). In `QualityGateReport.from_result` (line 297+) — or wherever the report is constructed from incoming data — emit the counter per failed REQUIRED check.

If no metric emitter exists, add this logger line to the `to_dict()` method:

```python
import logging
logger = logging.getLogger(__name__)
# inside to_dict(), after computing required_check_failures:
for name in self.required_check_failures:
    logger.warning(
        "gate.required_check_failure",
        extra={"check_name": name, "report_id": str(id(self))},
    )
```

If a metric emitter does exist (Prometheus client, OpenTelemetry), use it instead of `logger.warning`.

- [ ] **Step 5: Re-run tests and verify they pass**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/models/test_validation_contracts.py -v`
Expected: PASS plus any pre-existing tests still passing.

- [ ] **Step 6: Run the broader crackerjack test suite for regressions**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/models/ tests/test_websocket_auth.py tests/unit/mcp/ tests/mcp/ -q`
Expected: no new failures. Pre-existing failures are out of scope.

- [ ] **Step 7: Lint, format, commit**

```bash
cd /Users/les/Projects/crackerjack
uv run ruff check crackerjack/models/validation_contracts.py tests/models/test_validation_contracts.py
uv run ruff format crackerjack/models/validation_contracts.py tests/models/test_validation_contracts.py
git add crackerjack/models/validation_contracts.py tests/models/test_validation_contracts.py
git commit -m "fix(contracts): surface REQUIRED-check failures on QualityGateReport

Adds QualityGateReport.required_check_failures (list[str]) that
walks self.checks for REQUIRED-severity failures and exposes them
through to_dict(). Existing passed / blocking_failure semantics
preserved (callers depend on them); the new field is additive.

Wired through with a structured log line per failed check so
operators can detect severity-aware gate failures via grep /
metrics.

C-OUTCOME-CONTRACT from the Bodai OpenClaw/Hermes portfolio.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: WebSocket subscription auth normalize + test-status placeholder (C-WEBSOCKET-AUTH) — CONTRACT CHANGE

`_can_subscribe_to_channel` (line 167-188 of `crackerjack/websocket/server.py`) normalizes `"crackerjack: read"` → `"crackerjack:read"` then compares to the literal `"crackerjack: read"` (with space), so legitimate users with `"crackerjack: read"` get `FORBIDDEN`. Also fixes the `_get_test_status` placeholder that hardcodes a "running" dict.

**Files:**
- Modify: `crackerjack/websocket/server.py:167-188` (fix the comparison literal)
- Modify: `crackerjack/websocket/server.py:190-201` (replace the placeholder with a real lookup or honest stub)
- Test: `tests/test_websocket_auth.py` (extend `TestChannelAuthorization`)

**Interfaces:**
- Consumes: `CrackerjackWebSocketServer._can_subscribe_to_channel(self, user, channel)` (line 167); `_get_test_status(self, run_id)` (line 190).
- Produces: `_can_subscribe_to_channel` returns `True` when the user's permission set (after normalization) contains the channel-required permission — for both `"crackerjack: read"` (legacy space form) and `"crackerjack:read"` (canonical).
- Produces: `_get_test_status` either (a) delegates to `self.qc_manager` if available, or (b) returns `{"status": "unknown", "run_id": run_id}` and logs a structured warning that the test-status integration is pending C-ASYNC-DURABILITY (Task 6).
- Observability added: counter `crackerjack.ws.subscribe.denied{channel, reason}` incremented on `FORBIDDEN` reply.

- [ ] **Step 1: Add failing test for the WS permission normalize**

Open `tests/test_websocket_auth.py`. Locate `TestChannelAuthorization` (around line 195). Update the existing buggy test (line 198) so it asserts `True` for both forms, and add a fresh test:

```python
def test_can_subscribe_with_space_separated_permission(self) -> None:
    """'crackerjack: read' (legacy space form) must subscribe to quality:*."""
    from unittest.mock import MagicMock
    from crackerjack.websocket.server import CrackerjackWebSocketServer

    server = CrackerjackWebSocketServer(qc_manager=MagicMock())
    user = {"permissions": ["crackerjack: read"]}
    assert server._can_subscribe_to_channel(user, "quality:lint") is True


def test_can_subscribe_with_canonical_no_space_permission(self) -> None:
    from unittest.mock import MagicMock
    from crackerjack.websocket.server import CrackerjackWebSocketServer

    server = CrackerjackWebSocketServer(qc_manager=MagicMock())
    user = {"permissions": ["crackerjack:read"]}
    assert server._can_subscribe_to_channel(user, "quality:lint") is True
```

Update the existing buggy test at line 198 (which asserts `False` for `"crackerjack: read"`) to assert `True` so the suite captures the new contract. The two new tests exercise both forms; the existing test should agree with the new contract.

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/test_websocket_auth.py::TestChannelAuthorization::test_can_subscribe_with_space_separated_permission tests/test_websocket_auth.py::TestChannelAuthorization::test_can_subscribe_with_canonical_no_space_permission -v`
Expected: `test_can_subscribe_with_space_separated_permission` FAILS (the bug); `test_can_subscribe_with_canonical_no_space_permission` passes (this is the no-space form which currently matches because the literal happens to collide after normalization is unchanged — verify, and adjust the test if needed).

- [ ] **Step 3: Fix the comparison literals**

Open `crackerjack/websocket/server.py:167-188`. Change the comparison literals from `"crackerjack: read"` (with space) to `"crackerjack:read"` (no space), to match the post-normalization form produced by line 169's `.replace(" ", ":")`:

```python
def _can_subscribe_to_channel(self, user: dict[str, Any], channel: str) -> bool:
    permissions = {
        str(permission).strip().lower().replace(" ", ":")
        for permission in user.get("permissions", [])
    }

    if "admin" in permissions or "crackerjack:admin" in permissions:
        return True

    if channel.startswith("quality:"):
        return (
            "crackerjack:read" in permissions
            or "crackerjack:admin" in permissions
        )

    if channel.startswith("test:"):
        return (
            "crackerjack:read" in permissions
            or "crackerjack:admin" in permissions
        )

    return False
```

Note: also fixed `"crackerjack: admin"` → `"crackerjack:admin"` for the admin shortcut (same bug).

- [ ] **Step 4: Add the observability counter on `FORBIDDEN`**

In `_handle_request` (line 103-161), the existing code sends a `FORBIDDEN` error when `_can_subscribe_to_channel` returns `False`. Add an emit before the error is sent. Find crackerjack's metric emitter (Prometheus client, OpenTelemetry, or fall back to a structured logger line):

If a `crackerjack.ws.subscribe.denied` counter exists, increment it with `{channel: str(channel)}` label. Otherwise:

```python
logger.warning(
    "ws.subscribe.denied",
    extra={"channel": str(channel), "user_id": user.get("user_id") if user else "anonymous"},
)
```

Add this line at the rejection site (just before the `WebSocketProtocol.create_error(...)` call).

- [ ] **Step 5: Re-run tests and verify they pass**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/test_websocket_auth.py -v`
Expected: PASS plus any pre-existing tests still passing.

- [ ] **Step 6: Replace the `_get_test_status` placeholder**

Open `crackerjack/websocket/server.py:190-201`. Replace the hardcoded dict with either:

**Option A (preferred — wires to qc_manager):**

```python
async def _get_test_status(self, run_id: str) -> dict[str, t.Any]:
    """Look up the test status for ``run_id`` via the quality-control manager.

    Returns the qc_manager's response if it exposes a usable interface;
    otherwise returns an honest ``unknown`` stub with a structured log
    warning. The full integration is pending C-ASYNC-DURABILITY
    (Bodai portfolio Task 6).
    """
    if self.qc_manager is None:
        logger.warning("ws.test_status.no_qc_manager run_id=%s", run_id)
        return {"run_id": run_id, "status": "unknown"}

    for attr in ("get_test_status", "test_status", "run_status"):
        getter = getattr(self.qc_manager, attr, None)
        if getter is None:
            continue
        value = getter(run_id) if callable(getter) else getter
        if inspect.isawaitable(value):
            value = await value
        if isinstance(value, dict):
            return value

    logger.warning("ws.test_status.qc_manager_no_getter run_id=%s", run_id)
    return {"run_id": run_id, "status": "unknown"}
```

**Option B (minimal — honest stub):**

```python
async def _get_test_status(self, run_id: str) -> dict[str, t.Any]:
    """Honest stub: returns 'unknown' until C-ASYNC-DURABILITY (Bodai portfolio Task 6) ships."""
    logger.warning("ws.test_status.not_implemented run_id=%s", run_id)
    return {"run_id": run_id, "status": "unknown"}
```

Pick Option A if `qc_manager` exposes any test-status method; otherwise Option B.

- [ ] **Step 7: Lint, format, commit**

```bash
cd /Users/les/Projects/crackerjack
uv run ruff check crackerjack/websocket/server.py tests/test_websocket_auth.py
uv run ruff format crackerjack/websocket/server.py tests/test_websocket_auth.py
git add crackerjack/websocket/server.py tests/test_websocket_auth.py
git commit -m "fix(websocket): canonicalize subscription permission + honest test-status stub

- _can_subscribe_to_channel compares against 'crackerjack:read' and
  'crackerjack:admin' (post-normalization form) instead of the
  legacy 'crackerjack: read' / 'crackerjack: admin' literals, so
  'crackerjack: read' users get subscribed to quality:*/test:*
  channels as the policy intends.
- _get_test_status returns an honest 'unknown' (Option B) or
  delegates to qc_manager (Option A) instead of the hardcoded
  'running' dict that misled callers into believing a run was
  in flight.
- Adds structured log lines ws.subscribe.denied and (if Option B)
  ws.test_status.not_implemented for observability.

C-WEBSOCKET-AUTH from the Bodai OpenClaw/Hermes portfolio.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Persist AsyncTaskManager jobs (C-ASYNC-DURABILITY) — Phase 1.5, GATED ON D-LOCK

**Do not start this task** until `D-LOCK` from `docs/superpowers/specs/2026-08-03-bodai-openclaw-hermes-inspired-portfolio-design.md` §"Layer 0" has shipped into the Dhara substrate and is consumable from crackerjack. Verified: line 37 of `crackerjack/mcp/task_manager.py` is `self._cleanup_task = asyncio.create_task(self._cleanup_loop())` — the gating claim is accurate.

When unblocked, write a follow-up plan that:

- Imports `dhara.lock.DharaLock` (or whatever the agreed API is; reconfirm at plan time).
- Replaces the cleanup-loop `_cleanup_task` with a DharaLock-guarded equivalent.
- Persists `task_id → status` to Dhara so a restart resumes from the last persisted state.
- Surfaces a `result_store` MCP tool returning the persisted result for a given `task_id`.
- Defines a `reap_zombies` task keyed on the lock TTL.

Integration contract for the follow-up plan:

- **Triggered from:** `crackerjack mcp` restart, `reap_zombies` cron (TBD), and every `AsyncTaskManager.create_task` invocation.
- **Returns to / updates:** Dhara key `crackerjack/async-tasks/{task_id}` storing `{status, started_at, finished_at, result_payload}`.
- **Demonstrable by:** restart the MCP server mid-task, observe the task resume with the same `task_id`; `pytest tests/mcp/test_task_manager.py::test_restart_resumes_task -v` passes.
- **Rollback signal:** `crackerjack.async_tasks.resumed == 0` after a restart that should have resumed at least one task.
- **Observability added:** audit event `crackerjack.async_task.persisted` with `task_id + status + age_ms`.

Skip this task in the current round.
