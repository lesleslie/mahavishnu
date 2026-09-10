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
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import TYPE_CHECKING, Callable
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
    "MergeDriverRuntimeConfig",
    "MergeDriverUnavailableError",
    "MergeFailureError",
    "MergeResult",
    "MergeStrategy",
    "merge_three_way",
    "register_mark_fallback_callback",
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


# Phase 4 deferred review (M3): frozen dataclass replaces the previous
# mutable ``dict[str, object]`` so the runtime config is immutable and
# the type contract is explicit. The bootstrap installs a new instance
# via :func:`set_merge_driver_runtime_config` (which returns it for
# callers that want to capture the snapshot).
#
# Phase 4 deferred review (m2): the module-level singleton is populated
# at import from ``MAHAVISHNU_MERGE_DRIVER_DEFAULT`` and
# ``MAHAVISHNU_MERGE_DRIVER_REQUIRED`` env vars. CLI tools that import
# this module but skip the bootstrap (e.g. one-shot scripts) get the
# env-var-driven defaults; the bootstrap call overrides these on app
# start. Both env vars are also bound at the Pydantic-settings layer in
# :mod:`mahavishnu.core.config` — the env-var read here is a defense in
# depth for non-bootstrap importers.
@dataclass(frozen=True)
class MergeDriverRuntimeConfig:
    """Immutable snapshot of the Oneiric ``merge_driver_*`` settings.

    ``default`` is the operator's configured strategy ("line" or
    "mergiraf"). ``required`` is the operator's opt-in to hard-fail at
    boot when the mergiraf binary is missing. Both fields are stored
    as the typed values the bootstrap installs — the env-var read at
    module import normalizes the strings to ``MergeStrategy`` before
    constructing the dataclass so downstream code never needs to
    validate ``"mergiraf"`` vs ``MergeStrategy.MERGIRAF`` shape.
    """

    default: MergeStrategy
    required: bool


def _read_runtime_config_from_env() -> MergeDriverRuntimeConfig:
    """Build a ``MergeDriverRuntimeConfig`` from the operator env vars.

    Recognizes ``MAHAVISHNU_MERGE_DRIVER_DEFAULT`` ("line" / "mergiraf";
    anything else falls back to ``LINE`` defensively) and
    ``MAHAVISHNU_MERGE_DRIVER_REQUIRED`` (truthy = "1"/"true"/"yes",
    falsy = "0"/"false"/"no" or unset). Mirrors the Pydantic-settings
    layer in :mod:`mahavishnu.core.config` — the duplication is
    intentional for non-bootstrap importers.
    """
    raw_default = os.environ.get("MAHAVISHNU_MERGE_DRIVER_DEFAULT", "line").strip().lower()
    strategy = MergeStrategy.SEMANTIC if raw_default == "mergiraf" else MergeStrategy.LINE
    raw_required = os.environ.get("MAHAVISHNU_MERGE_DRIVER_REQUIRED", "false").strip().lower()
    required = raw_required in {"1", "true", "yes", "on"}
    return MergeDriverRuntimeConfig(default=strategy, required=required)


# Module-level singleton. Bootstrap overrides via
# :func:`set_merge_driver_runtime_config` (replaced wholesale rather
# than mutated, so the frozen contract holds).
_RUNTIME_CONFIG: MergeDriverRuntimeConfig = _read_runtime_config_from_env()


# Phase 4 deferred review (M4): callback registration replaces the
# previous ``from mahavishnu.core.health import mark_merge_driver_fallback``
# import inside ``_resolve_default_strategy``. Settle is a low-level
# module and core.health is higher in the dependency direction; the
# bootstrap owns the wire-up and registers the callback here. Tests
# install fakes via this hook.
#
# The callable slot defaults to a no-op so the runtime fallback path
# never needs a None check; ``register_mark_fallback_callback`` swaps
# it (and accepts ``None`` to restore the no-op).
def _noop() -> None:
    """Empty callback used when no fallback handler is registered.

    Avoids a None check at every fallback site — registering this
    default at import time keeps the runtime path branch-free.
    """


_mark_fallback_callback: Callable[[], None] = _noop


def register_mark_fallback_callback(callback: Callable[[], None] | None) -> None:
    """Install or remove the callback fired on runtime fallback.

    The settle module cannot import from ``mahavishnu.core.health``
    directly — that would invert the dependency direction (settle is
    low-level; health is higher). The bootstrap registers
    ``mark_merge_driver_fallback`` here once during
    ``MahavishnuApp._init_observability``; tests can install a fake.

    Pass ``None`` (or the no-op) to clear the registration. The
    default state is already no-op so production callers don't need
    to deregister on shutdown.
    """
    global _mark_fallback_callback
    _mark_fallback_callback = _noop if callback is None else callback


