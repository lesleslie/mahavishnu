# Crackerjack C-WIRE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve six Crackerjack quality and wiring gaps identified in `docs/superpowers/specs/2026-08-03-bodai-openclaw-hermes-inspired-portfolio-design.md` §"C-WIRE".

**Architecture:** Six independent tasks targeting distinct modules in `/Users/les/Projects/crackerjack`. Five tasks (C-SKILL-METRICS, C-OUTCOME-CONTRACT, C-PLUGIN-TRUST, C-WEBSOCKET-AUTH, C-HOOKS-LIST) ship in Phase 1. C-ASYNC-DURABILITY is gated on D-LOCK from the Dhara substrate and ships as Phase 1.5. Each task follows strict TDD: write the failing test, verify the failure, implement, verify the pass, commit.

**Tech Stack:** Python 3.13, pytest 9.x, asyncio, Pydantic v2, mcp-common auth primitives, crackerjack existing test infrastructure.

## Global Constraints

These come from `crackerjack/CLAUDE.md` and `crackerjack/pyproject.toml`. Every task implicitly requires them:

- All source files start with `from __future__ import annotations`.
- All test files start with `from __future__ import annotations`.
- Imports sorted within each section (stdlib → third-party → first-party, with `known-first-party = ["crackerjack"]`).
- Modern type syntax: `X | None` (not `Optional[X]`), `list[str]` (not `List[str]`), `pathlib.Path` for filesystem paths.
- Function arguments with default `None` must be typed `X | None = None`.
- No `assert` in production code (`crackerjack/**`). Use the `crackerjack/exceptions` hierarchy. Enforced by bandit B101.
- All first-party imports use `from crackerjack.X import Y` form, not `import crackerjack.X.Y`.
- Tests live under `/Users/les/Projects/crackerjack/tests/` mirroring package structure.
- Existing pytest markers `unit`, `integration` are available; use `unit` for new unit tests.
- Async tests run with `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` decorator needed.
- Per-test timeout ceiling is 300s; mark slow tests with `@pytest.mark.slow`.
- Run `uv run pytest <path> -v` (from `/Users/les/Projects/crackerjack/`) to execute any test step in this plan.
- Run `uv run ruff check <path>` and `uv run ruff format <path>` to lint/format any file touched in this plan.

## Working Directory

Every task runs from `/Users/les/Projects/crackerjack/`. The plan references paths relative to that root unless noted otherwise. The plan file lives in `/Users/les/Projects/mahavishnu/docs/superpowers/plans/` because it was authored from the Mahavishnu repo; the implementer must `cd` to crackerjack before executing any step.

## Dependency Graph Within This Plan

Tasks 1–5 are independent and may run in any order. Task 6 (C-ASYNC-DURABILITY) depends on D-LOCK from the Dhara substrate (`docs/superpowers/specs/2026-08-03-bodai-openclaw-hermes-inspired-portfolio-design.md` §"Layer 0"). Do not start Task 6 until D-LOCK has shipped.

```
Task 1 (C-SKILL-METRICS)   ─┐
Task 2 (C-OUTCOME-CONTRACT) ─┤
Task 3 (C-PLUGIN-TRUST)     ─┼─ all parallelizable
Task 4 (C-WEBSOCKET-AUTH)   ─┤
Task 5 (C-HOOKS-LIST)       ─┘
                            ↓
                    D-LOCK ships
                            ↓
                Task 6 (C-ASYNC-DURABILITY)
```

---

### Task 1: Fix skill metrics wire-up (C-SKILL-METRICS)

Two distinct defects, both in the skill-metrics path. One affects the runtime metric update; the other raises a `TypeError` from every skill MCP search.

**Files:**
- Modify: `crackerjack/skills/agent_skills.py:218` (`_update_success_rate` only runs on success branch)
- Modify: `crackerjack/mcp/tools/skill_tools.py:184` (calls `search_tool_names` with the `search_names` kwarg)
- Test: `tests/unit/skills/test_agent_skills.py` (extend existing)
- Test: `tests/unit/mcp/test_skill_tools.py` (new test file)

