"""Tests for the two merge-workflow gaps wired up on this branch.

Covers:

- ``mahavishnu.core.merge_review_dispatcher`` — the real stage-2 review
  dispatcher (replacing the stub that returned a synthetic ``pass``).
- ``mahavishnu.core.merge_to_main`` — the dev-log entry on the merge
  **success** path (previously only the consolidation-gate hold-back
  path wrote one).

These live in their own module so they do not collide with edits to
``tests/unit/core/test_merge_to_main.py``.
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from mahavishnu.core import dev_log, merge_to_main
from mahavishnu.core.merge_review_dispatcher import (
    _extract_reply_text,
    _parse_pool_result,
    _pool_failure_message,
    build_review_prompt,
    collect_diff_context,
    dispatch_review,
)
from mahavishnu.core.merge_to_main import (
    EXIT_OK,
    _default_dispatcher,
    _write_merge_log,
    parse_verdict,
    run_pipeline,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_repo_with_branch(tmp_path: Path) -> Path:
    """Create a git repo with one commit on ``main`` and a second branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(tmp_path),
    }
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=env)
    (repo / "a.txt").write_text("one\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True, env=env)
    subprocess.run(
        ["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True, env=env
    )
    (repo / "a.txt").write_text("one\ntwo\n")
    (repo / "b.txt").write_text("new\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "work"], cwd=repo, check=True, env=env)
    return repo


class TestDiffContext:
    """The review prompt must carry the diff, not just a pointer."""

    def test_collect_diff_context_reports_changed_files(self, tmp_path: Path) -> None:
        repo = _make_repo_with_branch(tmp_path)
        context = collect_diff_context("feature", "main", repo)
        assert "b.txt" in context
        assert "Changed files:" in context

    def test_collect_diff_context_is_empty_for_unknown_branch(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo_with_branch(tmp_path)
        assert collect_diff_context("no-such-branch", "main", repo) == ""

    def test_build_review_prompt_carries_diff_and_worktree(
        self, tmp_path: Path
    ) -> None:
        repo = _make_repo_with_branch(tmp_path)
        prompt = build_review_prompt("feature", "main", repo)
        assert "feature" in prompt
        assert str(repo) in prompt
        assert "b.txt" in prompt
        assert "<verdict>" in prompt

    def test_build_review_prompt_falls_back_when_diff_unavailable(
        self, tmp_path: Path
    ) -> None:
        prompt = build_review_prompt("feature", "main", tmp_path)
        assert "could not be summarized" in prompt
        assert "<verdict>" in prompt


class TestReplyExtraction:
    """The pool response arrives in several shapes; all must be readable."""

    def test_extract_reply_text_from_plain_string(self) -> None:
        assert _extract_reply_text("hello") == "hello"

    def test_extract_reply_text_from_call_tool_result(self) -> None:
        payload = SimpleNamespace(content=[SimpleNamespace(text="reviewer reply")])
        assert _extract_reply_text(payload) == "reviewer reply"

    def test_extract_reply_text_from_result_mapping(self) -> None:
        assert _extract_reply_text({"result": "reviewer reply"}) == "reviewer reply"

    def test_parse_pool_result_extracts_worker_output(self) -> None:
        assert _parse_pool_result('{"result": "the verdict"}') == "the verdict"

    def test_parse_pool_result_passes_through_non_json(self) -> None:
        assert _parse_pool_result("plain text") == "plain text"

    def test_pool_task_shape_failure_names_the_cause(self) -> None:
        """A shepherd-backed pool's refusal must say what is wrong."""
        payload = json.dumps(
            {
                "pool_id": "mahavishnu_1",
                "status": "failed",
                "output": None,
                "error": "Task must specify 'task_ref' or 'command'",
            }
        )
        message = _pool_failure_message(_parse_pool_result(payload))
        assert message is not None
        assert "task_ref" in message
        assert "does not accept a 'prompt' task" in message

    def test_pool_success_payload_has_no_failure_message(self) -> None:
        payload = json.dumps({"status": "completed", "output": "the verdict"})
        assert _pool_failure_message(_parse_pool_result(payload)) is None


class TestDispatcher:
    """The stub dispatcher must be gone, and failures must block."""

    def test_default_dispatcher_delegates_to_pool(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        def fake_dispatch(agent: str, prompt: str) -> str:
            seen["agent"] = agent
            seen["prompt"] = prompt
            return "<verdict>decision: pass note: ok</verdict>"

        monkeypatch.setattr(
            "mahavishnu.core.merge_review_dispatcher.dispatch_review", fake_dispatch
        )
        reply = _default_dispatcher("python-pro", "review this")
        assert seen["agent"] == "python-pro"
        assert seen["prompt"] == "review this"
        assert parse_verdict(reply)["decision"] == "pass"

    def test_dispatch_failure_returns_unparseable_reply(self) -> None:
        """An unreachable pool must fail loud, not return a synthetic pass.

        Driven through the synchronous wrapper: the MCP client's anyio
        task-group teardown does not survive pytest-asyncio's event loop
        under xdist, and this test is about the fail-loud contract, not
        about the transport.
        """
        reply = dispatch_review(
            "python-pro",
            "review this",
            mcp_url="http://127.0.0.1:1/mcp",
            timeout=5.0,
        )
        assert "<verdict>" not in reply
        assert parse_verdict(reply)["decision"] == "block"


class TestSuccessDevLog:
    """A successful merge must leave an audit entry."""

    @pytest.fixture
    def dev_log_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        target = tmp_path / "dev-log"
        target.mkdir()
        monkeypatch.setattr(
            dev_log, "get_dev_log_path", lambda *parts: target / parts[0]
        )
        monkeypatch.setattr(dev_log, "DEV_LOG_DIR", target)
        return target

    def test_write_merge_log_records_merged_outcome(self, dev_log_dir: Path) -> None:
        _write_merge_log(
            dev_log_dir,
            "feat/x",
            "main",
            push_result="ok",
            cleanup_performed=True,
            outcome="merged",
        )
        entries = list(dev_log_dir.rglob("*.md"))
        assert len(entries) == 1
        text = entries[0].read_text()
        assert "outcome: merged" in text
        assert "result: ok" in text
        assert "cleanup_performed: true" in text

    def test_run_pipeline_writes_the_success_entry(
        self, dev_log_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(merge_to_main, "run_squash_merge", lambda *a, **k: (0, ""))
        monkeypatch.setattr(merge_to_main, "run_push", lambda *a, **k: (0, ""))
        monkeypatch.setattr(merge_to_main, "_run_cleanup", lambda *a, **k: (0, ""))
        monkeypatch.setattr(merge_to_main, "_origin_remote_exists", lambda: True)

        rc = run_pipeline(
            dev_log_dir,
            branch="feat/x",
            review_mode="none",
            no_crackerjack=True,
            no_consolidation_gate=True,
        )
        assert rc == EXIT_OK
        entries = list(dev_log_dir.rglob("*.md"))
        assert len(entries) == 1
        text = entries[0].read_text()
        assert "outcome: merged" in text
        assert "result: ok" in text

    def test_run_pipeline_records_push_divergence(
        self, dev_log_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(merge_to_main, "run_squash_merge", lambda *a, **k: (0, ""))
        monkeypatch.setattr(merge_to_main, "run_push", lambda *a, **k: (1, "boom"))
        monkeypatch.setattr(merge_to_main, "_run_cleanup", lambda *a, **k: (0, ""))

        rc = run_pipeline(
            dev_log_dir,
            branch="feat/x",
            review_mode="none",
            no_crackerjack=True,
            no_consolidation_gate=True,
        )
        assert rc == merge_to_main.EXIT_PUSH_DIVERGENCE
        entries = list(dev_log_dir.rglob("*.md"))
        assert len(entries) == 1
        text = entries[0].read_text()
        assert "outcome: push_failed" in text
        assert "result: diverged" in text
