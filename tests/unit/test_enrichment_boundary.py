"""Boundary test for the tool-call enrichment layer.

REQ-TSQ-002 (per docs/plans/2026-09-26-tool-surface-quality.md): enrichment lives
in a local subclass of FastMCPOpenTelemetryMiddleware; mcp_common is untouched.

This test enforces the boundary at three levels:
  (a) `mcp_common/server/telemetry.py` AST/sha256 unchanged across the diff.
  (b) The subclass overrides `on_message` (the FastMCP middleware hook).
  (c) The subclass no-ops when `context.method != "tools/call"`.

When Phase 1 ships (the `ToolCallEnrichmentMiddleware` class at
`mahavishnu/mcp/tool_call_middleware.py`), the `pytest.importorskip` calls
below start passing and the tests become real assertion gates.
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Path to mcp_common/server/telemetry.py — adjust if the submodule location differs.
MCP_COMMON_TELEMETRY_PATH = Path(
    "/Users/les/Projects/mcp-common/mcp_common/server/telemetry.py"
)


def _sha256_of(path: Path) -> str:
    """Compute sha256 of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_mcp_common_telemetry_unchanged() -> None:
    """REQ-TSQ-002: mcp_common source must not be modified by this plan.

    Records the sha256 of mcp_common/server/telemetry.py before Phase 1 lands.
    Once Phase 1 lands, this assertion is the gate that catches a
    local-subclass boundary violation (any edit to mcp_common breaks it).
    """
    if not MCP_COMMON_TELEMETRY_PATH.exists():
        pytest.skip(f"{MCP_COMMON_TELEMETRY_PATH} not present in this checkout")

    # Recorded pre-Phase-1 sha256 of mcp_common/server/telemetry.py.
    # If this hash changes after Phase 1 lands, the local-subclass boundary
    # was violated (the plan added a new middleware by SUBCLASSING, not by
    # modifying mcp_common).
    expected_hash = _sha256_of(MCP_COMMON_TELEMETRY_PATH)

    # Sanity check: the file is non-empty and parses as Python.
    assert len(expected_hash) == 64  # sha256 hex digest length
    source = MCP_COMMON_TELEMETRY_PATH.read_text()
    assert len(source) > 0
    compile(source, str(MCP_COMMON_TELEMETRY_PATH), "exec")

    # Pinned 2026-09-27 (Phase 1 implementation day). If this hash changes
    # after this commit lands, the local-subclass boundary was violated
    # (the plan added a new middleware by SUBCLASSING, not by modifying
    # mcp_common). Update this pin only after an explicit cross-repo
    # coordination conversation + reviewer sign-off.
    pinned_pre_phase1_hash = "66567d5462cde38a18529c77cd4ad458aaeec5c17854d974bc13b1a6ce458b8a"
    assert expected_hash == pinned_pre_phase1_hash, (
        f"mcp_common/server/telemetry.py sha256 changed "
        f"({pinned_pre_phase1_hash[:12]}... -> {expected_hash[:12]}...); "
        "Phase 1 added a new middleware by SUBCLASSING, not by modifying "
        "mcp_common. If this change is intentional, update the pin and "
        "document the cross-repo coordination in the plan."
    )


def test_enrichment_subclass_overrides_on_message() -> None:
    """REQ-TSQ-002: enrichment lives in a subclass that overrides on_message.

    Verifies the structural shape: the subclass declares `on_message`
    itself (not inherits the parent default) and the override signature
    matches the FastMCP middleware contract.
    """
    pytest.importorskip("mahavishnu.mcp.tool_call_middleware")
    from mahavishnu.mcp.tool_call_middleware import ToolCallEnrichmentMiddleware

    # Subclass must override on_message (own attribute, not inherited).
    assert "on_message" in ToolCallEnrichmentMiddleware.__dict__, (
        "ToolCallEnrichmentMiddleware must override on_message, "
        "not inherit it from FastMCPOpenTelemetryMiddleware"
    )

    # Override signature must match the parent (FastMCP middleware contract).
    parent_class = ToolCallEnrichmentMiddleware.__bases__[0]
    parent_on_message = inspect.signature(parent_class.on_message)
    child_on_message = inspect.signature(ToolCallEnrichmentMiddleware.on_message)
    assert parent_on_message.parameters.keys() == child_on_message.parameters.keys()


@pytest.mark.asyncio
async def test_enrichment_noop_for_non_tool_messages() -> None:
    """REQ-TSQ-002: subclass no-ops when context.method != 'tools/call'.

    Verifies that the enrichment gate on `context.method == "tools/call"`
    prevents enricher attributes from being set for resources/read,
    prompts/get, notifications, etc. — the hook is `on_message` (fires for
    every FastMCP message), but enrichment is gated to tools/call only.
    """
    pytest.importorskip("mahavishnu.mcp.tool_call_middleware")
    from mahavishnu.mcp.tool_call_middleware import ToolCallEnrichmentMiddleware

    # Build a mock context whose method is NOT "tools/call".
    captured_span_attrs: dict = {}

    class FakeSpan:
        def set_attribute(self, key: str, value: object) -> None:
            captured_span_attrs[key] = value

    ctx = MagicMock()
    ctx.method = "resources/read"
    ctx.active_span = FakeSpan()

    call_next = AsyncMock(return_value=None)
    middleware = ToolCallEnrichmentMiddleware(service_name="unit-test")

    await middleware.on_message(ctx, call_next)

    # call_next must be invoked exactly once (middleware contract).
    call_next.assert_awaited_once()
    # No enrichment attributes should have been set for non-tool messages.
    assert captured_span_attrs == {}, (
        "Enrichment must no-op for non-tool messages; "
        f"unexpected attributes: {captured_span_attrs}"
    )
