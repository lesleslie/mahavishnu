"""In-process cache for capability reports."""

from __future__ import annotations

import time
from typing import Any

_STORE: dict[str, tuple[float, Any]] = {}


def get(key: str, ttl_s: int) -> object | None:
    ts, value = _STORE.get(key, (0.0, None))
    return value if time.monotonic() - ts < ttl_s else None


def put(key: str, value: Any) -> None:
    _STORE[key] = (time.monotonic(), value)


def invalidate(worker_type: str) -> None:
    for key in list(_STORE):
        if key.startswith(f"{worker_type}:"):
            _STORE.pop(key, None)


def clear() -> None:
    _STORE.clear()
