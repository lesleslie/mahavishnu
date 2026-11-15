"""The pool's worktree helpers: where the worker ran, and what it left behind.

Two things matter to a caller that asked for isolation:

- **Where the worker ran.** The dispatch result must say which
  checkout the worker was in. Without it an isolated run and a
  shared-checkout run look identical to the caller, and a dispatch
  that silently fell back to the shared checkout is indistinguishable
  from one that isolated.
- **What the worktree left behind.** ``git worktree add -b`` creates a
  branch as a side effect. Removing the worktree does not remove that
  branch, so every isolated dispatch leaked one branch into the
  repository — three per merge once the reviewers ran concurrently.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from mahavishnu.core._producer_metrics import WORKTREE_ISOLATION_REFUSALS_TOTAL
from mahavishnu.core.worktree_options import WorktreeOptions
from mahavishnu.mcp.tools.pool_tools import (
    REPO_ALLOWED,
    REPO_NOT_A_GIT_REPO,
    REPO_NOT_AUTHORIZED,
    REPO_SETTINGS_UNAVAILABLE,
    REPO_UNRESOLVED,
    _discard_worktree_branch,
    _finalize_worktree,
    _isolation_refusal_message,
    _prepare_worktree,
    _resolve_repo_nickname,
    _resolve_repo_path,
    _validate_repo_path,
)

_DISCARD = WorktreeOptions(isolation="worktree", on_completion="discard")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # nosec B603 — argv-list, no shell
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with one commit and one extra branch."""
    _git(tmp_path, "init", "-q", ".")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "f.txt").write_text("base\n")
    _git(tmp_path, "add", "f.txt")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "branch", "feature/ephemeral")
    return tmp_path


class _FakeManager:
    """A worktree manager stand-in that completes with a fixed info."""

    def __init__(self, info: Any) -> None:
        self._info = info

    async def complete_worktree(
        self,
        worktree_id: str,
        merge: bool = False,
        repo_path: Path | None = None,
    ) -> Any:
        return SimpleNamespace(info=self._info)


