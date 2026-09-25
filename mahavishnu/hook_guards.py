"""Hook guards — planned guard layer for ``bodai_hook_bridge``.

Per docs/spec/2026-09-14-mcp-mcp-decomposition-design.md §4.13.3
the bridge delegates PreToolUse decisions to a ``license_guard``
callable. That guard is planned for a future task; this stub keeps
``mahavishnu.hook_guards`` importable so the bridge's
``from mahavishnu.hook_guards import license_guard`` resolves and
ty stops complaining about an unresolved module. The stub returns 0
(permissive default), matching the bridge's documented ImportError
fallback so the hook hot path is never blocked on the missing guard.

Tests inject a stronger ``stub_module`` via
``monkeypatch.setitem(sys.modules, "mahavishnu.hook_guards", ...)``
to pin delegation semantics without depending on this stub's body.
"""

from __future__ import annotations

from typing import Any, Protocol


class CanonicalEnvelopeLike(Protocol):
    """Minimal protocol — the guard only reads tool_name and tool_input.

    Matches the real ``CanonicalEnvelope`` shape (``tool_input`` may be
    ``None`` for events that don't carry a tool payload) so existing
    envelope instances are assignable without a cast.
    """

    tool_name: str | None
    tool_input: dict[str, Any] | None


def license_guard(env: CanonicalEnvelopeLike) -> int:
    """Permissive stub: return 0 (accept) until the real guard lands.

    Returns:
        0 — accept the tool call.
    """
    return 0


__all__ = ["CanonicalEnvelopeLike", "license_guard"]
