"""Round-trip integration test for the workflow outcome pipeline.

Writer (Task 1 ``record_workflow_outcome``) and consumer (Task 3
``workflow_get_outcome``) are exercised against a shared in-memory Dhara
substrate. Both sides monkeypatch the same substrate-compat binding on the
``dhara`` module — ``dhara.put`` (writer) and ``dhara.get`` (consumer) —
so the writer's persisted payload is the consumer's read-back payload.

This locks the end-to-end contract:

  1. ``record_workflow_outcome`` validates against the substrate schema and
     persists a typed ``WorkflowOutcome``.
  2. ``workflow_get_outcome`` reads the same payload back via
     ``dhara.get(key)`` and re-validates via ``from_dict``.
  3. Struct equality holds across the boundary — same ``workflow_id``,
     ``status``, ``started_at``, ``finished_at``, ``metadata``.

Failure modes caught by this gate:

  - Producer key format drift (e.g. trailing slash dropped) — consumer would
    read ``None`` and return ``None``.
  - Producer payload drift (e.g. omitting ``metadata``) — consumer would
    either crash on validation or return a partially populated struct.
  - Status mapping drift at the boundary — Task 3 maps
    ``{"completed": "succeeded", "partial": "cancelled"}``; a mismatch
    here would propagate to the consumer and break downstream tooling.
"""

from __future__ import annotations

from datetime import UTC, datetime

from dhara.schema import WorkflowOutcome
import pytest

from mahavishnu.core.workflow.outcome_writer import record_workflow_outcome
from mahavishnu.mcp.tools.workflow_tools import workflow_get_outcome

pytestmark = pytest.mark.unit


@pytest.fixture
def shared_dhara(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Patch both producer and consumer to share an in-memory dict.

    Both modules' ``dhara.put`` / ``dhara.get`` resolve at call time via
    :func:`dhara_calltime` / direct ``getattr(dhara, ...)`` on the live
    ``dhara`` module. Patch the live module (NOT the producer/consumer
    modules — neither imports ``dhara`` as a name anymore) so the writer's
    persisted payload lands in the same dict the consumer reads. Keys are
    formatted ``f"workflow-results/{workflow_id}/"`` to match the producer
    key format exactly.
    """
    import dhara

    store: dict[str, object] = {}

    def put(key: str, value: object) -> None:
        store[key] = value

    async def get(key: str) -> object | None:
        return store.get(key)

    monkeypatch.setattr(dhara, "put", put, raising=False)
    monkeypatch.setattr(dhara, "get", get, raising=False)
    return store


@pytest.mark.asyncio
async def test_round_trip_succeeded_outcome_round_trips(shared_dhara: dict[str, object]) -> None:
    """Write a 'succeeded' outcome, read it back, assert struct equality."""
    workflow_id = "wf-round-trip-success"
    started_at = datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)
    finished_at = datetime(2026, 8, 10, 12, 5, 0, tzinfo=UTC)
    metadata = {"ttl_seconds": 300, "retries": 0}

    written = record_workflow_outcome(
        workflow_id=workflow_id,
        status="succeeded",
        started_at=started_at,
        finished_at=finished_at,
        metadata=metadata,
    )

    assert isinstance(written, WorkflowOutcome)
    assert written.workflow_id == workflow_id
    assert written.status == "succeeded"
    assert written.started_at == started_at
    assert written.finished_at == finished_at
    assert written.metadata == metadata

    # Substrate-side key matches producer contract
    assert f"workflow-results/{workflow_id}/" in shared_dhara

    # Consumer reads back via from_dict validation
    read_back = await workflow_get_outcome(workflow_id)

    assert isinstance(read_back, WorkflowOutcome)
    assert read_back.workflow_id == written.workflow_id
    assert read_back.status == written.status
    assert read_back.started_at == written.started_at
    assert read_back.finished_at == written.finished_at
    assert read_back.metadata == written.metadata


@pytest.mark.asyncio
async def test_round_trip_failed_outcome_round_trips(shared_dhara: dict[str, object]) -> None:
    """Failed status survives the validate-on-write + validate-on-read boundary."""
    workflow_id = "wf-round-trip-failed"
    started_at = datetime(2026, 8, 10, 13, 0, 0, tzinfo=UTC)
    finished_at = datetime(2026, 8, 10, 13, 0, 42, tzinfo=UTC)

    written = record_workflow_outcome(
        workflow_id=workflow_id,
        status="failed",
        started_at=started_at,
        finished_at=finished_at,
    )

    read_back = await workflow_get_outcome(workflow_id)

    assert isinstance(read_back, WorkflowOutcome)
    assert read_back == written
    assert read_back.status == "failed"


@pytest.mark.asyncio
async def test_round_trip_cancelled_outcome_round_trips(shared_dhara: dict[str, object]) -> None:
    """Cancelled status survives the validate-on-write + validate-on-read boundary."""
    workflow_id = "wf-round-trip-cancelled"
    started_at = datetime(2026, 8, 10, 14, 0, 0, tzinfo=UTC)
    finished_at = datetime(2026, 8, 10, 14, 1, 0, tzinfo=UTC)

    written = record_workflow_outcome(
        workflow_id=workflow_id,
        status="cancelled",
        started_at=started_at,
        finished_at=finished_at,
    )

    read_back = await workflow_get_outcome(workflow_id)

    assert isinstance(read_back, WorkflowOutcome)
    assert read_back == written
    assert read_back.status == "cancelled"


@pytest.mark.asyncio
async def test_round_trip_default_metadata_round_trips(shared_dhara: dict[str, object]) -> None:
    """Default empty metadata dict survives producer and consumer."""
    workflow_id = "wf-round-trip-no-meta"
    started_at = datetime(2026, 8, 10, 15, 0, 0, tzinfo=UTC)
    finished_at = datetime(2026, 8, 10, 15, 0, 5, tzinfo=UTC)

    written = record_workflow_outcome(
        workflow_id=workflow_id,
        status="succeeded",
        started_at=started_at,
        finished_at=finished_at,
    )

    assert written.metadata == {}

    read_back = await workflow_get_outcome(workflow_id)

    assert isinstance(read_back, WorkflowOutcome)
    assert read_back.metadata == {}
    assert read_back == written


@pytest.mark.asyncio
async def test_round_trip_consumer_returns_none_when_writer_missing(
    shared_dhara: dict[str, object],
) -> None:
    """Consumer returns None when no record exists — round-trip pre-condition.

    Confirms the consumer side of the round-trip is wired correctly even
    when the producer never wrote. Independent of the producer's
    validate-on-write guarantee.
    """
    result = await workflow_get_outcome("wf-never-written")
    assert result is None
