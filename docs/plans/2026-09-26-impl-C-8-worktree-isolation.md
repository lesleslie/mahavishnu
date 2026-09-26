# C-8: `pool_route_execute(worktree=WorktreeOptions(...))` (WP-1 — worktree isolation)

**REQ-NNN:** REQ-010, REQ-011
- REQ-010: `pool_route_execute(worktree=WorktreeOptions(...))` with REPLACED `WorktreeInfo` (diff/merge/files_touched + `complete_worktree()` returns them)
- REQ-011: `WorktreeLockedError` exception reused (no competing subclass)
**Risk:** High (replaces `WorktreeInfo` class shape; touches the dispatch path that C-6 just extended; affects git subprocess calls)
**Blocks:** C-13 (crackerjack review-pr workflow runs worktree-isolated LLM dispatches)
**Direct-to-main commit:** Yes (per `feedback-no-backwards-compat-pre-1.0` + `bodai-pre-1.0-merge-policy`).
**Status:** Draft — round-4 corrections baked in (`WorktreeInfo` REPLACED, `GitRunner` dropped, max-args guard preserved).

## Goal

Add the `worktree` Pydantic input model to `pool_route_execute` so dispatching a task against a repo creates an isolated `git worktree`, runs the work in it, and returns the diff/merge/files-touched summary. **Per no-backcompat, REPLACE `WorktreeInfo` outright** — don't extend the existing class with `diff()`, `merge()`, `files_touched()` methods. Compute those fields in `complete_worktree()` and attach to a fresh `WorktreeInfo` shape. **Also: drop the invented `GitRunner`** — use `asyncio.to_thread(subprocess.run)` directly in `complete_worktree`.

The arg-count concern from round-4: `pool_route_execute` now has 9 positional args after C-8 (existing 7 + C-6's `idempotency` + C-8's `worktree`). `WorktreeOptions` groups 4 fields into one Pydantic input model, keeping the total under `max-args=10`.

## Pre-flight checks

1. **C-1, C-5, C-6 have landed.**
   - C-1: `worktree_storage:` settings section exists; `default_isolation`, `base_branch`, `ttl_seconds`, `max_concurrent` keys.
   - C-5: `safe_publish()` available for Akosha event emission.
   - C-6: `IdempotencyOptions` accepted by `pool_route_execute`; `idempotency` kwarg works.
2. **`mahavishnu/core/worktree_manager.py` exists at line 228+.** Read the existing `create_worktree()` and `complete_worktree()` signatures and the existing `WorktreeInfo` dataclass shape. The plan REPLACES `WorktreeInfo` — preserve any callers that read existing fields by updating them in the same commit.
3. **`WorktreeLockedError` exists at `mahavishnu/core/errors.py:1792`** (per spec). Verify; do NOT create a competing subclass.
4. **`WorktreeError` exists at `mahavishnu/core/errors.py:1769`** (per spec). Verify.
5. **No `GitRunner` class exists** (`grep -r "class GitRunner" mahavishnu/` returns nothing). If found, this is a stale reference — the plan REPLACES the fictional symbol with direct `asyncio.to_thread(subprocess.run)` calls.
6. **`worktree_manage` MCP tool exists** at `mahavishnu/mcp/tools/worktree_tools.py`. The new `WorktreeInfo` shape must remain backward-compatible with this tool's output (it reads via `WorktreeInfo.to_dict()`).

## File-by-file changes

### 1. `mahavishnu/core/worktree_manager.py` — REPLACE `WorktreeInfo` class shape

Locate the existing `WorktreeInfo` `@dataclass`. Replace it with the new shape that includes `diff`, `merge`, `files_touched`:

```python
@dataclass
class WorktreeInfo:
    """Result of a worktree creation or completion.

    REPLACED per C-8 — no longer has methods like .diff(). The diff/merge/files_touched
    fields are populated by complete_worktree() and read by pool_route_execute().
    to_dict() preserved for backward compatibility with worktree_manage MCP tool.
    """
    worktree_id: str
    repo_path: Path
    branch_name: str
    base_branch: str
    created_at: datetime
    ttl_seconds: int

    # Populated by complete_worktree(). Empty before completion.
    diff: str = ""
    merge: bool = False
    files_touched: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Backward-compatible serialization for worktree_manage MCP tool."""
        return {
            "worktree_id": self.worktree_id,
            "repo_path": str(self.repo_path),
            "branch_name": self.branch_name,
            "base_branch": self.base_branch,
            "created_at": self.created_at.isoformat(),
            "ttl_seconds": self.ttl_seconds,
            "diff": self.diff,
            "merge": self.merge,
            "files_touched": self.files_touched,
        }
```

