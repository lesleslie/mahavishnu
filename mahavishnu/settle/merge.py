"""3-way merge helper — shells out to ``git merge-file`` or ``mergiraf``.

We deliberately do NOT implement our own merge algorithm. The user-facing
contract is "merge conflicts must return a structured error"; the
machine-facing contract is "git's existing 3-way merge is authoritative
for content conflict detection." ``git merge-file`` does both — its
exit code signals clean merge (0), conflict (1), or trunk (>=2), and
its output carries the conflict markers we surface to the caller.

The Phase 2 SEMANTIC strategy delegates to ``mergiraf merge``. Mergiraf
emits ``<<<<<<<`` conflict markers in stdout when it can't resolve an
edit; empirically ``mergiraf 0.19.1`` exits 1 in that case (the plan
claimed exit 0 — see ``_merge_via_mergiraf`` docstring for the marker-
first classification rationale that handles both shapes). Conflict
detection therefore scans stdout for markers regardless of exit code.
Exit codes 1 (input unreadable) and 2 (tree-sitter parse error) are
fatal when no markers are present; markers + any exit code is a
recoverable conflict.

This module is the ONLY place that shells out to git or mergiraf. The
MCP tool layer in :mod:`mahavishnu.mcp.tools.worker_contract_tools`
consumes this helper as ``merge.merge_three_way(base, ours, theirs)``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
import logging
from pathlib import Path
import shutil
import tempfile
import time
from typing import TYPE_CHECKING
import warnings

if TYPE_CHECKING:
    from opentelemetry.metrics import Counter as _Counter
    from opentelemetry.trace import Tracer as _Tracer

try:
    from opentelemetry import metrics as _otel_metrics
    from opentelemetry import trace as _otel_trace

    OTEL_AVAILABLE = True
    # Per-module Tracer instance. Lazy via ``trace.get_tracer(__name__)``
    # — TracerProvider must be initialized by the app before any span is
    # emitted, but ``get_tracer`` returns a no-op Tracer until then.
    _tracer: _Tracer = _otel_trace.get_tracer(__name__)  # type: ignore[assignment]
    # Per-module Meter for runtime observability counters (Phase 4 REQ).
    # The counter is created lazily — the meter itself returns a no-op
    # until MeterProvider is initialized, but creating the counter at
    # module import lets us cache the handle for hot-path use.
    _merge_meter = _otel_metrics.get_meter(__name__)
    _merge_fallback_counter: _Counter = _merge_meter.create_counter(  # type: ignore[assignment]
        name="merge.fallback_total",
        description="Increments when default-resolution falls back from SEMANTIC to LINE",
        unit="1",
    )
except ImportError:  # pragma: no cover — exercised only when opentelemetry absent
    OTEL_AVAILABLE = False

    class _NoopSpan:
        def __enter__(self) -> _NoopSpan:  # noqa: PYI034 — mock class, no Self import needed
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def set_attribute(self, key: str, value: object) -> None:
            pass

        def record_exception(self, exception: BaseException) -> None:
            pass

    class _NoopTracer:
        def start_as_current_span(
            self,
            name: str,
            attributes: dict[str, object] | None = None,
        ) -> _NoopSpan:
            return _NoopSpan()

    _tracer = _NoopTracer()  # type: ignore[assignment,misc]

    class _NoopCounter:
        def add(self, amount: int, attributes: dict[str, object] | None = None) -> None:
            pass

    _merge_fallback_counter: _Counter = _NoopCounter()  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


__all__ = [
    "MergeConflictError",
    "MergeDriverUnavailableError",
    "MergeFailureError",
    "MergeResult",
    "MergeStrategy",
    "merge_three_way",
    # NOTE: `merge_three_way_sync` is intentionally absent — deprecated in
    # Phase 1; kept importable as a shim for backward compat with Phase 0 callers.
]


class MergeConflictError(Exception):
    """Raised when ``git merge-file`` exits with code 1 (clean conflict),
    OR when ``mergiraf merge`` exits 0 with ``<<<<<<<`` markers in stdout.

    Carries the merged-with-markers content so the caller can inspect
    the conflict regions or stash them for manual resolution.
    """

    def __init__(
        self,
        *,
        path: str,
        merged: str,
        base: str,
        ours: str,
        theirs: str,
        driver_warnings: str | None = None,
        strategy_used: MergeStrategy | None = None,
        driver_warning: str | None = None,
    ) -> None:
        super().__init__(f"3-way merge conflict for {path!r}")
        self.path = path
        self.merged = merged
        self.base = base
        self.ours = ours
        self.theirs = theirs
        # Captured stderr from the merge driver, truncated to 4KB. None
        # for the LINE strategy (no driver stderr). Populated for SEMANTIC
        # even on conflict — mergiraf may emit warnings alongside markers.
        self.driver_warnings = driver_warnings
        # Phase 4: actual strategy used (after default-resolution matrix).
        # ``None`` for the LINE strategy (Phase 0/1/2/3 callers ignore it
        # if they don't read the field). ``MergeStrategy.SEMANTIC`` when
        # the mergiraf path actually ran.
        self.strategy_used = strategy_used
        # Phase 4: short operator-facing warning for fallback cases (e.g.
        # ``"mergiraf missing"`` when default-resolution fell back to LINE).
        # Distinct from ``driver_warnings`` (Phase 2 stderr capture) to
        # avoid overloading semantics.
        self.driver_warning = driver_warning


class MergeFailureError(Exception):
    """Raised when ``git merge-file`` exits with code >= 2 (trunk / fatal),
    OR when ``mergiraf merge`` exits 1 (input unreadable) or 2 (tree-sitter
    parse error)."""


class MergeDriverUnavailableError(Exception):
    """Raised when ``mergiraf`` is required (or default-resolved) but the
    binary is not on ``$PATH``.

    Loud-failure semantics: never silently fall back to LINE. The MCP
    consumer at ``mahavishnu/mcp/tools/worker_contract_tools.py`` catches
    this and surfaces ``ErrorCode.MERGE_DRIVER_UNAVAILABLE`` to the caller
    (REQ-SM-003, R3 #1).
    """


@dataclass(frozen=True)
class MergeResult:
    """The successful outcome of a 3-way merge."""

    merged: str
    conflict_count: int
    # Captured stderr from the merge driver, truncated to 4KB. None for
    # the LINE strategy. For SEMANTIC, populated even on success — mergiraf
    # emits informational diagnostics (e.g. ``note: parsed with tree-sitter
    # grammar vX.Y``) that operators may want to surface.
    driver_warnings: str | None = None
    # Phase 4: actual strategy used (after default-resolution matrix).
    # ``None`` for LINE (Phase 0/1/2/3 callers can ignore it).
    # ``MergeStrategy.SEMANTIC`` when mergiraf actually ran.
    strategy_used: MergeStrategy | None = None
    # Phase 4: short operator-facing warning for fallback cases (e.g.
    # ``"mergiraf missing"`` when default-resolution fell back to LINE).
    # Distinct from ``driver_warnings`` (Phase 2 stderr capture) — the
    # singular/plural naming is intentional.
    driver_warning: str | None = None


class MergeStrategy(StrEnum):
    """Pluggable 3-way merge strategy.

    * ``LINE`` — line-level ``git merge-file`` (Phase 0 default; always
      available when ``git`` is on ``$PATH``).
    * ``SEMANTIC`` — entity-aware ``mergiraf merge`` (Phase 2 driver;
      requires the ``mergiraf`` binary on ``$PATH``).

    REQ-SM-007 serialization contract: Dhara payloads persist
    ``str(self.value)`` (i.e. ``"line"`` or ``"semantic"``), NOT
    ``str(self)`` (which yields ``"MergeStrategy.SEMANTIC"`` and breaks
    cross-version payloads). The regression test in
    ``tests/unit/settle/test_merge_strategy.py::test_strategy_roundtrip``
    pins this contract.
    """

    LINE = "line"
    SEMANTIC = "semantic"


# Lazy PATH probe — populated on first ``merge_three_way`` invocation, not
# at module import. Eager probe would block module load when ``$PATH`` is
# slow or ``shutil.which`` is expensive; lazy keeps import deterministic.
# The Phase 4 startup guard in ``MahavishnuApp._init_observability``
# re-probes for the required-flag path; this cache is the runtime path.
_MERGIRAF_BIN: str | None = None


# Phase 4: Oneiric settings snapshot installed by the bootstrap. Mutable
# module-level state so ``merge_three_way`` doesn't need a parameter for
# every config knob — the bootstrap calls
# :func:`set_merge_driver_runtime_config` once during
# ``MahavishnuApp._init_observability`` and the default-resolution
# matrix reads from here on every call.
_MERGE_DRIVER_RUNTIME_CONFIG: dict[str, object] = {
    "default": "line",
    "required": False,
}


def set_merge_driver_runtime_config(*, default: str, required: bool) -> None:
    """Install the Oneiric ``merge_driver_*`` settings for runtime use.

    Called by ``MahavishnuApp._init_observability`` during app bootstrap.
    The default-resolution matrix in :func:`_resolve_default_strategy`
    reads these values on every call. Process-lifetime state — changing
    it at runtime requires a process restart (the startup guard runs
    once per process; tmux panes are out of scope per R4 #D).
    """
    _MERGE_DRIVER_RUNTIME_CONFIG["default"] = default
    _MERGE_DRIVER_RUNTIME_CONFIG["required"] = required


def _resolve_mergiraf_binary() -> str | None:
    """Return the ``mergiraf`` binary path, or ``None`` if not on ``$PATH``.

    Caches the result on first call. The cache is process-lifetime; if a
    fresh probe is required, ``scripts/check_merge_driver.py`` is the
    operator-facing alternative (Phase 4 REQ-SM-008).
    """
    global _MERGIRAF_BIN
    if _MERGIRAF_BIN is None:
        _MERGIRAF_BIN = shutil.which("mergiraf")
    return _MERGIRAF_BIN


def _resolve_default_strategy() -> MergeStrategy:
    """Pick the default strategy at first call.

    Resolution matrix (Phase 4 REQ-SM-005):

    1. ``merge_driver_default == "mergiraf"`` and binary present →
       :class:`MergeStrategy.SEMANTIC`.
    2. ``merge_driver_default == "mergiraf"`` and binary missing →
       **Runtime fallback**: log ``merge.semantic.unavailable`` WARNING,
       increment ``merge.fallback_total`` OTel counter, return
       :class:`MergeStrategy.LINE`. The fallback is **NOT** silent —
       the OTel counter and the ``MergeResult.driver_warning`` field
       surface the degradation.
    3. ``merge_driver_default == "line"`` → :class:`MergeStrategy.LINE`
       (Phase 0/1/2/3 behavior). The legacy PATH-probe fallback (SEMANTIC
       when ``mergiraf`` is on $PATH even though default is "line") is
       kept for backward compatibility with operators who set
       ``merge_driver_default="line"`` but install ``mergiraf`` — the
       follow-up default-flip plan re-evaluates this.
    """
    cfg_default = _MERGE_DRIVER_RUNTIME_CONFIG.get("default", "line")
    binary = _resolve_mergiraf_binary()
    if cfg_default == "mergiraf":
        if binary is not None:
            return MergeStrategy.SEMANTIC
        # Runtime fallback (R3 #3 mitigation: never silent).
        logger.warning(
            "merge.semantic.unavailable: merge_driver_default='mergiraf' "
            "but binary missing on $PATH. Falling back to LINE strategy. "
            "Install mergiraf (brew install mergiraf) or set "
            "merge_driver_default='line' to silence this warning. "
            "/health merge_driver.degraded_since will be set."
        )
        # Round-4 review fix (C4): wrap the OTel counter increment AND
        # the health-module timestamp stamp in a single try/except so
        # the runtime fallback path never crashes the merge call. The
        # prior code only protected the ``mark_merge_driver_fallback``
        # call against ImportError; if the OTel counter raised (SDK in
        # a bad state, attribute error on the noop fallback, etc.),
        # the function would propagate and the user's merge request
        # would crash mid-flight. State divergence (counter ticks without
        # stamp, or stamp without counter) is logged and tolerated —
        # observability is best-effort, the fallback decision is what
        # matters for the user's request.
        try:
            _merge_fallback_counter.add(1, {"reason": "mergiraf_missing"})
            # Stamp the ``merge_driver.degraded_since`` timestamp on the
            # ``/health`` aggregate. Lazy import — ``core.health`` is in the
            # boot path; pulling it eagerly would invert the dependency
            # direction (settle is a low-level module; health is higher).
            from mahavishnu.core.health import mark_merge_driver_fallback

            mark_merge_driver_fallback()
        except ImportError:  # pragma: no cover — core.health unavailable
            pass
        except Exception as exc:  # noqa: BLE001 — observability must never crash merge
            logger.warning(
                "merge.semantic.fallback_observability_error: "
                "type=%s message=%s — fallback decision stands, "
                "/health signal may be partial.",
                type(exc).__name__,
                exc,
            )
        return MergeStrategy.LINE
    # cfg_default == "line" (or unknown — defensive)
    if binary is not None:
        return MergeStrategy.SEMANTIC
    return MergeStrategy.LINE


async def _merge_via_mergiraf(
    *,
    base: str,
    ours: str,
    theirs: str,
    label: str,
    binary: str,
    driver_warning: str | None = None,
) -> MergeResult:
    """Mergiraf shell-out driver.

    Invokes ``mergiraf merge`` with the three input files written to a
    scratch tempdir. Classifies the result via "scan stdout for
    ``<<<<<<<`` markers first, then look at exit code":

    * Conflict markers in stdout → :class:`MergeConflictError`
      (recoverable; the worker can request manual resolution). This is
      the R4 reviewer-blind-spot fix: real semantic conflicts emit
      markers in stdout regardless of the exact exit code. The plan's
      R4 finding said "exit 0 may have markers"; empirically
      ``mergiraf 0.19.1`` actually exits 1 with markers. The marker-first
      branch handles both behaviors.
    * No markers + exit 0 → :class:`MergeResult`
    * No markers + exit 1 (per the original plan: input unreadable) OR
      exit 2 (tree-sitter parse error) OR any other exit → :class:`MergeFailureError`

    The validation gate for ``binary is None`` lives in
    :func:`merge_three_way`'s strategy branch — this helper assumes the
    caller has already resolved a non-null binary path.

    Captures stderr unconditionally (truncated to 4KB) and stores it on
    the result payloads as ``driver_warnings``. Operators may want to
    surface mergiraf's tree-sitter grammar notes even on a clean merge.

    ``driver_warning`` (Phase 4) is forwarded to result payloads when the
    caller detected a runtime-fallback condition. The SEMANTIC strategy
    never produces a ``driver_warning`` (binary was present) — the
    field stays ``None``.

    Round-4 review fix (M5): catches ``OSError`` /
    ``FileNotFoundError`` from ``create_subprocess_exec`` and re-probes
    the binary path. The cached ``_MERGIRAF_BIN`` is invalidated on
    exec failure so a tmux pane with a stale ``$PATH`` recovers on the
    next call instead of crashing every subsequent ``worker_settle``.
    """
    if binary is None:  # pragma: no cover — validation gate upstream
        raise MergeDriverUnavailableError(
            "mergiraf binary is None; the validation gate in merge_three_way "
            "should have raised MergeDriverUnavailableError before this call."
        )

    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="settle-mergiraf-") as tmp_str:
        tmp = Path(tmp_str)
        base_path = tmp / "base"
        ours_path = tmp / "ours"
        theirs_path = tmp / "theirs"
        base_path.write_text(base)
        ours_path.write_text(ours)
        theirs_path.write_text(theirs)

        # M5: invalidate-on-exec-failure. If the cached binary path is
        # stale (tmux pane inherited an old $PATH; operator deleted the
        # binary mid-process), the subprocess spawn raises OSError.
        # Invalidate the cache, re-probe once, and surface a clean
        # MergeDriverUnavailableError if the re-probe also fails.
        try:
            proc = await asyncio.create_subprocess_exec(
                binary,
                "merge",
                str(base_path),
                str(ours_path),
                str(theirs_path),
                "-p",
                label,
                "--allow-parse-errors",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, FileNotFoundError) as exc:
            # Invalidate the cache so the next merge call re-probes.
            global _MERGIRAF_BIN
            _MERGIRAF_BIN = None
            # Re-probe once: the binary may have moved into $PATH after
            # the cache was populated.
            fresh_binary = _resolve_mergiraf_binary()
            if fresh_binary is not None and fresh_binary != binary:
                # Retry once with the fresh path. If it fails again we
                # propagate — no third try, no infinite loop.
                return await _merge_via_mergiraf(
                    base=base,
                    ours=ours,
                    theirs=theirs,
                    label=label,
                    binary=fresh_binary,
                    driver_warning=driver_warning,
                )
            raise MergeDriverUnavailableError(
                f"mergiraf binary at cached path {binary!r} is no longer "
                f"executable ({type(exc).__name__}: {exc}). The PATH cache "
                f"has been invalidated — the next merge call will re-probe. "
                f"Set merge_driver_default='line' or install mergiraf to "
                f"suppress this error."
            ) from exc

        with _tracer.start_as_current_span(
            "merge.semantic.invocations",
            attributes={
                "merge.driver": "mergiraf",
                "merge.label": label,
            },
        ) as span:
            stdout, stderr = await proc.communicate()
            merged_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")
            # Truncate stderr to 4KB — large parse-error dumps can blow
            # up Dhara payloads. The first 4KB is where actionable hints
            # (grammar name, line number) live.
            driver_warnings: str | None = stderr_text[:4096] or None
            exit_code = proc.returncode
            has_conflict_markers = "<<<<<<< " in merged_text
            conflict_count = (
                sum(1 for line in merged_text.splitlines() if line.startswith("<<<<<<< "))
                if has_conflict_markers
                else 0
            )
            duration_ms = (time.monotonic() - start) * 1000.0

            span.set_attribute("merge.exit_code", exit_code or 0)
            span.set_attribute("merge.conflict_count", conflict_count)
            span.set_attribute("merge.duration_ms", duration_ms)
            span.set_attribute("merge.has_driver_warnings", driver_warnings is not None)

            # Marker-first classification (R4 reviewer-blind-spot fix).
            # Real semantic conflicts emit ``<<<<<<<`` markers in stdout
            # regardless of exit code — mergiraf 0.19.1 empirically
            # exits 1, but the plan's R4 finding said exit 0 may also
            # carry markers. The marker check handles both shapes.
            if has_conflict_markers:
                logger.warning(
                    "settle_merge: mergiraf conflict label=%r conflict_count=%d exit=%d",
                    label,
                    conflict_count,
                    exit_code or 0,
                )
                raise MergeConflictError(
                    path=label,
                    merged=merged_text,
                    base=base,
                    ours=ours,
                    theirs=theirs,
                    driver_warnings=driver_warnings,
                    strategy_used=MergeStrategy.SEMANTIC,
                )

            if exit_code == 0:
                return MergeResult(
                    merged=merged_text,
                    conflict_count=0,
                    driver_warnings=driver_warnings,
                    strategy_used=MergeStrategy.SEMANTIC,
                )

            # No markers + non-zero exit: per the plan, exit 1 is "input
            # unreadable" and exit 2 is "tree-sitter parse error". The
            # marker-first check above already routed real conflicts
            # (which can exit 1 in mergiraf 0.19.1) into MergeConflictError,
            # so by the time we reach this branch, exit != 0 with no
            # markers genuinely is a fatal.
            stderr_truncated = stderr_text.strip()[:4096]
            logger.error(
                "settle_merge: mergiraf fatal label=%r exit=%d stderr=%s",
                label,
                exit_code or 0,
                stderr_truncated[:512],
            )
            raise MergeFailureError(
                f"mergiraf failed (exit={exit_code}) for {label!r}: {stderr_truncated}"
            )


async def merge_three_way(
    *,
    base: str,
    ours: str,
    theirs: str,
    label: str = "<anonymous>",
    git_merge_file: str = "git",
    strategy: MergeStrategy | None = None,
) -> MergeResult:
    """Run a 3-way merge over the (base, ours, theirs) triple.

    Strategy resolution:
    - Explicit ``strategy`` argument wins.
    - Otherwise ``SEMANTIC`` when ``mergiraf`` is on ``$PATH``, else ``LINE``.

    Returns a :class:`MergeResult` on clean merge. For ``LINE``, raises
    :class:`MergeConflictError` on exit code 1 and :class:`MergeFailureError`
    on exit code >= 2. For ``SEMANTIC``, raises :class:`MergeConflictError`
    when exit code is 0 but ``<<<<<<<`` markers appear in stdout
    (mergiraf's exit semantics differ from git — see module docstring),
    :class:`MergeFailureError` on exit 1 or 2, and
    :class:`MergeDriverUnavailableError` when ``mergiraf`` is required but
    not on ``$PATH`` (loud-failure; never silently falls back).

    The merge runs in ``asyncio.create_subprocess_exec`` so the event
    loop is not blocked. Files are written to a tempdir and deleted on
    completion.
    """
    effective = strategy if strategy is not None else _resolve_default_strategy()
    # Phase 4: detect runtime-fallback conditions so callers can see
    # degradation via ``MergeResult.driver_warning`` (distinct from
    # Phase 2's stderr capture field). Runtime fallback fires when the
    # operator's Oneiric default is ``"mergiraf"`` but the binary is
    # missing; we silently fall back to LINE per R3 #3 but mark the
    # result so the operator can detect the degradation.
    cfg_default = _MERGE_DRIVER_RUNTIME_CONFIG.get("default", "line")
    binary_available = _resolve_mergiraf_binary() is not None
    runtime_fallback = (
        effective == MergeStrategy.LINE and cfg_default == "mergiraf" and not binary_available
    )
    driver_warning = "mergiraf missing" if runtime_fallback else None

    if effective == MergeStrategy.SEMANTIC:
        binary = _resolve_mergiraf_binary()
        if binary is None:
            # Loud-failure: never silently fall back to LINE. The MCP
            # consumer at ``worker_contract_tools.py`` catches this and
            # surfaces ``ErrorCode.MERGE_DRIVER_UNAVAILABLE``.
            raise MergeDriverUnavailableError(
                "MergeStrategy.SEMANTIC requires mergiraf on $PATH; binary "
                "not found. Install mergiraf (brew install mergiraf bundles "
                "tree-sitter grammars; cargo binstall mergiraf ships only "
                "the binary) or pass strategy=MergeStrategy.LINE for the "
                "legacy git merge-file path."
            )
        return await _merge_via_mergiraf(
            base=base,
            ours=ours,
            theirs=theirs,
            label=label,
            binary=binary,
            driver_warning=driver_warning,
        )

    with tempfile.TemporaryDirectory(prefix="settle-merge-") as tmp_str:
        tmp = Path(tmp_str)
        base_path = tmp / "base"
        ours_path = tmp / "ours"
        theirs_path = tmp / "theirs"
        base_path.write_text(base)
        ours_path.write_text(ours)
        theirs_path.write_text(theirs)

        # ``git merge-file`` exit codes:
        #   0 — clean merge (no conflicts)
        #   1 — conflicts; ``ours`` is now the merged-with-markers file
        # >=2 — fatal error (bad invocation, I/O, etc.)
        proc = await asyncio.create_subprocess_exec(
            git_merge_file,
            "merge-file",
            "-p",  # write merged result to stdout
            "-L",
            "base",
            "-L",
            "ours",
            "-L",
            "theirs",
            str(ours_path),
            str(base_path),
            str(theirs_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        merged = stdout.decode("utf-8", errors="replace")

        if proc.returncode == 0:
            return MergeResult(
                merged=merged,
                conflict_count=0,
                strategy_used=MergeStrategy.LINE,
                driver_warning=driver_warning,
            )

        if proc.returncode == 1:
            # Count conflict regions by counting "<<<<<<< " markers.
            # git emits three markers per conflict hunk: <<<<<<<,
            # =======, >>>>>>>. Counting the leading ones is the
            # canonical heuristic used by git-merge-file consumers.
            conflict_count = sum(1 for line in merged.splitlines() if line.startswith("<<<<<<< "))
            logger.warning(
                "settle_merge: conflict for label=%r conflict_count=%d",
                label,
                conflict_count,
            )
            raise MergeConflictError(
                path=label,
                merged=merged,
                base=base,
                ours=ours,
                theirs=theirs,
                strategy_used=MergeStrategy.LINE,
                driver_warning=driver_warning,
            )

        # Exit >=2 — fatal.
        stderr_text = stderr.decode("utf-8", errors="replace")
        logger.error(
            "settle_merge: git merge-file fatal label=%r stderr=%s",
            label,
            stderr_text.strip(),
        )
        raise MergeFailureError(
            f"git merge-file failed (exit={proc.returncode}) for {label!r}: {stderr_text.strip()}"
        )


def _merge_three_way_sync_internal(
    *,
    base: str,
    ours: str,
    theirs: str,
    label: str = "<anonymous>",
    git_merge_file: str = "git",
) -> MergeResult:
    """Synchronous variant for CLI / non-asyncio callers (internal).

    Renamed from ``merge_three_way_sync`` in Phase 1; the public name
    is now a deprecation shim. Threading the new ``strategy`` parameter
    through this path adds dead code (the public async ``merge_three_way``
    is the canonical surface), so this internal helper intentionally
    keeps the Phase 0 ``git merge-file`` semantics unchanged.
    """
    with tempfile.TemporaryDirectory(prefix="settle-merge-") as tmp_str:
        tmp = Path(tmp_str)
        base_path = tmp / "base"
        ours_path = tmp / "ours"
        theirs_path = tmp / "theirs"
        base_path.write_text(base)
        ours_path.write_text(ours)
        theirs_path.write_text(theirs)

        import subprocess

        result = subprocess.run(
            [
                git_merge_file,
                "merge-file",
                "-p",
                "-L",
                "base",
                "-L",
                "ours",
                "-L",
                "theirs",
                str(ours_path),
                str(base_path),
                str(theirs_path),
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        merged = result.stdout
        if result.returncode == 0:
            return MergeResult(merged=merged, conflict_count=0)
        if result.returncode == 1:
            raise MergeConflictError(
                path=label,
                merged=merged,
                base=base,
                ours=ours,
                theirs=theirs,
            )
        raise MergeFailureError(
            f"git merge-file failed (exit={result.returncode}) for {label!r}: "
            f"{result.stderr.strip()}"
        )


def merge_three_way_sync(
    *,
    base: str,
    ours: str,
    theirs: str,
    label: str = "<anonymous>",
    git_merge_file: str = "git",
) -> MergeResult:
    """Deprecated synchronous variant for CLI / non-asyncio callers.

    .. deprecated::
        Use the async :func:`merge_three_way` with an explicit
        ``strategy=MergeStrategy.LINE`` argument instead. The sync
        surface will be removed after one release cycle of opt-in
        telemetry (mirrors the ``minimax27`` plan's deprecation pattern).
    """
    warnings.warn(
        "merge_three_way_sync is deprecated; use the async merge_three_way "
        "with an explicit strategy=MergeStrategy.LINE argument instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _merge_three_way_sync_internal(
        base=base,
        ours=ours,
        theirs=theirs,
        label=label,
        git_merge_file=git_merge_file,
    )
