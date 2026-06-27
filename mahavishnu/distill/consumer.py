"""Spec #3 wiring: distiller output consumer.

The distiller produces structured output records (confidence-bearing
dicts) describing skill zone transitions, ingestion summaries, or
workflow results. The :func:`cap_distiller_output` function applies the
Spec #3 confidence ceiling to those records before they leave the
distiller, so downstream consumers (audit log, persistence, MCP tools)
never see over-confident self-reports.

The function is pure modulo side effects from the gate itself (warning
log, best-effort Akosha anomaly emission). It is the single integration
point between the gate and the distiller's output stage.
"""

from __future__ import annotations

from mahavishnu.core.events.confidence_ceiling import apply_confidence_ceiling


def cap_distiller_output(record: dict) -> dict:
    """Apply the Spec #3 confidence ceiling to a distiller output record.

    Pass-through to :func:`apply_confidence_ceiling` with the distiller's
    standard record shape. Returns the same reference when the record is
    within the cap; returns a capped copy otherwise.

    Args:
        record: A distiller output dict containing at least ``confidence``,
            ``open_questions``, and ``unchecked_sources`` keys.

    Returns:
        The same ``record`` reference when within the cap, otherwise a
        capped deep copy.
    """
    return apply_confidence_ceiling(record)


__all__ = ["cap_distiller_output"]
