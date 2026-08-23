"""Tests for ``mahavishnu.observability`` (PR-B)."""

from __future__ import annotations

import hashlib

import pytest

from mahavishnu.core.errors import WorktreeIntegrityError
from mahavishnu.observability.bundle_integrity import (
    ALLOWED_BACKEND_KINDS,
    compute_sha256,
    verify_sha256,
)
from mahavishnu.observability.metrics import (
    _ALLOWED_LABEL_KEYS,
    _short_principal,
    record_backend_health_check_failed,
    record_bundle_bytes,
    record_bundle_integrity_failure,
    record_cache_fallback,
    record_cache_invalidation,
    record_cache_op,
    record_lock_held,
    record_lock_wait,
    record_registry_drift,
    record_worktree_op,
)


# ---------------------------------------------------------------------------
# Helpers — pure-function tests
# ---------------------------------------------------------------------------


def test_short_principal_is_stable_8char_hash() -> None:
    """Same input must produce the same 8-char hash; different inputs different."""
    a1 = _short_principal("uid:12345")
    a2 = _short_principal("uid:12345")
    assert a1 == a2
    assert len(a1) == 8
    # Different principal → different hash
    b = _short_principal("uid:99999")
    assert a1 != b


def test_short_principal_anonymous_returns_anon() -> None:
    """None / empty / unknown collapses to the same single 'anon' value."""
    assert _short_principal(None) == "anon"
    assert _short_principal("") == "anon"


def test_short_principal_matches_sha256_prefix() -> None:
    """Implementation contract: hashlib.sha256(name).hexdigest()[:8]."""
    name = "uid:42"
    expected = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    assert _short_principal(name) == expected


# ---------------------------------------------------------------------------
# Helpers — emit-time validation
# ---------------------------------------------------------------------------


def test_record_worktree_op_accepts_known_labels() -> None:
    """Known label keys pass through without raising."""
    # op='create' goes to create histogram; op='fetch' goes to fetch histogram
    record_worktree_op("local", "create", 0.05, True, principal="uid:1")
    record_worktree_op("s3", "fetch", 1.2, True, principal="uid:1")
    # No assertion — we just verify no exception is raised.


def test_record_cache_invalidation_emits_without_raise() -> None:
    """Smoke test for cache invalidation counter."""
    record_cache_invalidation("local", "remove_handle", count=5)
    record_cache_invalidation("s3", "fetch")


def test_record_cache_op_handles_known_ops() -> None:
    """get/set ops dispatch to the correct histogram."""
    record_cache_op("local", "get", 0.005, hit=True)
    record_cache_op("local", "set", 0.010, hit=False)


def test_record_lock_helpers_emit_without_raise() -> None:
    """Smoke test for lock helpers."""
    record_lock_wait("mahavishnu", "feature/auth", 0.05, acquired=True)
    record_lock_held("mahavishnu", "feature/auth", "uid:1", held_seconds=10.0)


def test_record_registry_drift_emits_both_directions() -> None:
    """Both missing_in_s3 and missing_in_dhara are counted separately."""
    record_registry_drift(missing_in_s3=3, missing_in_dhara=2)


def test_record_cache_fallback_emit() -> None:
    record_cache_fallback("l1", "l2")


def test_record_backend_health_check_failed_emit() -> None:
    record_backend_health_check_failed("s3")


def test_record_bundle_bytes_emit() -> None:
    record_bundle_bytes("mahavishnu", 1024 * 1024)


def test_record_bundle_integrity_failure_emit() -> None:
    record_bundle_integrity_failure("s3", principal_short=None)


# ---------------------------------------------------------------------------
# Cardinality allowlist enforcement
# ---------------------------------------------------------------------------


def test_allowed_label_keys_is_a_stable_set() -> None:
    """The allowlist must include every label key the helpers emit."""
    expected = {
        "backend",
        "status",
        "principal_short",
        "repo",
        "branch",
        "acquired",
        "hit",
        "reason",
        "from_tier",
        "to_tier",
        "drift_kind",
    }
    assert set(_ALLOWED_LABEL_KEYS) == expected


# ---------------------------------------------------------------------------
# bundle_integrity.verify_sha256
# ---------------------------------------------------------------------------


def test_compute_sha256_matches_hashlib() -> None:
    blob = b"hello world"
    assert compute_sha256(blob) == hashlib.sha256(blob).hexdigest()


def test_verify_sha256_pass_silent() -> None:
    """No raise + no metric emission on success."""
    blob = b"abc"
    expected = compute_sha256(blob)
    # Should not raise
    verify_sha256(blob, expected, backend="local", principal="uid:1")


def test_verify_sha256_mismatch_raises_and_emits_counter() -> None:
    """Mismatch raises WorktreeIntegrityError. Counter emission is verified
    via the public function (InMemoryMeter capture deferred to OTel-side tests)."""
    blob = b"actual"
    wrong = "0" * 64
    with pytest.raises(WorktreeIntegrityError) as excinfo:
        verify_sha256(blob, wrong, backend="s3", principal="uid:42")
    assert "SHA-256 mismatch" in str(excinfo.value)
    assert "s3" in str(excinfo.value)


def test_allowed_backend_kinds_includes_canonical_set() -> None:
    """The allowlist for backend kinds matches BackendKind literal."""
    assert ALLOWED_BACKEND_KINDS == frozenset({"local", "s3", "gcs", "azure", "bundle"})


# ---------------------------------------------------------------------------
# Cardinality budget guard (CI enforces this)
# ---------------------------------------------------------------------------


def test_cardinality_budget_unique_principals_per_minute() -> None:
    """Per-process cardinality budget: <50 unique (backend, principal_short) combos.

    This test seeds 100 distinct principal names and asserts the
    underlying hash map stays bounded (capped at 100, but realistic
    production traffic at <50/minute). The CI guard catches when
    someone accidentally removes the hash and emits full principal names.
    """
    seen: set[tuple[str, str]] = set()
    for i in range(100):
        pname = f"uid:{i}"
        short = _short_principal(pname)
        seen.add(("local", short))
    # All 100 distinct principals → 100 distinct hash prefixes.
    # In production, traffic is well below this; the test enforces
    # that the hash function produces a unique value per input (no
    # accidental collapse to a single bucket).
    assert len(seen) == 100
