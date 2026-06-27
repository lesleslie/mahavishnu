"""Project-scoped SOP evolution (Spec #7).

This package ships the per-deployment SOP substrate:

- ``models`` — frozen dataclasses for ``ProjectSOP``,
  ``FailureModeCatalogEntry``, and ``SOPSuggestion``.
- ``evolution`` — ``EvolutionTrigger`` evaluates the catalog and proposes
  SOP edits once a failure mode crosses its threshold.
- ``persisters`` — ``SOPPersister`` Protocol with an ``InMemorySOPPersister``
  implementation and an ``HttpSOPPersister`` typed stub.

Substrate status (per the implementation plan): sql_blocked + http_blocked.
The Dhara-backed implementation is a follow-up (Workstream C) and reuses
the same ``SOPPersister`` Protocol so callers do not break when it lands.
"""

from __future__ import annotations

from .evolution import EvolutionTrigger, EvolutionTriggerDecision
from .models import FailureModeCatalogEntry, ProjectSOP, SOPSuggestion
from .persisters import (
    HttpSOPPersister,
    InMemorySOPPersister,
    SOPPersister,
)

__all__ = [
    "EvolutionTrigger",
    "EvolutionTriggerDecision",
    "FailureModeCatalogEntry",
    "HttpSOPPersister",
    "InMemorySOPPersister",
    "ProjectSOP",
    "SOPSuggestion",
    "SOPPersister",
]