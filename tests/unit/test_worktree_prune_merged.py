from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from mahavishnu.core.worktree_prune_merged import (
    WorktreePruneCandidate,
    WorktreePruner,
    classify_merge_status,
    find_merged_worktrees,
    owning_repo_path,
)

if TYPE_CHECKING:
    from pathlib import Path


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


@pytest.mark.req(["REQ-PRUNE-001"])
def test_classify_merge_status_handles_multi_commit_squash_merged_branch(
    tmp_path: Path,
) -> None:
    """A squash of MORE THAN ONE commit is merged too.

    This is the case the single-commit test above cannot reach.
    ``git cherry`` compares patch-ids, and a squash of N commits
    produces one commit whose diff is the union of N diffs -- a
    combination that matches none of the individual patch-ids. Every
    commit of the branch therefore shows ``+`` and the branch reads
    as ``not_merged`` even though its content is in ``main``.

    The single-commit case works by accident: with one commit the
    squash commit's diff IS that commit's diff, so the patch-ids
    match. That accident is what made the multi-commit case look
    like it was covered.
    """
    repo = tmp_path / "repo"
    wt = tmp_path / "wt"
    init_repo(repo)
    run_git("checkout", "-b", "feat", cwd=repo)
    for name in ("one", "two", "three"):
        (repo / f"{name}.txt").write_text(f"{name}\n")
        run_git("add", f"{name}.txt", cwd=repo)
        run_git("commit", "-m", name, cwd=repo)
    run_git("checkout", "main", cwd=repo)
    run_git("merge", "--squash", "feat", cwd=repo)
    run_git("commit", "-m", "squash feat", cwd=repo)
    run_git("worktree", "add", str(wt), "feat", cwd=repo)

    # The premise of the test: the patch-ids really do not match.
    cherry = run_git("cherry", "main", cwd=wt)
    assert cherry.stdout.strip().startswith("+")

    assert classify_merge_status(wt) == "merged"


@pytest.mark.req(["REQ-PRUNE-001"])
def test_classify_merge_status_reports_not_merged_when_the_branch_adds_content(
    tmp_path: Path,
) -> None:
    """Squash-merged, then one more commit: the branch is NOT merged.

    The content-equivalence signal must not fire on a branch that
    still carries something ``main`` does not have.
    """
    repo = tmp_path / "repo"
    wt = tmp_path / "wt"
    init_repo(repo)
    run_git("checkout", "-b", "feat", cwd=repo)
    for name in ("one", "two"):
        (repo / f"{name}.txt").write_text(f"{name}\n")
        run_git("add", f"{name}.txt", cwd=repo)
        run_git("commit", "-m", name, cwd=repo)
    run_git("checkout", "main", cwd=repo)
    run_git("merge", "--squash", "feat", cwd=repo)
    run_git("commit", "-m", "squash feat", cwd=repo)
    run_git("worktree", "add", str(wt), "feat", cwd=repo)
    # A commit that is NOT in main, made on the branch tip so the
    # worktree's HEAD is the one that carries it.
    (wt / "extra.txt").write_text("extra\n")
    run_git("add", "extra.txt", cwd=wt)
    run_git("commit", "-m", "extra", cwd=wt)

    assert classify_merge_status(wt) == "not_merged"


@pytest.mark.req(["REQ-PRUNE-001"])
def test_classify_merge_status_reports_not_merged_for_a_clean_unmerged_branch(
    tmp_path: Path,
) -> None:
    """A branch that merges cleanly but CHANGES main is not merged.

    ``git merge-tree --write-tree`` exits 0 for this branch too -- the
    merge is clean. Only the resulting tree differs from ``main``'s.
    Both conditions are required, so the exit code alone must not be
    read as "merged".
    """
    repo = tmp_path / "repo"
    wt = tmp_path / "wt"
    init_repo(repo)
    run_git("checkout", "-b", "feat", cwd=repo)
    (repo / "feat.txt").write_text("feat\n")
    run_git("add", "feat.txt", cwd=repo)
    run_git("commit", "-m", "feat", cwd=repo)
    run_git("checkout", "main", cwd=repo)
    run_git("worktree", "add", str(wt), "feat", cwd=repo)

    merge_tree = run_git("merge-tree", "--write-tree", "main", "HEAD", cwd=wt)
    assert merge_tree.returncode == 0, "the merge is clean -- only the tree differs"

    assert classify_merge_status(wt) == "not_merged"


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


