"""Precommitment tests — D-LOCK backed, async."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dhara.lock.sql import SQLBackendLock
import duckdb
import pytest

from mahavishnu.core.precommitment import (
    Hypothesis,
    HypothesisLock,
    HypothesisViolationError,
    SignatureMismatchError,
    compute_signature,
)

_MIGRATION_0003 = (
    Path(__file__).parents[3] / "dhara" / "dhara" / "migrations" / "sql" / "0003_locks.sql"
).read_text()


@pytest.fixture
def file_db(tmp_path: Path) -> Any:
    """File-backed DuckDB; precreate schema so per-test connections share it."""
    db_path = tmp_path / "precommit_test.db"
    init = duckdb.connect(str(db_path))
    init.execute(_MIGRATION_0003)
    init.close()
    return str(db_path)


@pytest.fixture
def lock(file_db: str) -> HypothesisLock:
    """HypothesisLock backed by a fresh SQLBackendLock against file_db."""
    return HypothesisLock(dhara_lock=SQLBackendLock(duckdb.connect(file_db)))


def _hypo(claim: str = "test claim") -> Hypothesis:
    return Hypothesis(
        claim=claim, falsification_criteria=("a",), success_criteria=("b",),
        confidence=80, locked_at=datetime.now(UTC),
    )


def test_hypothesis_validation_confidence_range() -> None:
    with pytest.raises(ValueError):
        Hypothesis(claim="x", falsification_criteria=(), success_criteria=(),
                   confidence=150, locked_at=datetime.now(UTC))


def test_compute_signature_is_deterministic() -> None:
    h = _hypo()
    assert compute_signature(h) == compute_signature(h)


@pytest.mark.asyncio
async def test_lock_persists_with_signature(lock: HypothesisLock) -> None:
    """Spec test: SQL-backed storage preserves metadata JSON and signature."""
    h = _hypo("claim A")
    expected_sig = compute_signature(h)
    result = await lock.lock(h)
    assert result.signature == expected_sig
    fetched = await lock.verify_lock(result.lock_id)
    assert fetched is True


@pytest.mark.asyncio
async def test_duplicate_lock_raises(lock: HypothesisLock) -> None:
    """Spec: duplicate-permanent raises ValueError when a lock with the same key already exists."""
    from unittest.mock import patch

    h = _hypo()
    # Force two lock() calls to generate the same lock_id (so they hit the same key).
    with patch("mahavishnu.core.precommitment.uuid.uuid4") as mock_uuid:
        mock_uuid.return_value.hex = "abcdef0123456789" * 2  # 32 hex chars; [:12] = "abcdef012345"
        await lock.lock(h)
        # Second call: try_acquire returns None (held) → raises ValueError
        with pytest.raises(ValueError, match="duplicate lock_id"):
            await lock.lock(h)
    # Verify the first lock was actually written
    sql = lock._lock._db  # type: ignore[attr-defined]
    fetched = sql.execute(
        "SELECT lock_key FROM substrate_locks WHERE lock_key = ?",
        ["precommit:l:L-abcdef012345"],
    ).fetchone()
    assert fetched is not None, "first lock must be persisted"


@pytest.mark.asyncio
async def test_verify_lock_returns_false_for_unknown(lock: HypothesisLock) -> None:
    assert await lock.verify_lock("L-does-not-exist") is False


@pytest.mark.asyncio
async def test_signature_mismatch_raises(lock: HypothesisLock) -> None:
    """Spec: tampering with stored hypothesis raises SignatureMismatchError."""
    h = _hypo("original")
    result = await lock.lock(h)

    # Tamper by overwriting the stored metadata with a tampered payload
    import json
    tampered_metadata = {
        "lock_id": result.lock_id,
        "signature": result.signature,  # signature unchanged
        "hypothesis": {
            "claim": "tampered",
            "falsification_criteria": ["a"],
            "success_criteria": ["b"],
            "confidence": 50,
            "locked_at": result.hypothesis.locked_at.isoformat(),
        },
    }
    sql = lock._lock._db  # type: ignore[attr-defined]
    sql.execute(
        "UPDATE substrate_locks SET metadata = ? WHERE lock_key = ?",
        [json.dumps(tampered_metadata), f"precommit:l:{result.lock_id}"],
    )
    with pytest.raises(SignatureMismatchError):
        await lock.verify_lock(result.lock_id)


@pytest.mark.asyncio
async def test_check_post_hoc_matches(lock: HypothesisLock) -> None:
    h = _hypo("my claim")
    result = await lock.lock(h)
    await lock.check_post_hoc(result.lock_id, observed_claim="my claim")


@pytest.mark.asyncio
async def test_check_post_hoc_drift_raises(lock: HypothesisLock) -> None:
    h = _hypo("locked claim")
    result = await lock.lock(h)
    with pytest.raises(HypothesisViolationError):
        await lock.check_post_hoc(result.lock_id, observed_claim="different claim")


@pytest.mark.asyncio
async def test_cross_instance_persistence(file_db: str) -> None:
    """C6 fix: a fresh DharaLock connection against the same file sees prior acquire."""
    # First connection: write
    lock1 = HypothesisLock(dhara_lock=SQLBackendLock(duckdb.connect(file_db)))
    h = _hypo("persisted")
    result = await lock1.lock(h)
    assert result.lock_id.startswith("L-")

    # Second connection: read
    lock2 = HypothesisLock(dhara_lock=SQLBackendLock(duckdb.connect(file_db)))
    fetched = await lock2.verify_lock(result.lock_id)
    assert fetched is True, "cross-instance persistence must round-trip via file-backed DuckDB"
