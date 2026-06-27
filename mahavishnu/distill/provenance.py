"""Source provenance gate for the Plan 5 distillation pipeline.

Plan 5 audit finding H4: a compromised workflow run is the entry point
for poisoned distillation. The reviewer-identity gate (H6,
``mahavishnu.distill.reviewer``) protects the reviewer side. H4 closes
the other half — the *source* side — by demanding that every run
record admitted into the distiller prove it came from a trusted
Mahavishnu workflow execution.

The gate is a pure function over a typed record:

- ``source_type=external`` is rejected outright (untrusted boundary —
  the conversation lives outside the Mahavishnu workflow executor).
- ``source_type=mahavishnu_workflow`` requires a reviewer identity. A
  missing or empty reviewer is rejected as unattributed. A present
  reviewer that is not in the configured allowlist is rejected as
  untrusted.
- ``source_type=mahavishnu_workflow`` with an allowlisted reviewer is
  accepted (PURE).
- Bootstrap mode (allowlist is None) preserves v1 single-tenant
  behavior: a mahavishnu_workflow record with ANY reviewer identity is
  accepted. The caller is expected to log a WARNING at the audit
  layer (the distiller does this) so operators notice before promoting
  distillers out of single-tenant use.

The distiller wires this gate into its pre-filter pipeline by calling
``check_source_purity(run_record, allowlist=...)`` for each candidate
session before invoking ``_synthesize_candidate``. Records that fail
the gate are logged and skipped — they NEVER reach the LLM synthesizer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


# Trusted source types — only runs from these are eligible for distillation.
TRUSTED_SOURCE_TYPE: str = "mahavishnu_workflow"

# Anything else is treated as external / untrusted.
EXTERNAL_SOURCE_SENTINELS: frozenset[str] = frozenset(
    {
        "external",
        "claude_code",
        "crackerjack",
        "manual",
        "migration",
        # Reserved for future boundary types; if a source_type is not
        # explicitly trusted AND not in this set, the conservative
        # behavior is to reject — see ``_classify_source_type``.
    },
)


class SourcePurity(StrEnum):
    """The four purity verdicts the gate can return.

    ``PURE`` — the record is eligible for distillation.
    ``REJECTED_EXTERNAL`` — source_type is not in the trusted set.
    ``REJECTED_UNATTRIBUTED`` — source_type is trusted but no reviewer
        identity is attached to the record.
    ``REJECTED_REVIEWER`` — source_type is trusted AND a reviewer is
        present BUT the reviewer is not in the configured allowlist.
    """

    PURE = "pure"
    REJECTED_EXTERNAL = "rejected_external"
    REJECTED_UNATTRIBUTED = "rejected_unattributed"
    REJECTED_REVIEWER = "rejected_reviewer"


@dataclass(frozen=True)
class ProvenanceDecision:
    """Frozen outcome of a ``check_source_purity`` call.

    Attributes:
        allowed: True iff the record is eligible for distillation.
        purity: Classification (see :class:`SourcePurity`).
        reason: Human-readable explanation (always populated — empty
            string only on the happy path with an allowlisted reviewer).
        reviewer_id: The reviewer identity on the record (None when
            absent). Echoed for forensic visibility.
        source_type: The source_type string on the record (None when
            absent). Echoed for forensic visibility.
    """

    allowed: bool
    purity: SourcePurity
    reason: str
    reviewer_id: str | None
    source_type: str | None


def _classify_source_type(raw: Any) -> tuple[str | None, bool]:
    """Return ``(normalized_source, is_external)``.

    - ``None`` when the field is missing or empty.
    - ``is_external`` is True when the value is NOT the trusted type
      (covers explicit external sentinels AND unknown strings — the
      conservative behavior).
    """
    if raw is None:
        return None, True
    text = str(raw).strip()
    if not text:
        return None, True
    lowered = text.lower()
    if lowered == TRUSTED_SOURCE_TYPE:
        return lowered, False
    # Known external sentinels are explicitly external; unknown values
    # are conservatively treated as external too — the distiller must
    # NOT silently trust a future source_type someone added to the
    # schema without updating this gate.
    return lowered, True


def _coerce_reviewer_id(raw: Any) -> str | None:
    """Normalize reviewer_id; empty string is treated as None."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def check_source_purity(
    run_record: Mapping[str, Any],
    *,
    allowlist: Iterable[str] | None = None,
) -> ProvenanceDecision:
    """Decide whether a workflow run record may feed the distiller.

    Args:
        run_record: A mapping with at minimum ``source_type`` and
            ``reviewer_id`` keys. ``run_id`` and ``session_id`` are
            tolerated but not required by this gate.
        allowlist: Optional iterable of allowed reviewer identities.
            ``None`` means bootstrap mode (any reviewer identity is
            accepted for trusted source_type records).

    Returns:
        A :class:`ProvenanceDecision` describing the verdict.
    """
    source_type, is_external = _classify_source_type(run_record.get("source_type"))
    reviewer_id = _coerce_reviewer_id(run_record.get("reviewer_id"))

    # Fast path: external or missing source_type → REJECTED_EXTERNAL.
    if is_external:
        if source_type is None:
            return ProvenanceDecision(
                allowed=False,
                purity=SourcePurity.REJECTED_EXTERNAL,
                reason=(
                    "Run record is missing source_type; cannot establish "
                    "a Mahavishnu workflow origin. External / unknown "
                    "sources are rejected by the H4 provenance gate."
                ),
                reviewer_id=reviewer_id,
                source_type=None,
            )
        return ProvenanceDecision(
            allowed=False,
            purity=SourcePurity.REJECTED_EXTERNAL,
            reason=(
                f"Run record source_type={source_type!r} is not a "
                f"trusted Mahavishnu workflow source. Only "
                f"{TRUSTED_SOURCE_TYPE!r} runs are eligible for "
                f"distillation. (H4 source provenance gate.)"
            ),
            reviewer_id=reviewer_id,
            source_type=source_type,
        )

    # source_type == TRUSTED_SOURCE_TYPE from here on.
    if reviewer_id is None:
        return ProvenanceDecision(
            allowed=False,
            purity=SourcePurity.REJECTED_UNATTRIBUTED,
            reason=(
                "Run record source_type is "
                f"{TRUSTED_SOURCE_TYPE!r} but reviewer_id is missing or "
                f"empty. Distillation requires an attributed reviewer "
                f"identity to prevent unattributed evidence from "
                f"feeding the synthesizer."
            ),
            reviewer_id=None,
            source_type=source_type,
        )

    # Bootstrap mode: any reviewer identity is accepted.
    if allowlist is None:
        return ProvenanceDecision(
            allowed=True,
            purity=SourcePurity.PURE,
            reason="",
            reviewer_id=reviewer_id,
            source_type=source_type,
        )

    allowed_set = frozenset(allowlist)
    if reviewer_id in allowed_set:
        return ProvenanceDecision(
            allowed=True,
            purity=SourcePurity.PURE,
            reason="",
            reviewer_id=reviewer_id,
            source_type=source_type,
        )

    return ProvenanceDecision(
        allowed=False,
        purity=SourcePurity.REJECTED_REVIEWER,
        reason=(
            f"Reviewer {reviewer_id!r} is not in the configured "
            f"MAHAVISHNU_PUBLISHER_ALLOWLIST. H4 requires an allowlisted "
            f"reviewer identity for distillation."
        ),
        reviewer_id=reviewer_id,
        source_type=source_type,
    )


__all__ = [
    "EXTERNAL_SOURCE_SENTINELS",
    "ProvenanceDecision",
    "SourcePurity",
    "TRUSTED_SOURCE_TYPE",
    "check_source_purity",
]
