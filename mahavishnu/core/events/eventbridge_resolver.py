"""Production wiring entry point for the Mahavishnu EventBridge publisher.

The ``mahavishnu.core.events.mahavishnu_publisher`` module's
``publish_workflow_*`` functions accept an injected publisher. The
``WebSocketServer`` exposes ``set_eventbridge_publisher()`` for runtime
injection. This resolver is the seam where production wiring happens.

Wiring is opt-in:
- ``settings.eventbridge.enabled=False`` (default) -> returns None
- ``settings.eventbridge.dry_run=True`` (default) -> returns None
- ``enabled=True`` AND ``dry_run=False`` AND ``bridge`` provided ->
  constructs ``EventBridgePublisher(bridge)``, calls
  ``server.set_eventbridge_publisher(...)`` with it, and returns the
  new publisher.

When ``bridge`` is None (the pre-Oneiric-runtime case), the resolver
returns None -- the full Oneiric runtime initialization is deferred;
this resolver is the seam where production code will pass the live
bridge once that wiring exists.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from mahavishnu.core.events.eventbridge_adapter import EventBridgePublisher

if TYPE_CHECKING:
    from mahavishnu.core.config import MahavishnuSettings
    from mahavishnu.core.events.canonical import OneiricEventPublisherProtocol


class _WebSocketServerProtocol(Protocol):
    def set_eventbridge_publisher(
        self,
        publisher: OneiricEventPublisherProtocol | None,
    ) -> None: ...


def resolve_event_publisher(
    settings: MahavishnuSettings,
    *,
    server: _WebSocketServerProtocol,
    bridge: Any | None = None,
) -> EventBridgePublisher | None:
    """Construct an EventBridgePublisher (when opted in) and wire it.

    Args:
        settings: Loaded Mahavishnu settings. The ``eventbridge`` block
            controls whether wiring happens.
        server: WebSocket server instance with a
            ``set_eventbridge_publisher`` method (production injects via
            this).
        bridge: Pre-constructed Oneiric EventBridge instance. If None,
            the resolver returns None -- this is the pre-Oneiric-runtime
            case.

    Returns:
        ``EventBridgePublisher(bridge)`` when enabled, not dry-run, and
        a bridge is available. ``None`` otherwise.
    """
    eb = settings.eventbridge
    if not eb.enabled:
        return None
    if eb.dry_run:
        return None
    if bridge is None:
        return None
    publisher = EventBridgePublisher(bridge)
    server.set_eventbridge_publisher(publisher)
    return publisher


__all__ = ["resolve_event_publisher"]