def set_merge_driver_runtime_config(
    *,
    default: MergeStrategy | str,
    required: bool,
) -> MergeDriverRuntimeConfig:
    """Install the Oneiric ``merge_driver_*`` settings for runtime use.

    Called by ``MahavishnuApp._init_observability`` during app bootstrap.
    The default-resolution matrix in :func:`_resolve_default_strategy`
    reads these values on every call. Process-lifetime state — changing
    it at runtime requires a process restart (the startup guard runs
    once per process; tmux panes are out of scope per R4 #D).

    Returns the new :class:`MergeDriverRuntimeConfig` so callers
    (especially tests) can capture the snapshot without re-reading the
    module global. Accepts ``str`` for ``default`` to preserve the
    bootstrap signature; ``MergeStrategy`` is preferred for new code.
    """
    global _RUNTIME_CONFIG
    if isinstance(default, str):
        normalized = default.strip().lower()
        strategy = MergeStrategy.SEMANTIC if normalized == "mergiraf" else MergeStrategy.LINE
    else:
        strategy = default
    _RUNTIME_CONFIG = MergeDriverRuntimeConfig(default=strategy, required=required)
    return _RUNTIME_CONFIG


def reset_runtime_config_from_env() -> MergeDriverRuntimeConfig:
    """Re-read ``MAHAVISHNU_MERGE_DRIVER_*`` env vars into the singleton.

    Test-only helper. Production code paths should call
    :func:`set_merge_driver_runtime_config` from the bootstrap (which
    sources from the Oneiric ``merge_driver_*`` settings rather than the
    raw env). This function exists so tests can exercise the env-var
    branch of :func:`_read_runtime_config_from_env` without reloading
    the module — a reload creates a fresh ``MergeDriverRuntimeConfig``
    class object that breaks ``isinstance`` checks elsewhere in the
    process.
    """
    global _RUNTIME_CONFIG
    _RUNTIME_CONFIG = _read_runtime_config_from_env()
    return _RUNTIME_CONFIG


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
       increment ``merge.fallback_total`` OTel counter with reason
       ``mergiraf_missing_default_mergiraf``, fire the registered
       fallback callback, return :class:`MergeStrategy.LINE`. The
       fallback is **NOT** silent — the OTel counter and the
       ``MergeResult.driver_warning`` field surface the degradation.
    3. ``merge_driver_default == "line"`` and binary missing →
       :class:`MergeStrategy.LINE` (Phase 0/1/2/3 behavior) but the
       Phase 4 deferred review (m1) fix ALSO logs ``merge.semantic.unavailable``
       and increments the counter with reason
       ``mergiraf_missing_default_line``. Pre-m1 the counter was silent
       when the operator explicitly chose ``"line"``, hiding telemetry
       the Phase 5 30-day gate needs to confirm that mergiraf
       installations are tracking adoption. The fallback callback still
       fires (the runtime degradation is real, the operator just
       expected it). The legacy PATH-probe path (SEMANTIC when
       ``mergiraf`` is on $PATH even though default is "line") is kept
       for backward compatibility — the follow-up default-flip plan
       re-evaluates this.
    """
    cfg_default = _RUNTIME_CONFIG.default
    binary = _resolve_mergiraf_binary()
    if cfg_default == MergeStrategy.SEMANTIC:
        if binary is not None:
            return MergeStrategy.SEMANTIC
        return _runtime_fallback(
            cfg_default=cfg_default,
            log_message=(
                "merge.semantic.unavailable: merge_driver_default='mergiraf' "
                "but binary missing on $PATH. Falling back to LINE strategy. "
                "Install mergiraf (brew install mergiraf) or set "
                "merge_driver_default='line' to silence this warning. "
                "/health merge_driver.degraded_since will be set."
            ),
            reason="mergiraf_missing_default_mergiraf",
        )
    # cfg_default == "line"
    if binary is not None:
        return MergeStrategy.SEMANTIC
    # m1: counter fires even when default is "line" so the 30-day
    # telemetry gate sees real-world missing-binary exposure instead of
    # a misleading zero. Log + counter + callback must NEVER raise.
    return _runtime_fallback(
        cfg_default=cfg_default,
        log_message=(
            "merge.semantic.unavailable: merge_driver_default='line' but "
            "mergiraf binary missing on $PATH. Recording exposure so the "
            "30-day telemetry gate can see adoption signal. Falling back "
            "to LINE strategy."
        ),
        reason="mergiraf_missing_default_line",
    )


def _runtime_fallback(
    *,
    cfg_default: MergeStrategy,
    log_message: str,
    reason: str,
) -> MergeStrategy:
    """Shared body for both runtime-fallback branches.

    The two matrix branches (``default=='mergiraf' AND missing`` and
    ``default=='line' AND missing``) share the log + counter + callback
    fan-out; only the log message and counter ``reason`` differ. The
    try/except keeps observability best-effort: a broken OTel SDK or
    a callback that raises must never crash the user's merge request.
    """
    logger.warning(log_message)
    try:
        _merge_fallback_counter.add(1, {"reason": reason})
        # Phase 4 deferred review (M4): fire the callback registered by
        # the bootstrap (or a test fake). The default no-op keeps the
        # hot path branch-free for non-bootstrap importers.
        _mark_fallback_callback()
    except Exception as exc:  # noqa: BLE001 — observability must never crash merge
        logger.warning(
            "merge.semantic.fallback_observability_error: "
            "type=%s message=%s — fallback decision stands, "
            "/health signal may be partial.",
            type(exc).__name__,
            exc,
        )
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
    cfg_default = _RUNTIME_CONFIG.default
    binary_available = _resolve_mergiraf_binary() is not None
    runtime_fallback = (
        effective == MergeStrategy.LINE
        and cfg_default == MergeStrategy.SEMANTIC
        and not binary_available
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
