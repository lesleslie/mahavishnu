"""Unit tests asserting the removal of dead code in the Session-Buddy
integration layer.

Two pre-existing dead paths are pinned here so a future refactor cannot
silently regress them:

1. ``mahavishnu.session_buddy.integration._send_code_context_to_session_buddy``
   was a stub that built a ``ProjectMessage`` and logged it — it never
   pushed to Session-Buddy. The real push is in
   ``mahavishnu.core.code_index.indexer._upsert_to_session_buddy`` which
   already does the full MCP JSON-RPC 2.0 ``tools/call`` against
   ``store_code_graph_from_mahavishnu``. The stub is dead and should be
   removed so future readers don't follow it.

2. ``mahavishnu.mcp.tools.session_buddy_tools.index_code_graph`` (and
   its sibling tools) gated on ``getattr(server, "app", None)`` returning
   a MahavishnuApp instance. In production the FastMCP server never has
   ``.app`` set, so every call returned
   ``{"status": "error", "error": "App instance not available in server context"}``.
   The tool should delegate to the real ``indexer.index_repo`` path so
   the MCP surface is no longer permanently broken.

Both tests target the public contract: the dead code is gone AND the
MCP tool returns the indexer's real result without requiring an
injected ``app``.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools.session_buddy_tools import register_session_buddy_tools

pytestmark = pytest.mark.unit


# =============================================================================
# Stubs (mirroring test_mcp_session_buddy_tools._StubMCP, inlined so this
# test file is self-contained and a future move of the helper does not
# silently break this module)
# =============================================================================


class _StubMCP:
    """Minimal FastMCP stand-in with no ``.app`` attribute (production shape)."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _run(coro):
    return asyncio.run(coro)


# =============================================================================
# Tests
# =============================================================================


class TestDeadStubsRemoved:
    """The pre-existing dead stubs in the integration module must be gone."""

    def test_session_buddy_integration_class_no_longer_exposes_send_code_context_to_session_buddy(self):
        """``_send_code_context_to_session_buddy`` is a stub method on
        ``SessionBuddyIntegration`` that built a ``ProjectMessage`` and
        logged it. The real cross-repo push lives in
        ``mahavishnu.core.code_index.indexer._upsert_to_session_buddy``. The
        stub must be removed so future maintainers do not follow a broken
        trail.
        """
        from mahavishnu.session_buddy.integration import SessionBuddyIntegration

        assert not hasattr(SessionBuddyIntegration, "_send_code_context_to_session_buddy"), (
            "_send_code_context_to_session_buddy was a stub that never actually "
            "pushed to Session-Buddy. The real push is in core.code_index.indexer. "
            "Remove the stub."
        )

    def test_session_buddy_integration_class_no_longer_exposes_index_documentation_in_session_buddy(self):
        """``_index_documentation_in_session_buddy`` was the documentation-side
        twin of the code-context stub — same ProjectMessage-and-log pattern,
        same dead-end. Remove it.
        """
        from mahavishnu.session_buddy.integration import SessionBuddyIntegration

        assert not hasattr(SessionBuddyIntegration, "_index_documentation_in_session_buddy"), (
            "_index_documentation_in_session_buddy was a stub. Remove it."
        )

    def test_integrate_code_graph_no_longer_calls_dead_stub(self):
        """``SessionBuddyIntegration.integrate_code_graph`` previously called
        ``self._send_code_context_to_session_buddy`` at the end of its
        happy-path body. After the stub is removed the method body must
        not reference it (it would raise ``AttributeError`` at call time).
        """
        from mahavishnu.session_buddy.integration import SessionBuddyIntegration

        source = inspect.getsource(SessionBuddyIntegration.integrate_code_graph)
        assert "_send_code_context_to_session_buddy" not in source, (
            "integrate_code_graph still references the dead stub. Remove the call."
        )


class TestIndexCodeGraphMcpToolDelegatesToIndexer:
    """``mcp__mahavishnu__index_code_graph`` must call the real
    ``mahavishnu.core.code_index.indexer.index_repo`` path. The legacy
    ``getattr(server, "app", None)`` guard produced
    ``{"status": "error", "error": "App instance not available in server context"}``
    for every call because the FastMCP server never has ``.app`` set in
    production. The fix routes around that guard.
    """

    def test_index_code_graph_returns_indexer_result_without_app(self):
        """The MCP tool must work when the server has no ``.app`` attribute
        (which is always the case in production). It should call
        ``indexer.index_repo`` and return the resulting ``IndexWorkItem``.
        """
        stub = _StubMCP()  # no .app attribute
        fake_mcp_client = MagicMock()
        fake_mcp_client.call_tool = AsyncMock(return_value={"status": "ok"})
        register_session_buddy_tools(
            stub,
            session_manager=MagicMock(),
            mcp_client=fake_mcp_client,
            rbac_manager=SimpleNamespace(
                check_permission=AsyncMock(return_value=True)
            ),
        )
        tool = stub.tools["index_code_graph"]

        # ``IndexWorkItem`` is the return type of ``indexer.index_repo``.
        from mahavishnu.core.code_index.models import IndexWorkItem

        expected = IndexWorkItem(
            repo_path="/tmp/repo",
            trigger="manual",
            files_changed=[],
            status="complete",
        )

        with patch(
            "mahavishnu.core.code_index.indexer.index_repo",
            return_value=expected,
        ) as mock_index:
            result = _run(tool(project_path="/tmp/repo", user_id="test-user"))

        assert result["status"] == "success", (
            f"index_code_graph should succeed when delegating to indexer; got {result!r}"
        )
        assert mock_index.called, (
            "index_code_graph must call mahavishnu.core.code_index.indexer.index_repo"
        )
        # The legacy guard string must NOT appear in the result.
        assert "App instance not available" not in str(result), (
            "Legacy 'App instance not available' guard must be removed; the tool "
            "should delegate to the indexer, not return an error."
        )

    def test_index_code_graph_no_longer_imports_session_buddy_manager(self):
        """The legacy implementation imported
        ``mahavishnu.session_buddy.integration.SessionBuddyManager`` and
        required an injected ``app``. After the fix the tool should
        delegate to the indexer, not the dead integration layer.

        Note: the tool function is a closure inside
        ``register_session_buddy_tools`` — it does not live at module
        level. We capture the registered tool from the stub's ``tools``
        dict and inspect its source that way.
        """
        stub = _StubMCP()
        register_session_buddy_tools(
            stub,
            session_manager=MagicMock(),
            mcp_client=MagicMock(),
            rbac_manager=SimpleNamespace(
                check_permission=AsyncMock(return_value=True)
            ),
        )
        tool = stub.tools["index_code_graph"]
        source = inspect.getsource(tool)
        # The legacy import-and-instantiate pattern is what produced the
        # broken guard. After the fix, the function body should not
        # reference SessionBuddyManager (or SessionBuddyIntegration) at all.
        assert "SessionBuddyManager" not in source, (
            "index_code_graph still references the dead SessionBuddyManager path. "
            "Route to indexer.index_repo instead."
        )
        assert "SessionBuddyIntegration" not in source, (
            "index_code_graph still references the dead SessionBuddyIntegration. "
            "Route to indexer.index_repo instead."
        )
