"""Confidence ceiling gate (Spec #3, Phase 1).

Pure-function cap on reported confidence based on enumerable doubt
(open questions + unchecked sources). Caps do not raise; over-confidence
is calibration, not a rule violation.

The arithmetic cap comes from the ``Building a Production Agent Harness``
article's A1 gate, scaled to a 0-100 integer scale:

    cap = max(0, 100 - (|open_questions| * 8) - (|unchecked_sources| * 5))

The cap is enumerable: given any persisted report, the cap is computable
from the structural state of the report alone.

The ``MAHAVISHNU_CONFIDENCE_CEILING`` env var (default ``0.85`` = 85) sets
an operator-imposed ceiling that is applied alongside the structural cap;
whichever is lower wins. The env var is expressed as a 0-1 float and is
clamped to [0, 100] after multiplication by 100.

Side effects (best-effort, never raise):

- WARNING log when capping occurs.
- Akosha anomaly emission (``mahavishnu.akosha_client.emit_anomaly``) when
  capping occurs. The import is intentionally lazy: if Akosha is not
  configured, the ImportError is swallowed and only the warning log
  remains. v2.0 makes this mandatory.
"""

from __future__ import annotations

import os
from copy import deepcopy

from oneiric.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants (spec article scaled to 0-100)
# ---------------------------------------------------------------------------

OPEN_QUESTION_PENALTY: int = 8
UNCHECKED_SOURCE_PENALTY: int = 5
FLOOR: int = 0
CEILING: int = 100

DEFAULT_ENV_CAP_FLOAT: float = 0.85
ENV_VAR_NAME: str = "MAHAVISHNU_CONFIDENCE_CEILING"


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def compute_confidence_cap(report: dict) -> int:
    """Compute the structural ceiling for an iteration report's confidence.

    Pure function; no IO, no shared state. Returns ``int`` in ``[FLOOR, CEILING]``.

    Missing ``open_questions`` or ``unchecked_sources`` default to empty
    lists (see spec's Error Handling table).
    """
    open_q_count = len(report.get("open_questions", []) or [])
    unchecked_count = len(report.get("unchecked_sources", []) or [])
    raw = (
        CEILING
        - (open_q_count * OPEN_QUESTION_PENALTY)
        - (unchecked_count * UNCHECKED_SOURCE_PENALTY)
    )
    return max(FLOOR, raw)


def get_confidence_ceiling_cap() -> int:
    """Read the operator-imposed cap from ``MAHAVISHNU_CONFIDENCE_CEILING``.

    Env var value is a 0-1 float (e.g. ``0.85`` -> 85). Invalid values
    fall back to ``DEFAULT_ENV_CAP_FLOAT``. Out-of-range values are
    clamped to ``[0, 100]`` after scaling.
    """
    raw = os.environ.get(ENV_VAR_NAME)
    if raw is None:
        return int(DEFAULT_ENV_CAP_FLOAT * CEILING)

    try:
        as_float = float(raw)
    except ValueError:
        return int(DEFAULT_ENV_CAP_FLOAT * CEILING)

    scaled = int(round(as_float * CEILING))
    return max(FLOOR, min(CEILING, scaled))


def effective_cap(report: dict) -> int:
    """Return the lower of the structural cap and the operator env cap."""
    structural = compute_confidence_cap(report)
    operator = get_confidence_ceiling_cap()
    return min(structural, operator)


# ---------------------------------------------------------------------------
# Side-effect-bearing gate
# ---------------------------------------------------------------------------


def _try_emit_anomaly(
    *,
    report: dict,
    reported: int,
    cap: int,
) -> None:
    """Best-effort Akosha anomaly emission.

    Silent when ``mahavishnu.akosha_client.emit_anomaly`` is not importable
    (Akosha not configured). Logs and swallows any exception from the call
    itself; never propagates.
    """
    try:
        from mahavishnu.akosha_client import emit_anomaly
    except ImportError:
        return
    except Exception:
        logger.exception("failed to import akosha emit_anomaly")
        return

    try:
        emit_anomaly(
            kind="confidence_capped",
            workflow_id=report.get("workflow_id"),
            iteration_index=report.get("iteration_index"),
            reported_confidence=reported,
            computed_cap=cap,
        )
    except Exception:
        logger.exception("failed to emit akosha anomaly for confidence cap")


def apply_confidence_ceiling(report: dict) -> dict:
    """Apply the confidence ceiling to an iteration report.

    If ``report["confidence"]`` exceeds the effective cap (the lower of
    the structural cap and the operator env cap), returns a deep copy with
    ``confidence`` replaced by the cap. Otherwise returns the report
    reference unchanged (no copy).

    Side effects when capping occurs:

    - WARNING log including workflow_id, iteration_index, reported
      confidence, computed cap, open_questions_count, unchecked_sources_count.
    - Best-effort Akosha anomaly emission (silent if not configured).

    Does NOT raise. Over-confidence is calibration, not a rule violation.
    """
    cap = effective_cap(report)
    reported = report.get("confidence", 0)

    if reported <= cap:
        return report

    capped = deepcopy(report)
    capped["confidence"] = cap
    logger.warning(
        "confidence capped by ceiling",
        extra={
            "workflow_id": report.get("workflow_id"),
            "iteration_index": report.get("iteration_index"),
            "reported_confidence": reported,
            "computed_cap": cap,
            "open_questions_count": len(report.get("open_questions", []) or []),
            "unchecked_sources_count": len(
                report.get("unchecked_sources", []) or []
            ),
        },
    )
    _try_emit_anomaly(report=report, reported=reported, cap=cap)
    return capped


__all__ = [
    "CEILING",
    "DEFAULT_ENV_CAP_FLOAT",
    "ENV_VAR_NAME",
    "FLOOR",
    "OPEN_QUESTION_PENALTY",
    "UNCHECKED_SOURCE_PENALTY",
    "apply_confidence_ceiling",
    "compute_confidence_cap",
    "effective_cap",
    "get_confidence_ceiling_cap",
]
