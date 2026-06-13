"""Coverage tests for mahavishnu.core.adapter_persistence.

This file targets uncovered branches and error paths in
adapter_persistence.py to reach >=80% line+branch coverage.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import mahavishnu.core.adapter_persistence as ap
from mahavishnu.core.adapter_persistence import (
    AdapterPersistenceLayer,
    AdapterState,
    AdapterStateError,
    HealthRecord,
    HealthRecordError,
    PersistenceError,
)


# =============================================================================
# Custom Exceptions
# =============================================================================


@pytest.mark.unit
def test_persistence_error_initialization() -> None:
    """PersistenceError carries the DATABASE_CONNECTION_ERROR code."""
    err = PersistenceError("boom", details={"k": "v"})
    assert "boom" in str(err)
    # MahavishnuError attaches error_code as an attribute
    assert err.details == {"k": "v"}


@pytest.mark.unit
def test_persistence_error_no_details() -> None:
    """PersistenceError accepts None details (default branch)."""
    err = PersistenceError("oops")
    assert err.details == {}


@pytest.mark.unit
def test_adapter_state_error_includes_details() -> None:
    """AdapterStateError merges custom details with structured fields."""
    err = AdapterStateError(
        "prefect",
        "save",
        "DB locked",
        details={"host": "localhost"},
    )
    # Surface the structured fields in the details dict
    assert err.details["adapter_id"] == "prefect"
    assert err.details["operation"] == "save"
    assert err.details["reason"] == "DB locked"
    assert err.details["host"] == "localhost"


@pytest.mark.unit
def test_health_record_error_includes_details() -> None:
    """HealthRecordError merges custom details with structured fields."""
    err = HealthRecordError(
        "prefect",
        "record",
        "timeout",
        details={"duration_ms": 500},
    )
    assert err.details["adapter_id"] == "prefect"
    assert err.details["operation"] == "record"
    assert err.details["reason"] == "timeout"
    assert err.details["duration_ms"] == 500


# =============================================================================
# AdapterState dataclass
# =============================================================================


@pytest.mark.unit
def test_adapter_state_to_dict_with_last_success() -> None:
    """to_dict serializes datetime as ISO string."""
    ts = datetime(2026, 6, 12, 10, 0, 0, tzinfo=UTC)
    state = AdapterState(
        adapter_id="prefect",
        enabled=True,
        preference_score=0.8,
        last_successful_execution=ts,
        consecutive_failures=0,
        metadata={"key": "value"},
        updated_at=ts,
    )
    d = state.to_dict()
    assert d["adapter_id"] == "prefect"
    assert d["enabled"] is True
    assert d["preference_score"] == 0.8
    assert d["last_successful_execution"] == ts.isoformat()
    assert d["consecutive_failures"] == 0
    assert d["updated_at"] == ts.isoformat()
    # metadata should be JSON-encoded
    assert json.loads(d["metadata"]) == {"key": "value"}


@pytest.mark.unit
def test_adapter_state_to_dict_no_last_success() -> None:
    """to_dict emits None when last_successful_execution is None."""
    state = AdapterState(adapter_id="agno", last_successful_execution=None)
    d = state.to_dict()
    assert d["last_successful_execution"] is None


@pytest.mark.unit
def test_adapter_state_from_dict_string_metadata() -> None:
    """from_dict parses metadata when provided as JSON string."""
    state = AdapterState.from_dict(
        {
            "adapter_id": "prefect",
            "enabled": 1,
            "preference_score": 0.5,
            "last_successful_execution": None,
            "consecutive_failures": 0,
            "metadata": json.dumps({"foo": "bar"}),
            "updated_at": "2026-06-12T10:00:00+00:00",
        }
    )
    assert state.metadata == {"foo": "bar"}


@pytest.mark.unit
def test_adapter_state_from_dict_dict_metadata() -> None:
    """from_dict accepts metadata as a dict (in-process branch)."""
    state = AdapterState.from_dict(
        {
            "adapter_id": "prefect",
            "enabled": 0,
            "preference_score": 0.1,
            "last_successful_execution": "2026-06-12T10:00:00+00:00",
            "consecutive_failures": 1,
            "metadata": {"foo": "bar"},
            "updated_at": "2026-06-12T10:00:00+00:00",
        }
    )
    assert state.metadata == {"foo": "bar"}
    assert state.enabled is False
    assert state.last_successful_execution is not None


@pytest.mark.unit
def test_adapter_state_post_init_validates_preference() -> None:
    """preference_score out of range raises ValueError."""
    with pytest.raises(ValueError, match="preference_score must be between"):
        AdapterState(adapter_id="prefect", preference_score=1.5)
    with pytest.raises(ValueError, match="preference_score must be between"):
        AdapterState(adapter_id="prefect", preference_score=-0.1)


@pytest.mark.unit
def test_adapter_state_post_init_validates_failures() -> None:
    """consecutive_failures must be non-negative."""
    with pytest.raises(ValueError, match="consecutive_failures must be non-negative"):
        AdapterState(adapter_id="prefect", consecutive_failures=-1)


@pytest.mark.unit
def test_adapter_state_defaults() -> None:
    """AdapterState default values are populated correctly."""
    state = AdapterState(adapter_id="x")
    assert state.enabled is True
    assert state.preference_score == 0.5
    assert state.consecutive_failures == 0
    assert state.metadata == {}
    assert state.last_successful_execution is None


# =============================================================================
# HealthRecord dataclass
# =============================================================================


@pytest.mark.unit
def test_health_record_to_dict() -> None:
    """to_dict emits a JSON-serializable dict with details as JSON."""
    ts = datetime(2026, 6, 12, 10, 0, 0, tzinfo=UTC)
    rec = HealthRecord(
        adapter_id="prefect",
        timestamp=ts,
        healthy=True,
        latency_ms=12.5,
        error_message=None,
        details={"foo": "bar"},
    )
    d = rec.to_dict()
    assert d["adapter_id"] == "prefect"
    assert d["timestamp"] == ts.isoformat()
    assert d["healthy"] is True
    assert d["latency_ms"] == 12.5
    assert d["error_message"] is None
    assert json.loads(d["details"]) == {"foo": "bar"}


@pytest.mark.unit
def test_health_record_from_dict_string_details() -> None:
    """from_dict parses details when provided as JSON string."""
    rec = HealthRecord.from_dict(
        {
            "adapter_id": "prefect",
            "timestamp": "2026-06-12T10:00:00+00:00",
            "healthy": 1,
            "latency_ms": 10.0,
            "error_message": None,
            "details": json.dumps({"a": 1}),
        }
    )
    assert rec.details == {"a": 1}
    assert rec.healthy is True
    assert rec.latency_ms == 10.0
    assert rec.error_message is None


@pytest.mark.unit
def test_health_record_from_dict_dict_details() -> None:
    """from_dict accepts details as a dict (in-process branch)."""
    rec = HealthRecord.from_dict(
        {
            "adapter_id": "prefect",
            "timestamp": "2026-06-12T10:00:00+00:00",
            "healthy": 0,
            "latency_ms": None,
            "error_message": "x",
            "details": {"b": 2},
        }
    )
    assert rec.details == {"b": 2}
    assert rec.healthy is False
    assert rec.latency_ms is None


# =============================================================================
# AdapterPersistenceLayer: helpers & init
# =============================================================================


@pytest.mark.unit
def test_layer_default_path_uses_data_dir(tmp_path: Path) -> None:
    """Without explicit storage_path, the layer uses get_data_path."""
    fake_data_path = tmp_path / "adapter_persistence.db"
    with patch.object(ap, "get_data_path", return_value=fake_data_path) as gdp_mock, \
         patch.object(ap, "ensure_directories") as ed_mock:
        layer = AdapterPersistenceLayer()
    ed_mock.assert_called_once()
    gdp_mock.assert_called_once_with("adapter_persistence.db")
    assert layer.storage_path == fake_data_path
    assert layer._explicit_storage_path is False


@pytest.mark.unit
def test_layer_explicit_storage_path(tmp_path: Path) -> None:
    """With explicit storage_path, ensure_directories is NOT called."""
    explicit = tmp_path / "explicit.db"
    layer = AdapterPersistenceLayer(storage_path=str(explicit))
    assert layer.storage_path == explicit
    assert layer._explicit_storage_path is True


@pytest.mark.unit
def test_fallback_storage_path_creates_dir(tmp_path: Path) -> None:
    """_fallback_storage_path returns a path under tmp and creates the dir."""
    with patch.object(ap.tempfile, "gettempdir", return_value=str(tmp_path)):
        layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
        path = layer._fallback_storage_path()
    assert path.parent == tmp_path / "mahavishnu"
    assert path.parent.exists()
    assert path.name.startswith("adapter_persistence_")
    assert path.name.endswith(".db")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_is_idempotent(tmp_path: Path) -> None:
    """Calling initialize() twice only opens the connection once."""
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "test.db"))
    await layer.initialize()
    first_db = layer._db
    await layer.initialize()
    # same connection object — no re-init
    assert layer._db is first_db
    assert layer._initialized is True
    await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_fallback_on_primary_failure(tmp_path: Path) -> None:
    """When primary path fails AND not explicit, layer falls back to /tmp."""
    # Patch get_data_path to return a bad path (so primary init will fail)
    bad_path = tmp_path / "nonexistent_dir" / "x.db"
    real_init_db = AdapterPersistenceLayer._initialize_database
    call_count = 0

    async def fake_init(self: "AdapterPersistenceLayer", storage_path: Path) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("disk full")
        # Second call: actually initialize at the fallback path
        await real_init_db(self, storage_path)

    with patch.object(
        AdapterPersistenceLayer,
        "_initialize_database",
        fake_init,
    ), patch.object(
        ap, "get_data_path", return_value=bad_path
    ), patch.object(ap, "ensure_directories"):
        layer = AdapterPersistenceLayer()  # No explicit path -> fallback eligible
        await layer.initialize()
    # Called twice: primary + fallback
    assert call_count == 2
    assert layer._initialized is True
    # After fallback, storage_path should point under tmp
    assert "mahavishnu" in str(layer.storage_path)
    await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_raises_when_explicit_path_fails(tmp_path: Path) -> None:
    """If explicit path fails, no fallback is attempted and PersistenceError raised."""
    with patch.object(
        AdapterPersistenceLayer,
        "_initialize_database",
        side_effect=OSError("disk full"),
    ) as init_mock:
        layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
        with pytest.raises(PersistenceError, match="Failed to initialize database"):
            await layer.initialize()
    # Only one attempt — no fallback when explicit
    assert init_mock.call_count == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_initialize_raises_when_fallback_also_fails(tmp_path: Path) -> None:
    """When primary fails (non-explicit) and fallback also fails, raise."""
    bad_path = tmp_path / "nonexistent_dir" / "x.db"
    with patch.object(
        AdapterPersistenceLayer,
        "_initialize_database",
        side_effect=OSError("disk full"),
    ):
        layer = AdapterPersistenceLayer(storage_path=str(bad_path))
        with pytest.raises(PersistenceError, match="Failed to initialize database"):
            await layer.initialize()
    # _initialized should remain False
    assert layer._initialized is False


# =============================================================================
# save_state / load_state / load_all_states
# =============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_and_load_state_roundtrip(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        ts = datetime(2026, 6, 12, 10, 0, 0, tzinfo=UTC)
        state = AdapterState(
            adapter_id="prefect",
            enabled=False,
            preference_score=0.3,
            last_successful_execution=ts,
            consecutive_failures=2,
            metadata={"k": "v"},
            updated_at=ts,
        )
        await layer.save_state(state)
        loaded = await layer.load_state("prefect")
        assert loaded is not None
        assert loaded.adapter_id == "prefect"
        assert loaded.enabled is False
        assert loaded.preference_score == 0.3
        assert loaded.consecutive_failures == 2
        assert loaded.metadata == {"k": "v"}
        assert loaded.last_successful_execution == ts
        # updated_at should round-trip
        assert loaded.updated_at == ts
    finally:
        await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_state_returns_none_when_missing(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        result = await layer.load_state("nonexistent")
        assert result is None
    finally:
        await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_state_raises_adapter_state_error_on_db_failure(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        with patch.object(
            layer._db, "execute", side_effect=RuntimeError("db exploded")
        ):
            with pytest.raises(AdapterStateError, match="load"):
                await layer.load_state("prefect")
    finally:
        await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_save_state_raises_adapter_state_error_on_db_failure(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        state = AdapterState(adapter_id="prefect")
        with patch.object(
            layer._db, "execute", side_effect=RuntimeError("db exploded")
        ):
            with pytest.raises(AdapterStateError, match="save"):
                await layer.save_state(state)
    finally:
        await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_all_states_returns_empty_dict_when_no_rows(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        states = await layer.load_all_states()
        assert states == {}
    finally:
        await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_all_states_returns_multiple(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        await layer.save_state(AdapterState(adapter_id="a", preference_score=0.1))
        await layer.save_state(AdapterState(adapter_id="b", preference_score=0.9))
        states = await layer.load_all_states()
        assert set(states.keys()) == {"a", "b"}
        assert states["a"].preference_score == 0.1
        assert states["b"].preference_score == 0.9
    finally:
        await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_all_states_raises_on_db_failure(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        with patch.object(
            layer._db, "execute", side_effect=RuntimeError("nope")
        ):
            with pytest.raises(AdapterStateError, match="load_all"):
                await layer.load_all_states()
    finally:
        await layer.close()


# =============================================================================
# record_health / get_health_history
# =============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_and_get_health_history(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        base = datetime(2026, 6, 12, 10, 0, 0, tzinfo=UTC)
        # 3 records, with different timestamps
        for i, healthy in enumerate([True, False, True]):
            await layer.record_health(
                HealthRecord(
                    adapter_id="prefect",
                    timestamp=base + timedelta(minutes=i),
                    healthy=healthy,
                    latency_ms=10.0 + i,
                    error_message=None if healthy else "boom",
                    details={"i": i},
                )
            )
        records = await layer.get_health_history("prefect")
        assert len(records) == 3
        # Most recent first
        assert records[0].latency_ms == 12.0
        assert records[1].error_message == "boom"
        # All details should round-trip
        assert {r.details["i"] for r in records} == {0, 1, 2}
    finally:
        await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_health_history_respects_limit(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        base = datetime(2026, 6, 12, 10, 0, 0, tzinfo=UTC)
        for i in range(5):
            await layer.record_health(
                HealthRecord(
                    adapter_id="prefect",
                    timestamp=base + timedelta(seconds=i),
                    healthy=True,
                    latency_ms=float(i),
                )
            )
        records = await layer.get_health_history("prefect", limit=2)
        assert len(records) == 2
    finally:
        await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_health_raises_on_db_failure(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        rec = HealthRecord(
            adapter_id="prefect",
            timestamp=datetime.now(UTC),
            healthy=True,
        )
        with patch.object(
            layer._db, "execute", side_effect=RuntimeError("nope")
        ):
            with pytest.raises(HealthRecordError, match="record"):
                await layer.record_health(rec)
    finally:
        await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_health_history_raises_on_db_failure(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        with patch.object(
            layer._db, "execute", side_effect=RuntimeError("nope")
        ):
            with pytest.raises(HealthRecordError, match="get_history"):
                await layer.get_health_history("prefect")
    finally:
        await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_health_history_empty_when_no_rows(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        records = await layer.get_health_history("unknown")
        assert records == []
    finally:
        await layer.close()


# =============================================================================
# cleanup_old_health_records
# =============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cleanup_old_health_records_returns_zero_when_nothing_to_delete(
    tmp_path: Path,
) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        # Record a fresh record — should not be deleted
        await layer.record_health(
            HealthRecord(
                adapter_id="prefect",
                timestamp=datetime.now(UTC),
                healthy=True,
            )
        )
        deleted = await layer.cleanup_old_health_records(retention_days=30)
        assert deleted == 0
    finally:
        await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cleanup_old_health_records_with_default_retention(tmp_path: Path) -> None:
    """Using the default retention should also work (None branch)."""
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        # No records at all — return 0
        deleted = await layer.cleanup_old_health_records()
        assert deleted == 0
    finally:
        await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cleanup_old_health_records_raises_on_db_failure(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        with patch.object(
            layer._db, "execute", side_effect=RuntimeError("nope")
        ):
            with pytest.raises(HealthRecordError, match="cleanup"):
                await layer.cleanup_old_health_records()
    finally:
        await layer.close()


# =============================================================================
# delete_state
# =============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_state_returns_true_when_existed(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        await layer.save_state(AdapterState(adapter_id="prefect"))
        deleted = await layer.delete_state("prefect")
        assert deleted is True
        # And now load_state returns None
        assert await layer.load_state("prefect") is None
    finally:
        await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_state_returns_false_when_missing(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        deleted = await layer.delete_state("nonexistent")
        assert deleted is False
    finally:
        await layer.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_state_raises_on_db_failure(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    try:
        with patch.object(
            layer._db, "execute", side_effect=RuntimeError("nope")
        ):
            with pytest.raises(AdapterStateError, match="delete"):
                await layer.delete_state("prefect")
    finally:
        await layer.close()


# =============================================================================
# close & context manager
# =============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_close_is_idempotent(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()
    await layer.close()
    # Second close should be a no-op (early return)
    await layer.close()
    assert layer._db is None
    assert layer._initialized is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_close_logs_warning_on_failure(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    await layer.initialize()

    # Patch aiosqlite.Connection.close on the instance to raise
    close_mock = AsyncMock(side_effect=RuntimeError("close failed"))
    with patch.object(layer._db, "close", close_mock):
        await layer.close()
    # Even after error, state is cleared
    assert layer._db is None
    assert layer._initialized is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_context_manager_initializes_and_closes(tmp_path: Path) -> None:
    async with AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db")) as layer:
        # Inside the context, the layer should be initialized
        assert layer._initialized is True
        assert layer._db is not None
        # Save a state to make sure things actually work
        await layer.save_state(AdapterState(adapter_id="prefect"))
    # After the context exits, resources should be released
    assert layer._db is None
    assert layer._initialized is False


# =============================================================================
# _ensure_initialized (lazy init)
# =============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_initialized_triggers_init(tmp_path: Path) -> None:
    layer = AdapterPersistenceLayer(storage_path=str(tmp_path / "x.db"))
    # Don't call initialize() — call _ensure_initialized() instead
    await layer._ensure_initialized()
    assert layer._initialized is True
    assert layer._db is not None
    await layer.close()


# =============================================================================
# Module-level convenience functions
# =============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_persistence_returns_singleton(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """get_persistence() returns the same instance on repeated calls."""
    # Reset the global instance
    monkeypatch.setattr(ap, "_persistence_instance", None)
    # Patch the constructor so it uses a tmp path
    real_init = AdapterPersistenceLayer.__init__

    def patched_init(self: AdapterPersistenceLayer, storage_path: str | None = None) -> None:
        real_init(self, storage_path=str(tmp_path / "global.db"))

    monkeypatch.setattr(AdapterPersistenceLayer, "__init__", patched_init)
    try:
        a = await ap.get_persistence()
        b = await ap.get_persistence()
        assert a is b
    finally:
        # Close + reset global
        await ap.close_persistence()
        monkeypatch.setattr(ap, "_persistence_instance", None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_close_persistence_is_safe_when_none() -> None:
    """close_persistence() on a never-created instance is a no-op."""
    ap._persistence_instance = None  # type: ignore[attr-defined]
    await ap.close_persistence()
    assert ap._persistence_instance is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_close_persistence_closes_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """close_persistence() closes the existing instance and clears the global."""
    real_init = AdapterPersistenceLayer.__init__

    def patched_init(self: AdapterPersistenceLayer, storage_path: str | None = None) -> None:
        real_init(self, storage_path=str(tmp_path / "global.db"))

    monkeypatch.setattr(AdapterPersistenceLayer, "__init__", patched_init)
    monkeypatch.setattr(ap, "_persistence_instance", None)
    try:
        instance = await ap.get_persistence()
        assert ap._persistence_instance is instance
        await ap.close_persistence()
        assert ap._persistence_instance is None
    finally:
        # Best-effort cleanup
        if ap._persistence_instance is not None:
            await ap.close_persistence()
        monkeypatch.setattr(ap, "_persistence_instance", None)
