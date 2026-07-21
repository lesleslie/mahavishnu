"""Precommitment hypothesis lock (Spec #2).

This module implements the structural lock that prevents post-hoc
rationalization of agent hypotheses. The pattern (synthesised from
Rebuilt Hermes / MAOS / IDSD / Building a Production Agent Harness)
freezes a hypothesis at iteration 0 of an investigation so downstream
iterations can be checked for silent claim drift.

Public surface:

- ``Hypothesis``              — frozen dataclass
- ``LockResult``              — frozen dataclass (lock_id + signature + hypothesis)
- ``compute_signature(payload)`` — stable sha256 hex over canonical JSON
- ``HypothesisLock(store)``   — main entry point; lock / verify / check_post_hoc
- ``LockStore``               — Protocol (runtime_checkable)
- ``InMemoryLockStore``       — v0 reference implementation (swappable for Dhara)
- ``HypothesisViolationError``     — raised on claim drift
- ``SignatureMismatchError``       — raised on lock tamper

Why no Dhara dependency in Phase 1? Spec #2 is explicitly substrate-ready
with no substrate dependency. The ``LockStore`` Protocol keeps the seam
clean for a future Dhara implementation, mirroring Spec #5's
``SkillPipeline`` / ``InMemorySkillPipeline`` / ``DharaSkillPipeline``
triad.
"""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
import uuid

from mahavishnu.core.errors import ErrorCode, MahavishnuError
from mahavishnu.core.json_state_store import (
    atomic_json_write,
    locked_json_modify,
    locked_json_read,
)

# ─────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────


class HypothesisViolationError(MahavishnuError):
    """Raised when a downstream iteration's claim drifts from the locked
    hypothesis.

    This is the post-hoc detection signal: once a hypothesis is locked
    at iteration 0, every later iteration must produce a claim that
    matches. Drift is the canonical signature of post-hoc rationalisation.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(
            message,
            error_code=ErrorCode.PRECOMMITMENT_VIOLATION,
        )


class SignatureMismatchError(MahavishnuError):
    """Raised when a lock's stored hypothesis has been tampered with.

    A ``verify_lock`` call computes a fresh signature over the currently
    stored hypothesis and compares it to the recorded signature. A
    mismatch means the lock has been altered after signing and the
    result must not be trusted.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(
            message,
            error_code=ErrorCode.PRECOMMITMENT_SIGNATURE_MISMATCH,
        )


# ─────────────────────────────────────────────────────────────────────────
# Hypothesis + LockResult
# ─────────────────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class Hypothesis:
    """A pre-iteration-0 hypothesis the agent commits to.

    Frozen + validated. The ``confidence`` field is bounded to [0, 100]
    so it can be wired into the future Spec #3 confidence-ceiling-gate
    arithmetic without runtime surprises.
    """

    claim: str
    falsification_criteria: tuple[str, ...]
    success_criteria: tuple[str, ...]
    confidence: int
    locked_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.confidence, int) or isinstance(self.confidence, bool):
            raise TypeError(f"confidence must be int (got {type(self.confidence).__name__})")
        if not 0 <= self.confidence <= 100:
            raise ValueError(f"confidence must be in [0, 100] (got {self.confidence})")


@dataclasses.dataclass(frozen=True)
class LockResult:
    """An immutable record of a locked hypothesis.

    ``lock_id`` is the durable handle the agent carries around to
    reference the lock later. ``signature`` is the canonical-JSON sha256
    over the hypothesis, computed at lock time. ``hypothesis`` is the
    exact frozen record that was signed.
    """

    lock_id: str
    signature: str
    hypothesis: Hypothesis


# ─────────────────────────────────────────────────────────────────────────
# Signature computation
# ─────────────────────────────────────────────────────────────────────────


def _canonical_payload(payload: Any) -> Any:
    """Normalise ``payload`` into a JSON-serialisable canonical form.

    - dataclasses → dict via ``dataclasses.asdict``
    - tuples / sets → sorted lists
    - datetimes → ISO 8601 strings

    The intent is to produce a tree whose JSON dump is stable across
    Python invocations and dict insertion orders.
    """

    if dataclasses.is_dataclass(payload) and not isinstance(payload, type):
        return _canonical_payload(dataclasses.asdict(payload))
    if isinstance(payload, Mapping):
        # Sort keys for canonical ordering.
        return {k: _canonical_payload(payload[k]) for k in sorted(payload)}
    if isinstance(payload, (tuple, set, frozenset)):
        return sorted(_canonical_payload(v) for v in payload)
    if isinstance(payload, list):
        return [_canonical_payload(v) for v in payload]
    if isinstance(payload, datetime):
        # ISO 8601 UTC, normalised to second precision.
        return payload.isoformat()
    return payload


