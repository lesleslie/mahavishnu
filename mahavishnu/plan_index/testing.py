"""Test helpers for plan_index — mock Dhara client."""

from __future__ import annotations

__all__ = ["FakeDhara"]


class FakeDhara:
    """Minimal in-memory Dhara stand-in for tests.

    Implements the subset of AsyncClient API used by PlanIndexStore.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def put(self, key: str, value: str, *, ttl: int | None = None) -> None:
        self._store[key] = value

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def list_prefix(self, prefix: str) -> list[tuple[str, str]]:
        return [(k, v) for k, v in self._store.items() if k.startswith(prefix)]

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