### 2. `mahavishnu/core/worktree_manager.py` — extend `complete_worktree` to populate diff/merge/files_touched

Read the existing `complete_worktree()` signature (line 324 per spec). Extend it to:

1. Compute `diff` via `git diff <base_branch>..HEAD` (run in `asyncio.to_thread`).
2. Compute `files_touched` via `git diff --name-only <base_branch>..HEAD`.
3. Optionally `git merge --no-ff` if `merge=True`.
4. Return a `WorktreeInfo` (the same one passed in) with the three new fields populated.

```python
async def complete_worktree(
    self,
    worktree_id: str,
    merge: bool,
    repo_path: Path,
) -> WorktreeCompletion:
    """Finalize a worktree. Returns the populated WorktreeInfo + merge outcome."""
    info = self._registry.get(worktree_id)
    if info is None:
        raise WorktreeError(f"worktree {worktree_id} not found in registry")

    wt_path = repo_path / ".worktrees" / info.worktree_id

    def _git_diff() -> tuple[str, list[str]]:
        diff_proc = subprocess.run(
            ["git", "diff", info.base_branch, "HEAD"],
            cwd=wt_path, capture_output=True, text=True, check=True,
        )
        names_proc = subprocess.run(
            ["git", "diff", "--name-only", info.base_branch, "HEAD"],
            cwd=wt_path, capture_output=True, text=True, check=True,
        )
        return diff_proc.stdout, [n for n in names_proc.stdout.splitlines() if n]

    diff_text, files = await asyncio.to_thread(_git_diff)

    merge_outcome = False
    if merge:
        def _git_merge() -> None:
            subprocess.run(
                ["git", "merge", "--no-ff", info.branch_name, "-m",
                 f"Auto-merge worktree {worktree_id}"],
                cwd=repo_path, capture_output=True, text=True, check=True,
            )
        await asyncio.to_thread(_git_merge)
        merge_outcome = True

    info.diff = diff_text
    info.merge = merge_outcome
    info.files_touched = files
    return WorktreeCompletion(info=info)
```

Add the return wrapper:

```python
@dataclass
class WorktreeCompletion:
    info: WorktreeInfo
```

This wrapper lets future C-revisions add fields (e.g., `merge_conflict: bool`) without breaking the signature.

### 3. `mahavishnu/mcp/tools/pool_tools.py` — extend `pool_route_execute` with `worktree` kwarg

Add the `WorktreeOptions` Pydantic input model and the new kwarg. Insert into the C-6-extended signature from line 482:

