"""Local lock sentinel — replaces ``dhara.lock.in_memory.InMemoryDharaLock``.

Per Phase 8 Task 5 of the Dhara MCP retirement plan: the consumer's
actual lock-service usage is limited to ``try_acquire(key, owner_token=...,
permanent=True, metadata=...)`` and ``get(key)`` — the cross-process
distributed-locking surface (heartbeat, TTL expiry, owner-token
validation across separate processes) was not exercised by any
consumer code in mahavishnu. ``HypothesisLock`` (the only caller)
treats the lock service as a "register an immutable record keyed by
``lock_id`` with an owner token, then look it up later to verify it
hasn't been tampered with." That's a witness-pattern use case, not
a critical-section lock.

This sentinel preserves that surface with a plain in-process dict.
asyncio is single-threaded, so dict operations are atomic by default;
no ``asyncio.Lock`` is needed at the dict-access level. The sentinel
is intentionally minimal: heartbeat, release, list_keys, and
async-acquire-with-timeout are NOT implemented because no consumer
in mahavishnu calls them. If a future caller needs them, extend
the surface here (and document the cross-process-or-not tradeoff in
the commit message).

Test fixtures that previously mocked ``dhara.lock.in_memory.InMemoryDharaLock``
must now mock ``mahavishnu.core._lock_sentinel.Lock`` (this path).
The lock module's TYPE_CHECKING import in
``mahavishnu/core/precommitment.py`` updates accordingly.

Decision rule (per plan Task 5): lock semantics reduced from
cross-process distributed locking to in-process dict-backed
register/get. If cross-process persistence is required in the
future, this sentinel would need a SQL/DuckDB backend; that's a
larger refactor and out of scope here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
import uuid


# Exception classes — shape-compatible with dhara.lock.protocol so
# any future caller that catches them keeps working.
class LockTimeout(Exception):
    """Acquire timed out before the lock became available."""


class LockLost(Exception):
    """Lock holder's entry vanished (TTL expired, owner mismatch, removed)."""


class LockPermanentError(Exception):
    """Attempted to release or heartbeat a permanent-held lock."""


@dataclass(frozen=True)
class LockHandle:
    """In-process lock handle — mirrors dhara.lock.protocol.LockHandle shape.

    Carries the metadata payload (a JSON-encoded ``LockResult`` in the
    HypothesisLock use case) so callers can recover the original record
    on subsequent ``get()`` calls.
    """

    lock_key: str
    owner_token: str
    acquired_at: datetime
    expires_at: datetime | None
    is_permanent: bool
    original_ttl_seconds: int | None
    metadata: dict[str, Any] = field(default_factory=dict)


class Lock:
    """In-process lock service — ``try_acquire`` + ``get`` only.

    Drop-in for ``dhara.lock.in_memory.InMemoryDharaLock`` on the subset
    of API actually used by ``mahavishnu.core.precommitment.HypothesisLock``.
    See module docstring for the scope decision.
    """

    def __init__(self) -> None:
        self._items: dict[str, LockHandle] = {}

    def try_acquire(
        self,
        lock_key: str,
        *,
        owner_token: str | None = None,
        ttl_seconds: int | None = None,
        permanent: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> LockHandle | None:
        """Acquire a lock entry or return None if the key is held.

        Raises ``ValueError`` if a permanent-held entry already exists
        at ``lock_key`` (matches dhara's contract for permanent-locked
        keys).
        """
        if permanent and ttl_seconds is not None:
            raise ValueError("permanent=True is mutually exclusive with ttl_seconds")
        if lock_key in self._items:
            existing = self._items[lock_key]
            if existing.is_permanent:
                raise ValueError(f"duplicate lock_id: {lock_key}")
            return None

        now = datetime.now(UTC)
        token = owner_token or uuid.uuid4().hex
        expires_at = (
            None if ttl_seconds is None else now + timedelta(seconds=ttl_seconds)
        )
        handle = LockHandle(
            lock_key=lock_key,
            owner_token=token,
            acquired_at=now,
            expires_at=expires_at,
            is_permanent=permanent,
            original_ttl_seconds=ttl_seconds,
            metadata=metadata or {},
        )
        self._items[lock_key] = handle
        return handle

    def get(self, lock_key: str) -> LockHandle | None:
        """Return the handle at ``lock_key`` or None if absent."""
        return self._items.get(lock_key)


__all__ = [
    "Lock",
    "LockHandle",
    "LockLost",
    "LockPermanentError",
    "LockTimeout",
]
