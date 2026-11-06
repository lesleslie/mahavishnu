"""The server's process-local key/value store.

Owns the single store that backs both:

* the ``mahavishnu_kv_*`` MCP tools (``mahavishnu/mcp/tools/kv_tools.py``),
  which expose it to sibling Bodai components; and
* the substrate facade (``mahavishnu/core/substrate.py``), which the
  server's own producers — the ecosystem registry, the workflow outcome
  log, the approval decision log, the webhook ingress log — write through.

The store lives in ``core/`` rather than ``mcp/tools/`` because ``core``
must not import from ``mcp``: the dependency already runs the other way
(``mcp.tools.kv_tools`` imports ``mahavishnu.core.permissions``). Keeping
one instance here means the producers and the public tools read and write
the same data.

Values are **strings** — that is the KV contract the ``mahavishnu_kv_*``
tools expose. Callers that store structured payloads JSON-encode them
first; :mod:`mahavishnu.core.substrate` does that on their behalf.

Entries may carry a **TTL** (in **seconds**). A TTL is recorded per
entry and enforced on every read path: an expired entry reads as
absent, does not appear in a listing, and is not counted.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class ProcessLocalKV:
    """Thread-safe string-shape KV for the server's own substrate.

    The MCP server is single-process; multiple concurrent tool calls run
    in the same event loop. A plain ``dict`` is safe under CPython's GIL
    for individual operations, but a ``threading.Lock`` makes the
    read-modify-write patterns in :meth:`list_prefix` race-free. The lock
    is held only across the in-memory mutation, not across any await, so
    it never blocks the event loop.

    **Expiry is lazy.** There is no background sweeper thread: an entry
    stops being visible the instant its deadline passes (every read
    path checks the deadline), and the record is physically dropped the
    next time the store is touched after that. A sweeper was rejected
    deliberately — the store is a module-level singleton with no
    lifecycle owner, so a daemon thread inside this module would have to
    be started and stopped by nobody, and it would make :meth:`count`
    (a health-feed metric) depend on thread timing rather than on the
    data. No caller relies on an expired entry being *physically* gone:
    the in-tree TTL users — the plan_index index, the watchdog lease,
    the approval TTL, the adapter health cache — all want the record to
    *read* as absent, which lazy expiry delivers exactly.

    The clock is injectable (:meth:`__init__`) so a test can advance
    time without sleeping.
    """

    def __init__(self, *, now: Callable[[], float] | None = None) -> None:
        self._data: dict[str, str] = {}
        #: Key -> absolute deadline, in seconds on the injected clock.
        self._expiry: dict[str, float] = {}
        #: A lower bound on the earliest deadline still outstanding.
        self._next_expiry: float | None = None
        self._now = now or time.monotonic
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            self._purge_expired(self._now())
            return self._data.get(key)

    def put(self, key: str, value: str, ttl: int | None = None) -> None:
        """Store ``value`` under ``key``.

        ``ttl`` is the entry's lifetime in **seconds**. ``None`` means
        the entry never expires. A ``ttl`` of zero (or less) expires
        the entry immediately — it reads as absent on the next read,
        which is the ``EXPIRE key 0`` semantic of a real KV store.

        Re-writing a key replaces its expiry: a write without a TTL
        clears a previously recorded deadline, so an entry can never be
        evicted by a deadline that no longer applies to it.
        """
        with self._lock:
            now = self._now()
            self._purge_expired(now)
            self._data[key] = value
            if ttl is None:
                self._expiry.pop(key, None)
                return
            deadline = now + ttl
            self._expiry[key] = deadline
            # ``_next_expiry`` is a lower bound on the earliest deadline
            # still outstanding, so it only ever moves down here.
            if self._next_expiry is None or deadline < self._next_expiry:
                self._next_expiry = deadline

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)
            self._expiry.pop(key, None)

    def list_prefix(self, prefix: str) -> list[tuple[str, str]]:
        with self._lock:
            self._purge_expired(self._now())
            return [(k, v) for k, v in self._data.items() if k.startswith(prefix)]

    def count(self) -> int:
        """Number of live (non-expired) records currently stored.

        O(1) in the steady state: the expiry index is walked only when a
        TTL has actually lapsed, and the answer is then a plain ``len``
        of the mapping. The storage health probe reports this as the
        feed's ``entities_count`` on every ``/health`` call, so it must
        not copy the mapping the way ``list_prefix("")`` would.
        """
        with self._lock:
            self._purge_expired(self._now())
            return len(self._data)

    def clear(self) -> None:
        """Remove every record.

        The store is a process-wide singleton, so a test that writes a
        record would otherwise leak it into every later test in the same
        process. This is the supported way to reset it between tests —
        reaching into ``_data`` from a fixture couples the test to the
        private layout.
        """
        with self._lock:
            self._data.clear()
            self._expiry.clear()
            self._next_expiry = None

    def _purge_expired(self, now: float) -> None:
        """Drop every entry whose deadline has passed.

        The caller holds the lock. The early return keeps the steady
        state O(1): ``_next_expiry`` is a lower bound on the earliest
        deadline still outstanding, so ``now < _next_expiry`` proves
        that nothing has expired and the expiry index does not need to
        be walked at all.
        """
        if self._next_expiry is None or now < self._next_expiry:
            return
        if self._expiry:
            expired = [key for key, deadline in self._expiry.items() if deadline <= now]
            for key in expired:
                del self._expiry[key]
                self._data.pop(key, None)
        self._next_expiry = min(self._expiry.values()) if self._expiry else None


#: Module-level singleton — one per process.
#:
#: The lifespan refactor (commit f6f2976f) runs the plan_index init in
#: the same process as the MCP server, and the substrate facade and the
#: ``mahavishnu_kv_*`` tools both live in that process, so one instance
#: serves all of them.
kv_store = ProcessLocalKV()


__all__ = ["ProcessLocalKV", "kv_store"]
