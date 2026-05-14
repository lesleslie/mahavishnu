"""Dhara-backed durable state persistence for Mahavishnu.

Provides a thin coordination layer over DharaClient that implements
degraded-boot mode and circuit-breaker protection. All writes are
fire-and-forget — callers never block on persistence.

Key schema (see addendum doc):
  workflow/v1/{execution_id}
  pool/v1/{pool_id}
  routing/v1/{task_class}/{timestamp}
  approval/v1/{request_id}
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)

_DHARA_FAILURE_THRESHOLD = 3
_DHARA_RECOVERY_SECONDS = 30.0


@dataclass
class DharaStateConfig:
    """Configuration for Dhara state persistence."""

    enabled: bool = True
    flush_interval_seconds: int = 60
    max_routing_buffer_age_seconds: int = 3600


class DharaStateBackend:
    """Durable state backend backed by Dhara.

    Wraps DharaClient with:
    - Degraded-boot mode: if Dhara is unreachable, writes are no-ops
    - Inline circuit breaker: 3 consecutive errors → open for 30 s
    - Fire-and-forget writes via asyncio.create_task
    """

    def __init__(self, base_url: str, config: DharaStateConfig | None = None) -> None:
        from mahavishnu.core.dhara_adapter import DharaClient

        self._client = DharaClient(base_url=base_url)
        self._config = config or DharaStateConfig()
        self._available = True
        self._consecutive_failures = 0
        self._circuit_open_until: float = 0.0

    @staticmethod
    def workflow_key(execution_id: str) -> str:
        """Return the canonical Dhara key for workflow execution state."""
        return f"workflow/v1/{execution_id}"

    @staticmethod
    def pool_key(pool_id: str) -> str:
        """Return the canonical Dhara key for pool state."""
        return f"pool/v1/{pool_id}"

    @staticmethod
    def routing_key(task_class: str, timestamp: datetime | None = None) -> str:
        """Return the canonical Dhara key for routing decision state."""
        when = timestamp or datetime.now(UTC)
        timestamp_ms = int(when.timestamp() * 1000)
        return f"routing/v1/{task_class}/{timestamp_ms}"

    @staticmethod
    def approval_key(request_id: str) -> str:
        """Return the canonical Dhara key for approval state."""
        return f"approval/v1/{request_id}"

    @property
    def available(self) -> bool:
        return self._available

    def _circuit_is_open(self) -> bool:
        import time
        if self._circuit_open_until > 0 and time.monotonic() < self._circuit_open_until:
            return True
        if self._circuit_open_until > 0:
            # Half-open: allow one probe
            self._circuit_open_until = 0.0
        return False

    def _record_failure(self) -> None:
        import time
        self._consecutive_failures += 1
        if self._consecutive_failures >= _DHARA_FAILURE_THRESHOLD:
            self._circuit_open_until = time.monotonic() + _DHARA_RECOVERY_SECONDS
            logger.warning(
                "Dhara state backend circuit open — persistence disabled for %ds",
                _DHARA_RECOVERY_SECONDS,
            )

    def _record_success(self) -> None:
        if self._consecutive_failures > 0:
            logger.info("Dhara state backend recovered — persistence re-enabled")
        self._consecutive_failures = 0
        self._available = True

    async def put(self, key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        """Persist key/value to Dhara. No-op when unavailable or circuit open."""
        if not self._config.enabled or self._circuit_is_open():
            return
        try:
            await self._client.put(key, value, ttl=ttl)
            self._record_success()
        except Exception as exc:
            self._record_failure()
            logger.debug("Dhara put(%r) failed: %s", key, exc)

    async def persist_workflow(
        self,
        execution_id: str,
        value: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        """Persist workflow execution state using the canonical key schema."""
        await self.put(self.workflow_key(execution_id), value, ttl=ttl)

    async def persist_pool(
        self,
        pool_id: str,
        value: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        """Persist pool state using the canonical key schema."""
        await self.put(self.pool_key(pool_id), value, ttl=ttl)

    async def persist_routing_decision(
        self,
        task_class: str,
        value: dict[str, Any],
        timestamp: datetime | None = None,
        ttl: int | None = None,
    ) -> None:
        """Persist a routing decision using the canonical key schema."""
        await self.put(self.routing_key(task_class, timestamp=timestamp), value, ttl=ttl)

    async def persist_approval(
        self,
        request_id: str,
        value: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        """Persist approval state using the canonical key schema."""
        await self.put(self.approval_key(request_id), value, ttl=ttl)

    async def recover_workflows(self) -> list[dict[str, Any]]:
        """Recover workflow execution state from Dhara."""
        entries = await self.list_prefix("workflow/v1/")
        return [value for _key, value in entries if isinstance(value, dict)]

    async def recover_pools(self) -> list[dict[str, Any]]:
        """Recover pool state from Dhara."""
        entries = await self.list_prefix("pool/v1/")
        return [value for _key, value in entries if isinstance(value, dict)]

    async def recover_routing_decisions(self) -> list[dict[str, Any]]:
        """Recover routing decisions from Dhara."""
        entries = await self.list_prefix("routing/v1/")
        return [value for _key, value in entries if isinstance(value, dict)]

    async def recover_approvals(self) -> list[dict[str, Any]]:
        """Recover approval state from Dhara."""
        entries = await self.list_prefix("approval/v1/")
        return [value for _key, value in entries if isinstance(value, dict)]

    async def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve a value from Dhara. Returns None when unavailable."""
        if not self._config.enabled or self._circuit_is_open():
            return None
        try:
            result = await self._client.call_tool("get", {"key": key})
            self._record_success()
            if isinstance(result, dict):
                return result
            return None
        except Exception as exc:
            self._record_failure()
            logger.debug("Dhara get(%r) failed: %s", key, exc)
            return None

    async def delete(self, key: str) -> None:
        """Delete a key from Dhara. No-op when unavailable."""
        if not self._config.enabled or self._circuit_is_open():
            return
        try:
            await self._client.call_tool("delete", {"key": key})
            self._record_success()
        except Exception as exc:
            self._record_failure()
            logger.debug("Dhara delete(%r) failed: %s", key, exc)

    async def list_prefix(self, prefix: str) -> list[tuple[str, dict[str, Any]]]:
        """List all keys under a prefix. Returns [] when unavailable."""
        if not self._config.enabled or self._circuit_is_open():
            return []
        try:
            result = await self._client.call_tool("list_prefix", {"prefix": prefix})
            self._record_success()
            if isinstance(result, list):
                return [(item["key"], item.get("value", {})) for item in result if "key" in item]
            return []
        except Exception as exc:
            self._record_failure()
            logger.debug("Dhara list_prefix(%r) failed: %s", prefix, exc)
            return []

    def schedule_put(self, key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        """Fire-and-forget put — does not block the event loop."""
        asyncio.create_task(self.put(key, value, ttl=ttl))

    def schedule_delete(self, key: str) -> None:
        """Fire-and-forget delete — does not block the event loop."""
        asyncio.create_task(self.delete(key))

    async def probe(self) -> bool:
        """Check if Dhara is reachable. Updates availability flag."""
        try:
            await self._client.call_tool("get", {"key": "__probe__"})
            self._available = True
            self._consecutive_failures = 0
            return True
        except Exception:
            self._available = False
            logger.warning("Dhara unavailable — state persistence disabled")
            return False

    async def aclose(self) -> None:
        """Release the underlying HTTP client."""
        await self._client.aclose()
