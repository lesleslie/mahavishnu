"""Unit tests for DharaKvClient — string-shape adapter for PlanIndexStore.

PlanIndexStore's _DharaClient Protocol declares string KV (str | None),
but Dhara's MCP wire shape returns dict envelopes (``{"ok":..., "key":...,
"value":...}``). This adapter unwraps the envelope so callers see the
raw string value Dhara actually stored. See state_backends/dhara_kv.py.

Tests cover: get/put round-trip, list_prefix tuple shape, delete no-op,
disabled-mode short-circuit, and the contract that wires Dhara's wire
envelope ``{"ok": True, "key": K, "value": V}`` to ``str | None``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.state_backends.dhara_kv import DharaKvClient, DharaKvConfig


def _make_client(
    enabled: bool = True,
    *,
    call_tool: AsyncMock | None = None,
    put: AsyncMock | None = None,
) -> DharaKvClient:
    """Build a DharaKvClient with a mocked DharaClient."""
    mock_client = MagicMock()
    mock_client.put = put or AsyncMock()
    mock_client.call_tool = call_tool or AsyncMock()
    mock_client.aclose = AsyncMock()

    cfg = DharaKvConfig(enabled=enabled)
    with patch("mahavishnu.core.dhara_adapter.DharaClient", return_value=mock_client):
        client = DharaKvClient(base_url="http://localhost:8683/mcp", config=cfg)
    client._client = mock_client  # belt-and-braces
    return client


class TestDharaKvClientGet:
    @pytest.mark.asyncio
    async def test_get_unwraps_wire_envelope_to_string(self):
        """Dhara MCP returns {'ok':..., 'key':K, 'value':V}; adapter
        surfaces the raw stored string. Critical for cron_core where
        int(await dhara.get(...)) raises if a dict envelope leaks."""
        envelope = {"ok": True, "key": "plan_index/meta/cycles_total", "value": "42"}
        client = _make_client(call_tool=AsyncMock(return_value=envelope))

        result = await client.get("plan_index/meta/cycles_total")

        assert result == "42"

    @pytest.mark.asyncio
    async def test_get_returns_none_when_value_missing(self):
        """When Dhara's wire envelope has value=None, the adapter
        surfaces None — matches PlanIndexStore's Protocol contract."""
        envelope = {"ok": True, "key": "plan_index/meta/cycles_total", "value": None}
        client = _make_client(call_tool=AsyncMock(return_value=envelope))

        result = await client.get("plan_index/meta/cycles_total")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_none_on_error(self):
        client = _make_client(call_tool=AsyncMock(side_effect=RuntimeError("timeout")))

        result = await client.get("plan_index/meta/cycles_total")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_none_when_disabled(self):
        client = _make_client(enabled=False)
        result = await client.get("k")
        assert result is None
        client._client.call_tool.assert_not_called()


class TestDharaKvClientPut:
    @pytest.mark.asyncio
    async def test_put_passes_through_to_dhara_client(self):
        mock_put = AsyncMock()
        client = _make_client(put=mock_put)

        await client.put("plan_index/meta/cycles_total", "42", ttl=86400)

        mock_put.assert_awaited_once_with(
            "plan_index/meta/cycles_total", "42", ttl=86400
        )

    @pytest.mark.asyncio
    async def test_put_returns_none_on_error(self):
        mock_put = AsyncMock(side_effect=RuntimeError("write fail"))
        client = _make_client(put=mock_put)

        # Should swallow — caller never blocks on persistence.
        await client.put("k", "v")  # must not raise

        mock_put.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_put_is_noop_when_disabled(self):
        mock_put = AsyncMock()
        client = _make_client(enabled=False, put=mock_put)
        await client.put("k", "v")
        mock_put.assert_not_called()


