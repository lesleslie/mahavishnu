"""Tests for ``pool_route_execute(worktree=WorktreeOptions(...))`` + ``WorktreeInfo`` shape (C-8 / REQ-010/011).

Round-8 corrections applied:
- ``tmp_git_repo`` fixture provided HERE (it does NOT exist in conftest_wireups.py).
- ``finally`` cleanup test patches ``_validate_repo_path`` so the test works on a
  non-git ``tmp_path``.
- Concurrent-caller test uses ``asyncio.gather`` to fire two simultaneous
  dispatches, ensuring exactly one observes ``WorktreeLockedError``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.errors import WorktreeLockedError
from mahavishnu.core.worktree_manager import (
    WorktreeCompletion,
    WorktreeInfo,
    WorktreeManager,
)
from mahavishnu.core.worktree_options import WorktreeOptions

# ---------------------------------------------------------------------------
# Round-8 FIX #1: ``tmp_git_repo`` fixture (does NOT exist in conftest_wireups).
# Creates a real git repo in ``tmp_path`` with one initial commit so
# ``git worktree add`` has something to fork from.
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Initialize a real git repository under ``tmp_path`` with one commit."""
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "README.md").write_text("initial\n")
    subprocess.run(
        ["git", "add", "."],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return tmp_path


def _capture_pool_route_execute(mock_pool_manager: MagicMock):
    """Capture the registered ``pool_route_execute`` callable via a stubbed
    ``mcp.tool`` decorator. Returns the real ``pool_route_execute`` function so
    tests can call it directly.
    """
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    captured: dict[str, object] = {}

    def registering_decorator(func=None):
        if func is None:
            return lambda wrapped: registering_decorator(wrapped)
        captured[func.__name__] = func
        return func

    mcp = MagicMock()
    mcp.tool = registering_decorator
    register_pool_tools(mcp, mock_pool_manager)
    return captured["mahavishnu_pool_route_execute"]


# ---------------------------------------------------------------------------
# WorktreeOptions input-model tests
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-010"])
class TestWorktreeOptions:
    def test_defaults(self) -> None:
        opts = WorktreeOptions()
        assert opts.isolation == "host"
        assert opts.base_branch == "main"
        assert opts.ttl_seconds == 86_400
        assert opts.on_completion == "return_diff"

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValueError, match="literal_error"):
            WorktreeOptions(isolation="bogus")

    def test_ttl_bounds(self) -> None:
        with pytest.raises(ValueError):
            WorktreeOptions(ttl_seconds=30)
        with pytest.raises(ValueError):
            WorktreeOptions(ttl_seconds=2_000_000)

    def test_base_branch_bounds(self) -> None:
        with pytest.raises(ValueError):
            WorktreeOptions(base_branch="")
        with pytest.raises(ValueError):
            WorktreeOptions(base_branch="x" * 256)

    def test_on_completion_literal(self) -> None:
        with pytest.raises(ValueError):
            WorktreeOptions(on_completion="bogus")


# ---------------------------------------------------------------------------
# WorktreeInfo REPLACED-shape tests
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-010"])
class TestWorktreeInfoReplaced:
    def test_worktree_info_has_new_fields(self) -> None:
        info = WorktreeInfo(
            worktree_id="wt-001",
            repo_path=Path("/tmp/repo"),
            branch_name="feature/wt-001",
            base_branch="main",
            created_at=datetime.now(UTC),
            ttl_seconds=3600,
        )
        assert info.diff == ""
        assert info.merge is False
        assert info.files_touched == []
        d = info.to_dict()
        assert "diff" in d
        assert "merge" in d
        assert "files_touched" in d
        assert len(d) == 9


@pytest.mark.req(["REQ-011"])
class TestWorktreeLockedErrorReused:
    def test_no_competing_subclass(self) -> None:
        """Per REQ-011: ``WorktreeLockedError`` is the ONLY lock exception."""
        import inspect

        from mahavishnu.core import worktree_manager

        for name, obj in inspect.getmembers(worktree_manager):
            if inspect.isclass(obj) and "Lock" in name and "Worktree" in name:
                assert obj is WorktreeLockedError, (
                    f"competing WorktreeLock* subclass: {name}"
                )


