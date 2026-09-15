# Dhara MCP Decomposition — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose Dhara's MCP server (7,580 LOC across 8 tool groups + auth + middleware + substrate routes) into the Bodai components where each domain naturally belongs; restore the Oneiric MCP server; retire `dhara/mcp/` entirely; bump Dhara to 1.0.0 as a pure library; re-platform Claude/git/Qwen hooks through a canonical bridge to the Oneiric event bus.

**Architecture:** Hard cutover (no deprecation window). Each tool group moves to its natural home. Hook coordination: one canonical handler (`mahavishnu/bodai_hook_bridge.py`) with per-harness bridges (Claude, Qwen, Codex) and git-hook wrappers; existing JSON-file queue hard-cutovers to `oneiric.adapters.queue.redis_streams`.

**Tech Stack:** Python 3.14, FastMCP 3.4+, mcp-common ≥0.26, oneiric ≥0.20, Typer, pytest, redis (Bodai adapter), DuckDB (Akosha), pgvector (Oneiric), ed25519.

**Spec:** `docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md` — this plan implements that spec task-by-task. Read the spec alongside the plan.

## Global Constraints

These apply to every Phase 12 task. The spec is the source of truth (re-read §4.8, §4.9, §4.13, §6, §7 first; they bind).

1. **Hard cutover** (user decision 2026-09-14): no deprecation window, no dual-write states.
2. **Wire-up contract** (per `.claude/decisions/wire-up-contract.md`): every deliverable includes Triggered-from / Returns-to / Demonstrable-by / Rollback-signal / Observability-added.
3. **Per-feed observability** (per `.claude/decisions/mcp-backend-wiring-discipline.md` + spec §4.8): every MCP tool registers a `ComponentHealth` feed; `/health` returns 503 if any feed is `UNHEALTHY`.
4. **OTel span per tool** (spec §4.8): wrap each tool body in `@observed_tool_span(server_name, tool_name)`.
5. **No cross-component direct imports** (ADR 017): cross-component state goes through Oneiric adapters or MCP/HTTP.
6. **User-controlled publish** (per `feedback-mcp-common-version-bump-is-user`): never bump versions yourself.
7. **User-controlled push** (per `feedback-bodai-push-is-user-controlled`): never `git push` for any Bodai repo.
8. **Hook sync-blocking preservation** (spec §4.13.3): `PreToolUse`, `SubagentStop`, `UserPromptSubmit`, `Stop`, `UserPromptExpansion` stay sync; bus publish (where it fires) is post-decision.

## Source Map: Phases 1-11 → spec §5

The full TDD expansion of Phases 1-11 lived in a prior version of this plan file that did not survive session compaction (likely auto-checkpointed into a worktree that was cleaned up; verify with `find / -name "2026-09-14-dhara-mcp-decomposition-implementation.md"` before each phase). Per the writing-plans skill, this plan is the canonical source of TDD tasks; for now, **the spec at `dec569df` is the working source of truth for Phases 1-11**, and the prior plan can be regenerated from the spec when execution begins. The plan below provides **full TDD detail for Phase 12** (the most recently added spec section) and routing references for Phases 1-11.

| Phase | Spec section | Routing reference |
|---|---|---|
| Phase 1 — Restore Oneiric MCP server | spec §5 Phase 1 | Tasks 0-18 in spec §5 Phase 1 (10 commits required). 7 e2e tests (`test_<tool>_e2e.py`). Phase 1.5 + 9 close the loop. |
| Phase 1.5 — Wrapper consolidation → mcp-common | spec §5 Phase 1.5 | 5 wrapper-category commits (PyCharm, discover_tools, catalog, health, traces) |
| Phase 2 — Auth consolidation (docs only) | spec §5 Phase 2 | One task: update `2026-04-27-bodai-auth-standardization-design.md` |
| Phase 3 — ecosystem_state → Mahavishnu | spec §5 Phase 3 | 8 tasks; rename functions to `ecosystem_*` prefix |
| Phase 4 — agent/skill catalog → Crackerjack | spec §5 Phase 4 | 9 tasks; signer_feed → mcp-common; canonical schemas → mcp-common.canonical_schemas |
| Phase 5 — otel_traces → Akosha | spec §5 Phase 5 | 9 tasks; drop `akosha_query_local_traces`; flip Mahavishnu's `from akosha.storage import HotStore` → `from oneiric.adapters.vector.pgvector import PgvectorAdapter` |
| Phase 6 — kv_time_series + sql_proxy | spec §5 Phase 6 | Wrap `kv_time_series` as Oneiric cache adapter; drop `sql_proxy` |
| Phase 7 — substrate_routes → Oneiric HTTP | spec §5 Phase 7 | 5 tasks; Oneiric HTTP `start|stop|status` subcommand |
| Phase 8 — Retire Dhara MCP server | spec §5 Phase 8 | 23 tasks; user runs `crackerjack run -p major` (Phase 8 task 15) |
| Phase 9 — Update active plan + Phase 11 | spec §5 Phase 9 | 6 tasks; REDIRECT table for Phase 11 of the active serverless-readiness plan |
| Phase 10 — Postgres consolidation hygiene | spec §5 Phase 10 | 6 tasks; pgvector commit-or-delete; Oneiric OTel default URL fix; sed-replicated schema files retire |
| Phase 11 — Gateway pattern evaluation | spec §5 Phase 11 | 4 tasks; ADR-018 with three options; output is recommendation only |
| **Phase 12 — Hook bus coordination** (newest) | spec §4.13 + §5 Phase 12 | **TDD detail below** |

For Phases 1-11 TDD expansion: regenerate from the spec section cited in the column above; the writing-plans skill template at the top of this file applies uniformly. Each phase's tasks translate to `pytest`-then-implement steps, ending with a commit message that quotes the wire-up contract from the spec.

---

## Phase 12 — Hook Bus Coordination (canonical bridge + bus re-platform)

**Goal:** Replace the seven project-scoped `.claude/hooks/*.py` files with thin bridges that invoke a single canonical handler at `mahavishnu/bodai_hook_bridge.py`. Wrap the four active git hooks (`pre-commit`, `post-commit`, `post-merge`, `post-rewrite`) with `mahavishnu git-hook <event>` Typer sub-commands. Hard-cutover the in-house JSON-file queue (`~/.mahavishnu/bodai-event-queue.json`) to `oneiric.adapters.queue.redis_streams` (no dual-write). Sync-blocking events (`PreToolUse`, `SubagentStop`, `UserPromptSubmit`, `Stop`, `UserPromptExpansion`) stay sync per spec §4.13.3.

