"""Budget enforcement state machine for Phase 3 (v2 plan).

This module owns the **state machine** portion of Phase 3 Budget
Enforcement. The watchdog that walks this state machine on a 60s timer
lives in :mod:`mahavishnu.core.budget_watchdog`. The MCP tool that
records budget declarations lives in
:mod:`mahavishnu.mcp.tools.pool_tools` (``budget_enforce``).

Design rules (from the v2 plan and the contrarian review that demoted
in-kernel per-turn reads):

* ``Primitives whose natural read frequency is per-turn belong in-process;
  per-run belong in the control plane.`` Token/turn budgets that need
  per-turn reads stay in the worker. The control plane only enforces
  per-run budget shape — wallclock plus final token/turn totals.

* Budget states are tiny and pure. There are no I/O dependencies here —
  no Dhara, no asyncio, no clock. Tests run in microseconds.

* State transitions are **explicit**. ``active`` only enters via
  :meth:`BudgetStateMachine.start`; ``exceeded`` only enters via
  :meth:`BudgetStateMachine.check` returning ``BudgetDimension.*``
  non-``None`` and the caller calling :meth:`BudgetStateMachine.mark_exceeded`.

* Idempotent transitions: re-entering the same state is a no-op (returns
  the same state, never raises) so the watchdog can poll cheaply.

The shape is dataclass-driven because tests in
``tests/unit/test_budget_state_machine.py`` rely on simple attribute
equality and ``hypothesis``-driven construction. JSON serialization is
explicit (``to_dict``/``from_dict``) so Dhara persistence does not
couple the state machine to Pydantic.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class BudgetState(StrEnum):
    """State of a single workflow's budget.

    Transitions::

        pending --start()--> active
        active --mark_exceeded()--> exceeded
        active --mark_completed()--> completed
        exceeded: terminal
        completed: terminal

    Re-entering the same state is a no-op (returns the current state).
    """

    PENDING = "pending"
    ACTIVE = "active"
    EXCEEDED = "exceeded"
    COMPLETED = "completed"


class BudgetDimension(StrEnum):
    """The dimension on which a budget was violated.

    Used as the OTel ``dimension`` label and the
    ``budget.exceeded.count`` counter value. Values are lowercase to
    match existing OTel conventions in the project.
    """

    TOKENS = "tokens"
    TURNS = "turns"
    WALLCLOCK = "wallclock"


# Terminal states never transition further.
_TERMINAL_STATES: frozenset[BudgetState] = frozenset({BudgetState.EXCEEDED, BudgetState.COMPLETED})


@dataclass(slots=True, frozen=True)
class BudgetSpec:
    """The declared budget shape for a workflow run.

    All three fields are optional. A spec with every field ``None`` is
    rejected by :meth:`BudgetStateMachine.start` because it provides
    nothing the watchdog can enforce — at least one dimension must be
    declared for a meaningful budget.

    Attributes:
        budget_tokens: Maximum cumulative tokens for the run. ``None``
            means "no cap" (cost was not a constraint for this run).
        budget_turns: Maximum number of turns/iterations. ``None``
            means no cap.
        budget_wallclock_seconds: Maximum wallclock seconds from
            ``started_at`` to now. ``None`` means no cap.
        declared_by: Identity of the entity that set the budget
            (MCP user id, workflow owner, etc). Stored for audit.
        declared_at: UTC timestamp of declaration.
    """

    budget_tokens: int | None = None
    budget_turns: int | None = None
    budget_wallclock_seconds: float | None = None
    declared_by: str | None = None
    declared_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def has_any_dimension(self) -> bool:
        """Return True when at least one dimension is bounded."""
        return (
            self.budget_tokens is not None
            or self.budget_turns is not None
            or self.budget_wallclock_seconds is not None
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict for Dhara persistence."""
        return {
            "budget_tokens": self.budget_tokens,
            "budget_turns": self.budget_turns,
            "budget_wallclock_seconds": self.budget_wallclock_seconds,
            "declared_by": self.declared_by,
            "declared_at": self.declared_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BudgetSpec:
        """Reconstruct from a persisted dict.

        Missing optional fields default to ``None``. ``declared_at`` falls
        back to "now" if absent (a corrupted record still loads).
        """
        declared_at_raw = payload.get("declared_at")
        if isinstance(declared_at_raw, str):
            declared_at = datetime.fromisoformat(declared_at_raw)
        else:
            declared_at = datetime.now(UTC)
        return cls(
            budget_tokens=payload.get("budget_tokens"),
            budget_turns=payload.get("budget_turns"),
            budget_wallclock_seconds=payload.get("budget_wallclock_seconds"),
            declared_by=payload.get("declared_by"),
            declared_at=declared_at,
        )


@dataclass(slots=True)
class BudgetUsage:
    """Observed counters for the workflow run up to the watchdog poll.

    Three dimensions, all cumulative:

    * ``tokens_used``: tokens spent so far (None if not yet observed).
    * ``turns_used``: agent/iteration turn count so far.
    * ``wallclock_seconds``: seconds elapsed since ``started_at``.

    At least one of the three should be non-``None`` for the watchdog
    to enforce anything; with all ``None``, :meth:`check` returns
    ``None`` (no violation observable yet).
    """

    tokens_used: int | None = None
    turns_used: int | None = None
    wallclock_seconds: float | None = None
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens_used": self.tokens_used,
            "turns_used": self.turns_used,
            "wallclock_seconds": self.wallclock_seconds,
            "observed_at": self.observed_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BudgetUsage:
        observed_at_raw = payload.get("observed_at")
        if isinstance(observed_at_raw, str):
            observed_at = datetime.fromisoformat(observed_at_raw)
        else:
            observed_at = datetime.now(UTC)
        return cls(
            tokens_used=payload.get("tokens_used"),
            turns_used=payload.get("turns_used"),
            wallclock_seconds=payload.get("wallclock_seconds"),
            observed_at=observed_at,
        )


@dataclass(slots=True)
class BudgetRecord:
    """The combined spec + state + latest usage for a workflow run.

    The watchdog persists this entire record to Dhara at
    ``mahavishni://budgets/{workflow_id}.json``. ``workflow_id`` is the
    canonical key; one record per workflow.

    Attributes:
        workflow_id: Stable identifier; used as Dhara key.
        spec: Declared budget shape.
        state: Current ``BudgetState``.
        usage: Latest observed usage. ``None`` until the first poll.
        started_at: UTC datetime when the budget was started. Drives
            wallclock accounting.
        exceeded_dimension: When ``state == EXCEEDED``, the dimension
            that triggered the transition. ``None`` otherwise.
        exceeded_at: UTC datetime the budget was exceeded, or ``None``.
        completed_at: UTC datetime the budget completed naturally, or
            ``None``.
    """

    workflow_id: str
    spec: BudgetSpec = field(default_factory=BudgetSpec)
    state: BudgetState = BudgetState.PENDING
    usage: BudgetUsage | None = None
    started_at: datetime | None = None
    exceeded_dimension: BudgetDimension | None = None
    exceeded_at: datetime | None = None
    completed_at: datetime | None = None

    def is_terminal(self) -> bool:
        """True when the record will not transition further."""
        return self.state in _TERMINAL_STATES

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "spec": self.spec.to_dict(),
            "state": self.state.value,
            "usage": self.usage.to_dict() if self.usage is not None else None,
            "started_at": (self.started_at.isoformat() if self.started_at is not None else None),
            "exceeded_dimension": (
                self.exceeded_dimension.value if self.exceeded_dimension is not None else None
            ),
            "exceeded_at": (self.exceeded_at.isoformat() if self.exceeded_at is not None else None),
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BudgetRecord:
        spec_payload = payload.get("spec") or {}
        spec = (
            BudgetSpec.from_dict(spec_payload) if isinstance(spec_payload, dict) else BudgetSpec()
        )
        usage_payload = payload.get("usage")
        usage = BudgetUsage.from_dict(usage_payload) if isinstance(usage_payload, dict) else None
        state_raw = payload.get("state") or BudgetState.PENDING.value
        try:
            state = BudgetState(state_raw)
        except ValueError:
            state = BudgetState.PENDING

        def _maybe_dt(key: str) -> datetime | None:
            raw = payload.get(key)
            if isinstance(raw, str):
                return datetime.fromisoformat(raw)
            return None

        exceeded_raw = payload.get("exceeded_dimension")
        try:
            exceeded_dim = BudgetDimension(exceeded_raw) if exceeded_raw else None
        except ValueError:
            exceeded_dim = None

        return cls(
            workflow_id=str(payload.get("workflow_id") or ""),
            spec=spec,
            state=state,
            usage=usage,
            started_at=_maybe_dt("started_at"),
            exceeded_dimension=exceeded_dim,
            exceeded_at=_maybe_dt("exceeded_at"),
            completed_at=_maybe_dt("completed_at"),
        )


class BudgetStateMachine:
    """Pure (no I/O) state machine for per-workflow budget records.

    Constructed with a fresh :class:`BudgetRecord`. Mutations return new
    state values via the dataclass ``replace`` machinery — the underlying
    record stays the same Python object so callers can observe state via
    attribute access (``record.state``) after calling mutator methods.

    Why this is a class and not just functions: it makes illegal
    transitions explicit (:meth:`check`, :meth:`mark_exceeded`,
    :meth:`mark_completed`) and centralizes the idempotency rule so the
    watchdog cannot accidentally double-transition on a slow poll.
    """

    def __init__(self, record: BudgetRecord | None = None) -> None:
        self._record = record or BudgetRecord(workflow_id="")

    @property
    def record(self) -> BudgetRecord:
        """Current record; mutate via the transition methods below."""
        return self._record

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def set_record(self, record: BudgetRecord) -> None:
        """Replace the underlying record (e.g., after loading from Dhara)."""
        self._record = record

    def declare(self, spec: BudgetSpec) -> BudgetRecord:
        """Register a budget spec without yet starting the clock.

        Allowed from any non-terminal state. Redeclaring replaces the
        spec; the state stays as-is. From ``PENDING`` this typically
        precedes :meth:`start`. From ``ACTIVE`` this re-bases the
        cap; re-capping tokens from 1000 to 500 on a running run is
        intentional ("pause at 500" semantics).
        """
        self._record = replace(self._record, spec=spec)
        return self._record

    def start(self, *, when: datetime | None = None) -> BudgetRecord:
        """Transition ``PENDING`` to ``ACTIVE`` and stamp ``started_at``.

        Idempotent: calling ``start`` on an already-active record
        returns the existing record unchanged. Calling ``start`` on a
        terminal record is a no-op (returns the terminal record).
        Raises :class:`ValueError` when the spec has no bounded
        dimension (nothing to enforce).
        """
        if self._record.is_terminal():
            return self._record
        if self._record.state is BudgetState.ACTIVE:
            return self._record
        if not self._record.spec.has_any_dimension():
            raise ValueError(
                "BudgetSpec must bound at least one dimension "
                "(tokens, turns, or wallclock) before start()"
            )
        self._record = replace(
            self._record,
            state=BudgetState.ACTIVE,
            started_at=when or datetime.now(UTC),
        )
        return self._record

    def check(
        self,
        usage: BudgetUsage,
    ) -> BudgetDimension | None:
        """Compare usage against the spec; return the violated dimension.

        Side-effect: updates ``record.usage`` to the latest observation
        so Dhara reflects what we just saw. Does **not** transition
        state — the caller decides whether to call :meth:`mark_exceeded`
        or :meth:`mark_completed` based on this signal. The split is
        deliberate so that the watchdog's caller code reads as a clear
        "decide, then commit" sequence.

        Returns:
            First dimension whose cap is exceeded (in the order
            tokens → turns → wallclock), or ``None`` if no violation
            is observable yet (caps were not declared or usage is
            ``None`` for those dims).
        """
        self._record = replace(self._record, usage=usage)
        spec = self._record.spec

        if (
            spec.budget_tokens is not None
            and usage.tokens_used is not None
            and usage.tokens_used > spec.budget_tokens
        ):
            return BudgetDimension.TOKENS
        if (
            spec.budget_turns is not None
            and usage.turns_used is not None
            and usage.turns_used > spec.budget_turns
        ):
            return BudgetDimension.TURNS
        if (
            spec.budget_wallclock_seconds is not None
            and usage.wallclock_seconds is not None
            and usage.wallclock_seconds > spec.budget_wallclock_seconds
        ):
            return BudgetDimension.WALLCLOCK
        return None

    def mark_exceeded(
        self,
        dimension: BudgetDimension,
        *,
        when: datetime | None = None,
    ) -> BudgetRecord:
        """Transition ``ACTIVE`` to ``EXCEEDED``, recording the cause.

        Idempotent: re-marking exceeded returns the existing record.
        Calling ``mark_exceeded`` from any non-active state raises
        :class:`ValueError` so the watchdog cannot exceed a budget
        before it has started (or after it has terminated).
        """
        if self._record.state is BudgetState.EXCEEDED:
            return self._record
        if self._record.state is not BudgetState.ACTIVE:
            raise ValueError(f"Cannot mark_exceeded from state {self._record.state!r}")
        self._record = replace(
            self._record,
            state=BudgetState.EXCEEDED,
            exceeded_dimension=dimension,
            exceeded_at=when or datetime.now(UTC),
        )
        return self._record

    def mark_completed(
        self,
        *,
        when: datetime | None = None,
    ) -> BudgetRecord:
        """Transition ``ACTIVE`` to ``COMPLETED``.

        Idempotent: re-marking completed returns the existing record.
        Calling from any non-active state raises :class:`ValueError`.
        """
        if self._record.state is BudgetState.COMPLETED:
            return self._record
        if self._record.state is not BudgetState.ACTIVE:
            raise ValueError(f"Cannot mark_completed from state {self._record.state!r}")
        self._record = replace(
            self._record,
            state=BudgetState.COMPLETED,
            completed_at=when or datetime.now(UTC),
        )
        return self._record
