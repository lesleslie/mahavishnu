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
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastmcp import FastMCP
from fastmcp.exceptions import ValidationError
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


def _advertised_input_schema(tool: Any) -> dict[str, Any]:
    """Return the JSON schema an MCP client validates arguments against.

    ``FunctionTool.parameters`` is FastMCP's view of the schema; the MCP
    SDK wire object carries the same payload under ``input_schema``
    (SDK v2) or ``inputSchema`` (SDK v1). We read the wire object so the
    assertion is against what a client actually receives over the
    protocol, not against the Python signature.
    """
    mcp_tool = tool.to_mcp_tool()
    schema = getattr(mcp_tool, "input_schema", None)
    if schema is None:  # MCP SDK v1 spelling
        schema = getattr(mcp_tool, "inputSchema", None)
    assert isinstance(schema, dict), "could not read the advertised input schema"
    return schema


# =============================================================================
# Tests
# =============================================================================


class TestDeadStubsRemoved:
    """The pre-existing dead stubs in the integration module must be gone."""

    def test_session_buddy_integration_class_no_longer_exposes_send_code_context_to_session_buddy(
        self,
    ):
        """``_send_code_context_to_session_buddy`` is a stub method on
        ``SessionBuddyIntegration`` that built a ``ProjectMessage`` and
        logged it. The real cross-repo push lives in
        ``mahavishnu.core.code_index.indexer._upsert_to_session_buddy``. The
        stub must be removed so future maintainers do not follow a broken
        trail.
        """
        from mahavishnu.session_buddy.integration import SessionBuddyIntegration

        assert not hasattr(
            SessionBuddyIntegration, "_send_code_context_to_session_buddy"
        ), (
            "_send_code_context_to_session_buddy was a stub that never actually "
            "pushed to Session-Buddy. The real push is in core.code_index.indexer. "
            "Remove the stub."
        )

    def test_session_buddy_integration_class_no_longer_exposes_index_documentation_in_session_buddy(
        self,
    ):
        """``_index_documentation_in_session_buddy`` was the documentation-side
        twin of the code-context stub — same ProjectMessage-and-log pattern,
        same dead-end. Remove it.
        """
        from mahavishnu.session_buddy.integration import SessionBuddyIntegration

        assert not hasattr(
            SessionBuddyIntegration, "_index_documentation_in_session_buddy"
        ), "_index_documentation_in_session_buddy was a stub. Remove it."

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
            rbac_manager=SimpleNamespace(check_permission=AsyncMock(return_value=True)),
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
            rbac_manager=SimpleNamespace(check_permission=AsyncMock(return_value=True)),
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


class TestIndexCodeGraphSchemaDropsIncludeDocs:
    """``index_code_graph`` must not advertise the dead ``include_docs``
    parameter.

    ``include_docs`` was a no-op from its first commit: the tool body
    never read it, and it could not even be threaded through, because
    ``index_repo`` is invoked positionally as ``(project_path,
    "manual")``. The docstring that justified it was false on both
    counts — the indexer parses ``.py`` files only
    (``PARSABLE_EXTENSIONS`` in ``core/code_index/parser.py``), so
    documentation *files* are never indexed, and the deprecation
    registry (``DEPRECATED_TOOLS`` in ``mcp/tool_versions.py``) maps
    tool names to replacement tool names, carrying no parameter shape
    to be compatible with.

    The parameter has been removed. These tests pin the advertised MCP
    input schema — the schema a client validates against — so it cannot
    creep back in.
    """

    @staticmethod
    def _registered_tool() -> Any:
        """Register the Session-Buddy tools on a real FastMCP server.

        A stub cannot answer this question: only a real FastMCP server
        builds the JSON schema that is advertised to clients. The RBAC
        manager is left unset: the advertised schema comes from the tool
        signature, which the auth decorator does not change, and the
        rejection assertion below happens during argument validation —
        before the tool body (and its auth gate) ever runs.
        """
        mcp = FastMCP(name="test-index-code-graph-schema")
        register_session_buddy_tools(
            mcp,
            session_manager=MagicMock(),
            mcp_client=MagicMock(),
        )
        tools = _run(mcp.list_tools())
        return next(t for t in tools if t.name == "index_code_graph")

    def test_advertised_input_schema_does_not_expose_include_docs(self):
        """The advertised schema must not list the removed parameter."""
        schema = _advertised_input_schema(self._registered_tool())
        properties = schema.get("properties", {})

        assert "include_docs" not in properties, (
            "index_code_graph must not advertise include_docs — it has been a "
            "no-op since birth. Advertised properties: "
            f"{sorted(properties)}"
        )

    def test_advertised_input_schema_still_exposes_the_live_parameters(self):
        """Removing the dead parameter must not disturb the real ones."""
        schema = _advertised_input_schema(self._registered_tool())
        properties = schema.get("properties", {})

        assert set(properties) == {"project_path", "user_id"}, (
            "index_code_graph must advertise exactly its live parameters; "
            f"got {sorted(properties)}"
        )
        assert schema.get("required") == ["project_path"], (
            f"project_path must stay required; got {schema.get('required')!r}"
        )

    def test_client_call_carrying_include_docs_is_rejected(self):
        """The removal is real at the protocol level, not silently ignored.

        A client that still sends the old parameter must get a
        validation error rather than a silently-accepted no-op.
        """
        tool = self._registered_tool()

        with pytest.raises(ValidationError, match="include_docs"):
            _run(
                tool.run(
                    {
                        "project_path": "/tmp/repo",
                        "user_id": "test-user",
                        "include_docs": True,
                    }
                )
            )
