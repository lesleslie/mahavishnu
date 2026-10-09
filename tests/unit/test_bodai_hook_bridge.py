"""Tests for bodai_hook_bridge event handlers.

This file was created in the pool-bootstrap plan (2026-10-09).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from mahavishnu.bodai_hook_bridge import (
    CanonicalEnvelope,
    _EVENT_HANDLERS,
    handle_pool_bootstrap,
)


def _make_env(harness: str = "claude") -> CanonicalEnvelope:
    # CanonicalEnvelope is a @dataclass with required field `cwd`
    # (no default). `payload={}` is NOT a field — the bridge normalizes
    # raw harness JSON into individual fields upstream, not via a
    # `payload` attribute.
    return CanonicalEnvelope(
        event="SessionStart", harness=harness, session_id="test", cwd="/tmp"
    )


def test_handle_pool_bootstrap_emits_telemetry_only() -> None:
    """The bridge handler does NOT call MCP — it only emits telemetry.

    The actual work is in the standalone hook script which calls
    mcp__mahavishnu__pool_bootstrap (Task 9). This handler is the
    bridge-side audit trail entry.
    """
    env = _make_env()
    with patch("mahavishnu.bodai_hook_bridge.logger") as mock_logger:
        result = handle_pool_bootstrap(env)

    assert result == 0  # SessionStart must never block
    assert mock_logger.info.call_count >= 1
    call_args = mock_logger.info.call_args
    assert "pool_bootstrap" in call_args.args[0]


def test_handle_pool_bootstrap_returns_zero_on_unexpected_exception() -> None:
    """If the handler raises unexpectedly, it must still return 0."""
    env = _make_env()
    with patch("mahavishnu.bodai_hook_bridge.logger") as mock_logger:
        mock_logger.info.side_effect = RuntimeError("logging broken")

    result = handle_pool_bootstrap(env)
    assert result == 0  # SessionStart must always return 0


def test_event_handlers_accepts_legacy_callable_shape() -> None:
    """Backward-compat: a single Callable entry (not in a list) still works.

    Verifies the dispatch site's `if not isinstance(handlers, list): handlers = [handlers]`
    fallback path. This guards against accidental breakage of any
    external caller that mutates _EVENT_HANDLERS to the legacy shape.
    """
    from mahavishnu.bodai_hook_bridge import handle

    def _legacy_handler(env: CanonicalEnvelope) -> int:
        return 0

    # Temporarily replace the SessionStart entry with a single Callable
    original = _EVENT_HANDLERS["SessionStart"]
    _EVENT_HANDLERS["SessionStart"] = _legacy_handler  # type: ignore[assignment]
    try:
        # Should not raise; the dispatch loop normalizes to a list
        result = handle(event_name="SessionStart", harness="claude", payload={})
        assert result == 0
    finally:
        _EVENT_HANDLERS["SessionStart"] = original  # type: ignore[assignment]
