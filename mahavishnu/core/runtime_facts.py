"""Runtime facts builder for the ``list_adapters`` MCP tool (Phase 2).

Mirrors the legacy inline ``list_adapters`` wire shape so the FastMCP
handler can delegate with ``RuntimeFactsBuilder(self.app).build_all()``.

Wire contract (v3, plan 2026-09-26):

* ``build_all`` returns the legacy LITERAL wire shape:
  ``{"adapters": {<name>: {"enabled", "health", "type", "features"}},
  "count": int, "available_names": list[str]}``.
* The Oneiric envelope (``success / registry / runtime / health``) is
  constructed inside :meth:`MahavishnuApp.report_runtime_facts`, NOT
  inside ``build_all``. This keeps the MCP-side ``list_adapters``
  payload binary-compatible with the pre-Phase-2 inline body.

Phase 2 design rules:

* No akosha / session_buddy / oneiric imports (stdlib ``logging`` only).
* Sync-only introspection; ``build_all`` never ``await``s; never makes
  blocking I/O. Live health probing belongs in
  ``MahavishnuApp.report_runtime_facts`` (separate circuit-breaker
  scope) so boot never blocks on a degraded adapter.
* Reads only attributes exposed by the ``OrchestratorAdapter`` protocol
  (``provider``, ``version``, ``enabled``, ``capabilities``, ``metadata``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .adapters.base import OrchestratorAdapter
    from .app import MahavishnuApp


logger = logging.getLogger(__name__)


class RuntimeFactsBuilder:
    """Enumerate ``MahavishnuApp.adapters`` into the legacy adapter-listing shape.

    The returned dict matches the canonical wire shape served by the
    pre-Phase-2 inline ``list_adapters`` MCP tool body. The Oneiric
    envelope is NOT constructed in this builder; it lives in
    :meth:`MahavishnuApp.report_runtime_facts` so the two surfaces
    (MCP ``list_adapters`` vs Oneiric push) can evolve independently.

    The builder is intentionally pure-introspection: ``build_all`` does
    not ``await`` anything. Live health probing is out of scope and
    belongs in the calling report_runtime_facts path (separate
    circuit-breaker scope).
    """

    LEGACY_HEALTH_FIELD = "unknown"  # Placeholder for legacy wire shape.
    DEFAULT_ADAPTER_TYPE = "engine"

    def __init__(self, app: "MahavishnuApp") -> None:
        self._app = app

    def build_all(self) -> dict[str, Any]:
        """Return the canonical adapter-listing envelope (legacy wire shape).

        Returns
        -------
        dict[str, Any]
            ``{"adapters": {<name>: {"enabled": bool, "health": str,
            "type": str, "features": list[str]}}, "count": int,
            "available_names": list[str]}``. The legacy shape is
            preserved verbatim for backward compatibility with
            pre-Phase-2 callers.
        """
        adapters: dict[str, dict[str, Any]] = {}
        for key in sorted(self._app.adapters):
            entry = self._build_entry(key, self._app.adapters[key])
            adapters[key] = entry

        available_names = sorted(adapters.keys())
        return {
            "adapters": adapters,
            "count": len(adapters),
            "available_names": available_names,
        }

    def _build_entry(
        self, key: str, adapter: "OrchestratorAdapter"
    ) -> dict[str, Any]:
        """Translate one ``OrchestratorAdapter`` into the legacy catalog row.

        Reads only protocol attributes; missing attributes fall back to
        safe defaults (``provider == key``, ``version == "unknown"``).
        The ``health`` field defaults to ``"unknown"`` to preserve the
        legacy wire shape; live probing is intentionally out of scope.
        """
        capabilities = sorted(getattr(adapter, "capabilities", []) or [])
        enabled = bool(getattr(adapter, "enabled", True))

        return {
            "enabled": enabled,
            "health": self.LEGACY_HEALTH_FIELD,
            "type": self.DEFAULT_ADAPTER_TYPE,
            "features": capabilities,
        }