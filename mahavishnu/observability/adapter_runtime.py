"""Adapter runtime observability substrate (Spec #8, Phase 3).

This module is the seam between Mahavishnu's adapter subsystem and the
operational telemetry substrate described in
``docs/superpowers/specs/2026-06-22-adapter-runtime-observability-design.md``.

Status
------
The Dhara-backed HTTP CRUD surface
(``/adapters/<id>/active-settings-version`` and friends) is ``http_blocked``
per the substrate status (overlaps with Plan 4 Phase D). This module
therefore ships the **model + persister interface** only. The Dhara-backed
implementation is a stub that raises ``NotImplementedError`` with a
``TODO(Workstream C - substrate)`` marker so accidental wiring is caught
at runtime.

Seam with Plan 4
----------------
Plan 4 (Oneiric Adapter Config Telemetry) ships ``TrackedSettings`` in
``mahavishnu/distill/tracked_settings.py`` as the upstream source of
``settings_hash`` and ``activated_by``. Spec #8 only consumes those
values; it does NOT own the Oneiric subscription / debounce / hash logic.
Once Plan 4's wiring lands, ``TrackedSettings`` will call
``record_activation(record, persister=...)`` on every change.

Seam with Workstream C substrate
--------------------------------
The Dhara-backed persister will satisfy ``SettingsActivationPersister``
once the substrate lands (Day 9 of the substrate plan). The class
``DharaSettingsActivationPersister`` here is the placeholder.

Mahavishnu conventions honored
------------------------------
- ``from __future__ import annotations`` first.
- Modern ``X | None`` and ``list[...]`` typing (no ``Optional``/``List``).
- Frozen dataclasses for immutable audit-log records (matches Spec #5's
  ``SkillTransition`` pattern).
- ``Protocol`` + ``runtime_checkable`` so callers can isinstance-check
  without a static type-checker.
- ``pathlib.Path`` not used here — this module does no filesystem I/O.
- ``oneiric.logging`` style: stdlib ``logging.getLogger(__name__)`` (matches
  Spec #5 / Substrate A's existing project pattern).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Immutable record of a single activation (read shape)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdapterSettingsVersion:
    """Immutable record of one settings activation for a single adapter.

    Mirrors the Dhara ``adapter_settings_versions`` row schema
    (Spec #8 §Storage Schema). Frozen + append-only by design: history is
    preserved, no edits, no deletes. The ``(adapter_id, version)`` pair is
    the natural primary key.

    Parameters
    ----------
    adapter_id:
        Stable adapter identifier (e.g. ``"prefect"``, ``"llamaindex"``).
    version:
        Monotonic per-adapter version number. Plan 4's ``TrackedSettings``
        computes this; Spec #8 only consumes it.
    settings_hash:
        SHA-256 (or equivalent) of the canonicalised settings payload.
        Plan 4's ``TrackedSettings`` computes this.
    activated_at:
        UTC timestamp the activation became effective. Plan 4 stamps
        this at the moment Oneiric commits the change.
    activated_by:
        ``user_id`` (e.g. ``"alice"``) or system actor (e.g.
        ``"system:deploy"``, ``"system:mcp"``).
    notes:
        Free-form operator note (``""`` when absent). Optional; defaults
        to empty string.
    """

    adapter_id: str
    version: int
    settings_hash: str
    activated_at: datetime
    activated_by: str
    notes: str = ""


# ---------------------------------------------------------------------------
# Write payload (what callers hand to record_activation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SettingsActivationRecord:
    """Caller-facing payload describing a single activation event.

    This is what Plan 4's ``TrackedSettings`` (and any other upstream
    source of activation truth) constructs and hands to
    ``record_activation``. It carries the data needed to write the
    activation but does NOT include ``activated_at`` — the persister
    stamps that at save time (or, for the Dhara implementation, Dhara
    stamps it via its ``activated_at`` column on INSERT).

    The frozen dataclass mirrors Spec #5's ``SkillTransition`` shape:
    immutable, audit-log friendly, hashable.
    """

    adapter_id: str
    version: int
    settings_hash: str
    activated_by: str
    notes: str = ""
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Persister interface
# ---------------------------------------------------------------------------


@runtime_checkable
class SettingsActivationPersister(Protocol):
    """Persistence contract for :class:`SettingsActivationRecord`.

    Implementations must:

    - Accept a single record via :meth:`save`.
    - Reject a second save for the same ``(adapter_id, version)`` pair
      (the natural primary key) by raising :class:`ValueError`.
    - Return the full insertion-ordered history via :meth:`history`.
    - Return the filtered history via :meth:`history_for`.
    - Return shallow copies from ``history`` / ``history_for`` so callers
      cannot mutate internal state.

    The Dhara-backed implementation (planned for Workstream C substrate)
    will satisfy this protocol by INSERTing into ``adapter_settings_versions``
    and reading via ``SELECT ... ORDER BY recorded_at``.
    """

    def save(self, record: SettingsActivationRecord) -> None:
        """Persist a single activation record. Raises ``ValueError`` on
        duplicate ``(adapter_id, version)``."""
        ...

    def history(self) -> list[SettingsActivationRecord]:
        """Return all records in insertion order."""
        ...

    def history_for(self, adapter_id: str) -> list[SettingsActivationRecord]:
        """Return records for one ``adapter_id`` in insertion order."""
        ...


# ---------------------------------------------------------------------------
# In-memory implementation (v0)
# ---------------------------------------------------------------------------


class InMemorySettingsActivationPersister:
    """In-memory implementation of :class:`SettingsActivationPersister`.

    Suitable for unit tests, local development, and the dhara-still-pending
    Workstream C. Stores records in a list keyed by
    ``(adapter_id, version)`` so PK collisions raise on ``save`` rather
    than silently overwriting history.

    Matches Spec #5's ``InMemorySkillPipeline`` shape so the two substrates
    stay symmetric.
    """

    def __init__(self) -> None:
        self._records: list[SettingsActivationRecord] = []
        self._seen_keys: set[tuple[str, int]] = set()

    def save(self, record: SettingsActivationRecord) -> None:
        key = (record.adapter_id, record.version)
        if key in self._seen_keys:
            raise ValueError(f"duplicate (adapter_id, version): {key!r}")
        self._seen_keys.add(key)
        self._records.append(record)
        logger.debug(
            "settings activation recorded",
            extra={
                "adapter_id": record.adapter_id,
                "version": record.version,
                "activated_by": record.activated_by,
            },
        )

    def history(self) -> list[SettingsActivationRecord]:
        # Shallow copy so callers cannot mutate internal state.
        return list(self._records)

    def history_for(self, adapter_id: str) -> list[SettingsActivationRecord]:
        return [r for r in self._records if r.adapter_id == adapter_id]


# ---------------------------------------------------------------------------
# Dhara-backed implementation stub
# ---------------------------------------------------------------------------


class DharaSettingsActivationPersister:
    """Stub for the Dhara-backed implementation.

    The Dhara ``adapter_settings_versions`` table is the durable backing
    store for this substrate. Until the Dhara substrate lands
    (Workstream C — Day 9 of the substrate plan), this stub raises
    ``NotImplementedError`` so the call site is documented and
    import-time visible, but no Dhara write occurs.

    TODO(Workstream C - substrate): replace ``save`` with a Dhara INSERT
    via ``mahavishnu.core.dhara_client.execute`` using the SQL::

        INSERT INTO adapter_settings_versions
            (version_id, adapter_id, version_number, config,
             activated_at, deactivated_at, activated_by, notes)
        VALUES (?, ?, ?, ?, ?, NULL, ?, ?)

    The follow-up must keep the append-only invariant by routing any
    DELETE / UPDATE through the migration runner's deny list.
    """

    def save(self, record: SettingsActivationRecord) -> None:
        raise NotImplementedError(
            "DharaSettingsActivationPersister is a stub. "
            "TODO(Workstream C - substrate): wire INSERT INTO "
            "adapter_settings_versions via DharaThinClient.execute. "
            f"Would have recorded: adapter_id={record.adapter_id!r} "
            f"version={record.version} settings_hash={record.settings_hash[:12]}..."
        )

    def history(self) -> list[SettingsActivationRecord]:
        raise NotImplementedError(
            "DharaSettingsActivationPersister.history() pending Workstream C substrate."
        )

    def history_for(self, adapter_id: str) -> list[SettingsActivationRecord]:
        raise NotImplementedError(
            "DharaSettingsActivationPersister.history_for() pending Workstream C substrate."
        )


# ---------------------------------------------------------------------------
# Single entry point used by upstream callers
# ---------------------------------------------------------------------------


def record_activation(
    record: SettingsActivationRecord,
    *,
    persister: SettingsActivationPersister,
) -> None:
    """Route a single activation record to the configured persister.

    This is the single entry point Plan 4's ``TrackedSettings`` (and any
    other upstream source) will call. Keeping the call site stable lets
    the in-memory and Dhara-backed implementations swap without touching
    callers.

    Parameters
    ----------
    record:
        The activation event. ``adapter_id``, ``version``, ``settings_hash``,
        and ``activated_by`` are required.
    persister:
        The destination persister. Must satisfy
        :class:`SettingsActivationPersister`. The :class:`DharaSettingsActivationPersister`
        stub raises ``NotImplementedError`` until Workstream C lands.

    Raises
    ------
    ValueError
        If the persister rejects the record as a duplicate
        ``(adapter_id, version)``.
    NotImplementedError
        If the persister is the Dhara stub (current state).
    """
    persister.save(record)


__all__ = [
    "AdapterSettingsVersion",
    "DharaSettingsActivationPersister",
    "InMemorySettingsActivationPersister",
    "SettingsActivationPersister",
    "SettingsActivationRecord",
    "record_activation",
]
