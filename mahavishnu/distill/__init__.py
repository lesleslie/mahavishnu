"""Distilled Workflows substrate (Plan 5 Phase A.0+).

Public surface is intentionally narrow: re-export the storage helpers,
the distiller entry point, the reviewer trust root (Phase H6), the
source provenance gate (Phase H4), and the confidence ceiling consumer
(Spec #3) for the distiller's output stage.
"""

from __future__ import annotations

from mahavishnu.distill.consumer import cap_distiller_output
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
    "cap_distiller_output",
]
