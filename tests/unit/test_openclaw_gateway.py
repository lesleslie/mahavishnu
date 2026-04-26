"""Tests for mahavishnu.workers.openclaw_gateway — OpenClaw gateway worker interface."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.base import BaseWorker, WorkerResult
from mahavishnu.workers.openclaw_gateway import (
    HTTPOpenClawGatewayClient,
    OpenClawGatewayClient,
    OpenClawGatewayConfig,
    OpenClawGatewayWorker,
    OpenClawTaskRequest,
)


class TestOpenClawGatewayConfig:
    """Test OpenClawGatewayConfig dataclass."""

    def test_default_values(self):
        cfg = OpenClawGatewayConfig()
        assert cfg.gateway_url == "http://localhost:8787"
        assert cfg.token is None
        assert cfg.default_method == "agent.run"
        assert cfg.default_timeout == 300
        assert cfg.health_method == "health"
        assert cfg.status_method == "status"
        assert cfg.metadata == {}

    def test_custom_values(self):
        cfg = OpenClawGatewayConfig(
            gateway_url="https://gateway.example.com",
            token="secret-token",
            default_method="custom.run",
            default_timeout=120,
            health_method="ping",
            status_method="info",
            metadata={"region": "us-east"},
        )
        assert cfg.gateway_url == "https://gateway.example.com"
        assert cfg.token == "secret-token"
        assert cfg.default_method == "custom.run"
        assert cfg.default_timeout == 120
        assert cfg.health_method == "ping"
        assert cfg.status_method == "info"
        assert cfg.metadata == {"region": "us-east"}

    def test_metadata_defaults_to_empty_dict(self):
        cfg1 = OpenClawGatewayConfig()
        cfg2 = OpenClawGatewayConfig()
        assert cfg1.metadata is not cfg2.metadata


class TestOpenClawTaskRequest:
    """Test OpenClawTaskRequest dataclass."""

    def test_defaults(self):
        req = OpenClawTaskRequest(method="agent.run")
        assert req.method == "agent.run"
        assert req.params == {}
        assert req.timeout_seconds == 300
        assert req.session_id is None
        assert req.agent_id is None

    def test_custom_values(self):
        req = OpenClawTaskRequest(
            method="task.execute",
            params={"prompt": "hello"},
            timeout_seconds=60,
            session_id="sess-1",
            agent_id="agent-1",
        )
        assert req.method == "task.execute"
        assert req.params == {"prompt": "hello"}
        assert req.timeout_seconds == 60
        assert req.session_id == "sess-1"
        assert req.agent_id == "agent-1"


class TestHTTPOpenClawGatewayClient:
    """Test HTTPOpenClawGatewayClient HTTP JSON-RPC client."""

    def _make_client(self, base_url="http://localhost:8787", token=None, **kwargs):
        client = HTTPOpenClawGatewayClient(base_url=base_url, token=token, **kwargs)
        return client

    def test_init_strips_trailing_slash(self):
        client = self._make_client(base_url="http://localhost:8787/")
        assert client.base_url == "http://localhost:8787"

    def test_init_with_token_sets_auth_header(self):
        client = self._make_client(token="my-token")
        assert client._headers["Authorization"] == "Bearer my-token"

    def test_init_without_token_no_auth_header(self):
        client = self._make_client()
        assert "Authorization" not in client._headers

    def test_init_sets_content_type(self):
        client = self._make_client()
        assert client._headers["Content-Type"] == "application/json"

    def test_init_custom_rpc_path(self):
        client = self._make_client(rpc_path="/api/v1/rpc")
        assert client.rpc_path == "/api/v1/rpc"

    @pytest.mark.asyncio
    async def test_health_returns_dict_payload(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = {"healthy": True, "version": "1.0"}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        result = await client.health()
        assert result == {"healthy": True, "version": "1.0"}
        client._client.get.assert_called_once_with(
            "http://localhost:8787/health", headers=client._headers
        )

    @pytest.mark.asyncio
    async def test_health_adds_healthy_key_if_missing(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = {"version": "1.0"}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        result = await client.health()
        assert result == {"version": "1.0", "healthy": True}

    @pytest.mark.asyncio
    async def test_health_handles_non_dict_payload(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = "OK"
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        result = await client.health()
        assert result == {"healthy": True, "raw": "OK"}

    @pytest.mark.asyncio
    async def test_health_propagates_http_error(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503", request=MagicMock(), response=MagicMock()
        )

        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        with pytest.raises(httpx.HTTPStatusError):
            await client.health()

    @pytest.mark.asyncio
    async def test_status_returns_dict_payload(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "running", "workers": 5}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        result = await client.status()
        assert result == {"status": "running", "workers": 5}
        client._client.get.assert_called_once_with(
            "http://localhost:8787/status", headers=client._headers
        )

    @pytest.mark.asyncio
    async def test_status_handles_non_dict_payload(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = "ok"
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.get = AsyncMock(return_value=mock_response)

        result = await client.status()
        assert result == {"status": "unknown", "raw": "ok"}

    @pytest.mark.asyncio
    async def test_call_returns_result_dict(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "result": {"output": "done"},
        }
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        result = await client.call("agent.run", {"prompt": "hello"})
        assert result == {"output": "done"}

        call_args = client._client.post.call_args
        posted_json = call_args.kwargs["json"]
        assert posted_json["method"] == "agent.run"
        assert posted_json["params"] == {"prompt": "hello"}
        assert posted_json["jsonrpc"] == "2.0"
        assert "id" in posted_json

    @pytest.mark.asyncio
    async def test_call_with_non_dict_result_wraps_in_dict(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "result": "scalar-result",
        }
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        result = await client.call("task.get", {})
        assert result == {"result": "scalar-result"}

    @pytest.mark.asyncio
    async def test_call_raises_on_rpc_error(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "error": {"code": -32000, "message": "Internal error"},
        }
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(RuntimeError, match="OpenClaw RPC error"):
            await client.call("bad.method", {})

    @pytest.mark.asyncio
    async def test_call_handles_non_dict_payload(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = "unexpected"
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        result = await client.call("weird", {})
        assert result == {"result": "unexpected"}

    @pytest.mark.asyncio
    async def test_call_handles_payload_without_result_or_error(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": "test-id",
            "data": "something",
        }
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        result = await client.call("no.result", {})
        assert result == {"jsonrpc": "2.0", "id": "test-id", "data": "something"}

    @pytest.mark.asyncio
    async def test_call_generates_unique_request_ids(self):
        client = self._make_client()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": "x",
            "result": {},
        }
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        await client.call("a", {})
        await client.call("b", {})

        id1 = client._client.post.call_args_list[0].kwargs["json"]["id"]
        id2 = client._client.post.call_args_list[1].kwargs["json"]["id"]
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_call_sends_to_correct_endpoint(self):
        client = self._make_client(base_url="https://gw.example.com", rpc_path="/api/rpc")
        mock_response = MagicMock()
        mock_response.json.return_value = {"jsonrpc": "2.0", "id": "x", "result": {}}
        mock_response.raise_for_status = MagicMock()

        client._client = AsyncMock()
        client._client.post = AsyncMock(return_value=mock_response)

        await client.call("test", {})
        client._client.post.assert_called_once()
        call_url = client._client.post.call_args.args[0]
        assert call_url == "https://gw.example.com/api/rpc"

    @pytest.mark.asyncio
    async def test_aclose_delegates_to_http_client(self):
        client = self._make_client()
        client._client = AsyncMock()
        await client.aclose()
        client._client.aclose.assert_called_once()


class TestOpenClawGatewayWorker:
    """Test OpenClawGatewayWorker lifecycle and task execution."""

    def _make_worker(self, gateway_client=None, config=None):
        client = gateway_client or AsyncMock(spec=OpenClawGatewayClient)
        return OpenClawGatewayWorker(gateway_client=client, config=config)

    def test_inherits_from_base_worker(self):
        worker = self._make_worker()
        assert isinstance(worker, BaseWorker)

    def test_worker_type(self):
        worker = self._make_worker()
        assert worker.worker_type == "gateway-openclaw"

    def test_worker_id_prefixed(self):
        worker = self._make_worker()
        assert worker.worker_id.startswith("openclaw_")
        assert len(worker.worker_id) == len("openclaw_") + 12

    def test_worker_id_is_unique(self):
        w1 = self._make_worker()
        w2 = self._make_worker()
        assert w1.worker_id != w2.worker_id

    def test_default_config(self):
        worker = self._make_worker()
        assert worker.config.gateway_url == "http://localhost:8787"
        assert worker.config.default_method == "agent.run"
        assert worker.config.default_timeout == 300

    def test_custom_config(self):
        cfg = OpenClawGatewayConfig(gateway_url="https://custom")
        worker = self._make_worker(config=cfg)
        assert worker.config.gateway_url == "https://custom"

    def test_initial_status_is_pending(self):
        worker = self._make_worker()
        assert worker._status == WorkerStatus.PENDING

    @pytest.mark.asyncio
    async def test_start_sets_running_on_healthy_gateway(self):
        client = AsyncMock(spec=OpenClawGatewayClient)
        client.health.return_value = {"healthy": True}
        worker = self._make_worker(gateway_client=client)

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.time.return_value = 100.0
            wid = await worker.start()

        assert wid == worker.worker_id
        assert worker._status == WorkerStatus.RUNNING
        assert worker._start_time == 100.0
        client.health.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_raises_on_unhealthy_gateway(self):
        client = AsyncMock(spec=OpenClawGatewayClient)
        client.health.return_value = {"healthy": False, "reason": "db down"}
        worker = self._make_worker(gateway_client=client)

        with pytest.raises(RuntimeError, match="not healthy"):
            await worker.start()

        assert worker._status == WorkerStatus.FAILED

    @pytest.mark.asyncio
    async def test_start_treats_missing_healthy_key_as_true(self):
        client = AsyncMock(spec=OpenClawGatewayClient)
        client.health.return_value = {"status": "ok"}
        worker = self._make_worker(gateway_client=client)

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.time.return_value = 0.0
            wid = await worker.start()

        assert worker._status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_stop_sets_completed(self):
        worker = self._make_worker()
        await worker.stop()
        assert worker._status == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_status_returns_current_status(self):
        worker = self._make_worker()
        result = await worker.status()
        assert result == WorkerStatus.PENDING

        worker._status = WorkerStatus.RUNNING
        result = await worker.status()
        assert result == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_get_progress_includes_gateway_status(self):
        client = AsyncMock(spec=OpenClawGatewayClient)
        client.status.return_value = {"workers": 3, "uptime": 3600}
        worker = self._make_worker(gateway_client=client)

        progress = await worker.get_progress()
        assert progress["worker_id"] == worker.worker_id
        assert progress["status"] == WorkerStatus.PENDING.value
        assert progress["gateway_status"] == {"workers": 3, "uptime": 3600}
        assert "duration" in progress

    @pytest.mark.asyncio
    async def test_get_progress_after_start(self):
        client = AsyncMock(spec=OpenClawGatewayClient)
        client.health.return_value = {"healthy": True}
        client.status.return_value = {"status": "ok"}
        worker = self._make_worker(gateway_client=client)

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.time.side_effect = [100.0, 110.0]
            await worker.start()
            progress = await worker.get_progress()

        assert progress["duration"] == 10.0
        assert progress["status"] == WorkerStatus.RUNNING.value

    @pytest.mark.asyncio
    async def test_execute_calls_gateway_client(self):
        client = AsyncMock(spec=OpenClawGatewayClient)
        client.health.return_value = {"healthy": True}
        client.call.return_value = {"output": "task done"}
        worker = self._make_worker(gateway_client=client)

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.time.return_value = 0.0
            await worker.start()

        result = await worker.execute({"method": "agent.run", "params": {"prompt": "hi"}})

        assert result.status == WorkerStatus.COMPLETED
        assert result.output == "task done"
        assert result.worker_id == worker.worker_id
        client.call.assert_called_once_with("agent.run", {"prompt": "hi"})

    @pytest.mark.asyncio
    async def test_execute_auto_starts_if_not_running(self):
        client = AsyncMock(spec=OpenClawGatewayClient)
        client.health.return_value = {"healthy": True}
        client.call.return_value = {"output": "auto-started"}
        worker = self._make_worker(gateway_client=client)

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.time.return_value = 0.0
            result = await worker.execute({"prompt": "test"})

        assert result.status == WorkerStatus.COMPLETED
        assert worker._status == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        client = AsyncMock(spec=OpenClawGatewayClient)
        client.health.return_value = {"healthy": True}
        client.call.side_effect = asyncio.TimeoutError()

        worker = self._make_worker(gateway_client=client, config=OpenClawGatewayConfig(default_timeout=1))

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.time.return_value = 0.0
            await worker.start()

        result = await worker.execute({"timeout": 1})
        assert result.status == WorkerStatus.TIMEOUT
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_generic_exception(self):
        client = AsyncMock(spec=OpenClawGatewayClient)
        client.health.return_value = {"healthy": True}
        client.call.side_effect = RuntimeError("connection refused")

        worker = self._make_worker(gateway_client=client)

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.time.return_value = 0.0
            await worker.start()

        result = await worker.execute({"method": "agent.run"})
        assert result.status == WorkerStatus.FAILED
        assert result.error == "connection refused"
        assert result.metadata["exception"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_execute_http_error(self):
        client = AsyncMock(spec=OpenClawGatewayClient)
        client.health.return_value = {"healthy": True}
        client.call.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )

        worker = self._make_worker(gateway_client=client)

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.time.return_value = 0.0
            await worker.start()

        result = await worker.execute({})
        assert result.status == WorkerStatus.FAILED
        assert result.metadata["exception"] == "HTTPStatusError"

    @pytest.mark.asyncio
    async def test_execute_metadata_includes_session_and_agent(self):
        client = AsyncMock(spec=OpenClawGatewayClient)
        client.health.return_value = {"healthy": True}
        client.call.return_value = {"output": "ok"}
        worker = self._make_worker(gateway_client=client)

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.time.return_value = 0.0
            await worker.start()

        result = await worker.execute({
            "session_id": "sess-42",
            "agent_id": "agent-7",
        })
        assert result.metadata["session_id"] == "sess-42"
        assert result.metadata["agent_id"] == "agent-7"
        assert result.metadata["gateway_url"] == "http://localhost:8787"


class TestOpenClawGatewayWorkerNormalizeTask:
    """Test OpenClawGatewayWorker._normalize_task."""

    def test_normalize_with_method_and_params(self):
        worker = OpenClawGatewayWorker(
            gateway_client=AsyncMock(spec=OpenClawGatewayClient)
        )
        task = {"method": "task.run", "params": {"key": "val"}}
        req = worker._normalize_task(task)
        assert req.method == "task.run"
        assert req.params == {"key": "val"}

    def test_normalize_defaults_method_from_config(self):
        cfg = OpenClawGatewayConfig(default_method="default.run")
        worker = OpenClawGatewayWorker(
            gateway_client=AsyncMock(spec=OpenClawGatewayClient), config=cfg
        )
        req = worker._normalize_task({})
        assert req.method == "default.run"

    def test_normalize_includes_prompt_in_params(self):
        worker = OpenClawGatewayWorker(
            gateway_client=AsyncMock(spec=OpenClawGatewayClient)
        )
        req = worker._normalize_task({"prompt": "hello world"})
        assert req.params["prompt"] == "hello world"

    def test_normalize_prompt_does_not_override_existing(self):
        worker = OpenClawGatewayWorker(
            gateway_client=AsyncMock(spec=OpenClawGatewayClient)
        )
        req = worker._normalize_task({
            "prompt": "new",
            "params": {"prompt": "original"},
        })
        assert req.params["prompt"] == "original"

    def test_normalize_timeout_from_task(self):
        worker = OpenClawGatewayWorker(
            gateway_client=AsyncMock(spec=OpenClawGatewayClient)
        )
        req = worker._normalize_task({"timeout": 60})
        assert req.timeout_seconds == 60

    def test_normalize_timeout_defaults_from_config(self):
        cfg = OpenClawGatewayConfig(default_timeout=180)
        worker = OpenClawGatewayWorker(
            gateway_client=AsyncMock(spec=OpenClawGatewayClient), config=cfg
        )
        req = worker._normalize_task({})
        assert req.timeout_seconds == 180

    def test_normalize_session_and_agent_ids(self):
        worker = OpenClawGatewayWorker(
            gateway_client=AsyncMock(spec=OpenClawGatewayClient)
        )
        req = worker._normalize_task({
            "session_id": "s1",
            "agent_id": "a1",
        })
        assert req.session_id == "s1"
        assert req.agent_id == "a1"

    def test_normalize_does_not_mutate_input_params(self):
        worker = OpenClawGatewayWorker(
            gateway_client=AsyncMock(spec=OpenClawGatewayClient)
        )
        original = {"params": {"key": "val"}}
        worker._normalize_task(original)
        assert "prompt" not in original["params"]


class TestOpenClawGatewayWorkerExtractOutput:
    """Test OpenClawGatewayWorker._extract_output."""

    def test_extracts_output_key(self):
        result = OpenClawGatewayWorker._extract_output({"output": "hello"})
        assert result == "hello"

    def test_extracts_result_key(self):
        result = OpenClawGatewayWorker._extract_output({"result": "hello"})
        assert result == "hello"

    def test_extracts_message_key(self):
        result = OpenClawGatewayWorker._extract_output({"message": "hello"})
        assert result == "hello"

    def test_extracts_text_key(self):
        result = OpenClawGatewayWorker._extract_output({"text": "hello"})
        assert result == "hello"

    def test_output_key_has_priority(self):
        result = OpenClawGatewayWorker._extract_output({
            "output": "first",
            "result": "second",
            "message": "third",
            "text": "fourth",
        })
        assert result == "first"

    def test_non_string_value_is_stringified(self):
        result = OpenClawGatewayWorker._extract_output({"output": 42})
        assert result == "42"

    def test_none_values_are_skipped(self):
        result = OpenClawGatewayWorker._extract_output({
            "output": None,
            "result": None,
            "message": None,
        })
        assert result == str({"output": None, "result": None, "message": None})

    def test_empty_dict_falls_through_to_str(self):
        result = OpenClawGatewayWorker._extract_output({})
        assert result == "{}"

    def test_unknown_keys_fall_through_to_str(self):
        resp = {"data": "value", "code": 200}
        result = OpenClawGatewayWorker._extract_output(resp)
        assert result == str(resp)


class TestOpenClawGatewayWorkerDuration:
    """Test OpenClawGatewayWorker._duration."""

    def _make_worker(self, gateway_client=None, config=None):
        client = gateway_client or AsyncMock(spec=OpenClawGatewayClient)
        return OpenClawGatewayWorker(gateway_client=client, config=config)

    def test_duration_is_zero_before_start(self):
        worker = OpenClawGatewayWorker(
            gateway_client=AsyncMock(spec=OpenClawGatewayClient)
        )
        assert worker._duration() == 0.0

    @pytest.mark.asyncio
    async def test_duration_after_start(self):
        client = AsyncMock(spec=OpenClawGatewayClient)
        client.health.return_value = {"healthy": True}
        worker = self._make_worker(gateway_client=client)

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.time.return_value = 50.0
            await worker.start()
            mock_loop.return_value.time.return_value = 55.5
            assert worker._duration() == 5.5
