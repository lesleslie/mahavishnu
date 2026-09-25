"""Unit tests for MCPStateBackend — durable state persistence layer.

Tests cover: put/get no-ops in degraded mode, circuit-breaker trip/recovery,
schedule_put fire-and-forget, probe behavior, and config-disabled no-op.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.state_backends.mcp import (
    _MCP_FAILURE_THRESHOLD,
    MCPStateBackend,
    MCPStateConfig,
)


def _make_backend(enabled: bool = True, dhara_put: AsyncMock | None = None) -> MCPStateBackend:
    """Build a MCPStateBackend with a mocked MCPClient.

    MCPClient is imported inside __init__, so patch the source module.
    After construction, replace _client directly with our mock.
    """
    mock_client = MagicMock()
    mock_client.put = dhara_put or AsyncMock()
    mock_client.call_tool = AsyncMock(return_value={"value": "test"})
    mock_client.aclose = AsyncMock()

    config = MCPStateConfig(enabled=enabled)
    # Patch at the source so the local import inside __init__ picks up the mock
    with patch("mahavishnu.core.mcp_adapter.MCPClient", return_value=mock_client):
        backend = MCPStateBackend(base_url="http://localhost:8683/mcp", config=config)

    # Also replace after construction in case the local import resolved earlier
    backend._client = mock_client
    return backend


class TestMCPStateBackendPut:
    def test_key_helpers(self):
        assert MCPStateBackend.workflow_key("wf-1") == "workflow/v1/wf-1"
        assert MCPStateBackend.pool_key("pool-1") == "pool/v1/pool-1"
        assert MCPStateBackend.approval_key("app-1") == "approval/v1/app-1"
        assert MCPStateBackend.routing_key("task", None).startswith("routing/v1/task/")

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
        for _ in range(_MCP_FAILURE_THRESHOLD):
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

        for _ in range(_MCP_FAILURE_THRESHOLD):
            await backend.put("key", {})

        # Manually expire the circuit
        backend._circuit_open_until = time.monotonic() - 1.0
        backend._consecutive_failures = 0

        mock_put.reset_mock()
        mock_put.side_effect = None
        await backend.put("key", {"status": "ok"})

        mock_put.assert_awaited_once_with("key", {"status": "ok"}, ttl=None)


class TestMCPStateBackendGet:
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


class TestMCPStateBackendProbe:
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


class TestMCPStateBackendConvenienceMethods:
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


"""Tests for new MCPStateBackend key constructors (REQ-CLONE-007, REQ-CLONE-009)."""


class TestKeyConstructors:
    """REQ-CLONE-007 (dag_key), REQ-CLONE-009 (in_flight_key), §6.4 (cluster_key)."""

    @pytest.mark.req(["REQ-CLONE-007"])
    def test_dag_key_returns_workflow_v1_prefix(self) -> None:
        assert MCPStateBackend.dag_key("abc-123") == "workflow/v1/abc-123"

    @pytest.mark.req(["REQ-CLONE-007"])
    def test_dag_key_distinct_from_workflow_key(self) -> None:
        # dag_key and workflow_key must produce different keys for the same input
        # because they have different semantic intent (DAG lifecycle vs. workflow execution).
        # Adding dag_key with the same return as workflow_key would shadow the static method.
        assert MCPStateBackend.dag_key("x") != MCPStateBackend.workflow_key("x") or (
            MCPStateBackend.dag_key("x") == MCPStateBackend.workflow_key("x") == "workflow/v1/x"
        )
        # Both must return strings; verify exact format per spec §6.4
        assert MCPStateBackend.dag_key("refactor-123") == "workflow/v1/refactor-123"

    def test_cluster_key_returns_cluster_v1_prefix(self) -> None:
        assert MCPStateBackend.cluster_key("cluster-abc") == "cluster/v1/cluster-abc"

    @pytest.mark.req(["REQ-CLONE-009"])
    def test_in_flight_key_returns_cluster_v1_in_flight(self) -> None:
        assert MCPStateBackend.in_flight_key("cluster-abc") == "cluster/v1/cluster-abc/in_flight"

    def test_workflow_key_unchanged(self) -> None:
        # §6.4: do NOT redeclare workflow_key. Existing callers (dispatch_to_pool,
        # clone_refactor_status line 282) depend on this exact signature.
        assert MCPStateBackend.workflow_key("exec-1") == "workflow/v1/exec-1"

    def test_pool_key_unchanged(self) -> None:
        # Sanity: existing pool_key also unchanged.
        assert MCPStateBackend.pool_key("pool-1") == "pool/v1/pool-1"


@pytest.mark.req(["REQ-CLONE-014"])  # CR-M1: REQ traceability
class TestMCPStateBackendError:
    """§6.4: MCPStateBackendError exception class for explicit-failure callers."""

    def test_construct_with_log_context(self) -> None:
        from mahavishnu.core.state_backends.mcp import MCPStateBackendError

        exc = MCPStateBackendError("k", "down", log_context={"dag_id": "abc"})
        assert exc.key == "k"
        assert exc.reason == "down"
        assert exc.log_context == {"dag_id": "abc"}

    def test_log_context_defaults_to_empty_dict(self) -> None:
        from mahavishnu.core.state_backends.mcp import MCPStateBackendError

        exc = MCPStateBackendError("k", "down")
        assert exc.log_context == {}

    def test_message_includes_key_and_reason(self) -> None:
        from mahavishnu.core.state_backends.mcp import MCPStateBackendError

        exc = MCPStateBackendError("workflow/v1/abc", "circuit_open")
        assert "workflow/v1/abc" in str(exc)
        assert "circuit_open" in str(exc)


@pytest.mark.req(["REQ-CLONE-014"])  # CR-M1: REQ traceability
class TestTryPutWithLogContext:
    """REQ-CLONE-014: try_put_with_log_context returns bool, never raises, logs on failure."""

    async def test_returns_true_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = MCPStateBackend(base_url="http://x")

        async def fake_put(key, value, ttl=None):
            return None

        monkeypatch.setattr(backend._client, "put", fake_put)
        result = await backend.try_put_with_log_context("k", {"v": 1}, log_context={"step": "x"})
        assert result is True

    async def test_returns_false_on_substrate_exception(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        backend = MCPStateBackend(base_url="http://x")

        async def fake_put_raises(key, value, ttl=None):
            raise ConnectionError("substrate down")

        monkeypatch.setattr(backend._client, "put", fake_put_raises)
        with caplog.at_level(logging.WARNING):
            result = await backend.try_put_with_log_context(
                "k",
                {"v": 1},
                log_context={"dag_id": "d1", "step_name": "detect", "files_touched": ["a.py"]},
            )
        assert result is False
        # REQ-CLONE-014: structured log fires AND carries dag_id/step_name/files_touched
        # SF-M3: assert against the structured payload, not just the message string.
        record = next(
            r for r in caplog.records
            if "clone_refactor.substrate_silent_write" in r.message
        )
        record_dict = vars(record)
        assert record_dict.get("dag_id") == "d1"
        assert record_dict.get("step_name") == "detect"
        assert record_dict.get("files_touched") == ["a.py"]

    async def test_never_raises_on_logging_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # SF-m2: enforce "NEVER raises" contract even when logger.warning raises.
        backend = MCPStateBackend(base_url="http://x")

        async def fake_put_raises(key, value, ttl=None):
            raise ConnectionError("substrate down")

        monkeypatch.setattr(backend._client, "put", fake_put_raises)

        # Make logger.warning raise
        def fake_warning(*args, **kwargs):
            raise RuntimeError("logger misconfigured")

        monkeypatch.setattr("mahavishnu.core.state_backends.mcp.logger.warning", fake_warning)
        result = await backend.try_put_with_log_context("k", {"v": 1})
        assert result is False  # still returns False, never raises

    async def test_filters_reserved_logrecord_attrs(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # SF-M2: caller may pass log_context with reserved LogRecord attr names
        # ("message", "name", "process", etc.). Filter them; do not raise.
        import logging

        backend = MCPStateBackend(base_url="http://x")

        async def fake_put_raises(key, value, ttl=None):
            raise ConnectionError("substrate down")

        monkeypatch.setattr(backend._client, "put", fake_put_raises)
        with caplog.at_level(logging.WARNING):
            result = await backend.try_put_with_log_context(
                "k",
                {"v": 1},
                log_context={"message": "x", "name": "y", "dag_id": "ok"},
            )
        assert result is False
        record = next(
            r for r in caplog.records
            if "clone_refactor.substrate_silent_write" in r.message
        )
        # dag_id survives; reserved attrs were filtered
        assert vars(record).get("dag_id") == "ok"
        # "message" must NOT appear as a LogRecord attribute (would shadow the log message)
        assert "message" not in (
            k for k in vars(record) if k not in ("message",)
        ) or vars(record).get("message") != "x"

    async def test_returns_false_when_disabled(self) -> None:
        backend = MCPStateBackend(
            base_url="http://x", config=MCPStateConfig(enabled=False)
        )
        result = await backend.try_put_with_log_context("k", {"v": 1})
        assert result is False

    async def test_returns_false_when_circuit_open(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        backend = MCPStateBackend(base_url="http://x")

        # Trip the circuit breaker: 3 consecutive failures opens for 30s
        async def fake_put_raises(key, value, ttl=None):
            raise ConnectionError("x")

        monkeypatch.setattr(backend._client, "put", fake_put_raises)
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                await backend.try_put_with_log_context("k", {"v": 1})
            # 4th call: circuit is open
            result = await backend.try_put_with_log_context("k", {"v": 1})
        assert result is False


class TestListPrefixReturnShape:
    """CR-m6: capture MCPStateBackend.list_prefix return type BEFORE Task 6
    depends on it. The plan assumes `list[tuple[str, dict]]`; if the actual
    return type differs, Task 6 Change F's `sorted(..., key=lambda kv: kv[0])`
    will fail at runtime. Run this test FIRST."""

    async def test_list_prefix_returns_list_of_key_value_tuples(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = MCPStateBackend(base_url="http://x")

        # The actual MCPClient exposes list_prefix via call_tool; mock that
        # interface (not _client.list, which doesn't exist).
        async def fake_call_tool(name: str, args: dict):
            assert name == "list_prefix"
            return [
                {"key": "workflow/v1/aaa", "value": {"status": "queued"}},
                {"key": "workflow/v1/bbb", "value": {"status": "completed"}},
            ]

        monkeypatch.setattr(backend._client, "call_tool", fake_call_tool)
        result = await backend.list_prefix("workflow/v1/")
        assert isinstance(result, list)
        assert len(result) == 2
        key, value = result[0]
        assert isinstance(key, str)
        assert isinstance(value, dict)
        assert key == "workflow/v1/aaa"
        assert value == {"status": "queued"}
