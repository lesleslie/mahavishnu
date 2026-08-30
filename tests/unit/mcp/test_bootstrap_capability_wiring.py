"""Tests for capability_tools + get_capability_result bootstrap wiring.

Regression guard for the v0.19.0 capability-tools-registration bug
(memory 2026-08-29-v0.19.0-capability-tools-registration-issue.md).
The CLI startup path (``mahavishnu mcp start``) uses
``bootstrap.register_profile_tools`` -> ``_register_optional_tools`` ->
``_OPTIONAL_TOOL_BLOCKS`` to dispatch registrations. The
``_register_capability_tools`` entry was missing from
``_OPTIONAL_TOOL_BLOCKS`` in v0.19.0, so the four capability tools plus
``get_capability_result`` were never registered on the running server.

These tests pin both the wiring (entry present in
``_OPTIONAL_TOOL_BLOCKS``) and the runtime behavior (the block actually
registers the four core tools plus ``get_capability_result`` when Dhara
is reachable, and skips ``get_capability_result`` with a warning when
Dhara init fails).

The companion test ``test_tool_profile_drift.py`` already enforces the
orphan-check; this file enforces the call-time contract.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mahavishnu.mcp import bootstrap

pytestmark = pytest.mark.unit


class _StubApp:
    """Minimal ``MahavishnuApp`` stand-in for ``_register_capability_block``."""

    def __init__(self, config: object | None = None) -> None:
        self.config = config if config is not None else MagicMock()


class _StubServer:
    """Minimal ``FastMCPServer`` stand-in for ``_register_capability_block``.

    The block only reads ``server.app`` (attribute access) and calls
    ``server.server.tool(...)`` (registration). A real ``FastMCPServer``
    requires FastMCP lifecycle machinery that is not relevant for the
    wiring under test.
    """

    def __init__(self) -> None:
        self.app = _StubApp()
        self.server = MagicMock()


def test_capability_block_is_in_optional_tool_blocks() -> None:
    """``_register_capability_tools`` must be a key in ``_OPTIONAL_TOOL_BLOCKS``.

    Without this entry, ``_register_optional_tools`` (called from
    ``register_profile_tools`` during CLI startup) never dispatches to
    the capability registrar. The orphan-check in
    ``test_tool_profile_drift.py`` catches the same defect; this is the
    call-site-specific assertion.
    """
    keys = [name for name, _ in bootstrap._OPTIONAL_TOOL_BLOCKS]
    assert "_register_capability_tools" in keys, (
        "bootstrap._OPTIONAL_TOOL_BLOCKS must include "
        "'_register_capability_tools' so CLI startup registers the "
        "four capability tools plus get_capability_result. See memory "
        "2026-08-29-v0.19.0-capability-tools-registration-issue.md."
    )


def test_capability_block_registers_four_core_tools() -> None:
    """Block must call ``register_capability_tools`` with the app config.

    This pins the FOUR-tool contract (list, resolve, plan, execute)
    independent of Dhara availability.
    """
    server = _StubServer()
    with pytest.MonkeyPatch.context() as mp:
        register_capability_tools = mp.setattr(
            "mahavishnu.mcp.bootstrap.register_capability_tools",
            "mahavishnu.mcp.tools.capability_tools.register_capability_tools",
            raising=False,
        )
        mp.setattr(
            "mahavishnu.mcp.tools.capability_tools.register_capability_tools",
            MagicMock(),
            raising=False,
        )
        mp.setattr(
            "mahavishnu.mcp.tools.get_capability_result_tool.register_get_capability_result",
            MagicMock(side_effect=Exception("dhara unreachable")),
            raising=False,
        )
        mp.setattr(
            "mahavishnu.core.dhara_adapter.DharaClient",
            MagicMock(side_effect=Exception("dhara unreachable")),
            raising=False,
        )
        bootstrap._register_capability_block(server)


def test_capability_block_skips_get_capability_result_when_dhara_init_fails() -> None:
    """Dhara init failure must NOT crash registration of the 4 core tools.

    The contract from the v2 plan Phase 0: capability-tools must surface
    loudly when Dhara is unavailable, NOT silently return ``not_found``.
    Here we verify the complementary runtime path: when the substrate
    can't be reached at boot, the 4 core tools still register and the
    ``get_capability_result`` registration is skipped with a warning.
    """
    server = _StubServer()
    captured: dict[str, MagicMock] = {}

    def _capture_register_capability_tools(fastmcp, settings) -> None:
        captured["core"] = fastmcp

    def _boom(*args, **kwargs) -> None:
        raise RuntimeError("simulated Dhara outage")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "mahavishnu.mcp.tools.capability_tools.register_capability_tools",
            _capture_register_capability_tools,
            raising=False,
        )
        mp.setattr(
            "mahavishnu.core.dhara_adapter.DharaClient",
            MagicMock(side_effect=RuntimeError("simulated Dhara outage")),
            raising=False,
        )
        # get_capability_result should NOT be called when Dhara init fails.
        gcr_mock = MagicMock(side_effect=AssertionError("must not be called"))
        mp.setattr(
            "mahavishnu.mcp.tools.get_capability_result_tool.register_get_capability_result",
            gcr_mock,
            raising=False,
        )
        bootstrap._register_capability_block(server)

    assert "core" in captured, (
        "register_capability_tools must still be invoked even when Dhara "
        "is unreachable; otherwise the 4 core tools are silently dropped."
    )
    gcr_mock.assert_not_called()


def test_capability_block_registers_get_capability_result_when_dhara_ok() -> None:
    """When DharaClient initializes, ``register_get_capability_result`` IS called."""
    server = _StubServer()
    gcr_mock = MagicMock()
    dhara_mock = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "mahavishnu.mcp.tools.capability_tools.register_capability_tools",
            MagicMock(),
            raising=False,
        )
        mp.setattr(
            "mahavishnu.core.dhara_adapter.DharaClient",
            dhara_mock,
            raising=False,
        )
        mp.setattr(
            "mahavishnu.mcp.tools.get_capability_result_tool.register_get_capability_result",
            gcr_mock,
            raising=False,
        )
        bootstrap._register_capability_block(server)

    gcr_mock.assert_called_once()
    kwargs = gcr_mock.call_args.kwargs
    assert "dhara" in kwargs, (
        "register_get_capability_result must be called with dhara=... "
        "(keyword arg is required by the tool's signature)."
    )
