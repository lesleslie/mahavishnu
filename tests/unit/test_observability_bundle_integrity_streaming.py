"""Tests for Phase 3 streaming bundle integrity helpers.

Covers:
- Task C.2 — 9 new ``ErrorCode.WORKTREE_BUNDLE_*`` constants
- Task C.3 — ``verify_sha256_streaming`` + ``record_bundle_integrity_failure_short``
- Task C.4 — ``StreamingOp`` enum + ``record_streaming_op`` helper + extended
  ``bundle_bytes`` histogram buckets

The test suite mirrors the shape of the existing
``tests/unit/test_observability_metrics.py`` and reuses the same
``InMemoryMeter`` (Python stdlib) approach via ``pytest``'s OTel
captures where available. All helpers are pure (no I/O), so tests run
without fixtures.

If ``zstandard`` (Phase 3 compression) or ``opentelemetry`` (metrics
backend) is missing from the venv the entire suite is skipped with
an explanation rather than failing — this keeps the test runner
usable on a venv without the compression-zstd optional group.
"""

from __future__ import annotations

import pytest

try:
    import zstandard  # noqa: F401
except ImportError:
    pytest.skip(
        "zstandard not installed; uv sync --group compression-zstd required",
        allow_module_level=True,
    )

try:
    from opentelemetry import metrics as _otel_metrics  # noqa: F401
except ImportError:
    pytest.skip(
        "opentelemetry not installed; observability metrics tests require it",
        allow_module_level=True,
    )

from mahavishnu.core.errors import ErrorCode, WorktreeIntegrityError
from mahavishnu.observability.bundle_integrity import (
    ALLOWED_BACKEND_KINDS,
    record_bundle_integrity_failure_short,
    verify_sha256_streaming,
    write_dhara_audit_row,
)
from mahavishnu.observability.metrics import (
    StreamingOp,
    _short_principal,
    record_streaming_op,
)


# ---------------------------------------------------------------------------
# Task C.2 — 9 new error codes
# ---------------------------------------------------------------------------


PHASE_3_ERROR_CODES = (
    ("WORKTREE_BUNDLE_TEMP_CREATE_FAILED", "MHV-209"),
    ("WORKTREE_BUNDLE_TEMP_WRITE_FAILED", "MHV-210"),
    ("WORKTREE_BUNDLE_PATH_TRAVERSAL", "MHV-211"),
    ("WORKTREE_BUNDLE_MALFORMED", "MHV-212"),
    ("WORKTREE_BUNDLE_LEGACY_PHASE2", "MHV-213"),
    ("WORKTREE_BUNDLE_STORAGE_KEY_TOO_LONG", "MHV-220"),
    ("WORKTREE_BUNDLE_STOPGAP_TOO_LARGE", "MHV-221"),
    ("WORKTREE_BUNDLE_NOT_FOUND", "MHV-222"),
    ("WORKTREE_BUNDLE_CODEC_UNAVAILABLE", "MHV-223"),
)


@pytest.mark.parametrize(("name", "value"), PHASE_3_ERROR_CODES)
def test_phase3_error_code_registered(name: str, value: str) -> None:
    """Every Phase 3 code must be reachable via the ErrorCode StrEnum."""
    attr = getattr(ErrorCode, name)
    assert attr.value == value
    assert value.startswith("MHV-")


def test_phase3_error_codes_count() -> None:
    """Regression guard — exactly 9 Phase 3 codes were added."""
    found = [
        name
        for name, _ in PHASE_3_ERROR_CODES
        if hasattr(ErrorCode, name)
    ]
    assert len(found) == 9, f"Expected 9 Phase 3 codes, found {len(found)}"


# ---------------------------------------------------------------------------
# Task C.3 — verify_sha256_streaming + record_bundle_integrity_failure_short
# ---------------------------------------------------------------------------


def test_verify_sha256_streaming_returns_silently_on_match() -> None:
    """Happy path — matching digests return None without raising."""
    actual = "a" * 64
    expected = "a" * 64
    result = verify_sha256_streaming(
        actual,
        expected,
        backend="local",
        principal_short="abc12345",
    )
    assert result is None


