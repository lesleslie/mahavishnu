<<<<<<< HEAD
"""Distilled Workflows substrate (Plan 5 Phase A.0+).

Public surface is intentionally narrow: re-export the storage helpers,
the distiller entry point, the reviewer trust root (Phase H6), and the
source provenance gate (Phase H4).
=======
"""Distilled Workflows substrate (Plan 5 Phase A.0).

Spec #3 wiring: this package hosts the distiller's output stage.
The confidence ceiling gate (see
``mahavishnu.core.events.confidence_ceiling``) is applied to the
distiller's output records via :func:`cap_distiller_output`.
>>>>>>> feat/spec-3-confidence-ceiling
"""

from __future__ import annotations

<<<<<<< HEAD
from mahavishnu.distill.llm_usage import CostCeilingExceeded, UsageTracker
from mahavishnu.distill.provenance import (
    ProvenanceDecision,
    SourcePurity,
)
from mahavishnu.distill.reviewer import (
    ReviewerDecision,
    ReviewerIdentity,
    ReviewerSource,
)

__all__ = [
    "CostCeilingExceeded",
    "ProvenanceDecision",
    "ReviewerDecision",
    "ReviewerIdentity",
    "ReviewerSource",
    "SourcePurity",
    "UsageTracker",
]
=======
from mahavishnu.distill.consumer import cap_distiller_output

__all__ = ["cap_distiller_output"]
>>>>>>> feat/spec-3-confidence-ceiling
