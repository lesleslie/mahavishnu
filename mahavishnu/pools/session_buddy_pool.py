"""Session-Buddy delegated pool management.

Each Session-Buddy instance manages 3 workers directly.

Phase 3 (REQ-004): rewired to ``mcp_common.clients.common_mcp_client.CommonMCPClient``.
The ``httpx2.AsyncClient`` POST path is replaced with ``CommonMCPClient.call_tool``
so all Bodai clients share the same streamable-HTTP transport.
"""

import logging
import time
from typing import Any

from mcp_common.clients.common_mcp_client import CommonMCPClient
from mcp_common.exceptions import MCPServerError

from .base import BasePool, PoolConfig, PoolMetrics, PoolStatus

logger = logging.getLogger(__name__)


async def _await_if_needed(value: Any) -> Any:
    """Await ``value`` if it is awaitable, otherwise return as-is.

    Kept for API compatibility with the test suite (see
    ``tests/unit/test_session_buddy_pool.py::TestAwaitIfNeeded`` and
    ``tests/unit/test_pool_manager.py::TestAwaitIfNeededHelper``).
    """
    if hasattr(value, "__await__"):
        return await value
    return value


def _extract_tool_payload(call_result: Any) -> Any:
    """Unwrap MCP CallToolResult to its payload.

    FastMCP wraps tool returns into ``CallToolResult(content=[TextContent(text=...)])``.
    For tools declared with ``-> dict[str, Any]`` (structured output), FastMCP
    sets ``structured_content`` to the dict directly. For tools declared with
    ``-> str``, ``content[0].text`` is the formatted string.

    For dict returns, callers get the dict directly. For string returns,
    callers get the string directly. Anything else passes through unchanged.
    """
    # mcp.types.CallToolResult has .structured_content (dict) and .content (list[TextContent])
    structured = getattr(call_result, "structured_content", None)
    if isinstance(structured, dict) and structured:
        return structured
    content = getattr(call_result, "content", None)
    if content and len(content) > 0:
        text = getattr(content[0], "text", None)
        if isinstance(text, str):
            # Try JSON-parse for tools that return JSON strings; fall back to raw text.
            import json
            try:
                parsed = json.loads(text)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except (ValueError, TypeError):
                pass
            return text
    return call_result


