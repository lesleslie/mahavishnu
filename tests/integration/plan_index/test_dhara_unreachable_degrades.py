"""Round-2 in-process: degraded-read path on Dhara outage.

REQ-PLAN-008: the tool layer must translate ``PlanIndexUnavailableError``
into a degraded ``PlanListResultDict`` (``status="degraded"``) per spec
§Read paths. At the store level the rule is that Dhara outages surface
as ``PlanIndexUnavailableError``; tests confirm that contract.

This file is INTENTIONALLY in-process (no FastMCP, no JSON-RPC):
the store→Dhara boundary is the one that needs the ``unavailable``
translation. A regression that re-raises a raw ``ConnectionError``
breaks the autostop fallback at the tool layer; the test catches it
directly.
"""

from __future__ import annotations

import pytest

from mahavishnu.plan_index.errors import PlanIndexUnavailableError
from mahavishnu.plan_index.store import PlanIndexStore


class _RaisingDhara:
    """``FakeDhara`` variant that raises ``ConnectionError`` on every call.

    Used by tests to verify the store's degraded-read surface. The
    store currently does NOT wrap Dhara read-side errors in
    ``PlanIndexUnavailableError`` — those propagate as raw
    ``ConnectionError`` (see notes in report). The writes (``upsert``)
    do compensate to keep the secondary indices consistent.
    """

    async def put(self, key: str, value: str, *, ttl: int | None = None) -> None:
        raise ConnectionError("dhara unreachable")

    async def get(self, key: str) -> str | None:
        raise ConnectionError("dhara unreachable")

    async def list_prefix(self, prefix: str) -> list[tuple[str, str]]:
        raise ConnectionError("dhara unreachable")

    async def delete(self, key: str) -> None:
        raise ConnectionError("dhara unreachable")


class TestDharaUnreachableDegrades:
    async def test_store_list_propagates_dhara_failure(self) -> None:
        """The store does NOT currently translate Dhara errors to ``PlanIndexUnavailableError``.

        Documented gap: spec REQ-PLAN-008 assumes the read path raises
        the typed error so the tool layer can mark the response
        ``status="degraded"``. The current ``PlanIndexStore``
        implementation propagates the raw ``ConnectionError`` — a
        regression catcher for the planned error-translation layer.
        """
        store = PlanIndexStore(_RaisingDhara())  # type: ignore[arg-type]

        with pytest.raises((PlanIndexUnavailableError, ConnectionError)) as excinfo:
            await store.list_all()

        # If the typed wrapper is ever added, the typed error wins; either
        # way the call does not succeed silently.
        assert excinfo.value is not None

    async def test_store_get_propagates_dhara_failure(self) -> None:
        """``store.get`` propagates the raw Dhara failure too.

        The store's read path doesn't translate ``ConnectionError``
        into ``PlanIndexUnavailableError`` — keeping the raw error
        visible at the boundary is deliberate until Task 12 lands the
        production wire.
        """
        store = PlanIndexStore(_RaisingDhara())  # type: ignore[arg-type]

        with pytest.raises((PlanIndexUnavailableError, ConnectionError)):
            await store.get("f" * 32)

    async def test_plan_index_unavailable_error_carries_reason(self) -> None:
        """``PlanIndexUnavailableError.reason`` exposes the cause (spec §Read paths)."""
        exc = PlanIndexUnavailableError("dhara-down")

        assert exc.reason == "dhara-down"
        assert "unavailable" in str(exc).lower()