# ---------------------------------------------------------------------------
# complete_worktree() populates diff/merge/files_touched
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-010"])
class TestCompleteWorktreePopulates:
    @pytest.mark.asyncio
    async def test_complete_worktree_returns_diff(
        self, tmp_git_repo: Path, tmp_path: Path
    ) -> None:
        """``complete_worktree()`` populates diff/merge/files_touched via git subprocess."""
        wt_root = tmp_path / "wt-root"
        wt_root.mkdir()
        mgr = WorktreeManager(base_path=str(wt_root))
        try:
            info = await mgr.create_worktree(
                task_id="exec-001",
                repo_path=tmp_git_repo,
                branch_name="feature/exec-001",
                base_branch="main",
                ttl_seconds=3600,
            )
            wt_path = tmp_git_repo / ".worktrees" / info.worktree_id
            (wt_path / "new_file.txt").write_text("hello\n")
            subprocess.run(
                ["git", "add", "new_file.txt"],
                cwd=wt_path,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "add file"],
                cwd=wt_path,
                check=True,
                capture_output=True,
                text=True,
            )
            completion = await mgr.complete_worktree(
                worktree_id=info.worktree_id,
                merge=False,
                repo_path=tmp_git_repo,
            )
            assert isinstance(completion, WorktreeCompletion)
            assert "new_file.txt" in completion.info.files_touched
            assert "new_file.txt" in completion.info.diff
            assert completion.info.merge is False
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force"],
                cwd=tmp_git_repo,
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "branch", "-D", "feature/exec-001"],
                cwd=tmp_git_repo,
                capture_output=True,
                check=False,
            )