```python
from mahavishnu.core.worktree_manager import WorktreeLockedError, WorktreeError
from mahavishnu.core.worktree_options import WorktreeOptions  # new module


async def pool_route_execute(
    prompt: str,
    pool_selector: str = "least_loaded",
    # ... 5 more positional args preserved unchanged ...
    idempotency: "IdempotencyOptions | None" = None,
    worktree: WorktreeOptions | None = None,
) -> dict[str, Any]:
    # ... existing idempotency lookup (C-6) preserved ...

    worktree_info: WorktreeInfo | None = None
    settings = get_settings()
    effective_isolation = (
        worktree.isolation
        if worktree
        else settings.worktree_storage.default_isolation
    )
    repo_nickname = _resolve_repo_nickname(prompt)  # impl detail

    if effective_isolation == "worktree" and await _repo_has_git(repo_nickname):
        try:
            worktree_info = await worktree_manager.create_worktree(
                task_id=execution_id,
                repo_path=_resolve_repo_path(repo_nickname),
                branch_name=f"feature/{execution_id}-{uuid4().hex[:8]}",
                base_branch=(
                    worktree.base_branch
                    if worktree
                    else settings.worktree_storage.base_branch
                ),
                ttl_seconds=(
                    worktree.ttl_seconds
                    if worktree
                    else settings.worktree_storage.ttl_seconds
                ),
            )
            await safe_publish(create_event_envelope(
                event_type="insight.generated",
                payload={"insight_type": "worktree_created",
                         "worktree_id": worktree_info.worktree_id,
                         "repo_nickname": repo_nickname},
                source="mahavishnu.pool_route_execute",
                correlation_id=execution_id,
            ))
        except WorktreeLockedError as exc:
            logger.exception("worktree lock conflict",
                              extra={"error_id": "WORKTREE_LOCK_CONFLICT"})
            metrics.worktree_creation_total.labels(result="lock_conflict").inc()
            await safe_publish(create_event_envelope(
                event_type="anomaly.detected",
                payload={"anomaly_type": "worktree_lock_conflict",
                         "execution_id": execution_id},
                source="mahavishnu.pool_route_execute",
                metadata={"severity": "medium"},
            ))
            return {"status": "worktree_conflict", "error": str(exc)}
        except WorktreeError:
            logger.exception("worktree creation failed",
                              extra={"error_id": "WORKTREE_CREATION_FAILED"})
            metrics.worktree_creation_total.labels(result="error").inc()
            raise

    try:
        result = await _dispatch_internal(prompt, pool_selector, execution_id)
        if worktree_info and effective_isolation == "worktree":
            on_completion = (
                worktree.on_completion
                if worktree
                else "return_diff"
            )
            completion = await worktree_manager.complete_worktree(
                worktree_id=worktree_info.worktree_id,
                merge=(on_completion == "auto_merge"),
                repo_path=_resolve_repo_path(repo_nickname),
            )
            worktree_info = completion.info  # REPLACES WorktreeInfo with full shape
            result["worktree"] = {
                "diff": worktree_info.diff,
                "merge": worktree_info.merge,
                "files_touched": worktree_info.files_touched,
            }
            await safe_publish(create_event_envelope(
                event_type="insight.generated",
                payload={"insight_type": "worktree_completed",
                         "worktree_id": worktree_info.worktree_id,
                         "files_touched": worktree_info.files_touched},
                source="mahavishnu.pool_route_execute",
                correlation_id=execution_id,
            ))
        return result
    finally:
        if worktree_info and effective_isolation == "worktree":
            await worktree_manager.cleanup_worktree(
                worktree_id=worktree_info.worktree_id,
                repo_path=_resolve_repo_path(repo_nickname),
            )
```

### 4. `mahavishnu/core/worktree_options.py` — new file (~30 LoC)

Pydantic input model:

```python
"""WorktreeOptions input model for pool_route_execute(worktree=...)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorktreeOptions(BaseModel):
    """Pydantic input model for pool_route_execute(worktree=...).

    Grouping 4 fields into one Pydantic model keeps pool_route_execute's arg count
    under max-args=10 (currently 9 with idempotency + worktree kwargs).
    """
    model_config = ConfigDict(extra="forbid")

    isolation: Literal["host", "worktree"] = "host"
    base_branch: str = Field(default="main", min_length=1, max_length=255)
    ttl_seconds: int = Field(default=86_400, ge=60, le=604_800)
    on_completion: Literal["auto_merge", "discard", "return_diff"] = "return_diff"
```

### 5. `mahavishnu/core/metrics.py` — add 3 metrics

```python
WORKTREE_CREATION_TOTAL = Counter(
    "worktree_creation_total",
    "Total worktree creation attempts, labeled by result.",
    labelnames=["result"],  # success | lock_conflict | error
)

WORKTREE_ACTIVE_COUNT = Gauge(
    "worktree_active_count",
    "Currently active worktrees.",
)

WORKTREE_DISK_BYTES = Gauge(
    "worktree_disk_bytes",
    "Total disk bytes consumed by active worktrees.",
)
```

Increment `WORKTREE_CREATION_TOTAL.labels(result="success")` on successful `create_worktree`; `result="lock_conflict"` on `WorktreeLockedError`; `result="error"` on `WorktreeError`. Update the gauges on create/cleanup.

## Tests

### 6. `tests/integration/test_pool_worktree_isolation.py` — new file (~280 LoC)

