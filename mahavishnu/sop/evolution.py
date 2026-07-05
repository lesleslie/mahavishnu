"""EvolutionTrigger — propose an SOP edit once a failure mode fires N times.

Spec #7 architecture:

- The trigger is a pure function over the failure-mode catalog.
- It does **not** mutate state — the caller (cron or retrospective
  consumer) is responsible for persisting the resulting ``SOPSuggestion``.
- Threshold default is 3 (per the plan: 3/10 → suggestion, 6/10 → alert;
  we only model suggestion here; alerting is a downstream concern).
- ``evaluate_batch`` is a convenience that returns one decision per
  input entry, in order.

The trigger never auto-applies suggestions — Spec #7 forbids autonomous
SOP mutation. Operators review via ``mahavishnu sop show`` / ``propose``.
"""

from __future__ import annotations

from dataclasses import dataclass
import uuid

from .models import FailureModeCatalogEntry, SOPSuggestion

# Plan-calibrated default: 3/10 occurrences → suggestion.
DEFAULT_THRESHOLD = 3


@dataclass(frozen=True)
class EvolutionTriggerDecision:
    """The outcome of evaluating a single catalog entry.

    When ``propose`` is True, ``suggestion`` is populated and the caller
    is expected to persist it via ``SOPPersister.save_suggestion``.
    When ``propose`` is False, ``suggestion`` is None and ``reason``
    explains why no proposal was generated.
    """

    propose: bool
    reason: str
    suggestion: SOPSuggestion | None = None


class EvolutionTrigger:
    """Evaluate the failure-mode catalog and propose SOP edits.

    Stateless. Reusable across projects. The threshold is the only knob.
    """

    def __init__(self, threshold: int = DEFAULT_THRESHOLD) -> None:
        if threshold < 1:
            raise ValueError(f"threshold must be >= 1, got {threshold}")
        self.threshold = threshold

    def evaluate(self, entry: FailureModeCatalogEntry) -> EvolutionTriggerDecision:
        """Return a decision for one catalog entry."""
        if entry.occurrences < self.threshold:
            return EvolutionTriggerDecision(
                propose=False,
                reason=(f"occurrences={entry.occurrences} below threshold={self.threshold}"),
            )
        suggestion = self._build_suggestion(entry)
        return EvolutionTriggerDecision(
            propose=True,
            suggestion=suggestion,
            reason=(f"occurrences={entry.occurrences} >= threshold={self.threshold}"),
        )

    def evaluate_batch(
        self,
        entries: list[FailureModeCatalogEntry],
    ) -> list[EvolutionTriggerDecision]:
        """Return one decision per entry, in input order."""
        return [self.evaluate(e) for e in entries]

    def _build_suggestion(self, entry: FailureModeCatalogEntry) -> SOPSuggestion:
        """Build the proposed ``SOPSuggestion`` for a triggered entry.

        Body is a conservative placeholder — the operator is expected to
        edit it during review. We always embed the SOP name and the
        failure fingerprint so the operator sees what triggered the
        suggestion.
        """
        suggestion_id = f"sug-{uuid.uuid4().hex[:12]}"
        proposed_body = (
            f"# Proposed update for SOP '{entry.sop_name}'\n\n"
            f"# Trigger: failure fingerprint '{entry.fingerprint}' "
            f"fired {entry.occurrences} times (threshold={self.threshold}).\n"
            f"# Replace this body with the operator-approved edit.\n"
        )
        rationale = (
            f"failure_mode_id={entry.failure_mode_id} reached "
            f"{entry.occurrences} occurrences (threshold={self.threshold}) "
            f"for project {entry.project_id}"
        )
        return SOPSuggestion(
            suggestion_id=suggestion_id,
            project_id=entry.project_id,
            sop_name=entry.sop_name,
            failure_mode_id=entry.failure_mode_id,
            proposed_body=proposed_body,
            rationale=rationale,
        )
