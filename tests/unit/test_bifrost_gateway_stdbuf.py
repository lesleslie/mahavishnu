"""Phase G follow-up tests for ``wrap_with_line_buffering`` in the Bifrost gateway.

Per docs/plans/2026-10-15-bifrost-gateway-wiring.md §5 Phase G follow-ups
the bifrost-gateway Node subprocess should emit stdout/stderr with
line-buffering so the e2e test_agno_dispatch_emits_caller_id sees
``bifrost.log`` entries within seconds rather than after the ~4 KB
block-buffer fills.

The wrapper prepends ``stdbuf -oL -eL`` when ``stdbuf`` is on PATH
and falls back to the bare command (with a stderr warning) when it
isn't. These tests pin both branches plus the integration with
``launch_bifrost``'s ``Popen`` call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    import pytest

# The gateway supervisor now lives in the package proper
# (``mahavishnu.bifrost.gateway``) rather than ``scripts/bifrost-gateway.py``,
# so a normal import replaces the old importlib-by-path dance.
from mahavishnu.bifrost import gateway as bifrost_gateway

# ---------------------------------------------------------------------------
# wrap_with_line_buffering
# ---------------------------------------------------------------------------


def test_wraps_with_stdbuf_when_available() -> None:
    """``stdbuf -oL -eL`` is prepended when stdbuf is on PATH."""
    with patch("shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/stdbuf"
        result = bifrost_gateway.wrap_with_line_buffering(["node", "bin.js"])

    assert result == ["stdbuf", "-oL", "-eL", "node", "bin.js"]


def test_passthrough_when_stdbuf_missing(capsys: pytest.CaptureFixture[str]) -> None:
    """The bare command is returned when stdbuf is not on PATH.

    A stderr warning is emitted so operators can see the line-
    buffering fallback is in effect (and know to install coreutils
    on macOS). The e2e test still works — within the 15s window
    the test already documents — just with potentially longer
    bifrost.log emission latency.
    """
    with patch("shutil.which") as mock_which:
        mock_which.return_value = None
        result = bifrost_gateway.wrap_with_line_buffering(["node", "bin.js"])

    assert result == ["node", "bin.js"]

    # Operator-facing warning on stderr.
    captured = capsys.readouterr()
    assert "stdbuf" in captured.err
    assert "block-buffering" in captured.err or "coreutils" in captured.err


def test_wraps_preserves_command_args() -> None:
    """All command args are preserved after the stdbuf prefix.

    Pins the *cmd order so the gateway flags (``-host``, ``-port``,
    etc.) still reach the Node binary in the same order.
    """
    with patch("shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/stdbuf"
        result = bifrost_gateway.wrap_with_line_buffering(
            ["npx", "-y", "@maximhq/bifrost", "-host", "127.0.0.1", "-port", "8471"]
        )

    assert result == [
        "stdbuf",
        "-oL",
        "-eL",
        "npx",
        "-y",
        "@maximhq/bifrost",
        "-host",
        "127.0.0.1",
        "-port",
        "8471",
    ]


def test_wraps_empty_command() -> None:
    """Empty command list returns just the stdbuf prefix (defensive)."""
    with patch("shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/stdbuf"
        result = bifrost_gateway.wrap_with_line_buffering([])

    assert result == ["stdbuf", "-oL", "-eL"]