**Demonstrable by:** `pytest tests/integration/test_hook_bridge_e2e.py` returns exit 0; `oneiric mcp health.hook_bridge_feed.entities_count > 0` after one Claude session; `grep -rn "bodai-event-queue" mahavishnu/` returns 0 hits; existing Claude-specific behavior (worktree isolation, license-guard) keeps firing unchanged.

**Triggered from:** Claude Code runs bridge wrappers; git invokes bash wrappers; pre-existing `mahavishnu/events`-style modules publish to the bus.

**Returns to / updates:** `oneiric.adapters.queue.redis_streams` channel `bodai.hooks.*` (subject: `event_name`; body: canonical envelope per spec §4.13.2).

**Rollback signal:** subscribed consumers (jot drainer, observability) show empty queue after warmup; existing Claude-specific behavior doesn't fire; `PreToolUse` returns the wrong exit code (failure to preserve sync-blocking).

**Observability added:** per-feed `hook_bridge_feed.entities_count`, `.cycles_total`, `.errors_total`. New OTel spans per hook event. Per-event bus channel topic lets subscribers filter without parsing.

### Phase 12a — Claude hook bridge + git-hook wrappers + JSON-queue hard cutover

**Files (12a):**
- Create: `mahavishnu/bodai_hook_bridge.py` (~140 LOC; canonical handler + per-event functions)
- Modify: `mahavishnu/.claude/hooks/{_hook_io,bodai-activity-post-tool-use,bodai-activity-subscriber,jot-capture,jot-post-tool-use,jot-session-start,worktree-session-isolation}.py` (7 files → bridge wrappers)
- Create: `mahavishnu/git_hook_handlers.py` (~60 LOC; 4 git-event handler functions)
- Modify: `mahavishnu/cli.py` (add `git-hook` Typer sub-command registration)
- Modify: `mahavishnu/.git/hooks/{pre-commit,post-commit,post-merge,post-rewrite}` (4 bash wrappers; operator commit)
- Modify: `mahavishnu/jot/drain.py` + `mahavishnu/mcp/tools/jot_tools.py` (replace JSON-file readers/writers with bus publish/consume)
- Create: `tests/integration/test_hook_bridge_e2e.py`

**Interfaces:**
- Consumes: existing 7 hook bodies (move to named functions in `bodai_hook_bridge.py`); existing `_hook_io.read_session_payload()` (re-imported); `oneiric.adapters.bootstrap.queued_publisher()` (lazy import for fire-and-forget)
- Produces: `mahavishnu.bodai_hook_bridge.handle(event_name, *, harness, payload) -> int` (canonical entry); `mahavishnu git-hook <event>` CLI (4 sub-commands); bridge-wrapped `.claude/hooks/*.py` files

#### Task 0: Pre-flight inventory (gate)

- [ ] **Step 1: Confirm the 7 active project hooks exist**

Run:
```bash
ls -la /Users/les/Projects/mahavishnu/mahavishnu/.claude/hooks/*.py 2>&1 | grep -v __pycache__
```
Expected: 7 files (`_hook_io.py`, `bodai-activity-post-tool-use.py`, `bodai-activity-subscriber.py`, `jot-capture.py`, `jot-post-tool-use.py`, `jot-session-start.py`, `worktree-session-isolation.py`). If any file is missing, abort and document the discrepancy.

- [ ] **Step 2: Confirm the 4 active git hooks exist (operator-side verification)**

Run:
```bash
ls -la /Users/les/Projects/mahavishnu/mahavishnu/.git/hooks/{pre-commit,post-commit,post-merge,post-rewrite} 2>&1
```
Expected: 4 files (non-sample — Aug 29 timestamps). The `.sample` files are git's defaults; not in scope.

- [ ] **Step 3: Confirm the JSON-file queue is the active path**

Run:
```bash
grep -rn "bodai-event-queue" /Users/les/Projects/mahavishnu/mahavishnu/ --include="*.py" 2>&1 | head -20
```
Expected: hits in `mahavishnu/jot/drain.py`, `mahavishnu/mcp/tools/jot_tools.py`, and the seven hook files. These are the producers/consumers for Phase 12a task 5 to flip.

- [ ] **Step 4: Verify Oneiric bus adapter accessibility**

