"""Tests for cluster_claim / release_cluster_claim (REQ-CLONE-009).

Implements: REQ-CLONE-009
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mahavishnu.mcp.tools.clone_claims import (
    ConcurrentDAGError,
    cluster_state_claim,
    release_cluster_claim,
)


@pytest.fixture
def mock_backend() -> AsyncMock:
    """Returns an AsyncMock that mimics MCPStateBackend.put/delete."""
    backend = AsyncMock()
    backend.dag_key = lambda x: f"workflow/v1/{x}"
    backend.cluster_key = lambda x: f"cluster/v1/{x}"
    backend.in_flight_key = lambda x: f"cluster/v1/{x}/in_flight"
    # _circuit_is_open must be a sync bool — production calls `if mcp_backend._circuit_is_open():`.
    # An AsyncMock attribute returns a coroutine, which would be truthy and raise.
    backend._circuit_is_open = lambda: False
    return backend


@pytest.mark.req(["REQ-CLONE-009"])  # CR-M1: REQ traceability
class TestClusterStateClaim:
    """REQ-CLONE-009: cluster_id is locked across concurrent invocations."""

    async def test_first_claim_succeeds(self, mock_backend: AsyncMock) -> None:
        # First call: no existing sentinel → claim acquired, sentinel written.
        async def fake_get(key: str):
            return None  # no existing claim

        mock_backend.get = fake_get
        mock_backend.put = AsyncMock()
        result = await cluster_state_claim(mock_backend, "cluster-1", "job-aaa")
        # TD-m6: cluster_state_claim returns None (was `-> bool`); success = no exception
        assert result is None
        mock_backend.put.assert_called_once()
        call = mock_backend.put.call_args
        assert call.args[0] == "cluster/v1/cluster-1/in_flight"
        assert call.args[1]["refactor_job_id"] == "job-aaa"

    async def test_existing_same_job_id_succeeds(self, mock_backend: AsyncMock) -> None:
        # Idempotent: same caller re-claiming their own job → returns None.
        async def fake_get(key: str):
            return {"refactor_job_id": "job-aaa"}

        mock_backend.get = fake_get
        mock_backend.put = AsyncMock()
        result = await cluster_state_claim(mock_backend, "cluster-1", "job-aaa")
        assert result is None
        # No new put — claim already held by same job
        mock_backend.put.assert_not_called()

    async def test_existing_different_job_id_raises(self, mock_backend: AsyncMock) -> None:
        async def fake_get(key: str):
            return {"refactor_job_id": "job-bbb"}

        mock_backend.get = fake_get
        mock_backend.put = AsyncMock()
        with pytest.raises(ConcurrentDAGError) as exc_info:
            await cluster_state_claim(mock_backend, "cluster-1", "job-aaa")
        assert exc_info.value.existing_job_id == "job-bbb"

    async def test_concurrent_claim_serialized_within_process(self) -> None:
        # In-process lock: two concurrent claims for the same cluster_id —
        # one acquires (returns None), the other sees the sentinel and raises.
        import asyncio

        backend = AsyncMock()
        backend.cluster_key = lambda x: f"cluster/v1/{x}"
        backend.in_flight_key = lambda x: f"cluster/v1/{x}/in_flight"
        # See fixture note: _circuit_is_open must be sync bool, not a coroutine.
        backend._circuit_is_open = lambda: False

        claim_count = 0

        async def fake_get(key: str):
            nonlocal claim_count
            # After first put, subsequent gets see the sentinel
            return {"refactor_job_id": "job-aaa"} if claim_count > 0 else None

        async def fake_put(key: str, value: dict, ttl=None):
            nonlocal claim_count
            claim_count += 1

        backend.get = fake_get
        backend.put = fake_put

        results = await asyncio.gather(
            cluster_state_claim(backend, "cluster-1", "job-aaa"),
            cluster_state_claim(backend, "cluster-1", "job-bbb"),
            return_exceptions=True,
        )
        # Exactly one succeeded (returns None), one raised
        successes = [r for r in results if r is None]
        errors = [r for r in results if isinstance(r, ConcurrentDAGError)]
        assert len(successes) == 1
        assert len(errors) == 1


class TestReleaseClusterClaim:
    async def test_release_deletes_in_flight_key(self, mock_backend: AsyncMock) -> None:
        mock_backend.delete = AsyncMock()
        await release_cluster_claim(mock_backend, "cluster-1")
        mock_backend.delete.assert_called_once_with("cluster/v1/cluster-1/in_flight")

    async def test_release_does_not_raise_on_missing_key(self, mock_backend: AsyncMock) -> None:
        async def fake_delete(key: str):
            return None  # no-op even if key didn't exist

        mock_backend.delete = fake_delete
        await release_cluster_claim(mock_backend, "cluster-1")  # must not raise


class TestConcurrentDAGError:
    def test_existing_job_id_attribute(self) -> None:
        exc = ConcurrentDAGError(existing_job_id="0193f5e2-7c8d-7abc-9def-1234567890ab")
        assert exc.existing_job_id == "0193f5e2-7c8d-7abc-9def-1234567890ab"
        assert "0193f5e2-7c8d-7abc-9def-1234567890ab" in str(exc)
