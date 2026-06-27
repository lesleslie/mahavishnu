"""SOP persisters (Spec #7).

Two implementations:

- ``InMemorySOPPersister`` — used for tests, dev, and the Phase 3
  in-memory v0 documented in the implementation plan.
- ``HttpSOPPersister`` — typed stub that raises ``NotImplementedError``
  on every call. The Dhara-backed implementation lands with Workstream C
  (sql_blocked + http_blocked in the substrate status). Keeping the stub
  around exercises the import site and pins the contract callers depend
  on.

Both implement the ``SOPPersister`` Protocol so callers (CLI, evolution
trigger) stay substrate-agnostic. The Dhara implementation will be a
third conformant implementation and require no caller changes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from .models import FailureModeCatalogEntry, ProjectSOP, SOPSuggestion


@runtime_checkable
class SOPPersister(Protocol):
    """Persistence boundary for SOP evolution state.

    The Dhara-backed implementation will conform to this Protocol and
    back it with the ``project_sops``, ``sop_suggestions``, and
    ``failure_mode_catalog`` tables (Workstream C).
    """

    # --- ProjectSOP CRUD -------------------------------------------------
    def save(self, sop: ProjectSOP) -> None: ...
    def get(self, project_id: str, name: str) -> ProjectSOP | None: ...
    def list_for_project(self, project_id: str) -> list[ProjectSOP]: ...

    # --- SOPSuggestion CRUD ---------------------------------------------
    def save_suggestion(self, suggestion: SOPSuggestion) -> None: ...
    def get_suggestion(self, suggestion_id: str) -> SOPSuggestion | None: ...
    def list_suggestions(self, project_id: str) -> list[SOPSuggestion]: ...

    # --- FailureModeCatalog ---------------------------------------------
    def record_failure_mode(
        self,
        failure_mode_id: str,
        project_id: str,
        fingerprint: str,
        sop_name: str,
    ) -> None: ...
    def list_failure_modes(self, project_id: str) -> list[FailureModeCatalogEntry]: ...


class InMemorySOPPersister:
    """In-memory implementation of ``SOPPersister``.

    Suitable for tests, dev, and the Phase 3 in-memory v0. Stores all
    state in plain dicts. Not thread-safe; not persistent.
    """

    def __init__(self) -> None:
        # Keyed by (project_id, name).
        self._sops: dict[tuple[str, str], ProjectSOP] = {}
        # Keyed by suggestion_id.
        self._suggestions: dict[str, SOPSuggestion] = {}
        # Keyed by (project_id, fingerprint).
        self._failure_modes: dict[tuple[str, str], FailureModeCatalogEntry] = {}

    # --- ProjectSOP CRUD -------------------------------------------------
    def save(self, sop: ProjectSOP) -> None:
        self._sops[(sop.project_id, sop.name)] = sop

    def get(self, project_id: str, name: str) -> ProjectSOP | None:
        return self._sops.get((project_id, name))

    def list_for_project(self, project_id: str) -> list[ProjectSOP]:
        return [s for (pid, _), s in self._sops.items() if pid == project_id]

    # --- SOPSuggestion CRUD ---------------------------------------------
    def save_suggestion(self, suggestion: SOPSuggestion) -> None:
        self._suggestions[suggestion.suggestion_id] = suggestion

    def get_suggestion(self, suggestion_id: str) -> SOPSuggestion | None:
        return self._suggestions.get(suggestion_id)

    def list_suggestions(self, project_id: str) -> list[SOPSuggestion]:
        return [
            s for s in self._suggestions.values() if s.project_id == project_id
        ]

    # --- FailureModeCatalog ---------------------------------------------
    def record_failure_mode(
        self,
        failure_mode_id: str,
        project_id: str,
        fingerprint: str,
        sop_name: str,
    ) -> None:
        key = (project_id, fingerprint)
        now = datetime.now(UTC)
        existing = self._failure_modes.get(key)
        if existing is None:
            # First time we have seen this fingerprint for this project.
            entry = FailureModeCatalogEntry(
                failure_mode_id=failure_mode_id,
                project_id=project_id,
                fingerprint=fingerprint,
                sop_name=sop_name,
                occurrences=1,
                first_seen_at=now,
                last_seen_at=now,
            )
        else:
            # Frozen dataclass — rebuild with bumped counter + timestamp.
            entry = FailureModeCatalogEntry(
                failure_mode_id=existing.failure_mode_id,
                project_id=existing.project_id,
                fingerprint=existing.fingerprint,
                sop_name=existing.sop_name,
                occurrences=existing.occurrences + 1,
                first_seen_at=existing.first_seen_at or now,
                last_seen_at=now,
            )
        self._failure_modes[key] = entry

    def list_failure_modes(self, project_id: str) -> list[FailureModeCatalogEntry]:
        return [
            e for (pid, _), e in self._failure_modes.items() if pid == project_id
        ]


class HttpSOPPersister:
    """Typed stub for the future HTTP-backed ``SOPPersister``.

    Substrate status (per the implementation plan): ``http_blocked``.
    Every method raises ``NotImplementedError`` so callers fail loud at
    the import site instead of silently returning empty data.

    The Workstream C implementation will fill these out against the
    Dhara HTTP surface; the contract here pins the method signatures and
    return types callers depend on.
    """

    def __init__(self, base_url: str, timeout_seconds: float = 5.0) -> None:
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds

    @property
    def base_url(self) -> str:
        return self._base_url

    # --- ProjectSOP CRUD -------------------------------------------------
    def save(self, sop: ProjectSOP) -> None:
        raise NotImplementedError(
            "HttpSOPPersister.save is a Phase 3 stub. "
            "See Spec #7 Workstream C (substrate) for the Dhara HTTP "
            "implementation."
        )

    def get(self, project_id: str, name: str) -> ProjectSOP | None:
        raise NotImplementedError(
            "HttpSOPPersister.get is a Phase 3 stub. "
            "See Spec #7 Workstream C (substrate) for the Dhara HTTP "
            "implementation."
        )

    def list_for_project(self, project_id: str) -> list[ProjectSOP]:
        raise NotImplementedError(
            "HttpSOPPersister.list_for_project is a Phase 3 stub. "
            "See Spec #7 Workstream C (substrate) for the Dhara HTTP "
            "implementation."
        )

    # --- SOPSuggestion CRUD ---------------------------------------------
    def save_suggestion(self, suggestion: SOPSuggestion) -> None:
        raise NotImplementedError(
            "HttpSOPPersister.save_suggestion is a Phase 3 stub. "
            "See Spec #7 Workstream C (substrate) for the Dhara HTTP "
            "implementation."
        )

    def get_suggestion(self, suggestion_id: str) -> SOPSuggestion | None:
        raise NotImplementedError(
            "HttpSOPPersister.get_suggestion is a Phase 3 stub. "
            "See Spec #7 Workstream C (substrate) for the Dhara HTTP "
            "implementation."
        )

    def list_suggestions(self, project_id: str) -> list[SOPSuggestion]:
        raise NotImplementedError(
            "HttpSOPPersister.list_suggestions is a Phase 3 stub. "
            "See Spec #7 Workstream C (substrate) for the Dhara HTTP "
            "implementation."
        )

    # --- FailureModeCatalog ---------------------------------------------
    def record_failure_mode(
        self,
        failure_mode_id: str,
        project_id: str,
        fingerprint: str,
        sop_name: str,
    ) -> None:
        raise NotImplementedError(
            "HttpSOPPersister.record_failure_mode is a Phase 3 stub. "
            "See Spec #7 Workstream C (substrate) for the Dhara HTTP "
            "implementation."
        )

    def list_failure_modes(self, project_id: str) -> list[FailureModeCatalogEntry]:
        raise NotImplementedError(
            "HttpSOPPersister.list_failure_modes is a Phase 3 stub. "
            "See Spec #7 Workstream C (substrate) for the Dhara HTTP "
            "implementation."
        )


__all__ = [
    "SOPPersister",
    "InMemorySOPPersister",
    "HttpSOPPersister",
]