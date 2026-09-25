"""Precommitment tests — local Lock backed, async.

Migrated from mcp.lock.sql.SQLBackendLock to
``mahavishnu.core._lock_sentinel.Lock`` per Phase 8 Task 5 of the
Dhara MCP retirement plan. The cross-instance persistence test
(``test_cross_instance_persistence``) is intentionally dropped:
an in-process dict-backed sentinel cannot provide that guarantee
across separate processes. If cross-instance persistence is required
in the future, a SQL/DuckDB-backed lock service would need to be
plugged into ``_lock_sentinel.py``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest

from mahavishnu.core._lock_sentinel import Lock
from mahavishnu.core.precommitment import (
    Hypothesis,
    HypothesisLock,
    HypothesisViolationError,
    SignatureMismatchError,
    compute_signature,
)


@pytest.fixture
def lock() -> HypothesisLock:
    """HypothesisLock backed by a fresh in-process Lock sentinel."""
    return HypothesisLock(lock=Lock())


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
    """Spec test: in-process storage preserves metadata JSON and signature."""
    h = _hypo("claim A")
    expected_sig = compute_signature(h)
    result = await lock.lock(h)
    assert result.signature == expected_sig
    fetched = await lock.verify_lock(result.lock_id)
    assert fetched is True


@pytest.mark.asyncio
async def test_duplicate_lock_raises(lock: HypothesisLock) -> None:
    """Spec: duplicate-permanent raises ValueError when a lock with the same key already exists."""
    h = _hypo()
    # Force two lock() calls to generate the same lock_id (so they hit the same key).
    with patch("mahavishnu.core.precommitment.uuid.uuid4") as mock_uuid:
        mock_uuid.return_value.hex = "abcdef0123456789" * 2  # 32 hex chars; [:12] = "abcdef012345"
        await lock.lock(h)
        # Second call: try_acquire returns None (held) → raises ValueError
        with pytest.raises(ValueError, match="duplicate lock_id"):
            await lock.lock(h)
    # Verify the first lock was actually written to the in-process sentinel.
    items: dict[str, Any] = lock._lock._items  # type: ignore[attr-defined]
    assert items.get("precommit:l:L-abcdef012345") is not None, (
        "first lock must be persisted"
    )


@pytest.mark.asyncio
async def test_verify_lock_returns_false_for_unknown(lock: HypothesisLock) -> None:
    assert await lock.verify_lock("L-does-not-exist") is False


@pytest.mark.asyncio
async def test_signature_mismatch_raises(lock: HypothesisLock) -> None:
    """Spec: tampering with stored hypothesis raises SignatureMismatchError."""
    h = _hypo("original")
    result = await lock.lock(h)

    # Tamper by overwriting the stored metadata with a tampered payload.
    # Local sentinel stores metadata as a dict (no JSON round-trip
    # in-process), unlike the SQL backend which stored it as a JSON string.
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
    items: dict[str, Any] = lock._lock._items  # type: ignore[attr-defined]
    key = f"precommit:l:{result.lock_id}"
    items[key] = replace(items[key], metadata=tampered_metadata)
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
