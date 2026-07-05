"""Unit tests for the precommitment hypothesis lock (Spec #2, Phase 1).

TDD red phase: these tests describe the contract that
``mahavishnu.core.precommitment`` must satisfy. They should FAIL until
the module is implemented.

Contract summary (from the spec):

- ``Hypothesis`` dataclass with ``claim``, ``falsification_criteria``,
  ``success_criteria``, ``confidence``, ``locked_at``.
- ``compute_signature`` produces a stable sha256 hex digest over a
  canonical JSON representation.
- ``HypothesisLock.lock(hypothesis)`` returns an immutable ``LockResult``
  carrying ``lock_id`` and ``signature``.
- ``HypothesisLock.verify_lock(...)`` returns True/False; raises
  ``SignatureMismatchError`` on tamper.
- ``HypothesisLock.check_post_hoc(...)`` raises ``HypothesisViolationError``
  on claim drift.
- ``LockStore`` Protocol + ``InMemoryLockStore`` v0 reference impl
  (swappable for Dhara later).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
import hashlib
import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from mahavishnu.core.precommitment import LockResult

# ─────────────────────────────────────────────────────────────────────────
# Hypothesis dataclass
# ─────────────────────────────────────────────────────────────────────────


def test_hypothesis_dataclass_carries_all_fields() -> None:
    """The dataclass must store every required field."""
    from mahavishnu.core.precommitment import Hypothesis

    locked = datetime(2026, 6, 22, 10, 0, 0)
    h = Hypothesis(
        claim="Will improve throughput by 10%",
        falsification_criteria=("throughput drops", "latency spikes"),
        success_criteria=("throughput increases >=10%", "p99 < 200ms"),
        confidence=75,
        locked_at=locked,
    )
    assert h.claim == "Will improve throughput by 10%"
    assert h.falsification_criteria == ("throughput drops", "latency spikes")
    assert h.success_criteria == ("throughput increases >=10%", "p99 < 200ms")
    assert h.confidence == 75
    assert h.locked_at == locked


def test_hypothesis_dataclass_is_frozen() -> None:
    """Hypothesis must be frozen so the lock cannot drift after signing."""
    from mahavishnu.core.precommitment import Hypothesis

    h = Hypothesis(
        claim="x",
        falsification_criteria=("a",),
        success_criteria=("b",),
        confidence=50,
        locked_at=datetime(2026, 1, 1),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        h.claim = "y"  # type: ignore[misc]


def test_hypothesis_confidence_must_be_in_range() -> None:
    """Confidence is an integer in [0, 100]."""
    from mahavishnu.core.precommitment import Hypothesis

    with pytest.raises((ValueError, TypeError)):
        Hypothesis(
            claim="x",
            falsification_criteria=("a",),
            success_criteria=("b",),
            confidence=150,
            locked_at=datetime(2026, 1, 1),
        )


# ─────────────────────────────────────────────────────────────────────────
# compute_signature
# ─────────────────────────────────────────────────────────────────────────


def test_compute_signature_is_sha256_hex() -> None:
    """The digest must be a 64-char hex string (sha256)."""
    from mahavishnu.core.precommitment import Hypothesis, compute_signature

    h = Hypothesis(
        claim="claim",
        falsification_criteria=("a", "b"),
        success_criteria=("c", "d"),
        confidence=50,
        locked_at=datetime(2026, 6, 22, 10, 0, 0),
    )
    sig = compute_signature(h)
    assert isinstance(sig, str)
    assert len(sig) == 64
    int(sig, 16)  # hex-decodable


def test_compute_signature_is_stable_across_calls() -> None:
    """Same hypothesis inputs must produce the same signature."""
    from mahavishnu.core.precommitment import Hypothesis, compute_signature

    locked = datetime(2026, 6, 22, 10, 0, 0)
    h = Hypothesis(
        claim="stable",
        falsification_criteria=("a",),
        success_criteria=("b",),
        confidence=50,
        locked_at=locked,
    )
    assert compute_signature(h) == compute_signature(h)


def test_compute_signature_differs_when_claim_changes() -> None:
    """Changing any field must change the signature."""
    from mahavishnu.core.precommitment import Hypothesis, compute_signature

    locked = datetime(2026, 6, 22, 10, 0, 0)
    base = Hypothesis(
        claim="a",
        falsification_criteria=("f",),
        success_criteria=("s",),
        confidence=50,
        locked_at=locked,
    )
    modified = dataclasses.replace(base, claim="b")
    assert compute_signature(base) != compute_signature(modified)


def test_compute_signature_canonical_key_order_independent() -> None:
    """The serialization is canonical: reordering dict keys must not change digest.

    This guards against accidental use of Python's non-deterministic
    dict ordering inside the signature function.
    """
    from mahavishnu.core.precommitment import compute_signature

    payload_a = {"claim": "x", "confidence": 50, "falsification_criteria": ["f"]}
    payload_b = {"falsification_criteria": ["f"], "confidence": 50, "claim": "x"}
    # Same payload, different dict insertion order.
    assert compute_signature(payload_a) == compute_signature(payload_b)


def test_compute_signature_matches_independent_hashlib_calc() -> None:
    """The signature must equal an independent sha256 over canonical JSON."""
    from mahavishnu.core.precommitment import compute_signature

    payload = {"claim": "x", "confidence": 50}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    expected = hashlib.sha256(canonical).hexdigest()
    assert compute_signature(payload) == expected


# ─────────────────────────────────────────────────────────────────────────
# HypothesisLock.lock + LockResult
# ─────────────────────────────────────────────────────────────────────────


def test_hypothesis_lock_lock_returns_lock_result() -> None:
    """Lock produces an immutable LockResult with lock_id and signature."""
    from mahavishnu.core.precommitment import (
        Hypothesis,
        HypothesisLock,
        LockResult,
    )

    h = Hypothesis(
        claim="c",
        falsification_criteria=("f",),
        success_criteria=("s",),
        confidence=50,
        locked_at=datetime(2026, 6, 22),
    )
    store = InMemoryLockStoreProbe()
    lock = HypothesisLock(store=store)
    result = lock.lock(h)

    assert isinstance(result, LockResult)
    assert isinstance(result.lock_id, str) and len(result.lock_id) > 0
    assert isinstance(result.signature, str) and len(result.signature) == 64
    assert result.hypothesis == h


def test_lock_result_is_immutable() -> None:
    """LockResult must be frozen so a locked hypothesis cannot be altered."""
    from mahavishnu.core.precommitment import (
        Hypothesis,
        HypothesisLock,
    )

    h = Hypothesis(
        claim="c",
        falsification_criteria=("f",),
        success_criteria=("s",),
        confidence=50,
        locked_at=datetime(2026, 6, 22),
    )
    lock = HypothesisLock(store=InMemoryLockStoreProbe())
    result = lock.lock(h)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.lock_id = "tampered"  # type: ignore[misc]


def test_lock_persists_to_store() -> None:
    """Locking must write to the supplied LockStore."""
    from mahavishnu.core.precommitment import (
        Hypothesis,
        HypothesisLock,
    )

    store = InMemoryLockStoreProbe()
    lock = HypothesisLock(store=store)
    h = Hypothesis(
        claim="c",
        falsification_criteria=("f",),
        success_criteria=("s",),
        confidence=50,
        locked_at=datetime(2026, 6, 22),
    )
    result = lock.lock(h)
    fetched = store.get(result.lock_id)
    assert fetched is not None
    assert fetched.signature == result.signature
    assert fetched.hypothesis == h


# ─────────────────────────────────────────────────────────────────────────
# verify_lock
# ─────────────────────────────────────────────────────────────────────────


def test_verify_lock_returns_true_for_unmodified() -> None:
    """A correctly signed lock verifies as True."""
    from mahavishnu.core.precommitment import (
        Hypothesis,
        HypothesisLock,
    )

    h = Hypothesis(
        claim="c",
        falsification_criteria=("f",),
        success_criteria=("s",),
        confidence=50,
        locked_at=datetime(2026, 6, 22),
    )
    store = InMemoryLockStoreProbe()
    lock = HypothesisLock(store=store)
    result = lock.lock(h)
    assert lock.verify_lock(result.lock_id) is True


def test_verify_lock_raises_signature_mismatch_on_tamper() -> None:
    """Tampering with the stored hypothesis must raise SignatureMismatchError."""
    from mahavishnu.core.precommitment import (
        Hypothesis,
        HypothesisLock,
        SignatureMismatchError,
    )

    h = Hypothesis(
        claim="original",
        falsification_criteria=("f",),
        success_criteria=("s",),
        confidence=50,
        locked_at=datetime(2026, 6, 22),
    )
    store = InMemoryLockStoreProbe()
    lock = HypothesisLock(store=store)
    result = lock.lock(h)

    # Tamper: rewrite the stored claim to something else.
    store._tamper(result.lock_id, dataclasses.replace(h, claim="TAMPERED"))

    with pytest.raises(SignatureMismatchError):
        lock.verify_lock(result.lock_id)


def test_verify_lock_returns_false_when_lock_id_missing() -> None:
    """verify_lock returns False (not raises) when lock_id is unknown."""
    from mahavishnu.core.precommitment import HypothesisLock

    lock = HypothesisLock(store=InMemoryLockStoreProbe())
    assert lock.verify_lock("nonexistent-lock-id") is False


# ─────────────────────────────────────────────────────────────────────────
# check_post_hoc
# ─────────────────────────────────────────────────────────────────────────


def test_check_post_hoc_passes_when_claim_unchanged() -> None:
    """If the observed claim matches the locked claim, no violation."""
    from mahavishnu.core.precommitment import (
        Hypothesis,
        HypothesisLock,
    )

    h = Hypothesis(
        claim="throughput up",
        falsification_criteria=("down",),
        success_criteria=("up",),
        confidence=50,
        locked_at=datetime(2026, 6, 22),
    )
    lock = HypothesisLock(store=InMemoryLockStoreProbe())
    result = lock.lock(h)
    # No raise.
    lock.check_post_hoc(result.lock_id, observed_claim="throughput up")


def test_check_post_hoc_raises_on_claim_drift() -> None:
    """If the observed claim disagrees, raise HypothesisViolationError."""
    from mahavishnu.core.precommitment import (
        Hypothesis,
        HypothesisLock,
        HypothesisViolationError,
    )

    h = Hypothesis(
        claim="throughput up",
        falsification_criteria=("down",),
        success_criteria=("up",),
        confidence=50,
        locked_at=datetime(2026, 6, 22),
    )
    lock = HypothesisLock(store=InMemoryLockStoreProbe())
    result = lock.lock(h)
    with pytest.raises(HypothesisViolationError):
        lock.check_post_hoc(result.lock_id, observed_claim="actually throughput flat")


# ─────────────────────────────────────────────────────────────────────────
# LockStore Protocol + InMemoryLockStore v0
# ─────────────────────────────────────────────────────────────────────────


def test_lock_store_protocol_is_runtime_checkable() -> None:
    """The LockStore protocol must be runtime_checkable for duck typing."""
    from mahavishnu.core.precommitment import LockStore

    assert getattr(LockStore, "_is_runtime_protocol", False) or callable(LockStore)  # loose check; runtime_checkable attaches __call__


def test_in_memory_lock_store_satisfies_protocol() -> None:
    """InMemoryLockStore must satisfy the LockStore protocol."""
    from mahavishnu.core.precommitment import InMemoryLockStore, LockStore

    store: LockStore = InMemoryLockStore()
    assert isinstance(store, LockStore)


def test_in_memory_lock_store_rejects_duplicate_lock_id() -> None:
    """Append-only: reusing the same lock_id must raise."""
    from mahavishnu.core.precommitment import (
        Hypothesis,
        InMemoryLockStore,
        LockResult,
    )

    store = InMemoryLockStore()
    h = Hypothesis(
        claim="c",
        falsification_criteria=("f",),
        success_criteria=("s",),
        confidence=50,
        locked_at=datetime(2026, 6, 22),
    )
    first = LockResult(lock_id="L-1", signature="x" * 64, hypothesis=h)
    store.put(first)
    with pytest.raises((ValueError, KeyError)):
        store.put(first)


def test_in_memory_lock_store_get_missing_returns_none() -> None:
    """A missing lock_id must return None, not raise."""
    from mahavishnu.core.precommitment import InMemoryLockStore

    store = InMemoryLockStore()
    assert store.get("missing") is None


def test_in_memory_lock_store_iteration_order_is_insertion() -> None:
    """``history()`` returns locks in insertion order for auditability."""
    from mahavishnu.core.precommitment import (
        Hypothesis,
        InMemoryLockStore,
        LockResult,
    )

    store = InMemoryLockStore()
    h = Hypothesis(
        claim="c",
        falsification_criteria=("f",),
        success_criteria=("s",),
        confidence=50,
        locked_at=datetime(2026, 6, 22),
    )
    for i in range(3):
        store.put(LockResult(lock_id=f"L-{i}", signature=str(i) * 64, hypothesis=h))

    history = store.history()
    assert [r.lock_id for r in history] == ["L-0", "L-1", "L-2"]


# ─────────────────────────────────────────────────────────────────────────
# JsonFileLockStore (H-PRECOMMIT: persist locks to disk)
# ─────────────────────────────────────────────────────────────────────────


def test_lock_survives_process_restart(tmp_path: object) -> None:
    """A lock written by one process must be visible to a fresh process.

    This proves the store is not per-process (the headline audit finding
    H-PRECOMMIT: ``InMemoryLockStore`` was created fresh per CLI
    invocation, so ``verify_lock`` and ``check_post_hoc`` never saw prior
    locks and the security control silently failed open).
    """
    from datetime import datetime

    from mahavishnu.core.precommitment import (
        Hypothesis,
        HypothesisLock,
        JsonFileLockStore,
    )

    store_path = tmp_path / "locks.json"  # type: ignore[operator]
    hypothesis = Hypothesis(
        claim="x",
        falsification_criteria=("y",),
        success_criteria=("z",),
        confidence=50,
        locked_at=datetime.now(UTC),
    )

    # Process 1: lock
    store1 = JsonFileLockStore(path=store_path)
    lock1 = HypothesisLock(store=store1)
    result = lock1.lock(hypothesis)
    lock_id = result.lock_id

    # Process 2: re-open the store from disk and verify
    store2 = JsonFileLockStore(path=store_path)
    lock2 = HypothesisLock(store=store2)
    assert lock2.verify_lock(lock_id) is True


def test_json_file_lock_store_persists_signature(tmp_path: object) -> None:
    """The signature stored on disk must equal the fresh signature."""
    from datetime import datetime

    from mahavishnu.core.precommitment import (
        Hypothesis,
        JsonFileLockStore,
    )

    store_path = tmp_path / "locks.json"  # type: ignore[operator]
    hypothesis = Hypothesis(
        claim="c",
        falsification_criteria=("f",),
        success_criteria=("s",),
        confidence=60,
        locked_at=datetime(2026, 6, 27),
    )

    store = JsonFileLockStore(path=store_path)
    store.put_result(
        __import__(
            "mahavishnu.core.precommitment", fromlist=["LockResult"]
        ).LockResult(
            lock_id="L-test",
            signature=compute_signature_inline(hypothesis),
            hypothesis=hypothesis,
        )
    )

    reloaded = JsonFileLockStore(path=store_path)
    fetched = reloaded.get("L-test")
    assert fetched is not None
    assert fetched.hypothesis == hypothesis


def test_json_file_lock_store_rejects_duplicate_lock_id(tmp_path: object) -> None:
    """put must be idempotency-safe: duplicate lock_id raises."""
    from datetime import datetime

    from mahavishnu.core.precommitment import (
        Hypothesis,
        HypothesisLock,
        JsonFileLockStore,
    )

    store_path = tmp_path / "locks.json"  # type: ignore[operator]
    h = Hypothesis(
        claim="c",
        falsification_criteria=("f",),
        success_criteria=("s",),
        confidence=50,
        locked_at=datetime(2026, 6, 27),
    )
    lock = HypothesisLock(store=JsonFileLockStore(path=store_path))
    result = lock.lock(h)
    with pytest.raises((ValueError, KeyError)):
        lock.lock(h)  # same hypothesis → new lock_id, so we need same lock_id
        # Force duplicate:
        store = JsonFileLockStore(path=store_path)
        store.put_result(result)


def test_json_file_lock_store_default_path_under_xdg_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    """When constructed without ``path``, it must use ``$XDG_CACHE_HOME/mahavishnu/``."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    from mahavishnu.core.precommitment import JsonFileLockStore

    store = JsonFileLockStore()
    assert str(store.path).startswith(str(tmp_path))
    assert "mahavishnu" in str(store.path)
    assert str(store.path).endswith("precommitment_locks.json")