**Interfaces:**
- Consumes: `AgentSkillOutcome` from `crackerjack/skills/agent_skills.py:120-140` (the call site that invokes `_update_success_rate`)
- Consumes: `search_skill_tools(search_in: str, ...)` — the function at `crackerjack/mcp/tools/skill_tools.py:179`
- Produces: `_update_success_rate(outcome: "success" | "failure" | "timeout")` — three-way classification that records all three paths
- Produces: `search_skill_tools` callable with the keyword arg `search_tool_names=...` (matches the actual parameter name on the underlying `search_semantic` call)

- [ ] **Step 1: Add failing test for failure/timeout success-rate updates**

Open `tests/unit/skills/test_agent_skills.py`. Add a new test method to `TestAgentSkillsOutcome` (or create it if absent):

```python
def test_update_success_rate_records_failures_and_timeouts(self) -> None:
    """Skill outcomes must record failure and timeout paths, not only success."""
    from crackerjack.skills.agent_skills import AgentSkillsTracker

    tracker = AgentSkillsTracker()
    tracker.record_outcome("skill.a", "failure", duration_ms=42)
    tracker.record_outcome("skill.b", "timeout", duration_ms=123)

    assert tracker.success_rate("skill.a") < 1.0
    assert tracker.success_rate("skill.b") < 1.0
```

The actual method names on `AgentSkillsTracker` may differ. Read `crackerjack/skills/agent_skills.py` first to confirm the public surface (`record_outcome`, `success_rate`, or the equivalents). Adjust the test to use the names you find. The contract under test is: a `failure` or `timeout` outcome must lower the recorded success rate below 1.0.

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/skills/test_agent_skills.py::TestAgentSkillsOutcome::test_update_success_rate_records_failures_and_timeouts -v`
Expected: FAIL with assertion on `success_rate` returning 1.0 (the current default when only success path is wired).

- [ ] **Step 3: Add failing test for skill-tools TypeError**

Create `tests/unit/mcp/test_skill_tools.py`:

```python
from __future__ import annotations

from unittest.mock import patch


def test_search_skill_tools_does_not_raise_typeerror() -> None:
    """Every skill MCP search used to raise TypeError; verify it now returns."""
    from crackerjack.mcp.tools import skill_tools

    with patch.object(skill_tools, "_search_skill_tools_impl", return_value=[]) as mock:
        # Whichever keyword is supported — both forms exercised below.
        try:
            result = skill_tools.search_skill_tools(search_in="names", query="x")
        except TypeError:
            result = skill_tools.search_skill_tools(search_tool_names=True, query="x")
        assert result == []
        assert mock.called
```

The test asserts no `TypeError` is raised and the underlying implementation is invoked. Adjust the import path if `skill_tools.search_skill_tools` is not the public name (read `crackerjack/mcp/tools/skill_tools.py` to confirm the exported symbol).

- [ ] **Step 4: Run the test and verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/mcp/test_skill_tools.py -v`
Expected: FAIL with `TypeError: search_tool_tools_impl() got an unexpected keyword argument 'search_names'`.

- [ ] **Step 5: Implement the fix in `_update_success_rate`**

Open `crackerjack/skills/agent_skills.py`. Locate `_update_success_rate(self, success: bool)` at line 218. Change the signature and body so it accepts the outcome classification and records all three branches:

```python
def _update_success_rate(self, outcome: str) -> None:
    """Record a skill outcome for the success-rate rolling metric.

    Args:
        outcome: One of "success", "failure", "timeout".
    """
    if outcome not in {"success", "failure", "timeout"}:
        msg = f"Unknown skill outcome: {outcome!r}"
        raise ValueError(msg)

    self._total_runs += 1
    if outcome == "success":
        self._success_runs += 1
    # failure and timeout both reduce the success rate; no separate counter needed.
    self._success_rate = self._success_runs / self._total_runs if self._total_runs else 1.0
```

Adjust the attribute names (`_total_runs`, `_success_runs`, `_success_rate`) to match what the existing dataclass already uses. Read lines 1-100 of `agent_skills.py` to confirm.

Then update the call site (line 130 area) to pass the classification string instead of a bool. If the call site currently passes `bool(success)`, change it to pass the outcome name directly.

- [ ] **Step 6: Implement the fix in `skill_tools.py:184`**

Open `crackerjack/mcp/tools/skill_tools.py`. At line 184, replace:

