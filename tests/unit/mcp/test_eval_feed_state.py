"""Tests for the eval health feed's error contract (REQ-EVAL-008).

A client-caused error must not be able to take the server down. The
feed's ``warm`` flag means "a run has completed"; if a failed request
warmed it, one bad dataset path would drive ``/health`` to 503 and the
launchd healthcheck wrapper would kill the process.
"""

from __future__ import annotations

import pytest

from mahavishnu.mcp.eval_feed import (
    EvalFeedState,
    get_eval_feed_state,
    init_eval_feed_state,
    record_eval_cycle,
    record_eval_error,
    reset_eval_feed_state,
)

# req: REQ-EVAL-008


@pytest.mark.req(["REQ-EVAL-008"])
def test_a_fresh_feed_is_healthy() -> None:
    """A feed that has not run anything reports healthy."""
    state = EvalFeedState()
    assert state.is_ok()
    assert state.warm is False


@pytest.mark.req(["REQ-EVAL-008"])
def test_an_error_alone_does_not_make_the_feed_unhealthy() -> None:
    """A client error does not warm the feed or fail the health check."""
    state = EvalFeedState()
    state.record_error()

    assert state.errors_total == 1
    assert state.warm is False
    assert state.is_ok()


@pytest.mark.req(["REQ-EVAL-008"])
def test_a_successful_cycle_warms_the_feed() -> None:
    """A completed run warms the feed and counts its cases."""
    state = EvalFeedState()
    state.record_cycle(case_count=4)

    assert state.warm is True
    assert state.cycles_total == 1
    assert state.entities_count == 4
    assert state.is_ok()


@pytest.mark.req(["REQ-EVAL-008"])
def test_a_cycle_with_no_cases_does_not_warm_the_feed() -> None:
    """A cycle that persisted nothing leaves the feed cold and healthy.

    This is the other half of the "a client must not be able to take
    the server down" contract. A client that asks for a zero budget
    gets a run that executes no case; if that cycle warmed the feed,
    the feed would be warm with an empty entity count, ``is_ok()``
    would be False, and ``/health`` would answer 503 -- which the
    launchd wrapper turns into a process kill. The cycle is still
    counted, so the operator can see the request arrived.
    """
    state = EvalFeedState()
    state.record_cycle(case_count=0)

    assert state.warm is False
    assert state.cycles_total == 1
    assert state.entities_count == 0
    assert state.is_ok()
    assert state.as_dict()["ok"] is True


@pytest.mark.req(["REQ-EVAL-008"])
def test_a_later_empty_cycle_does_not_unwarm_the_feed() -> None:
    """Once warm, an empty cycle does not make the feed cold again."""
    state = EvalFeedState()
    state.record_cycle(case_count=3)
    state.record_cycle(case_count=0)

    assert state.warm is True
    assert state.entities_count == 3
    assert state.is_ok()


@pytest.mark.req(["REQ-EVAL-008"])
def test_an_error_after_a_successful_cycle_stays_counted() -> None:
    """An error after a successful run is visible but not fatal."""
    state = EvalFeedState()
    state.record_cycle(case_count=2)
    state.record_error()

    assert state.errors_total == 1
    assert state.cycles_total == 1
    assert state.is_ok()


@pytest.mark.req(["REQ-EVAL-008"])
def test_the_module_helpers_tolerate_an_uninitialised_feed() -> None:
    """The helpers are a no-op before the lifespan installs the feed."""
    reset_eval_feed_state()
    assert get_eval_feed_state() is None

    record_eval_cycle(case_count=1)
    record_eval_error()

    assert get_eval_feed_state() is None


@pytest.mark.req(["REQ-EVAL-008"])
def test_init_installs_a_fresh_feed() -> None:
    """Init installs the singleton and bumps the generation token."""
    reset_eval_feed_state()
    first = init_eval_feed_state()
    second = init_eval_feed_state()

    assert get_eval_feed_state() is second
    assert second.generation == first.generation + 1
    reset_eval_feed_state()


@pytest.mark.req(["REQ-EVAL-008"])
def test_the_payload_carries_the_four_signal_contract() -> None:
    """The payload carries the four signals the aggregator expects."""
    state = EvalFeedState()
    state.record_cycle(case_count=3)

    payload = state.as_dict()
    assert payload["feed"] == "eval"
    assert payload["ok"] is True
    assert payload["feed_entities_count"] == 3
    timestamp = payload["feed_last_updated_timestamp"]
    assert isinstance(timestamp, float)
    assert timestamp > 0
    assert payload["cycles_total"] == 1
    assert payload["errors_total"] == 0