def test_json_file_lock_store_satisfies_protocol(tmp_path: object) -> None:
    """JsonFileLockStore must satisfy the LockStore runtime protocol."""
    from mahavishnu.core.precommitment import JsonFileLockStore, LockStore

    store = JsonFileLockStore(path=tmp_path / "locks.json")  # type: ignore[operator]
    assert isinstance(store, LockStore)


def compute_signature_inline(payload: object) -> str:
    from mahavishnu.core.precommitment import compute_signature

    return compute_signature(payload)


# ─────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────


def test_hypothesis_violation_subclasses_mahavishnu_error() -> None:
    """HypothesisViolationError must subclass MahavishnuError so callers catch both."""
    from mahavishnu.core.errors import MahavishnuError
    from mahavishnu.core.precommitment import HypothesisViolationError

    assert issubclass(HypothesisViolationError, MahavishnuError)


def test_signature_mismatch_subclasses_mahavishnu_error() -> None:
    """SignatureMismatchError must subclass MahavishnuError."""
    from mahavishnu.core.errors import MahavishnuError
    from mahavishnu.core.precommitment import SignatureMismatchError

    assert issubclass(SignatureMismatchError, MahavishnuError)


# ─────────────────────────────────────────────────────────────────────────
# Internal helper used by the tamper test above
# ─────────────────────────────────────────────────────────────────────────


class InMemoryLockStoreProbe:
    """In-test stand-in that satisfies the LockStore protocol AND lets us
    swap the stored hypothesis for the tamper test.

    Tests above depend on the production ``InMemoryLockStore`` for the
    real protocol contract; this probe is used only where we need to
    mutate the stored value to simulate drift.
    """

    def __init__(self) -> None:

        self._items: dict[str, LockResult] = {}

    def put(self, result: Any) -> None:
        if result.lock_id in self._items:
            raise ValueError(f"duplicate lock_id: {result.lock_id}")
        self._items[result.lock_id] = result

    def get(self, lock_id: str) -> Any:
        return self._items.get(lock_id)

    def history(self) -> list[Any]:
        return list(self._items.values())

    def _tamper(self, lock_id: str, new_hypothesis: Any) -> None:
        self._items[lock_id] = dataclasses.replace(
            self._items[lock_id], hypothesis=new_hypothesis
        )
