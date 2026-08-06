"""Precommitment hypothesis lock (Spec #2) — D-LOCK backed, async."""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses
from datetime import datetime
import hashlib
import json
from typing import Any
import uuid

from dhara.lock import DharaLock

from mahavishnu.core.errors import ErrorCode, MahavishnuError

# Exceptions (unchanged shape)
class HypothesisViolationError(MahavishnuError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message, error_code=ErrorCode.PRECOMMITMENT_VIOLATION)


class SignatureMismatchError(MahavishnuError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message, error_code=ErrorCode.PRECOMMITMENT_SIGNATURE_MISMATCH)


@dataclasses.dataclass(frozen=True)
class Hypothesis:
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
    lock_id: str
    signature: str
    hypothesis: Hypothesis


def _canonical_payload(payload: Any) -> Any:
    if dataclasses.is_dataclass(payload) and not isinstance(payload, type):
        return _canonical_payload(dataclasses.asdict(payload))
    if isinstance(payload, Mapping):
        return {k: _canonical_payload(payload[k]) for k in sorted(payload)}
    if isinstance(payload, (tuple, set, frozenset)):
        return sorted(_canonical_payload(v) for v in payload)
    if isinstance(payload, list):
        return [_canonical_payload(v) for v in payload]
    if isinstance(payload, datetime):
        return payload.isoformat()
    return payload


def compute_signature(payload: Any) -> str:
    canonical = _canonical_payload(payload)
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _encode_lock_result(result: LockResult) -> dict[str, Any]:
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


class HypothesisLock:
    """Async, D-LOCK backed."""

    def __init__(self, *, dhara_lock: DharaLock, owner_token: str = "precommit-cli") -> None:
        self._lock = dhara_lock
        self._owner = owner_token

    def _key(self, lock_id: str) -> str:
        return f"precommit:l:{lock_id}"

    async def lock(self, hypothesis: Hypothesis) -> LockResult:
        signature = compute_signature(hypothesis)
        lock_id = f"L-{uuid.uuid4().hex[:12]}"
        result = LockResult(lock_id=lock_id, signature=signature, hypothesis=hypothesis)
        handle = self._lock.try_acquire(
            self._key(lock_id),
            owner_token=self._owner,
            permanent=True,
            metadata=_encode_lock_result(result),
        )
        if handle is None:
            raise ValueError(f"duplicate lock_id: {lock_id}")
        return result

    async def verify_lock(self, lock_id: str) -> bool:
        handle = self._lock.get(self._key(lock_id))
        if handle is None:
            return False
        stored = _decode_lock_result(handle.metadata)
        fresh = compute_signature(stored.hypothesis)
        if fresh != stored.signature:
            raise SignatureMismatchError(
                f"lock_id={lock_id} hypothesis has been altered since signing"
            )
        return True

    async def check_post_hoc(self, lock_id: str, *, observed_claim: str) -> None:
        if not await self.verify_lock(lock_id):
            raise SignatureMismatchError(f"lock_id={lock_id} not found")
        handle = self._lock.get(self._key(lock_id))
        if handle is None:
            raise SignatureMismatchError(f"lock_id={lock_id} not found")
        stored = _decode_lock_result(handle.metadata)
        if stored.hypothesis.claim != observed_claim:
            raise HypothesisViolationError(
                f"claim drift for lock_id={lock_id}: "
                f"locked={stored.hypothesis.claim!r} observed={observed_claim!r}"
            )


__all__ = [
    "Hypothesis",
    "HypothesisLock",
    "HypothesisViolationError",
    "LockResult",
    "SignatureMismatchError",
    "compute_signature",
]
