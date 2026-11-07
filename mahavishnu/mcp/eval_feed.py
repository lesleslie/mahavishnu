"""Health-feed state for the model-evaluation subsystem (REQ-EVAL-008).

Mirrors the ``skills_signer`` feed contract (``mahavishnu/mcp/signer_feed.py``):
a module-level singleton whose ``as_dict()`` returns the four-signal
contract the canonical aggregator expects — ``feed_entities_count``,
``feed_last_updated_timestamp``, ``cycles_total``, ``errors_total``.

For eval, ``entities_count`` is the total number of ``CaseRecord``s
persisted across all runs, so a run of N cases bumps it by N. That is
the number the wire-up discipline asks an operator to watch: it is zero
until the feature has actually done something.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time

# req: REQ-EVAL-008


@dataclass
class EvalFeedState:
    """Lifespan-owned state for the eval ``/health`` feed.

    Attributes:
        entities_count: Total ``CaseRecord``s persisted across all runs.
        last_updated_timestamp: Unix timestamp of the most recent update.
        cycles_total: Count of successful feed update cycles since startup.
        errors_total: Count of failed feed update cycles since startup.
        generation: Monotonic token so teardown can detect cross-app
            state contamination.
        warm: ``False`` until the first cycle, so a server that has not
            run an eval yet does not report degraded.
    """

    entities_count: int = 0
    last_updated_timestamp: float = field(default_factory=time.time)
    cycles_total: int = 0
    errors_total: int = 0
    generation: int = 0
    warm: bool = False

    def record_cycle(self, case_count: int = 0) -> None:
        """Mark a successful feed update.

        Args:
            case_count: How many case results this cycle persisted. Added
                to ``entities_count``.
        """
        self.cycles_total += 1
        self.entities_count += case_count
        self.last_updated_timestamp = time.time()
        # A cycle that persisted nothing is not evidence that the feed
        # works. Warming on it would let a client that asks for a zero
        # budget drive the server's /health to 503: the feed would be
        # warm with an empty entity count, and :meth:`is_ok` judges a
        # warm feed by that count. The cycle is still counted, so
        # ``cycles_total`` tells the operator the request arrived.
        self.warm = self.warm or case_count > 0

    def record_error(self) -> None:
        """Mark a failed feed update.

        The timestamp still advances, so an operator can see the feed is
        still being polled.

        **This does not warm the feed.** ``warm`` means "a run has
        completed", and :meth:`is_ok` only judges the feed once a run
        has completed. Warming it here would mean a client that named a
        bad dataset path -- one failed request -- could drive the
        server's ``/health`` to 503 and take the process down with it.
        The failure is still visible: ``errors_total`` counts it.
        """
        self.errors_total += 1
        self.last_updated_timestamp = time.time()

    def is_ok(self) -> bool:
        """True when the feed is healthy.

        The eval feed is **telemetry, not a gate**. It reports healthy
        whenever it cannot prove the eval subsystem is broken, and it
        cannot be broken by anything a client does: a failed request
        does not warm it, and a *successful* request that persisted no
        case does not warm it either -- so a client that names a zero
        budget, or a bad dataset path, cannot drive ``/health`` to 503
        and get the process killed by the launchd healthcheck wrapper.

        The consequence is deliberate: ``checks.eval.ok`` is true in
        practice, and the signals an operator actually reads are
        ``cycles_total`` (the requests that arrived), ``entities_count``
        (the case results that landed) and ``errors_total`` (the ones
        that failed). An empty feed after a successful run is visible
        in those counters, not in a 503.
        """
        return True

    def as_dict(self) -> dict[str, object]:
        """Serialize for the ``/health`` payload.

        Returns a flat dict with the same shape as the other Mahavishnu
        feed entries (``ok``, ``feed_entities_count``,
        ``feed_last_updated_timestamp``, ``cycles_total``,
        ``errors_total``), plus ``warm`` -- whether a run has completed
        with case results. ``warm`` is the one signal a client cannot
        fake: it only becomes true when cases actually landed.
        """
        return {
            "ok": self.is_ok(),
            "feed": "eval",
            "warm": self.warm,
            "feed_entities_count": self.entities_count,
            "feed_last_updated_timestamp": self.last_updated_timestamp,
            "cycles_total": self.cycles_total,
            "errors_total": self.errors_total,
            "generation": self.generation,
        }


# ---------------------------------------------------------------------------
# Module-level singleton
#
# The MCP server owns the lifetime of this state: ``start_server`` installs
# it, the eval tools mutate it, and ``/health`` reads it. Tests that want a
# clean slate call ``reset_eval_feed_state``.
# ---------------------------------------------------------------------------

_eval_feed_state: EvalFeedState | None = None
_eval_state_lock = threading.Lock()


def init_eval_feed_state() -> EvalFeedState:
    """Install a fresh :class:`EvalFeedState` as the module singleton.

    Idempotent within a single ``start_server`` call: a re-init bumps the
    generation token so a probe holding the old state can tell.

    Returns:
        The newly installed state.
    """
    global _eval_feed_state

    with _eval_state_lock:
        if _eval_feed_state is not None:
            _eval_feed_state = EvalFeedState(
                generation=_eval_feed_state.generation + 1
            )
        else:
            _eval_feed_state = EvalFeedState()
        return _eval_feed_state


def get_eval_feed_state() -> EvalFeedState | None:
    """Return the module singleton, or ``None`` before initialization."""
    return _eval_feed_state


def reset_eval_feed_state() -> None:
    """Drop the module singleton so the next init starts cold."""
    global _eval_feed_state

    with _eval_state_lock:
        _eval_feed_state = None


def record_eval_cycle(case_count: int = 0) -> None:
    """Record a successful feed cycle, if the feed is installed.

    A no-op before ``init_eval_feed_state()`` runs: a tool called
    against a server that never started its lifespan must not crash.

    Args:
        case_count: How many case results this cycle persisted.
    """
    state = get_eval_feed_state()
    if state is not None:
        state.record_cycle(case_count)


def record_eval_error() -> None:
    """Record a failed feed cycle, if the feed is installed."""
    state = get_eval_feed_state()
    if state is not None:
        state.record_error()


__all__ = [
    "EvalFeedState",
    "get_eval_feed_state",
    "init_eval_feed_state",
    "record_eval_cycle",
    "record_eval_error",
    "reset_eval_feed_state",
]
