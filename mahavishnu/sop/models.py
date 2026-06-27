"""Frozen dataclasses for SOP evolution (Spec #7).

Three models:

- ``ProjectSOP`` — a single SOP file scoped to a project. Versioned so
  operators can audit evolution over time. ``last_failure_id`` and
  ``last_evolved_at`` link the SOP to the failure mode that last
  triggered a proposal and the timestamp that proposal applied.
- ``FailureModeCatalogEntry`` — a counter for one (project, fingerprint)
  tuple. ``occurrences`` is monotonically increasing. The first/last
  seen timestamps are populated by the persister, not by the model.
- ``SOPSuggestion`` — a proposed edit pending operator review. ``status``
  defaults to ``"pending"``; the plan forbids autonomous mutation so
  suggestions never auto-apply.

All three are ``frozen=True`` — once written, they cannot be edited in
place. This mirrors the audit-log discipline of Spec #5 (three-zone skill
pipeline) and Substrate WS-A.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ProjectSOP:
    """A single SOP file scoped to a project.

    Mirrors the Dhara ``project_sops`` table schema (Workstream C).
    """

    project_id: str
    name: str
    body: str
    version: int
    last_failure_id: str | None = None
    last_evolved_at: datetime | None = None


@dataclass(frozen=True)
class FailureModeCatalogEntry:
    """A counter for one (project, fingerprint) failure-mode tuple.

    Mirrors the Dhara ``failure_mode_catalog`` table schema (Workstream C).
    """

    failure_mode_id: str
    project_id: str
    fingerprint: str
    sop_name: str
    occurrences: int
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


@dataclass(frozen=True)
class SOPSuggestion:
    """A proposed SOP edit pending operator review.

    ``status`` is one of: ``"pending"`` (default), ``"approved"``,
    ``"rejected"``, ``"applied"``. The plan forbids autonomous mutation,
    so suggestions never transition to ``applied`` without an operator
    decision.
    """

    suggestion_id: str
    project_id: str
    sop_name: str
    failure_mode_id: str
    proposed_body: str
    rationale: str
    status: str = "pending"