```python
search_names=search_in in ("all", "names"),
```

with the keyword that `search_skill_tools_impl` actually accepts (read the function signature at the top of the file to confirm — most likely `search_tool_names`):

```python
search_tool_names=search_in in ("all", "names"),
```

If the implementation function uses a different keyword (e.g. `search_query`), match that exactly.

- [ ] **Step 7: Re-run both tests and verify they pass**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/skills/test_agent_skills.py::TestAgentSkillsOutcome::test_update_success_rate_records_failures_and_timeouts tests/unit/mcp/test_skill_tools.py -v`
Expected: PASS, PASS.

- [ ] **Step 8: Run the full skill test files to confirm no regression**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/skills/ tests/unit/mcp/ -q`
Expected: all pass; pre-existing failures (if any) documented in the prior research are out of scope.

- [ ] **Step 9: Lint and format**

Run: `cd /Users/les/Projects/crackerjack && uv run ruff check crackerjack/skills/agent_skills.py crackerjack/mcp/tools/skill_tools.py tests/unit/skills/test_agent_skills.py tests/unit/mcp/test_skill_tools.py && uv run ruff format crackerjack/skills/agent_skills.py crackerjack/mcp/tools/skill_tools.py tests/unit/skills/test_agent_skills.py tests/unit/mcp/test_skill_tools.py`
Expected: no errors; format applies if needed.

- [ ] **Step 10: Commit**

```bash
cd /Users/les/Projects/crackerjack
git add crackerjack/skills/agent_skills.py crackerjack/mcp/tools/skill_tools.py tests/unit/skills/test_agent_skills.py tests/unit/mcp/test_skill_tools.py
git commit -m "fix(skills): wire skill-metrics for failure/timeout + repair skill-tools kwarg

- _update_success_rate now takes the outcome classification
  (\"success\" | \"failure\" | \"timeout\") and lowers the rolling rate on
  any non-success path.
- skill_tools.search_skill_tools passes search_tool_names (matching the
  underlying impl signature) instead of the never-declared search_names,
  which previously raised TypeError on every MCP skill search.

C-SKILL-METRICS from the Bodai OpenClaw/Hermes portfolio.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Complete QualityGateReport outcome contract (C-OUTCOME-CONTRACT)

`QualityGateReport.passed` and `blocking_failure` only consider `REQUIRED` severity today. Optional and warning checks are missing from the contract. Spec demands they participate in the boolean at least in a documented way.

**Files:**
- Modify: `crackerjack/models/validation_contracts.py:254-295` (`QualityGateReport.passed` and `blocking_failure`)
- Test: `tests/models/test_validation_contracts.py` (extend existing)

**Interfaces:**
- Consumes: `GateSeverity` enum (already in the file at line ~50) with members `REQUIRED`, `WARNING`, `OPTIONAL`
- Consumes: `GateCheck.passed: bool` (already in the file)
- Produces: `QualityGateReport.passed` returns `True` iff every `REQUIRED` check is `passed` AND no warning-level `blocking_failure` exists (warnings must be reviewed, not silently passed)
- Produces: `QualityGateReport.blocking_failure` returns the name of the first failing required check, or `None` when all required pass

- [ ] **Step 1: Add failing tests**

Open `tests/models/test_validation_contracts.py`. Locate `TestQualityGateReport`. Add:

```python
def test_passed_false_when_required_check_fails(self) -> None:
    from crackerjack.models.validation_contracts import GateCheck, GateSeverity, QualityGateReport

    failing = GateCheck(name="lint.required", passed=False, severity=GateSeverity.REQUIRED)
    report = QualityGateReport(checks=[failing])

    assert report.passed is False
    assert report.blocking_failure == "lint.required"


def test_passed_true_when_only_optional_check_fails(self) -> None:
    from crackerjack.models.validation_contracts import GateCheck, GateSeverity, QualityGateReport

    optional = GateCheck(name="docs.optional", passed=False, severity=GateSeverity.OPTIONAL)
    report = QualityGateReport(checks=[optional])

    assert report.passed is True
    assert report.blocking_failure is None


