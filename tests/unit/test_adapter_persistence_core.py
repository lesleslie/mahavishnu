"""Unit tests for core.adapter_persistence with temp SQLite storage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

import mahavishnu.core.adapter_persistence as ap

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_adapter_state_and_health_record_roundtrip_dicts() -> None:
    ts = datetime.now(UTC).replace(microsecond=0)
    state = ap.AdapterState(
        adapter_id="prefect",
        enabled=True,
        preference_score=0.8,
        last_successful_execution=ts,
        consecutive_failures=2,
        metadata={"k": "v"},
        updated_at=ts,
    )
    d = state.to_dict()
    loaded = ap.AdapterState.from_dict(d)
    assert loaded.adapter_id == "prefect"
    assert loaded.preference_score == 0.8
    assert loaded.metadata == {"k": "v"}

    rec = ap.HealthRecord(
        adapter_id="prefect",
        timestamp=ts,
        healthy=False,
        latency_ms=12.3,
        error_message="boom",
        details={"e": 1},
    )
    rec_d = rec.to_dict()
    rec_loaded = ap.HealthRecord.from_dict(rec_d)
    assert rec_loaded.adapter_id == "prefect"
    assert rec_loaded.healthy is False
    assert rec_loaded.details == {"e": 1}

    # dict-form metadata/details accepted by from_dict
    state2 = ap.AdapterState.from_dict(
        {
            "adapter_id": "agno",
            "enabled": 1,
            "preference_score": 0.5,
            "last_successful_execution": None,
            "consecutive_failures": 0,
            "metadata": {"x": 1},
            "updated_at": ts.isoformat(),
        }
    )
    assert state2.metadata == {"x": 1}
    rec2 = ap.HealthRecord.from_dict(
        {
            "adapter_id": "agno",
            "timestamp": ts.isoformat(),
            "healthy": 1,
            "latency_ms": None,
            "error_message": None,
            "details": {"d": 2},
        }
    )
    assert rec2.details == {"d": 2}


def test_adapter_state_validation_errors() -> None:
    with pytest.raises(ValueError):
        ap.AdapterState(adapter_id="x", preference_score=2.0)
    with pytest.raises(ValueError):
        ap.AdapterState(adapter_id="x", consecutive_failures=-1)


@pytest.mark.asyncio
async def test_persistence_crud_and_health_history(tmp_path: Path) -> None:
    db_path = tmp_path / "adapter_persistence.db"
    p = ap.AdapterPersistenceLayer(storage_path=str(db_path))
    await p.initialize()
    await p.initialize()  # idempotent branch

    now = datetime.now(UTC).replace(microsecond=0)
    s1 = ap.AdapterState(adapter_id="prefect", preference_score=0.7, updated_at=now)
    s2 = ap.AdapterState(adapter_id="agno", enabled=False, preference_score=0.3, updated_at=now)
    await p.save_state(s1)
    await p.save_state(s2)

    loaded = await p.load_state("prefect")
    assert loaded is not None
    assert loaded.adapter_id == "prefect"
    assert loaded.preference_score == 0.7
    assert await p.load_state("missing") is None

    all_states = await p.load_all_states()
    assert set(all_states.keys()) == {"prefect", "agno"}

    r1 = ap.HealthRecord(
        adapter_id="prefect",
        timestamp=now - timedelta(minutes=2),
        healthy=True,
        latency_ms=5.0,
    )
    r2 = ap.HealthRecord(
        adapter_id="prefect",
        timestamp=now - timedelta(minutes=1),
        healthy=False,
        latency_ms=15.0,
        error_message="timeout",
    )
    await p.record_health(r1)
    await p.record_health(r2)
    hist = await p.get_health_history("prefect", limit=10)
    assert len(hist) == 2
    assert hist[0].timestamp >= hist[1].timestamp

    deleted = await p.cleanup_old_health_records(retention_days=30)
    assert isinstance(deleted, int)

    assert await p.delete_state("agno") is True
    assert await p.delete_state("agno") is False

    await p.close()
    await p.close()  # safe multi-close


@pytest.mark.asyncio
async def test_persistence_context_manager(tmp_path: Path) -> None:
    db_path = tmp_path / "ctx.db"
    async with ap.AdapterPersistenceLayer(storage_path=str(db_path)) as p:
        assert p._initialized is True
        await p.save_state(ap.AdapterState(adapter_id="llamaindex"))
    assert p._initialized is False


@pytest.mark.asyncio
async def test_global_get_and_close_persistence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ap._persistence_instance = None
    real_cls = ap.AdapterPersistenceLayer
    db_path = tmp_path / "global.db"

    class _TempLayer(real_cls):
        def __init__(self) -> None:
            super().__init__(storage_path=str(db_path))

    monkeypatch.setattr(ap, "AdapterPersistenceLayer", _TempLayer)
    p1 = await ap.get_persistence()
    p2 = await ap.get_persistence()
    assert p1 is p2
    assert p1._initialized is True

    await ap.close_persistence()
    assert ap._persistence_instance is None


def test_error_classes_and_default_storage_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(ap, "ensure_directories", lambda: calls.append("ensure"), raising=True)
    monkeypatch.setattr(ap, "get_data_path", lambda name: tmp_path / name, raising=True)

    layer = ap.AdapterPersistenceLayer()
    assert layer.storage_path == tmp_path / "adapter_persistence.db"
    assert calls == ["ensure"]

    base = ap.PersistenceError("base error", details={"k": "v"})
    assert "base error" in str(base)
    assert base.details["k"] == "v"

    state_err = ap.AdapterStateError("prefect", "save", "boom", details={"x": 1})
    assert "prefect" in str(state_err)
    assert state_err.details["operation"] == "save"
    assert state_err.details["x"] == 1

    health_err = ap.HealthRecordError("prefect", "record", "boom", details={"y": 2})
    assert "prefect" in str(health_err)
    assert health_err.details["operation"] == "record"
    assert health_err.details["y"] == 2


@pytest.mark.asyncio
async def test_persistence_error_paths_and_cleanup_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _MixedDB:
        async def execute(self, query, params=None):  # noqa: ANN001,ANN201
            if "DELETE FROM health_history" in query:
                return SimpleNamespace(rowcount=2)
            if "DELETE FROM adapter_state" in query:
                return SimpleNamespace(rowcount=1)
            return None

        async def commit(self) -> None:
            return None

        async def close(self) -> None:
            return None

    class _BoomDB:
        def execute(self, *args, **kwargs):  # noqa: ANN001,ANN003
            raise RuntimeError("boom")

        async def commit(self) -> None:
            return None

        async def close(self) -> None:
            raise RuntimeError("close boom")

    # Cover _ensure_initialized via a fresh save_state call.
    layer = ap.AdapterPersistenceLayer(storage_path=str(tmp_path / "init.db"))
    mixed_db = _MixedDB()

    async def fake_initialize() -> None:
        layer._db = mixed_db
        layer._initialized = True

    monkeypatch.setattr(layer, "initialize", fake_initialize, raising=True)
    await layer.save_state(ap.AdapterState(adapter_id="prefect"))
    assert layer._initialized is True

    # Cleanup branch with deleted > 0.
    deleted = await layer.cleanup_old_health_records(retention_days=7)
    assert deleted == 2

    # initialize() failure branch.
    failing = ap.AdapterPersistenceLayer(storage_path=str(tmp_path / "fail.db"))

    async def boom_connect(*args, **kwargs):  # noqa: ANN001,ANN003
        raise RuntimeError("connect boom")

    monkeypatch.setattr(ap.aiosqlite, "connect", boom_connect, raising=True)
    with pytest.raises(ap.PersistenceError):
        await failing.initialize()

    # Error branches for CRUD methods.
    boom = ap.AdapterPersistenceLayer(storage_path=str(tmp_path / "boom.db"))
    boom._db = _BoomDB()
    boom._initialized = True

    with pytest.raises(ap.AdapterStateError):
        await boom.save_state(ap.AdapterState(adapter_id="x"))
    with pytest.raises(ap.AdapterStateError):
        await boom.load_state("x")
    with pytest.raises(ap.AdapterStateError):
        await boom.load_all_states()
    with pytest.raises(ap.HealthRecordError):
        await boom.record_health(
            ap.HealthRecord(adapter_id="x", timestamp=datetime.now(UTC), healthy=True)
        )
    with pytest.raises(ap.HealthRecordError):
        await boom.get_health_history("x")
    with pytest.raises(ap.HealthRecordError):
        await boom.cleanup_old_health_records()
    with pytest.raises(ap.AdapterStateError):
        await boom.delete_state("x")
    await boom.close()
