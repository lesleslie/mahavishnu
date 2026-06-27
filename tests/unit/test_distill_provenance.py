"""Source provenance gate for the Plan 5 distillation pipeline.

Plan 5 audit finding H4: a compromised workflow run is the entry point
for poisoned distillation. The reviewer-identity gate (H6) protects the
reviewer side, but H4 closes the other half — the *source* side. A run
record must prove it came from a trusted Mahavishnu workflow execution
before its session evidence is fed to the distiller.

This module tests ``mahavishnu.distill.provenance.check_source_purity``:

- ``source_type=external`` is rejected outright (untrusted boundary).
- ``source_type=mahavishnu_workflow`` requires a reviewer identity in
  the allowlist; otherwise it's rejected.
- The happy path (mahavishnu_workflow + allowlisted reviewer) is
  accepted.

The gate is intentionally a pure function over a typed record so the
distiller can call it per-candidate without side effects. The distiller
wires it into the pre-filter pipeline; this module verifies the gate
contract independently.
"""

from __future__ import annotations

import pytest

from mahavishnu.distill.provenance import (
    ProvenanceDecision,
    SourcePurity,
    check_source_purity,
)

# --------------------------------------------------------------- types


class TestSourcePurity:
    """Enum covers the four purity verdicts the gate can return."""

    def test_enum_members(self) -> None:
        assert {m.value for m in SourcePurity} == {
            "pure",
            "rejected_external",
            "rejected_unattributed",
            "rejected_reviewer",
        }


class TestProvenanceDecision:
    """Frozen value object: allowed, purity class, reason, identity."""

    def test_repr_includes_key_fields(self) -> None:
        d = ProvenanceDecision(
            allowed=True,
            purity=SourcePurity.PURE,
            reason="ok",
            reviewer_id="alice",
            source_type="mahavishnu_workflow",
        )
        text = repr(d)
        assert "alice" in text
        assert "mahavishnu_workflow" in text
        assert "pure" in text

    def test_frozen_rejects_mutation(self) -> None:
        d = ProvenanceDecision(
            allowed=True,
            purity=SourcePurity.PURE,
            reason="ok",
            reviewer_id="alice",
            source_type="mahavishnu_workflow",
        )
        with pytest.raises((AttributeError, TypeError)):
            d.allowed = False  # type: ignore[misc]


# --------------------------------------------------------------- behavior


class TestCheckSourcePurity:
    """The three required scenarios from the audit finding."""

    def test_external_source_is_rejected(self) -> None:
        """A run record with source_type=external is untrusted. Reject."""
        record = {
            "run_id": "01HEX0001",
            "session_id": "01HEXSESS01",
            "source_type": "external",
            "reviewer_id": None,
        }
        result = check_source_purity(record)
        assert isinstance(result, ProvenanceDecision)
        assert result.allowed is False
        assert result.purity is SourcePurity.REJECTED_EXTERNAL
        assert result.source_type == "external"
        # The reason must name the offending field for forensic value.
        assert "external" in result.reason.lower()

    def test_mahavishnu_workflow_without_reviewer_is_rejected(self) -> None:
        """source_type=mahavishnu_workflow but reviewer_id missing."""
        record = {
            "run_id": "01HEX0002",
            "session_id": "01HEXSESS02",
            "source_type": "mahavishnu_workflow",
            "reviewer_id": None,
        }
        result = check_source_purity(record)
        assert result.allowed is False
        assert result.purity is SourcePurity.REJECTED_UNATTRIBUTED
        # Forensic reason mentions the missing attribution.
        assert "reviewer" in result.reason.lower() or "identity" in result.reason.lower()

    def test_allowlisted_reviewer_is_accepted(self) -> None:
        """Happy path: mahavishnu_workflow + reviewer in allowlist."""
        record = {
            "run_id": "01HEX0003",
            "session_id": "01HEXSESS03",
            "source_type": "mahavishnu_workflow",
            "reviewer_id": "alice",
        }
        result = check_source_purity(record, allowlist=frozenset({"alice", "bob"}))
        assert result.allowed is True
        assert result.purity is SourcePurity.PURE
        assert result.reviewer_id == "alice"
        assert result.source_type == "mahavishnu_workflow"

    def test_mahavishnu_workflow_with_unlisted_reviewer_is_rejected(self) -> None:
        """Reviewer present but not in the allowlist."""
        record = {
            "run_id": "01HEX0004",
            "session_id": "01HEXSESS04",
            "source_type": "mahavishnu_workflow",
            "reviewer_id": "mallory",
        }
        result = check_source_purity(record, allowlist=frozenset({"alice", "bob"}))
        assert result.allowed is False
        assert result.purity is SourcePurity.REJECTED_REVIEWER
        assert result.reviewer_id == "mallory"


# --------------------------------------------------------------- bootstrap


class TestCheckSourcePurityBootstrap:
    """Bootstrap mode (no allowlist) preserves v1 trust-on-first-use.

    With no allowlist configured, mahavishnu_workflow records that DO
    carry a reviewer identity are accepted (matches the H6 bootstrap
    shape: warn + audit, but do not block single-tenant dev).
    """

    def test_no_allowlist_with_reviewer_is_accepted(self) -> None:
        record = {
            "run_id": "01HEX0005",
            "session_id": "01HEXSESS05",
            "source_type": "mahavishnu_workflow",
            "reviewer_id": "alice",
        }
        result = check_source_purity(record)
        assert result.allowed is True
        assert result.purity is SourcePurity.PURE

    def test_no_allowlist_without_reviewer_still_rejected(self) -> None:
        """Bootstrap mode does NOT bypass the reviewer-presence check.

        Without a reviewer identity the provenance is unattributed and
        the gate refuses the record regardless of allowlist state.
        """
        record = {
            "run_id": "01HEX0006",
            "session_id": "01HEXSESS06",
            "source_type": "mahavishnu_workflow",
            "reviewer_id": None,
        }
        result = check_source_purity(record)
        assert result.allowed is False
        assert result.purity is SourcePurity.REJECTED_UNATTRIBUTED


# --------------------------------------------------------------- malformed


class TestCheckSourcePurityMalformed:
    """Defensive: missing source_type, wrong types, etc."""

    def test_missing_source_type_is_rejected(self) -> None:
        record = {"run_id": "01HEX0007", "reviewer_id": "alice"}
        result = check_source_purity(record)
        assert result.allowed is False
        # Without a source_type, the record is unattributed by definition.
        assert result.purity in {
            SourcePurity.REJECTED_UNATTRIBUTED,
            SourcePurity.REJECTED_EXTERNAL,
        }

    def test_empty_reviewer_string_treated_as_missing(self) -> None:
        """Empty-string reviewer_id is treated the same as None."""
        record = {
            "run_id": "01HEX0008",
            "session_id": "01HEXSESS08",
            "source_type": "mahavishnu_workflow",
            "reviewer_id": "",
        }
        result = check_source_purity(record, allowlist=frozenset({"alice"}))
        assert result.allowed is False
        assert result.purity is SourcePurity.REJECTED_UNATTRIBUTED