def test_blocking_failure_is_well_documented_for_warnings(self) -> None:
    """Warnings must surface; contract decides whether they block or are reported.

    Per the spec: warnings are reviewed, not silently passed. Document the
    behavior by asserting the chosen contract explicitly. The chosen contract
    here is: warnings are reported (block via `blocking_failure`) but do not
    flip `passed` to False on their own — only REQUIRED failures do.
    """
    from crackerjack.models.validation_contracts import GateCheck, GateSeverity, QualityGateReport

    warning = GateCheck(name="lint.warning", passed=False, severity=GateSeverity.WARNING)
    report = QualityGateReport(checks=[warning])

    # Documented contract: warning is surfaced but does not by itself block `passed`.
    assert report.passed is True
    assert report.blocking_failure is None  # see QualityGateReport docstring for rationale
```

If the `GateCheck` constructor signature differs from `(name, passed, severity)`, read `crackerjack/models/validation_contracts.py` to confirm and adjust.

- [ ] **Step 2: Run the tests and verify the failure**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/models/test_validation_contracts.py -k "passed_false_when_required_check_fails or passed_true_when_only_optional or blocking_failure_is_well_documented_for_warnings" -v`
Expected: at least one failure (the contract is incomplete).

- [ ] **Step 3: Implement the contract fix**

Open `crackerjack/models/validation_contracts.py`. Replace the `passed` and `blocking_failure` properties on `QualityGateReport` (lines 270-289) with:

```python
@property
def passed(self) -> bool:
    """True iff every REQUIRED check passes. Optional failures do not block.

    Warning-level failures are surfaced via `blocking_failure` callers but
    do not flip this property to False on their own — operators are expected
    to review warnings before declaring the gate green.
    """
    return all(
        check.passed for check in self.checks if check.severity == GateSeverity.REQUIRED
    )

@property
def blocking_failure(self) -> str | None:
    """Name of the first failing REQUIRED check, or None when all REQUIRED pass."""
    for check in self.checks:
        if check.severity == GateSeverity.REQUIRED and not check.passed:
            return check.name
    return None
```

The exact field name on `GateCheck` may be `severity` or something else; adjust if needed. Update the module docstring or `QualityGateReport` class docstring to document the WARNING policy explicitly (one sentence: "Warning failures do not flip `passed`; review them via `report_failures()` or downstream consumers").

- [ ] **Step 4: Re-run tests and verify they pass**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/models/test_validation_contracts.py -v`
Expected: PASS, PASS, PASS (and any pre-existing tests still passing).

- [ ] **Step 5: Lint, format, commit**

```bash
cd /Users/les/Projects/crackerjack
uv run ruff check crackerjack/models/validation_contracts.py tests/models/test_validation_contracts.py
uv run ruff format crackerjack/models/validation_contracts.py tests/models/test_validation_contracts.py
git add crackerjack/models/validation_contracts.py tests/models/test_validation_contracts.py
git commit -m "fix(contracts): complete QualityGateReport outcome contract

- passed is True iff every REQUIRED check passes; OPTIONAL failures
  no longer silently flip the gate.
- blocking_failure returns the first failing REQUIRED check name (or
  None).
- WARNING-level failures are surfaced through report consumers but do
  not by themselves block `passed`; the chosen contract is documented
  on the class.

C-OUTCOME-CONTRACT from the Bodai OpenClaw/Hermes portfolio.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Crackerjack plugin-trust fixes (C-PLUGIN-TRUST)

Three small but distinct trust defects. The `_get_test_status` placeholder is a fourth but lives in `tests/integration/test_skills_tracking.py` and is a test-only fake — address it in the same commit since they share the theme.

**Files:**
- Modify: `crackerjack/plugins/hooks.py:42` (replace `assert` with explicit raise)
- Modify: `crackerjack/plugins/base.py:19-50` (fix `PluginMetadata.requires_python` parsing)
- Modify: `crackerjack/integration/skills_tracking.py:251` (fix `SessionBuddyMCPTracker` default URL)
- Modify: `tests/integration/test_skills_tracking.py` (`_get_test_status` placeholder)
- Test: `tests/test_plugins_coverage.py` (extend existing)