```python
"""Tests for pool_route_execute(worktree=WorktreeOptions(...)) + WorktreeInfo shape."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mahavishnu.core.worktree_manager import (
    WorktreeError,
    WorktreeInfo,
    WorktreeLockedError,
    WorktreeManager,
)
from mahavishnu.core.worktree_options import WorktreeOptions


@pytest.mark.req(["REQ-010"])
class TestWorktreeOptions:
    def test_defaults(self) -> None:
        opts = WorktreeOptions()
        assert opts.isolation == "host"
        assert opts.base_branch == "main"
        assert opts.ttl_seconds == 86_400
        assert opts.on_completion == "return_diff"

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValueError, match="extra"):
            WorktreeOptions(isolation="bogus")

    def test_ttl_bounds(self) -> None:
        with pytest.raises(ValueError):
            WorktreeOptions(ttl_seconds=30)
        with pytest.raises(ValueError):
            WorktreeOptions(ttl_seconds=2_000_000)


@pytest.mark.req(["REQ-010"])
class TestWorktreeInfoReplaced:
    def test_worktree_info_has_new_fields(self) -> None:
        from datetime import UTC, datetime
        info = WorktreeInfo(
            worktree_id="wt-001",
            repo_path=Path("/tmp/repo"),
            branch_name="feature/wt-001",
            base_branch="main",
            created_at=datetime.now(UTC),
            ttl_seconds=3600,
        )
        # New fields exist
        assert info.diff == ""
        assert info.merge is False
        assert info.files_touched == []
        # to_dict() includes them
        d = info.to_dict()
        assert "diff" in d
        assert "merge" in d
        assert "files_touched" in d


@pytest.mark.req(["REQ-011"])
class TestWorktreeLockedErrorReused:
    def test_no_competing_subclass(self) -> None:
        """Per REQ-011: WorktreeLockedError is the only lock exception."""
        # If a competing subclass exists, this test catches it
        import inspect
        from mahavishnu.core import worktree_manager

        for name, obj in inspect.getmembers(worktree_manager):
            if inspect.isclass(obj) and "Lock" in name and "Worktree" in name:
                assert obj is WorktreeLockedError, (
                    f"competing WorktreeLock* subclass: {name}"
                )


@pytest.mark.req(["REQ-010"])
class TestCompleteWorktreePopulates:
    async def test_complete_worktree_returns_diff(
        self, worktree_manager_factory, tmp_git_repo
    ) -> None:
        """complete_worktree() populates diff/merge/files_touched via git subprocess."""
        wt_mgr = worktree_manager_factory
        info = await wt_mgr.create_worktree(
            task_id="exec-001",
            repo_path=tmp_git_repo,
            branch_name="feature/exec-001",
            base_branch="main",
            ttl_seconds=3600,
        )
        # Make a change in the worktree
        wt_path = tmp_git_repo / ".worktrees" / info.worktree_id
        (wt_path / "new_file.txt").write_text("hello\n")
        subprocess.run(["git", "add", "new_file.txt"], cwd=wt_path, check=True)
        subprocess.run(["git", "commit", "-m", "add file"], cwd=wt_path, check=True)

        completion = await wt_mgr.complete_worktree(
            worktree_id=info.worktree_id,
            merge=False,
            repo_path=tmp_git_repo,
        )
        assert "new_file.txt" in completion.info.files_touched
        assert "new_file.txt" in completion.info.diff
        assert completion.info.merge is False


@pytest.mark.req(["REQ-010"])
class TestPoolRouteExecuteWorktree:
    async def test_worktree_creation_emits_event(
        self, isolated_database, tmp_git_repo, safe_publisher_monkeypatch
    ) -> None:
        from mahavishnu.mcp.tools.pool_tools import pool_route_execute
        from mahavishnu.core.worktree_options import WorktreeOptions

        opts = WorktreeOptions(isolation="worktree", base_branch="main")
        result = await pool_route_execute(
            prompt=f"edit {tmp_git_repo}",
            pool_selector="least_loaded",
            worktree=opts,
        )
        assert "worktree" in result
        assert "files_touched" in result["worktree"]

    async def test_worktree_lock_conflict_returns_error(self) -> None:
        """If two concurrent calls request the same worktree, one must
        observe WorktreeLockedError and return 'worktree_conflict'."""
        from mahavishnu.mcp.tools.pool_tools import pool_route_execute
        from mahavishnu.core.worktree_options import WorktreeOptions

        opts = WorktreeOptions(isolation="worktree")
        # First call succeeds; second call (simulated) sees lock conflict
        with patch(
            "mahavishnu.core.worktree_manager.WorktreeManager.create_worktree",
            side_effect=WorktreeLockedError("test"),
        ):
            result = await pool_route_execute(
                prompt="edit repo",
                pool_selector="least_loaded",
                worktree=opts,
            )
            assert result["status"] == "worktree_conflict"

    async def test_finally_block_cleans_up_worktree_on_dispatch_failure(self) -> None:
        """FIX (round-5): the `finally` block in pool_route_execute must
        run `git worktree remove --force` even when the dispatch raises.

        FIX (round-6): the test must also patch `_repo_has_git` (added by C-8
        to gate the worktree path) to return True; otherwise an unregistered
        repo_nickname causes the worktree block to short-circuit, worktree_info
        stays None, and cleanup never runs.

        Without this test, a future refactor that accidentally moves
        `cleanup_worktree` outside the `finally` block would silently leak
        worktrees on every dispatch failure.
        """
        from unittest.mock import AsyncMock, patch
        from mahavishnu.core.worktree_manager import WorktreeInfo, WorktreeManager
        from mahavishnu.core.worktree_options import WorktreeOptions
        from mahavishnu.mcp.tools.pool_tools import pool_route_execute
        from datetime import UTC, datetime

        mock_worktree_info = WorktreeInfo(
            worktree_id="wt-leak-test",
            repo_path=Path("/tmp/test-repo"),
            branch_name="feature/wt-leak-test",
            base_branch="main",
            created_at=datetime.now(UTC),
            ttl_seconds=3600,
        )
        # Patch create_worktree to return success; patch _dispatch_internal
        # to raise; patch cleanup_worktree to track calls. FIX round-6: also
        # patch _repo_has_git so the worktree path activates.
        with patch.object(
            WorktreeManager, "create_worktree",
            new=AsyncMock(return_value=mock_worktree_info),
        ), patch.object(
            WorktreeManager, "cleanup_worktree",
            new=AsyncMock(),
        ) as mock_cleanup, patch(
            "mahavishnu.mcp.tools.pool_tools._dispatch_internal",
            new=AsyncMock(side_effect=RuntimeError("dispatch failed")),
        ), patch(
            "mahavishnu.mcp.tools.pool_tools._repo_has_git",
            new=AsyncMock(return_value=True),  # FIX round-6: activate worktree path
        ):
            with pytest.raises(RuntimeError, match="dispatch failed"):
                await pool_route_execute(
                    prompt="edit test",
                    pool_selector="least_loaded",
                    worktree=WorktreeOptions(isolation="worktree"),
                )
            # Cleanup MUST have run even though dispatch raised
            mock_cleanup.assert_awaited_once()
```

