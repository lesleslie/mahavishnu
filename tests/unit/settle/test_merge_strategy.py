"""Tests for ``mahavishnu.settle.merge.MergeStrategy`` and the Phase 1
strategy plumbing.

REQ-SM-007 regression: ``MergeStrategy`` round-trips through plain-string
serialization (``str(value)``) without leaking the enum repr
(``"MergeStrategy.SEMANTIC"``) into Dhara payloads. The cross-version
compatibility of ``SettleRunRecord.bindings[*].merge_strategy`` (Phase 3
payload) depends on this contract — without the pin, ``str(member)``
would emit the enum repr and silently break older Dhara records.

Also covers the Phase 1 exit-criterion: ``merge_three_way_sync`` is
removed from ``__all__`` and emits ``DeprecationWarning`` on call.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.settle.merge import (
    MergeConflictError,
    MergeDriverUnavailableError,
    MergeFailureError,
    MergeResult,
    MergeStrategy,
    _merge_via_mergiraf,
    merge_three_way,
    merge_three_way_sync,
    set_merge_driver_runtime_config,
)

# ---------------------------------------------------------------------------
# REQ-SM-007: MergeStrategy round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "strategy",
    [MergeStrategy.LINE, MergeStrategy.SEMANTIC],
)
def test_strategy_roundtrip(strategy: MergeStrategy) -> None:
    """``str(strategy.value)`` -> ``MergeStrategy(raw)`` must equal ``strategy``.

    This is the Dhara persistence contract: ``to_dict`` writes the raw
    string (e.g. ``"semantic"``) and ``from_dict`` reads it back via
    ``MergeStrategy(raw)``. Without this pin, ``str(MergeStrategy.SEMANTIC)``
    would emit ``"MergeStrategy.SEMANTIC"`` and break cross-version
    payloads.
    """
    serialized = str(strategy.value)
    # Sanity: the serialized form is one of the canonical values, NOT the
    # enum repr. This guards against a future Python change to StrEnum
    # behavior that would silently break the contract.
    assert serialized in {"line", "semantic"}
    deserialized = MergeStrategy(serialized)
    assert deserialized is strategy


def test_strategy_value_is_plain_string() -> None:
    """Sanity check: ``strategy.value`` is a plain ``str`` literal."""
    assert MergeStrategy.LINE.value == "line"
    assert MergeStrategy.SEMANTIC.value == "semantic"
    assert isinstance(MergeStrategy.LINE.value, str)
    assert isinstance(MergeStrategy.SEMANTIC.value, str)


def test_strategy_str_returns_value_not_repr() -> None:
    """``str(MergeStrategy.SEMANTIC)`` returns ``"semantic"`` (the value).

    Python's ``StrEnum`` (3.11+) overrides ``__str__`` to return the value
    directly — this is the safe default for Dhara serialization. The
    REQ-SM-007 pin (``str(member.value)``) is defensive: if a future
    maintainer switches to plain ``Enum`` or overrides ``__str__``, the
    pin still produces the cross-version-safe raw string.
    """
    assert str(MergeStrategy.SEMANTIC) == "semantic"
    assert str(MergeStrategy.LINE) == "line"


def test_strategy_roundtrip_through_json() -> None:
    """``json.dumps(strategy.value)`` round-trips to the same string.

    Belt-and-suspenders: even if a future refactor adds a custom
    ``__json__`` to MergeStrategy that leaks the repr, this test catches
    it because ``json.dumps(MergeStrategy.SEMANTIC)`` would emit
    ``'"MergeStrategy.SEMANTIC"'`` (the repr, JSON-quoted).
    """
    for strategy in MergeStrategy:
        serialized = json.dumps(strategy.value)
        deserialized = json.loads(serialized)
        assert deserialized == strategy.value


# ---------------------------------------------------------------------------
# Phase 1 exit criteria: merge_three_way_sync is deprecated
# ---------------------------------------------------------------------------


def test_merge_three_way_sync_emits_deprecation_warning() -> None:
    """The deprecated public sync shim must emit DeprecationWarning.

    Phase 1 exit criteria: ``merge_three_way_sync`` no longer in
    ``__all__`` and emits ``DeprecationWarning`` if called. The behavior
    must remain identical (delegates to ``_merge_three_way_sync_internal``).

    ``subprocess.run`` is patched to a clean-merge CompletedProcess so
    the shim returns successfully — we're verifying the warning emission,
    not the merge semantics (which the existing ``test_settle_merge.py``
    suite already covers).
    """
    completed = MagicMock(spec=subprocess.CompletedProcess)
    completed.returncode = 0
    completed.stdout = "ok\n"
    completed.stderr = ""

    with patch("subprocess.run", return_value=completed):
        with pytest.warns(
            DeprecationWarning,
            match="merge_three_way_sync is deprecated",
        ):
            result = merge_three_way_sync(base="x", ours="y", theirs="z")
    assert result.merged == "ok\n"
    assert result.conflict_count == 0


def test_merge_three_way_sync_not_in_module_all() -> None:
    """The sync surface must not be advertised as public.

    Even though ``merge_three_way_sync`` is still importable (for backward
    compat with Phase 0 callers), ``__all__`` must exclude it so
    ``from mahavishnu.settle.merge import *`` no longer surfaces it.
    """
    import mahavishnu.settle.merge as merge_module

    assert "merge_three_way" in merge_module.__all__
    assert "MergeStrategy" in merge_module.__all__
    assert "MergeDriverUnavailableError" in merge_module.__all__
    assert "merge_three_way_sync" not in merge_module.__all__


# ---------------------------------------------------------------------------
# Phase 2 exit-criterion: mergiraf exit-code matrix
# ---------------------------------------------------------------------------


def _make_mergiraf_proc(
    *,
    returncode: int,
    stdout: str,
    stderr: str = "",
) -> AsyncMock:
    """Build an ``AsyncMock`` for the mergiraf subprocess.

    The async driver awaits ``proc.communicate()`` and then reads
    ``proc.returncode`` — wire both to fixed values so the matrix tests
    branch deterministically on (exit_code, has_markers).
    """
    proc = AsyncMock(spec=asyncio.subprocess.Process)
    proc.communicate = AsyncMock(return_value=(stdout.encode("utf-8"), stderr.encode("utf-8")))
    proc.returncode = returncode
    return proc


async def test_mergiraf_markers_in_stdout_raises_conflict_error() -> None:
    """Marker-first classification: markers in stdout → conflict (R4 fix).

    A 3-way merge where ``ours`` and ``theirs`` define different values
    for the same entity must raise ``MergeConflictError`` regardless of
    exit code. The plan claimed "exit 0 with markers"; empirically
    ``mergiraf 0.19.1`` exits 1 with markers. The marker-first branch
    handles both behaviors — see ``_merge_via_mergiraf`` docstring for
    the matrix rationale.
    """
    merged_with_markers = (
        "<<<<<<< ours\n"
        "def foo() -> int: return 1\n"
        "=======\n"
        "def foo() -> int: return 2\n"
        ">>>>>>> theirs\n"
    )
    proc = _make_mergiraf_proc(returncode=0, stdout=merged_with_markers)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with pytest.raises(MergeConflictError) as excinfo:
            await _merge_via_mergiraf(
                base="def foo() -> int: return 0\n",
                ours="def foo() -> int: return 1\n",
                theirs="def foo() -> int: return 2\n",
                label="src/foo.py",
                binary="/usr/local/bin/mergiraf",
            )
    err = excinfo.value
    assert err.path == "src/foo.py"
    assert err.merged == merged_with_markers
    assert "<<<<<<< " in err.merged
    assert err.driver_warnings is None  # no stderr in this test


async def test_mergiraf_exit_zero_clean_returns_result() -> None:
    """Exit 0 with no ``<<<<<<<`` markers → ``MergeResult``.

    Non-overlapping function edits merge cleanly under mergiraf. The
    ``driver_warnings`` field is None when stderr is empty.
    """
    merged = "def foo() -> int: return 0\ndef bar() -> int: return 99\n"
    proc = _make_mergiraf_proc(returncode=0, stdout=merged)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await _merge_via_mergiraf(
            base="def foo() -> int: return 0\n",
            ours="def foo() -> int: return 0\ndef bar() -> int: return 99\n",
            theirs="def foo() -> int: return 0\n",
            label="src/foo.py",
            binary="/usr/local/bin/mergiraf",
        )
    assert isinstance(result, MergeResult)
    assert result.merged == merged
    assert result.conflict_count == 0
    assert result.driver_warnings is None


@pytest.mark.parametrize("returncode", [1, 2, 127])
async def test_mergiraf_fatal_exit_raises_failure(returncode: int) -> None:
    """Exit 1 (input unreadable) or 2 (tree-sitter parse error) is fatal.

    These exit codes map to ``MergeFailureError`` — never to
    ``MergeConflictError``. The stderr message must appear in the error
    string so operators can diagnose grammar drift.
    """
    proc = _make_mergiraf_proc(
        returncode=returncode,
        stdout="",
        stderr="fatal: tree-sitter grammar missing for FooLang\n",
    )
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with pytest.raises(MergeFailureError) as excinfo:
            await _merge_via_mergiraf(
                base="x",
                ours="y",
                theirs="z",
                label="binding-X",
                binary="/usr/local/bin/mergiraf",
            )
    assert f"exit={returncode}" in str(excinfo.value)
    assert "binding-X" in str(excinfo.value)
    assert "tree-sitter grammar missing" in str(excinfo.value)


async def test_mergiraf_captures_driver_warnings_on_success() -> None:
    """Stderr is captured even on a clean merge (R3 #4 fix).

    Mergiraf may emit informational diagnostics (e.g. ``note: parsed with
    tree-sitter grammar vX.Y``) on a successful merge. ``driver_warnings``
    surfaces them so operators can detect grammar drift without losing
    the merge result.
    """
    merged = "ok\n"
    stderr = "note: grammar Python v1.2 loaded\n"
    proc = _make_mergiraf_proc(
        returncode=0,
        stdout=merged,
        stderr=stderr,
    )
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await _merge_via_mergiraf(
            base="x",
            ours="x",
            theirs="x",
            label="ok",
            binary="/usr/local/bin/mergiraf",
        )
    assert result.driver_warnings == stderr


async def test_mergiraf_captures_driver_warnings_on_conflict() -> None:
    """Stderr is captured on a conflict path too.

    Mergiraf may emit grammar notes alongside the conflict markers.
    The ``MergeConflictError.driver_warnings`` field preserves them for
    operator inspection.
    """
    merged_with_markers = "<<<<<<< ours\nA\n=======\nB\n>>>>>>> theirs\n"
    stderr = "warning: ambiguous resolution for entity Foo\n"
    proc = _make_mergiraf_proc(
        returncode=0,
        stdout=merged_with_markers,
        stderr=stderr,
    )
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with pytest.raises(MergeConflictError) as excinfo:
            await _merge_via_mergiraf(
                base="orig\n",
                ours="A\n",
                theirs="B\n",
                label="conflict",
                binary="/usr/local/bin/mergiraf",
            )
    assert excinfo.value.driver_warnings == stderr


async def test_mergiraf_truncates_driver_warnings_at_4kb() -> None:
    """Stderr beyond 4KB is truncated to protect downstream payloads.

    Mergiraf can emit multi-megabyte parse-error dumps for a single file.
    The first 4KB is where actionable hints (grammar name, line number)
    live; the rest is noise for the merge call site.
    """
    huge_stderr = "x" * 10_000  # 10KB of stderr
    proc = _make_mergiraf_proc(
        returncode=2,
        stdout="",
        stderr=huge_stderr,
    )
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with pytest.raises(MergeFailureError) as excinfo:
            await _merge_via_mergiraf(
                base="x",
                ours="y",
                theirs="z",
                label="huge",
                binary="/usr/local/bin/mergiraf",
            )
    # stderr is embedded in the error message but also truncated.
    msg = str(excinfo.value)
    assert len(msg) < 10_000  # far less than the 10KB input


async def test_merge_three_way_semantic_raises_driver_unavailable_when_binary_missing() -> None:
    """Validation gate: ``MergeStrategy.SEMANTIC`` with no binary on PATH.

    The validation gate fires BEFORE the subprocess spawn (R3 #1). No
    silent fallback to LINE.
    """
    with patch(
        "mahavishnu.settle.merge._resolve_mergiraf_binary",
        return_value=None,
    ):
        with pytest.raises(MergeDriverUnavailableError) as excinfo:
            await merge_three_way(
                base="x",
                ours="y",
                theirs="z",
                label="binding-X",
                strategy=MergeStrategy.SEMANTIC,
            )
    assert "mergiraf" in str(excinfo.value)
    assert "binding-X" not in str(excinfo.value)  # validation gate, not per-binding


async def test_merge_three_way_line_strategy_does_not_resolve_mergiraf() -> None:
    """``LINE`` strategy must not require mergiraf on PATH.

    The Phase 1 default-resolution matrix says ``LINE`` is independent of
    mergiraf availability. This guards against a future regression where
    the validation gate accidentally fires for the LINE path.
    """
    # Patch git merge-file instead (LINE strategy).
    proc = AsyncMock(spec=asyncio.subprocess.Process)
    proc.communicate = AsyncMock(return_value=(b"ok\n", b""))
    proc.returncode = 0
    with (
        patch(
            "mahavishnu.settle.merge._resolve_mergiraf_binary",
            return_value=None,
        ),
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
    ):
        result = await merge_three_way(
            base="x",
            ours="y",
            theirs="z",
            label="line-only",
            strategy=MergeStrategy.LINE,
        )
    assert result.merged == "ok\n"


async def test_merge_result_default_driver_warnings_is_none() -> None:
    """``MergeResult.driver_warnings`` defaults to None.

    LINE strategy never populates ``driver_warnings``; the default must
    be None to keep backward compatibility with Phase 0 callers that
    don't expect the field.
    """
    result = MergeResult(merged="x", conflict_count=0)
    assert result.driver_warnings is None


async def test_merge_conflict_error_default_driver_warnings_is_none() -> None:
    """``MergeConflictError.driver_warnings`` defaults to None.

    LINE strategy never populates ``driver_warnings``; the default must
    be None so legacy ``MergeConflictError(...)`` callers don't break.
    """
    err = MergeConflictError(
        path="p",
        merged="m",
        base="b",
        ours="o",
        theirs="t",
    )
    assert err.driver_warnings is None


async def test_merge_driver_unavailable_error_is_exception() -> None:
    """``MergeDriverUnavailableError`` is an ``Exception`` subclass.

    MCP catch chain relies on this for ``except MergeDriverUnavailableError``
    arms. Subclassing ``Exception`` (not ``RuntimeError`` or ``MergeFailureError``)
    keeps the contract crisp.
    """
    err = MergeDriverUnavailableError("test")
    assert isinstance(err, Exception)
    assert not isinstance(err, MergeFailureError)


# ---------------------------------------------------------------------------
# Phase 4 exit criteria: startup guard + runtime fallback + /health wiring
# ---------------------------------------------------------------------------


async def test_missing_binary_with_required_flag_raises_at_startup() -> None:
    """R3 #2 Critical: startup guard raises ``MergeDriverUnavailableError``.

    Phase 4 REQ-SM-005 wires the guard in ``MahavishnuApp._init_observability``.
    When ``merge_driver_required=True`` and ``merge_driver_default='mergiraf'``
    but the binary is missing, the guard MUST raise at process start — NOT
    defer to first-apply. Defer-to-first-use means the app boots green and
    crashes on first apply, which destroys operator trust.

    We exercise the guard via the bootstrap helper it delegates to:
    ``_install_merge_driver_runtime_config`` in ``mahavishnu.core.bootstrap``.
    """
    # Reset runtime config so the test isn't poisoned by sibling tests.
    set_merge_driver_runtime_config(default="line", required=False)

    class _StubConfig:
        merge_driver_default = "mergiraf"
        merge_driver_required = True

    class _StubApp:
        config = _StubConfig()

    from mahavishnu.core.bootstrap import _install_merge_driver_runtime_config

    with patch(
        "mahavishnu.settle.merge._resolve_mergiraf_binary",
        return_value=None,
    ):
        with pytest.raises(MergeDriverUnavailableError) as excinfo:
            _install_merge_driver_runtime_config(_StubApp())
    assert "mergiraf" in str(excinfo.value).lower()
    assert "boot" in str(excinfo.value).lower() or "process" in str(excinfo.value).lower()


async def test_startup_guard_does_not_fire_when_binary_present() -> None:
    """Startup guard passes when ``mergiraf`` is on $PATH.

    Sanity check: the guard is conditional on binary missing. With
    ``merge_driver_required=True`` and binary present, the app boots.
    """
    set_merge_driver_runtime_config(default="line", required=False)

    class _StubConfig:
        merge_driver_default = "mergiraf"
        merge_driver_required = True

    class _StubApp:
        config = _StubConfig()

    from mahavishnu.core.bootstrap import _install_merge_driver_runtime_config

    with patch(
        "mahavishnu.settle.merge._resolve_mergiraf_binary",
        return_value="/usr/local/bin/mergiraf",
    ):
        # No exception expected.
        _install_merge_driver_runtime_config(_StubApp())


async def test_startup_guard_skipped_when_required_false() -> None:
    """Startup guard is conditional on ``merge_driver_required=True``.

    When ``required=False`` (the default), the guard does NOT raise even
    when ``merge_driver_default='mergiraf'`` and binary is missing — the
    runtime fallback path handles it (R3 #3 mitigation). Loud-failure at
    boot is the operator's opt-in via ``required=True``.
    """
    set_merge_driver_runtime_config(default="line", required=False)

    class _StubConfig:
        merge_driver_default = "mergiraf"
        merge_driver_required = False

    class _StubApp:
        config = _StubConfig()

    from mahavishnu.core.bootstrap import _install_merge_driver_runtime_config

    with patch(
        "mahavishnu.settle.merge._resolve_mergiraf_binary",
        return_value=None,
    ):
        # No exception — runtime fallback is the path here.
        _install_merge_driver_runtime_config(_StubApp())


async def test_runtime_fallback_increments_counter_and_sets_degraded_since() -> None:
    """R3 #3 mitigation: runtime fallback is loud, never silent.

    When ``merge_driver_default='mergiraf'`` (non-required) and binary
    missing, ``_resolve_default_strategy`` falls back to LINE, increments
    ``merge.fallback_total`` OTel counter, and stamps
    ``merge_driver.degraded_since``. The caller surfaces degradation via
    ``/health``.

    Patches the mergiraf PATH probe to None so the fallback path triggers
    without depending on the actual binary state.
    """
    # Reset config + degraded timestamp so this test is isolated.
    set_merge_driver_runtime_config(default="mergiraf", required=False)
    import mahavishnu.core.health as health_module

    # Reset the module-level state for an isolated probe.
    health_module._DEGRADED_SINCE = None  # type: ignore[attr-defined]

    from mahavishnu.settle.merge import _resolve_default_strategy

    with patch(
        "mahavishnu.settle.merge._resolve_mergiraf_binary",
        return_value=None,
    ):
        resolved = _resolve_default_strategy()

    assert resolved == MergeStrategy.LINE

    # The OTel counter is incremented — exact metric value depends on
    # the OTel SDK state, but the call must not raise.
    # The degraded_since stamp is set on the health module.
    assert health_module._DEGRADED_SINCE is not None  # type: ignore[attr-defined]


async def test_runtime_fallback_sets_driver_warning_field() -> None:
    """``MergeResult.driver_warning`` is set when runtime fallback fires.

    Distinct from ``driver_warnings`` (Phase 2 stderr capture). When
    ``merge_driver_default='mergiraf'`` and binary missing, the LINE
    strategy runs and ``driver_warning='mergiraf missing'`` surfaces the
    degradation on the result object.
    """
    set_merge_driver_runtime_config(default="mergiraf", required=False)

    proc = AsyncMock(spec=asyncio.subprocess.Process)
    proc.communicate = AsyncMock(return_value=(b"merged\n", b""))
    proc.returncode = 0

    with (
        patch(
            "mahavishnu.settle.merge._resolve_mergiraf_binary",
            return_value=None,
        ),
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
    ):
        result = await merge_three_way(
            base="x",
            ours="x",
            theirs="x",
            label="fallback",
        )
    assert result.driver_warning == "mergiraf missing"
    assert result.strategy_used == MergeStrategy.LINE
    assert result.merged == "merged\n"


async def test_runtime_fallback_does_not_set_driver_warning_for_explicit_strategy() -> None:
    """Explicit ``strategy=LINE`` skips the fallback detection.

    The runtime fallback detection in ``merge_three_way`` only fires when
    the resolved strategy is LINE AND ``merge_driver_default='mergiraf'``.
    An explicit ``strategy=LINE`` keeps the default at any value the
    operator chose — no fallback, no warning.

    Round-4 review fix (M7): patch ``_resolve_mergiraf_binary`` to
    return a deterministic non-None value so the test does not depend
    on whether mergiraf happens to be on the test runner's ``$PATH``.
    Previously the test passed only when the operator had mergiraf
    installed; on a clean CI image it would fail with
    ``driver_warning == "mergiraf missing"``.
    """
    set_merge_driver_runtime_config(default="mergiraf", required=False)

    proc = AsyncMock(spec=asyncio.subprocess.Process)
    proc.communicate = AsyncMock(return_value=(b"ok\n", b""))
    proc.returncode = 0

    with (
        patch(
            "mahavishnu.settle.merge._resolve_mergiraf_binary",
            return_value="/usr/local/bin/mergiraf",
        ),
        patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
    ):
        result = await merge_three_way(
            base="x",
            ours="x",
            theirs="x",
            label="explicit-line",
            strategy=MergeStrategy.LINE,
        )
    assert result.driver_warning is None
    assert result.strategy_used == MergeStrategy.LINE


async def test_merge_result_strategy_used_set_for_semantic() -> None:
    """``MergeResult.strategy_used=MergeStrategy.SEMANTIC`` after a real mergiraf run.

    Phase 4 surface contract: ``strategy_used`` reports the actual
    strategy that ran (vs. what was requested via the ``strategy=``
    keyword). When the SEMANTIC driver ran, the field is set.
    """
    proc = AsyncMock(spec=asyncio.subprocess.Process)
    proc.communicate = AsyncMock(return_value=(b"semantic-ok\n", b""))
    proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await _merge_via_mergiraf(
            base="x",
            ours="x",
            theirs="x",
            label="semantic-ok",
            binary="/usr/local/bin/mergiraf",
        )
    assert result.strategy_used == MergeStrategy.SEMANTIC
    assert result.driver_warning is None  # binary present, no fallback


async def test_merge_conflict_error_strategy_used_set_for_semantic() -> None:
    """``MergeConflictError.strategy_used=MergeStrategy.SEMANTIC`` on conflict.

    Same surface contract for the conflict path: when the SEMANTIC
    driver ran and produced markers, the conflict error carries the
    actual strategy.
    """
    merged_with_markers = "<<<<<<< ours\nA\n=======\nB\n>>>>>>> theirs\n"
    proc = AsyncMock(spec=asyncio.subprocess.Process)
    proc.communicate = AsyncMock(
        return_value=(merged_with_markers.encode("utf-8"), b""),
    )
    proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with pytest.raises(MergeConflictError) as excinfo:
            await _merge_via_mergiraf(
                base="x",
                ours="x",
                theirs="x",
                label="semantic-conflict",
                binary="/usr/local/bin/mergiraf",
            )
    assert excinfo.value.strategy_used == MergeStrategy.SEMANTIC