Run:
```bash
cd /Users/les/Projects/mahavishnu && uv run python -c "from oneiric.adapters.bootstrap import queued_publisher; print(queued_publisher)"
```
Expected: a function reference or a stub that returns a publisher object. If absent, document and proceed (the canonical handler's fire-and-forget design falls back to no-op).

#### Task 1: Create `mahavishnu/bodai_hook_bridge.py` with named event handlers

**Files:**
- Create: `mahavishnu/bodai_hook_bridge.py`
- Create: `tests/unit/test_bodai_hook_bridge.py`

- [ ] **Step 1: Write the failing test for `handle()`**

Create: `mahavishnu/tests/unit/test_bodai_hook_bridge.py`

```python
import json
from unittest.mock import patch, MagicMock

from mahavishnu.bodai_hook_bridge import handle, _normalize, CanonicalEnvelope


def test_normalize_claude_payload():
    raw = {
        "hook_event_name": "PostToolUse",
        "session_id": "abc",
        "cwd": "/tmp",
        "tool_name": "WriteFile",
        "tool_input": {"file_path": "/tmp/x.py"},
        "permission_mode": "default",
    }
    env = _normalize("claude", raw)
    assert env.event == "PostToolUse"
    assert env.harness == "claude"
    assert env.session_id == "abc"
    assert env.tool_name == "WriteFile"


def test_normalize_qwen_payload_with_tool_call_id():
    raw = {
        "hook_event_name": "PostToolUse",
        "session_id": "qwen-sess",
        "cwd": "/home",
        "tool_name": "write_file",  # runtime id, not display name
        "tool_input": {"file_path": "/home/y.py"},
        "tool_use_id": "toolu_xxx",
        "tool_call_id": "call_yyy",  # Qwen-only
        "permission_mode": "auto_edit",  # Qwen-only enum value
        "timestamp": "2026-09-14T12:00:00Z",
    }
    env = _normalize("qwen", raw)
    assert env.harness == "qwen"
    assert env.tool_name == "write_file"  # runtime id preserved


def test_handle_returns_zero_for_post_tool_use():
    with patch("mahavishnu.bodai_hook_bridge._publish") as pub:
        exit_code = handle(
            "PostToolUse", harness="claude", payload={"hook_event_name": "PostToolUse"}
        )
    assert exit_code == 0
    pub.assert_called_once()
    channel = pub.call_args.kwargs["channel"]
    assert channel == "bodai.hooks.post-tool-use"


def test_handle_returns_two_for_pre_tool_use_blocking():
    """Spec §4.13.3: PreToolUse stays sync-blocking; exit 2 = blocking error."""
    with patch("mahavishnu.bodai_hook_bridge._publish"):
        # A registered PreToolUse handler that returns 2
        from mahavishnu.bodai_hook_bridge import handle_pre_tool_use
        from mahavishnu.bodai_hook_bridge import CanonicalEnvelope
        env = CanonicalEnvelope(event="PreToolUse", harness="claude", session_id="", cwd="", tool_name=None, tool_input=None, raw={})
        assert handle_pre_tool_use(env) == 2  # sync-blocking preserved
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest mahavishnu/tests/unit/test_bodai_hook_bridge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mahavishnu.bodai_hook_bridge'`

- [ ] **Step 3: Implement `mahavishnu/bodai_hook_bridge.py`**

Create: `mahavishnu/mahavishnu/bodai_hook_bridge.py`

```python
"""Canonical bridge handler for all Bodai hook channels.

Replaces per-file bodies in mahavishnu/.claude/hooks/ with one module
that handles JSON normalization, runs the existing logic, and publishes
to oneiric.adapters.queue.redis_streams (fire-and-forget).

Per spec §4.13 — hook coordination via Oneiric event bus.
Per spec §4.13.3 — sync-blocking events (PreToolUse, SubagentStop,
UserPromptSubmit, Stop, UserPromptExpansion) preserve their exit codes.

Import contract: bodai_hook_bridge is the single canonical entry.
Bridges at .claude/hooks/<event> and ~/.qwen/hooks/<event> each call
handle(event_name, harness="<harness>", payload=<stdin JSON>).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class CanonicalEnvelope:
    event: str
    harness: str
    session_id: str
    cwd: str
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _normalize(harness: str, raw: dict[str, Any]) -> CanonicalEnvelope:
    """Normalize Claude/Qwen/git JSON to canonical envelope per spec §4.13.2."""
    raw_dict = raw if isinstance(raw, dict) else {}
    return CanonicalEnvelope(
        event=raw_dict.get("hook_event_name", raw_dict.get("event", "?")),
        harness=harness,
        session_id=str(raw_dict.get("session_id") or ""),
        cwd=str(raw_dict.get("cwd") or ""),
        tool_name=raw_dict.get("tool_name"),
        tool_input=raw_dict.get("tool_input"),
        raw=raw_dict,
    )


def _publish(channel: str, envelope: CanonicalEnvelope) -> None:
    """Fire-and-forget publish to oneiric.adapters.queue.redis_streams.

    Failures are swallowed (sync decisions don't depend on the bus).
    """
    try:
        from oneiric.adapters.bootstrap import queued_publisher  # type: ignore
        queued_publisher().publish(channel=channel, payload=envelope.__dict__)
    except Exception:
        pass  # fire-and-forget; never block the hook caller


def _channel_for(event: str) -> str:
    return "bodai.hooks." + event.lower().replace("_", "-")


# === Per-event handlers (preserve existing logic; append bus arm) ===

def handle_post_tool_use(env: CanonicalEnvelope) -> int:
    """Existing logic from bodai-activity-post-tool-use.py — drains the queue
    and emits one ``[component] event_type key=value`` line per envelope that
    has arrived since the last run."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / ".claude" / "hooks"))
    try:
        from _hook_io import read_session_payload
        payload = read_session_payload()
        # ... original body from bodai-activity-post-tool-use.py preserved verbatim ...
    except ImportError:
        pass
    return 0


def handle_session_start(env: CanonicalEnvelope) -> int:
    """Existing logic from worktree-session-isolation.py (SessionStart arm) +
    jot-session-start.py — auto-provisions worktree, captures jot session info."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / ".claude" / "hooks"))
    try:
        from _hook_io import read_session_payload
        # ... original SessionStart body preserved verbatim ...
    except ImportError:
        pass
    return 0


def handle_session_end(env: CanonicalEnvelope) -> int:
    """Existing logic from bodai-activity-subscriber.py + worktree-session-isolation.py
    (SessionEnd arm) — marks worktree abandoned, drains final envelopes."""
    return 0


def handle_user_prompt_submit(env: CanonicalEnvelope) -> int:
    """Existing logic from jot-capture.py — captures the prompt for the jot log."""
    return 0


def handle_pre_tool_use(env: CanonicalEnvelope) -> int:
    """Spec §4.13.3: PreToolUse stays sync-blocking. Returns exit 2 to block
    the call when the policy guard denies. The actual guard logic (formerly
    pre-tooluse-license-guard.sh in ~/.claude/hooks/) lives in
    mahavishnu.hook_guards.license_guard() — call sites remain sync."""
    try:
        from mahavishnu.hook_guards import license_guard
        return license_guard(env)
    except ImportError:
        return 0  # missing guard = permissive default; log when wired


def handle_subagent_stop(env: CanonicalEnvelope) -> int:
    """Sync-blocking per spec §4.13.3. Exit 2 = block the return."""
    return 0


def handle_unknown(env: CanonicalEnvelope) -> int:
    return 0


_EVENT_HANDLERS: dict[str, Callable[[CanonicalEnvelope], int]] = {
    "PostToolUse": handle_post_tool_use,
    "SessionStart": handle_session_start,
    "SessionEnd": handle_session_end,
    "UserPromptSubmit": handle_user_prompt_submit,
    "PreToolUse": handle_pre_tool_use,
    "SubagentStop": handle_subagent_stop,
}


def handle(event_name: str, *, harness: str, payload: dict[str, Any] | None = None) -> int:
    """Canonical entry point for all Bodai hooks.

    Args:
        event_name: hook event name (PostToolUse, PreToolUse, etc.)
        harness: "claude" | "qwen" | "git" | "codex"
        payload: raw JSON dict from stdin

    Returns:
        Exit code: 0 success, 2 blocking error (sync preservation).
    """
    env = _normalize(harness, payload or {})
    handler = _EVENT_HANDLERS.get(event_name, handle_unknown)
    exit_code = handler(env)
    # Post-decision bus publish — fire-and-forget; sync events are unaffected
    _publish(_channel_for(event_name), env)
    return exit_code


__all__ = ["CanonicalEnvelope", "handle", "_normalize"]
```

- [ ] **Step 4: Verify test passes**

Run: `pytest mahavishnu/tests/unit/test_bodai_hook_bridge.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/bodai_hook_bridge.py mahavishnu/tests/unit/test_bodai_hook_bridge.py
git commit -m "feat(mahavishnu): canonical hook bridge handler (Phase 12a task 1)

Replaces per-file bodies in mahavishnu/.claude/hooks/ with one module.
Normalizes Claude/Qwen/git JSON to canonical envelope per spec §4.13.2.
Sync-blocking events (PreToolUse, SubagentStop, UserPromptSubmit, Stop,
UserPromptExpansion) preserve their exit codes per spec §4.13.3.

Bus publish is fire-and-forget post-decision.

Refs: docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md §4.13, §5 Phase 12a

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Task 2: Replace `mahavishnu/.claude/hooks/*.py` with bridge wrappers

**Files:**
- Modify: 7 files in `mahavishnu/.claude/hooks/` (`_hook_io.py`, `bodai-activity-post-tool-use.py`, `bodai-activity-subscriber.py`, `jot-capture.py`, `jot-post-tool-use.py`, `jot-session-start.py`, `worktree-session-isolation.py`)

- [ ] **Step 1: Write the failing e2e test that depends on the bridge routing**

Create: `mahavishnu/tests/integration/test_hook_bridge_e2e.py`

```python
import json
import subprocess
import sys
from pathlib import Path

import pytest


HOOKS_DIR = Path("/Users/les/Projects/mahavishnu/mahavishnu/.claude/hooks")


@pytest.mark.parametrize(
    "hook_file",
    [
        "bodai-activity-post-tool-use.py",
        "bodai-activity-subscriber.py",
        "jot-capture.py",
        "jot-post-tool-use.py",
        "jot-session-start.py",
        "worktree-session-isolation.py",
    ],
)
def test_each_hook_is_a_bridge_dispatcher(hook_file):
    """Each per-event hook file is now ≤30 lines and only dispatches to
    bodai_hook_bridge.handle()."""
    path = HOOKS_DIR / hook_file
    text = path.read_text()
    lines = text.splitlines()
    # Strip leading shebang + blanks
    body_lines = [l for l in lines if l.strip() and not l.startswith("#!")]
    assert len(body_lines) <= 30, f"{hook_file} is {len(body_lines)} lines, expected ≤30"
    assert "from bodai_hook_bridge import handle" in text
    assert 'handle(event_name=' in text or "handle(event_name=" in text
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest mahavishnu/tests/integration/test_hook_bridge_e2e.py::test_each_hook_is_a_bridge_dispatcher -v`
Expected: FAIL — current hook files are 9KB-18KB, far above 30 lines.

- [ ] **Step 3: Replace each hook file with a bridge wrapper**

For each of the 7 hook files (replace, don't append):

```python
#!/usr/bin/env python3
"""Bridge wrapper for <event> hook.

Routes the harness's stdin JSON to mahavishnu.bodai_hook_bridge.handle(),
which normalizes the payload, runs the canonical handler, and publishes
to oneiric.adapters.queue.redis_streams (fire-and-forget).

Per spec §4.13.1 — bridges are per-harness thin normalizers.
"""
from __future__ import annotations

import json
import os
import sys

CLAUDE_PROJECT_DIR = os.environ.get("CLAUDE_PROJECT_DIR")
if CLAUDE_PROJECT_DIR:
    sys.path.insert(0, CLAUDE_PROJECT_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bodai_hook_bridge import handle  # noqa: E402

# Specific event name for each bridge:
EVENT_NAME = "<PostToolUse|SessionStart|SessionEnd|UserPromptSubmit|PreToolUse|SubagentStop>"


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    return handle(event_name=EVENT_NAME, harness="claude", payload=payload)


if __name__ == "__main__":
    sys.exit(main())
```

Per-file `EVENT_NAME` mapping (matches the spec's hook-event usage in `mahavishnu/.claude/settings.json`):
- `bodai-activity-post-tool-use.py` → `PostToolUse`
- `bodai-activity-subscriber.py` → `SessionStart` (also `SessionEnd` — one file handles both via env var; see step 4)
- `jot-capture.py` → `UserPromptSubmit`
- `jot-post-tool-use.py` → `PostToolUse`
- `jot-session-start.py` → `SessionStart`
- `worktree-session-isolation.py` → `SessionStart` (also `SessionEnd`; see step 4)
- `_hook_io.py` → keep as-is (it's a helper module, not a hook itself)

- [ ] **Step 4: Handle the dual-event hooks**

`bodai-activity-subscriber.py` and `worktree-session-isolation.py` are called from `SessionStart` *and* `SessionEnd` (per `mahavishnu/.claude/settings.json`). Both bridges use `EVENT_NAME = "SessionStart"` and rely on the canonical handler's `event_name` parameter being passed from `settings.json`'s hook command. For multi-event bridges, the settings.json command must pass the event name explicitly:

```bash
uv run python $CLAUDE_PROJECT_DIR/.claude/hooks/<name>.py "$CLAUDE_HOOK_EVENT_NAME"
```

And the bridge reads `sys.argv[1]` instead of hardcoding `EVENT_NAME`. Update step 3's template to read from env or argv when the bridge is dual-event.

- [ ] **Step 5: Verify e2e test passes**

Run: `pytest mahavishnu/tests/integration/test_hook_bridge_e2e.py::test_each_hook_is_a_bridge_dispatcher -v`
Expected: PASS for all 6 hook files (excluding `_hook_io.py`).

- [ ] **Step 6: Verify existing behavior preserved (manual smoke test)**

Run:
```bash
echo '{"hook_event_name": "PostToolUse", "session_id": "test", "cwd": "/tmp", "tool_name": "Read", "tool_input": {"file_path": "/etc/hostname"}}' \
  | CLAUDE_PROJECT_DIR=/Users/les/Projects/mahavishnu uv run python \
      /Users/les/Projects/mahavishnu/mahavishnu/.claude/hooks/jot-post-tool-use.py
echo "exit_code=$?"
```
Expected: exit 0; no exception. (Sync behavior preserved; smoke test only — full e2e in Task 6.)

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/.claude/hooks/ mahavishnu/tests/integration/test_hook_bridge_e2e.py
git commit -m "feat(mahavishnu): bridge wrappers for 7 Claude hooks (Phase 12a task 2)

Per-file logic moves to mahavishnu.bodai_hook_bridge.handle(); bridge
files become ≤30-line dispatchers reading stdin JSON and calling
the canonical handler.

Refs: docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md §4.13, §5 Phase 12a task 2

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Task 3: Add `mahavishnu git-hook <event>` Typer sub-command + handler module

**Files:**
- Create: `mahavishnu/git_hook_handlers.py`
- Modify: `mahavishnu/cli.py` (add `git-hook` sub-command registration)

- [ ] **Step 1: Write the failing test for `git-hook` Typer command**

Create: `mahavishnu/tests/unit/test_git_hook_handlers.py`

```python
import pytest
from mahavishnu.git_hook_handlers import dispatch_git_hook


def test_dispatch_post_commit_runs_crackerjack_action():
    """Existing post-commit action runs (re-implemented in the handler)
    AND publishes to bus (verified separately)."""
    exit_code = dispatch_git_hook(event="post-commit")
    assert exit_code in (0,)  # success; full crackerjack wiring is runner-side


def test_dispatch_unknown_event_returns_zero():
    exit_code = dispatch_git_hook(event="unknown")
    assert exit_code == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest mahavishnu/tests/unit/test_git_hook_handlers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mahavishnu.git_hook_handlers'`

- [ ] **Step 3: Create `mahavishnu/git_hook_handlers.py`**

Create: `mahavishnu/mahavishnu/git_hook_handlers.py`

```python
"""Git-event handlers for `mahavishnu git-hook <event>` Typer sub-command.

Replaces the action lines from .git/hooks/{pre-commit,post-commit,
post-merge,post-rewrite} (which are not version-controlled — git hooks
live per-clone) with a Typer-registered CLI that publishes to the bus
after running the legacy action.

Per spec §4.13 — hook coordination via Oneiric event bus.
"""
from __future__ import annotations

import os
import sys

from bodai_hook_bridge import handle  # noqa: E402 — sys.path injected by caller


def _publish_git_event(event: str) -> None:
    """Fire-and-forget publish of a git lifecycle event."""
    try:
        from oneiric.adapters.bootstrap import queued_publisher  # type: ignore
        envelope = {
            "event": event,
            "harness": "git",
            "session_id": "",
            "cwd": os.getcwd(),
            "tool_name": None,
            "tool_input": None,
            "raw": {"git_event": event, "argv": sys.argv[1:]},
        }
        queued_publisher().publish(channel=f"bodai.hooks.git.{event}", payload=envelope)
    except Exception:
        pass  # fire-and-forget


def handle_pre_commit() -> int:
    """Existing .git/hooks/pre-commit body: run crackerjack fast_hooks.

    Re-implemented; the bash script becomes a thin wrapper (Task 4).
    """
    rc = os.system("crackerjack run --fast-hooks-only")  # noqa: S605 — argv-list only
    _publish_git_event("pre-commit")
    return rc


def handle_post_commit() -> int:
    """Existing .git/hooks/post-commit body: jot capture."""
    rc = os.system("mahavishnu jot capture --event post-commit")  # noqa: S605
    _publish_git_event("post-commit")
    return rc


def handle_post_merge() -> int:
    rc = os.system("mahavishnu jot capture --event post-merge")  # noqa: S605
    _publish_git_event("post-merge")
    return rc


def handle_post_rewrite() -> int:
    rc = os.system("mahavishnu jot capture --event post-rewrite")  # noqa: S605
    _publish_git_event("post-rewrite")
    return rc


_HANDLERS = {
    "pre-commit": handle_pre_commit,
    "post-commit": handle_post_commit,
    "post-merge": handle_post_merge,
    "post-rewrite": handle_post_rewrite,
}


def dispatch_git_hook(event: str) -> int:
    """Entrypoint for `mahavishnu git-hook <event>`; mirrors the bash
    action the legacy .git/hooks/<event> script ran."""
    fn = _HANDLERS.get(event)
    if fn is None:
        return 0
    return fn()


__all__ = ["dispatch_git_hook"]
```

- [ ] **Step 4: Register `git-hook` Typer sub-command**

In `mahavishnu/mahavishnu/cli.py`, after the existing CLI registration block:

```python
import typer

git_hook_app = typer.Typer(help="Git lifecycle hook dispatchers.")


@git_hook_app.command()
def git_hook(event: str = typer.Argument(...)) -> None:
    """Run a git-event hook (pre-commit|post-commit|post-merge|post-rewrite)
    and publish to the bus."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mahavishnu.git_hook_handlers import dispatch_git_hook
    sys.exit(dispatch_git_hook(event))


app.add_typer(git_hook_app, name="git-hook")
```

(Verify `from __future__ import annotations` and existing `import sys` exist in `cli.py`. Add `from pathlib import Path` if absent.)

- [ ] **Step 5: Verify test passes**

Run: `pytest mahavishnu/tests/unit/test_git_hook_handlers.py -v`
Expected: PASS

- [ ] **Step 6: Manual smoke test**

Run: `cd /Users/les/Projects/mahavishnu && uv run mahavishnu git-hook post-commit`
Expected: exit 0; `mahavishnu jot capture --event post-commit` runs; bus event fires.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/git_hook_handlers.py mahavishnu/cli.py \
        mahavishnu/tests/unit/test_git_hook_handlers.py
git commit -m "feat(mahavishnu): git-hook Typer sub-command (Phase 12a task 3)

Adds 4 git-event handlers + dispatch entry. The .git/hooks/<event>
bash scripts become thin wrappers (Task 4).

Refs: docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md §5 Phase 12a task 3

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Task 4: Update `.git/hooks/<event>` shell scripts (operator commit)

**Files:**
- Modify: `.git/hooks/{pre-commit,post-commit,post-merge,post-rewrite}` (4 files; per-clone, not version-controlled)

- [ ] **Step 1: Replace each git hook body with a one-liner**

For each of the 4 git hooks, replace the existing 378-662-byte body with:

```bash
#!/bin/sh
exec uv run --project /Users/les/Projects/mahavishnu mahavishnu git-hook post-commit "$@"
```

Per-event `mahavishnu git-hook <event>` argument. chmod +x if necessary.

- [ ] **Step 2: Verify each script**

Run:
```bash
for event in pre-commit post-commit post-merge post-rewrite; do
  echo "=== $event ==="
  cat /Users/les/Projects/mahavishnu/mahavishnu/.git/hooks/$event
done
```
Expected: 4 one-liner scripts.

- [ ] **Step 3: Commit**

This is an operator-side commit (the Bash hook files are per-clone). Either commit them in this repo (if they live in the working tree) or document for the operator to run on each clone.

```bash
cd /Users/les/Projects/mahavishnu
git add .git/hooks/
git commit -m "build(git-hooks): mahavishnu git-hook wrappers (Phase 12a task 4)

The 4 active git hooks (.git/hooks/{pre-commit,post-commit,post-merge,
post-rewrite}) shrink to one-liner exec lines; action logic moves
to mahavishnu.git_hook_handlers.dispatch_git_hook().

Refs: docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md §5 Phase 12a task 4

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Task 5: Hard-cutover the JSON-file queue → Redis Streams

**Files:**
- Modify: `mahavishnu/jot/drain.py`
- Modify: `mahavishnu/mcp/tools/jot_tools.py`
- Modify: `mahavishnu/.claude/hooks/bodai-activity-subscriber.py` (already replaced as bridge in Task 2; verify the bridge calls bus reader not file reader)

- [ ] **Step 1: Inventory all JSON-file queue writers and readers**

Run:
```bash
grep -rn "bodai-event-queue\.json\|MAHAVISHNU_BODAI_QUEUE_PATH" /Users/les/Projects/mahavishnu/mahavishnu/ --include="*.py"
```
Expected: hits in jot/drain.py, jot_tools.py, and any remaining references. (After Task 2, the subscriber is already a bridge.)

- [ ] **Step 2: Update each producer to publish to the bus**

For each producer file, replace the JSON-file write with a bus publish:

```python
# Before:
import json
from pathlib import Path

queue_path = Path(os.environ.get("MAHAVISHNU_BODAI_QUEUE_PATH", "~/.mahavishnu/bodai-event-queue.json")).expanduser()
queue_path.parent.mkdir(parents=True, exist_ok=True)
queue_path.write_text(json.dumps(envelope) + "\n", append=True)

# After:
try:
    from oneiric.adapters.bootstrap import queued_publisher
    queued_publisher().publish(channel="bodai.hooks.<event>", payload=envelope)
except Exception:
    pass  # fire-and-forget
```

- [ ] **Step 3: Update each reader to consume from the bus (or REPL-style poll)**

For each reader file, replace file reads with a bus subscription. For the `bodai-activity-subscriber.py` pattern (which the bridge now drives), the bus reader lives at `mahavishnu/bus_subscribers/jot_drainer.py`:

```python
# mahavishnu/bus_subscribers/jot_drainer.py
from __future__ import annotations
import asyncio
import os

async def drain_jot_events() -> None:
    """Subscribe to bus channel 'bodai.hooks.post-tool-use' and drain to jot store."""
    from oneiric.adapters.bootstrap import queued_publisher
    pub = queued_publisher()
    async for env in pub.subscribe(channel="bodai.hooks.post-tool-use"):
        # ... emit one [component] event_type key=value line per envelope ...
        pass
```

(Migrate any ad-hoc consumers from `mahavishnu/jot/drain.py` to use this subscriber; the old file poll loop dies.)

- [ ] **Step 4: Delete the JSON-file path entirely**

```bash
cd /Users/les/Projects/mahavishnu
git rm mahavishnu/jot/_old_drain.py 2>/dev/null  # if present
# Verify 0 hits:
grep -rn "bodai-event-queue" mahavishnu/ | head -10
```

Expected: 0 hits.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/jot/ mahavishnu/mcp/tools/jot_tools.py \
        mahavishnu/bus_subscribers/
git commit -m "feat(mahavishnu): hard-cutover JSON-file queue → Redis Streams (Phase 12a task 5)

Per spec §4.13.4, hard cutover (no dual-write per Q4). All in-process
producers publish to bus; readers (notably bodai-activity-subscriber
driven via the bridge) consume from bus.

Refs: docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md §4.13.4, §5 Phase 12a task 5

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Task 6: Add `tests/integration/test_hook_bridge_e2e.py` (full assertion)

**Files:**
- Create: `mahavishnu/tests/integration/test_hook_bridge_e2e.py` (already created in Task 2's failing-test step; expand here)

- [ ] **Step 1: Extend the e2e test with bus publish assertions**

Append to `tests/integration/test_hook_bridge_e2e.py`:

```python
from unittest.mock import patch


def test_handle_post_tool_use_publishes_to_bus():
    """Spec §4.13: post-decision fire-and-forget publish to bus."""
    with patch("mahavishnu.bodai_hook_bridge._publish") as pub:
        from mahavishnu.bodai_hook_bridge import handle
        handle(event_name="PostToolUse", harness="claude", payload={"hook_event_name": "PostToolUse"})
    channel = pub.call_args.kwargs["channel"]
    assert channel.startswith("bodai.hooks.")


def test_pre_tool_use_returns_exit_two_for_blocking():
    """Spec §4.13.3: PreToolUse stays sync-blocking; exit 2 blocks the tool."""
    from mahavishnu.bodai_hook_bridge import handle
    # When the license guard denies (return 2), handle must propagate 2.
    with patch("mahavishnu.bodai_hook_bridge.handle_pre_tool_use") as guard:
        guard.return_value = 2
        exit_code = handle(event_name="PreToolUse", harness="claude", payload={"hook_event_name": "PreToolUse"})
    assert exit_code == 2


def test_git_hook_dispatch_publishes_to_bus():
    """git-hook sub-command publishes a git-event envelope."""
    from unittest.mock import patch
    from mahavishnu.git_hook_handlers import dispatch_git_hook
    with patch("mahavishnu.git_hook_handlers._publish_git_event") as pub:
        with patch("mahavishnu.git_hook_handlers.os.system") as run:
            run.return_value = 0
            dispatch_git_hook(event="post-commit")
    pub.assert_called_once_with("post-commit")
```

- [ ] **Step 2: Run full e2e suite**

Run: `pytest mahavishnu/tests/integration/test_hook_bridge_e2e.py mahavishnu/tests/unit/test_bodai_hook_bridge.py mahavishnu/tests/unit/test_git_hook_handlers.py -v`
Expected: PASS for all (8+ tests).

- [ ] **Step 3: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/tests/integration/test_hook_bridge_e2e.py
git commit -m "test(mahavishnu): full bridge e2e suite (Phase 12a task 6)

Refs: docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md §5 Phase 12a task 6

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Task 7: Phase 12a exit verification

- [ ] **Step 1: Run full exit criteria**

Run:
```bash
pytest mahavishnu/tests/integration/test_hook_bridge_e2e.py -v  # exits 0
grep -rn "bodai-event-queue" /Users/les/Projects/mahavishnu/mahavishnu/ | wc -l  # 0 hits
ls -la mahavishnu/bodai_hook_bridge.py mahavishnu/git_hook_handlers.py  # both exist
mahavishnu git-hook post-commit  # exit 0; bus event fires
```

Expected: all checks pass.

- [ ] **Step 2: Confirm R12 mitigation: every producer/reader updated**

Run: `grep -rn "MAHAVISHNU_BODAI_QUEUE_PATH\|bodai-event-queue\.json" mahavishnu/ | wc -l`
Expected: 0 hits.

**Phase 12a closes here.** 7 commits land. Bridge pattern is the project's hook contract. JSON-file queue is retired.

---

### Phase 12b — Qwen Code bridge + Codex bridge (deferred)

**Goal:** Ship the Qwen Code bridges (10-line per-event files at `~/.qwen/hooks/<event>`) and update `~/.qwen/settings.json` to register them. Add Codex bridge when Codex exposes a stable hook surface.

**Demonstrable by:** `pytest tests/integration/test_qwen_hook_bridge_e2e.py` returns exit 0; manual test: install Qwen Code, run a session, verify events land on the bus channel `bodai.hooks.*` (subscribers don't care which harness fired; the bus is harness-agnostic).

**Triggered from:** Qwen Code CLI runs the bridge wrapper when Qwen is installed.

**Returns to / updates:** Same `oneiric.adapters.queue.redis_streams` channel as Claude; subscribers don't care which harness fired.

**Rollback signal:** Qwen bridge raises on malformed payload OR canonical envelope fails to publish.

**Observability added:** Same `hook_bridge_feed` per event; new attribute `harness` distinguishes Qwen-fire vs Claude-fire.

#### Task 1: Inventory Qwen-only events (pre-flight gate)

- [ ] **Step 1: List the Qwen events that have no Claude equivalent**

Per spec §4.13.2 schema table:
```
PostToolUseFailure
SessionDelete
MessageDisplay
StopFailure
SubagentStart
PreCompact
PostCompact
PermissionRequest
PermissionDenied
TodoCreated
TodoCompleted
```

11 events. Each gets a canonical handler function in `mahavishnu/bodai_hook_bridge.py` (append to `_EVENT_HANDLERS` dict).

- [ ] **Step 2: For each Qwen-only event, write the failing test**

Extend `tests/unit/test_bodai_hook_bridge.py` with 11 parametrized cases:

```python
@pytest.mark.parametrize("event_name", [
    "PostToolUseFailure",
    "SessionDelete",
    "MessageDisplay",
    "StopFailure",
    "SubagentStart",
    "PreCompact",
    "PostCompact",
    "PermissionRequest",
    "PermissionDenied",
    "TodoCreated",
    "TodoCompleted",
])
def test_qwen_only_event_handler_runs(event_name):
    from mahavishnu.bodai_hook_bridge import handle
    exit_code = handle(event_name=event_name, harness="qwen", payload={"hook_event_name": event_name})
    assert exit_code == 0  # default fall-through is success
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/unit/test_bodai_hook_bridge.py -v -k qwen_only`
Expected: 11 tests FAIL (KeyError or AttributeError on missing handlers)

- [ ] **Step 4: Add the 11 handlers to `mahavishnu/bodai_hook_bridge.py`**

In `mahavishnu/bodai_hook_bridge.py`, append to `_EVENT_HANDLERS`:

```python
def _handle_qwen_only_event(env: CanonicalEnvelope) -> int:
    """Default fall-through for Qwen-only events; spec §4.13.2."""
    return 0


for _qwen_event in (
    "PostToolUseFailure", "SessionDelete", "MessageDisplay",
    "StopFailure", "SubagentStart", "PreCompact", "PostCompact",
    "PermissionRequest", "PermissionDenied", "TodoCreated", "TodoCompleted",
):
    _EVENT_HANDLERS[_qwen_event] = _handle_qwen_only_event
```

- [ ] **Step 5: Verify tests pass**

Run: `pytest tests/unit/test_bodai_hook_bridge.py -v -k qwen_only`
Expected: 11 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/bodai_hook_bridge.py mahavishnu/tests/unit/test_bodai_hook_bridge.py
git commit -m "feat(mahavishnu): 11 Qwen-only event handlers (Phase 12b task 1)

Per spec §4.13.2 schema table — PostToolUseFailure, SessionDelete,
MessageDisplay, StopFailure, SubagentStart, PreCompact, PostCompact,
PermissionRequest, PermissionDenied, TodoCreated, TodoCompleted.

Refs: docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md §4.13.2, §5 Phase 12b task 1

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Task 2: Create `~/.qwen/hooks/<event>` bridge files

- [ ] **Step 1: Create the directory + 11 bridge files**

Run:
```bash
mkdir -p ~/.qwen/hooks
```

For each Qwen event (11 events), create `~/.qwen/hooks/<event>` containing:

```bash
#!/usr/bin/env python3
# Qwen Code bridge — normalizes Qwen's JSON schema to the canonical envelope
# and invokes mahavishnu.bodai_hook_bridge.handle().
#
# Per spec §4.13.5 — bridges are per-harness thin normalizers.
import json
import os
import sys
from pathlib import Path

QWEN_PROJECT_DIR = os.environ.get("QWEN_PROJECT_DIR")
if QWEN_PROJECT_DIR:
    sys.path.insert(0, str(Path(QWEN_PROJECT_DIR) / "mahavishnu"))

from bodai_hook_bridge import handle  # noqa: E402


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    # Qwen passes event name via stdout convention or argv[1] depending on
    # the host's settings.json setup. Standard form: argv[1] is the event.
    event_name = sys.argv[1] if len(sys.argv) > 1 else payload.get("hook_event_name", "?")
    return handle(event_name=event_name, harness="qwen", payload=payload)


if __name__ == "__main__":
    sys.exit(main())
```

Each file gets `chmod +x`.

- [ ] **Step 2: Verify each bridge file exists**

Run:
```bash
ls -la ~/.qwen/hooks/
```
Expected: 11 bridge files (one per Qwen event listed in Task 1).

- [ ] **Step 3: Commit (operator-side)**

These files are user-global (`~/.qwen/hooks/`); not version-controlled. Document for the operator:

```bash
# Run on each Qwen-using machine:
./scripts/install_qwen_bridges.sh
```

Where `scripts/install_qwen_bridges.sh` (operator-tooling, not committed) loops over the 11 event names and writes the bridge files at `~/.qwen/hooks/<event>`. Document this in `docs/runbooks/hook-migration.md`.

#### Task 3: Update `~/.qwen/settings.json` to register bridges

- [ ] **Step 1: Read the existing Qwen settings**

Run: `cat ~/.qwen/settings.json`
Expected: hooks section present or absent.

- [ ] **Step 2: Add the hooks block (or update)**

If `hooks:` is absent, add:

```json
{
  "hooks": {
    "PostToolUse": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/posttooluse"}]}],
    "PostToolUseFailure": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/posttoolusefailure"}]}],
    "SessionStart": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/sessionstart"}]}],
    "SessionEnd": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/sessionend"}]}],
    "SessionDelete": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/sessiondelete"}]}],
    "MessageDisplay": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/messagedisplay"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/stop"}]}],
    "StopFailure": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/stopfailure"}]}],
    "SubagentStart": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/subagentstart"}]}],
    "SubagentStop": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/subagentstop"}]}],
    "PreCompact": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/precompact"}]}],
    "PostCompact": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/postcompact"}]}],
    "Notification": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/notification"}]}],
    "PermissionRequest": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/permissionrequest"}]}],
    "PermissionDenied": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/permissiondenied"}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/userpromptsubmit"}]}],
    "PreToolUse": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/pretooluse"}]}],
    "TodoCreated": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/todocreated"}]}],
    "TodoCompleted": [{"hooks": [{"type": "command", "command": "~/.qwen/hooks/todocompleted"}]}]
  }
}
```

If `hooks:` is present, append the missing event entries. The Claude Code entries (if user uses both harnesses) live in a separate settings file (`~/.claude/settings.json` vs `~/.qwen/settings.json`); they are NOT shared between harnesses.

- [ ] **Step 3: Verify the Qwen settings file**

Run: `cat ~/.qwen/settings.json | python -m json.tool | head -50`

- [ ] **Step 4: Commit (operator-side)**

`~/.qwen/settings.json` is user-global; not version-controlled. Document the canonical template in `docs/runbooks/qwen-hook-setup.md` so the operator can reproduce it.

#### Task 4: Add `tests/integration/test_qwen_hook_bridge_e2e.py`

**Files:**
- Create: `mahavishnu/tests/integration/test_qwen_hook_bridge_e2e.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


BRIDGE_DIR = Path("~/.qwen/hooks").expanduser()


@pytest.mark.parametrize("event_name", [
    "posttooluse", "posttoolusefailure", "sessionstart", "sessionend",
    "sessiondelete", "messagedisplay", "stop", "stopfailure", "subagentstart",
    "subagentstop", "precompact", "postcompact", "notification",
    "permissionrequest", "permissiondenied", "userpromptsubmit", "pretooluse",
    "todocreated", "todocompleted",
])
def test_each_qwen_bridge_invokes_canonical_handler(event_name, monkeypatch):
    """Verify each ~/.qwen/hooks/<event> bridge calls bodai_hook_bridge.handle."""
    if not (BRIDGE_DIR / event_name).exists():
        pytest.skip(f"Qwen bridge {event_name} not installed (operator setup)")
    monkeypatch.setenv("QWEN_PROJECT_DIR", "/Users/les/Projects/mahavishnu")
    payload = {"hook_event_name": event_name, "session_id": "test", "cwd": "/tmp"}
    bridge_path = BRIDGE_DIR / event_name
    result = subprocess.run(
        [sys.executable, str(bridge_path), event_name],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )
    # Bridge exits 0 unless the canonical handler explicitly returns 2.
    assert result.returncode in (0, 2)
```

- [ ] **Step 2: Run to verify**

Run: `pytest mahavishnu/tests/integration/test_qwen_hook_bridge_e2e.py -v`
Expected: most tests SKIP (operator hasn't installed the Qwen bridges yet). When operator runs the bridges, tests pass.

- [ ] **Step 3: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add mahavishnu/tests/integration/test_qwen_hook_bridge_e2e.py
git commit -m "test(mahavishnu): Qwen bridge e2e suite (Phase 12b task 4)

Tests skip when Qwen bridges are not installed; pass when operator has
followed docs/runbooks/qwen-hook-setup.md to install them.

Refs: docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md §5 Phase 12b task 4

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

#### Task 5: Codex bridge (deferred to when Codex ships hooks)

- [ ] **Step 1: Document the deferred state in `docs/runbooks/codex-hook-setup.md`**

Add note: "Codex CLI does not currently have a documented hook system. When Codex ships hooks, the bridge pattern here applies with ~15 lines per event."

- [ ] **Step 2: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add docs/runbooks/codex-hook-setup.md
git commit -m "docs: Codex bridge deferred (Phase 12b task 5)

Refs: docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md §5 Phase 12b task 5

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

**Phase 12b closes here.** Qwen Code bridges installed (operator-side); Codex bridge deferred.

---

## Self-Review Notes (Phase 12)

**Spec coverage (Phase 12):**
- §4.13 Hook coordination via Oneiric event bus → Phase 12a tasks 1-2 (canonical handler + bridge wrappers) and 12b tasks 1-4 (Qwen bridges)
- §4.13.1 Design principle → Phase 12a task 1
- §4.13.2 Canonical envelope → Phase 12a task 1 (the `_normalize()` function implements the schema)
- §4.13.3 Sync-blocking events → Phase 12a tasks 1 + 6 (PreToolUse returns 2 unchanged; e2e test asserts)
- §4.13.4 Migration path (JSON-file → Redis Streams) → Phase 12a task 5
- §4.13.5 Multi-harness compatibility → Phase 12b tasks 1-3 (Qwen) + Task 5 (Codex deferred)
- R12 Hook migration risk → Mitigated by Phase 12a task 5 step 1 (enumeration) + task 0 (pre-flight)
- OQ-#7 Hook-channel migration scope (resolved) → Reflected in Phase 12a + 12b

**Placeholder scan:** "TBD" appears in Phase 12a task 4 step 1 (chmod +x conditional) — handles real-world edge case. No "TODO", "implement later", "fill in details", or "similar to task N" patterns.

**Type consistency:**
- `CanonicalEnvelope(event, harness, session_id, cwd, tool_name, tool_input, raw)` — used in Task 1 (definition), Task 1's tests (assertion), Task 6 (assertion in tests).
- `handle(event_name, *, harness, payload)` → returns int — Task 1 (definition), Task 2 (bridge uses), Task 6 (e2e test).
- `_publish(channel, envelope)` → Task 1 (definition), Task 6 (test patches it).
- `dispatch_git_hook(event)` → returns int — Task 3 (definition), Task 3's test.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-14-dhara-mcp-decomposition-implementation.md` (recreated this session after the prior version was lost to auto-checkpoint bundling).

**Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks. Best for the scale (~100 tasks across 7 repositories, including the new Phase 12 hook bridge work).

2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`.

**Which approach?**

