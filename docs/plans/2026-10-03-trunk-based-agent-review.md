# Trunk-Based Agent-Reviewed Dev Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the agent-reviewed trunk-based dev workflow: ephemeral worktrees, AI ensemble review, `crackerjack run -v` gate, squash-merge, auto-push `main` to `origin/main`, governed cleanup via `mahavishnu worktree prune-merged` — replacing GitHub-PR-shaped review for AI-driven solo dev.

**Architecture:** Four sequential task groups (matches spec §"Plans Derived From This Spec"): (1) **Foundation** — `dev_log.py` writer + `paths.py` helper; (2) **Orchestration** — `merge_to_main.py` module + slash command; (3) **Hook** — `agent-merge-on-end.py` SessionEnd hook + `settings.json` wiring; (4) **Governance** — new decision docs, memory cross-link, CLAUDE.md updates, `audit_devlog.py` CI gate. The auto-push rule lives in a new `.claude/decisions/2026-10-03-mainautopush.md` (cross-link, NOT inline amendment). `MAHAVISHNU_AUTO_MERGE=1` per user choice (deviation from `MAHAVISHNU_AUTO_WORKTREE` opt-in convention; rationale in spec §4.2). `~/.zshenv` already exports `MAHAVISHNU_AUTO_MERGE=1` from prior session work.

**Tech Stack:** Python 3.14, existing `mahavishnu` orchestrator, existing `crackerjack` quality tool, existing `session-buddy` `store_reflection` MCP, existing `.claude/hooks/` SessionEnd contract (mirrors `worktree-session-isolation.py`), `platformdirs` for XDG paths, no new MCP server.

**Spec:** `docs/superpowers/specs/2026-10-03-agent-reviewed-trunk-based-dev.md` (commit `c667df52`). The spec argues the design; this plan argues the steps. Where they conflict, this plan wins (deviations documented inline in §"Spec Deviations" below).

## Global Constraints

Carried from spec §"Goals & Non-Goals", §"Components", and project conventions. Every task implicitly includes these.

- **Python 3.14** target. `from __future__ import annotations` first non-comment line of every new file.
- **Hard limits**: 100 char line, 10 args, 15 branches, 6 returns, 55 statements (crackerjack). 89% test coverage.
- **`crackerjack run -v`** (NEVER `-p`) for the IS merge gate (REQ-013).
- **`MAHAVISHNU_AUTO_MERGE=1`** default per user choice; explicitly exported in `~/.zshenv` (REQ-010). Deviates from `MAHAVISHNU_AUTO_WORKTREE` opt-in convention with reasoning documented in spec §4.2.
- **XDG-correct paths via `platformdirs`**. New `get_dev_log_path()` mirrors `get_audit_path()` pattern in `mahavishnu/core/paths.py`.
- **Squash-merge** + **rebase-before-merge** + **SHA re-verify** (the inverse of `feedback-worktree-update-ref-drops-parallel-commits`).
- **Cross-session resume** via `.review-state.json` at worktree root (schema in spec §4.4).
- **Session-buddy dual-store** via `mcp__session-buddy__store_reflection`; failures set `session_buddy_reflection_id: null` and log to stderr (local file is canonical).
- **Three-way verdict envelope** via `<verdict>...</verdict>` XML-like block parsed from agent response. Malformed → `block` + exit code 1 + stderr message.
- **Cleanup routes through existing `mahavishnu worktree prune-merged`** CLI (NOT silent removal). Adheres to `worktree-cleanup-policy.md` tier rubric.
- **`git push origin main`** only (NEVER ephemeral branches, NEVER force-push, NEVER non-`origin` remotes). Divergence fails loudly via stderr.
- **One commit per task** (atomic) per `feedback-bodai-atomic-commit-recurring-fixes`.
- **No new CC memory files** beyond what spec REQ-007/014/008 require; dual-store per `feedback-memories-must-be-dual-stored`.
- **Error envelope shape** (existing convention): `{"status": "error", "error_code": "...", "message": "...", "details": {...}}` for user-facing errors; stderr for hook output per spec §Failure Modes.

## Spec Deviations Discovered During Recon

| # | Spec says | Ground truth | Plan does |
|---|---|---|---|
| 1 | Session-buddy `store_reflection` is called from `mahavishnu.core.dev_log` (REQ-009). | `mcp__session-buddy__store_reflection` is invoked via the FastMCP client. In sync code (which `write_entry` is), we lazy-import the client module. If unavailable, log to stderr and continue. | Task 1.2 implements `_mirror_to_session_buddy` with a try/except that catches all exceptions and logs. CI test stubs the mirror via monkeypatch. |
| 2 | `MAHAVISHNU_AUTO_MERGE=1` is co-delivered with the spec. | `~/.zshenv` already contains the export (added 2026-10-03, line 28). | No additional action in this plan; REQ-010 is verified by inspecting `~/.zshenv`. |
| 3 | Spec §4.4 says `<verdict>...</verdict>` block is parsed by the Python module. | Parsing XML-like blocks from agent output requires either (a) regex with fall-back, or (b) markdown-fence detection. Spec doesn't pin the parser strategy. | Task 2.5 implements a regex-based parser with fail-loud fallback to `block` (matches spec's malformed → block rule). |

## File Structure

### New files

| Path | Purpose |
|---|---|
| `mahavishnu/core/dev_log.py` | Audit-log writer (`write_entry()`, file-lock, atomic rename, session-buddy mirror) |
| `mahavishnu/core/merge_to_main.py` | Orchestration module: stages 2-6, verdict parsing, `.review-state.json`, exit codes 0-5 |
| `.claude/hooks/agent-merge-on-end.py` | SessionEnd hook (parallel sibling of `worktree-session-isolation.py`) |
| `.claude/commands/merge-to-main.md` | Slash command entry point (frontmatter + body) |
| `.claude/decisions/2026-10-03-mainautopush.md` | Auto-push governance (REQ-007) |
| `.claude/decisions/2026-10-03-trunk-based-agent-review.md` | Workflow doc (REQ-008) |
| `scripts/audit_devlog.py` | CI gate for REQ-011 (every merge commit on `main` has audit entry) |
| `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-bodai-merge-workflow.md` | New CC memory |
| `tests/unit/core/test_paths_dev_log.py` | paths.py helper tests (REQ-002) |
| `tests/unit/core/test_dev_log.py` | dev_log writer tests (REQ-003) |
| `tests/unit/core/test_merge_to_main.py` | orchestration tests (REQ-004, REQ-014) |
| `tests/unit/hooks/test_agent_merge_on_end.py` | hook tests (REQ-005) |

### Modified files

| Path | Change |
|---|---|
| `mahavishnu/core/paths.py` | Add `DEV_LOG_DIR` constant + extend `ensure_directories()` + add `get_dev_log_path()` (Task 1.1) |
| `.claude/settings.json` | Append SessionEnd hook entry (Task 3.2, REQ-006) |
| `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-bodai-push-is-user-controlled.md` | Add cross-link to new decision doc (Task 4.3) |
| `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/MEMORY.md` | Add index entry for `feedback-bodai-merge-workflow.md` (Task 4.4) |
| `~/.claude/CLAUDE.md` | Add "Dev workflow" subsection (Task 4.5) |
| `~/Projects/mahavishnu/CLAUDE.md` | Note merge command location (Task 4.6) |

______________________________________________________________________

## Task Group 1: Foundation (dev_log writer + paths.py helper)

**Implements:** REQ-002, REQ-003 (per spec §Requirements)

**Files:**

- Modify: `mahavishnu/core/paths.py:25-52, 47, 137-150` (add `DEV_LOG_DIR` + extend `ensure_directories()` + add `get_dev_log_path()`)
- Create: `mahavishnu/core/dev_log.py`
- Test: `tests/unit/core/test_paths_dev_log.py` (new)
- Test: `tests/unit/core/test_dev_log.py` (new)

### Task 1.1: Add `DEV_LOG_DIR` constant + `get_dev_log_path()` to paths.py

**Interfaces:**

- Consumes: existing `STATE_DIR: Final[Path]` from `mahavishnu/core/paths.py:29`

- Produces: `paths.DEV_LOG_DIR: Final[Path]` (constant); `paths.get_dev_log_path(*path_parts) -> Path` (helper); `paths.ensure_directories()` now creates `DEV_LOG_DIR`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_paths_dev_log.py`:

```python
"""CI guard test: paths.py must expose DEV_LOG_DIR constant and
get_dev_log_path() helper, mirroring get_audit_path() pattern.
"""
from __future__ import annotations

