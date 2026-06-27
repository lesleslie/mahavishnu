"""Three-zone skill pipeline interface (Spec #5, Phase 2).

The three-zone pipeline is the architectural fix for autonomous self-learning
silently overwriting manually-tuned skills (see design spec
``docs/superpowers/specs/2026-06-22-three-zone-skill-pipeline-design.md``).

Zones:

    INTAKE    - agents propose skills here (analogue of ``staging/``)
    TRANSFORM - validated, lint-passing skills awaiting human promotion
    PUBLISH   - active, human-promoted skills (analogue of ``systems/``)

This module ships:

- ``SkillZone`` enum (INTAKE / TRANSFORM / PUBLISH)
- ``SkillTransition`` audit-log dataclass (append-only, frozen)
- ``SkillPipeline`` protocol (interface only)
- ``InMemorySkillPipeline`` implementation for tests + dev
- ``DharaSkillPipeline`` stub that raises ``NotImplementedError``

The Dhara-backed implementation is a follow-up that lands with Workstream B
(substrate: ``skill_transitions`` audit table). The stub keeps the Dhara
dependency documented and exercises the call site at import time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol, runtime_checkable


class SkillZone(str, Enum):
    """The three zones in the skill pipeline.

    Mirrors the Spec #5 architectural contract:
    the agent proposes, the human disposes, history is preserved.
    """

    INTAKE = "intake"
    TRANSFORM = "transform"
    PUBLISH = "publish"


@dataclass(frozen=True)
class SkillTransition:
    """A single audit-log entry recording a zone transition.

    Frozen + append-only by design (Spec #5 G3: history is preserved,
    no edits, no deletes). ``content_hash`` is the SHA-256 of the skill
    body at the moment of transition.

    Mirrors the Dhara ``skill_transitions`` table schema (Spec #5 audit log).
    """

    transition_id: str
    skill_name: str
    from_zone: SkillZone
    to_zone: SkillZone
    actor: str
    reason: str
    content_hash: str
    confidence: int | None = None
    transition_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class SkillPipeline(Protocol):
    """Append-only audit log interface for zone transitions.

    The Dhara implementation will satisfy this protocol by inserting
    rows into ``skill_transitions``. Until then, ``InMemorySkillPipeline``
    is the production reference implementation for tests and local dev.
    """

    def record_transition(self, transition: SkillTransition) -> None:
        """Persist a transition. Implementations must reject duplicate
        ``transition_id`` values to preserve the append-only invariant.
        """
        ...

    def history(self) -> list[SkillTransition]:
        """Return all recorded transitions in insertion order."""
        ...

    def history_for(self, skill_name: str) -> list[SkillTransition]:
        """Return transitions filtered by ``skill_name`` (insertion order)."""
        ...


class InMemorySkillPipeline:
    """In-memory implementation of :class:`SkillPipeline`.

    Suitable for unit tests, local development, and the dhara-still-pending
    Workstream B. Stores transitions in a list keyed by ``transition_id``
    so PK collisions raise on ``record_transition`` rather than silently
    overwriting history.
    """

    def __init__(self) -> None:
        self._transitions: list[SkillTransition] = []
        self._seen_ids: set[str] = set()

    def record_transition(self, transition: SkillTransition) -> None:
        if transition.transition_id in self._seen_ids:
            raise ValueError(
                f"duplicate transition_id: {transition.transition_id}"
            )
        self._seen_ids.add(transition.transition_id)
        self._transitions.append(transition)

    def history(self) -> list[SkillTransition]:
        # Return a shallow copy so callers cannot mutate our log.
        return list(self._transitions)

    def history_for(self, skill_name: str) -> list[SkillTransition]:
        return [t for t in self._transitions if t.skill_name == skill_name]


class DharaSkillPipeline:
    """Stub for the Dhara-backed implementation.

    The Dhara ``skill_transitions`` table is the durable backing store
    for this audit log. Until the Dhara substrate lands (Workstream B),
    this stub raises ``NotImplementedError`` so the call site is
    documented and import-time visible, but no Dhara write occurs.

    TODO(Workstream B - substrate): replace ``record_transition`` with
    a Dhara INSERT into ``skill_transitions`` using the SQL:

        INSERT INTO skill_transitions
            (transition_id, skill_name, skill_kind, from_zone, to_zone,
             actor, reason, confidence, content_hash, transition_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

    The follow-up must also keep the append-only invariant by routing
    any DELETE / UPDATE through the migration runner's deny list.
    """

    def record_transition(self, transition: SkillTransition) -> None:
        raise NotImplementedError(
            "DharaSkillPipeline is a stub. The Dhara-backed "
            "skill_transitions table is blocked on Workstream B (substrate). "
            "Use InMemorySkillPipeline until then. "
            "TODO(Workstream B): wire INSERT INTO skill_transitions."
        )

    def history(self) -> list[SkillTransition]:
        raise NotImplementedError(
            "DharaSkillPipeline.history() pending Workstream B substrate."
        )

    def history_for(self, skill_name: str) -> list[SkillTransition]:
        raise NotImplementedError(
            "DharaSkillPipeline.history_for() pending Workstream B substrate."
        )


# ---------------------------------------------------------------------------
# Dhara execute call site (TODO Workstream B)
# ---------------------------------------------------------------------------
#
# The Dhara execute hook is intentionally a stub function (not the class
# method above) so that downstream code can call a single entry point
# without committing to a specific pipeline implementation. When the
# substrate lands, the body becomes:
#
#     from mahavishnu.core.dhara_client import execute
#     execute(
#         "INSERT INTO skill_transitions "
#         "(transition_id, skill_name, skill_kind, from_zone, to_zone, "
#         " actor, reason, confidence, content_hash, transition_at) "
#         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
#         (
#             transition.transition_id,
#             transition.skill_name,
#             skill_kind,                      # 'tool' | 'workflow' - set by caller
#             transition.from_zone.value,
#             transition.to_zone.value,
#             transition.actor,
#             transition.reason,
#             transition.confidence,
#             transition.content_hash,
#         ),
#     )
#
# Until then, this call site is a TODO marker that imports cleanly and
# fails loudly if anything routes through it accidentally.


def record_to_dhara(
    transition: SkillTransition,
    *,
    skill_kind: str,
) -> None:
    """Dhara execute stub for ``skill_transitions``.

    TODO(Workstream B - substrate): replace with a real
    ``execute(SQL, params)`` call once the Dhara-backed audit table lands.
    For now, raise so accidental wiring is caught at runtime.
    """
    raise NotImplementedError(
        "record_to_dhara() is a stub. TODO(Workstream B - substrate): "
        "wire the Dhara execute() call to INSERT into skill_transitions. "
        f"Would have recorded: {transition} (skill_kind={skill_kind!r})"
    )


__all__ = [
    "DharaSkillPipeline",
    "InMemorySkillPipeline",
    "SkillPipeline",
    "SkillTransition",
    "SkillZone",
    "record_to_dhara",
]
