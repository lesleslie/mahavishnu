"""Unit tests for fail-closed DLQ behavior.

Follows up ``docs/followups/2026-06-29-dlq-silent-fallback.md``. When
``dlq.fail_on_opensearch_unavailable`` is True, ``DeadLetterQueue.enqueue``
must raise ``ExternalServiceError`` rather than silently dropping the
failed task into the per-process in-memory queue when OpenSearch is
unavailable. Default behavior (flag False) preserves the legacy silent
fallback unchanged.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

import mahavishnu.core.dead_letter_queue as dlq_module
from mahavishnu.core.dead_letter_queue import DeadLetterQueue
from mahavishnu.core.errors import ExternalServiceError

pytestmark = pytest.mark.asyncio


def _stub_opensearch_availability(monkeypatch: pytest.MonkeyPatch, available: bool) -> None:
    """Force the module-level ``OPENSEARCH_AVAILABLE`` constant."""
    monkeypatch.setattr(dlq_module, "OPENSEARCH_AVAILABLE", available, raising=False)


async def test_dlq_silent_when_flag_false_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default (flag off): silent in-memory fallback when OpenSearch unavailable."""
    _stub_opensearch_availability(monkeypatch, False)

    dlq = DeadLetterQueue(max_size=100)  # default fail_on_opensearch_unavailable=False

    failed = await dlq.enqueue(
        task_id="wf_default",
        task={"type": "code_sweep"},
        repos=["/path/to/repo"],
        error="OpenSearch unreachable",
    )

    assert failed.task_id == "wf_default"
    # Silent fallback: in-memory queue holds the task (legacy behavior).
    assert any(t.task_id == "wf_default" for t in dlq._queue)


async def test_dlq_raises_when_flag_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-closed opt-in: raise ExternalServiceError when OpenSearch unavailable."""
    _stub_opensearch_availability(monkeypatch, False)

    dlq = DeadLetterQueue(
        max_size=100,
        fail_on_opensearch_unavailable=True,
    )

    with pytest.raises(ExternalServiceError) as excinfo:
        await dlq.enqueue(
            task_id="wf_fail_closed",
            task={"type": "code_sweep"},
            repos=["/path/to/repo"],
            error="OpenSearch unreachable",
        )

    # Error refers to OpenSearch and surfaces the opt-in hint.
    assert "OpenSearch" in str(excinfo.value)
    assert "fail_on_opensearch_unavailable" in str(excinfo.value)

    # The task must NOT have been silently dropped into the in-memory queue.
    assert all(t.task_id != "wf_fail_closed" for t in dlq._queue)
    assert dlq._stats["enqueued_total"] == 0


async def test_dlq_works_normally_when_opensearch_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed flag on, but OpenSearch is available: enqueue proceeds normally."""
    _stub_opensearch_availability(monkeypatch, True)
    mock_client = AsyncMock()
    mock_obs = Mock()

    dlq = DeadLetterQueue(
        max_size=100,
        opensearch_client=mock_client,
        observability_manager=mock_obs,
        fail_on_opensearch_unavailable=True,
    )

    failed = await dlq.enqueue(
        task_id="wf_ok",
        task={"type": "code_sweep"},
        repos=["/path/to/repo"],
        error="connection timeout",
    )

    assert failed.task_id == "wf_ok"
    # OpenSearch index was called once with the canonical DLQ index name.
    mock_client.index.assert_called_once()
    call_kwargs = mock_client.index.call_args.kwargs
    assert call_kwargs["index"] == "mahavishnu_dlq"
    assert call_kwargs["id"] == "wf_ok"


async def test_dlq_fail_closed_no_opensearch_client_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-closed flag on, library importable but no client injected: still raises.

    Guards the case where ``OPENSEARCH_AVAILABLE`` is True (the library
    installed) but the orchestrator didn't get a client wired in. The
    fallback deque is not a safe default in fail-closed mode.
    """
    _stub_opensearch_availability(monkeypatch, True)

    dlq = DeadLetterQueue(
        max_size=100,
        opensearch_client=None,
        fail_on_opensearch_unavailable=True,
    )

    with pytest.raises(ExternalServiceError):
        await dlq.enqueue(
            task_id="wf_no_client",
            task={"type": "code_sweep"},
            repos=["/path/to/repo"],
            error="OpenSearch client not wired",
        )


# ---------------------------------------------------------------------------
# Phase 2: runtime write-failure handling
# See docs/plans/2026-07-16-dlq-fail-closed-wiring.md, Phase 2.
# ---------------------------------------------------------------------------


async def test_runtime_write_failure_raises_when_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag on + configured client whose ``index`` raises → enqueue re-raises
    ``ExternalServiceError`` and does NOT leave a memory-only phantom.

    This closes the data-loss window the followup
    ``2026-06-29-dlq-silent-fallback.md`` couldn't close: previously
    ``_persist_task`` swallowed write errors so a configured-but-failing
    client silently kept tasks only in memory.
    """
    _stub_opensearch_availability(monkeypatch, True)
    mock_client = AsyncMock()
    mock_client.index.side_effect = RuntimeError("connection reset by peer")

    dlq = DeadLetterQueue(
        max_size=100,
        opensearch_client=mock_client,
        fail_on_opensearch_unavailable=True,
    )

    with pytest.raises(ExternalServiceError) as excinfo:
        await dlq.enqueue(
            task_id="wf_write_fail",
            task={"type": "code_sweep"},
            repos=["/path/to/repo"],
            error="OpenSearch write failed",
        )

    # The ExternalServiceError wraps the underlying driver error.
    assert "OpenSearch" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, RuntimeError)

    # The task must NOT have been appended to the in-memory queue — that
    # would be the exact "memory-only phantom" data-loss the strict
    # persist was added to prevent.
    assert all(t.task_id != "wf_write_fail" for t in dlq._queue)
    assert dlq._stats["enqueued_total"] == 0
    # And the write was attempted exactly once.
    mock_client.index.assert_called_once()


async def test_flag_off_swallows_runtime_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag off + configured client whose ``index`` raises → legacy behavior:
    task is appended to the in-memory queue, the error is logged and swallowed.

    This guards the "byte-for-byte unchanged" back-compat contract:
    ``fail_on_opensearch_unavailable=False`` must keep the original
    silent-fallback behavior, including for runtime write failures.
    """
    _stub_opensearch_availability(monkeypatch, True)
    mock_client = AsyncMock()
    mock_client.index.side_effect = RuntimeError("connection reset by peer")

    dlq = DeadLetterQueue(
        max_size=100,
        opensearch_client=mock_client,
        fail_on_opensearch_unavailable=False,  # default; explicit for clarity
    )

    # Should NOT raise — legacy silent-fallback path is preserved.
    failed = await dlq.enqueue(
        task_id="wf_legacy_silent",
        task={"type": "code_sweep"},
        repos=["/path/to/repo"],
        error="OpenSearch write failed",
    )

    assert failed.task_id == "wf_legacy_silent"
    # Task IS in the in-memory queue (legacy behavior).
    assert any(t.task_id == "wf_legacy_silent" for t in dlq._queue)
    assert dlq._stats["enqueued_total"] == 1
