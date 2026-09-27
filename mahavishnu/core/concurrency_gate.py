"""Per-TaskCategory concurrency counter (C-9).

LIMITATION: per-process scope. With N workers, the effective limit is
N x spec.concurrency_limit across N workers in N separate processes.
Documented in ``docs/runbooks/concurrency-limit-storm.md``.

Fix path: replace with a Redis / Dhara-backed shared counter when
cross-pool guarantees are required. Out of scope for C-9.

REQ-012: ConcurrencyGate per-TaskCategory with shard locks by (category, pool_id).
REQ-013: Token-bucket rate limiting with fail-closed default.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

from cachetools import LRUCache
from oneiric.core.logging import get_logger

if TYPE_CHECKING:
    from mahavishnu.core.config import ConcurrencyLimitSpec, ConcurrencyLimitsSettings
    from mahavishnu.core.model_routing import TaskCategory


logger = get_logger(__name__)


class ConcurrencyGate:
    """Per-TaskCategory concurrency counter.

    Thread-safety: shard locks keyed by (category, pool_id) prevent
    races within a single process. Cross-process / cross-worker
    races are NOT prevented — see module docstring LIMITATION.

    Specs without a ``concurrency_limit`` (``None``) are pass-through:
    the gate grants every request regardless of count. Specs with
    ``global_override=True`` use a single shared counter regardless of
    ``pool_id``.
    """

    def __init__(self, settings: ConcurrencyLimitsSettings) -> None:
        self._specs: dict[TaskCategory, ConcurrencyLimitSpec] = settings.by_category
        self._counters: dict[tuple[TaskCategory, str | None], int] = defaultdict(int)
        # LRUCache bounds shard lock memory. 1024 entries is enough for
        # any realistic (category, pool_id) combination without unbounded
        # growth in long-running processes.
        self._shard_locks: LRUCache = LRUCache(maxsize=1024)

    async def try_acquire(
        self, category: TaskCategory, pool_id: str | None
    ) -> bool:
        """Try to acquire a concurrency slot. Returns True if granted."""
        spec = self.spec_for(category)
        if spec is None or spec.concurrency_limit is None:
            return True
        key = self._key_for(category, pool_id, spec)
        lock = self._shard_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._shard_locks[key] = lock
        async with lock:
            if self._counters[key] >= spec.concurrency_limit:
                return False
            self._counters[key] += 1
            return True

    async def release(self, category: TaskCategory, pool_id: str | None) -> None:
        """Release a previously-acquired concurrency slot.

        Clamps to zero so a buggy double-release cannot drive the
        counter negative and grant phantom slots.
        """
        spec = self.spec_for(category)
        if spec is None:
            return
        key = self._key_for(category, pool_id, spec)
        lock = self._shard_locks.get(key)
        if lock is None:
            return
        async with lock:
            self._counters[key] = max(0, self._counters[key] - 1)

    def spec_for(self, category: TaskCategory) -> ConcurrencyLimitSpec | None:
        """Public accessor — replaces direct ``_specs`` access."""
        return self._specs.get(category)

    @staticmethod
    def _key_for(
        category: TaskCategory,
        pool_id: str | None,
        spec: ConcurrencyLimitSpec,
    ) -> tuple[TaskCategory, str | None]:
        """Build the shard key — global_override=True collapses pool_id to None."""
        return (category, None if spec.global_override else pool_id)


__all__ = ["ConcurrencyGate"]