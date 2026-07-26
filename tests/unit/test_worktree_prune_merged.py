from __future__ import annotations

from pathlib import Path  # noqa: TC003 — used directly by test fixtures
import subprocess

import pytest

from mahavishnu.core.worktree_prune_merged import (
    WorktreePruneCandidate,
    WorktreePruner,
    classify_merge_status,
    find_merged_worktrees,
)


def run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )


def init_repo(repo: Path, branch: str = "main") -> None:
    repo.mkdir()
    run_git("init", f"--initial-branch={branch}", cwd=repo)
    run_git("config", "user.email", "test@example.com", cwd=repo)
    run_git("config", "user.name", "Test", cwd=repo)
    (repo / "base.txt").write_text("base\n")
    run_git("add", "base.txt", cwd=repo)
    run_git("commit", "-m", "base", cwd=repo)


def candidate(
    path: Path,
    *,
    merge_status: str = "merged",
    dirty_status: str = "clean",
) -> WorktreePruneCandidate:
    return WorktreePruneCandidate(
        repo_path=path.parent,
        repo_nickname="vishnu",
        worktree_path=path,
        branch="feat",
        head_sha="abc123",
        merge_status=merge_status,
        dirty_status=dirty_status,
        behind=2,
        last_touched_at="2026-07-20T00:00:00+00:00",
    )


def test_candidate_fields_round_trip(tmp_path: Path) -> None:
    merged = candidate(tmp_path / "wt")
    assert merged.is_merged is True
    assert merged.is_clean is True
    assert merged.age_days is not None

    unknown = candidate(
        tmp_path / "unknown", merge_status="undetermined", dirty_status="undetermined"
    )
    assert unknown.is_merged is False
    assert unknown.is_clean is False


def test_classify_merge_status_handles_squash_merged_branch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    wt = tmp_path / "wt"
    init_repo(repo)
    run_git("checkout", "-b", "feat", cwd=repo)
    (repo / "feat.txt").write_text("feat\n")
    run_git("add", "feat.txt", cwd=repo)
    run_git("commit", "-m", "feat", cwd=repo)
    run_git("checkout", "main", cwd=repo)
    run_git("merge", "--squash", "feat", cwd=repo)
    run_git("commit", "-m", "squash feat", cwd=repo)
    run_git("worktree", "add", str(wt), "feat", cwd=repo)

    assert classify_merge_status(wt) == "merged"


def test_classify_merge_status_handles_merge_commit_branch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    wt = tmp_path / "wt"
    init_repo(repo)
    run_git("checkout", "-b", "feat", cwd=repo)
    (repo / "feat.txt").write_text("feat\n")
    run_git("add", "feat.txt", cwd=repo)
    run_git("commit", "-m", "feat", cwd=repo)
    run_git("checkout", "-b", "side", cwd=repo)
    (repo / "side.txt").write_text("side\n")
    run_git("add", "side.txt", cwd=repo)
    run_git("commit", "-m", "side", cwd=repo)
    run_git("checkout", "feat", cwd=repo)
    run_git("merge", "--no-ff", "side", "-m", "merge side", cwd=repo)
    run_git("checkout", "main", cwd=repo)
    run_git("worktree", "add", str(wt), "feat", cwd=repo)

    assert classify_merge_status(wt) == "undetermined"


def test_classify_merge_status_returns_undetermined_on_missing_main(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo, branch="trunk")
    assert classify_merge_status(repo) == "undetermined"


def test_classify_merge_status_returns_not_merged_for_unmerged_branch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    wt = tmp_path / "wt"
    init_repo(repo)
    run_git("checkout", "-b", "feat", cwd=repo)
    (repo / "feat.txt").write_text("feat\n")
    run_git("add", "feat.txt", cwd=repo)
    run_git("commit", "-m", "feat", cwd=repo)
    run_git("checkout", "main", cwd=repo)
    run_git("worktree", "add", str(wt), "feat", cwd=repo)
    assert classify_merge_status(wt) == "not_merged"


@pytest.mark.asyncio
async def test_find_merged_worktrees_repo_without_main_returns_zero_candidates(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    wt = tmp_path / "wt"
    init_repo(repo, branch="trunk")
    run_git("checkout", "-b", "feat", cwd=repo)
    (repo / "feat.txt").write_text("feat\n")
    run_git("add", "feat.txt", cwd=repo)
    run_git("commit", "-m", "feat", cwd=repo)
    run_git("checkout", "trunk", cwd=repo)
    run_git("worktree", "add", str(wt), "feat", cwd=repo)
    assert await find_merged_worktrees(repo) == []


class FakeCoordinator:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    async def remove_worktree(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeAudit:
    def __init__(self) -> None:
        self.partial_calls: list[tuple[object, ...]] = []

    def log_prune_merged_attempt(self, *args: object) -> None:
        pass

    def log_prune_merged_success(self, *args: object) -> None:
        pass

    def log_prune_merged_failure(self, *args: object) -> None:
        pass

    def log_prune_merged_partial(self, *args: object) -> None:
        self.partial_calls.append(args)


def allow_revalidation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mahavishnu.core.worktree_prune_merged._git_head_sha", lambda path: "abc123"
    )
    monkeypatch.setattr(
        "mahavishnu.core.worktree_prune_merged.classify_merge_status",
        lambda path: "merged",
    )
    monkeypatch.setattr(
        "mahavishnu.core.worktree_prune_merged._git_dirty_count",
        lambda path: "clean",
    )


@pytest.mark.asyncio
async def test_worktree_pruner_remove_calls_coordinator_with_force_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_revalidation(monkeypatch)
    coordinator = FakeCoordinator([{"success": True}])
    results = await WorktreePruner(coordinator, FakeAudit()).remove([candidate(tmp_path / "wt")])  # type: ignore[arg-type]
    assert results[0].success is True
    assert coordinator.calls[0]["force"] is False


@pytest.mark.asyncio
async def test_worktree_pruner_remove_force_false_then_escalate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_revalidation(monkeypatch)
    coordinator = FakeCoordinator(
        [
            {"success": False, "force_required": True, "error": "force-required"},
            {"success": True, "backup_path": "/tmp/backup"},
        ]
    )
    result = (
        await WorktreePruner(coordinator, FakeAudit()).remove(  # type: ignore[arg-type]
            [candidate(tmp_path / "wt")], force_reason="reviewed"
        )
    )[0]
    assert [call["force"] for call in coordinator.calls] == [False, True]
    assert coordinator.calls[1]["force_reason"] == "reviewed"
    assert result.escalated is True


@pytest.mark.asyncio
async def test_worktree_pruner_remove_raises_on_unmerged_candidate(tmp_path: Path) -> None:
    coordinator = FakeCoordinator([])
    with pytest.raises(ValueError, match="merge_status"):
        await WorktreePruner(coordinator, FakeAudit()).remove(  # type: ignore[arg-type]
            [candidate(tmp_path / "wt", merge_status="not_merged")]
        )
    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_worktree_pruner_remove_writes_partial_event_when_some_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_revalidation(monkeypatch)
    coordinator = FakeCoordinator([{"success": True}, {"success": False, "error": "failed"}])
    audit = FakeAudit()
    results = await WorktreePruner(coordinator, audit).remove(  # type: ignore[arg-type]
        [candidate(tmp_path / "one"), candidate(tmp_path / "two")]
    )
    assert [result.success for result in results] == [True, False]
    assert len(audit.partial_calls) == 1
