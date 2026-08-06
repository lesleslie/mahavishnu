"""Async HypothesisLock tests (TDD: written before impl)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace as dc_replace
from datetime import datetime
from importlib.resources import files
from typing import Any

import duckdb
import pytest

from dhara.lock import DharaLock
from dhara.lock.in_memory import InMemoryDharaLock
from dhara.lock.sql import SQLBackendLock

from mahavishnu.core.precommitment import (
    Hypothesis,
    HypothesisLock,
    HypothesisViolationError,
    SignatureMismatchError,
    compute_signature,
)

_MIGRATION_0003 = files("dhara").joinpath("migrations/sql/0003_locks.sql").read_text()


@pytest.fixture
def sql_backend() -> Iterator[Any]:
    c = duckdb.connect(":memory:")
    c.execute(_MIGRATION_0003)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def in_memory_lock() -> DharaLock:
    return InMemoryDharaLock()


@pytest.fixture
def lock_sql(sql_backend: Any) -> HypothesisLock:
    return HypothesisLock(dhara_lock=SQLBackendLock(sql_backend))


@pytest.fixture
def lock_inmem(in_memory_lock: DharaLock) -> HypothesisLock:
    return HypothesisLock(dhara_lock=in_memory_lock)


def _hypo(claim: str = "test") -> Hypothesis:
    return Hypothesis(
        claim=claim,
        falsification_criteria=("a",),
        success_criteria=("b",),
        confidence=80,
        locked_at=datetime.now(),
    )


@pytest.mark.asyncio
async def test_lock_persists_with_signature(lock_inmem: HypothesisLock) -> None:
    """H4 (spec test): signature survives the round-trip in metadata."""
    h = _hypo("claim A")
    expected_sig = compute_signature(h)
    result = await lock_inmem.lock(h)
    assert result.signature == expected_sig

    fetched = await lock_inmem.verify_lock(result.lock_id)
    assert fetched is True


@pytest.mark.asyncio
async def test_verify_lock_returns_false_for_unknown(lock_inmem: HypothesisLock) -> None:
    assert await lock_inmem.verify_lock("L-does-not-exist") is False


@pytest.mark.asyncio
async def test_signature_mismatch_raises(lock_inmem: HypothesisLock) -> None:
    """Tamper with stored metadata — verify must raise SignatureMismatchError."""
    h = _hypo("original")
    result = await lock_inmem.lock(h)

    # Tamper by directly modifying the underlying store's metadata
    dhara = lock_inmem._lock  # type: ignore[attr-defined]
    stored = dhara.get(f"precommit:l:{result.lock_id}")
    assert stored is not None
    tampered_metadata = {
        "lock_id": result.lock_id,
        "signature": "INVALID",
        "hypothesis": {
            "claim": "tampered",
            "falsification_criteria": ["a"],
            "success_criteria": ["b"],
            "confidence": 50,
            "locked_at": result.hypothesis.locked_at.isoformat(),
        },
    }
    # Both backends support tampering via attribute replacement
    if isinstance(dhara, InMemoryDharaLock):
        new_handle = dc_replace(stored, metadata=tampered_metadata)
        dhara._items[f"precommit:l:{result.lock_id}"] = new_handle  # type: ignore[attr-defined]
    else:
        import json
        sql = dhara._db  # type: ignore[attr-defined]
        sql.execute(
            "UPDATE substrate_locks SET metadata = ? WHERE lock_key = ?",
            [json.dumps(tampered_metadata), f"precommit:l:{result.lock_id}"],
        )
    with pytest.raises(SignatureMismatchError):
        await lock_inmem.verify_lock(result.lock_id)


@pytest.mark.asyncio
async def test_check_post_hoc_matches(lock_inmem: HypothesisLock) -> None:
    h = _hypo("my claim")
    result = await lock_inmem.lock(h)
    # No exception
    await lock_inmem.check_post_hoc(result.lock_id, observed_claim="my claim")


@pytest.mark.asyncio
async def test_check_post_hoc_drift_raises(lock_inmem: HypothesisLock) -> None:
    h = _hypo("locked claim")
    result = await lock_inmem.lock(h)
    with pytest.raises(HypothesisViolationError):
        await lock_inmem.check_post_hoc(result.lock_id, observed_claim="different")


@pytest.mark.asyncio
async def test_duplicate_lock_returns_none_from_underlying(
    lock_sql: HypothesisLock,
) -> None:
    """Ambiguity resolution: the underlying try_acquire returns None on duplicate.

    When the same precommit lock key is asked twice, the underlying
    SQLBackendLock.try_acquire returns None (because the first call is
    permanent and the conditional UPSERT returns no rows). The public
    HypothesisLock.lock path doesn't trigger this naturally (UUID4
    lock_ids are unique), so we test the underlying directly: the
    SQL substrate contract is that duplicate permanent acquisition
    returns None.
    """
    h = _hypo("first")
    result = await lock_sql.lock(h)
    key = f"precommit:l:{result.lock_id}"
    second = lock_sql._lock.try_acquire(  # type: ignore[attr-defined]
        key,
        owner_token="someone-else",
        permanent=True,
        metadata={"some": "metadata"},
    )
    assert second is None, "duplicate precommit lock acquisition must return None"
