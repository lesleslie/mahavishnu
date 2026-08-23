"""Tests for the v4 §12 pre_migration_discover() module."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mahavishnu.auth import Principal
from mahavishnu.core.worktree_providers.pre_migrate import (
    handle_to_jsonl_dict,
    infer_repo,
    parse_porcelain,
    pre_migration_discover,
    synthesize_handle,
)
from mahavishnu.core.worktree_providers.types import LocalWorktreeRef, WorktreeHandle


# ----- parse_porcelain -------------------------------------------------------


def test_parse_porcelain_empty() -> None:
    assert parse_porcelain("") == []


def test_parse_porcelain_single_worktree() -> None:
    output = (
        "worktree /Users/les/worktrees/agent-abc\n"
        "HEAD abc123\n"
        "branch refs/heads/feature/auth\n"
    )
    entries = parse_porcelain(output)
    assert len(entries) == 1
    assert entries[0]["worktree"] == "/Users/les/worktrees/agent-abc"
    assert entries[0]["HEAD"] == "abc123"
    assert entries[0]["branch"] == "refs/heads/feature/auth"


def test_parse_porcelain_multiple_worktrees() -> None:
    output = (
        "worktree /Users/les/worktrees/agent-1\n"
        "HEAD aaaa\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /Users/les/worktrees/agent-2\n"
        "HEAD bbbb\n"
        "detached\n"
    )
    entries = parse_porcelain(output)
    assert len(entries) == 2
    assert entries[0]["worktree"] == "/Users/les/worktrees/agent-1"
    assert entries[1]["worktree"] == "/Users/les/worktrees/agent-2"
    assert "branch" not in entries[1]  # detached
    assert entries[1]["HEAD"] == "bbbb"


def test_parse_porcelain_strips_trailing_newline() -> None:
    output = (
        "worktree /tmp/wt\n"
        "HEAD deadbeef\n"
        "branch refs/heads/main\n"
        "\n"  # trailing blank line
    )
    entries = parse_porcelain(output)
    assert len(entries) == 1


# ----- infer_repo ----------------------------------------------------------


def test_infer_repo_returns_leaf_basename() -> None:
    assert infer_repo("/Users/les/worktrees/agent-abc123") == "agent-abc123"
    assert infer_repo("/Users/les/worktrees/mahavishnu/feature-auth") == "feature-auth"


def test_infer_repo_handles_trailing_slash() -> None:
    assert infer_repo("/Users/les/worktrees/agent-abc/") == "agent-abc"


def test_infer_repo_handles_relative_path() -> None:
    # Falls back to Path().name
    assert infer_repo("relative/agent-xyz") == "agent-xyz"


# ----- synthesize_handle ---------------------------------------------------


def test_synthesize_handle_branch() -> None:
    entry = {
        "worktree": "/Users/les/worktrees/mahavishnu/feature-auth",
        "HEAD": "abc123",
        "branch": "refs/heads/feature/auth",
    }
    p = Principal.from_uid(1000)
    h = synthesize_handle("/Users/les/Projects/mahavishnu", entry, p)
    assert h.principal == p
    assert h.branch == "feature/auth"
    assert h.base_ref == "abc123"
    assert h.repo == "mahavishnu"
    assert h.provenance == "pre-v2-migration"
    assert h.sha256 == ""  # lazy
    assert h.bytes_size == 0  # lazy
    assert isinstance(h.storage_ref, LocalWorktreeRef)
    assert h.storage_ref.path == Path("/Users/les/worktrees/mahavishnu/feature-auth")


def test_synthesize_handle_detached() -> None:
    entry = {
        "worktree": "/Users/les/worktrees/agent-abc",
        "HEAD": "abcdef",
        # no 'branch' key — detached
    }
    h = synthesize_handle("/Users/les/Projects/mahavishnu", entry, Principal.from_uid(7))
    assert h.branch == "detached-HEAD"


def test_synthesize_handle_anonymous_principal() -> None:
    entry = {"worktree": "/tmp/wt", "HEAD": "x", "branch": "refs/heads/main"}
    h = synthesize_handle("/tmp", entry, Principal.anonymous())
    assert h.principal.is_anonymous


# ----- pre_migration_discover integration -----------------------------------


def test_pre_migration_discover_against_real_repo(tmp_path) -> None:
    """Spin up a real git repo + worktree, run discovery, validate."""
    main = tmp_path / "main"
    main.mkdir()
    wt1 = tmp_path / "wt1"
    wt2 = tmp_path / "wt2"

    # Init repo + first commit
    subprocess.run(["git", "init", "--initial-branch=main", str(main)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(main), "config", "user.email", "test@test"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(main), "config", "user.name", "Test"], check=True, capture_output=True)
    (main / "a.txt").write_text("hello\n")
    subprocess.run(["git", "-C", str(main), "add", "a.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(main), "commit", "-m", "init"], check=True, capture_output=True)

    # Add two worktrees
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-b", "feature/a", str(wt1)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-b", "feature/b", str(wt2)],
        check=True, capture_output=True,
    )

    handles = pre_migration_discover(str(main), principal=Principal.from_uid(99))

    # 3 worktrees: main + wt1 + wt2
    assert len(handles) == 3

    paths = {h.storage_ref.path for h in handles}
    assert main in paths
    assert wt1 in paths
    assert wt2 in paths

    branches = {h.branch for h in handles}
    assert "main" in branches
    assert "feature/a" in branches
    assert "feature/b" in branches

    # provenance consistent
    assert all(h.provenance == "pre-v2-migration" for h in handles)


def test_pre_migration_discover_default_principal(tmp_path) -> None:
    """No principal passed → defaults to Principal.current()."""
    main = tmp_path / "main"
    main.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", str(main)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(main), "config", "user.email", "t@t"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(main), "config", "user.name", "T"], check=True, capture_output=True)
    (main / "a.txt").write_text("hi\n")
    subprocess.run(["git", "-C", str(main), "add", "a.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(main), "commit", "-m", "init"], check=True, capture_output=True)

    handles = pre_migration_discover(str(main))  # no principal arg
    assert handles[0].principal.uid is not None  # Principal.current() worked


# ----- handle_to_jsonl_dict ----------------------------------------------


def test_handle_to_jsonl_dict_roundtrip() -> None:
    p = Principal.from_uid(1000)
    h = synthesize_handle(
        "/Users/les/Projects/mahavishnu",
        {
            "worktree": "/Users/les/worktrees/mahavishnu/feature-auth",
            "HEAD": "abc123",
            "branch": "refs/heads/feature/auth",
        },
        p,
    )
    d = handle_to_jsonl_dict(h)
    assert d["handle_id"] == h.handle_id
    assert d["repo"] == "mahavishnu"
    assert d["branch"] == "feature/auth"
    assert d["principal"]["uid"] == 1000
    assert isinstance(d["created_at"], str)
    assert d["storage_ref"]["path"] == "/Users/les/worktrees/mahavishnu/feature-auth"
    assert d["provenance"] == "pre-v2-migration"

    # Path roundtrip via JSON
    import json

    s = json.dumps(d)
    rt = json.loads(s)
    assert rt["repo"] == "mahavishnu"
    assert rt["storage_ref"]["path"] == "/Users/les/worktrees/mahavishnu/feature-auth"
    assert rt["provenance"] == "pre-v2-migration"
    assert rt["principal"]["uid"] == 1000
    assert rt["principal"]["name"] == "uid:1000"
    # (Path() doesn't exist on disk — it's a synthesized porcelain entry,
    # not a real worktree. The roundtrip only verifies the string.)
