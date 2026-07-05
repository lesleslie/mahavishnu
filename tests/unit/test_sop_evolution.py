"""Unit tests for mahavishnu/sop/ (Spec #7: project-scoped-sop-evolution).

Phase 3 scope: ProjectSOP model, FailureModeCatalog entry, EvolutionTrigger
threshold logic, and InMemory + HTTP CRUD persisters.

Substrate status (per the implementation plan): sql_blocked + http_blocked,
so the Dhara/SQL backend is intentionally a follow-up. These tests pin the
interface and the InMemory implementation; the HTTP persister is a typed
stub that exercises the call site at import time.

The substrate swap-in mirrors Spec #5 (three-zone skill pipeline) and
Substrate WS-A (dhara_client): the Dhara-backed implementations land with
Workstream C and reuse the same Protocol/abstract surface so callers do
not break.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mahavishnu.sop.evolution import EvolutionTrigger, EvolutionTriggerDecision
from mahavishnu.sop.models import (
    FailureModeCatalogEntry,
    ProjectSOP,
    SOPSuggestion,
)
from mahavishnu.sop.persisters import (
    HttpSOPPersister,
    InMemorySOPPersister,
    SOPPersister,
)

# ---------------------------------------------------------------------------
# ProjectSOP model
# ---------------------------------------------------------------------------


class TestProjectSOP:
    def test_required_fields(self) -> None:
        sop = ProjectSOP(
            project_id="proj-1",
            name="anti-ai-flavor",
            body="Avoid 'delve into', 'tapestry', etc.",
            version=1,
        )
        assert sop.project_id == "proj-1"
        assert sop.name == "anti-ai-flavor"
        assert "delve into" in sop.body
        assert sop.version == 1

    def test_default_optional_fields(self) -> None:
        sop = ProjectSOP(
            project_id="proj-1",
            name="test-sop",
            body="body",
            version=1,
        )
        # No failure has touched this SOP yet.
        assert sop.last_failure_id is None
        assert sop.last_evolved_at is None

    def test_evolved_fields_set(self) -> None:
        ts = datetime(2026, 6, 27, 12, 0, 0, tzinfo=UTC)
        sop = ProjectSOP(
            project_id="proj-1",
            name="test-sop",
            body="updated body",
            version=2,
            last_failure_id="fail-42",
            last_evolved_at=ts,
        )
        assert sop.last_failure_id == "fail-42"
        assert sop.last_evolved_at == ts
        assert sop.version == 2

    def test_immutable_after_creation(self) -> None:
        sop = ProjectSOP(
            project_id="proj-1",
            name="sop",
            body="body",
            version=1,
        )
        with pytest.raises(Exception):
            sop.version = 99  # type: ignore[misc]

    def test_equality_by_content(self) -> None:
        a = ProjectSOP(project_id="p", name="n", body="b", version=1)
        b = ProjectSOP(project_id="p", name="n", body="b", version=1)
        # Frozen dataclass: __eq__ on all fields.
        assert a == b

    def test_inequality_on_version(self) -> None:
        a = ProjectSOP(project_id="p", name="n", body="b", version=1)
        b = ProjectSOP(project_id="p", name="n", body="b", version=2)
        assert a != b


# ---------------------------------------------------------------------------
# FailureModeCatalogEntry model
# ---------------------------------------------------------------------------


class TestFailureModeCatalogEntry:
    def test_required_fields(self) -> None:
        entry = FailureModeCatalogEntry(
            failure_mode_id="fm-001",
            project_id="proj-1",
            fingerprint="ai-flavor:delve-into",
            sop_name="anti-ai-flavor",
            occurrences=0,
        )
        assert entry.failure_mode_id == "fm-001"
        assert entry.project_id == "proj-1"
        assert entry.fingerprint == "ai-flavor:delve-into"
        assert entry.sop_name == "anti-ai-flavor"
        assert entry.occurrences == 0

    def test_default_state(self) -> None:
        entry = FailureModeCatalogEntry(
            failure_mode_id="fm-001",
            project_id="proj-1",
            fingerprint="fp",
            sop_name="sop-1",
            occurrences=0,
        )
        assert entry.first_seen_at is None
        assert entry.last_seen_at is None

    def test_immutable_after_creation(self) -> None:
        entry = FailureModeCatalogEntry(
            failure_mode_id="fm-001",
            project_id="proj-1",
            fingerprint="fp",
            sop_name="sop-1",
            occurrences=0,
        )
        with pytest.raises(Exception):
            entry.occurrences = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SOPSuggestion model
# ---------------------------------------------------------------------------


class TestSOPSuggestion:
    def test_required_fields(self) -> None:
        suggestion = SOPSuggestion(
            suggestion_id="sug-1",
            project_id="proj-1",
            sop_name="anti-ai-flavor",
            failure_mode_id="fm-001",
            proposed_body="Avoid 'delve into' in opening paragraphs.",
            rationale="3 occurrences in last week.",
        )
        assert suggestion.suggestion_id == "sug-1"
        assert suggestion.project_id == "proj-1"
        assert suggestion.sop_name == "anti-ai-flavor"
        assert suggestion.failure_mode_id == "fm-001"
        assert "delve into" in suggestion.proposed_body
        assert "3 occurrences" in suggestion.rationale

    def test_default_status(self) -> None:
        suggestion = SOPSuggestion(
            suggestion_id="sug-1",
            project_id="proj-1",
            sop_name="sop-1",
            failure_mode_id="fm-1",
            proposed_body="body",
            rationale="why",
        )
        # Default to PENDING — operator reviews before apply.
        assert suggestion.status == "pending"

    def test_status_override(self) -> None:
        suggestion = SOPSuggestion(
            suggestion_id="sug-1",
            project_id="proj-1",
            sop_name="sop-1",
            failure_mode_id="fm-1",
            proposed_body="body",
            rationale="why",
            status="approved",
        )
        assert suggestion.status == "approved"

    def test_immutable_after_creation(self) -> None:
        suggestion = SOPSuggestion(
            suggestion_id="sug-1",
            project_id="proj-1",
            sop_name="sop-1",
            failure_mode_id="fm-1",
            proposed_body="body",
            rationale="why",
        )
        with pytest.raises(Exception):
            suggestion.status = "applied"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# EvolutionTrigger — threshold logic
# ---------------------------------------------------------------------------


class TestEvolutionTriggerThreshold:
    """The trigger proposes an SOP edit once a failure mode fires N times.

    Threshold default is 3 (per the plan: 3/10 → suggestion, 6/10 → alert).
    """

    def test_below_threshold_no_proposal(self) -> None:
        trigger = EvolutionTrigger(threshold=3)
        entry = FailureModeCatalogEntry(
            failure_mode_id="fm-1",
            project_id="proj-1",
            fingerprint="fp",
            sop_name="sop-1",
            occurrences=2,
        )
        decision = trigger.evaluate(entry)
        assert decision.propose is False
        assert decision.reason is not None

    def test_at_threshold_proposal(self) -> None:
        trigger = EvolutionTrigger(threshold=3)
        entry = FailureModeCatalogEntry(
            failure_mode_id="fm-1",
            project_id="proj-1",
            fingerprint="fp",
            sop_name="sop-1",
            occurrences=3,
        )
        decision = trigger.evaluate(entry)
        assert decision.propose is True
        assert decision.suggestion is not None
        assert decision.suggestion.sop_name == "sop-1"
        assert decision.suggestion.failure_mode_id == "fm-1"
        # Default body should at least reference the SOP name.
        assert decision.suggestion.sop_name in decision.suggestion.proposed_body

    def test_above_threshold_proposal(self) -> None:
        trigger = EvolutionTrigger(threshold=3)
        entry = FailureModeCatalogEntry(
            failure_mode_id="fm-1",
            project_id="proj-1",
            fingerprint="fp",
            sop_name="sop-1",
            occurrences=10,
        )
        decision = trigger.evaluate(entry)
        assert decision.propose is True

    def test_default_threshold_is_three(self) -> None:
        trigger = EvolutionTrigger()
        # Default per the plan: 3/10 → suggestion.
        assert trigger.threshold == 3

    def test_custom_threshold_respected(self) -> None:
        trigger = EvolutionTrigger(threshold=5)
        entry = FailureModeCatalogEntry(
            failure_mode_id="fm-1",
            project_id="proj-1",
            fingerprint="fp",
            sop_name="sop-1",
            occurrences=4,
        )
        decision = trigger.evaluate(entry)
        assert decision.propose is False

        entry_5 = FailureModeCatalogEntry(
            failure_mode_id="fm-1",
            project_id="proj-1",
            fingerprint="fp",
            sop_name="sop-1",
            occurrences=5,
        )
        decision_5 = trigger.evaluate(entry_5)
        assert decision_5.propose is True

    def test_evaluate_batch_proposes_for_each_above(self) -> None:
        trigger = EvolutionTrigger(threshold=2)
        entries = [
            FailureModeCatalogEntry(
                failure_mode_id="fm-1",
                project_id="proj-1",
                fingerprint="fp1",
                sop_name="sop-1",
                occurrences=1,
            ),
            FailureModeCatalogEntry(
                failure_mode_id="fm-2",
                project_id="proj-1",
                fingerprint="fp2",
                sop_name="sop-2",
                occurrences=5,
            ),
            FailureModeCatalogEntry(
                failure_mode_id="fm-3",
                project_id="proj-1",
                fingerprint="fp3",
                sop_name="sop-3",
                occurrences=2,
            ),
        ]
        decisions = trigger.evaluate_batch(entries)
        # Two entries at/above threshold (occurrences 5 and 2).
        proposed = [d for d in decisions if d.propose]
        assert len(proposed) == 2
        proposed_ids = {d.suggestion.failure_mode_id for d in proposed if d.suggestion}
        assert proposed_ids == {"fm-2", "fm-3"}


# ---------------------------------------------------------------------------
# EvolutionTriggerDecision
# ---------------------------------------------------------------------------


class TestEvolutionTriggerDecision:
    def test_no_proposal_decision(self) -> None:
        decision = EvolutionTriggerDecision(
            propose=False,
            reason="below threshold",
        )
        assert decision.propose is False
        assert decision.suggestion is None
        assert decision.reason == "below threshold"

    def test_proposal_decision(self) -> None:
        suggestion = SOPSuggestion(
            suggestion_id="sug-1",
            project_id="proj-1",
            sop_name="sop-1",
            failure_mode_id="fm-1",
            proposed_body="body",
            rationale="why",
        )
        decision = EvolutionTriggerDecision(
            propose=True,
            suggestion=suggestion,
            reason="threshold reached",
        )
        assert decision.propose is True
        assert decision.suggestion is suggestion
        assert decision.reason == "threshold reached"


# ---------------------------------------------------------------------------
# SOPPersister interface + InMemory implementation
# ---------------------------------------------------------------------------


class TestSOPPersisterInterface:
    def test_in_memory_implements_protocol(self) -> None:
        persister: SOPPersister = InMemorySOPPersister()
        assert isinstance(persister, SOPPersister)


class TestInMemorySOPPersister:
    def test_save_and_get(self) -> None:
        persister = InMemorySOPPersister()
        sop = ProjectSOP(
            project_id="proj-1",
            name="sop-1",
            body="body",
            version=1,
        )
        persister.save(sop)
        loaded = persister.get("proj-1", "sop-1")
        assert loaded == sop

    def test_get_missing_returns_none(self) -> None:
        persister = InMemorySOPPersister()
        assert persister.get("proj-1", "missing") is None

    def test_list_for_project(self) -> None:
        persister = InMemorySOPPersister()
        persister.save(ProjectSOP(project_id="p1", name="a", body="x", version=1))
        persister.save(ProjectSOP(project_id="p1", name="b", body="y", version=1))
        persister.save(ProjectSOP(project_id="p2", name="c", body="z", version=1))
        p1_sops = persister.list_for_project("p1")
        assert len(p1_sops) == 2
        assert {s.name for s in p1_sops} == {"a", "b"}
        p2_sops = persister.list_for_project("p2")
        assert len(p2_sops) == 1
        assert p2_sops[0].name == "c"

    def test_save_overwrites_by_project_and_name(self) -> None:
        persister = InMemorySOPPersister()
        persister.save(ProjectSOP(project_id="p", name="n", body="v1", version=1))
        persister.save(ProjectSOP(project_id="p", name="n", body="v2", version=2))
        loaded = persister.get("p", "n")
        assert loaded is not None
        assert loaded.version == 2
        assert loaded.body == "v2"

    def test_save_suggestion_and_list(self) -> None:
        persister = InMemorySOPPersister()
        suggestion = SOPSuggestion(
            suggestion_id="sug-1",
            project_id="proj-1",
            sop_name="sop-1",
            failure_mode_id="fm-1",
            proposed_body="body",
            rationale="why",
        )
        persister.save_suggestion(suggestion)
        loaded = persister.get_suggestion("sug-1")
        assert loaded == suggestion

    def test_list_suggestions_filters_by_project(self) -> None:
        persister = InMemorySOPPersister()
        persister.save_suggestion(
            SOPSuggestion(
                suggestion_id="s1",
                project_id="p1",
                sop_name="s",
                failure_mode_id="f",
                proposed_body="b",
                rationale="r",
            )
        )
        persister.save_suggestion(
            SOPSuggestion(
                suggestion_id="s2",
                project_id="p2",
                sop_name="s",
                failure_mode_id="f",
                proposed_body="b",
                rationale="r",
            )
        )
        p1_suggestions = persister.list_suggestions("p1")
        assert len(p1_suggestions) == 1
        assert p1_suggestions[0].suggestion_id == "s1"

    def test_record_failure_mode_occurrence_increments(self) -> None:
        persister = InMemorySOPPersister()
        persister.record_failure_mode(
            failure_mode_id="fm-1",
            project_id="proj-1",
            fingerprint="ai-flavor:delve-into",
            sop_name="anti-ai-flavor",
        )
        persister.record_failure_mode(
            failure_mode_id="fm-1",
            project_id="proj-1",
            fingerprint="ai-flavor:delve-into",
            sop_name="anti-ai-flavor",
        )
        entries = persister.list_failure_modes("proj-1")
        assert len(entries) == 1
        assert entries[0].occurrences == 2
        assert entries[0].sop_name == "anti-ai-flavor"

    def test_record_failure_mode_distinct_keys(self) -> None:
        persister = InMemorySOPPersister()
        persister.record_failure_mode(
            failure_mode_id="fm-1",
            project_id="proj-1",
            fingerprint="fp-1",
            sop_name="sop-1",
        )
        persister.record_failure_mode(
            failure_mode_id="fm-2",
            project_id="proj-1",
            fingerprint="fp-2",
            sop_name="sop-2",
        )
        entries = persister.list_failure_modes("proj-1")
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# HttpSOPPersister — typed stub, exercises call site at import time
# ---------------------------------------------------------------------------


class TestHttpSOPPersister:
    def test_instantiation_with_url(self) -> None:
        persister = HttpSOPPersister(base_url="http://example.invalid")
        assert isinstance(persister, SOPPersister)

    def test_save_raises_not_implemented(self) -> None:
        """Phase 3 substrate status is http_blocked. Persister is a typed stub."""
        persister = HttpSOPPersister(base_url="http://example.invalid")
        sop = ProjectSOP(project_id="p", name="n", body="b", version=1)
        with pytest.raises(NotImplementedError):
            persister.save(sop)

    def test_get_raises_not_implemented(self) -> None:
        persister = HttpSOPPersister(base_url="http://example.invalid")
        with pytest.raises(NotImplementedError):
            persister.get("p", "n")

    def test_list_for_project_raises_not_implemented(self) -> None:
        persister = HttpSOPPersister(base_url="http://example.invalid")
        with pytest.raises(NotImplementedError):
            persister.list_for_project("p")

    def test_save_suggestion_raises_not_implemented(self) -> None:
        persister = HttpSOPPersister(base_url="http://example.invalid")
        suggestion = SOPSuggestion(
            suggestion_id="s",
            project_id="p",
            sop_name="n",
            failure_mode_id="f",
            proposed_body="b",
            rationale="r",
        )
        with pytest.raises(NotImplementedError):
            persister.save_suggestion(suggestion)

    def test_get_suggestion_raises_not_implemented(self) -> None:
        persister = HttpSOPPersister(base_url="http://example.invalid")
        with pytest.raises(NotImplementedError):
            persister.get_suggestion("s")

    def test_list_suggestions_raises_not_implemented(self) -> None:
        persister = HttpSOPPersister(base_url="http://example.invalid")
        with pytest.raises(NotImplementedError):
            persister.list_suggestions("p")

    def test_record_failure_mode_raises_not_implemented(self) -> None:
        persister = HttpSOPPersister(base_url="http://example.invalid")
        with pytest.raises(NotImplementedError):
            persister.record_failure_mode(
                failure_mode_id="f",
                project_id="p",
                fingerprint="fp",
                sop_name="s",
            )

    def test_list_failure_modes_raises_not_implemented(self) -> None:
        persister = HttpSOPPersister(base_url="http://example.invalid")
        with pytest.raises(NotImplementedError):
            persister.list_failure_modes("p")