def test_classify_merge_status_returns_undetermined_on_missing_main(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo, branch="trunk")
    assert classify_merge_status(repo) == "undetermined"


def test_classify_merge_status_returns_not_merged_for_unmerged_branch(
    tmp_path: Path,
) -> None:
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


class ListingCoordinator:
    """A coordinator that reports a worktree list of its own choosing."""

    def __init__(self, paths: list[str], *, fail: bool = False) -> None:
        self.paths = paths
        self.fail = fail

    async def list_worktrees(self, **kwargs: object) -> dict[str, object]:
        if self.fail:
            raise RuntimeError("coordinator unavailable")
        return {
            "success": True,
            "worktrees": [{"path": path} for path in self.paths],
        }


@pytest.mark.asyncio
@pytest.mark.req(["REQ-PRUNE-002"])
async def test_find_merged_worktrees_finds_worktrees_the_coordinator_omits(
    tmp_path: Path,
) -> None:
    """Git is the ground truth for which worktrees exist.

    The coordinator's registry can lag behind the filesystem: it
    reported Session-Buddy as unhealthy during a prune sweep and fell
    back to a local listing that covered the agent-scoped worktrees
    but not the repo-scoped ones. Consulting only the coordinator made
    the sweep blind to a whole class of worktrees -- it found nothing
    to prune while merged worktrees sat on disk.
    """
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

    # The coordinator knows about some OTHER path, not this worktree.
    coordinator = ListingCoordinator([str(tmp_path / "somewhere-else")])
    found = await find_merged_worktrees(repo, repo_nickname="mh", coordinator=coordinator)

    assert [str(c.worktree_path) for c in found] == [str(wt)]
    assert found[0].merge_status == "merged"


@pytest.mark.asyncio
@pytest.mark.req(["REQ-PRUNE-002"])
async def test_find_merged_worktrees_survives_a_failing_coordinator(
    tmp_path: Path,
) -> None:
    """A coordinator outage must not silence the sweep.

    The enumeration used to return an EMPTY list when the coordinator
    raised, which made the direct git fallback unreachable: a
    transient registry outage silently pruned nothing at all.
    """
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

    coordinator = ListingCoordinator([], fail=True)
    found = await find_merged_worktrees(repo, repo_nickname="mh", coordinator=coordinator)

    assert [str(c.worktree_path) for c in found] == [str(wt)]


@pytest.mark.req(["REQ-PRUNE-003"])
@pytest.mark.asyncio
async def test_find_merged_worktrees_skips_a_locked_worktree(tmp_path: Path) -> None:
    """A locked worktree is never offered for removal.

    ``git worktree lock`` is the fleet's existing "do not touch this"
    marker. Before this guard the only thing standing between a live
    session's worktree and automatic removal was the dirty check --
    which a CLEAN session passes straight through. A lock is not a
    recency signal (locked worktrees here are up to a fortnight old);
    it is a statement that removal was refused, and the sweep honours
    it unconditionally.
    """
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

    # Unlocked: the sweep sees it.
    unlocked = await find_merged_worktrees(repo)
    assert [str(c.worktree_path) for c in unlocked] == [str(wt)]

    run_git("worktree", "lock", str(wt), cwd=repo)
    assert await find_merged_worktrees(repo) == []


@pytest.mark.asyncio
async def test_find_merged_worktrees_only_path_classifies_one_worktree(
    tmp_path: Path,
) -> None:
    """``only_path`` narrows the scan BEFORE the classification.

    Classifying a worktree costs a handful of git subprocesses --
    ``git status --short`` alone measured 0.26 s -- so filtering after
    the fact still pays for every worktree in the repository. The
    merge cycle's cleanup uses this, and it is the difference between
    a fleet-wide sweep (83.9 s) and a scoped one (10.9 s, of which
    about 10 s is the CLI's own startup).
    """
    repo = tmp_path / "repo"
    wanted = tmp_path / "wanted"
    other = tmp_path / "other"
    init_repo(repo)
    for name in ("one", "two"):
        run_git("checkout", "-b", f"feat-{name}", cwd=repo)
        (repo / f"{name}.txt").write_text(f"{name}\n")
        run_git("add", f"{name}.txt", cwd=repo)
        run_git("commit", "-m", name, cwd=repo)
    run_git("checkout", "main", cwd=repo)
    for name in ("one", "two"):
        run_git("merge", "--squash", f"feat-{name}", cwd=repo)
        run_git("commit", "-m", f"squash {name}", cwd=repo)
    run_git("worktree", "add", str(wanted), "feat-one", cwd=repo)
    run_git("worktree", "add", str(other), "feat-two", cwd=repo)

    everything = await find_merged_worktrees(repo)
    assert {str(c.worktree_path) for c in everything} == {str(wanted), str(other)}

    scoped = await find_merged_worktrees(repo, only_path=wanted)
    assert [str(c.worktree_path) for c in scoped] == [str(wanted)]