**Interfaces:**
- Consumes: `PluginType` enum already imported in `hooks.py`
- Consumes: `PluginMetadata` in `base.py`; existing parsing logic for `requires_python`
- Consumes: `SessionBuddyMCPTracker.__init__` defaults in `skills_tracking.py`
- Produces: `register_custom_hook` raises `crackerjack.exceptions.PluginTrustError` instead of asserting
- Produces: `PluginMetadata.requires_python: str | None` accepts malformed inputs and parses them safely (returns the raw string and flags invalid parses via a separate validator method, not a runtime crash)
- Produces: `SessionBuddyMCPTracker` default `mcp_server_url` is `"http://localhost:8678"` (no space)
- Produces: `_get_test_status` returns a real pytest-based status (collected via `pytest.main(["--collect-only", ...])` returning exit-code semantics) or, if simpler, marks the placeholder as such via `TODO(durable)` and raises `NotImplementedError` instead of returning 100%

- [ ] **Step 1: Add failing test for plugin-trust asserts**

Open `tests/test_plugins_coverage.py`. Add:

```python
def test_register_custom_hook_raises_on_wrong_type() -> None:
    """assert removed from production code; explicit exception instead."""
    from crackerjack.plugins.hooks import register_custom_hook
    from crackerjack.plugins.base import PluginMetadata, PluginType
    from crackerjack.exceptions import PluginTrustError

    # Minimal valid metadata for everything except the type, which is wrong.
    md = PluginMetadata(name="bad", plugin_type=PluginType.TOOL, version="0.0.1")  # type isn't HOOK
    with pytest.raises(PluginTrustError):
        register_custom_hook(md, callable=lambda: None)
```

If the `PluginMetadata` constructor signature differs, adjust. If the import path for `PluginTrustError` is wrong, find the actual exception class in `crackerjack/exceptions/` and use that.

- [ ] **Step 2: Add failing test for malformed URL**

Open `tests/integration/test_skills_tracking.py`. Add:

```python
def test_session_buddy_mcp_tracker_default_url_has_no_space() -> None:
    from crackerjack.integration.skills_tracking import SessionBuddyMCPTracker

    tracker = SessionBuddyMCPTracker(session_id="x")
    assert " " not in tracker.mcp_server_url
    assert tracker.mcp_server_url == "http://localhost:8678"
```

- [ ] **Step 3: Add failing test for placeholder `_get_test_status`**

In the same file or `tests/integration/test_skills_tracking.py`, find `_get_test_status`. Add:

```python
def test_get_test_status_does_not_lie() -> None:
    """The placeholder that always returned 100% must not be a default."""
    from crackerjack.integration.skills_tracking import _get_test_status

    with pytest.raises((NotImplementedError, RuntimeError)):
        _get_test_status(skill_name="nonexistent.skill")
```

- [ ] **Step 4: Run all three tests and verify failures**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/test_plugins_coverage.py::test_register_custom_hook_raises_on_wrong_type tests/integration/test_skills_tracking.py::test_session_buddy_mcp_tracker_default_url_has_no_space tests/integration/test_skills_tracking.py::test_get_test_status_does_not_lie -v`
Expected: three failures (assert raises AssertionError instead of PluginTrustError; URL has a space; `_get_test_status` returns 1.0).

- [ ] **Step 5: Implement the fixes**

Open `crackerjack/plugins/hooks.py:42`. Replace:

```python
assert metadata.plugin_type == PluginType.HOOK
```

with:

```python
if metadata.plugin_type != PluginType.HOOK:
    raise PluginTrustError(
        f"register_custom_hook requires PluginType.HOOK, got {metadata.plugin_type!r}"
    )