### 7. `tests/property/test_worktree_path_uniqueness_property.py` — new file (~80 LoC)

```python
"""Property test: distinct task_ids always produce distinct worktree paths."""
from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st


@pytest.mark.req(["REQ-010"])
@given(task_ids=st.lists(st.uuids(), min_size=2, max_size=10))
@settings(max_examples=50, deadline=30_000)
async def test_for_distinct_task_ids_paths_are_distinct(
    task_ids: list, worktree_manager_factory
) -> None:
    wt_mgr = worktree_manager_factory
    paths: set[Path] = set()
    for task_id in task_ids:
        info = await wt_mgr.create_worktree(
            task_id=str(task_id),
            repo_path=Path("/tmp/test-repo"),
            branch_name=f"feature/{task_id}",
            base_branch="main",
            ttl_seconds=3600,
        )
        wt_path = Path("/tmp/test-repo") / ".worktrees" / info.worktree_id
        assert wt_path not in paths, f"duplicate worktree path: {wt_path}"
        paths.add(wt_path)
```

## Crackerjack verification

```bash
uv run pytest tests/integration/test_pool_worktree_isolation.py -v
uv run pytest tests/property/test_worktree_path_uniqueness_property.py -v
uv run pytest --cov=mahavishnu --cov-fail-under=89.01682905225863
uv run crackerjack run -p minor
```

## Acceptance criteria (decisive pass/fail)

1. `mahavishnu/core/worktree_options.py` exists with `WorktreeOptions` Pydantic model.
2. `WorktreeInfo` has new fields `diff: str`, `merge: bool`, `files_touched: list[str]` (REPLACED, not extended).
3. `to_dict()` includes all 9 fields (5 original + 3 new + created_at preserved).
4. `complete_worktree()` returns a `WorktreeCompletion` wrapping the populated `WorktreeInfo` (REPLACED — does not return a tuple or None).
5. **No `GitRunner` class exists** anywhere in `mahavishnu/` (`grep -r "class GitRunner" mahavishnu/` returns nothing).
6. `WorktreeLockedError` is the ONLY worktree-lock exception (no competing subclass).
7. `pool_route_execute(worktree=...)` returns `result["worktree"]` dict with `diff`, `merge`, `files_touched` keys.
8. Two concurrent dispatches with `isolation="worktree"` against the same repo: one succeeds, one observes `WorktreeLockedError` → `{"status": "worktree_conflict", ...}`.
9. `pool_route_execute` arg count is ≤ 10 (C-6 + C-8 = 9 args; verified by `crackerjack run`).
10. Property test passes for 50 random distinct task IDs.
11. `python scripts/audit_requirements.py --json` reports REQ-010, REQ-011 wired.
12. `crackerjack run` passes; coverage gate holds.