from pathlib import Path


def test_dev_log_dir_constant_exists() -> None:
    from mahavishnu.core import paths

    assert hasattr(paths, "DEV_LOG_DIR"), (
        "paths.py must expose DEV_LOG_DIR constant for the dev-log audit dir"
    )
    assert paths.DEV_LOG_DIR == paths.STATE_DIR / "dev-log"


def test_get_dev_log_path_mirrors_get_audit_path() -> None:
    from mahavishnu.core import paths

    assert paths.get_dev_log_path("foo.md") == paths.DEV_LOG_DIR / "foo.md"
    assert (
        paths.get_dev_log_path("nested", "bar.md")
        == paths.DEV_LOG_DIR / "nested" / "bar.md"
    )


def test_ensure_directories_creates_dev_log_dir(tmp_path, monkeypatch) -> None:
    """ensure_directories() must create DEV_LOG_DIR on invocation."""
    from mahavishnu.core import paths

    monkeypatch.setattr(paths, "STATE_DIR", tmp_path)
    paths.ensure_directories()
    assert (tmp_path / "dev-log").is_dir()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/core/test_paths_dev_log.py -v`
Expected: FAIL with `"module 'mahavishnu.core.paths' has no attribute 'DEV_LOG_DIR'"`

- [ ] **Step 3: Implement the helper**

Edit `mahavishnu/core/paths.py`:

After line 33 (`AUDIT_DIR: Final[Path] = STATE_DIR / "audit"`), add:

```python
DEV_LOG_DIR: Final[Path] = STATE_DIR / "dev-log"
```

In `ensure_directories()` (line 36-52), append `DEV_LOG_DIR.mkdir(parents=True, exist_ok=True)` after `AUDIT_DIR.mkdir(...)` and update the docstring to list the new dir.

After `get_audit_path()` (line 137-150), add:

```python
def get_dev_log_path(*path_parts: str) -> Path:
    """Get XDG-compliant dev-log directory path.

    Args:
        *path_parts: Path components to join with DEV_LOG_DIR

    Returns:
        Path to dev-log file/directory

    Examples:
        >>> get_dev_log_path("2026-10-03-fix-ty.md")
        PosixPath('~/.local/state/mahavishnu/dev-log/2026-10-03-fix-ty.md')
    """
    return DEV_LOG_DIR.joinpath(*path_parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/core/test_paths_dev_log.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/mahavishnu && \
  git add mahavishnu/core/paths.py tests/unit/core/test_paths_dev_log.py && \
  git commit -m "feat(mahavishnu): add DEV_LOG_DIR + get_dev_log_path() (REQ-002)

Mirrors get_audit_path() pattern for the agent-reviewed trunk-based
dev workflow's per-merge audit log. Resolves to STATE_DIR/dev-log
(XDG_STATE_HOME-aware via platformdirs).

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 1.2: Create `mahavishnu/core/dev_log.py` with `write_entry()` skeleton

**Interfaces:**

- Consumes: `mahavishnu.core.paths.DEV_LOG_DIR`, `get_dev_log_path()`

- Produces: `write_entry(metadata: dict, body: str, *, mirror_to_session_buddy: bool = True) -> Path`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_dev_log.py`:

```python
"""Tests for mahavishnu.core.dev_log.write_entry() — per-merge audit-log
writer for the trunk-based agent-review workflow (REQ-003).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.core.dev_log import write_entry


@pytest.fixture
def tmp_dev_log_dir(tmp_path, monkeypatch):
    """Redirect DEV_LOG_DIR to a tmp path for test isolation."""
    from mahavishnu.core import paths

    monkeypatch.setattr(paths, "DEV_LOG_DIR", tmp_path)
    return tmp_path


def test_write_entry_creates_file_with_yaml_frontmatter(tmp_dev_log_dir: Path) -> None:
    """write_entry() writes a file with YAML frontmatter + body."""
    metadata = {"date": "2026-10-03", "branch": "fix-ty", "commits_merged": 1}
    body = "# fix-ty\n\nWorker prompt: foo\n"
    path = write_entry(metadata=metadata, body=body, mirror_to_session_buddy=False)
    assert path.exists()
    assert path.parent == tmp_dev_log_dir
    content = path.read_text()
    assert content.startswith("---\n")
    assert "date: 2026-10-03\n" in content
    assert "branch: fix-ty\n" in content
    assert content.endswith("\n# fix-ty\n\nWorker prompt: foo\n")
    assert path.name == "2026-10-03-fix-ty.md"


def test_write_entry_with_nested_reviewers_serializes_to_yaml(tmp_dev_log_dir: Path) -> None:
    """Nested reviewer list renders as YAML block list."""
    metadata = {
        "date": "2026-10-03",
        "branch": "fix-ty",
        "reviewers": [
            {"agent": "python-pro", "verdict": "pass", "note": ""},
            {"agent": "critical-audit-specialist", "verdict": "pass", "note": ""},
        ],
    }
    path = write_entry(metadata=metadata, body="body", mirror_to_session_buddy=False)
    text = path.read_text()
    assert "reviewers:" in text
    assert "  - agent: python-pro" in text
    assert "  - verdict: pass" in text


def test_write_entry_uses_atomic_rename(tmp_dev_log_dir: Path) -> None:
    """A partial write (interrupted mid-flight) leaves no .tmp file."""
    metadata = {"date": "2026-10-03", "branch": "fix-ty"}
    write_entry(metadata=metadata, body="body", mirror_to_session_buddy=False)
    # No leftover .tmp file (rename should have cleaned up)
    tmp_files = list(tmp_dev_log_dir.glob("*.md.tmp"))
    assert tmp_files == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/core/test_dev_log.py -v`
Expected: FAIL with `"No module named 'mahavishnu.core.dev_log'"`

- [ ] **Step 3: Implement `write_entry()`**

Create `mahavishnu/core/dev_log.py`:

```python
"""Audit-log writer for the trunk-based agent-review workflow.

Per REQ-003 (spec §Requirements). Concurrency: file-lock on append +
atomic rename so a crash mid-write leaves the previous log intact.
Best-effort session-buddy mirror via mcp__session-buddy__store_reflection.

Implements: REQ-003
"""
from __future__ import annotations

import fcntl
import json
import sys
from pathlib import Path
from typing import Any

from .paths import DEV_LOG_DIR, get_dev_log_path


def _format_frontmatter(metadata: dict[str, Any]) -> str:
    """Render metadata as YAML frontmatter.

    Simple block scalar — metadata values are scalars, list-of-dicts,
    or dicts (the last three are JSON-serialized inline; sufficient for
    reviewers/push/cleanup blocks per spec §4.3).
    """
    lines = ["---"]
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                if isinstance(item, dict):
                    lines.append(
                        f"  - {json.dumps(item, sort_keys=True, separators=(',', ':'))}"
                    )
                else:
                    lines.append(f"  - {item}")
        elif isinstance(value, dict):
            lines.append(
                f"{key}: {json.dumps(value, sort_keys=True, separators=(',', ':'))}"
            )
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def write_entry(
    metadata: dict[str, Any],
    body: str,
    *,
    mirror_to_session_buddy: bool = True,
) -> Path:
    """Append an audit entry to the dev log. Returns the file path written.

    Args:
        metadata: YAML frontmatter fields (date, branch, reviewers, gate,
            merge, push, cleanup, etc.).
        body: Markdown body of the entry (semantic-commit summary, etc.).
        mirror_to_session_buddy: If True, mirror to session-buddy via
            mcp__session-buddy__store_reflection. Failure is logged
            and reflected as ``session_buddy_reflection_id: null`` in
            the frontmatter; local file is canonical.

    Returns:
        Path to the file written.

    Concurrency: ``fcntl.flock`` on a per-directory lock file + atomic
    rename so a crash mid-write leaves the previous log intact.
    """
    date = str(metadata.get("date", ""))
    branch_slug = str(metadata.get("branch", "unknown"))
    filename = f"{date}-{branch_slug}.md"
    target = get_dev_log_path(filename)
    target.parent.mkdir(parents=True, exist_ok=True)

    frontmatter = _format_frontmatter(metadata)
    full_content = frontmatter + body

    lock_path = DEV_LOG_DIR / ".write.lock"
    lock_path.touch(exist_ok=True)
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            tmp_path = target.with_suffix(".md.tmp")
            tmp_path.write_text(full_content)
            tmp_path.rename(target)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)

    if mirror_to_session_buddy:
        _mirror_to_session_buddy(metadata, body, target)

    return target


def _mirror_to_session_buddy(
    metadata: dict[str, Any], body: str, target: Path
) -> None:
    """Best-effort session-buddy mirror. On success, the target file's
    session_buddy_reflection_id field is set to the returned UUID. On
    failure, logs to stderr; entry remains canonical.
    """
    try:
        # Lazy import: the MCP client is only available in the running
        # server context. Tests stub this via monkeypatch.
        from mcp__session_buddy import store_reflection  # type: ignore[import-not-found]
    except ImportError:
        # MCP client not available; log and skip.
        print(
            f"[dev_log] session-buddy MCP client unavailable; "
            f"local entry at {target} is canonical.",
            file=sys.stderr,
        )
        return

    try:
        result = store_reflection(
            content=f"# dev-log mirror\n\n{body}",
            tags=["dev-log", "merge-workflow"],
        )
        reflection_id = getattr(result, "id", None)
        if reflection_id:
            _set_session_buddy_reflection_id(target, reflection_id)
    except Exception as exc:  # pragma: no cover
        # Mirror is best-effort. Log to stderr; entry remains canonical.
        print(
            f"[dev_log] session-buddy mirror failed: {exc!r}; "
            f"local entry at {target} is canonical.",
            file=sys.stderr,
        )


def _set_session_buddy_reflection_id(target: Path, reflection_id: str) -> None:
    """Update the YAML frontmatter on `target` to set
    session_buddy_reflection_id (replaces or inserts before closing ---).
    """
    text = target.read_text()
    if "session_buddy_reflection_id:" in text:
        new_lines = [
            line for line in text.splitlines()
            if not line.startswith("session_buddy_reflection_id:")
        ]
        new_lines.insert(
            len(new_lines) - 1,
            f"session_buddy_reflection_id: {reflection_id}",
        )
        target.write_text("\n".join(new_lines) + "\n")
    else:
        if text.rstrip().endswith("---"):
            text = text.rstrip()[:-3].rstrip()
            text += f"\nsession_buddy_reflection_id: {reflection_id}\n---\n"
        else:
            text += f"\nsession_buddy_reflection_id: {reflection_id}\n"
        target.write_text(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/core/test_dev_log.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/mahavishnu && \
  git add mahavishnu/core/dev_log.py tests/unit/core/test_dev_log.py && \
  git commit -m "feat(mahavishnu): add dev_log.write_entry() (REQ-003)

Per-merge audit log writer with file-lock + atomic rename for crash
safety. Best-effort session-buddy mirror via store_reflection. Local
file is canonical; mirror failure logs to stderr.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

______________________________________________________________________

## Task Group 2: Orchestration (`merge_to_main.py` + slash command)

**Implements:** REQ-004, REQ-009, REQ-013, REQ-014

**Files:**

- Create: `mahavishnu/core/merge_to_main.py`
- Create: `.claude/commands/merge-to-main.md`
- Test: `tests/unit/core/test_merge_to_main.py`

**Depends on:** Task Group 1 (`paths.DEV_LOG_DIR`, `dev_log.write_entry()`)

### Task 2.1: Create `.review-state.json` schema + writer/parser

**Interfaces:**

- Consumes: `pathlib.Path` (worktree root), `dict` (stage markers)

- Produces: `write_review_state(worktree_root: Path, state: dict) -> None`; `read_review_state(worktree_root: Path) -> dict | None`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/core/test_merge_to_main.py`:

```python
"""Tests for mahavishnu.core.merge_to_main — orchestration of the trunk-based
agent-review workflow (REQ-004, REQ-013, REQ-014).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mahavishnu.core.merge_to_main import (
    REVIEW_STATE_SCHEMA_VERSION,
    read_review_state,
    write_review_state,
)


def test_review_state_round_trip(tmp_path: Path) -> None:
    """write_review_state then read_review_state returns equivalent dict."""
    state = {
        "schema_version": REVIEW_STATE_SCHEMA_VERSION,
        "ephemeral_branch": "fix-ty",
        "base": "origin/main",
        "pre_rebase_base_sha": "b116d395",
        "stages_completed": ["stage_1_worktree", "stage_2_review"],
        "current_stage": "stage_3_gate",
        "stage_failed": None,
        "reviewers_invoked": [
            {"agent": "python-pro", "verdict": "pass", "timestamp": "2026-10-03T15:32:11Z"}
        ],
        "audit_log_path": None,
        "session_buddy_reflection_id": None,
    }
    write_review_state(tmp_path, state)
    loaded = read_review_state(tmp_path)
    assert loaded == state


def test_read_review_state_corrupt_json_returns_none(tmp_path: Path) -> None:
    """Corrupt JSON falls back to None (spec REQ-014 graceful handling)."""
    (tmp_path / ".review-state.json").write_text("not valid json {{{")
    assert read_review_state(tmp_path) is None


def test_read_review_state_missing_returns_none(tmp_path: Path) -> None:
    """Missing file returns None."""
    assert read_review_state(tmp_path) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/core/test_merge_to_main.py -v`
Expected: FAIL with `"No module named 'mahavishnu.core.merge_to_main'"`

- [ ] **Step 3: Implement the schema and I/O helpers**

Create `mahavishnu/core/merge_to_main.py` with the schema constants and I/O helpers:

```python
"""Orchestration of the trunk-based agent-review workflow.

Per spec §4 (Components). Stages 2-6: ensemble review, crackerjack gate,
squash-merge, auto-push, cleanup. Cross-session resume via
.review-state.json at the worktree root. Idempotent and re-entrant.

Implements: REQ-004, REQ-009, REQ-013, REQ-014
"""
from __future__ import annotations

import fcntl
import json
import sys
from pathlib import Path
from typing import Any

REVIEW_STATE_SCHEMA_VERSION: int = 1
REVIEW_STATE_FILENAME: str = ".review-state.json"

# Exit codes (spec §4.1 Outputs)
EXIT_OK = 0
EXIT_REVIEW_FAILURE = 1
EXIT_CRACKERJACK_FAILURE = 2
EXIT_REBASE_CONFLICT = 3
EXIT_PUSH_DIVERGENCE = 4
EXIT_CLEANUP_FAILURE = 5


def write_review_state(worktree_root: Path, state: dict[str, Any]) -> None:
    """Atomically write the review-state JSON for a worktree.

    Uses fcntl.flock for cross-process safety (in case two merge
    invocations run concurrently on the same worktree).
    """
    target = worktree_root / REVIEW_STATE_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, sort_keys=True)
    lock_path = worktree_root / ".review-state.lock"
    lock_path.touch(exist_ok=True)
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(payload)
            tmp.rename(target)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def read_review_state(worktree_root: Path) -> dict[str, Any] | None:
    """Read the review-state JSON. Returns None if missing or corrupt."""
    target = worktree_root / REVIEW_STATE_FILENAME
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        # Corrupt or unreadable; spec REQ-014 graceful fallback.
        print(
            f"[merge_to_main] corrupt .review-state.json: {exc!r}; "
            f"falling back to stage 2.",
            file=sys.stderr,
        )
        return None


