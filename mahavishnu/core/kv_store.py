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
"""

from __future__ import annotations

import threading


class ProcessLocalKV:
    """Thread-safe string-shape KV for the server's own substrate.

    The MCP server is single-process; multiple concurrent tool calls run
    in the same event loop. A plain ``dict`` is safe under CPython's GIL
    for individual operations, but a ``threading.Lock`` makes the
    read-modify-write patterns in :meth:`list_prefix` race-free. The lock
    is held only across the in-memory mutation, not across any await, so
    it never blocks the event loop.
    """

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._data.get(key)

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._data[key] = value

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def list_prefix(self, prefix: str) -> list[tuple[str, str]]:
        with self._lock:
            return [(k, v) for k, v in self._data.items() if k.startswith(prefix)]

    def count(self) -> int:
        """Number of records currently stored.

        O(1). The storage health probe reports this as the feed's
        ``entities_count`` on every ``/health`` call, so it must not
        copy the mapping the way ``list_prefix("")`` would.
        """
        with self._lock:
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


#: Module-level singleton — one per process.
#:
#: The lifespan refactor (commit f6f2976f) runs the plan_index init in
#: the same process as the MCP server, and the substrate facade and the
#: ``mahavishnu_kv_*`` tools both live in that process, so one instance
#: serves all of them.
kv_store = ProcessLocalKV()


__all__ = ["ProcessLocalKV", "kv_store"]
