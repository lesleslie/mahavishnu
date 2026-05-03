"""OpenClaw gateway worker interface and base implementation.

This module defines a transport-agnostic interface for running Mahavishnu tasks
through an OpenClaw gateway endpoint.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol
import uuid

import httpx

from .base import BaseWorker, WorkerResult, WorkerStatus


@dataclass
class OpenClawGatewayConfig:
    """Configuration for an OpenClaw gateway worker."""

    gateway_url: str = "http://localhost:8787"
    token: str | None = None
    default_method: str = "agent.run"
    default_timeout: int = 300
    health_method: str = "health"
    status_method: str = "status"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OpenClawTaskRequest:
    """Normalized task request sent to OpenClaw gateway."""

    method: str
    params: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 300
    session_id: str | None = None
    agent_id: str | None = None


class OpenClawGatewayClient(Protocol):
    """Protocol for OpenClaw gateway clients.

    Implementations may use CLI wrappers, HTTP RPC, WebSocket RPC, or MCP bridge.
    """

    async def health(self) -> dict[str, Any]:
        """Check gateway health."""

    async def status(self) -> dict[str, Any]:
        """Get gateway status and runtime info."""

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Call a gateway RPC method."""


class HTTPOpenClawGatewayClient:
    """HTTP JSON-RPC client for OpenClaw gateway endpoints."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        rpc_path: str = "/rpc",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.rpc_path = rpc_path
        self._client = httpx.AsyncClient(timeout=timeout)
        self._headers: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    async def health(self) -> dict[str, Any]:
        """Check gateway health endpoint."""
        response = await self._client.get(f"{self.base_url}/health", headers=self._headers)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            payload.setdefault("healthy", True)
            return payload
        return {"healthy": True, "raw": payload}

    async def status(self) -> dict[str, Any]:
        """Get gateway status endpoint."""
        response = await self._client.get(f"{self.base_url}/status", headers=self._headers)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"status": "unknown", "raw": payload}

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a JSON-RPC style call."""
        request_id = str(uuid.uuid4())
        response = await self._client.post(
            f"{self.base_url}{self.rpc_path}",
            headers=self._headers,
            json={
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return {"result": payload}

        if payload.get("error"):
            raise RuntimeError(f"OpenClaw RPC error: {payload['error']}")

        if "result" in payload:
            result = payload["result"]
            return result if isinstance(result, dict) else {"result": result}

        return payload

    async def aclose(self) -> None:
        """Close underlying HTTP client."""
        await self._client.aclose()


class OpenClawGatewayWorker(BaseWorker):
    """Worker that routes tasks to an OpenClaw gateway client."""

    def __init__(
        self,
        gateway_client: OpenClawGatewayClient,
        config: OpenClawGatewayConfig | None = None,
    ) -> None:
        super().__init__(worker_type="gateway-openclaw")
        self.gateway_client = gateway_client
        self.config = config or OpenClawGatewayConfig()
        self.worker_id = f"openclaw_{uuid.uuid4().hex[:12]}"
        self._start_time: float | None = None

    async def start(self) -> str:
        """Validate gateway availability and mark worker as running."""
        health = await self.gateway_client.health()
        healthy = bool(health.get("healthy", True))
        if not healthy:
            self._status = WorkerStatus.FAILED
            raise RuntimeError(f"OpenClaw gateway is not healthy: {health}")

        self._status = WorkerStatus.RUNNING
        self._start_time = asyncio.get_event_loop().time()
        return self.worker_id

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Execute a task through the configured OpenClaw gateway client."""
        if self._status != WorkerStatus.RUNNING:
            await self.start()

        request = self._normalize_task(task)

        try:
            response = await asyncio.wait_for(
                self.gateway_client.call(request.method, request.params),
                timeout=request.timeout_seconds,
            )
            output = self._extract_output(response)
            return WorkerResult(
                worker_id=self.worker_id,
                status=WorkerStatus.COMPLETED,
                output=output,
                duration_seconds=self._duration(),
                metadata={
                    "gateway_url": self.config.gateway_url,
                    "method": request.method,
                    "session_id": request.session_id,
                    "agent_id": request.agent_id,
                    "response": response,
                },
            )
        except TimeoutError:
            return WorkerResult(
                worker_id=self.worker_id,
                status=WorkerStatus.TIMEOUT,
                error=f"Gateway call timed out after {request.timeout_seconds}s",
                duration_seconds=self._duration(),
                metadata={"method": request.method},
            )
        except Exception as e:
            return WorkerResult(
                worker_id=self.worker_id,
                status=WorkerStatus.FAILED,
                error=str(e),
                duration_seconds=self._duration(),
                metadata={"method": request.method, "exception": type(e).__name__},
            )

    async def stop(self) -> None:
        """Stop worker."""
        self._status = WorkerStatus.COMPLETED

    async def status(self) -> WorkerStatus:
        """Return current worker status."""
        return self._status

    async def get_progress(self) -> dict[str, Any]:
        """Return progress snapshot for this worker."""
        gateway_status = await self.gateway_client.status()
        return {
            "worker_id": self.worker_id,
            "status": self._status.value,
            "duration": self._duration(),
            "gateway_status": gateway_status,
        }

    def _normalize_task(self, task: dict[str, Any]) -> OpenClawTaskRequest:
        """Map generic task input to OpenClawTaskRequest."""
        params = dict(task.get("params", {}))
        prompt = task.get("prompt")
        if prompt and "prompt" not in params:
            params["prompt"] = prompt

        return OpenClawTaskRequest(
            method=task.get("method", self.config.default_method),
            params=params,
            timeout_seconds=int(task.get("timeout", self.config.default_timeout)),
            session_id=task.get("session_id"),
            agent_id=task.get("agent_id"),
        )

    @staticmethod
    def _extract_output(response: dict[str, Any]) -> str:
        """Extract user-facing output from gateway response."""
        for key in ("output", "result", "message", "text"):
            value = response.get(key)
            if value is not None:
                return value if isinstance(value, str) else str(value)
        return str(response)

    def _duration(self) -> float:
        """Calculate elapsed worker time."""
        if self._start_time is None:
            return 0.0
        return asyncio.get_event_loop().time() - self._start_time


__all__ = [
    "HTTPOpenClawGatewayClient",
    "OpenClawGatewayConfig",
    "OpenClawTaskRequest",
    "OpenClawGatewayClient",
    "OpenClawGatewayWorker",
]