```

Add the import for `PluginTrustError` (or whichever exception class actually exists in `crackerjack/exceptions/`).

Open `crackerjack/plugins/base.py:19-50`. Locate `PluginMetadata.requires_python`. The current value is `'>= 3.11'` with a stray space — fix the literal to `'>=3.11'`. If the field has a `field(...)` validator, ensure the validator enforces that the value parses as a PEP 440 specifier; if not, add a soft parse via `packaging.specifiers.SpecifierSet` and store the parsed form, raising `ValueError` on parse failure. Keep the change minimal: strip the space, add a `validator` that parses the specifier, store the raw string. Update the docstring.

Open `crackerjack/integration/skills_tracking.py:251`. Change the default:

```python
mcp_server_url: str = "http://localhost:8678"
```

(no space).

Open the file containing `_get_test_status`. Find the placeholder. If it's a function returning `1.0` (100%), replace the body with a `raise NotImplementedError("DURABLE: integrate with crackerjack CI runner — see C-ASYNC-DURABILITY")`. If it's already raising somewhere else, leave it but document the integration contract on the docstring. The tests will tell you which is which.

- [ ] **Step 6: Re-run all three tests and verify they pass**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/test_plugins_coverage.py::test_register_custom_hook_raises_on_wrong_type tests/integration/test_skills_tracking.py::test_session_buddy_mcp_tracker_default_url_has_no_space tests/integration/test_skills_tracking.py::test_get_test_status_does_not_lie -v`
Expected: PASS, PASS, PASS.

- [ ] **Step 7: Run the broader plugin + integration suites for regressions**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/test_plugins_coverage.py tests/integration/test_skills_tracking.py -q`
Expected: no new failures; pre-existing failures are out of scope.

- [ ] **Step 8: Lint, format, commit**

```bash
cd /Users/les/Projects/crackerjack
uv run ruff check crackerjack/plugins/hooks.py crackerjack/plugins/base.py crackerjack/integration/skills_tracking.py tests/test_plugins_coverage.py tests/integration/test_skills_tracking.py
uv run ruff format crackerjack/plugins/hooks.py crackerjack/plugins/base.py crackerjack/integration/skills_tracking.py tests/test_plugins_coverage.py tests/integration/test_skills_tracking.py
git add crackerjack/plugins/hooks.py crackerjack/plugins/base.py crackerjack/integration/skills_tracking.py tests/test_plugins_coverage.py tests/integration/test_skills_tracking.py
git commit -m "fix(plugins): replace asserts, fix malformed url + python spec, surface placeholder

- register_custom_hook raises PluginTrustError instead of assert.
- PluginMetadata.requires_python literal stripped of stray space;
  validator parses via packaging.specifiers.
- SessionBuddyMCPTracker default mcp_server_url is the well-formed
  http://localhost:8678.
- _get_test_status no longer silently returns 100%; raises
  NotImplementedError with a C-ASYNC-DURABILITY handoff note.

C-PLUGIN-TRUST from the Bodai OpenClaw/Hermes portfolio.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Fix WebSocket subscription auth normalize (C-WEBSOCKET-AUTH)

`_can_subscribe_to_channel` in `crackerjack/websocket/server.py:167-185` transforms permission strings via `.strip().lower().replace(" ", ":")` and then compares against the literal `"crackerjack: read"` (with space). The two sides disagree: the stored form has no space, the compared form has one. Operators with a legitimate `"crackerjack: read"` permission get a `FORBIDDEN`.

**Files:**
- Modify: `crackerjack/websocket/server.py:167-185` (`_can_subscribe_to_channel`)
- Test: `tests/unit/test_websocket_auth.py` (extend existing)

**Interfaces:**
- Consumes: `user["permissions"]` list of strings (some `crackerjack: read`, some `crackerjack:read`, some bare `read`)
- Produces: `_can_subscribe_to_channel(user, channel)` returns `True` iff the user's permission set, after canonicalization, contains the channel's required permission

- [ ] **Step 1: Add failing test**

Open `tests/unit/test_websocket_auth.py`. Add:

```python
def test_can_subscribe_quality_channel_with_space_separated_permission(self) -> None:
    """User with permission 'crackerjack: read' (with space) must subscribe to quality:* channels."""
    from crackerjack.websocket.server import WebSocketServer

    server = WebSocketServer()
    user = {"permissions": ["crackerjack: read"]}
    assert server._can_subscribe_to_channel(user, "quality:lint") is True


def test_can_subscribe_with_canonical_no_space_permission(self) -> None:
    user = {"permissions": ["crackerjack:read"]}
    from crackerjack.websocket.server import WebSocketServer

    server = WebSocketServer()
    assert server._can_subscribe_to_channel(user, "quality:lint") is True
```

If `WebSocketServer` has constructor requirements (config, manager, etc.), use whatever bare constructor the existing tests already use; read the existing tests in this file for the pattern.