class TestDharaKvClientListPrefix:
    @pytest.mark.asyncio
    async def test_list_prefix_flattens_wire_envelope(self):
        """MCP tool wraps list_prefix_async result as
        ``{"ok": True, "count": N, "items": [{"key":..., "value":...}]}``.
        Adapter must flatten to ``[(key, str_value), ...]`` per
        PlanIndexStore's _DharaClient Protocol."""
        wire_response = {
            "ok": True,
            "count": 2,
            "items": [
                {"key": "plan_index/aaa", "value": '{"plan_id": "aaa"}'},
                {"key": "plan_index/bbb", "value": '{"plan_id": "bbb"}'},
            ],
        }
        client = _make_client(call_tool=AsyncMock(return_value=wire_response))

        result = await client.list_prefix("plan_index/")

        assert result == [
            ("plan_index/aaa", '{"plan_id": "aaa"}'),
            ("plan_index/bbb", '{"plan_id": "bbb"}'),
        ]

    @pytest.mark.asyncio
    async def test_list_prefix_returns_empty_when_disabled(self):
        client = _make_client(enabled=False)
        result = await client.list_prefix("plan_index/")
        assert result == []


class TestDharaKvClientDelete:
    @pytest.mark.asyncio
    async def test_delete_calls_dhara(self):
        mock_call_tool = AsyncMock()
        client = _make_client(call_tool=mock_call_tool)

        await client.delete("plan_index/meta/rebuild_lock/holder")

        mock_call_tool.assert_awaited_once_with(
            "delete", {"key": "plan_index/meta/rebuild_lock/holder"}
        )

    @pytest.mark.asyncio
    async def test_delete_is_noop_when_disabled(self):
        mock_call_tool = AsyncMock()
        client = _make_client(enabled=False, call_tool=mock_call_tool)
        await client.delete("k")
        mock_call_tool.assert_not_called()


class TestDharaKvClientContract:
    """Sanity: DharaKvClient satisfies PlanIndexStore's _DharaClient Protocol.

    The Protocol declared in plan_index/store.py:109-115 is::

        class _DharaClient(Protocol):
            async def put(self, key: str, value: str, *, ttl: int | None = ...) -> None: ...
            async def get(self, key: str) -> str | None: ...
            async def list_prefix(self, prefix: str) -> list[tuple[str, str]]: ...
            async def delete(self, key: str) -> None: ...
    """

    def test_satisfies_plan_index_store_protocol(self):
        from mahavishnu.plan_index.store import PlanIndexStore

        client = _make_client()
        store = PlanIndexStore(client)  # type: ignore[arg-type]
        # No exception here means the protocol is satisfied at runtime.
        assert store._dhara is client


class TestDharaKvClientCronCoreIntBug:
    """Reproduces the original int(dict) bug end-to-end through the adapter.

    When DharaStateBackend was wired into PlanIndexStore, cron_core's
    ``int(await store._dhara.get(KEY))`` raised ``TypeError``. With
    DharaKvClient unwrapping the envelope, the same code returns an
    int-compatible string and the conversion succeeds.
    """

    @pytest.mark.asyncio
    async def test_int_of_get_returns_int(self):
        envelope = {"ok": True, "key": "plan_index/meta/cycles_total", "value": "42"}
        client = _make_client(call_tool=AsyncMock(return_value=envelope))

        cycles_raw = await client.get("plan_index/meta/cycles_total")
        # This is the exact expression that crashed cron_core.py:559
        cycles_total = int(cycles_raw) + 1 if cycles_raw else 1

        assert cycles_total == 43

    @pytest.mark.asyncio
    async def test_json_loads_of_recent_errors(self):
        import json

        recent_raw = (
            '[{"ts_ms": 1234, "op": "upsert", "err": "see ctx", '
            '"ctx": {"path_hash": "abc"}}]'
        )
        envelope = {
            "ok": True,
            "key": "plan_index/meta/recent_errors",
            "value": recent_raw,
        }
        client = _make_client(call_tool=AsyncMock(return_value=envelope))

        raw = await client.get("plan_index/meta/recent_errors")
        parsed = json.loads(raw) if raw else []
        assert isinstance(parsed, list)
        # cron_core stores recent_errors as [{ts_ms, op, err, ctx:{path_hash,...}}]
        assert parsed[0]["ctx"]["path_hash"] == "abc"