class SessionBuddyPool(BasePool):
    """Delegates worker management to Session-Buddy instance.

    Session-Buddy manages 3 workers directly.
    Mahavishnu communicates via MCP protocol.

    Use Cases:
    - Distributed worker management
    - Remote worker execution
    - Session-Buddy memory integration
    - Multi-server deployments

    Architecture:
    ┌─────────────────────────────────────┐
    │      SessionBuddyPool              │
    │  • CommonMCPClient                 │
    │  • worker_spawn (3 workers)        │
    │  • worker_execute                  │
    │  • worker_monitor                  │
    └─────────────────────────────────────┘
            │ HTTP (MCP streamable)
            ↓
    ┌───────────────────────┐
    │  Session-Buddy MCP    │
    │  (Port 8678)          │
    ├───────────────────────┤
    │  WorkerManager        │
    │  • 3 workers          │
    │  • Memory storage     │
    └───────────────────────┘
    """

    def __init__(
        self,
        config: PoolConfig,
        session_buddy_url: str = "http://localhost:8678/mcp",
        max_workers: int = 3,  # Session-Buddy manages 3 workers
    ):
        """Initialize SessionBuddyPool.

        Args:
            config: Pool configuration
            session_buddy_url: Session-Buddy MCP server URL
            max_workers: Fixed worker count (Session-Buddy manages 3)
        """
        super().__init__(config)
        self.session_buddy_url = session_buddy_url
        self.max_workers = max_workers
        self._mcp = CommonMCPClient(base_url=session_buddy_url, timeout=300.0)

        # Track task statistics
        self._tasks_completed = 0
        self._tasks_failed = 0
        self._task_durations: list[float] = []

    async def _call_mcp_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call session-buddy MCP tool and unwrap the CallToolResult envelope.

        Returns:
            Dictionary payload from the tool (for tools declared ``-> dict``),
            OR a string (for tools declared ``-> str``), OR any raw return value.
            Callers that expect ``dict`` semantics should check ``isinstance``.

        Raises:
            MCPServerError: If MCP call fails.
        """
        call_result = await self._mcp.call_tool(tool_name, arguments)
        payload = _extract_tool_payload(call_result)
        if isinstance(payload, dict):
            return payload
        # Non-dict payloads (strings, lists): wrap so callers that
        # read ``.get("result", ...)`` keep working without crashing.
        return {"result": payload}

    async def start(self) -> str:
        """Initialize Session-Buddy pool by creating a remote pool via MCP.

        Calls session-buddy's ``create_pool`` tool. The response is a structured
        dict: ``{"success": True, "pool_id": "abc", "status": "running",
        "workers_count": 3, "queue_size": 0, ...}``. We extract ``pool_id`` and
        synthesize 3 worker_ids as ``{pool_id}-worker-{i}`` for downstream
        caller compatibility.

        Returns:
            pool_id: Unique Mahavishnu-side pool identifier.
        """
        self._status = PoolStatus.INITIALIZING

        try:
            result = await self._call_mcp_tool("create_pool", {})

            if not result.get("success", False):
                error_msg = result.get("error", "create_pool returned success=False")
                raise MCPServerError(error_msg)

            pool_id = result.get("pool_id", "")
            if not isinstance(pool_id, str) or not pool_id:
                pool_id = ""

            self._workers = {
                f"{pool_id}-worker-{i}": f"worker_{i}"
                for i in range(self.max_workers)
            } if pool_id else {}
            self._status = PoolStatus.RUNNING

            logger.info(
                f"SessionBuddyPool {self.pool_id} started with "
                f"{len(self._workers)} workers (pool_id={pool_id!r} via "
                f"{self.session_buddy_url})"
            )

        except MCPServerError as e:
            logger.error(f"Failed to start SessionBuddyPool: {e}")
            self._status = PoolStatus.FAILED
            raise

        return self.pool_id

    async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        """Execute task via session-buddy's ``execute_on_pool`` MCP tool.

        session-buddy response shape:
        ``{"success": True, "pool_id", "worker_id", "result": {...}}``.
        Failure shape: ``{"success": False, "pool_id", "error": str}``.

        Args:
            task: Task specification with ``prompt``, optional ``timeout``,
                optional ``working_dir`` (triggers ``subagent_marker``
                mark/clear).

        Returns:
            Envelope ``{pool_id, worker_id, status, output, error, duration}``.
        """
        if not self._workers:
            raise RuntimeError("No workers available in pool")

        worker_id = next(iter(self._workers.keys()))
        pool_id = worker_id.rsplit("-worker-", 1)[0] if worker_id else ""
        working_dir = task.get("working_dir")

        if working_dir:
            await self._call_mcp_tool(
                "subagent_marker",
                {"working_dir": working_dir, "action": "mark"},
            )

        start_time = time.time()
        try:
            result = await self._call_mcp_tool(
                "execute_on_pool",
                {
                    "pool_id": pool_id,
                    "prompt": task.get("prompt", ""),
                    "timeout": task.get("timeout", 300),
                },
            )

            duration = time.time() - start_time

            # Structured response handling.
            if result.get("success"):
                self._tasks_completed += 1
                status_value = "completed"
                output = result.get("result")
                error = None
            else:
                self._tasks_failed += 1
                status_value = "failed"
                output = None
                error = result.get("error", "execute_on_pool returned success=False")
            self._task_durations.append(duration)

            # session-buddy's actual worker_id is more authoritative than our
            # synthetic prefix; prefer it when present.
            actual_worker_id = result.get("worker_id") or worker_id

            return {
                "pool_id": self.pool_id,
                "worker_id": actual_worker_id,
                "status": status_value,
                "output": output,
                "error": error,
                "duration": duration,
            }

        except MCPServerError as e:
            logger.error(f"Failed to execute task on SessionBuddyPool: {e}")
            self._tasks_failed += 1
            return {
                "pool_id": self.pool_id,
                "worker_id": worker_id,
                "status": "failed",
                "output": None,
                "error": str(e),
                "duration": time.time() - start_time,
            }
        finally:
            if working_dir:
                try:
                    await self._call_mcp_tool(
                        "subagent_marker",
                        {"working_dir": working_dir, "action": "clear"},
                    )
                except Exception:
                    logger.exception(
                        "subagent_marker clear failed for %s; consumer "
                        "may see a stale lockfile until the next mark",
                        working_dir,
                    )

    async def execute_batch(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        """Execute tasks via session-buddy's ``execute_batch_on_pool``.

        session-buddy response shape (after Task 0b):
        ``{"success": True, "pool_id", "results_count", "results":
        [{"status": "completed"|"failed", "output": ..., "error": ...}, ...]}``.

        Args:
            tasks: List of task specifications. Each MAY carry ``working_dir``.

        Raises:
            ValueError: If tasks contain more than one distinct ``working_dir``
                (the underlying MCP tool accepts only one shared context).
                Callers should split batches by working_dir beforehand.

        Returns:
            Dictionary mapping task_id -> result envelope.
        """
        if not self._workers:
            raise RuntimeError("No workers available in pool")

        worker_id = next(iter(self._workers.keys()))
        pool_id = worker_id.rsplit("-worker-", 1)[0] if worker_id else ""

        # Collect the working_dirs to mark; preserve order while
        # de-duplicating. Fail fast on multiple distinct dirs — the
        # underlying MCP tool accepts only ONE shared context, so we
        # can't preserve per-task working_dir semantics.
        working_dirs: list[str] = []
        seen: set[str] = set()
        for task in tasks:
            wd = task.get("working_dir")
            if wd and wd not in seen:
                seen.add(wd)
                working_dirs.append(wd)

        if len(working_dirs) > 1:
            raise ValueError(
                f"execute_batch supports at most one distinct working_dir "
                f"per batch; got {len(working_dirs)}: {working_dirs}. "
                f"Split the batch by working_dir before calling."
            )

        # Wrap mark loop in its own try/finally so partial mark failure
        # doesn't leak earlier marks (defense against MCPServerError on Nth dir).
        if working_dirs:
            await self._call_mcp_tool(
                "subagent_marker",
                {"working_dir": working_dirs[0], "action": "mark"},
            )

        try:
            # Extract prompts; share the (at most one) working_dir as context.
            prompts = [task.get("prompt", "") for task in tasks]
            context: dict[str, Any] = {}
            if working_dirs:
                context["working_dir"] = working_dirs[0]

            start_time = time.time()
            result = await self._call_mcp_tool(
                "execute_batch_on_pool",
                {
                    "pool_id": pool_id,
                    "prompts": prompts,
                    "context": context,
                },
            )

            duration = time.time() - start_time

            # Structured response handling.
            if not result.get("success"):
                error_msg = result.get("error", "execute_batch_on_pool returned success=False")
                self._tasks_failed += len(tasks)
                raise MCPServerError(error_msg)

            # session-buddy returns results in input order; align by index.
            batch_results = result.get("results", [])
            if not isinstance(batch_results, list):
                batch_results = []

            # Track statistics from per-task status.
            for entry in batch_results:
                status_value = (
                    entry.get("status", "unknown") if isinstance(entry, dict) else "unknown"
                )
                if status_value == "completed":
                    self._tasks_completed += 1
                else:
                    self._tasks_failed += 1
            self._task_durations.append(duration / max(len(tasks), 1))

            # Stitch results back into task_id-keyed envelopes.
            task_results: dict[str, Any] = {}
            for idx, task in enumerate(tasks):
                entry = batch_results[idx] if idx < len(batch_results) else {}
                entry = entry if isinstance(entry, dict) else {}
                task_id = task.get("task_id") or str(idx)
                task_results[task_id] = {
                    "pool_id": self.pool_id,
                    "worker_id": worker_id,
                    "status": entry.get("status", "unknown"),
                    "output": entry.get("output"),
                    "error": entry.get("error"),
                }

            logger.info(
                f"SessionBuddyPool {self.pool_id} executed {len(tasks)} tasks "
                f"in {duration:.2f}s"
            )

            return task_results

        except MCPServerError as e:
            logger.error(f"Failed to execute batch on SessionBuddyPool: {e}")
            self._tasks_failed += len(tasks)
            # Error envelope MUST include "output": None for shape parity
            # with the success path (audit BUG: missing field caused KeyError
            # in downstream PoolManager consumers).
            return {
                task.get("task_id") or str(idx): {
                    "pool_id": self.pool_id,
                    "worker_id": worker_id,
                    "status": "failed",
                    "output": None,
                    "error": str(e),
                }
                for idx, task in enumerate(tasks)
            }
        finally:
            if working_dirs:
                try:
                    await self._call_mcp_tool(
                        "subagent_marker",
                        {"working_dir": working_dirs[0], "action": "clear"},
                    )
                except Exception:
                    logger.exception(
                        "subagent_marker clear failed for %s; consumer "
                        "may see a stale lockfile until the next mark",
                        working_dirs[0],
                    )

    async def scale(self, target_worker_count: int) -> None:
        """Scale not supported (fixed at 3 workers).

        Args:
            target_worker_count: Desired worker count

        Raises:
            NotImplementedError: Always - SessionBuddyPool has fixed worker count
        """
        raise NotImplementedError(
            "SessionBuddyPool has fixed worker count (3). Spawn additional pools for more capacity."
        )

    async def health_check(self) -> dict[str, Any]:
        """Check pool health via session-buddy's ``check_pool_health``.

        When the pool failed to start (``self._workers`` is empty), skip the
        upstream call and return a local "unhealthy" marker instead of leaking
        session-buddy's global pool-manager health response.

        Returns:
            Health status dictionary.
        """
        worker_id = next(iter(self._workers.keys()), "")
        pool_id = worker_id.rsplit("-worker-", 1)[0] if worker_id else ""

        # Local computation independent of upstream.
        if len(self._workers) == 0:
            pool_status = "unhealthy"
        elif len(self._workers) < self.config.min_workers:
            pool_status = "degraded"
        else:
            pool_status = "healthy"

        # Skip upstream when we have no pool_id — session-buddy's
        # ``check_pool_health(pool_id=None)`` returns global health which
        # would be misleading.
        if not pool_id:
            return {
                "pool_id": self.pool_id,
                "pool_type": "session-buddy",
                "status": pool_status,
                "workers_active": len(self._workers),
                "max_workers": self.max_workers,
                "worker_health": None,
                "tasks_completed": self._tasks_completed,
                "tasks_failed": self._tasks_failed,
                "session_buddy_url": self.session_buddy_url,
            }

        try:
            result = await self._call_mcp_tool(
                "check_pool_health",
                {"pool_id": pool_id},
            )
            # Local status wins; upstream provides supplementary worker_health.
            worker_health = result if result.get("success") else None
            if not result.get("success"):
                pool_status = "degraded" if self._workers else "unhealthy"

            return {
                "pool_id": self.pool_id,
                "pool_type": "session-buddy",
                "status": pool_status,
                "workers_active": len(self._workers),
                "max_workers": self.max_workers,
                "worker_health": worker_health,
                "tasks_completed": self._tasks_completed,
                "tasks_failed": self._tasks_failed,
                "session_buddy_url": self.session_buddy_url,
            }

        except MCPServerError as e:
            logger.error(f"Failed health check for SessionBuddyPool: {e}")
            return {
                "pool_id": self.pool_id,
                "pool_type": "session-buddy",
                "status": pool_status,
                "workers_active": len(self._workers),
                "max_workers": self.max_workers,
                "worker_health": None,
                "tasks_completed": self._tasks_completed,
                "tasks_failed": self._tasks_failed,
                "error": str(e),
                "session_buddy_url": self.session_buddy_url,
            }

    async def get_metrics(self) -> PoolMetrics:
        """Get metrics from Session-Buddy.

        Returns:
            PoolMetrics with current stats
        """
        await self.health_check()

        # Calculate average task duration
        avg_duration = (
            sum(self._task_durations) / len(self._task_durations) if self._task_durations else 0.0
        )

        return PoolMetrics(
            pool_id=self.pool_id,
            status=self._status,
            active_workers=len(self._workers),
            total_workers=self.max_workers,
            tasks_completed=self._tasks_completed,
            tasks_failed=self._tasks_failed,
            avg_task_duration=avg_duration,
            memory_usage_mb=0.0,
        )

    async def collect_memory(self) -> list[dict[str, Any]]:
        """Collect memory from Session-Buddy.

        Returns:
            List of memory dictionaries
        """
        try:
            # Query Session-Buddy for recent worker executions
            result = await self._call_mcp_tool(
                "search_conversations",
                {
                    "query": f"pool_id:{self.pool_id}",
                    "limit": 100,
                },
            )

            conversations = result.get("result", {}).get("conversations", [])

            logger.info(
                f"Collected {len(conversations)} memory items from SessionBuddyPool {self.pool_id}"
            )

            return conversations  # type: ignore[no-any-return]

        except MCPServerError as e:
            logger.error(f"Failed to collect memory from SessionBuddyPool: {e}")
            return []

    async def stop(self) -> None:
        """Shutdown pool by deleting the remote session-buddy pool via MCP.

        Calls session-buddy's ``delete_pool`` tool which removes the underlying
        3-worker ``WorkerPool`` and stops its asyncio workers.

        The underlying ``CommonMCPClient`` (and its httpx2 transport) is
        always closed via the ``finally`` block — every code path through
        ``stop`` (success / no-pool-id early-return / failure) must release
        the MCP client's connection pool before returning.

        Raises:
            MCPServerError: If the upstream delete call fails after retries.
        """
        try:
            worker_id = next(iter(self._workers.keys()), "")
            pool_id = worker_id.rsplit("-worker-", 1)[0] if worker_id else ""
            if not pool_id:
                logger.warning(
                    f"SessionBuddyPool {self.pool_id} has no remote pool_id; "
                    f"skipping delete_pool call"
                )
                self._workers.clear()
                self._status = PoolStatus.STOPPED
                return

            try:
                await self._call_mcp_tool(
                    "delete_pool", {"pool_id": pool_id, "timeout": 5.0}
                )
                self._workers.clear()
                self._status = PoolStatus.STOPPED
                logger.info(
                    f"SessionBuddyPool {self.pool_id} stopped (pool_id={pool_id})"
                )
            except MCPServerError as e:
                logger.error(f"Failed to stop SessionBuddyPool {self.pool_id}: {e}")
                # Local cleanup happens regardless so the Mahavishnu-side
                # pool can be reaped; upstream residue is operator-visible
                # via session-buddy's own pool list.
                self._workers.clear()
                self._status = PoolStatus.FAILED
                raise
        finally:
            await self._mcp.aclose()


# Registry integration: SessionBuddyPool reads session_buddy_url from config.get()
# (matching the original manager dispatch). It does not need terminal_manager or
# session_buddy_client kwargs — they are ignored if forwarded.
def _build_session_buddy_pool(
    config: PoolConfig,
    **_unused_kwargs: Any,
) -> SessionBuddyPool:
    return SessionBuddyPool(
        config=config,
        session_buddy_url=config.get("session_buddy_url", "http://localhost:8678/mcp"),
    )


from ._registry import register_pool_type

register_pool_type("session-buddy", _build_session_buddy_pool)