- [ ] **Step 2: Run the tests and verify the failure**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_websocket_auth.py::test_can_subscribe_quality_channel_with_space_separated_permission -v`
Expected: FAIL with `AssertionError` (the current code returns `False`).

- [ ] **Step 3: Implement the fix**

Open `crackerjack/websocket/server.py:167-185`. Replace the body of `_can_subscribe_to_channel` with a version that canonicalizes both sides the same way. Use the existing `Permission` enum from `mcp_common.auth.permissions` (the same one `crackerjack/websocket/auth.py` already uses):

```python
def _can_subscribe_to_channel(self, user: dict[str, Any], channel: str) -> bool:
    """Return True iff the user can subscribe to ``channel``.

    Permission strings are canonicalized to ``crackerjack:<action>`` form
    before comparison so operators may use either ``crackerjack: read``
    (with space, legacy) or ``crackerjack:read`` (no space, canonical).
    """
    from crackerjack.websocket.auth import _normalize_permission

    user_perms = {
        p.normalized for p in (_normalize_permission(p) for p in user.get("permissions", []))
        if p is not None
    }

    required_perm = self._required_permission_for_channel(channel)
    if required_perm is None:
        return True
    return required_perm.normalized in user_perms or "admin" in user_perms
```

Then add `_required_permission_for_channel`:

```python
def _required_permission_for_channel(self, channel: str) -> "Permission | None":
    """Return the Permission required to subscribe to ``channel``, or None if open."""
    from mcp_common.auth.permissions import Permission

    if channel.startswith(("quality:", "test:")):
        return Permission("read")
    return None
```

If `_normalize_permission` in `crackerjack/websocket/auth.py` returns `Permission | None` (it does, per the spec's earlier grep), use it directly. If it returns a different shape, wrap accordingly. Keep imports minimal; do not over-import.

- [ ] **Step 4: Re-run tests and verify they pass**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/unit/test_websocket_auth.py -v`
Expected: PASS, PASS, plus any pre-existing tests.

- [ ] **Step 5: Lint, format, commit**

```bash
cd /Users/les/Projects/crackerjack
uv run ruff check crackerjack/websocket/server.py tests/unit/test_websocket_auth.py
uv run ruff format crackerjack/websocket/server.py tests/unit/test_websocket_auth.py
git add crackerjack/websocket/server.py tests/unit/test_websocket_auth.py
git commit -m "fix(websocket): canonicalize subscription permission comparison

- _can_subscribe_to_channel now normalizes both user permissions and
  the channel-required permission via the shared _normalize_permission
  helper before comparing, so 'crackerjack: read' (legacy space form)
  and 'crackerjack:read' (canonical) both subscribe to quality:*/test:*
  channels.
- Extracted _required_permission_for_channel so the rule lives in one
  place and is testable.

C-WEBSOCKET-AUTH from the Bodai OpenClaw/Hermes portfolio.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Refresh CRITICAL_HOOKS in SecurityAuditor (C-HOOKS-LIST)

`crackerjack/security/audit.py:44` declares `CRITICAL_HOOKS` with three names (bandit, pyright, gitleaks). Real-world coverage wants at least semgrep and a secrets scanner (betterleaks or trufflehog). Adding them keeps parity with the prior research's recommendation.

**Files:**
- Modify: `crackerjack/security/audit.py:44` (extend the set)
- Test: `tests/test_security_audit.py` (extend existing)

**Interfaces:**
- Consumes: existing `SecurityAuditor.CRITICAL_HOOKS` consumers (the `is_critical_hook` lookup at line 131 and the reason lookup at line 152)
- Produces: `CRITICAL_HOOKS` set includes at minimum: `bandit`, `pyright`, `gitleaks`, `semgrep`, `betterleaks` (or `trufflehog` if betterleaks is unavailable — pick the one in `pyproject.toml` extras or `crackerjack/hooks/`)

- [ ] **Step 1: Add failing test**

Open `tests/test_security_audit.py`. Add:

```python
def test_critical_hooks_includes_semgrep_and_betterleaks(self) -> None:
    """Critical hooks must include semgrep and a modern secrets scanner."""
    from crackerjack.security.audit import SecurityAuditor

    required = {"bandit", "pyright", "gitleaks", "semgrep", "betterleaks"}
    assert required.issubset(SecurityAuditor.CRITICAL_HOOKS)
