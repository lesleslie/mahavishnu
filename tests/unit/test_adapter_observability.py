"""Unit tests for mahavishnu/observability/adapter_runtime.py.

Spec #8: adapter-runtime-observability (Phase 3).

The Dhara-backed HTTP CRUD surface is http_blocked (per substrate status),
so this module ships:

- ``AdapterSettingsVersion`` frozen dataclass (adapter_id, version, settings_hash,
  activated_at, activated_by) - the immutable record of a single activation.
- ``SettingsActivationRecord`` lighter dataclass (what a caller passes when
  writing).
- ``SettingsActivationPersister`` Protocol - the persister interface that the
  Dhara-backed implementation will satisfy.
- ``InMemorySettingsActivationPersister`` - in-memory implementation for v0.
- ``DharaSettingsActivationPersister`` - stub that raises NotImplementedError
  with a TODO referencing Workstream C substrate.
- ``record_activation()`` - the single entry point used by upstream callers
  (Plan 4 TrackedSettings will call this once it ships).

The seam with Plan 4:
- Plan 4's ``TrackedSettings`` (Phase A, in-flight) is the upstream source of
  ``settings_hash`` and ``activated_by``. Spec #8 only consumes those values;
  it does not own the Oneiric subscription / debounce / hash logic.
- Plan 4 Phase D adds the adapter observability HTTP routes. Spec #8 does
  NOT touch those routes - it only ships the model + persister interface
  that Phase D will plug into.

Tests pin:
- Model shape and immutability
- Persister Protocol runtime checkability
- InMemory implementation rejects duplicate (adapter_id, version) and
  preserves insertion order
- ``record_activation`` routes to the configured persister
- Dhara stub raises NotImplementedError with a substrate-marked TODO
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from mahavishnu.observability.adapter_runtime import (
    AdapterSettingsVersion,
    DharaSettingsActivationPersister,
    InMemorySettingsActivationPersister,
    SettingsActivationPersister,
    SettingsActivationRecord,
    record_activation,
)

# ---------------------------------------------------------------------------
# AdapterSettingsVersion model
# ---------------------------------------------------------------------------


class TestAdapterSettingsVersion:
    def test_required_fields(self) -> None:
        activated_at = datetime(2026, 6, 27, 12, 0, 0, tzinfo=UTC)
        v = AdapterSettingsVersion(
            adapter_id="prefect",
            version=1,
            settings_hash="a" * 64,
            activated_at=activated_at,
            activated_by="alice",
        )
        assert v.adapter_id == "prefect"
        assert v.version == 1
        assert v.settings_hash == "a" * 64
        assert v.activated_at == activated_at
        assert v.activated_by == "alice"

    def test_default_notes_is_empty_string(self) -> None:
        v = AdapterSettingsVersion(
            adapter_id="prefect",
            version=1,
            settings_hash="0" * 64,
            activated_at=datetime.now(UTC),
            activated_by="system:deploy",
        )
        assert v.notes == ""

    def test_custom_notes_passes_through(self) -> None:
        v = AdapterSettingsVersion(
            adapter_id="llamaindex",
            version=7,
            settings_hash="f" * 64,
            activated_at=datetime.now(UTC),
            activated_by="bob",
            notes="A/B test with smaller pool_size",
        )
        assert v.notes == "A/B test with smaller pool_size"

    def test_is_frozen(self) -> None:
        v = AdapterSettingsVersion(
            adapter_id="prefect",
            version=1,
            settings_hash="0" * 64,
            activated_at=datetime.now(UTC),
            activated_by="alice",
        )
        with pytest.raises(FrozenInstanceError):
            v.adapter_id = "llamaindex"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SettingsActivationRecord (write payload)
# ---------------------------------------------------------------------------


class TestSettingsActivationRecord:
    def test_required_fields(self) -> None:
        rec = SettingsActivationRecord(
            adapter_id="prefect",
            version=1,
            settings_hash="a" * 64,
            activated_by="alice",
        )
        assert rec.adapter_id == "prefect"
        assert rec.version == 1
        assert rec.settings_hash == "a" * 64
        assert rec.activated_by == "alice"
        assert rec.notes == ""

    def test_custom_notes_passes_through(self) -> None:
        rec = SettingsActivationRecord(
            adapter_id="agno",
            version=3,
            settings_hash="b" * 64,
            activated_by="system:mcp",
            notes="promoted from staging",
        )
        assert rec.notes == "promoted from staging"

    def test_default_recorded_at_is_now_utc(self) -> None:
        before = datetime.now(UTC)
        rec = SettingsActivationRecord(
            adapter_id="prefect",
            version=1,
            settings_hash="0" * 64,
            activated_by="alice",
        )
        after = datetime.now(UTC)
        assert before <= rec.recorded_at <= after


# ---------------------------------------------------------------------------
# SettingsActivationPersister Protocol
# ---------------------------------------------------------------------------


class TestSettingsActivationPersisterProtocol:
    def test_is_runtime_checkable(self) -> None:
        # The Protocol must be @runtime_checkable so callers can
        # isinstance-check without a static type-checker.
        assert isinstance(InMemorySettingsActivationPersister(), SettingsActivationPersister)
        assert not isinstance(object(), SettingsActivationPersister)


# ---------------------------------------------------------------------------
# InMemorySettingsActivationPersister
# ---------------------------------------------------------------------------


class TestInMemorySettingsActivationPersister:
    def test_empty_history(self) -> None:
        persister = InMemorySettingsActivationPersister()
        assert persister.history() == []

    def test_empty_history_for_unknown_adapter(self) -> None:
        persister = InMemorySettingsActivationPersister()
        assert persister.history_for("prefect") == []

    def test_save_records_payload(self) -> None:
        persister = InMemorySettingsActivationPersister()
        rec = SettingsActivationRecord(
            adapter_id="prefect",
            version=1,
            settings_hash="a" * 64,
            activated_by="alice",
        )
        persister.save(rec)
        assert persister.history() == [rec]

    def test_history_for_filters_by_adapter(self) -> None:
        persister = InMemorySettingsActivationPersister()
        r1 = SettingsActivationRecord(
            adapter_id="prefect",
            version=1,
            settings_hash="a" * 64,
            activated_by="alice",
        )
        r2 = SettingsActivationRecord(
            adapter_id="llamaindex",
            version=1,
            settings_hash="b" * 64,
            activated_by="bob",
        )
        r3 = SettingsActivationRecord(
            adapter_id="prefect",
            version=2,
            settings_hash="c" * 64,
            activated_by="alice",
        )
        persister.save(r1)
        persister.save(r2)
        persister.save(r3)
        prefect_versions = persister.history_for("prefect")
        assert prefect_versions == [r1, r3]

    def test_duplicate_adapter_version_raises(self) -> None:
        # The (adapter_id, version) pair is the natural PK - the persister
        # must reject a second save with the same pair to preserve the
        # append-only invariant.
        persister = InMemorySettingsActivationPersister()
        r1 = SettingsActivationRecord(
            adapter_id="prefect",
            version=1,
            settings_hash="a" * 64,
            activated_by="alice",
        )
        r2 = SettingsActivationRecord(
            adapter_id="prefect",
            version=1,
            settings_hash="different-hash-but-same-version",
            activated_by="bob",
        )
        persister.save(r1)
        with pytest.raises(ValueError, match="duplicate"):
            persister.save(r2)

    def test_history_returns_copy(self) -> None:
        # Callers must not be able to mutate internal state through
        # history() - a shallow copy prevents accidental writes.
        persister = InMemorySettingsActivationPersister()
        rec = SettingsActivationRecord(
            adapter_id="prefect",
            version=1,
            settings_hash="a" * 64,
            activated_by="alice",
        )
        persister.save(rec)
        snapshot = persister.history()
        snapshot.clear()
        assert persister.history() == [rec]


# ---------------------------------------------------------------------------
# DharaSettingsActivationPersister stub
# ---------------------------------------------------------------------------


class TestDharaSettingsActivationPersisterStub:
    def test_save_raises_not_implemented_with_substrate_marker(self) -> None:
        stub = DharaSettingsActivationPersister()
        rec = SettingsActivationRecord(
            adapter_id="prefect",
            version=1,
            settings_hash="a" * 64,
            activated_by="alice",
        )
        with pytest.raises(NotImplementedError) as excinfo:
            stub.save(rec)
        # The message must call out the substrate TODO so accidental wiring
        # is obvious in the traceback.
        assert "Workstream C" in str(excinfo.value)
        assert "substrate" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# record_activation() entry point
# ---------------------------------------------------------------------------


class TestRecordActivation:
    def test_routes_to_injected_persister(self) -> None:
        persister = InMemorySettingsActivationPersister()
        rec = SettingsActivationRecord(
            adapter_id="prefect",
            version=1,
            settings_hash="a" * 64,
            activated_by="alice",
        )
        record_activation(rec, persister=persister)
        assert persister.history() == [rec]

    def test_routes_to_dhara_stub_when_requested(self) -> None:
        stub = DharaSettingsActivationPersister()
        rec = SettingsActivationRecord(
            adapter_id="prefect",
            version=1,
            settings_hash="a" * 64,
            activated_by="alice",
        )
        with pytest.raises(NotImplementedError):
            record_activation(rec, persister=stub)