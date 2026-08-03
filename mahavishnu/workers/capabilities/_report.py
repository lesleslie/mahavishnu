"""Public entry points for capability evaluation."""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING, Any

from ..registry import WORKER_REGISTRY, get_worker_config
from ._cache import invalidate as cache_invalidate
from ._cache import put as cache_put
from ._observability import emit_transition, record_cache, record_probe, record_probe_failure
from ._probes import (
    _probe_openclaw_cli,
    _probe_openclaw_gateway,
)
from ._states import WorkerCapabilityReport, WorkerCapabilityState
from ._static import StaticContext, evaluate_static

if TYPE_CHECKING:
    from collections.abc import Iterable


def _run_live(report, config, settings):
    if report.state is not WorkerCapabilityState.READY:
        return report
    # Dispatch is per-branch so each call site matches its probe's typed
    # signature (avoids tuple-spreading unions that confuse ty).
    if config.worker_type == "gateway-openclaw":
        endpoint = os.getenv("OPENCLAW_GATEWAY_URL", "")
        token = os.getenv("OPENCLAW_GATEWAY_TOKEN")
        check = asyncio.run(_probe_openclaw_gateway(endpoint, token))
    elif config.worker_type == "terminal-openclaw":
        check = asyncio.run(_probe_openclaw_cli("openclaw"))
    elif config.requires_tool:
        check = asyncio.run(_probe_openclaw_cli(config.requires_tool))
    else:
        return report
    start = time.perf_counter()
    record_probe(config.worker_type, check.kind, time.perf_counter() - start, check.status)
    if check.status == "fail":
        record_probe_failure(report, check.kind, check.safe_reason or "unknown")
    return WorkerCapabilityReport(
        report.worker_type,
        WorkerCapabilityState.AVAILABLE if check.status == "pass" else WorkerCapabilityState.READY,
        report.checks + [check],
        report.missing_requirements,
        safe_reason=report.safe_reason,
    )


def evaluate_worker_capabilities(
    worker_type: str, *, settings: Any, force_live: bool = False
) -> WorkerCapabilityReport:
    key = f"{worker_type}:full" if force_live else f"{worker_type}:static"
    cached = None
    if cached is not None:
        record_cache(worker_type, "hit")
        return cached
    record_cache(worker_type, "miss")
    config = get_worker_config(worker_type)
    if config is None:
        report = WorkerCapabilityReport(
            worker_type,
            WorkerCapabilityState.REGISTERED,
            missing_requirements=[f"unknown:{worker_type}"],
            safe_reason="unknown worker type",
        )
    else:
        report = evaluate_static(
            worker_type, config=config, ctx=StaticContext(settings, dict(os.environ.items()))
        )
        report = _run_live(report, config, settings) if force_live else report
    cache_put(key, report)
    emit_transition(report)
    return report


def evaluate_all_capabilities(
    *, settings: Any, force_live: bool = False
) -> dict[str, WorkerCapabilityReport]:
    return {
        w: evaluate_worker_capabilities(w, settings=settings, force_live=force_live)
        for w in WORKER_REGISTRY
    }


def select_routable_workers(
    candidates: Iterable[str] | None = None, *, settings: Any, require_available: bool = False
) -> list[str]:
    result = []
    for w in list(candidates) if candidates is not None else list(WORKER_REGISTRY):
        state = evaluate_worker_capabilities(w, settings=settings).state
        if state is WorkerCapabilityState.AVAILABLE or (
            state is WorkerCapabilityState.READY and not require_available
        ):
            result.append(w)
    return result


def invalidate_capability(worker_type: str) -> None:
    cache_invalidate(worker_type)
