"""Loop-until-dry helper for re-runnable scanners.

Phase 2 of the Ultracode Integration Wiring plan. Provides
:func:`detect_until_dry`, a small async helper that drives a re-runnable
scanner until K consecutive rounds surface no new findings, with a hard
cap on total iterations.

The pattern
-----------
A scanner is called repeatedly until a number of consecutive empty rounds
signals convergence. It is suitable for any async scan where later rounds
may surface work that earlier rounds missed — e.g. cross-repo pattern
detection where a new cluster appears after round N-1's snapshot, or
ecosystem clone detection where a freshly-merged file creates a new
similarity pair. Repeated re-runs let the scan "chase" the evolving
corpus until no new findings appear, then stop.

Dedup-key contract
------------------
``dedup_key`` is a single-argument callable applied to each finding to
produce a hashable identity used for de-duplication across iterations.
The default ``lambda r: r["id"]`` requires every finding to be a
mapping with an ``"id"`` key. If ``dedup_key`` raises (most commonly
``KeyError`` on a finding missing its identifier), the helper aborts
the loop, captures the exception and the findings that were successfully
merged from prior iterations, and returns ``stopped_reason="error"``.

stopped_reason semantics
------------------------
- ``"converged"`` — K consecutive rounds (default 2) surfaced no new
  findings; the scan has dried up. This is the happy path.
- ``"max_iterations"`` — Hard iteration cap was hit without convergence.
  Operators may need to raise ``max_iterations`` or accept that the
  corpus is non-converging for this scan.
- ``"error"`` — ``scan_fn`` raised OR a per-iteration timeout fired OR
  ``dedup_key`` raised on a finding. The exception is captured in
  ``run_metadata["exception"]`` and its summary in
  ``run_metadata["error"]``; findings successfully merged from prior
  iterations are returned so the caller can decide whether to use them.

The helper never propagates application exceptions out of
:func:`detect_until_dry`. ``asyncio.CancelledError`` on the outer task is
the one exception that propagates as normal — cancellation is not a
recoverable error.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from oneiric.core.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = get_logger("mahavishnu.loop_helpers")


def _dedupe_by_key(items: list[Any], dedup_key: Callable[[Any], Any]) -> list[Any]:
    """Return ``items`` in first-seen order, deduplicated by ``dedup_key(item)``.

    The first occurrence of each distinct key is kept; later duplicates
    with the same key are dropped. Relies on the stable iteration order
    of ``set`` and ``list`` (CPython 3.7+ guarantees insertion order).
    """
    seen: set[Any] = set()
    out: list[Any] = []
    for item in items:
        key = dedup_key(item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _validate_detect_until_dry_args(
    *,
    k_empty_rounds: int,
    max_iterations: int,
    per_iteration_timeout_seconds: float,
) -> None:
    """Validate ``detect_until_dry`` arguments; raise ``ValueError`` on bad input.

    Extracted from ``detect_until_dry`` to keep its cyclomatic complexity
    below the project ceiling (see CLAUDE.md hard limits).
    """
    if k_empty_rounds < 1:
        raise ValueError(f"k_empty_rounds must be >= 1, got {k_empty_rounds}")
    if max_iterations < 1:
        raise ValueError(f"max_iterations must be >= 1, got {max_iterations}")
    if per_iteration_timeout_seconds <= 0:
        raise ValueError(
            f"per_iteration_timeout_seconds must be > 0, "
            f"got {per_iteration_timeout_seconds}"
        )


async def detect_until_dry(
    scan_fn: Callable[[], Awaitable[list[Any]]],
    *,
    k_empty_rounds: int = 2,
    max_iterations: int = 5,
    dedup_key: Callable[[Any], Any] = lambda r: r["id"],
    per_iteration_timeout_seconds: float = 60.0,
) -> tuple[list[Any], dict[str, Any]]:
    """Run ``scan_fn`` repeatedly until the result stream dries up.

    Each iteration awaits ``scan_fn()`` under a wall-clock timeout of
    ``per_iteration_timeout_seconds``. The findings returned by each call
    are merged into a cumulative list, deduplicated by ``dedup_key``. When
    ``k_empty_rounds`` consecutive iterations return zero NEW findings, the
    loop terminates with ``stopped_reason="converged"``. If the iteration
    cap (``max_iterations``) is reached first, the loop terminates with
    ``stopped_reason="max_iterations"``.

    Args:
        scan_fn: Zero-argument async callable returning a list of findings.
        k_empty_rounds: Number of consecutive rounds with zero new findings
            that signals convergence. Must be ``>= 1``.
        max_iterations: Hard cap on total iterations. Must be ``>= 1``.
        dedup_key: Callable mapping a finding to a hashable identity used
            for de-duplication across iterations. Default assumes each
            finding is a mapping with an ``"id"`` key.
        per_iteration_timeout_seconds: Per-iteration wall-clock cap. On
            expiry the iteration is recorded as an error and the loop
            terminates. Must be ``> 0``.

    Returns:
        A tuple ``(all_findings, run_metadata)``:
            * ``all_findings`` — list of unique findings merged across
              successful iterations, in first-seen order.
            * ``run_metadata`` — dict with keys:
              - ``iterations`` (``int``): number of iterations completed.
              - ``empty_rounds`` (``int``): consecutive empty rounds
                observed at termination.
              - ``stopped_reason``
                (``Literal["converged", "max_iterations", "error"]``).
              - ``error`` (``str | None``): human summary when
                ``stopped_reason == "error"``.
              - ``exception`` (``BaseException | None``): the captured
                exception when ``stopped_reason == "error"``.

    Raises:
        ValueError: When ``k_empty_rounds < 1``, ``max_iterations < 1``,
            or ``per_iteration_timeout_seconds <= 0``.
    """
    _validate_detect_until_dry_args(
        k_empty_rounds=k_empty_rounds,
        max_iterations=max_iterations,
        per_iteration_timeout_seconds=per_iteration_timeout_seconds,
    )

    all_findings: list[Any] = []
    seen_keys: set[Any] = set()
    empty_rounds = 0
    iterations = 0
    stopped_reason: Literal["converged", "max_iterations", "error"] = "max_iterations"
    error: str | None = None
    exception: BaseException | None = None

    while iterations < max_iterations:
        iterations += 1
        try:
            iter_findings: list[Any] = await asyncio.wait_for(
                scan_fn(),
                timeout=per_iteration_timeout_seconds,
            )
        except TimeoutError as exc:
            stopped_reason = "error"
            error = (
                f"scan_fn timed out after {per_iteration_timeout_seconds}s "
                f"on iteration {iterations}"
            )
            exception = exc
            logger.exception(
                "detect_until_dry: timeout on iteration %d", iterations
            )
            break
        except Exception as exc:
            stopped_reason = "error"
            error = (
                f"scan_fn raised on iteration {iterations}: "
                f"{type(exc).__name__}: {exc}"
            )
            exception = exc
            logger.exception(
                "detect_until_dry: scan_fn raised on iteration %d", iterations
            )
            break

        # Inline per-finding key extraction so every ``dedup_key`` call is
        # error-trapped; routing this through :func:`_dedupe_by_key` would let
        # a ``KeyError`` (or similar) propagate past our handler. Intra-
        # iteration duplicates collapse naturally via the cumulative
        # ``seen_keys`` membership check.
        new_findings: list[Any] = []
        dedup_error: Exception | None = None
        for finding in iter_findings:
            try:
                key = dedup_key(finding)
            except Exception as exc:
                dedup_error = exc
                break
            if key not in seen_keys:
                seen_keys.add(key)
                new_findings.append(finding)

        # Extend with whatever was successfully deduped BEFORE checking
        # ``dedup_error`` so the caller observes partial findings from this
        # iteration even when a later finding trips the dedup. Items in
        # ``new_findings`` were individually validated (their ``dedup_key``
        # ran without raising); the failed finding never reaches
        # ``all_findings``.
        all_findings.extend(new_findings)

        if dedup_error is not None:
            stopped_reason = "error"
            error = (
                f"dedup_key raised on iteration {iterations}: "
                f"{type(dedup_error).__name__}: {dedup_error}"
            )
            exception = dedup_error
            logger.exception(
                "detect_until_dry: dedup_key raised on iteration %d", iterations
            )
            break

        if not new_findings:
            empty_rounds += 1
            if empty_rounds >= k_empty_rounds:
                stopped_reason = "converged"
                break
        else:
            empty_rounds = 0

    run_metadata: dict[str, Any] = {
        "iterations": iterations,
        "empty_rounds": empty_rounds,
        "stopped_reason": stopped_reason,
        "error": error,
        "exception": exception,
    }
    return all_findings, run_metadata