def test_owning_repo_path_finds_the_repository_of_a_worktree(tmp_path: Path) -> None:
    """The owning repository is asked of git, not inferred from the path.

    A worktree lives OUTSIDE its repository's directory -- the fleet's
    are under ``~/.local/state/mahavishnu/worktrees/`` -- so the path's
    parents say nothing about who owns it.
    """
    repo = tmp_path / "repo"
    wt = tmp_path / "elsewhere" / "wt"
    init_repo(repo)
    (tmp_path / "elsewhere").mkdir()
    run_git("checkout", "-b", "feat", cwd=repo)
    (repo / "feat.txt").write_text("feat\n")
    run_git("add", "feat.txt", cwd=repo)
    run_git("commit", "-m", "feat", cwd=repo)
    # The branch must be free before it can be checked out elsewhere.
    run_git("checkout", "main", cwd=repo)
    run_git("worktree", "add", str(wt), "feat", cwd=repo)

    assert owning_repo_path(wt) == repo.resolve()


def test_owning_repo_path_is_none_for_a_plain_directory(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert owning_repo_path(plain) is None


def test_owning_repo_path_handles_a_bare_repository(tmp_path: Path) -> None:
    """A bare repository's common dir IS the repository.

    ``git rev-parse --git-common-dir`` reports the bare repo's own
    directory rather than a ``.git`` inside it, so the parent rule
    would point one level too high.
    """
    bare = tmp_path / "bare.git"
    bare.mkdir()
    run_git("init", "--bare", str(bare), cwd=tmp_path)

    assert owning_repo_path(bare) == bare.resolve()


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
    results = await WorktreePruner(coordinator, FakeAudit()).remove(
        [candidate(tmp_path / "wt")]
    )
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
        await WorktreePruner(coordinator, FakeAudit()).remove(
            [candidate(tmp_path / "wt")], force_reason="reviewed"
        )
    )[0]
    assert [call["force"] for call in coordinator.calls] == [False, True]
    assert coordinator.calls[1]["force_reason"] == "reviewed"
    assert result.escalated is True


@pytest.mark.asyncio
async def test_worktree_pruner_remove_raises_on_unmerged_candidate(
    tmp_path: Path,
) -> None:
    coordinator = FakeCoordinator([])
    with pytest.raises(ValueError, match="merge_status"):
        await WorktreePruner(coordinator, FakeAudit()).remove(
            [candidate(tmp_path / "wt", merge_status="not_merged")]
        )
    assert coordinator.calls == []


@pytest.mark.asyncio
async def test_worktree_pruner_remove_writes_partial_event_when_some_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_revalidation(monkeypatch)
    coordinator = FakeCoordinator(
        [{"success": True}, {"success": False, "error": "failed"}]
    )
    audit = FakeAudit()
    results = await WorktreePruner(coordinator, audit).remove(
        [candidate(tmp_path / "one"), candidate(tmp_path / "two")]
    )
    assert [result.success for result in results] == [True, False]
    assert len(audit.partial_calls) == 1


class CliRepo:
    def __init__(self, path: Path, nickname: str) -> None:
        self.path = path
        self.nickname = nickname
        self.name = nickname


class CliRepoManager:
    def __init__(self, repos: list[CliRepo]) -> None:
        self.repos = repos

    def get_repo(self, key: str) -> CliRepo | None:
        return next(
            (repo for repo in self.repos if key in (repo.name, repo.nickname)), None
        )

    def list_repos(self) -> list[CliRepo]:
        return self.repos


class CliApp:
    def __init__(self, repos: list[CliRepo]) -> None:
        self.repo_manager = CliRepoManager(repos)
        self.worktree_coordinator = object()

    async def initialize_worktree_coordinator(self) -> None:
        pass


