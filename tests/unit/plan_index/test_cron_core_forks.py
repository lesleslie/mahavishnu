"""The rebuild cycle's fork budget, and the repo URL it resolves.

Two properties, both of which were broken before 2026-11-16:

1. **The cycle forked once per plan document.** 60 plan documents meant 60
   ``git rev-parse`` forks per cycle, twice at startup, in a process that
   forks anyway. On macOS a fork taken while grpcio's threads are live
   produces a child that dies with SIGILL -- see
   ``docs/decisions/2026-11-16-no-grpc-in-forking-processes.md``. The cycle
   now makes two forks, whatever the document count.

2. **Every record failed to index.** The record's ``repo`` came from the
   plan document's frontmatter, and no document declares one. The empty URL
   was rejected by ``normalize_repo_url``, so all 60 records failed at the
   "normalize" step: ``success=0 errors=60 entities=0``. The index now falls
   back to the repository's own remote.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from mahavishnu.plan_index.cron_core import (
    _git_blob_shas,
    _git_remote_url,
    discover_records,
)
from mahavishnu.plan_index.url import RepoUrlRejectedError, normalize_repo_url

if TYPE_CHECKING:
    from pathlib import Path

_PLAN = """---
status: active
role: canonical
kind: plan
date: 2026-11-16
last_reviewed: 2026-11-16
title: "A plan"
---

# A plan
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo_with_plans(tmp_path: Path) -> Path:
    """A git repo with one committed plan document and an origin remote."""
    repo = tmp_path / "repo"
    (repo / "docs" / "plans").mkdir(parents=True)
    (repo / "docs" / "plans" / "2026-11-16-a-plan.md").write_text(_PLAN)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "remote", "add", "origin", "https://github.com/example/repo.git")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "add a plan")
    return repo


class TestForkBudget:
    def test_blob_shas_make_one_fork_for_the_whole_tree(
        self, repo_with_plans: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One ``git`` call, not one per document."""
        calls: list[list[str]] = []
        real_run = subprocess.run

        def _counting_run(args, *a, **kw):  # type: ignore[no-untyped-def]
            calls.append(list(args))
            return real_run(args, *a, **kw)

        monkeypatch.setattr(subprocess, "run", _counting_run)

        shas = _git_blob_shas(repo_with_plans)

        assert len(calls) == 1, f"expected one fork, got {calls}"
        assert calls[0][:3] == ["git", "ls-tree", "-r"]
        assert shas, "the committed plan should have a blob sha"
        assert all(len(sha) == 40 for sha in shas.values())

    def test_discovery_makes_two_forks_not_one_per_document(
        self, repo_with_plans: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fork count does not grow with the document count."""
        calls: list[list[str]] = []
        real_run = subprocess.run

        def _counting_run(args, *a, **kw):  # type: ignore[no-untyped-def]
            calls.append(list(args))
            return real_run(args, *a, **kw)

        monkeypatch.setattr(subprocess, "run", _counting_run)

        discover_records(repo_with_plans)

        assert len(calls) == 2, f"expected two forks (ls-tree + remote), got {calls}"


class TestRepoResolution:
    def test_the_record_falls_back_to_the_repos_own_remote(
        self, repo_with_plans: Path
    ) -> None:
        """A plan document need not declare its repo.

        The index indexes THIS repository's plans, so the repository's own
        remote is the correct value -- and it is the only value that
        ``normalize_repo_url`` accepts.
        """
        records = discover_records(repo_with_plans)

        assert records, "the plan should have been discovered"
        for record in records:
            # Would have raised before the fallback existed.
            assert normalize_repo_url(record.repo, raise_on_reject=True)

    def test_the_record_repo_is_accepted_by_the_rebuilder(
        self, repo_with_plans: Path
    ) -> None:
        """The rebuilder's normalize step must not reject the record.

        This is the exact step that failed for all 60 documents before.
        """
        records = discover_records(repo_with_plans)
        rejected = 0
        for record in records:
            try:
                normalize_repo_url(record.repo, raise_on_reject=True)
            except RepoUrlRejectedError:
                rejected += 1
        assert rejected == 0

    def test_the_remote_url_is_the_repos_origin(self, repo_with_plans: Path) -> None:
        """The fallback reads ``origin``, not some arbitrary remote."""
        assert _git_remote_url(repo_with_plans) == "https://github.com/example/repo.git"

    def test_a_missing_remote_is_not_fatal(self, tmp_path: Path) -> None:
        """No origin → empty string, not an exception."""
        repo = tmp_path / "bare"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        assert _git_remote_url(repo) == ""
