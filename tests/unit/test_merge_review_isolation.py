"""The stage-2 review must actually run in an isolated checkout.

Three reviewers run concurrently against one repository, so each needs
its own checkout. The pool can decline to provide one — it skips the
worktree silently when it cannot resolve the repository, and a pool
type that cannot honour a working directory refuses the task outright.
A review that then runs in the shared main checkout is the situation
where a reviewer ran ``git stash`` in another session's work on
2026-11-06.

So isolation is verified, not assumed.
"""

from __future__ import annotations

import json
from typing import Any, Self

import pytest

from mahavishnu.core.merge_review_dispatcher import (
    _worktree_context,
    dispatch_review_async,
)
from mahavishnu.core.merge_to_main import parse_verdict

STREAM_FRAGMENT = (
    '...,"result":"<verdict>\\ndecision: pass\\nnote: smoke test\\n</verdict>",'
    '"ttft_ms":17210,"type":"result"}'
)

WORKTREE_OPTION = {
    "isolation": "worktree",
    "base_branch": "feat/under-review",
    "on_completion": "discard",
}


class _Text:
    def __init__(self, text: str) -> None:
        self.text = text


class _CallResult:
    """A stand-in for the MCP ``CallToolResult``."""

    def __init__(self, text: str) -> None:
        self.content = [_Text(text)]


class _FakeClient:
    """A ``CommonMCPClient`` stand-in that returns one envelope."""

    def __init__(self, envelope: str) -> None:
        self._envelope = envelope
        #: Every tool call made, so a test can assert what the
        #: dispatcher asked the pool for.
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def call_tool(self, name: str, args: dict[str, Any]) -> _CallResult:
        self.calls.append((name, args))
        return _CallResult(self._envelope)


def _envelope(output: str, worktree: dict[str, Any] | None = None) -> str:
    payload: dict[str, Any] = {
        "pool_id": "mahavishnu_1",
        "worker_id": "worker-1",
        "status": "completed",
        "output": output,
    }
    if worktree is not None:
        payload["worktree"] = worktree
    return json.dumps(payload)


def _install(monkeypatch: pytest.MonkeyPatch, envelope: str) -> _FakeClient:
    """Install the fake client and return it, for call assertions."""
    client = _FakeClient(envelope)
    monkeypatch.setattr(
        "mcp_common.clients.common_mcp_client.CommonMCPClient",
        lambda **kwargs: client,
    )
    return client


class TestTheWorktreeContext:
    def test_it_reads_the_worktree_the_pool_attached(self) -> None:
        envelope = _envelope(
            STREAM_FRAGMENT,
            {"path": "/tmp/wt-1", "branch": "feature/x", "base_branch": "feat/y"},
        )

        context = _worktree_context(envelope)

        assert context is not None
        assert context["path"] == "/tmp/wt-1"
        assert context["base_branch"] == "feat/y"

    def test_it_is_none_when_no_worktree_was_attached(self) -> None:
        assert _worktree_context(_envelope(STREAM_FRAGMENT)) is None

    def test_it_is_none_for_a_non_envelope(self) -> None:
        assert _worktree_context("not json at all") is None


