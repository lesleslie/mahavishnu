"""Unit tests for DharaStateBackend — durable state persistence layer.

Tests cover: put/get no-ops in degraded mode, circuit-breaker trip/recovery,
schedule_put fire-and-forget, probe behavior, and config-disabled no-op.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.state_backends.dhara import (
    _DHARA_FAILURE_THRESHOLD,
    DharaStateBackend,
    DharaStateConfig,
)


def _make_backend(enabled: bool = True, dhara_put: AsyncMock | None = None) -> DharaStateBackend:
    """Build a DharaStateBackend with a mocked DharaClient.

    DharaClient is imported inside __init__, so patch the source module.
    After construction, replace _client directly with our mock.
    """
    mock_client = MagicMock()
    mock_client.put = dhara_put or AsyncMock()
    mock_client.call_tool = AsyncMock(return_value={"value": "test"})
    mock_client.aclose = AsyncMock()

    config = DharaStateConfig(enabled=enabled)
    # Patch at the source so the local import inside __init__ picks up the mock
    with patch("mahavishnu.core.dhara_adapter.DharaClient", return_value=mock_client):
        backend = DharaStateBackend(base_url="http://localhost:8683/mcp", config=config)

    # Also replace after construction in case the local import resolved earlier
    backend._client = mock_client
    return backend


class TestDharaStateBackendPut:
    def test_key_helpers(self):
        assert DharaStateBackend.workflow_key("wf-1") == "workflow/v1/wf-1"
        assert DharaStateBackend.pool_key("pool-1") == "pool/v1/pool-1"
        assert DharaStateBackend.approval_key("app-1") == "approval/v1/app-1"
        assert DharaStateBackend.routing_key("task", None).startswith("routing/v1/task/")

    @pytest.mark.asyncio
    async def test_put_calls_client_when_available(self):
        mock_put = AsyncMock()
        backend = _make_backend(dhara_put=mock_put)

        await backend.put("workflow/v1/abc", {"status": "running"})

        mock_put.assert_awaited_once_with("workflow/v1/abc", {"status": "running"}, ttl=None)

    @pytest.mark.asyncio
    async def test_put_is_noop_when_disabled(self):
        mock_put = AsyncMock()
        backend = _make_backend(enabled=False, dhara_put=mock_put)

        await backend.put("workflow/v1/abc", {"status": "running"})

        mock_put.assert_not_called()

    @pytest.mark.asyncio
    async def test_put_is_noop_when_circuit_open(self):
        mock_put = AsyncMock(side_effect=RuntimeError("Dhara down"))
        backend = _make_backend(dhara_put=mock_put)

        # Trip the circuit
        for _ in range(_DHARA_FAILURE_THRESHOLD):
            await backend.put("key", {})

        # Reset mock to ensure no more calls
        mock_put.reset_mock()
        await backend.put("key", {})

        mock_put.assert_not_called()

    @pytest.mark.asyncio
    async def test_circuit_resets_after_recovery_timeout(self):
        import time

        mock_put = AsyncMock(side_effect=RuntimeError("down"))
        backend = _make_backend(dhara_put=mock_put)

        for _ in range(_DHARA_FAILURE_THRESHOLD):
            await backend.put("key", {})

        # Manually expire the circuit
        backend._circuit_open_until = time.monotonic() - 1.0
        backend._consecutive_failures = 0

        mock_put.reset_mock()
        mock_put.side_effect = None
        await backend.put("key", {"status": "ok"})

        mock_put.assert_awaited_once_with("key", {"status": "ok"}, ttl=None)


class TestDharaStateBackendGet:
    @pytest.mark.asyncio
    async def test_get_returns_dict_on_success(self):
        backend = _make_backend()
        backend._client.call_tool = AsyncMock(return_value={"key": "k", "value": "v"})

        result = await backend.get("workflow/v1/abc")

        assert result == {"key": "k", "value": "v"}

    @pytest.mark.asyncio
    async def test_get_returns_none_when_disabled(self):
        backend = _make_backend(enabled=False)

        result = await backend.get("workflow/v1/abc")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_none_on_error(self):
        backend = _make_backend()
        backend._client.call_tool = AsyncMock(side_effect=RuntimeError("timeout"))

        result = await backend.get("workflow/v1/abc")

        assert result is None


class TestDharaStateBackendProbe:
    @pytest.mark.asyncio
    async def test_probe_sets_available_true_on_success(self):
        backend = _make_backend()
        backend._available = False
        backend._client.call_tool = AsyncMock(return_value={})

        result = await backend.probe()

        assert result is True
        assert backend.available is True

    @pytest.mark.asyncio
    async def test_probe_sets_available_false_on_failure(self):
        backend = _make_backend()
        backend._client.call_tool = AsyncMock(side_effect=RuntimeError("unreachable"))

        result = await backend.probe()

        assert result is False
        assert backend.available is False


class TestSchedulePut:
    @pytest.mark.asyncio
    async def test_schedule_put_creates_task(self):
        backend = _make_backend()
        mock_put = AsyncMock()
        backend._client.put = mock_put

        backend.schedule_put("workflow/v1/xyz", {"status": "running"})

        # Yield to allow the created task to run
        import asyncio
        await asyncio.sleep(0)
        mock_put.assert_awaited_once()


class TestDharaStateBackendConvenienceMethods:
    @pytest.mark.asyncio
    async def test_persist_pool_uses_canonical_key(self):
        backend = _make_backend()
        backend._client.put = AsyncMock()

        await backend.persist_pool("pool-123", {"status": "running"})

        backend._client.put.assert_awaited_once()
        args = backend._client.put.call_args[0]
        assert args[0] == "pool/v1/pool-123"

    @pytest.mark.asyncio
    async def test_persist_routing_decision_uses_task_class_key(self):
        backend = _make_backend()
        backend._client.put = AsyncMock()

        await backend.persist_routing_decision("workflow", {"pool_id": "pool-1"})

        backend._client.put.assert_awaited_once()
        key = backend._client.put.call_args[0][0]
        assert key.startswith("routing/v1/workflow/")

    @pytest.mark.asyncio
    async def test_recover_helpers_filter_dict_values(self):
        backend = _make_backend()
        backend._client.call_tool = AsyncMock(
            return_value=[
                {"key": "pool/v1/pool-1", "value": {"pool_id": "pool-1"}},
                {"key": "pool/v1/pool-2", "value": "not-a-dict"},
            ]
        )

        pools = await backend.recover_pools()

        assert pools == [{"pool_id": "pool-1"}]

    @pytest.mark.asyncio
    async def test_recover_routing_decisions_filters_dict_values(self):
        backend = _make_backend()
        backend._client.call_tool = AsyncMock(
            return_value=[
                {
                    "key": "routing/v1/workflow/1",
                    "value": {"task_class": "workflow", "pool_id": "pool-1"},
                },
                {"key": "routing/v1/workflow/2", "value": "not-a-dict"},
            ]
        )

        decisions = await backend.recover_routing_decisions()

        assert decisions == [{"task_class": "workflow", "pool_id": "pool-1"}]