def compute_signature(payload: Any) -> str:
    """Return the sha256 hex digest over the canonical-JSON form of ``payload``.

    Accepts dataclasses, dicts, lists, tuples, sets, datetimes. Two
    payloads that are equal in canonical form (e.g. dicts with the
    same keys and values regardless of insertion order) yield the same
    signature.
    """
    canonical = _canonical_payload(payload)
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ─────────────────────────────────────────────────────────────────────────
# LockStore Protocol + InMemoryLockStore
# ─────────────────────────────────────────────────────────────────────────


@runtime_checkable
class LockStore(Protocol):
    """Durable storage interface for ``LockResult`` records.

    Implementations must:

    - reject duplicate ``lock_id`` on ``put`` to preserve append-only semantics
    - return ``None`` from ``get`` for unknown ``lock_id`` (not raise)
    - return ``history()`` in insertion order for auditability
    """

    def put(self, result: LockResult) -> None:
        """Persist ``result``. Must reject duplicate ``lock_id``."""
        ...

    def get(self, lock_id: str) -> LockResult | None:
        """Return the lock for ``lock_id``, or ``None`` if unknown."""
        ...

    def history(self) -> list[LockResult]:
        """Return all locks in insertion order."""
        ...


class InMemoryLockStore:
    """Reference ``LockStore`` implementation backed by a Python dict.

    Suitable for tests, local development, and the no-substrate Phase 1
    of Spec #2. A future Dhara-backed implementation will satisfy the
    same Protocol by inserting rows into a Dhara table.
    """

    def __init__(self) -> None:
        self._items: dict[str, LockResult] = {}

    def put(self, result: LockResult) -> None:
        if result.lock_id in self._items:
            raise ValueError(f"duplicate lock_id: {result.lock_id}")
        self._items[result.lock_id] = result

    def get(self, lock_id: str) -> LockResult | None:
        return self._items.get(lock_id)

    def history(self) -> list[LockResult]:
        return list(self._items.values())


def _default_lock_store_path() -> Path:
    """Return ``$XDG_CACHE_HOME/mahavishnu/precommitment_locks.json``.

    Honors the XDG Base Directory spec so operators can control cache
    location. Falls back to ``~/.cache/mahavishnu/`` when the variable
    is unset (typical macOS / Linux default).
    """
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "mahavishnu" / "precommitment_locks.json"