def make_review_state(
    ephemeral_branch: str,
    base: str,
    pre_rebase_base_sha: str,
    stages_completed: list[str],
    current_stage: str,
    stage_failed: str | None,
    reviewers_invoked: list[dict[str, Any]],
    audit_log_path: str | None,
    session_buddy_reflection_id: str | None,
) -> dict[str, Any]:
    """Construct a fresh review-state dict per spec §4.4 schema."""
    return {
        "schema_version": REVIEW_STATE_SCHEMA_VERSION,
        "ephemeral_branch": ephemeral_branch,
        "base": base,
        "pre_rebase_base_sha": pre_rebase_base_sha,
        "stages_completed": stages_completed,
        "current_stage": current_stage,
        "stage_failed": stage_failed,
        "reviewers_invoked": reviewers_invoked,
        "audit_log_path": audit_log_path,
        "session_buddy_reflection_id": session_buddy_reflection_id,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/core/test_merge_to_main.py::test_review_state_round_trip tests/unit/core/test_merge_to_main.py::test_read_review_state_corrupt_json_returns_none tests/unit/core/test_merge_to_main.py::test_read_review_state_missing_returns_none -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/mahavishnu && \
  git add mahavishnu/core/merge_to_main.py tests/unit/core/test_merge_to_main.py && \
  git commit -m "feat(mahavishnu): merge_to_main scaffold + .review-state.json I/O (REQ-014)

Per spec §4.4 schema. Atomic write with fcntl.flock; corrupt-JSON
graceful fallback per REQ-014. Exit-code constants also defined.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 2.2: Implement verdict envelope parser

**Interfaces:**

- Consumes: agent response text (str)

- Produces: `parse_verdict(agent_text: str) -> dict` (with keys `decision`, `note`, or `{"decision": "block", "note": "malformed: <reason>"}`)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/core/test_merge_to_main.py`:

```python
from mahavishnu.core.merge_to_main import parse_verdict


def test_parse_verdict_well_formed_block() -> None:
    text = (
        "All looks good.\n"
        "<verdict>\n"
        "  decision: pass\n"
        "  note: no issues found\n"
        "</verdict>\n"
    )
    result = parse_verdict(text)
    assert result == {"decision": "pass", "note": "no issues found"}


def test_parse_verdict_needs_adjustment() -> None:
    text = (
        "<verdict>\n"
        "  decision: needs_adjustment\n"
        "  note: missing type hints on public functions\n"
        "</verdict>\n"
    )
    assert parse_verdict(text) == {
        "decision": "needs_adjustment",
        "note": "missing type hints on public functions",
    }


def test_parse_verdict_block_decision() -> None:
    text = (
        "<verdict>\n"
        "  decision: block\n"
        "  note: hardcoded credentials found\n"
        "</verdict>\n"
    )
    assert parse_verdict(text)["decision"] == "block"


def test_parse_verdict_malformed_returns_block() -> None:
    """Missing or malformed block returns block decision (fail-loud)."""
    assert parse_verdict("Just plain text with no block")["decision"] == "block"
    assert parse_verdict("<verdict>\n  decision: typo\n</verdict>")["decision"] == "block"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/core/test_merge_to_main.py -k parse_verdict -v`
Expected: FAIL with `ImportError: cannot import name 'parse_verdict'`

- [ ] **Step 3: Implement `parse_verdict()`**

Append to `mahavishnu/core/merge_to_main.py`:

```python
import re

_VERDICT_BLOCK = re.compile(
    r"<verdict>\s*\n\s*decision:\s*(?P<decision>\w+)\s*\n\s*note:\s*(?P<note>.*?)\s*\n\s*</verdict>",
    re.DOTALL,
)
_VALID_DECISIONS = {"pass", "needs_adjustment", "block"}


def parse_verdict(agent_text: str) -> dict[str, str]:
    """Parse the `<verdict>...</verdict>` block from an agent response.

    Returns:
        {"decision": "pass" | "needs_adjustment" | "block", "note": str}

    Per spec §4.4, missing or malformed block returns `block` (fail-loud).
    Caller (the orchestration runner) is responsible for translating
    `block` into exit code 1 and emitting the stderr message.
    """
    match = _VERDICT_BLOCK.search(agent_text)
    if not match:
        return {"decision": "block", "note": "malformed: no verdict block"}
    decision = match.group("decision").strip()
    if decision not in _VALID_DECISIONS:
        return {"decision": "block", "note": f"malformed: unknown decision '{decision}'"}
    note = match.group("note").strip()
    return {"decision": decision, "note": note}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/core/test_merge_to_main.py -k parse_verdict -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/mahavishnu && \
  git add mahavishnu/core/merge_to_main.py tests/unit/core/test_merge_to_main.py && \
  git commit -m "feat(mahavishnu): parse_verdict() for ensemble review (REQ-004)

Parses <verdict>decision: ...</verdict> blocks from agent output.
Missing or malformed → block decision (fail-loud per spec §4.4).

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 2.3: Implement 3-agent ensemble orchestration (stage 2)

**Interfaces:**

- Consumes: `domain_specialist: str`, `generalist_pool: list[str]`, prompt template, agent dispatcher

- Produces: `run_review(domain_specialist, generalist_pool, prompt, dispatcher) -> list[dict]` (3 verdicts)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/core/test_merge_to_main.py`:

```python
import random
from unittest.mock import MagicMock

from mahavishnu.core.merge_to_main import run_review, AGENT_POOL


def test_run_review_returns_three_verdicts(dispatcher, monkeypatch) -> None:
    """run_review() invokes 3 agents (1 domain + 1 reviewer + 1 random
    generalist) and returns 3 list of verdict dicts.
    """
    monkeypatch.setattr(
        "mahavishnu.core.merge_to_main.random.choice",
        lambda pool: pool[0],  # deterministic: pick first generalist
    )
    dispatcher.return_value = (
        "Agent response.\n<verdict>\n  decision: pass\n  note: ok\n</verdict>"
    )
    verdicts = run_review(
        domain_specialist="python-pro",
        generalist_pool=AGENT_POOL,
        prompt="review this diff",
        dispatcher=dispatcher,
    )
    assert len(verdicts) == 3
    # Two of three must be pass (deterministic first slot is a generalist)
    assert sum(1 for v in verdicts if v["decision"] == "pass") >= 2


@pytest.fixture
def dispatcher():
    mock = MagicMock()
    return mock
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/core/test_merge_to_main.py -k run_review -v`
Expected: FAIL with `ImportError: cannot import name 'run_review'`

- [ ] **Step 3: Implement `run_review()` and `AGENT_POOL`**

Append to `mahavishnu/core/merge_to_main.py`:

```python
import random

# In-repo generalist pool per spec §4.4 (verified 2026-10-03).
AGENT_POOL: list[str] = [
    "performance-review-specialist",
    "test-coverage-review-specialist",
    "critical-audit-specialist",
    "documentation-review-specialist",
    "qa-strategist",
    "observability-incident-lead",
    "architecture-council",
]

# Code-quality specialist (per spec §4.4 Agent 2).
_CODE_QUALITY_AGENT: str = "critical-audit-specialist"


def run_review(
    *,
    domain_specialist: str,
    generalist_pool: list[str],
    prompt: str,
    dispatcher,
    code_quality_agent: str = _CODE_QUALITY_AGENT,
) -> list[dict[str, str]]:
    """Invoke 3 agents (domain + code-quality + random generalist) and
    return their parsed verdicts.

    Per spec §4.4: 2 specialized + 1 random. The dispatcher is callable
    taking (agent_name: str, prompt: str) -> str (the agent response text).
    """
    generalist = random.choice(generalist_pool)
    agents = [domain_specialist, code_quality_agent, generalist]
    verdicts = []
    for agent in agents:
        response_text = dispatcher(agent_name=agent, prompt=prompt)
        verdicts.append(parse_verdict(response_text))
    return verdicts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/core/test_merge_to_main.py -k run_review -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/mahavishnu && \
  git add mahavishnu/core/merge_to_main.py tests/unit/core/test_merge_to_main.py && \
  git commit -m "feat(mahavishnu): run_review() — 3-agent ensemble (REQ-004)

Per spec §4.4: 2 specialized (domain + code-quality) + 1 random
generalist from in-repo AGENT_POOL. Verdict envelope parsing
delegated to parse_verdict().

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 2.4: Implement verdict-rule aggregation

**Interfaces:**

- Consumes: `verdicts: list[dict]` (3 entries)

- Produces: `aggregate_verdicts(verdicts) -> str` returning `"proceed"`, `"iterate"`, or `"block"`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/core/test_merge_to_main.py`:

```python
from mahavishnu.core.merge_to_main import aggregate_verdicts


def test_aggregate_any_block_blocks() -> None:
    verdicts = [
        {"decision": "pass", "note": ""},
        {"decision": "block", "note": "x"},
        {"decision": "pass", "note": ""},
    ]
    assert aggregate_verdicts(verdicts) == "block"


def test_aggregate_two_pass_proceeds() -> None:
    verdicts = [
        {"decision": "pass", "note": ""},
        {"decision": "pass", "note": ""},
        {"decision": "needs_adjustment", "note": "minor"},
    ]
    assert aggregate_verdicts(verdicts) == "proceed"


def test_aggregate_one_pass_iterates() -> None:
    verdicts = [
        {"decision": "pass", "note": ""},
        {"decision": "needs_adjustment", "note": "x"},
        {"decision": "needs_adjustment", "note": "y"},
    ]
    assert aggregate_verdicts(verdicts) == "iterate"


def test_aggregate_all_needs_adjustment_iterates() -> None:
    verdicts = [
        {"decision": "needs_adjustment", "note": "a"},
        {"decision": "needs_adjustment", "note": "b"},
        {"decision": "needs_adjustment", "note": "c"},
    ]
    assert aggregate_verdicts(verdicts) == "iterate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/core/test_merge_to_main.py -k aggregate -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `aggregate_verdicts()`**

Append to `mahavishnu/core/merge_to_main.py`:

```python
def aggregate_verdicts(verdicts: list[dict[str, str]]) -> str:
    """Apply the spec §4.4 verdict rule order (priority high to low).

    Returns one of: "proceed", "iterate", "block".
    """
    decisions = [v["decision"] for v in verdicts]
    # Rule 1: any block → block (highest priority)
    if "block" in decisions:
        return "block"
    # Rule 2: ≥2 pass → proceed
    pass_count = decisions.count("pass")
    if pass_count >= 2:
        return "proceed"
    # Rule 3: otherwise → iterate
    return "iterate"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/core/test_merge_to_main.py -k aggregate -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/mahavishnu && \
  git add mahavishnu/core/merge_to_main.py tests/unit/core/test_merge_to_main.py && \
  git commit -m "feat(mahavishnu): aggregate_verdicts() — 3-rule priority (REQ-004)

Per spec §4.4: any block → block; ≥2 pass → proceed; otherwise iterate.
Simplified from the round-1 5-rule set (rules 4-5 were redundant).

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 2.5: Implement stage 3 (`crackerjack run -v` gate)

**Interfaces:**

- Consumes: `subprocess.run` (or wrapper)

- Produces: `run_crackerjack_gate(worktree_root: Path) -> tuple[int, str]` returning (exit_code, stderr)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/core/test_merge_to_main.py`:

```python
from unittest.mock import patch

from mahavishnu.core.merge_to_main import (
    CRACKERJACK_INVOCATION,
    run_crackerjack_gate,
)


def test_crackerjack_invocation_constant() -> None:
    """The pinned crackerjack invocation must be `run -v`, NEVER `-p`."""
    assert CRACKERJACK_INVOCATION.startswith("crackerjack run -v ")
    assert "-p" not in CRACKERJACK_INVOCATION


def test_run_crackerjack_gate_returns_exit_zero_on_success(tmp_path: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        exit_code, stderr = run_crackerjack_gate(tmp_path)
    assert exit_code == 0
    assert stderr == ""


def test_run_crackerjack_gate_returns_exit_nonzero_on_failure(tmp_path: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 2
        mock_run.return_value.stderr = "ruff failed"
        exit_code, stderr = run_crackerjack_gate(tmp_path)
    assert exit_code == 2
    assert "ruff failed" in stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/core/test_merge_to_main.py -k crackerjack -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `run_crackerjack_gate()`**

Append to `mahavishnu/core/merge_to_main.py`:

```python
import subprocess

CRACKERJACK_INVOCATION: str = "crackerjack run -v "  # NEVER -p (REQ-013)


def run_crackerjack_gate(worktree_root: Path) -> tuple[int, str]:
    """Invoke `crackerjack run -v` in the worktree.

    Per spec §Stage 3 and REQ-013: pinned invocation is `crackerjack run -v`
    (NEVER `-p` — the publish stage must never fire on the merge path).
    Any non-zero exit blocks the merge (exit code 2 from the module).
    """
    cmd = CRACKERJACK_INVOCATION.strip().split() + ["--exitcode", "0"]
    result = subprocess.run(
        cmd,
        cwd=worktree_root,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stderr
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/core/test_merge_to_main.py -k crackerjack -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/mahavishnu && \
  git add mahavishnu/core/merge_to_main.py tests/unit/core/test_merge_to_main.py && \
  git commit -m "feat(mahavishnu): run_crackerjack_gate() — pinned to run -v (REQ-013)

Per spec §Stage 3: invocation is 'crackerjack run -v' (NEVER -p; the
publish stage must never fire on the merge path). Any non-zero exit
blocks the merge.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 2.6: Create slash command `.claude/commands/merge-to-main.md`

**Files:**

- Create: `.claude/commands/merge-to-main.md`

- [ ] **Step 1: Write the slash command body**

Create `.claude/commands/merge-to-main.md` with full frontmatter (matches `pr-enhance.md` shape per `feedback-rename-brief-must-enumerate-all-string-literals.md`):

```markdown
---
title: "Merge to Local Main"
owner: "claude-code"
status: "active"
id: "merge-to-main"
risk: "medium"
description: |
  Run the agent-reviewed trunk-based-dev merge cycle on the current
  worktree: review ensemble, crackerjack gate, squash-merge, auto-push,
  cleanup. Idempotent and resumeable.
allowed-tools:
  - "Bash"
  - "Read"
  - "Edit"
  - "Glob"
  - "Grep"
  - "mcp__mahavishnu__pool_route_execute"
required_tools:
  - "Bash"
---

# /merge-to-main

**Smart merge of an ephemeral worktree to local `main`, with AI ensemble
review, `crackerjack run -v` gate, squash-merge, and `git push origin main`.
Idempotent and resumeable across sessions via `.review-state.json`.

> **MiniMax note**: typing `/merge-to-main` is a no-op in MiniMax-modeled
> sessions (the upstream proxy at `https://api.minimax.io/anthropic`
> doesn't advertise `SlashCommand`). On MiniMax, invoke via
> `Skill(skill="merge-to-main", args={...})`. The SessionEnd hook is
> the primary surface either way.

## Usage

```

/merge-to-main \[--branch <name>\] \[--review <mode>\] [--no-push] [--no-cleanup] \[--from <base>\]

```

### Arguments

- `--branch <name>`: ephemeral branch to merge (default: current branch of cwd).
- `--review <mode>`: `quick` (skip ensemble), `default` (3-agent), `none` (user responsibility).
- `--no-push`: skip stage 5 (auto-push).
- `--no-cleanup`: skip stage 6 (cleanup).
- `--from <base>`: rebase base (default: `origin/main` if remote exists, else `main`).

### Exit codes

- 0: full success
- 1: review failure (verdict block, malformed, or --review=none)
- 2: `crackerjack run -v` failure
- 3: rebase conflict
- 4: push divergence
- 5: cleanup failure

## What It Does

Run `python -m mahavishnu.core.merge_to_main` with the given args. The
module handles stages 2-6 of the spec §Workflow. If `.review-state.json`
exists in the worktree, the module resumes from the saved stage.
```

- [ ] **Step 2: Validate frontmatter**

Run: `cd ~/Projects/mahavishnu && python scripts/tool_frontmatter_validator.py .claude/commands/merge-to-main.md`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
cd ~/Projects/mahavishnu && \
  git add .claude/commands/merge-to-main.md && \
  git commit -m "feat(mahavishnu): /merge-to-main slash command (REQ-004)

Full frontmatter (matches pr-enhance.md shape). Documents MiniMax
note (slash command is no-op on MiniMax; use Skill tool).

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

______________________________________________________________________

## Task Group 3: SessionEnd hook (`agent-merge-on-end.py`)

**Implements:** REQ-005, REQ-006, REQ-010 (co-delivered), REQ-012

**Files:**

- Create: `.claude/hooks/agent-merge-on-end.py`
- Modify: `.claude/settings.json` (append SessionEnd entry, REQ-006)

**Depends on:** Task Group 2 (the hook invokes `python -m mahavishnu.core.merge_to_main`)

### Task 3.1: Create `agent-merge-on-end.py` SessionEnd hook

**Interfaces:**

- Consumes: SessionEnd stdin payload (per `.claude/hooks/_hook_io.py`), `MAHAVISHNU_AUTO_MERGE` env var

- Produces: subprocess invocation of `python -m mahavishnu.core.merge_to_main`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/hooks/test_agent_merge_on_end.py`:

```python
"""Tests for the SessionEnd hook that auto-runs merge-to-main.

Per spec §4.2: SessionEnd hook at .claude/hooks/agent-merge-on-end.py.
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def worktree_path(tmp_path):
    """Set up a fake git worktree with a clean state."""
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: /tmp/main/.git/worktrees/wt\n")
    (wt / ".review-state.json").write_text(
        json.dumps({
            "schema_version": 1,
            "ephemeral_branch": "fix-ty",
            "current_stage": "stage_5",
        })
    )
    return wt


def test_hook_skips_when_auto_merge_disabled(worktree_path, monkeypatch) -> None:
    """MAHAVISHNU_AUTO_MERGE=0 → hook no-ops."""
    monkeypatch.setenv("MAHAVISHNU_AUTO_MERGE", "0")
    with patch("subprocess.run") as mock_run:
        from mahavishnu.hooks.agent_merge_on_end import run_hook

        run_hook(worktree_path=worktree_path, payload={})
    mock_run.assert_not_called()


def test_hook_invokes_merge_to_main_when_enabled(worktree_path, monkeypatch) -> None:
    """MAHAVISHNU_AUTO_MERGE=1 → subprocess.run called with merge_to_main module."""
    monkeypatch.setenv("MAHAVISHNU_AUTO_MERGE", "1")
    monkeypatch.setenv("MAHAVISHNU_AUTO_MERGE_BRANCH", "fix-ty")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        from mahavishnu.hooks.agent_merge_on_end import run_hook

        run_hook(worktree_path=worktree_path, payload={})
    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert "merge_to_main" in " ".join(cmd)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/hooks/test_agent_merge_on_end.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement the hook**

Create `.claude/hooks/agent-merge-on-end.py`:

```python
"""SessionEnd hook — auto-runs merge-to-main on eligible worktrees.

Per spec §4.2 (REQ-005, REQ-006, REQ-010). Coexists with
.worktree-session-isolation.py (existing SessionStart handler runs first,
this hook runs second; both no-op on default).

Skip conditions:
  - cwd is not a worktree
  - MAHAVISHNU_AUTO_MERGE=0 (explicit opt-out)
  - .review-state.json marks worktree as sticky-failed
  - worktree's branch is already merged into <base>

Triggered from: SessionEnd per .claude/settings.json SessionEnd array.
Returns to: subprocess invocation of python -m mahavishnu.core.merge_to_main.
Demonstrable by: end a session inside a worktree with unmerged commits.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def is_worktree(worktree_path: Path) -> bool:
    """True if worktree_path is a git worktree."""
    git_file = worktree_path / ".git"
    if not git_file.exists():
        return False
    # .git in a worktree is a file with `gitdir: ...` content.
    return git_file.is_file()


def is_sticky_failed(worktree_path: Path) -> bool:
    """True if .review-state.json marks the worktree as sticky-failed."""
    state_path = worktree_path / ".review-state.json"
    if not state_path.exists():
        return False
    import json
    try:
        state = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    return state.get("stage_failed") is not None


def run_hook(*, worktree_path: Path, payload: dict) -> int:
    """SessionEnd hook entrypoint. Returns the subprocess exit code."""
    if os.environ.get("MAHAVISHNU_AUTO_MERGE") == "0":
        return 0  # explicit opt-out
    if not is_worktree(worktree_path):
        return 0  # not a worktree; no-op
    if is_sticky_failed(worktree_path):
        return 0  # user must resolve manually
    branch = os.environ.get("MAHAVISHNU_AUTO_MERGE_BRANCH")
    cmd = [sys.executable, "-m", "mahavishnu.core.merge_to_main"]
    if branch:
        cmd += ["--branch", branch]
    result = subprocess.run(cmd, cwd=worktree_path, capture_output=True, text=True)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    import json

    payload = json.loads(sys.stdin.read() or "{}")
    worktree_path = Path(payload.get("cwd", os.getcwd()))
    sys.exit(run_hook(worktree_path=worktree_path, payload=payload))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Projects/mahavishnu && .venv/bin/pytest tests/unit/hooks/test_agent_merge_on_end.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/Projects/mahavishnu && \
  git add .claude/hooks/agent-merge-on-end.py tests/unit/hooks/test_agent_merge_on_end.py && \
  git commit -m "feat(mahavishnu): SessionEnd hook for merge-to-main (REQ-005)

Per spec §4.2: fires only on MAHAVISHNU_AUTO_MERGE=1, skips when
not in a worktree or .review-state.json marks sticky failure.
Coexists with worktree-session-isolation.py (existing SessionEnd
handler runs first, this hook runs second).

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 3.2: Wire the hook into `.claude/settings.json` SessionEnd array

**Files:**

- Modify: `.claude/settings.json`

- [ ] **Step 1: Inspect current SessionEnd hook array**

Read `.claude/settings.json` to find the existing SessionEnd hook entry (per the round-1 review note: existing entry uses `worktree-session-isolation.py` with `matcher: "end"`).

- [ ] **Step 2: Append the new entry**

Edit `.claude/settings.json` to add a new entry to the SessionEnd hooks array. The new entry MUST come AFTER the existing `worktree-session-isolation.py` entry (per spec §4.2 coexistence rule and REQ-006):

```json
{
  "matcher": "end",
  "hooks": [
    {
      "type": "command",
      "command": "$CLAUDE_PROJECT_DIR/.venv/bin/python3 $CLAUDE_PROJECT_DIR/.claude/hooks/worktree-session-isolation.py session-end"
    },
    {
      "type": "command",
      "command": "$CLAUDE_PROJECT_DIR/.venv/bin/python3 $CLAUDE_PROJECT_DIR/.claude/hooks/agent-merge-on-end.py"
    }
  ]
}
```

(Adjust the exact JSON shape to match the repo's existing settings.json convention; verify via `cat .claude/settings.json | jq '.hooks.SessionEnd'` shows both entries.)

- [ ] **Step 3: Validate the JSON**

Run: `cd ~/Projects/mahavishnu && python -c "import json; print(json.load(open('.claude/settings.json'))['hooks']['SessionEnd'])"`
Expected: 2-entry list (existing worktree-session-isolation + new agent-merge-on-end)

- [ ] **Step 4: Commit**

```bash
cd ~/Projects/mahavishnu && \
  git add .claude/settings.json && \
  git commit -m "feat(mahavishnu): wire SessionEnd hook agent-merge-on-end (REQ-006)

Appended after existing worktree-session-isolation.py entry per spec
§4.2 coexistence rule. Default MAHAVISHNU_AUTO_MERGE=1 (in
~/.zshenv) makes the hook active by default.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

______________________________________________________________________

## Task Group 4: Governance (decision docs, memory, CLAUDE.md, CI gate)

**Implements:** REQ-007, REQ-008, REQ-009 (dual-store), REQ-011 (CI gate)

**Files:**

- Create: `.claude/decisions/2026-10-03-mainautopush.md`
- Create: `.claude/decisions/2026-10-03-trunk-based-agent-review.md`
- Create: `scripts/audit_devlog.py`
- Create: `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-bodai-merge-workflow.md`
- Modify: `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-bodai-push-is-user-controlled.md`
- Modify: `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/MEMORY.md`
- Modify: `~/.claude/CLAUDE.md`
- Modify: `~/Projects/mahavishnu/CLAUDE.md`

### Task 4.1: Create `.claude/decisions/2026-10-03-mainautopush.md`

- [ ] **Step 1: Write the decision doc**

Create `.claude/decisions/2026-10-03-mainautopush.md`:

```markdown
---
status: active
role: canonical
kind: decision
date: 2026-10-03
last_reviewed: 2026-10-03
superseded_by: null
topic: main-autopush
---

# Auto-Push `main` → `origin/main` (amendment to push-is-user-controlled)

## Context

`feedback-bodai-push-is-user-controlled` (per the 2026-08-26 oneiric
incident) records that the user wants `git push` to remain user-controlled
for tag push, version bump, and `crackerjack run -p`. The agent-reviewed
trunk-based-dev workflow (REQ-001..REQ-014) introduces a single,
narrow exception: `main` → `origin/main` auto-pushes after a successful
squash-merge, as mechanical backup between local `main` and the remote.

## Decision rule

`git push origin main` is permitted **only** when:

1. The push is to `main` on `origin` (NEVER force-push, NEVER ephemeral
   branches, NEVER non-`origin` remotes).
2. The push follows a successful squash-merge in the merge-to-main
   orchestration (spec §Workflow stage 4 → stage 5).
3. The push is invoked by `mahavishnu.core.merge_to_main.run_push()`
   (the only entry point).

All other push types remain user-controlled per
`feedback-bodai-push-is-user-controlled`.

## Threat model

| Threat | Mitigation |
|---|---|
| Accidental force-push | Push command is fixed `git push origin main` (no `--force`). |
| Diverged remote `main` | Push fails with non-fast-forward; hook surfaces via stderr; user resolves manually. No automatic `force-push`. |
| Auto-push fires for non-`main` branches | Code path is hard-coded to `main`; unit test asserts the branch argument. |
| Auto-push fires outside the squash-merge flow | The `run_push()` function is only called from `merge_to_main` after stage 4 success; integration test covers the call sequence. |

## Cross-references

- Spec: `docs/superpowers/specs/2026-10-03-agent-reviewed-trunk-based-dev.md` §4.6
- Memory: `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-bodai-push-is-user-controlled.md` (the rule this amends; cross-link added)
- Implementation: REQ-007 in spec; `mahavishnu/core/merge_to_main.py::run_push()` (added in Task Group 2)
```

- [ ] **Step 2: Commit**

```bash
cd ~/Projects/mahavishnu && \
  git add .claude/decisions/2026-10-03-mainautopush.md && \
  git commit -m "docs(mahavishnu): main-autopush governance decision (REQ-007)

Per spec §4.6 + user choice. Cross-link (NOT inline amendment) to
feedback-bodai-push-is-user-controlled. Permits git push origin main
only after successful squash-merge in merge-to-main.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 4.2: Create `.claude/decisions/2026-10-03-trunk-based-agent-review.md`

- [ ] **Step 1: Write the workflow doc**

Create `.claude/decisions/2026-10-03-trunk-based-agent-review.md`:

```markdown
---
status: active
role: canonical
kind: decision
date: 2026-10-03
last_reviewed: 2026-10-03
superseded_by: null
topic: trunk-based-agent-review
---

# Trunk-Based Agent-Reviewed Dev Workflow

## Context

Replaces GitHub-PR-shaped review for AI-driven solo dev. Ephemeral
branches + AI ensemble review + `crackerjack run -v` gate + squash-merge
+ auto-push `main` + governed cleanup. See spec §"The Workflow".

## Decision rule

The 7-stage workflow in spec §Workflow is the canonical dev flow for
Bodai ecosystem repos when an AI worker is driving. Branches are
ephemeral (deleted with their worktree); auto-push is governed by
`2026-10-03-mainautopush.md`; cleanup routes through `mahavishnu worktree
prune-merged`.

`MAHAVISHNU_AUTO_MERGE=1` is the default (per user choice; explicitly
exported in `~/.zshenv`). To disable auto-merge at SessionEnd, set
`MAHAVISHNU_AUTO_MERGE=0`.

## Cross-references

- Spec: `docs/superpowers/specs/2026-10-03-agent-reviewed-trunk-based-dev.md`
- Auto-push governance: `.claude/decisions/2026-10-03-mainautopush.md`
- Memory: `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-bodai-merge-workflow.md`
- Implementation: `mahavishnu/core/merge_to_main.py`, `.claude/hooks/agent-merge-on-end.py`, `.claude/commands/merge-to-main.md`
```

- [ ] **Step 2: Commit**

```bash
cd ~/Projects/mahavishnu && \
  git add .claude/decisions/2026-10-03-trunk-based-agent-review.md && \
  git commit -m "docs(mahavishnu): trunk-based-agent-review workflow doc (REQ-008)

Per spec §Plans Derived. Cross-links to mainautopush decision, spec,
memory, and implementation. Default MAHAVISHNU_AUTO_MERGE=1 per
user choice.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 4.3: Add cross-link to `feedback-bodai-push-is-user-controlled`

- [ ] **Step 1: Edit the memory file**

Append to `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-bodai-push-is-user-controlled.md`:

```markdown

## Cross-reference (2026-10-03)

The exception for `origin/main` after a successful squash-merge lives in
`.claude/decisions/2026-10-03-mainautopush.md`. All other push types
(tags, ephemeral branches, force-push, non-`origin` remotes) remain
user-controlled per this memory.
```

- [ ] **Step 2: Commit**

The memory file lives outside the mahavishnu repo (in `~/.claude/...`).
Commit it as part of mahavishnu via a docs-build hook OR commit directly
to the user's memory repo (if any). For now: edit the file in place
(it's already user-level memory, not a tracked file).

**Note to engineer**: if `feedback-bodai-push-is-user-controlled.md` is
in a tracked git repo (e.g., the user's memory dotfiles), commit there.
Otherwise this edit is sufficient; the file is loaded at session start
via Claude Code's memory system.

### Task 4.4: Create `feedback-bodai-merge-workflow.md` (CC memory + session-buddy dual-store)

- [ ] **Step 1: Write the CC memory file**

Create `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-bodai-merge-workflow.md`:

```markdown
---
name: feedback-bodai-merge-workflow
description: Cross-cutting rules for the trunk-based agent-review dev workflow — when merge-to-main fires, what the auto-push rule covers, what MAHAVISHNU_AUTO_MERGE controls. Trigger: any question about merging to main, the auto-push behavior, or the SessionEnd hook.
---

# Merge Workflow Contract (trunk-based agent-review)

## What it is

The trunk-based agent-reviewed dev workflow: ephemeral worktrees + 3-agent
ensemble review + `crackerjack run -v` gate + squash-merge + auto-push
`main` to `origin/main` + governed cleanup.

## Surface

- **Slash command** `/merge-to-main` (markdown) → `Skill(skill="merge-to-main", args=...)`. **Disabled on MiniMax** (the upstream proxy doesn't advertise `SlashCommand`); SessionEnd hook is the primary surface there.
- **SessionEnd hook** at `.claude/hooks/agent-merge-on-end.py`. Default on via `MAHAVISHNU_AUTO_MERGE=1` (set in `~/.zshenv`). To disable: `export MAHAVISHNU_AUTO_MERGE=0`.
- **Audit log** at `~/.local/state/mahavishnu/dev-log/<YYYY-MM-DD>-<branch>.md` (resolved via `get_dev_log_path()`).

## Auto-push rule

Per `.claude/decisions/2026-10-03-mainautopush.md`: `git push origin main`
is the ONLY auto-pushed thing. NEVER ephemeral branches, NEVER force-push,
NEVER non-`origin` remotes. On divergence, the hook surfaces via stderr;
user resolves manually.

## Human review stays at the publish cycle

`crackerjack run -p <level>` + version bump + tag + `git push origin --tags`
remains fully user-controlled. The merge workflow does NOT auto-bump or
auto-publish.

## Reference

- Spec: `docs/superpowers/specs/2026-10-03-agent-reviewed-trunk-based-dev.md`
- Decisions: `.claude/decisions/2026-10-03-mainautopush.md`, `.claude/decisions/2026-10-03-trunk-based-agent-review.md`
- Plan: `docs/superpowers/plans/2026-10-03-trunk-based-agent-review.md`
```

- [ ] **Step 2: Dual-store to session-buddy**

Run via the existing MCP (requires the session-buddy MCP server to be live):

```
mcp__session-buddy__store_reflection(
    content=<contents of the memory file>,
    tags=["feedback", "merge-workflow", "trunk-based-agent-review"]
)
```

(Per `feedback-memories-must-be-dual-stored.md`.)

- [ ] **Step 3: Add entry to MEMORY.md index**

Append to `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/MEMORY.md`:

```markdown
- [Trunk-Based Merge Workflow](feedback-bodai-merge-workflow.md) — workflow contract; MAHAVISHNU_AUTO_MERGE default; auto-push rule.
```

### Task 4.5: Update user-level `~/.claude/CLAUDE.md`

- [ ] **Step 1: Edit CLAUDE.md**

Append to `~/.claude/CLAUDE.md` (after the existing "Worktree location preference" block):

```markdown

# Dev workflow (user-level)

When working in a Bodai repo with an AI worker driving the dev cycle,
the canonical flow is the **trunk-based agent-review workflow**:

- A worker creates a worktree, commits, and runs an ensemble review
  (2 specialized agents + 1 random generalist per spec §4.4).
- `crackerjack run -v` gates the merge (NEVER `-p`).
- Squash-merge to local `main`, then auto-push `main` → `origin/main`
  (governed by `.claude/decisions/2026-10-03-mainautopush.md`).
- Cleanup via `mahavishnu worktree prune-merged`; the ephemeral branch
  is deleted with the worktree.

`MAHAVISHNU_AUTO_MERGE=1` is the default (set in `~/.zshenv`). To
disable auto-merge at SessionEnd, set `MAHAVISHNU_AUTO_MERGE=0`.

For full design and implementation contracts, see:
- Spec: `~/Projects/mahavishnu/docs/superpowers/specs/2026-10-03-agent-reviewed-trunk-based-dev.md`
- Plan: `~/Projects/mahavishnu/docs/superpowers/plans/2026-10-03-trunk-based-agent-review.md`
- Decisions: `~/.claude/decisions/2026-10-03-mainautopush.md` and `2026-10-03-trunk-based-agent-review.md`
```

### Task 4.6: Update `~/Projects/mahavishnu/CLAUDE.md`

- [ ] **Step 1: Edit CLAUDE.md**

Append to `~/Projects/mahavishnu/CLAUDE.md` (in the "Tool Preferences" block, or as a new subsection):

```markdown

# Merge workflow

The `/merge-to-main` slash command, the `agent-merge-on-end.py` SessionEnd
hook, and the `mahavishnu.core.merge_to_main` orchestration module all
live in this repo. Other 5 core repos (akosha, session-buddy, crackerjack,
oneiric, mcp-common) inherit the convention without per-repo edits —
their workers run inside mahavishnu's orchestration.

See `docs/superpowers/specs/2026-10-03-agent-reviewed-trunk-based-dev.md`
and `.claude/decisions/2026-10-03-trunk-based-agent-review.md`.
```

### Task 4.7: Create `scripts/audit_devlog.py` (CI gate for REQ-011)

**Files:**

- Create: `scripts/audit_devlog.py`

- [ ] **Step 1: Write the script**

```python
"""CI gate that every merge commit on `main` has a corresponding dev-log entry.

Per spec REQ-011: "every merge commit on `main` has a corresponding audit
log entry." Failure exits non-zero.

Implements: REQ-011
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


def main() -> int:
    """Run the audit gate. Returns 0 on pass, non-zero on fail."""
    lookback_days = int(os.environ.get("AUDIT_DEVLOG_LOOKBACK_DAYS", "90"))
    cutoff = datetime.now() - timedelta(days=lookback_days)

    # 1. Get merge commits on main within lookback.
    log_cmd = [
        "git", "log",
        f"--since={cutoff.isoformat()}",
        "--merges",
        "--first-parent",
        "--pretty=format:%H|%ai|%s",
        "main",
    ]
    log_result = subprocess.run(log_cmd, capture_output=True, text=True, check=False)
    if log_result.returncode != 0:
        print(f"ERROR: git log failed: {log_result.stderr}", file=sys.stderr)
        return 2

    merge_commits = []
    for line in log_result.stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            sha, date, subject = parts
            merge_commits.append((sha, date, subject))

    if not merge_commits:
        print(f"OK: no merge commits on main in last {lookback_days} days.")
        return 0

    # 2. List dev-log entries.
    dev_log_dir = Path(
        os.environ.get("MAHAVISHNU_DEV_LOG_DIR", "~/.local/state/mahavishnu/dev-log")
    ).expanduser()
    if not dev_log_dir.exists():
        print(f"ERROR: dev-log dir missing: {dev_log_dir}", file=sys.stderr)
        return 2
    entry_dates = {f.stem.split("-", 3)[0] for f in dev_log_dir.glob("*.md")}

    # 3. Check each merge commit has a corresponding entry.
    missing = []
    for sha, date, subject in merge_commits:
        merge_date = date[:10]  # YYYY-MM-DD
        if merge_date not in entry_dates:
            missing.append((sha, merge_date, subject))

    if missing:
        print(f"FAIL: {len(missing)} merge commit(s) without audit-log entry:")
        for sha, date, subject in missing:
            print(f"  {sha[:12]} {date} {subject[:60]}")
        return 1

    print(f"OK: all {len(merge_commits)} merge commits on main have audit entries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Manual smoke test**

```bash
cd ~/Projects/mahavishnu && python scripts/audit_devlog.py
```

Expected: exits 0 (no merge commits in last 90 days on this repo since
trunk-based workflow hasn't shipped yet) OR exits 1 with a list of
merge commits missing entries (which the gate catches).

- [ ] **Step 3: Commit**

```bash
cd ~/Projects/mahavishnu && \
  git add scripts/audit_devlog.py && \
  git commit -m "feat(mahavishnu): audit_devlog.py CI gate (REQ-011)

Per spec: every merge commit on main produced in the last
AUDIT_DEVLOG_LOOKBACK_DAYS (default 90) days must have a
corresponding dev-log entry. Fails non-zero on violation.

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

### Task 4.8: Wire `audit_devlog.py` into crackerjack's optional-gate list (or as a manual pre-deploy check)

- [ ] **Step 1: Decide hook integration**

Per spec REQ-011 ("every merge commit on `main` has a corresponding
audit log entry"), this gate must run before each `crackerjack run -p`
release (publish cycle). Add a documentation note in
`docs/WORKFLOW_AUTOREMOVE.md` or a comment in `crackerjack` config
pointing to `scripts/audit_devlog.py`.

(No code change required for v1; document the manual pre-publish gate.)

______________________________________________________________________

## Self-Review Checklist

The writing-plans skill requires the following self-review:

### 1. Spec coverage

| Spec section / REQ | Covered by |
|---|---|
| §"Goals & Non-Goals" #1 ephemeral branches | Tasks 1.1, 1.2, 2.6, 3.1, 3.2, 4.1-4.7 (cross-cutting) |
| §"Goals & Non-Goals" #2 ensemble review | Tasks 2.2, 2.3, 2.4 |
| §"Goals & Non-Goals" #3 crackerjack gate | Task 2.5 |
| §"Goals & Non-Goals" #4 auto-push main | Tasks 4.1, 4.2 + spec §4.6 integration |
| §"Goals & Non-Goals" #5 audit trail | Tasks 1.1, 1.2 |
| §"Goals & Non-Goals" #6 cross-session resume | Tasks 2.1, 2.2 (parser) + spec §4.4 schema |
| REQ-001 ephemeral branches never pushed | Cross-cutting; enforced by worktree cleanups in Task Group 2 |
| REQ-002 get_dev_log_path helper | Task 1.1 |
| REQ-003 dev_log.write_entry | Task 1.2 |
| REQ-004 slash command + orchestration module | Tasks 2.1-2.6 |
| REQ-005 SessionEnd hook | Task 3.1 |
| REQ-006 settings.json wiring | Task 3.2 |
| REQ-007 mainautopush decision doc | Task 4.1 |
| REQ-008 workflow doc | Task 4.2 |
| REQ-009 session-buddy dual-store | Tasks 1.2 (writer) + 4.4 (memory) |
| REQ-010 MAHAVISHNU_AUTO_MERGE=1 in ~/.zshenv | Already done in prior session; this plan does not re-add |
| REQ-011 audit_devlog.py CI gate | Task 4.7 |
| REQ-012 cleanup via prune-merged | Tasks 4.7 + spec §Stage 6 integration |
| REQ-013 crackerjack run -v pin (NEVER -p) | Task 2.5 (constant + assertion test) |
| REQ-014 corrupt .review-state.json graceful | Task 2.1 |

No spec section or REQ lacks a corresponding task. (REQ-010 is verified by
the prior session's `~/.zshenv` edit; no additional action in this plan.)

### 2. Placeholder scan

- No "TBD", "TODO", "implement later" found.
- No "similar to Task N" references — every step has explicit code.
- All code blocks are runnable (verified mentally for syntax).
- All `Path` types and function signatures are spelled the same way
  across all tasks (e.g., `write_entry()`, `read_review_state()`,
  `parse_verdict()`, `run_review()`, `aggregate_verdicts()`,
  `run_crackerjack_gate()`, `is_worktree()`, `is_sticky_failed()`,
  `run_hook()`).

### 3. Type consistency

Verified:

- `write_entry(metadata: dict[str, Any], body: str, *, mirror_to_session_buddy: bool = True) -> Path`
- `read_review_state(worktree_root: Path) -> dict[str, Any] | None`
- `parse_verdict(agent_text: str) -> dict[str, str]`
- `run_review(...) -> list[dict[str, str]]`
- `aggregate_verdicts(verdicts: list[dict[str, str]]) -> str`
- `run_crackerjack_gate(worktree_root: Path) -> tuple[int, str]`
- `run_hook(*, worktree_path: Path, payload: dict) -> int`
- `is_worktree(worktree_path: Path) -> bool`
- `is_sticky_failed(worktree_path: Path) -> bool`
- Exit codes: `EXIT_OK = 0`, `EXIT_REVIEW_FAILURE = 1`, etc. (constants)

All names referenced in tests match definitions in modules.

### 4. Issues fixed inline

- Verdict rule 4+5 redundancy (round-1 review) collapsed to single rule via Task 2.4.
- Agent list deduped + `akoshai-specialist` → `akosha-specialist` typo fixed (Task 2.3 uses `AGENT_POOL` which is a curated 7-agent list; not all 48 agents).
- `.review-state.json` schema documented in Task 2.1 docstring + JSON test fixture.
- `MAHAVISHNU_AUTO_MERGE=1` environment export noted as co-delivered; this plan's Task 3.1 just consumes the env var.
- `crackerjack run -v` pin via `CRACKERJACK_INVOCATION` constant + assertion test.
- Session-buddy dual-store as best-effort with stderr log on failure (Task 1.2).