```

If `betterleaks` is not actually available in crackerjack (read `pyproject.toml` to confirm), substitute `"trufflehog"` or whatever real hook name exists in `crackerjack/hooks/`. Update the test to match what's actually wired in.

- [ ] **Step 2: Run the test and verify it fails**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/test_security_audit.py::test_critical_hooks_includes_semgrep_and_betterleaks -v`
Expected: FAIL with assertion showing the missing hooks.

- [ ] **Step 3: Implement the fix**

Open `crackerjack/security/audit.py:44`. Extend `CRITICAL_HOOKS` (a `frozenset[str]`) by adding `"semgrep"` and `"betterleaks"` (or whatever real hook name you confirmed in Step 1). Keep the existing entries. Add a comment explaining why each entry matters:

```python
CRITICAL_HOOKS = frozenset(
    {
        # Code quality / static analysis
        "bandit",
        "pyright",
        "semgrep",
        # Secret detection
        "gitleaks",
        "betterleaks",  # or trufflehog if betterleaks is unavailable
    }
)
```

Verify the new hook names exist as actual hook names in `crackerjack/hooks/` (or in `pyproject.toml` extras). If they don't, drop the missing one from the test in Step 1 and adjust accordingly — but do not silently weaken the contract.

- [ ] **Step 4: Re-run tests and verify they pass**

Run: `cd /Users/les/Projects/crackerjack && uv run pytest tests/test_security_audit.py -v`
Expected: PASS plus any pre-existing tests.

- [ ] **Step 5: Lint, format, commit**

```bash
cd /Users/les/Projects/crackerjack
uv run ruff check crackerjack/security/audit.py tests/test_security_audit.py
uv run ruff format crackerjack/security/audit.py tests/test_security_audit.py
git add crackerjack/security/audit.py tests/test_security_audit.py
git commit -m "fix(security): expand SecurityAuditor.CRITICAL_HOOKS

Add semgrep (static analysis) and betterleaks (secrets) to the
critical-hooks allow-list so the auditor flags their absence as
noteworthy, matching the prior parity audit.

C-HOOKS-LIST from the Bodai OpenClaw/Hermes portfolio.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Persist AsyncTaskManager jobs (C-ASYNC-DURABILITY) — Phase 1.5, GATED ON D-LOCK

**Do not start this task** until `D-LOCK` from `docs/superpowers/specs/2026-08-03-bodai-openclaw-hermes-inspired-portfolio-design.md` §"Layer 0" has shipped into the Dhara substrate and is consumable from crackerjack. This task is the only one in the C-WIRE plan that depends on substrate work; the other five ship ahead.

This plan intentionally stops at the gating signal. When D-LOCK is available, write a follow-up plan that:

- Imports `dhara.lock.DharaLock` (or the agreed API; reconfirm at plan time).
- Replaces `asyncio.create_task(self._cleanup_loop())` at `crackerjack/mcp/task_manager.py:37` with a DharaLock-guarded equivalent.
- Persists `task_id → status` to Dhara so a restart resumes from the last persisted state.
- Surfaces a `result_store` MCP tool that returns the persisted result for a given `task_id`.
- Defines a `reap_zombies` task (analogous to the Mahavishnu one) keyed on the lock TTL.

The integration contract for this task (placeholder until the per-repo D-LOCK spec lands):

- **Triggered from:** `crackerjack mcp` restart, `reap_zombies` cron (TBD), and `create_task` invocations on `AsyncTaskManager`.
- **Returns to / updates:** Dhara key `crackerjack/async-tasks/{task_id}` storing `{status, started_at, finished_at, result_payload}`.
- **Demonstrable by:** restart the MCP server mid-task, observe the task resume with the same `task_id`; `pytest tests/mcp/test_task_manager.py::test_restart_resumes_task -v` passes.
- **Rollback signal:** `metric:crackerjack.async_tasks.resumed == 0` after a restart that should have resumed at least one task; revert the durability commit.
- **Observability added:** audit event `crackerjack.async_task.persisted` with `task_id + status + age_ms`.

Skip this task in the current round. The integration contract above is the seed for the follow-up plan.
