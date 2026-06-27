"""Distilled Workflows substrate (Plan 5 Phase A.0).

Spec #3 wiring: this package hosts the distiller's output stage.
The confidence ceiling gate (see
``mahavishnu.core.events.confidence_ceiling``) is applied to the
distiller's output records via :func:`cap_distiller_output`.
"""

from __future__ import annotations

from mahavishnu.distill.consumer import cap_distiller_output

__all__ = ["cap_distiller_output"]
