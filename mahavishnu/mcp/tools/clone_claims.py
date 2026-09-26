"""Cluster-claim helpers for clone_refactor_group.

Single-process dedup via dict[str, asyncio.Lock]. Cross-process dedup is
deferred (out of scope per spec §3 Non-Goals; MCPStateBackend.put() is not CAS).

Implements: REQ-CLONE-009
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mahavishnu.core.state_backends.mcp import MCPStateBackend

logger = logging.getLogger(__name__)


class ConcurrentDAGError(Exception):
    """Raised by cluster_state_claim when another DAG holds the claim.

    Implements: REQ-CLONE-009
    """

    def __init__(self, existing_job_id: str) -> None:
        super().__init__(f"cluster_id already has in-flight DAG {existing_job_id}")
        self.existing_job_id = existing_job_id


# TD-m9: MCPStateBackendUnavailable is defined in state_backends/mcp.py
# (alongside its peer MCPStateBackendError). Re-exported here for backward
# compat with Task 6's import path.
from mahavishnu.core.state_backends.mcp import MCPStateBackendUnavailable

# In-process locks keyed by cluster_id. Cross-process dedup is out of scope
# (MCPStateBackend.put() is not CAS — see spec §3 Non-Goals + §6.4 v4 MAJOR-fix M4).
_cluster_locks: dict[str, asyncio.Lock] = {}


def _get_cluster_lock(cluster_id: str) -> asyncio.Lock:
    if cluster_id not in _cluster_locks:
        _cluster_locks[cluster_id] = asyncio.Lock()
    return _cluster_locks[cluster_id]


async def cluster_state_claim(
    mcp_backend: MCPStateBackend,
    cluster_id: str,
    refactor_job_id: str,
) -> None:
    """Acquire cluster-claim. Returns on success.

    TD-m6: return type is `None` (was `-> bool`). Every non-success path
    raises; the only `return True` paths were dead-code. Callers in
    `clone_tools.py` already discard the return value.

    Raises:
        ConcurrentDAGError: another DAG holds the claim with a different
            refactor_job_id.
        MCPStateBackendUnavailable: substrate is unreachable. SF-B6 fails
            loud rather than silently letting two cross-process DAGs race.

    Implements: REQ-CLONE-009
    """
    # SF-B6: fail loud if the substrate circuit is open. Two cross-process
    # DAGs both calling put() would each silently fail and each return True.
    if mcp_backend._circuit_is_open():
        raise MCPStateBackendUnavailable(
            key=mcp_backend.in_flight_key(cluster_id),
            reason="circuit_open",
        )

    lock = _get_cluster_lock(cluster_id)
    async with lock:
        sentinel_key = mcp_backend.in_flight_key(cluster_id)
        existing = await mcp_backend.get(sentinel_key)
        if existing is not None:
            existing_job_id = existing.get("refactor_job_id") if existing else None
            # SF-M4: missing/None refactor_job_id (corrupt/legacy sentinel) is
            # treated as unowned — overwrite rather than raise with None.
            if existing_job_id is None:
                logger.warning("cluster_claim: stale sentinel at %s, overwriting", sentinel_key)
            elif existing_job_id == refactor_job_id:
                # Idempotent: same caller re-claiming their own job
                return
            else:
                raise ConcurrentDAGError(existing_job_id=existing_job_id)
        await mcp_backend.put(
            sentinel_key,
            {"refactor_job_id": refactor_job_id, "claimed_at": asyncio.get_event_loop().time()},
        )


async def release_cluster_claim(
    mcp_backend: MCPStateBackend,
    cluster_id: str,
) -> None:
    """Release the cluster-claim by deleting the sentinel.

    Idempotent: does not raise if the sentinel didn't exist or delete fails.
    SF-B3/SF-M6: a release failure must never shadow the calling @flow's
    original exception.
    """
    sentinel_key = mcp_backend.in_flight_key(cluster_id)
    try:
        await mcp_backend.delete(sentinel_key)
    except Exception as exc:  # noqa: BLE001 - release is best-effort
        logger.warning(
            "release_cluster_claim: delete failed for %s (%s); continuing",
            sentinel_key,
            exc,
        )