class JsonFileLockStore:
    """Persistent ``LockStore`` implementation backed by a JSON file.

    Each instance opens the same file via ``fcntl.flock`` so concurrent
    writers serialize safely. ``put`` is atomic (write-to-temp +
    rename) so a crash mid-write can never leave a partially-written
    lock file. The store is process-independent: a ``lock`` written by
    one invocation of the CLI is visible to a later invocation of
    ``verify_lock`` or ``check_post_hoc``.

    This is the production default store for the ``precommit`` CLI.
    ``InMemoryLockStore`` remains the test fixture and the substrate
    abstraction; a future ``DharaLockStore`` will satisfy the same
    ``LockStore`` protocol.

    Implementation note: this class delegates all flock + atomic-write
    mechanics to ``mahavishnu.core.json_state_store``. ``put`` uses
    ``locked_json_modify`` to atomically read-modify-write; reads
    (``get``/``history``) use ``locked_json_read``. This is the single
    source of truth for the flock + atomic-rename pattern (was
    triplicated pre-2026-07-20 per multi-agent review Architecture #1).
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else _default_lock_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_all(self) -> list[LockResult]:
        """Read all locks from disk. Returns ``[]`` if missing or corrupt.

        Delegates to ``locked_json_read`` (which uses ``O_NOFOLLOW`` +
        ``flock``) from ``mahavishnu.core.json_state_store``.
        """
        try:
            data = locked_json_read(self.path)
        except (json.JSONDecodeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [
            _decode_lock_result(item)
            for item in data
            if isinstance(item, dict)
        ]

    def _write_all(self, results: list[LockResult]) -> None:
        """Atomically write ``results`` to disk via ``atomic_json_write``."""
        encoded = [_encode_lock_result(r) for r in results]
        atomic_json_write(self.path, encoded)

    def put(self, result: LockResult) -> None:
        """Persist ``result``. Reject duplicate ``lock_id``.

        Read-modify-write via ``locked_json_modify`` so concurrent
        writers serialize under a single ``LOCK_EX`` on the lockfile
        across the entire read and write (closes the lost-update race
        pattern that the prior ``_read_all`` + ``_write_all`` had).
        """
        new_entry = _encode_lock_result(result)

        def modifier(data):
            items: list[dict[str, Any]] = list(data) if data is not None else []
            if any(r.get("lock_id") == new_entry["lock_id"] for r in items):
                raise ValueError(f"duplicate lock_id: {result.lock_id}")
            items.append(new_entry)
            return items

        locked_json_modify(self.path, modifier)

    # Convenience alias matching how production code uses it; semantically
    # identical to ``put`` — exposed so tests can call it without importing
    # ``LockResult`` separately when the store stands alone.
    put_result = put

    def get(self, lock_id: str) -> LockResult | None:
        for r in self._read_all():
            if r.lock_id == lock_id:
                return r
        return None

    def history(self) -> list[LockResult]:
        return self._read_all()


def _encode_lock_result(result: LockResult) -> dict[str, Any]:
    """Serialise a ``LockResult`` to a JSON-safe dict."""
    h = result.hypothesis
    return {
        "lock_id": result.lock_id,
        "signature": result.signature,
        "hypothesis": {
            "claim": h.claim,
            "falsification_criteria": list(h.falsification_criteria),
            "success_criteria": list(h.success_criteria),
            "confidence": h.confidence,
            "locked_at": h.locked_at.isoformat(),
        },
    }


def _decode_lock_result(payload: Mapping[str, Any]) -> LockResult:
    """Reconstruct a ``LockResult`` from a JSON-safe dict."""
    h = payload["hypothesis"]
    return LockResult(
        lock_id=payload["lock_id"],
        signature=payload["signature"],
        hypothesis=Hypothesis(
            claim=h["claim"],
            falsification_criteria=tuple(h["falsification_criteria"]),
            success_criteria=tuple(h["success_criteria"]),
            confidence=h["confidence"],
            locked_at=datetime.fromisoformat(h["locked_at"]),
        ),
    )


# ─────────────────────────────────────────────────────────────────────────
# HypothesisLock
# ─────────────────────────────────────────────────────────────────────────


class HypothesisLock:
    """Lock / verify / check_post_hoc against a ``LockStore``.

    Usage::

        store = InMemoryLockStore()
        lock = HypothesisLock(store=store)
        result = lock.lock(hypothesis)        # LockResult
        assert lock.verify_lock(result.lock_id) is True
        lock.check_post_hoc(result.lock_id, observed_claim="...")

    The lock is purely functional — no global state, no I/O outside the
    supplied ``LockStore``.
    """

    def __init__(self, *, store: LockStore) -> None:
        self._store = store

    def lock(self, hypothesis: Hypothesis) -> LockResult:
        """Sign ``hypothesis``, persist via the store, return the LockResult."""
        signature = compute_signature(hypothesis)
        lock_id = f"L-{uuid.uuid4().hex[:12]}"
        result = LockResult(
            lock_id=lock_id,
            signature=signature,
            hypothesis=hypothesis,
        )
        self._store.put(result)
        return result

    def verify_lock(self, lock_id: str) -> bool:
        """Return True iff the stored lock matches its recorded signature.

        Raises ``SignatureMismatchError`` if the stored hypothesis has been
        tampered with (signature does not match). Returns False if the
        ``lock_id`` is unknown.
        """
        stored = self._store.get(lock_id)
        if stored is None:
            return False
        fresh = compute_signature(stored.hypothesis)
        if fresh != stored.signature:
            raise SignatureMismatchError(
                f"lock_id={lock_id} hypothesis has been altered since signing"
            )
        return True

    def check_post_hoc(self, lock_id: str, *, observed_claim: str) -> None:
        """Verify that ``observed_claim`` matches the locked claim.

        Raises ``SignatureMismatchError`` if the lock itself is broken.
        Raises ``HypothesisViolationError`` if ``observed_claim`` disagrees
        with the locked claim.
        """
        # First verify the lock itself.
        if not self.verify_lock(lock_id):
            raise SignatureMismatchError(f"lock_id={lock_id} not found")
        stored = self._store.get(lock_id)
        assert stored is not None  # verify_lock just confirmed it exists
        if stored.hypothesis.claim != observed_claim:
            raise HypothesisViolationError(
                f"claim drift for lock_id={lock_id}: "
                f"locked={stored.hypothesis.claim!r} "
                f"observed={observed_claim!r}"
            )


__all__ = [
    "Hypothesis",
    "HypothesisLock",
    "HypothesisViolationError",
    "InMemoryLockStore",
    "JsonFileLockStore",
    "LockResult",
    "LockStore",
    "SignatureMismatchError",
    "compute_signature",
]
