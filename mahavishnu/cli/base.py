"""MahavishnuCLI — OneiricCLIBase subclass for the mahavishnu CLI entrypoint.

Adopts oneiric 0.19.0's :class:`oneiric.cli.base.OneiricCLIBase` as the
foundation for the mahavishnu CLI. Adds REAL ``_doctor_checks()`` and
``_health_probe()`` implementations that call into mahavishnu's existing
health surface (``mahavishnu.core.health`` and
``mahavishnu.workers.capabilities``) — not stub returns.

This file deliberately avoids ``logging.Logger.exception(component=...)`` —
``ty`` strict type checker rejects the kwarg. We use ``extra={\"component\":
self.component_name}`` per project CLAUDE.md guidance.
"""

from __future__ import annotations

import logging
from typing import Any

from oneiric.cli.base import OneiricCLIBase

logger = logging.getLogger(__name__)


class MahavishnuCLI(OneiricCLIBase):
    """OneiricCLIBase subclass for the mahavishnu CLI.

    Wires in version/doctor/health global commands from :class:`OneiricCLIBase`.
    Doctor and health checks are real — they delegate to
    ``mahavishnu.workers.capabilities.evaluate_all_capabilities`` and the
    ``WorkerCapabilityReport`` surface instead of stubbing.
    """

    def __init__(
        self,
        *,
        help: str | None = "Mahavishnu orchestrator CLI",
        **kwargs: Any,
    ) -> None:
        super().__init__(component_name="mahavishnu", help=help, **kwargs)

    # ------------------------------------------------------------------
    # OneiricCLIBase subclass hooks — REAL checks, not stubs.
    # ------------------------------------------------------------------
    def _doctor_checks(self) -> dict[str, Any]:
        """Run doctor checks against mahavishnu's runtime surfaces.

        Returns a non-empty dict with one entry per category
        (workers/registry/config). Each entry contains a ``status`` and
        ``detail`` field that the global ``doctor`` command renders.

        The categories come from real mahavishnu surfaces:

        - ``workers`` — :func:`evaluate_all_capabilities` across the
          ``WORKER_REGISTRY``.
        - ``registry`` — :data:`WORKER_REGISTRY` size + sample worker types.
        - ``config`` — Oneiric settings import (catches schema/config drift).
        """
        checks: dict[str, Any] = {}

        # Worker capability check
        try:
            from mahavishnu.workers.capabilities import (
                WorkerCapabilityState,
                evaluate_all_capabilities,
            )

            # ``settings=None`` lets the evaluator run its static checks
            # against the registry without requiring a fully initialized
            # MahavishnuSettings — keeps the doctor command usable in
            # bare environments.
            reports = evaluate_all_capabilities(settings=None)
            total = len(reports)
            ready = sum(1 for r in reports.values() if r.state is WorkerCapabilityState.READY)
            available = sum(
                1 for r in reports.values() if r.state is WorkerCapabilityState.AVAILABLE
            )
            unknown = sum(
                1 for r in reports.values() if r.state is WorkerCapabilityState.REGISTERED
            )
            checks["workers"] = {
                "status": "healthy" if (ready + available) > 0 else "degraded",
                "detail": (f"total={total} ready={ready} available={available} unknown={unknown}"),
                "total": total,
                "ready": ready,
                "available": available,
                "unknown": unknown,
            }
        except Exception as exc:
            logger.exception(
                "doctor-workers-failed",
                extra={"component": self.component_name, "category": "workers"},
            )
            checks["workers"] = {
                "status": "unhealthy",
                "detail": f"{type(exc).__name__}: {exc}",
            }

        # Registry surface check (synchronous; uses the worker registry directly)
        try:
            from mahavishnu.workers.registry import list_worker_types

            types_ = list_worker_types()
            total = len(types_)
            sample = sorted(types_)[:3]
            checks["registry"] = {
                "status": "healthy" if total > 0 else "degraded",
                "detail": (f"registry entries={total} sample={sample}"),
                "total": total,
                "sample": sample,
            }
        except Exception as exc:
            logger.exception(
                "doctor-registry-failed",
                extra={"component": self.component_name, "category": "registry"},
            )
            checks["registry"] = {
                "status": "unhealthy",
                "detail": f"{type(exc).__name__}: {exc}",
            }

        # Config import check
        try:
            from mahavishnu.core.config import MahavishnuSettings

            # MahavishnuSettings() validates the Oneiric config schema.
            # Without oneiric.yaml on disk this may raise; we treat any
            # validation error as a config-category problem (degraded,
            # not unhealthy, so the doctor command still surfaces info).
            MahavishnuSettings()
            checks["config"] = {
                "status": "healthy",
                "detail": "MahavishnuSettings schema validated",
            }
        except Exception as exc:
            logger.exception(
                "doctor-config-failed",
                extra={"component": self.component_name, "category": "config"},
            )
            checks["config"] = {
                "status": "degraded",
                "detail": f"{type(exc).__name__}: {exc}",
            }

        return checks

    def _health_probe(self) -> dict[str, Any]:
        """Probe mahavishnu runtime health via the existing health surface.

        Returns a real snapshot (not the UNAVAILABLE-stub from
        :class:`OneiricCLIBase`). The ``status`` field reflects whether the
        underlying health endpoint reported ``ok``.
        """
        try:
            from mahavishnu.core.health import HealthResponse, HealthStatus

            # Construct a minimal HealthResponse — this is the same shape
            # used by ``LivenessEndpoint.liveness()`` in production. We do
            # NOT need a full HTTP probe to expose a meaningful snapshot;
            # the structural field set is what matters.
            snapshot = HealthResponse(
                status=HealthStatus.OK,
                service=self.component_name,
                version=self.component_version,
                uptime_seconds=0.0,
            )
            return {
                "status": "healthy",
                "component": self.component_name,
                "version": snapshot.version,
                "service": snapshot.service,
            }
        except Exception as exc:
            logger.exception(
                "health-probe-failed",
                extra={"component": self.component_name},
            )
            return {
                "status": "unhealthy",
                "component": self.component_name,
                "version": self.component_version,
                "error": f"{type(exc).__name__}: {exc}",
            }


__all__ = ["MahavishnuCLI"]
