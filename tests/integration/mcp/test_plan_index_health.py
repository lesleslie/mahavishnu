"""Task 13 — plan_index feed state feeds the ``/health`` aggregator.

Covers the accessor contract consumed by
``mahavishnu.mcp.bootstrap.register_health_endpoint``:

* ``get_plan_index_feed_state()`` returns ``None`` before any rebuild
  cycle has run, which the aggregator maps to a degraded
  ``checks["plan_index"]`` branch.
* ``set_plan_index_feed_state()`` publishes a state whose ``as_dict()``
  carries the 4-signal wire-up contract plus ``ok``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from mahavishnu.plan_index.health import (
    PlanIndexFeedState,
    get_plan_index_feed_state,
    reset_plan_index_feed_state,
    set_plan_index_feed_state,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _clean_feed_state() -> Iterator[None]:
    """Keep the module-level singleton from leaking across tests."""
    reset_plan_index_feed_state()
    yield
    reset_plan_index_feed_state()


class TestHealthAggregation:
    def test_get_returns_none_initially(self) -> None:
        reset_plan_index_feed_state()
        assert get_plan_index_feed_state() is None

    def test_set_then_get(self) -> None:
        state = PlanIndexFeedState(
            entities_count=10,
            last_updated_timestamp=int(time.time() * 1000),
            errors_total=0,
            cycles_total=5,
        )
        set_plan_index_feed_state(state)
        result = get_plan_index_feed_state()
        assert result is state
        d = result.as_dict()
        assert "ok" in d
        assert d["feed_entities_count"] == 10
