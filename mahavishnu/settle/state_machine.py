"""Settle state machine — proposed -> selected -> applied/released/discarded.

The state machine is the single source of truth for settle-run transitions.
It is intentionally tiny: a transition table, a small ``SettleRunRecord``
dataclass, and a few pure-function helpers. There is NO automatic
side-effect (no file IO, no Dhara IO). The persistence layer (see
:mod:`mahavishnu.settle.persistence`) wraps these primitives and is
responsible for writing to Dhara BEFORE any filesystem side-effect.

This split lets the state machine be unit-tested with no IO and no
mocking, which is the property-based test surface (see
``tests/unit/test_settle_state_machine.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from mahavishnu.core.errors import (
    ErrorCode,
    MahavishnuError,
    ValidationError,
)


class SettleState(StrEnum):
    """Settle-run lifecycle states.

    * ``PROPOSED`` — worker has produced candidate artifacts; bindings not yet
      modified on disk. Initial state for every newly-created run.
    * ``SELECTED`` — caller has chosen this run (vs. sibling candidates) and
      intends to apply it. Apply/release/discard are legal next actions.
    * ``APPLIED`` — terminal: 3-way merge succeeded; binding file is the merged
      result. Absorbing — no further transitions allowed.
    * ``RELEASED`` — terminal: caller abandoned the run without applying;
      bindings are unchanged. Absorbing.
    * ``DISCARDED`` — terminal: caller discarded the run because it was
      invalid (e.g. worker produced garbage). Absorbing.
    """

    PROPOSED = "proposed"
    SELECTED = "selected"
    APPLIED = "applied"
    RELEASED = "released"
    DISCARDED = "discarded"


class SettleAction(StrEnum):
    """Settle-run lifecycle actions.

    * ``SELECT`` — promote ``proposed`` to ``selected``.
    * ``APPLY`` — finalize: 3-way merge and write merged result to the binding.
    * ``RELEASE`` — abandon without merging. Bindings stay at their pre-run state.
    * ``DISCARD`` — mark the run as invalid (e.g. corrupted, wrong target).
    """

    SELECT = "select"
    APPLY = "apply"
    RELEASE = "release"
    DISCARD = "discard"


# Transition table: ``{(from_state, action): to_state}``.
#
# ``APPLIED``, ``RELEASED``, ``DISCARDED`` are intentionally absent on the
# right-hand side — once you reach a terminal state, you cannot transition
# out of it. The property-based test (``tests/unit/test_settle_state_machine.py::test_terminal_states_absorbing``)
# exercises this property exhaustively.
_TRANSITIONS: dict[tuple[SettleState, SettleAction], SettleState] = {
    (SettleState.PROPOSED, SettleAction.SELECT): SettleState.SELECTED,
    (SettleState.SELECTED, SettleAction.APPLY): SettleState.APPLIED,
    (SettleState.SELECTED, SettleAction.RELEASE): SettleState.RELEASED,
    (SettleState.SELECTED, SettleAction.DISCARD): SettleState.DISCARDED,
}

_TERMINAL_STATES: frozenset[SettleState] = frozenset(
    {SettleState.APPLIED, SettleState.RELEASED, SettleState.DISCARDED}
)


@dataclass(frozen=True)
class Binding:
    """A file targeted by the settle run.

    Each binding is identified by ``path`` (relative to the run's repo root)
    and carries the pre-run ``base`` content (snapshot before the worker
    ran) so the 3-way merge can be performed by an external tool
    (``git merge-file`` is the canonical implementer).
    """

    path: str
    base: str


@dataclass(frozen=True)
class SettleRunRecord:
    """Durable record for a single settle run.

    Persisted under the Dhara key ``settle/v1/{run_ref}`` so that
    :func:`mahavishnu.settle.persistence.load_record` can recover it across
    process restarts. The ``transitions`` list is the audit trail — every
    action is appended on success.
    """

    run_ref: str
    worker_id: str
    task_signature: str
    bindings: tuple[Binding, ...]
    state: SettleState
    created_at: datetime
    updated_at: datetime
    transitions: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable dict suitable for Dhara persistence."""
        return {
            "run_ref": self.run_ref,
            "worker_id": self.worker_id,
            "task_signature": self.task_signature,
            "bindings": [{"path": b.path, "base": b.base} for b in self.bindings],
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "transitions": list(self.transitions),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> SettleRunRecord:
        """Hydrate a record from its Dhara representation.

        Tolerates missing optional fields by defaulting to ``PROPOSED`` and
        an empty transition log — this keeps forward-compat with records
        written by older versions.
        """
        if not isinstance(payload, dict):
            raise ValidationError(
                "SettleRunRecord.from_dict requires a dict payload",
                details={"payload_type": type(payload).__name__},
            )
        run_ref = _require_str_field(payload, "run_ref", run_ref=None, empty_required=True)
        worker_id = _require_str_field(payload, "worker_id", run_ref=run_ref, empty_required=True)
        task_signature = _require_str_field(
            payload, "task_signature", run_ref=run_ref, empty_required=False
        )
        bindings = _parse_bindings(payload.get("bindings", ()), run_ref)
        state_raw = payload.get("state", SettleState.PROPOSED.value)
        state = SettleState(state_raw)
        created_at = _parse_iso(payload.get("created_at"), field_name="created_at")
        updated_at = _parse_iso(payload.get("updated_at"), field_name="updated_at")
        transitions = _parse_transitions(payload.get("transitions", ()), run_ref)
        return cls(
            run_ref=run_ref,
            worker_id=worker_id,
            task_signature=task_signature,
            bindings=tuple(bindings),
            state=state,
            created_at=created_at,
            updated_at=updated_at,
            transitions=tuple(transitions),
        )


def _require_str_field(
    payload: dict[str, object],
    field: str,
    *,
    run_ref: str | None,
    empty_required: bool,
) -> str:
    """Return ``payload[field]`` if it is a string meeting the empty rule.

    ``empty_required=True`` rejects empty strings with ``"missing {field}"``
    (matches pre-refactor behavior for ``run_ref`` and ``worker_id``).
    ``empty_required=False`` allows empty strings but rejects non-strings
    with ``"{field} must be string"`` (matches ``task_signature``).

    When ``run_ref`` is known, validation errors include it in ``details``;
    otherwise ``details`` carries the sorted payload keys so the caller
    can still diagnose a malformed record.
    """
    value = payload.get(field)
    is_valid = isinstance(value, str) and (not empty_required or value)
    if is_valid:
        return value  # type: ignore[return-value]
    details = (
        {"run_ref": run_ref} if run_ref is not None else {"payload_keys": sorted(payload.keys())}
    )
    if empty_required:
        raise ValidationError(
            f"SettleRunRecord.from_dict: missing {field}",
            details=details,
        )
    raise ValidationError(
        f"SettleRunRecord.from_dict: {field} must be string",
        details=details,
    )


def _parse_bindings(raw_bindings: object, run_ref: str) -> list[Binding]:
    """Validate ``bindings`` payload shape and return ``Binding`` objects."""
    if not isinstance(raw_bindings, (list, tuple)):
        raise ValidationError(
            "SettleRunRecord.from_dict: bindings must be a list/tuple",
            details={"run_ref": run_ref},
        )
    bindings: list[Binding] = []
    for idx, raw in enumerate(raw_bindings):
        if not isinstance(raw, dict):
            raise ValidationError(
                f"SettleRunRecord.from_dict: binding #{idx} is not a dict",
                details={"run_ref": run_ref},
            )
        path_v = raw.get("path")
        base_v = raw.get("base", "")
        if not isinstance(path_v, str) or not path_v:
            raise ValidationError(
                f"SettleRunRecord.from_dict: binding #{idx} missing path",
                details={"run_ref": run_ref},
            )
        if not isinstance(base_v, str):
            raise ValidationError(
                f"SettleRunRecord.from_dict: binding #{idx} base must be str",
                details={"run_ref": run_ref},
            )
        bindings.append(Binding(path=path_v, base=base_v))
    return bindings


def _parse_transitions(raw_transitions: object, run_ref: str) -> list[dict[str, str]]:
    """Validate ``transitions`` payload shape and coerce to ``dict[str, str]``."""
    if not isinstance(raw_transitions, (list, tuple)):
        raise ValidationError(
            "SettleRunRecord.from_dict: transitions must be a list",
            details={"run_ref": run_ref},
        )
    transitions: list[dict[str, str]] = []
    for entry in raw_transitions:
        if not isinstance(entry, dict):
            raise ValidationError(
                "SettleRunRecord.from_dict: transition entries must be dicts",
                details={"run_ref": run_ref},
            )
        transitions.append({str(k): str(v) for k, v in entry.items()})
    return transitions


@dataclass
class SettleTransitionError(MahavishnuError):
    """Raised when an action is illegal from the current state.

    Maps to ``MHV-500`` (Precommitment Violation — Spec #2) because the
    state machine mirrors a precommitment-style invariant: once a settle
    run reaches ``applied``, the binding is mutated; any attempt to
    re-apply or undo via the state machine is forbidden.

    Not ``@dataclass(frozen=True)`` because :class:`MahavishnuError`
    assigns ``self.message`` and ``self.details`` in its constructor —
    a frozen dataclass would raise ``FrozenInstanceError``.
    """

    run_ref: str
    current_state: str
    attempted_action: str

    def __init__(
        self,
        message: str,
        *,
        run_ref: str,
        current_state: str,
        attempted_action: str,
        details: dict | None = None,
    ) -> None:
        merged = {
            "run_ref": run_ref,
            "current_state": current_state,
            "attempted_action": attempted_action,
            **(details or {}),
        }
        super().__init__(
            message,
            ErrorCode.PRECOMMITMENT_VIOLATION,
            details=merged,
        )


def _parse_iso(value: object, *, field_name: str) -> datetime:
    """Parse an ISO 8601 timestamp; default to ``datetime.now(UTC)`` on absence."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(UTC)


def legal_next(state: SettleState) -> tuple[SettleAction, ...]:
    """Return the actions that are legal from ``state``.

    Returns an empty tuple for terminal states.
    """
    actions = [action for (s, action), _ in _TRANSITIONS.items() if s == state]
    return tuple(actions)


def is_terminal(state: SettleState) -> bool:
    """Return True if ``state`` is absorbing (no legal transitions)."""
    return state in _TERMINAL_STATES


def transition(
    record: SettleRunRecord,
    action: SettleAction,
    *,
    actor: str = "system",
) -> SettleRunRecord:
    """Apply ``action`` to ``record`` and return the new record.

    Pure function: the input ``record`` is not mutated. The returned record
    has an updated ``state``, ``updated_at``, and an appended transition
    entry. Persistence is the caller's responsibility (see
    :mod:`mahavishnu.settle.persistence`).

    Raises:
        SettleTransitionError: if ``action`` is illegal from ``record.state``.
    """
    next_state = _TRANSITIONS.get((record.state, action))
    if next_state is None:
        raise SettleTransitionError(
            f"Illegal settle transition: {action.value!r} from {record.state.value!r}",
            run_ref=record.run_ref,
            current_state=record.state.value,
            attempted_action=action.value,
        )
    now = datetime.now(UTC)
    transition_entry = {
        "action": action.value,
        "from_state": record.state.value,
        "to_state": next_state.value,
        "actor": actor,
        "at": now.isoformat(),
    }
    return SettleRunRecord(
        run_ref=record.run_ref,
        worker_id=record.worker_id,
        task_signature=record.task_signature,
        bindings=record.bindings,
        state=next_state,
        created_at=record.created_at,
        updated_at=now,
        transitions=(*record.transitions, transition_entry),
    )


def initial_record(
    *,
    run_ref: str,
    worker_id: str,
    task_signature: str,
    bindings: tuple[Binding, ...],
) -> SettleRunRecord:
    """Build the initial ``PROPOSED`` record for a new settle run."""
    if not run_ref:
        raise ValidationError(
            "initial_record requires non-empty run_ref",
        )
    if not worker_id:
        raise ValidationError(
            "initial_record requires non-empty worker_id",
        )
    if not isinstance(task_signature, str):
        raise ValidationError(
            "initial_record: task_signature must be string",
        )
    if not bindings:
        raise ValidationError(
            "initial_record: bindings must be non-empty",
            details={"run_ref": run_ref},
        )
    now = datetime.now(UTC)
    return SettleRunRecord(
        run_ref=run_ref,
        worker_id=worker_id,
        task_signature=task_signature,
        bindings=bindings,
        state=SettleState.PROPOSED,
        created_at=now,
        updated_at=now,
        transitions=(),
    )
