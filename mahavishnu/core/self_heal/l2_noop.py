"""L2 no-op layer (Spec #4, Phase 2).

L2 is the bounded agentic heal slot per the spec; in v0 it is a
deterministic pass-through so the recovery protocol has a stable marker
between L1 (transient retry) and L3 (rule extraction). Future L2
implementations (bounded Claude turns, etc.) can be slotted in here
without re-wiring callers.

The ``MARKER`` class attribute is the canonical regression pin. Downstream
callers grep for the string ``"noop_recovery"`` to detect the L2 stub;
changing the marker is a deliberate, breaking-API decision and must be
reflected in tests/unit/test_self_heal.py::TestL2Noop::test_marker_is_canonical_string.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

T = TypeVar("T")


class L2Noop:
    """Deterministic pass-through. Marker for the L2 slot in the protocol."""

    #: Canonical regression pin. Do not change without updating the
    #: test that pins it and any downstream consumer that grep-matches it.
    MARKER: str = "noop_recovery"

    @staticmethod
    async def run(
        operation: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Invoke ``operation`` exactly once. Exceptions propagate verbatim.

        Args:
            operation: async callable to run.
            *args: forwarded to ``operation``.
            **kwargs: forwarded to ``operation``.

        Returns:
            Whatever ``operation`` returns.
        """
        return await operation(*args, **kwargs)
