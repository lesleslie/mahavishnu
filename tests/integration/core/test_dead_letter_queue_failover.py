"""Integration tests for DLQ failover behavior.

Exercises the two outcomes the runtime fail-closed wiring cares about:

  1. **OpenSearch down + flag off (legacy silent fallback)**: the task
     ends up in the in-memory queue and ``mahavishnu_dlq_fallback_total``
     increments with ``outcome="in_memory"``.
  2. **OpenSearch down + flag on (fail-closed)**: ``enqueue`` raises
     ``ExternalServiceError`` and the metric increments with
     ``outcome="rejected"``. No memory-only phantom.

This is marked ``@pytest.mark.integration`` so a fast-feedback run can
exclude it with ``-m "not integration"``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mahavishnu.core.dead_letter_queue import DeadLetterQueue
from mahavishnu.core.dlq_metrics import get_dlq_metrics
from mahavishnu.core.errors import ExternalServiceError

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_legacy_silent_fallback_increments_in_memory_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When OpenSearch is unavailable and the operator has not enabled
    fail-closed, the task survives in memory and the metric reflects
    that with ``outcome="in_memory"``."""
    import mahavishnu.core.dead_letter_queue as dlq_module

    # Force the module-level "library not installed" path.
    monkeypatch.setattr(dlq_module, "OPENSEARCH_AVAILABLE", False, raising=False)

    dlq = DeadLetterQueue(max_size=100)  # fail_on_opensearch_unavailable=False default
    metrics = get_dlq_metrics()

    persisted_before = metrics.dlq_fallback_total.labels(
        outcome="persisted"
    )._value.get()  # type: ignore[attr-defined]
    in_memory_before = metrics.dlq_fallback_total.labels(
        outcome="in_memory"
    )._value.get()  # type: ignore[attr-defined]

    failed = await dlq.enqueue(
        task_id="wf_legacy_inmem",
        task={"type": "code_sweep"},
        repos=["/path/to/repo"],
        error="OpenSearch unreachable",
    )

    assert failed.task_id == "wf_legacy_inmem"
    # Task IS in the in-memory queue (legacy behavior).
    assert any(t.task_id == "wf_legacy_inmem" for t in dlq._queue)

    # The metric recorded the fallback.
    assert (
        metrics.dlq_fallback_total.labels(
            outcome="in_memory"
        )._value.get()  # type: ignore[attr-defined]
        == in_memory_before + 1
    )
    # And the persisted counter did NOT increment.
    assert (
        metrics.dlq_fallback_total.labels(
            outcome="persisted"
        )._value.get()  # type: ignore[attr-defined]
        == persisted_before
    )


async def test_fail_closed_runtime_write_failure_increments_rejected_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When fail-closed is on and a configured client's write fails at
    runtime, ``enqueue`` re-raises and the metric records
    ``outcome="rejected"``. No memory-only phantom."""
    import mahavishnu.core.dead_letter_queue as dlq_module

    monkeypatch.setattr(dlq_module, "OPENSEARCH_AVAILABLE", True, raising=False)

    mock_client = AsyncMock()
    mock_client.index.side_effect = RuntimeError("connection reset by peer")

    dlq = DeadLetterQueue(
        max_size=100,
        opensearch_client=mock_client,
        fail_on_opensearch_unavailable=True,
    )
    metrics = get_dlq_metrics()

    rejected_before = metrics.dlq_fallback_total.labels(
        outcome="rejected"
    )._value.get()  # type: ignore[attr-defined]
    persisted_before = metrics.dlq_fallback_total.labels(
        outcome="persisted"
    )._value.get()  # type: ignore[attr-defined]

    with pytest.raises(ExternalServiceError):
        await dlq.enqueue(
            task_id="wf_fail_closed_rejected",
            task={"type": "code_sweep"},
            repos=["/path/to/repo"],
            error="OpenSearch write failed",
        )

    # The task was NOT appended to the in-memory queue — this is the
    # whole point of fail-closed: no silent phantom.
    assert all(t.task_id != "wf_fail_closed_rejected" for t in dlq._queue)

    # The metric recorded the rejection.
    assert (
        metrics.dlq_fallback_total.labels(
            outcome="rejected"
        )._value.get()  # type: ignore[attr-defined]
        == rejected_before + 1
    )
    # And nothing was counted as persisted or in_memory.
    assert (
        metrics.dlq_fallback_total.labels(
            outcome="persisted"
        )._value.get()  # type: ignore[attr-defined]
        == persisted_before
    )
    mock_client.index.assert_called_once()