def cli_candidate(path: Path, nickname: str = "fake") -> WorktreePruneCandidate:
    return WorktreePruneCandidate(
        repo_path=path.parent,
        repo_nickname=nickname,
        worktree_path=path,
        branch="feat/x",
        head_sha="abc123",
        merge_status="merged",
        dirty_status="clean",
        behind=5,
    )


def patch_cli_app(monkeypatch: pytest.MonkeyPatch, app: CliApp) -> None:
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.MahavishnuApp.load",
        classmethod(lambda cls: app),
    )
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.SessionWorktreeRegistry",
        lambda: type("Registry", (), {"list_active": lambda self, state=None: []})(),
    )


def test_cli_prune_merged_lists_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from typer.testing import CliRunner

    from mahavishnu.worktree_cli import worktree_app

    repo = CliRepo(tmp_path / "repo", "fake")
    repo.path.mkdir()
    patch_cli_app(monkeypatch, CliApp([repo]))
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.find_merged_worktrees",
        lambda *a, **kw: [cli_candidate(tmp_path / "wt")],
    )
    result = CliRunner().invoke(
        worktree_app, ["prune-merged", "--repo", "fake", "--dry-run"]
    )
    assert result.exit_code == 0
    assert "feat/x" in result.stdout


def test_cli_prune_merged_path_restricts_the_sweep_to_one_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``--path`` narrows the sweep to a single worktree.

    The merge cycle's stage 6 uses it. Without it, stage 6 swept every
    configured repository and removed, unattended, on every merge --
    which is not what stage 6 is for, and which the worktree policy
    decision reserves for explicit invocation.
    """
    from typer.testing import CliRunner

    from mahavishnu.worktree_cli import worktree_app

    repo = CliRepo(tmp_path / "repo", "fake")
    repo.path.mkdir()
    patch_cli_app(monkeypatch, CliApp([repo]))
    wanted = tmp_path / "wt"
    other = tmp_path / "other"
    # The sweep only scans the repository that OWNS the worktree, and
    # the owner is asked of git -- these are mock paths, so the answer
    # is stubbed.
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.owning_repo_path",
        lambda _path: repo.path.resolve(),
    )
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.find_merged_worktrees",
        lambda *a, **kw: [
            c
            for c in (cli_candidate(wanted), cli_candidate(other))
            if kw.get("only_path") is None
            or c.worktree_path.resolve() == kw["only_path"].resolve()
        ],
    )

    result = CliRunner().invoke(
        worktree_app,
        ["prune-merged", "--repo", "fake", "--path", str(wanted), "--dry-run"],
    )
    assert result.exit_code == 0
    assert str(wanted) in result.stdout
    assert str(other) not in result.stdout


def test_cli_prune_merged_scans_only_the_repository_that_owns_the_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``--path`` scans ONE repository -- the one that owns the worktree.

    The scoping has to happen BEFORE the scan, not after it. A
    repository that cannot hold the worktree is skipped outright, so
    its worktrees are never classified -- which is where the fleet-wide
    cost used to be paid.
    """
    from typer.testing import CliRunner

    from mahavishnu.worktree_cli import worktree_app

    owner = CliRepo(tmp_path / "owner", "owner")
    other = CliRepo(tmp_path / "other", "other")
    for repo in (owner, other):
        repo.path.mkdir()
    patch_cli_app(monkeypatch, CliApp([owner, other]))
    wanted = tmp_path / "wt"
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.owning_repo_path",
        lambda _path: owner.path.resolve(),
    )
    scanned: list[str] = []
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.find_merged_worktrees",
        lambda *a, **kw: scanned.append(kw["repo_nickname"]) or [],
    )

    result = CliRunner().invoke(
        worktree_app, ["prune-merged", "--path", str(wanted), "--dry-run"]
    )
    assert result.exit_code == 0
    assert scanned == ["owner"]


