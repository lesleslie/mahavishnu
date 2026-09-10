"""Test helpers for plan_index — mock Dhara client."""

from __future__ import annotations

__all__ = ["FakeDhara"]


class FakeDhara:
    """Minimal in-memory Dhara stand-in for tests.

    Implements the subset of AsyncClient API used by PlanIndexStore.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int | None] = {}

    async def put(self, key: str, value: str, *, ttl: int | None = None) -> None:
        self._store[key] = value
        self._ttls[key] = ttl

    def get_ttl(self, key: str) -> int | None:
        """Test-only inspection hook: the TTL recorded for ``key``."""
        return self._ttls.get(key)

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def list_prefix(self, prefix: str) -> list[tuple[str, str]]:
        return [(k, v) for k, v in self._store.items() if k.startswith(prefix)]

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._ttls.pop(key, None)
