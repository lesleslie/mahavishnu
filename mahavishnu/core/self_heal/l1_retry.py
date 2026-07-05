"""L1 transient retry (Spec #4, Phase 2).

Bounded async retry with exponential backoff. Used to absorb transient
failures (network blips, 503s, momentary resource contention) before the
L2/L3 layers get involved.

Design notes:

- ``max_attempts`` includes the first call. A value of 1 means "no retry,
  just run once." ``max_attempts=3`` means up to two retries after the
  initial failure.
- ``base_backoff`` is the delay before the second attempt. Each
  subsequent retry doubles the previous delay (``base_backoff * 2 ** n``).
  The default is 0.1s so the worst-case total backoff for 3 attempts is
  0.1 + 0.2 = 0.3s, well under the 1-second budget the spec calls out.
- ``L1RetryExhaustedError`` wraps the final attempt's underlying exception so
  callers can introspect the cause without losing stack context.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")

# Type alias for the injectable sleep coroutine. Tests pass a fake
# collector; production code uses ``asyncio.sleep``.
Sleeper = Callable[[float], Awaitable[None]]


class L1RetryExhaustedError(Exception):
    """Raised when the retry budget is exhausted.

    ``cause`` carries the underlying exception from the final attempt
    so L3 (rule extraction) and observability can introspect it.
    """

    def __init__(self, message: str, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause


async def l1_retry[T](
    operation: Callable[..., Awaitable[T]],
    *args: Any,
    max_attempts: int = 3,
    base_backoff: float = 0.1,
    sleeper: Sleeper | None = None,
    **kwargs: Any,
) -> T:
    """Run ``operation`` with bounded retry on transient failure.

    Args:
        operation: async callable to invoke. Failures (any ``Exception``)
            trigger retry; non-``Exception`` ``BaseException`` subclasses
            propagate immediately.
        *args: forwarded to ``operation``.
        max_attempts: total attempts including the first. Must be >= 1.
        base_backoff: seconds to wait before the second attempt; doubles
            on each subsequent retry. Must be >= 0.
        sleeper: optional injectable awaitable for the backoff sleep.
            Defaults to ``asyncio.sleep``.
        **kwargs: forwarded to ``operation``.

    Raises:
        ValueError: if ``max_attempts`` is non-positive.
        L1RetryExhaustedError: when all attempts raise. ``__cause__`` points
            at the final attempt's exception.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    if base_backoff < 0:
        raise ValueError(f"base_backoff must be >= 0, got {base_backoff}")

    sleep = sleeper if sleeper is not None else asyncio.sleep
    last_exc: BaseException | None = None

    for attempt_index in range(1, max_attempts + 1):
        try:
            return await operation(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - intentional catch-all for retry
            last_exc = exc
            if attempt_index >= max_attempts:
                break
            # Exponential backoff: base, 2*base, 4*base, ...
            delay = base_backoff * (2 ** (attempt_index - 1))
            await sleep(delay)

    assert last_exc is not None  # loop only exits via break after a failed attempt
    raise L1RetryExhaustedError(
        f"L1 retry exhausted after {max_attempts} attempt(s): {last_exc!s}",
        cause=last_exc,
    ) from last_exc