def test_cli_prune_merged_fails_when_no_repository_owns_the_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A ``--path`` that no repository owns is an ERROR, not an empty result.

    The merge cycle's stage 6 reads a zero return code as
    ``cleanup_performed: true``. A silent no-op would have the merge
    report a cleanup that never happened while the worktree stayed on
    disk.
    """
    from typer.testing import CliRunner

    from mahavishnu.worktree_cli import worktree_app

    repo = CliRepo(tmp_path / "repo", "fake")
    repo.path.mkdir()
    patch_cli_app(monkeypatch, CliApp([repo]))
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.owning_repo_path",
        lambda _path: None,
    )
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.find_merged_worktrees",
        lambda *a, **kw: [],
    )

    result = CliRunner().invoke(
        worktree_app,
        ["prune-merged", "--path", str(tmp_path / "wt"), "--dry-run"],
    )
    assert result.exit_code == 1
    assert "owns" in result.stderr


def test_cli_prune_merged_fails_when_the_owner_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The owner is known, but no configured repository is it.

    The worktree survives either way, so the run must not report
    success: the same false ``cleanup_performed: true`` the previous
    case guards against.
    """
    from typer.testing import CliRunner

    from mahavishnu.worktree_cli import worktree_app

    repo = CliRepo(tmp_path / "repo", "fake")
    repo.path.mkdir()
    patch_cli_app(monkeypatch, CliApp([repo]))
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.owning_repo_path",
        lambda _path: (tmp_path / "unconfigured").resolve(),
    )
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.find_merged_worktrees",
        lambda *a, **kw: [],
    )

    result = CliRunner().invoke(
        worktree_app,
        ["prune-merged", "--path", str(tmp_path / "wt"), "--dry-run"],
    )
    assert result.exit_code == 1
    assert "owns" in result.stderr


def test_cli_prune_merged_threads_resolved_nickname(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from typer.testing import CliRunner

    from mahavishnu.worktree_cli import worktree_app

    repo = CliRepo(tmp_path / "repo", "alias")
    repo.path.mkdir()
    patch_cli_app(monkeypatch, CliApp([repo]))
    calls: list[str] = []
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.find_merged_worktrees",
        lambda *a, **kw: calls.append(kw["repo_nickname"]) or [],
    )
    result = CliRunner().invoke(
        worktree_app, ["prune-merged", "--repo", "alias", "--dry-run"]
    )
    assert result.exit_code == 0
    assert calls == ["alias"]


def test_cli_prune_merged_without_repo_iterates_all_nicknames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from typer.testing import CliRunner

    from mahavishnu.worktree_cli import worktree_app

    repos = [CliRepo(tmp_path / "one", "one"), CliRepo(tmp_path / "two", "two")]
    for repo in repos:
        repo.path.mkdir()
    patch_cli_app(monkeypatch, CliApp(repos))
    calls: list[str] = []
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.find_merged_worktrees",
        lambda *a, **kw: calls.append(kw["repo_nickname"]) or [],
    )
    result = CliRunner().invoke(worktree_app, ["prune-merged", "--dry-run"])
    assert result.exit_code == 0
    assert calls == ["one", "two"]


def test_cli_prune_merged_json_is_single_document(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import json

    from typer.testing import CliRunner

    from mahavishnu.worktree_cli import worktree_app

    repo = CliRepo(tmp_path / "repo", "fake")
    repo.path.mkdir()
    patch_cli_app(monkeypatch, CliApp([repo]))
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.find_merged_worktrees",
        lambda *a, **kw: [cli_candidate(tmp_path / "wt")],
    )
    payload = json.loads(
        CliRunner().invoke(worktree_app, ["prune-merged", "--dry-run", "--json"]).stdout
    )
    assert payload["candidates"][0]["dirty_status"] == "clean"


def test_cli_prune_merged_partial_failure_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from typer.testing import CliRunner

    from mahavishnu.core.worktree_prune_merged import WorktreePruneResult
    from mahavishnu.worktree_cli import worktree_app

    repo = CliRepo(tmp_path / "repo", "fake")
    repo.path.mkdir()
    patch_cli_app(monkeypatch, CliApp([repo]))
    candidates = [cli_candidate(tmp_path / "one"), cli_candidate(tmp_path / "two")]
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.find_merged_worktrees", lambda *a, **kw: candidates
    )
    monkeypatch.setattr(
        "mahavishnu.worktree_cli.WorktreePruner.remove",
        lambda self, cs, **kw: __import__("asyncio").sleep(
            0,
            result=[
                WorktreePruneResult(cs[0], True, None, None),
                WorktreePruneResult(cs[1], False, None, "provider failed"),
            ],
        ),
    )
    result = CliRunner().invoke(worktree_app, ["prune-merged"])
    assert result.exit_code == 1
    assert "feat/x" in result.stdout
    assert "provider failed" in result.stdout