def _info(**overrides: Any) -> Any:
    base = {
        "worktree_id": "wt-1",
        "worktree_path": Path("/tmp/wt-1"),
        "branch_name": "feature/ephemeral",
        "base_branch": "feat/under-review",
        "diff": "diff --git a/f b/f",
        "merge": False,
        "files_touched": ["f.txt"],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _refusal_count(reason: str) -> float:
    """The current value of the refusal counter for one reason."""
    return WORKTREE_ISOLATION_REFUSALS_TOTAL.labels(reason=reason)._value.get()


class TestTheWorktreeContext:
    @pytest.mark.asyncio
    async def test_the_result_says_where_the_worker_ran(self) -> None:
        result: dict[str, Any] = {}

        await _finalize_worktree(
            _FakeManager(_info()),
            _info(),
            _DISCARD,
            Path("/repo"),
            result,
        )

        context = result["worktree"]
        assert context["path"] == Path("/tmp/wt-1")
        assert context["branch"] == "feature/ephemeral"
        assert context["base_branch"] == "feat/under-review"
        assert context["files_touched"] == ["f.txt"]

    @pytest.mark.asyncio
    async def test_a_completion_failure_is_reported_not_raised(self) -> None:
        class _FailingManager:
            async def complete_worktree(self, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("boom")

        result: dict[str, Any] = {}

        await _finalize_worktree(
            _FailingManager(),
            None,
            _DISCARD,
            Path("/repo"),
            result,
        )

        assert "error" in result["worktree"]


class TestTheBranchIsDiscarded:
    @pytest.mark.asyncio
    async def test_the_ephemeral_branch_is_deleted(self, repo: Path) -> None:
        assert "feature/ephemeral" in _git(repo, "branch", "--list")

        await _discard_worktree_branch(_info(), repo)

        assert "feature/ephemeral" not in _git(repo, "branch", "--list")

    @pytest.mark.asyncio
    async def test_other_branches_survive(self, repo: Path) -> None:
        _git(repo, "branch", "feature/keep-me")

        await _discard_worktree_branch(_info(), repo)

        remaining = _git(repo, "branch", "--list")
        assert "feature/keep-me" in remaining

    @pytest.mark.asyncio
    async def test_no_branch_name_is_a_no_op(self, repo: Path) -> None:
        await _discard_worktree_branch(_info(branch_name=None), repo)

        assert "feature/ephemeral" in _git(repo, "branch", "--list")

    @pytest.mark.asyncio
    async def test_no_repo_path_is_a_no_op(self) -> None:
        # Nothing to delete against; the caller must not crash.
        await _discard_worktree_branch(_info(), None)

    @pytest.mark.asyncio
    async def test_a_missing_branch_does_not_raise(self, repo: Path) -> None:
        """A deletion failure is untidy, not dangerous."""
        await _discard_worktree_branch(_info(branch_name="feature/never-existed"), repo)


class TestTheRepositoryIsAuthorized:
    """Creating a worktree of a repository is a security boundary.

    The pool may create a worktree of a repository and run a worker in
    it, so the repository it is allowed to name is the boundary: an
    unchecked path would let a dispatch isolate a worktree of anything
    readable on the host. The operator's authorized roots come from the
    settings, and the repo's own ``PathValidator`` does the checking.
    """

    @staticmethod
    def _settings(allowed: list[str]) -> Any:
        return SimpleNamespace(allowed_repo_paths=allowed)

    def test_a_repository_inside_an_allowed_root_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowed = tmp_path / "projects"
        repo = allowed / "crackerjack"
        repo.mkdir(parents=True)
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.pool_tools.get_settings",
            lambda: self._settings([str(allowed)]),
        )

        path, reason = _validate_repo_path(repo)
        assert path == repo.resolve()
        assert reason == REPO_ALLOWED

    def test_a_repository_outside_the_allowed_roots_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowed = tmp_path / "projects"
        allowed.mkdir()
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.pool_tools.get_settings",
            lambda: self._settings([str(allowed)]),
        )

        path, reason = _validate_repo_path(outside)
        assert path is None
        assert reason == REPO_NOT_AUTHORIZED

    def test_a_repository_that_does_not_exist_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.pool_tools.get_settings",
            lambda: self._settings([str(tmp_path)]),
        )

        path, reason = _validate_repo_path(tmp_path / "absent")
        assert path is None
        assert reason == REPO_UNRESOLVED

    def test_no_configured_roots_means_nothing_is_authorized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unset allowlist is not an open door."""
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.pool_tools.get_settings",
            lambda: self._settings([]),
        )

        path, reason = _validate_repo_path(tmp_path)
        assert path is None
        assert reason == REPO_NOT_AUTHORIZED


class TestTheRepositoryToken:
    """The prompt names the repository the worktree is forked from."""

    @pytest.mark.asyncio
    async def test_an_absolute_token_names_the_repository(self, tmp_path: Path) -> None:
        nickname = await _resolve_repo_nickname(
            f"Review this branch\nRepository: {tmp_path}/.git"
        )

        # The token is the path with its ``.git`` suffix removed; the
        # separator before it stays, and ``Path`` normalises that away.
        assert Path(nickname) == tmp_path

    @pytest.mark.asyncio
    async def test_a_relative_token_is_kept_relative(self) -> None:
        nickname = await _resolve_repo_nickname("Repository: ../crackerjack.git")

        assert nickname == "../crackerjack"

    @pytest.mark.asyncio
    async def test_a_path_without_the_git_suffix_is_not_a_token(self) -> None:
        """The worktree path in the prompt is not a repository token."""
        nickname = await _resolve_repo_nickname("Worktree: /tmp/some-worktree")

        assert nickname == ""

    @pytest.mark.asyncio
    async def test_a_mentioned_repository_url_is_not_a_token(self) -> None:
        """A prompt that *mentions* a repository does not name one.

        The token is read from a ``Repository:`` line, so a URL in a
        bug report or an SSH remote in a clone instruction is prose,
        not a request to isolate. Scanning the whole prompt for a
        ``.git`` token made those prompts name a repository — usually
        not a local path — which turned an ordinary dispatch into a
        refusal.
        """
        for prompt in (
            "Look at https://example.com/repo.git and fix the README",
            "clone git@github.com:someone/thing.git then review it",
            "the failure was in /srv/checkouts/thing.git",
        ):
            nickname = await _resolve_repo_nickname(prompt)

            assert nickname == "", f"{prompt!r} was read as a repository"

    @pytest.mark.asyncio
    async def test_the_marker_line_wins_over_a_mention(self, tmp_path: Path) -> None:
        """The named repository is the one the caller asked for."""
        nickname = await _resolve_repo_nickname(
            f"compare against https://example.com/other.git\n"
            f"Repository: {tmp_path}/.git"
        )

        assert Path(nickname) == tmp_path

    def test_an_absolute_nickname_resolves_to_itself(self, tmp_path: Path) -> None:
        assert _resolve_repo_path(str(tmp_path)) == tmp_path

    def test_a_relative_nickname_resolves_against_the_cwd(self) -> None:
        assert _resolve_repo_path("crackerjack") == Path.cwd() / "crackerjack"


class TestTheRefusalNamesTheReason:
    """The refusal is the operator's only signal.

    The dispatch did not happen, so nothing else will tell the
    operator why. A wrong prompt, a policy decision and a broken
    server are three different problems; one message covering all
    three sends the operator to fix the wrong one.
    """

    def test_an_unauthorized_repository_names_the_policy(self) -> None:
        message = _isolation_refusal_message(REPO_NOT_AUTHORIZED)

        assert "allowed_repo_paths" in message
        assert "not inside an allowed repository root" in message

    def test_an_unresolved_repository_names_the_prompt(self) -> None:
        message = _isolation_refusal_message(REPO_UNRESOLVED)

        assert "does not resolve to a local path" in message
        assert "'<repo path>/.git'" in message

    def test_a_non_git_path_says_so(self) -> None:
        message = _isolation_refusal_message(REPO_NOT_A_GIT_REPO)

        assert "not a git working tree" in message

    def test_unreadable_settings_say_so(self) -> None:
        message = _isolation_refusal_message(REPO_SETTINGS_UNAVAILABLE)

        assert "could not be read" in message
        assert "Check the Mahavishnu settings" in message

    def test_every_refusal_says_the_task_was_not_dispatched(self) -> None:
        """The consequence is the same for every reason."""
        for reason in (
            REPO_NOT_AUTHORIZED,
            REPO_UNRESOLVED,
            REPO_NOT_A_GIT_REPO,
            REPO_SETTINGS_UNAVAILABLE,
            "something-else",
        ):
            message = _isolation_refusal_message(reason)

            assert "not dispatched" in message, reason
            assert "shared checkout" in message, reason


class TestTheRefusalIsCounted:
    """A refusal that only logs is a silence on-call cannot hear."""

    @pytest.mark.asyncio
    async def test_the_refusal_counts_its_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowed = tmp_path / "projects"
        allowed.mkdir()
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.pool_tools.get_settings",
            lambda: SimpleNamespace(allowed_repo_paths=[str(allowed)]),
        )
        before = _refusal_count(REPO_NOT_AUTHORIZED)

        result = await _prepare_worktree(
            WorktreeOptions(isolation="worktree"),
            f"Repository: {outside}/.git",
            "exec-1",
            "worktree",
            _FakeManager(_info()),
        )

        assert result[2] is not None
        assert result[2]["status"] == "failed"
        assert _refusal_count(REPO_NOT_AUTHORIZED) == before + 1


class TestTheAllowlistIsConfiguration:
    """The allowlist is the operator's, and nothing widens it.

    The security boundary is the configured set of roots. Widening it
    at validation time -- by appending the process's working
    directory, say -- makes the effective boundary depend on where
    the server happens to be running, which is not a decision the
    operator made about which repositories may be isolated.

    The server's own checkout is therefore authorized by the
    *configuration*: it is the default of the setting, and the
    deployment config adds the fleet's roots beside it.
    """

    def test_a_path_outside_the_configured_roots_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        elsewhere = tmp_path / "somewhere-else"
        elsewhere.mkdir()
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.pool_tools.get_settings",
            lambda: SimpleNamespace(allowed_repo_paths=[str(elsewhere)]),
        )

        path, reason = _validate_repo_path(Path.cwd())

        assert path is None
        assert reason == REPO_NOT_AUTHORIZED

    def test_an_empty_allowlist_still_authorizes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty allowlist is a deliberate deny-all.

        It is not an unconfigured default, so the server's own checkout
        must not slip past it.
        """
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.pool_tools.get_settings",
            lambda: SimpleNamespace(allowed_repo_paths=[]),
        )

        path, reason = _validate_repo_path(Path.cwd())

        assert path is None
        assert reason == REPO_NOT_AUTHORIZED

    def test_the_settings_default_is_the_servers_own_checkout(self) -> None:
        """The default is the one repository every install has."""
        from mahavishnu.core.config import MahavishnuSettings

        settings = MahavishnuSettings()

        assert str(Path.cwd()) in settings.allowed_repo_paths
