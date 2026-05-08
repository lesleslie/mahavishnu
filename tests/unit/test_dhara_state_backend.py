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
