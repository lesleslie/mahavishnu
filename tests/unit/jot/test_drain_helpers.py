"""Task 5: _should_exhaust_retry_budget + MAX_AUTO_ATTEMPTS."""
from __future__ import annotations

from mahavishnu.jot.drain import MAX_AUTO_ATTEMPTS, _should_exhaust_retry_budget
from mahavishnu.jot.fold import JotSummary


def _summary(current_attempt: int) -> JotSummary:
    return JotSummary(  # type: ignore[arg-type]
        id="e1", short_id="e1", text="x",
        status="open", last_modified_ms=0,
        dispatch_state=None, dispatch_workflow_id=None,
        current_attempt=current_attempt,
        dispatch_started_at_ms=None,
        deferred_until=None, deleted=False,
    )


def test_max_auto_attempts_is_2() -> None:
    assert MAX_AUTO_ATTEMPTS == 2


def test_should_exhaust_false_on_first_attempt() -> None:
    assert _should_exhaust_retry_budget(_summary(current_attempt=1)) is False


def test_should_exhaust_true_on_second_attempt() -> None:
    assert _should_exhaust_retry_budget(_summary(current_attempt=2)) is True


def test_should_exhaust_false_on_third_attempt_unusual_but_safe() -> None:
    """current_attempt > MAX_AUTO_ATTEMPTS → True (must already be exhausted)."""
    assert _should_exhaust_retry_budget(_summary(current_attempt=3)) is True


def test_should_exhaust_treats_zero_as_first_attempt() -> None:
    """Fail-safe: malformed 0 attempt → treat as attempt=1 → don't exhaust."""
    assert _should_exhaust_retry_budget(_summary(current_attempt=0)) is False


def test_should_exhaust_treats_negative_as_first_attempt() -> None:
    """Negative attempt (defensive): max(neg, 1) = 1, treat as first attempt."""
    assert _should_exhaust_retry_budget(_summary(current_attempt=-1)) is False
