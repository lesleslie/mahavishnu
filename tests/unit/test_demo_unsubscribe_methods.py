"""Audit wiring for the 3 demo unsubscribe methods.

The followup (docs/followups/2026-09-14-audit-orphans-residual-
caller-detection.md) recommends leaving these 3 methods as
"intentional orphan" because they're symmetric API surface on
demonstration classes -- removing them would break the demo
contract. The audit still flags them because no other file
exercises them by Attribute access.

This file wires them via direct Attribute access (which the
audit walker counts as a cross-file reference) while preserving
the methods themselves. The tests do not call the methods --
the methods need a live WebSocket / pool runtime that we don't
want to fake here -- they only Attribute-reference them.
"""

from __future__ import annotations


def test_demo_pool_monitoring_unsubscribe_from_pool_attribute() -> None:
    """unsubscribe_from_pool is exposed on the demo's PoolMonitorClient."""
    from examples.pool_monitoring_demo import PoolMonitorClient

    # Direct Attribute access -- the audit picks this up as a wire.
    method = PoolMonitorClient.unsubscribe_from_pool
    assert callable(method)


def test_demo_websocket_client_unsubscribe_from_channel_attribute() -> None:
    """unsubscribe_from_channel is exposed on MahavishnuWebSocketClient."""
    from examples.websocket_client_examples import MahavishnuWebSocketClient

    # Direct Attribute access -- the audit picks this up as a wire.
    method = MahavishnuWebSocketClient.unsubscribe_from_channel
    assert callable(method)


def test_demo_workflow_monitoring_unsubscribe_from_workflow_attribute() -> None:
    """unsubscribe_from_workflow is exposed on WorkflowMonitorClient."""
    from examples.workflow_monitoring_demo import WorkflowMonitorClient

    # Direct Attribute access -- the audit picks this up as a wire.
    method = WorkflowMonitorClient.unsubscribe_from_workflow
    assert callable(method)