class TestIsolationIsVerified:
    @pytest.mark.asyncio
    async def test_a_dispatch_without_a_worktree_blocks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pool ran the reviewer without isolating it.

        That is the silent fallback: the pool could not create the
        worktree and said nothing, so the reviewer would be sharing
        the main checkout with every other session.
        """
        _install(monkeypatch, _envelope(STREAM_FRAGMENT))

        reply = await dispatch_review_async(
            "python-pro", "review this", worktree=WORKTREE_OPTION
        )

        verdict = parse_verdict(reply)
        assert verdict["decision"] == "block"
        assert "isolation was requested" in verdict["note"]

    @pytest.mark.asyncio
    async def test_an_empty_worktree_context_blocks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The check is fail-closed on a context it cannot read.

        An empty context says the server attached a ``worktree`` key
        but populated it with nothing. That is not evidence that a
        worktree was created, so the review is abandoned rather than
        run in the shared checkout on a maybe.
        """
        _install(monkeypatch, _envelope(STREAM_FRAGMENT, {}))

        reply = await dispatch_review_async(
            "python-pro", "review this", worktree=WORKTREE_OPTION
        )

        verdict = parse_verdict(reply)
        assert verdict["decision"] == "block"
        assert "isolation was requested" in verdict["note"]

    @pytest.mark.asyncio
    async def test_a_context_without_a_path_still_counts_as_isolated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The signal is the key's presence, not the path.

        The pool sets the ``worktree`` key only when it created a
        worktree, and that is true of every server version. A server
        that predates the ``path`` field still isolates, so requiring
        the path would block a review that was safely isolated.

        The context is server-attested: it is a sibling key of the
        envelope, set by the pool tool after ``create_worktree``
        succeeds. The reviewer's reply travels in the separate
        ``output`` field and cannot forge a sibling key.
        """
        _install(monkeypatch, _envelope(STREAM_FRAGMENT, {"diff": "", "merge": None}))

        reply = await dispatch_review_async(
            "python-pro", "review this", worktree=WORKTREE_OPTION
        )

        assert parse_verdict(reply)["decision"] == "pass"

    @pytest.mark.asyncio
    async def test_an_isolated_dispatch_yields_its_verdict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(
            monkeypatch,
            _envelope(
                STREAM_FRAGMENT,
                {
                    "path": "/tmp/wt-1",
                    "branch": "feature/x",
                    "base_branch": "feat/under-review",
                },
            ),
        )

        reply = await dispatch_review_async(
            "python-pro", "review this", worktree=WORKTREE_OPTION
        )

        verdict = parse_verdict(reply)
        assert verdict["decision"] == "pass"
        assert verdict["note"] == "smoke test"

    @pytest.mark.asyncio
    async def test_a_dispatch_without_isolation_is_not_checked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No isolation requested means no isolation to verify."""
        _install(monkeypatch, _envelope(STREAM_FRAGMENT))

        reply = await dispatch_review_async("python-pro", "review this")

        assert parse_verdict(reply)["decision"] == "pass"


class TestAFailedDispatchReportsItsOwnReason:
    """A dispatch that never happened is not an isolation failure.

    The pool raises when it cannot make the dispatch at all — no pool
    can honour the directory the task named, or the repository to
    isolate could not be resolved. The error text comes back instead
    of a result, and reporting that as "the review ran without an
    isolated checkout" would replace the real reason with a
    misleading one: the operator would go looking for a pool that
    quietly ignored the directory, when the pool never ran at all.
    """

    @pytest.mark.asyncio
    async def test_the_dispatch_error_is_reported_as_itself(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install(
            monkeypatch,
            "No pool available that can honour task['cwd']. Spawn one "
            "--type mahavishnu --worker-type terminal-claude --name "
            "merge-review -- and retry.",
        )

        reply = await dispatch_review_async(
            "python-pro", "review this", worktree=WORKTREE_OPTION
        )

        verdict = parse_verdict(reply)
        assert verdict["decision"] == "block"
        assert "No pool available" in verdict["note"]
        assert "isolation was requested" not in verdict["note"]

    @pytest.mark.asyncio
    async def test_a_failed_dispatch_does_not_claim_the_reviewer_ran(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The wording must not say the reviewer ran somewhere unsafe.

        The check that follows a failed dispatch used to report "the
        review would have shared the main checkout" — describing a
        harm that, in this case, never happened: the worker was never
        dispatched.
        """
        _install(monkeypatch, "worktree isolation was requested but the repository")

        reply = await dispatch_review_async(
            "python-pro", "review this", worktree=WORKTREE_OPTION
        )

        verdict = parse_verdict(reply)
        assert verdict["decision"] == "block"
        assert "would have shared" not in verdict["note"]


class TestTheWorktreeReachesThePool:
    """The isolation request has to arrive at the pool.

    The whole mechanism is a request field: the pool forks a worktree
    and runs the worker in it only when it is told to. A dispatcher
    that dropped the field would leave the reviewer in the shared
    checkout — and the post-hoc check would catch it only after the
    harm was done, so the field's arrival is worth its own test.
    """

    @pytest.mark.asyncio
    async def test_the_worktree_options_reach_the_pool(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _install(
            monkeypatch,
            _envelope(STREAM_FRAGMENT, {"path": "/tmp/wt-1"}),
        )

        await dispatch_review_async(
            "python-pro",
            "review this",
            worktree={"isolation": "worktree", "on_completion": "discard"},
        )

        assert client.calls, "the pool was never called"
        name, args = client.calls[0]
        assert name == "mahavishnu_pool_route_execute"
        assert args["worktree"] == {
            "isolation": "worktree",
            "on_completion": "discard",
        }