## Rollback / recovery narration

Per `feedback-no-backwards-compat-pre-1.0`:
- `WorktreeInfo` is REPLACED (the new shape is incompatible with code that reads old fields). Code that reads old fields must be updated in the same commit (the `worktree_manage` MCP tool's `to_dict()` output is preserved for backward compat).
- No `GitRunner` shim. The plan uses `asyncio.to_thread(subprocess.run)` directly.
- `worktree.isolation` defaults to `"host"` (existing behavior); callers must opt in with `isolation="worktree"`.

Recovery for a bad merge outcome: set `worktree_storage.enabled: false` in `settings/mahavishnu.yaml` (added in C-1). All calls fall back to host-isolation. No code rollback required.

## Observability added

Three new Prometheus metrics:

- `worktree_creation_total{result}` — Counter (success | lock_conflict | error)
- `worktree_active_count` — Gauge
- `worktree_disk_bytes` — Gauge

Operators alert on `rate(worktree_creation_total{result="lock_conflict"}[5m]) > 0.5` (too many lock conflicts = concurrency limits misconfigured). `worktree_active_count` and `worktree_disk_bytes` feed capacity dashboards.

## Health aggregation

`worktree_disk_bytes > max_disk_bytes` should trigger a 503 from `/health` if operators choose. The plan does not add the check by default — operators opt in via a follow-up commit.

## Implementation notes / gotchas

- **`WorktreeInfo` REPLACEMENT is strict.** Code that does `info.diff()` (calling the old method) breaks immediately. `grep -r "\.diff()" mahavishnu/` to find any callers; update them in this commit to read `info.diff` (attribute) instead.
- **`asyncio.to_thread(subprocess.run)`** is the canonical pattern for blocking subprocess calls in async code. No `GitRunner` abstraction needed — the function call is already a single line.
- **`WorktreeCompletion` wrapper** lets future revisions add fields (e.g., `merge_conflict: bool`) without changing the return type signature. The pool dispatch reads `completion.info` and adds fields to `result["worktree"]`.
- **`subprocess.run(..., check=True)`** raises `CalledProcessError` on non-zero exit. The `await asyncio.to_thread` propagates the exception. `pool_route_execute`'s `except WorktreeError` clause catches it (verify the existing handler does not swallow unrelated exceptions).
- **Property test uses `hypothesis.strategies.uuids()`** for distinct task IDs. The 50-example setting is conservative; expand if flakes appear in CI.
- **The companion CLI `mahavishnu worktree status`** (per spec) is unchanged — uses existing `worktree_manage(action="list", ...)`.
- **`worktree_manage` MCP tool reads `WorktreeInfo.to_dict()`.** The new `to_dict()` includes the 3 new fields; old consumers that ignore unknown keys (e.g., the JSON serialization layer) are unaffected.
- **The fictional `GitRunner` is NOT replaced by an "equivalent" abstraction.** Per no-backcompat, the abstraction would be a layer of indirection with no functional purpose. Use `asyncio.to_thread(subprocess.run)` directly.
- **`isolation: Literal["host", "worktree"]`** — only two values are valid. `"process"` or `"docker"` would require additional plumbing; out of scope for C-8.
- **TTL bucket applies to the worktree lifetime, not the idempotency record.** Cleanup runs in the `finally` block; if the dispatch hangs past TTL, cleanup still runs (the TTL is checked on next pool health probe, not mid-dispatch).

## Files modified (summary)

| File | Action | LoC |
|---|---|---|
| `mahavishnu/core/worktree_options.py` | create | ~30 |
| `mahavishnu/core/worktree_manager.py` | edit (REPLACE `WorktreeInfo` shape + extend `complete_worktree` + add `WorktreeCompletion`) | +80 / -20 |
| `mahavishnu/mcp/tools/pool_tools.py` | edit (add `worktree` kwarg + dispatch path) | +90 |
| `mahavishnu/core/metrics.py` | edit (add 3 metrics) | +20 |
| `tests/integration/test_pool_worktree_isolation.py` | create | +280 |
| `tests/property/test_worktree_path_uniqueness_property.py` | create | +80 |
