"""MCP-backed durable state persistence for Mahavishnu.

Provides a thin coordination layer over MCPClient that implements
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

_MCP_FAILURE_THRESHOLD = 3
_MCP_RECOVERY_SECONDS = 30.0

# SF-M2: reserved LogRecord attrs that would collide with logger.warning(extra=...)
_RESERVED_LOGRECORD_ATTRS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname",
    "filename", "module", "exc_info", "exc_text", "stack_info",
    "lineno", "funcName", "created", "msecs", "relativeCreated",
    "thread", "threadName", "processName", "process", "message",
    "asctime", "key",  # 'key' is reserved in some impls; keep for safety
})


def _safe_extra(ctx: dict[str, Any] | None) -> dict[str, Any]:
    """Filter log_context against reserved LogRecord attrs.

    Implements: REQ-CLONE-014 (SF-M2 hardening)
    """
    if not ctx:
        return {}
    return {k: v for k, v in ctx.items() if k not in _RESERVED_LOGRECORD_ATTRS}


@dataclass
class MCPStateConfig:
    """Configuration for MCP state persistence."""

    enabled: bool = True
    flush_interval_seconds: int = 60
    max_routing_buffer_age_seconds: int = 3600


class MCPStateBackend:
    """Durable state backend backed by MCP.

    Wraps MCPClient with:
    - Degraded-boot mode: if MCP is unreachable, writes are no-ops
    - Inline circuit breaker: 3 consecutive errors → open for 30 s
    - Fire-and-forget writes via asyncio.create_task
    """

    def __init__(self, base_url: str, config: MCPStateConfig | None = None) -> None:
        from mahavishnu.core.mcp_adapter import MCPClient

        self._client = MCPClient(base_url=base_url)
        self._config = config or MCPStateConfig()
        self._available = True
        self._consecutive_failures = 0
        self._circuit_open_until: float = 0.0

    @staticmethod
    def workflow_key(execution_id: str) -> str:
        """Return the canonical MCP key for workflow execution state."""
        return f"workflow/v1/{execution_id}"

    @staticmethod
    def pool_key(pool_id: str) -> str:
        """Return the canonical MCP key for pool state."""
        return f"pool/v1/{pool_id}"

    @staticmethod
    def routing_key(task_class: str, timestamp: datetime | None = None) -> str:
        """Return the canonical MCP key for routing decision state."""
        when = timestamp or datetime.now(UTC)
        timestamp_ms = int(when.timestamp() * 1000)
        return f"routing/v1/{task_class}/{timestamp_ms}"

    @staticmethod
    def approval_key(request_id: str) -> str:
        """Return the canonical MCP key for approval state."""
        return f"approval/v1/{request_id}"

    @staticmethod
    def dag_key(refactor_job_id: str) -> str:
        """Return the canonical MCP key for clone-refactor DAG lifecycle records.

        Implements: REQ-CLONE-007
        Distinct from workflow_key() because semantic intent differs
        (DAG lifecycle vs. workflow execution).
        """
        return f"workflow/v1/{refactor_job_id}"

    @staticmethod
    def cluster_key(cluster_id: str) -> str:
        """Return the canonical MCP key for per-cluster consumer-progress records.

        Implements: REQ-CLONE-009 (claim sentinel sits in cluster/v1/{id}/in_flight,
        a different key from this consumer-progress record).
        """
        return f"cluster/v1/{cluster_id}"

    @staticmethod
    def in_flight_key(cluster_id: str) -> str:
        """Return the canonical MCP key for the cluster-claim sentinel.

        Implements: REQ-CLONE-009
        Distinct from cluster_key() — the claim sentinel and consumer-progress
        are two different concerns under the same prefix.
        """
        return f"cluster/v1/{cluster_id}/in_flight"

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
        if self._consecutive_failures >= _MCP_FAILURE_THRESHOLD:
            self._circuit_open_until = time.monotonic() + _MCP_RECOVERY_SECONDS
            logger.warning(
                "MCP state backend circuit open — persistence disabled for %ds",
                _MCP_RECOVERY_SECONDS,
            )

    def _record_success(self) -> None:
        if self._consecutive_failures > 0:
            logger.info("MCP state backend recovered — persistence re-enabled")
        self._consecutive_failures = 0
        self._available = True

    async def put(self, key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        """Persist key/value to MCP. No-op when unavailable or circuit open."""
        if not self._config.enabled or self._circuit_is_open():
            return
        try:
            await self._client.put(key, value, ttl=ttl)
            self._record_success()
        except Exception as exc:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            self._record_failure()
            logger.debug("MCP put(%r) failed: %s", key, exc)

    async def try_put_with_log_context(
        self,
        key: str,
        value: dict[str, Any],
        *,
        log_context: dict[str, Any] | None = None,
    ) -> bool:
        """Persist key/value with structured-log context on failure.

        Returns True on success, False if the substrate is unavailable
        or circuit-open. NEVER raises — substrate failures are logged
        with the caller's log_context so the audit trail is intact.

        Implements: REQ-CLONE-014
        Used by the clone-refactor DAG so the structured
        `clone_refactor.substrate_silent_write` log always carries
        `dag_id, step_name, files_touched`.

        SF-M1 hardening: _record_failure() is wrapped in its own try/except
        so a metrics-sink failure cannot suppress the structured log line.
        SF-M2 hardening: log_context is filtered against the LogRecord
        reserved-attribute set so caller-supplied keys like {"message": "x"}
        do not raise KeyError/AttributeError out of logger.warning().
        CR-m1: _record_failure failures are logged at WARNING (not DEBUG)
        per CLAUDE.md style — operators running at INFO must see this.
        """
        try:
            if not self._config.enabled or self._circuit_is_open():
                try:
                    logger.warning(
                        "clone_refactor.substrate_silent_write",
                        extra={"key": key, **_safe_extra(log_context)},
                    )
                except Exception:  # noqa: BLE001 - SF-m2: NEVER raises
                    pass
                return False
            await self._client.put(key, value, ttl=None)
            self._record_success()
            return True
        except Exception as exc:  # noqa: BLE001 - boundary handler
            # SF-M1 + CR-m1: wrap _record_failure() in try/except so a
            # metrics-sink failure cannot suppress the structured log
            # line. Log the _record_failure failure at WARNING (not DEBUG)
            # per CLAUDE.md style.
            try:
                self._record_failure()
            except Exception as record_exc:  # noqa: BLE001
                try:
                    logger.warning(
                        "MCPStateBackend._record_failure failed; continuing",
                        exc_info=record_exc,
                    )
                except Exception:  # noqa: BLE001 - SF-m2: NEVER raises
                    pass
            try:
                logger.warning(
                    "clone_refactor.substrate_silent_write",
                    extra={
                        "key": key,
                        "substrate_error": str(exc),
                        **_safe_extra(log_context),
                    },
                )
            except Exception:  # noqa: BLE001 - SF-m2: NEVER raises
                pass
            return False

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
        """Recover workflow execution state from MCP."""
        entries = await self.list_prefix("workflow/v1/")
        return [value for _key, value in entries if isinstance(value, dict)]

    async def recover_pools(self) -> list[dict[str, Any]]:
        """Recover pool state from MCP."""
        entries = await self.list_prefix("pool/v1/")
        return [value for _key, value in entries if isinstance(value, dict)]

    async def recover_routing_decisions(self) -> list[dict[str, Any]]:
        """Recover routing decisions from MCP."""
        entries = await self.list_prefix("routing/v1/")
        return [value for _key, value in entries if isinstance(value, dict)]

    async def recover_approvals(self) -> list[dict[str, Any]]:
        """Recover approval state from MCP."""
        entries = await self.list_prefix("approval/v1/")
        return [value for _key, value in entries if isinstance(value, dict)]

    async def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve a value from MCP. Returns None when unavailable."""
        if not self._config.enabled or self._circuit_is_open():
            return None
        try:
            result = await self._client.call_tool("get", {"key": key})
            self._record_success()
            if isinstance(result, dict):
                return result
            return None
        except Exception as exc:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            self._record_failure()
            logger.debug("MCP get(%r) failed: %s", key, exc)
            return None

    async def delete(self, key: str) -> None:
        """Delete a key from MCP. No-op when unavailable."""
        if not self._config.enabled or self._circuit_is_open():
            return
        try:
            await self._client.call_tool("delete", {"key": key})
            self._record_success()
        except Exception as exc:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            self._record_failure()
            logger.debug("MCP delete(%r) failed: %s", key, exc)

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
        except Exception as exc:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            self._record_failure()
            logger.debug("MCP list_prefix(%r) failed: %s", prefix, exc)
            return []

    def schedule_put(self, key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        """Fire-and-forget put — does not block the event loop."""
        asyncio.create_task(self.put(key, value, ttl=ttl))

    def schedule_delete(self, key: str) -> None:
        """Fire-and-forget delete — does not block the event loop."""
        asyncio.create_task(self.delete(key))

    async def probe(self) -> bool:
        """Check if MCP is reachable. Updates availability flag."""
        try:
            await self._client.call_tool("get", {"key": "__probe__"})
            self._available = True
            self._consecutive_failures = 0
            return True
        except Exception:  # noqa: BLE001 - boundary handler catches all errors to keep calling code alive
            self._available = False
            logger.warning("MCP unavailable — state persistence disabled")
            return False

    async def aclose(self) -> None:
        """Release the underlying HTTP client."""
        await self._client.aclose()


class MCPStateBackendError(Exception):
    """Raised by MCPStateBackend when the substrate is unavailable AND the caller
    has opted into explicit-failure semantics.

    The default put() still swallows (preserves existing callers' no-throw
    contract); only callers using try_put_with_log_context and explicitly
    raising this class opt into the failure mode. See §6.4 of the spec.

    Implements: REQ-CLONE-014
    """

    def __init__(
        self,
        key: str,
        reason: str,
        *,
        log_context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"MCPStateBackend put({key!r}) failed: {reason}")
        self.key = key
        self.reason = reason
        self.log_context = log_context or {}


# TD-m9: MCPStateBackendUnavailable is defined here (next to its peer
# MCPStateBackendError) for architectural consistency. Re-exported from
# clone_claims.py for the wire-up code path.
class MCPStateBackendUnavailable(Exception):
    """Raised when the substrate is unreachable AND the caller has opted into
    fail-loud semantics.

    SF-B6: cluster_state_claim raises this when the circuit is open, rather
    than silently returning True (which would allow two cross-process DAGs to
    race for the same cluster claim).

    Implements: REQ-CLONE-014
    """

    def __init__(self, key: str, reason: str) -> None:
        super().__init__(f"MCPStateBackend unavailable: {key} ({reason})")
        self.key = key
        self.reason = reason
