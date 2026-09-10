"""PeriodicTaskRunner — asyncio loop hosting the plan_index_rebuild task.

NOT in fitness_analyzer.py (that's an OTel trace-tag filter, not a
periodic-task registry).

Per-task lock with stale-PID detection. Per-task DLQ for Dhara write
failures. Hostname is hashed (not raw) for the lock key.

The cycle itself lives in cron_core.run_rebuild_cycle — kept separate so
the cycle is unit-testable without asyncio.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import socket
from typing import TYPE_CHECKING

from mahavishnu.plan_index.cron_core import RebuildOutcome, run_rebuild_cycle
from mahavishnu.plan_index.rebuild import PlanIndexRebuilder

if TYPE_CHECKING:
    from pathlib import Path

    from mahavishnu.plan_index.store import PlanIndexStore


__all__ = ["PeriodicTaskRunner"]

LOCK_KEY = "plan_index/meta/rebuild_lock/{holder}"
LOCK_TTL_SECONDS = 60
CRON_DEFAULT_SECONDS = 3600
ENTITIES_COUNT_KEY = "plan_index/meta/entities_count"
CYCLES_TOTAL_KEY = "plan_index/meta/cycles_total"
SUCCESS_CYCLES_KEY = "plan_index/meta/successful_cycles_total"
ERRORS_TOTAL_KEY = "plan_index/meta/errors_total"
LAST_REBUILD_MS_KEY = "plan_index/meta/last_rebuild_ms"
LAST_SUCCESS_MS_KEY = "plan_index/meta/last_success_ms"
RECENT_ERRORS_KEY = "plan_index/meta/recent_errors"


def _hostname_hash() -> str:
    """Hash socket.gethostname() to 8 hex chars (FQDN-safe)."""
    return hashlib.sha256(socket.gethostname().encode()).hexdigest()[:8]


def _lock_holder() -> str:
    return f"{_hostname_hash()}/{os.getpid()}"


class PeriodicTaskRunner:
    """Asyncio loop that runs the rebuild at cron_every_seconds interval."""

    def __init__(
        self,
        *,
        store: PlanIndexStore,
        rebuilder: PlanIndexRebuilder | None = None,
        cron_every_seconds: int = CRON_DEFAULT_SECONDS,
        repo_root: Path | None = None,
    ) -> None:
        self._store = store
        self._rebuilder = rebuilder or PlanIndexRebuilder()
        self._cron_every_seconds = cron_every_seconds
        self._repo_root = repo_root
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task
            self._task = None

    async def force_run(self) -> RebuildOutcome:
        """Run a rebuild cycle synchronously. Caller awaits completion."""
        return await run_rebuild_cycle(
            self._store,
            self._rebuilder,
            repo_root=self._repo_root,
        )

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            await self.force_run()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._cron_every_seconds
                )
            except TimeoutError:
                pass  # Time to run again