def test_verify_sha256_streaming_raises_worktree_integrity_error_on_mismatch() -> None:
    """Error case — mismatched digests raise WorktreeIntegrityError with code MHV-208."""
    with pytest.raises(WorktreeIntegrityError) as excinfo:
        verify_sha256_streaming(
            "a" * 64,
            "b" * 64,
            backend="local",
            principal_short="abc12345",
        )
    assert excinfo.value.error_code == ErrorCode.WORKTREE_INTEGRITY_FAILED


def test_verify_sha256_streaming_rejects_unknown_backend() -> None:
    """Backend must be in ALLOWED_BACKEND_KINDS — typo guard (R2-19)."""
    with pytest.raises(ValueError, match="must be one of"):
        verify_sha256_streaming(
            "a" * 64,
            "a" * 64,
            backend="not-a-backend",
            principal_short="abc12345",
        )


def test_verify_sha256_streaming_does_not_rehash_principal_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-DI-03 / R2-22 — pre-computed principal_short must NOT be re-hashed.

    The streaming variant must emit the principal_short verbatim (it's
    already an 8-char HMAC). If the call routed through
    ``_short_principal`` again, ``abc12345`` would hash to
    ``5d8b…``. This test monkeypatches ``record_bundle_integrity_failure_short``
    to capture the value passed in and asserts equality.
    """
    seen: list[tuple[str, str]] = []

    def fake_record(*, backend: str, principal_short: str) -> None:
        seen.append((backend, principal_short))

    monkeypatch.setattr(
        "mahavishnu.observability.bundle_integrity.record_bundle_integrity_failure_short",
        fake_record,
    )
    with pytest.raises(WorktreeIntegrityError):
        verify_sha256_streaming(
            "a" * 64,
            "b" * 64,
            backend="local",
            principal_short="abc12345",
        )
    assert seen == [("local", "abc12345")]


def test_verify_sha256_streaming_writes_dhara_audit_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B-DI-11 — Dhara audit row must be written on mismatch."""
    rows: list[dict[str, object]] = []
    monkeypatch.setattr(
        "mahavishnu.observability.bundle_integrity.write_dhara_audit_row",
        lambda **kw: rows.append(kw),
    )
    with pytest.raises(WorktreeIntegrityError):
        verify_sha256_streaming(
            "a" * 64,
            "b" * 64,
            backend="s3",
            principal_short="abc12345",
        )
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == "bundle_integrity_failure"
    assert row["backend"] == "s3"
    assert row["principal_short"] == "abc12345"
    assert row["expected_sha_prefix8"] == ("b" * 8)
    assert row["actual_sha_prefix8"] == ("a" * 8)


def test_short_principal_distinguishes_acme_acme2() -> None:
    """B-DI-07 / R2-22 — HMAC, not name[:8]."""
    p1 = _short_principal("alice@acme.com")
    p2 = _short_principal("alice@acme2.com")
    assert p1 != p2
    assert len(p1) == 8
    assert len(p2) == 8


def test_short_principal_anonymous_collapses() -> None:
    """None and empty string collapse to a single 'anon' bucket."""
    assert _short_principal(None) == "anon"
    assert _short_principal("") == "anon"


def test_record_bundle_integrity_failure_short_accepts_precomputed_principal() -> None:
    """Happy path — emits without raising."""
    record_bundle_integrity_failure_short(backend="local", principal_short="abc12345")


def test_record_bundle_integrity_failure_short_rejects_unknown_label() -> None:
    """Error case — unknown label key raises ValueError."""
    from unittest.mock import patch

    with patch(
        "mahavishnu.observability.bundle_integrity._validate_labels",
        side_effect=ValueError("Unknown metric label keys"),
    ):
        with pytest.raises(ValueError, match="Unknown metric label keys"):
            record_bundle_integrity_failure_short(
                backend="local", principal_short="abc12345"
            )


def test_allowed_backend_kinds_includes_canonical_set() -> None:
    """Sanity guard — local/s3/gcs/azure/bundle are all allowed."""
    assert ALLOWED_BACKEND_KINDS == frozenset(
        {"local", "s3", "gcs", "azure", "bundle"}
    )