# ---------------------------------------------------------------------------
# pool_route_execute(worktree=...) end-to-end behavior
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-010"])
class TestPoolRouteExecuteWorktree:
    @pytest.mark.asyncio
    async def test_worktree_creation_emits_event(self, tmp_git_repo: Path) -> None:
        """``pool_route_execute(worktree=...)`` returns ``result["worktree"]`` dict."""
        pool_route_execute = _capture_pool_route_execute(MagicMock())
        opts = WorktreeOptions(isolation="worktree", base_branch="main")

        async def _fake_dispatch(**kwargs: object) -> dict[str, object]:
            return {"status": "success", "result": "ok"}

        with (
            patch(
                "mahavishnu.mcp.tools.pool_tools._validate_repo_path",
                side_effect=lambda path: (path, "allowed"),
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._dispatch_internal",
                new=_fake_dispatch,
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._resolve_repo_nickname",
                new=AsyncMock(return_value=tmp_git_repo.name),
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._resolve_repo_path",
                return_value=tmp_git_repo,
            ),
        ):
            result = await pool_route_execute(
                prompt=f"edit {tmp_git_repo.name}",
                pool_selector="least_loaded",
                worktree=opts,
            )
        assert result["status"] == "success"
        assert "worktree" in result
        assert "files_touched" in result["worktree"]

    @pytest.mark.asyncio
    async def test_dispatch_runs_in_the_worktree(self, tmp_git_repo: Path) -> None:
        """The dispatched task names the worktree as its working directory.

        Without this the worker edits the source repo while the diff is
        captured from the untouched worktree: isolation that isolates
        nothing, and an empty diff that reads like "the worker did
        nothing". The worktree path is checked for existence *inside* the
        dispatch because the finally-block removes the worktree before
        the assertion runs.
        """
        pool_route_execute = _capture_pool_route_execute(MagicMock())
        opts = WorktreeOptions(isolation="worktree", base_branch="main")

        captured: dict[str, object] = {}

        async def _fake_dispatch(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            cwd_value = kwargs.get("cwd")
            captured["cwd_existed"] = (
                Path(str(cwd_value)).is_dir() if cwd_value else False
            )
            return {"status": "success", "result": "ok"}

        with (
            patch(
                "mahavishnu.mcp.tools.pool_tools._validate_repo_path",
                side_effect=lambda path: (path, "allowed"),
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._dispatch_internal",
                new=_fake_dispatch,
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._resolve_repo_nickname",
                new=AsyncMock(return_value=tmp_git_repo.name),
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._resolve_repo_path",
                return_value=tmp_git_repo,
            ),
        ):
            result = await pool_route_execute(
                prompt=f"edit {tmp_git_repo.name}",
                pool_selector="least_loaded",
                worktree=opts,
            )

        assert result["status"] == "success"
        cwd = captured.get("cwd")
        assert cwd is not None, "the dispatch received no working directory"
        assert captured["cwd_existed"] is True
        assert Path(str(cwd)).parent == tmp_git_repo / ".worktrees"

    @pytest.mark.asyncio
    async def test_no_worktree_leaves_cwd_unset(self) -> None:
        """A dispatch without worktree isolation must not invent a cwd."""
        pool_route_execute = _capture_pool_route_execute(MagicMock())

        captured: dict[str, object] = {}

        async def _fake_dispatch(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"status": "success", "result": "ok"}

        with patch(
            "mahavishnu.mcp.tools.pool_tools._dispatch_internal",
            new=_fake_dispatch,
        ):
            result = await pool_route_execute(
                prompt="edit something",
                pool_selector="least_loaded",
            )

        assert result["status"] == "success"
        assert captured.get("cwd") is None

    @pytest.mark.asyncio
    async def test_worktree_lock_conflict_returns_error(self) -> None:
        """Two concurrent dispatches with ``isolation="worktree"``: one
        succeeds, one observes ``WorktreeLockedError`` and returns
        ``{"status": "worktree_conflict", ...}``.

        Round-8 FIX: concurrent caller coverage via ``asyncio.gather``.
        """
        pool_route_execute = _capture_pool_route_execute(MagicMock())

        mock_wt = WorktreeInfo(
            worktree_id="wt-conflict-test",
            repo_path=Path("/tmp/test-repo"),
            branch_name="feature/concurrent",
            base_branch="main",
            created_at=datetime.now(UTC),
            ttl_seconds=3600,
        )

        # Side-effect function: first call returns success, second raises.
        call_count = {"n": 0}

        def _create_side_effect(*args: object, **kwargs: object):
            call_count["n"] += 1
            if call_count["n"] == 1:

                async def _ok() -> WorktreeInfo:
                    return mock_wt

                return _ok()
            raise WorktreeLockedError("test conflict")

        async def _fake_dispatch(**kwargs: object) -> dict[str, object]:
            return {"status": "success", "result": "ok"}

        opts = WorktreeOptions(isolation="worktree")
        with (
            patch(
                "mahavishnu.mcp.tools.pool_tools._validate_repo_path",
                side_effect=lambda path: (path, "allowed"),
            ),
            patch.object(
                WorktreeManager,
                "create_worktree",
                side_effect=_create_side_effect,
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._dispatch_internal",
                new=_fake_dispatch,
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._resolve_repo_nickname",
                new=AsyncMock(return_value="test-repo"),
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._resolve_repo_path",
                return_value=Path("/tmp/test-repo"),
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._path_is_git_repo",
                new=AsyncMock(return_value=True),
            ),
        ):
            results = await asyncio.gather(
                pool_route_execute(
                    prompt="edit repo",
                    pool_selector="least_loaded",
                    worktree=opts,
                ),
                pool_route_execute(
                    prompt="edit repo",
                    pool_selector="least_loaded",
                    worktree=opts,
                ),
                return_exceptions=False,
            )
            statuses = {r["status"] for r in results}
            assert statuses == {"success", "worktree_conflict"}

    @pytest.mark.asyncio
    async def test_finally_block_cleans_up_worktree_on_dispatch_failure(self) -> None:
        """The ``finally`` block in ``pool_route_execute`` MUST run
        ``cleanup_worktree`` even when the dispatch raises.

        Round-8 FIX: patch ``_validate_repo_path`` so the worktree path
        activates even though the test cwd is not a git repo.
        """
        pool_route_execute = _capture_pool_route_execute(MagicMock())

        mock_worktree_info = WorktreeInfo(
            worktree_id="wt-leak-test",
            repo_path=Path("/tmp/test-repo"),
            branch_name="feature/wt-leak-test",
            base_branch="main",
            created_at=datetime.now(UTC),
            ttl_seconds=3600,
        )
        with (
            patch.object(
                WorktreeManager,
                "create_worktree",
                new=AsyncMock(return_value=mock_worktree_info),
            ),
            patch.object(
                WorktreeManager,
                "cleanup_worktree",
                new=AsyncMock(),
            ) as mock_cleanup,
            patch(
                "mahavishnu.mcp.tools.pool_tools._dispatch_internal",
                new=AsyncMock(side_effect=RuntimeError("dispatch failed")),
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._validate_repo_path",
                side_effect=lambda path: (path, "allowed"),  # FIX round-8: activate worktree path
            ),
        ):
            with pytest.raises(RuntimeError, match="dispatch failed"):
                await pool_route_execute(
                    prompt="edit test",
                    pool_selector="least_loaded",
                    worktree=WorktreeOptions(isolation="worktree"),
                )
            mock_cleanup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_worktree_path_when_isolation_is_host(self) -> None:
        """When ``WorktreeOptions.isolation == "host"`` the worktree path is skipped."""
        pool_route_execute = _capture_pool_route_execute(MagicMock())

        async def _fake_dispatch(**kwargs: object) -> dict[str, object]:
            return {"status": "success", "result": "ok"}

        with (
            patch(
                "mahavishnu.mcp.tools.pool_tools._dispatch_internal",
                new=_fake_dispatch,
            ),
            patch.object(
                WorktreeManager,
                "create_worktree",
            ) as mock_create,
        ):
            result = await pool_route_execute(
                prompt="hello",
                pool_selector="least_loaded",
                worktree=WorktreeOptions(isolation="host"),
            )
            assert result["status"] == "success"
            assert "worktree" not in result
            mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# The discarded worktree must not leave its branch behind
# ---------------------------------------------------------------------------


def _feature_branches(repo: Path) -> list[str]:
    """The ephemeral branches a worktree creation leaves in the repo."""
    output = subprocess.run(
        ["git", "branch", "--list", "feature/*"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line.strip() for line in output.splitlines() if line.strip()]


@pytest.mark.req(["REQ-010"])
class TestTheDiscardedWorktreeLeavesNoBranch:
    """``git worktree add -b`` creates a branch as a side effect.

    Removing the worktree does not remove that branch, so every
    worktree-isolated dispatch leaked one branch into the repository —
    three per merge with the concurrent ensemble review, accumulating
    in the branch list forever. The ``on_completion="discard"`` mode
    is the one that throws the work away, so it is the one that
    deletes the branch; the other modes keep it, because there the
    branch is where the work still lives.
    """

    @pytest.mark.asyncio
    async def test_a_discarded_worktree_leaves_no_branch(
        self, tmp_git_repo: Path
    ) -> None:
        pool_route_execute = _capture_pool_route_execute(MagicMock())
        opts = WorktreeOptions(
            isolation="worktree",
            base_branch="main",
            on_completion="discard",
        )

        async def _fake_dispatch(**kwargs: object) -> dict[str, object]:
            return {"status": "success", "result": "ok"}

        with (
            patch(
                "mahavishnu.mcp.tools.pool_tools._validate_repo_path",
                side_effect=lambda path: (path, "allowed"),
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._dispatch_internal",
                new=_fake_dispatch,
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._resolve_repo_nickname",
                new=AsyncMock(return_value=tmp_git_repo.name),
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._resolve_repo_path",
                return_value=tmp_git_repo,
            ),
        ):
            result = await pool_route_execute(
                prompt=f"edit {tmp_git_repo.name}",
                pool_selector="least_loaded",
                worktree=opts,
            )

        assert result["status"] == "success"
        leaked = _feature_branches(tmp_git_repo)
        assert leaked == [], f"the discarded worktree leaked a branch: {leaked!r}"

    @pytest.mark.asyncio
    async def test_a_returned_diff_worktree_keeps_its_branch(
        self, tmp_git_repo: Path
    ) -> None:
        """The other modes keep the branch — there the work still lives."""
        pool_route_execute = _capture_pool_route_execute(MagicMock())
        opts = WorktreeOptions(isolation="worktree", base_branch="main")

        async def _fake_dispatch(**kwargs: object) -> dict[str, object]:
            return {"status": "success", "result": "ok"}

        with (
            patch(
                "mahavishnu.mcp.tools.pool_tools._validate_repo_path",
                side_effect=lambda path: (path, "allowed"),
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._dispatch_internal",
                new=_fake_dispatch,
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._resolve_repo_nickname",
                new=AsyncMock(return_value=tmp_git_repo.name),
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._resolve_repo_path",
                return_value=tmp_git_repo,
            ),
        ):
            result = await pool_route_execute(
                prompt=f"edit {tmp_git_repo.name}",
                pool_selector="least_loaded",
                worktree=opts,
            )

        assert result["status"] == "success"
        assert _feature_branches(tmp_git_repo) != []


# ---------------------------------------------------------------------------
# The repository the worktree is forked from
# ---------------------------------------------------------------------------


@pytest.mark.req(["REQ-010"])
class TestTheIsolatedRepositoryIsNamed:
    """The caller knows which repository the work belongs to.

    The server's own heuristic reads a ``.git``-suffixed token out of
    the dispatch prompt and resolves it against the server's working
    directory — so it can only ever name the server's repository. A
    merge reviewing a branch in another repository has to say which
    repository it means; without that, the worktree is forked from
    the wrong place and every cross-repo merge dies at stage 2.
    """

    @pytest.mark.asyncio
    async def test_an_absolute_repository_token_names_the_repository(
        self, tmp_git_repo: Path
    ) -> None:
        """The prompt names the repository the worktree is forked from.

        The pool resolves the repository out of the dispatch prompt,
        because the server's working directory is its *own* checkout:
        a relative token can only ever name a repository beside it. A
        merge reviewing a branch in another repository has to name it
        in full.
        """
        pool_route_execute = _capture_pool_route_execute(MagicMock())
        opts = WorktreeOptions(isolation="worktree", base_branch="main")

        captured: dict[str, object] = {}

        async def _fake_dispatch(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"status": "success", "result": "ok"}

        with (
            patch(
                "mahavishnu.mcp.tools.pool_tools._validate_repo_path",
                side_effect=lambda path: (path, "allowed"),
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._dispatch_internal",
                new=_fake_dispatch,
            ),
        ):
            result = await pool_route_execute(
                prompt=f"review this branch\nRepository: {tmp_git_repo}/.git",
                pool_selector="least_loaded",
                worktree=opts,
            )

        assert result["status"] == "success"
        cwd = captured.get("cwd")
        assert cwd is not None, "the dispatch received no working directory"
        assert Path(str(cwd)).parent == tmp_git_repo / ".worktrees"

    @pytest.mark.asyncio
    async def test_an_unresolvable_repository_refuses_before_the_dispatch(
        self, tmp_git_repo: Path
    ) -> None:
        """Isolation was asked for and could not be provided.

        Dispatching anyway would run the worker in the shared
        checkout — the exact harm the isolation exists to prevent —
        and the caller would only find out afterwards, once the harm
        was done. So the dispatch must not happen at all.
        """
        pool_route_execute = _capture_pool_route_execute(MagicMock())
        opts = WorktreeOptions(isolation="worktree", base_branch="main")

        dispatched = False

        async def _fake_dispatch(**kwargs: object) -> dict[str, object]:
            nonlocal dispatched
            dispatched = True
            return {"status": "success", "result": "ok"}

        with (
            patch(
                "mahavishnu.mcp.tools.pool_tools._validate_repo_path",
                return_value=(None, "unresolved"),
            ),
            patch(
                "mahavishnu.mcp.tools.pool_tools._dispatch_internal",
                new=_fake_dispatch,
            ),
        ):
            result = await pool_route_execute(
                prompt="review this branch",
                pool_selector="least_loaded",
                worktree=opts,
            )

        assert dispatched is False, "the worker ran without an isolated checkout"
        assert result["status"] == "failed"
        assert "isolation was requested" in result["error"]