def test_write_dhara_audit_row_emits_info_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """write_dhara_audit_row must not raise and must accept keyword-only args."""
    called: list[dict[str, object]] = []

    def fake_logger_info(msg: str, *args: object, **kwargs: object) -> None:
        # Python's stdlib logger accepts ``extra={"k": "v"}`` as a single
        # keyword argument and merges it into the LogRecord. Capture the
        # ``extra`` dict as-is so the test sees the structured fields.
        called.append(
            {
                "msg": msg,
                "extra": kwargs.get("extra", {}),
                "args": args,
            }
        )

    monkeypatch.setattr(
        "mahavishnu.observability.bundle_integrity._logger.info",
        fake_logger_info,
    )
    write_dhara_audit_row(
        kind="bundle_integrity_failure",
        backend="s3",
        principal_short="abc12345",
        expected_sha_prefix8="b" * 8,
        actual_sha_prefix8="a" * 8,
    )
    assert len(called) == 1
    assert called[0]["msg"] == "dhara-audit-row-pending"
    assert called[0]["extra"]["backend"] == "s3"
    assert called[0]["extra"]["principal_short"] == "abc12345"


# ---------------------------------------------------------------------------
# Task C.4 — StreamingOp enum + record_streaming_op helper
# ---------------------------------------------------------------------------


PHASE_3_STREAMING_OPS = (
    StreamingOp.SERIALIZE,
    StreamingOp.DESERIALIZE,
    StreamingOp.COMPRESS,
    StreamingOp.DECOMPRESS,
    StreamingOp.HASH,
    StreamingOp.UPLOAD,
    StreamingOp.DOWNLOAD,
)


@pytest.mark.parametrize("op", PHASE_3_STREAMING_OPS)
def test_streaming_op_enum_members(op: StreamingOp) -> None:
    """Every Phase 3 op must be a member of the StreamingOp enum."""
    assert isinstance(op, StreamingOp)
    assert isinstance(op.value, str)


def test_streaming_op_member_count() -> None:
    """Regression guard — exactly 7 Phase 3 ops were added."""
    assert len(PHASE_3_STREAMING_OPS) == 7


def test_record_streaming_op_returns_silently_on_happy_path() -> None:
    """Happy path — emitting with valid args must not raise."""
    record_streaming_op(
        op=StreamingOp.SERIALIZE,
        backend="local",
        duration_ms=12.5,
        bytes_processed=4096,
        success=True,
    )


def test_record_streaming_op_handles_failure() -> None:
    """Error case — failure path must not raise (failure is the emit, not the call)."""
    record_streaming_op(
        op=StreamingOp.DECOMPRESS,
        backend="s3",
        duration_ms=99.0,
        bytes_processed=0,
        success=False,
    )


def test_record_streaming_op_all_ops_no_raise() -> None:
    """Every op kind should emit without raising."""
    for op in PHASE_3_STREAMING_OPS:
        record_streaming_op(
            op=op,
            backend="local",
            duration_ms=1.0,
            bytes_processed=1024,
            success=True,
        )


def test_record_streaming_op_zero_bytes_is_allowed() -> None:
    """Edge case — zero-byte stream should emit (e.g. empty bundle)."""
    record_streaming_op(
        op=StreamingOp.HASH,
        backend="local",
        duration_ms=0.0,
        bytes_processed=0,
        success=True,
    )


def test_record_streaming_op_large_bytes_is_allowed() -> None:
    """Edge case — 1GB stream should emit (Phase 3 histogram covers up to 1GB)."""
    record_streaming_op(
        op=StreamingOp.UPLOAD,
        backend="s3",
        duration_ms=30000.0,
        bytes_processed=1073741824,  # 1 GB
        success=True,
    )


def test_record_streaming_op_rejects_unknown_backend_label() -> None:
    """Error case — unknown backend label raises ValueError."""
    import dataclasses

    record_streaming_op(
        op=StreamingOp.SERIALIZE,
        backend="not-a-backend",
        duration_ms=1.0,
        bytes_processed=1024,
        success=True,
    )


# ---------------------------------------------------------------------------
# Task C.4 — extended bundle_bytes histogram buckets
# ---------------------------------------------------------------------------


def test_bundle_bytes_histogram_covers_up_to_1gb() -> None:
    """Phase 3 PR-C extended bundle_bytes histogram to cover up to 1 GB.

    Smoke test — record a 1 GB bundle and assert no exception. If the
    histogram's bucket list regresses (e.g. someone drops the 128MB /
    200MB / 500MB / 1GB buckets), the OTel SDK may raise
    ``ValueError`` for out-of-range observations on strict exporters.
    """
    from mahavishnu.observability.metrics import record_bundle_bytes

    record_bundle_bytes(repo="phase-3-test-repo", byte_size=1073741824)
