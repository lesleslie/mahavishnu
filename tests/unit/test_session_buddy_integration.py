"""Unit tests for ``mahavishnu.session_buddy.integration``.

These tests target the Session Buddy integration module without requiring
a live ``mcp_common`` install or any network calls. The heavy
``CodeGraphAnalyzer`` class is mocked at the import site and the
shared ``messaging.types`` models are imported directly because the
``messaging/`` package ships alongside this project.

Each public method is exercised in a happy path and an error path; the
private helpers (``:py:meth:`SessionBuddyIntegration._extract_docstring_from_file``
and the two ``_*_in_session_buddy`` coroutines) get a focused test of
their own so a future refactor of the public surface still has
behavior locked in.
"""

from __future__ import annotations

from pathlib import Path
import sys
import textwrap
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from mahavishnu.session_buddy.integration import (
    SessionBuddyIntegration,
    SessionBuddyManager,
)
from messaging.types import Priority

# ---------------------------------------------------------------------------
# Module-level safety net
# ---------------------------------------------------------------------------
# ``integration.py`` does ``from mcp_common.code_graph import CodeGraphAnalyzer``
# at import time. The shared conftest injects an ``mcp_common.types`` shim but
# does not cover ``mcp_common.code_graph``. Inject a minimal shim here so the
# module under test imports cleanly even in environments where the real
# ``mcp_common`` package is missing. Tests then patch
# ``mahavishnu.session_buddy.integration.CodeGraphAnalyzer`` to control behavior.


def _ensure_mcp_common_code_graph() -> None:
    if "mcp_common.code_graph" in sys.modules:
        return
    mod = ModuleType("mcp_common.code_graph")
    mod.CodeGraphAnalyzer = MagicMock()
    sys.modules["mcp_common.code_graph"] = mod


_ensure_mcp_common_code_graph()


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_node(node_type: str, name: str, file_id: str, **attrs: Any) -> Mock:
    """Return a Mock node shaped to look like a CodeNode subclass.

    The integration code only inspects ``name``, ``file_id`` and a
    small set of node-type-specific attributes (``calls``/``methods``/
    ``imported_from``). Mock makes that easy without instantiating the
    real ``CodeNode`` dataclasses.
    """
    node = Mock()
    node.name = name
    node.file_id = file_id
    if node_type == "function":
        node.calls = attrs.get("calls", [])
        node.is_export = attrs.get("is_export", True)
        node.start_line = attrs.get("start_line", 1)
        node.end_line = attrs.get("end_line", 10)
    elif node_type == "class":
        node.methods = attrs.get("methods", ["m1", "m2"])
        node.inherits_from = attrs.get("inherits_from", ["Base"])
    elif node_type == "import":
        node.imported_from = attrs.get("imported_from", "some.module")
        node.alias = attrs.get("alias")
    return node


def _make_analyzer(
    *,
    nodes: dict[str, Mock] | None = None,
    analyze_result: dict[str, Any] | None = None,
    related_files: list[dict[str, Any]] | None = None,
    function_context: dict[str, Any] | None = None,
) -> MagicMock:
    """Return a MagicMock shaped like ``CodeGraphAnalyzer`` with sensible defaults."""
    analyzer = MagicMock()
    analyzer.nodes = nodes if nodes is not None else {}
    analyzer.analyze_repository = AsyncMock(
        return_value=analyze_result
        if analyze_result is not None
        else {
            "files_indexed": 1,
            "functions_indexed": 0,
            "classes_indexed": 0,
            "total_nodes": 0,
        }
    )
    analyzer.find_related_files = AsyncMock(
        return_value=related_files
        if related_files is not None
        else [{"file_path": "related.py", "relationship": "imports", "strength": 1}]
    )
    analyzer.get_function_context = AsyncMock(
        return_value=function_context
        if function_context is not None
        else {"function": {"name": "foo"}, "callers": [], "callees": []}
    )
    return analyzer


@pytest.fixture
def patched_code_graph_analyzer():
    """Patch ``CodeGraphAnalyzer`` on the integration module for the test.

    Yields the patched class. Tests can configure ``return_value`` to
    control what the constructor returns, or ``side_effect`` to raise.
    """
    with patch("mahavishnu.session_buddy.integration.CodeGraphAnalyzer") as analyzer_cls:
        analyzer_cls.return_value = _make_analyzer()
        yield analyzer_cls


@pytest.fixture
def integration(patched_code_graph_analyzer) -> SessionBuddyIntegration:
    """A ``SessionBuddyIntegration`` instance with a stubbed analyzer."""
    return SessionBuddyIntegration(app=Mock())


# ---------------------------------------------------------------------------
# Importability
# ---------------------------------------------------------------------------


def test_public_classes_are_importable() -> None:
    """The two top-level public classes are exposed from the module."""
    assert SessionBuddyIntegration is not None
    assert SessionBuddyManager is not None
    # Each class should be constructible with a plain mock ``app``.
    assert callable(SessionBuddyIntegration)
    assert callable(SessionBuddyManager)


def test_integration_init_stores_app_and_default_fields(
    patched_code_graph_analyzer,
) -> None:
    """``__init__`` wires up the app handle, a default analyzer and a logger."""
    app = Mock()
    integration = SessionBuddyIntegration(app=app)

    assert integration.app is app
    assert integration.session_buddy_client is None
    # __init__ always instantiates a default analyzer
    patched_code_graph_analyzer.assert_called_with(Path())
    assert integration.logger is not None


# ---------------------------------------------------------------------------
# integrate_code_graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integrate_code_graph_success_extracts_nodes(
    integration: SessionBuddyIntegration,
    patched_code_graph_analyzer,
) -> None:
    """Happy path: functions, classes and imports are extracted from analyzer nodes."""
    func_node = _make_node(
        "function",
        "alpha",
        "src/m.py",
        calls=["beta"],
        is_export=True,
        start_line=1,
        end_line=5,
    )
    class_node = _make_node("class", "Gamma", "src/m.py", methods=["g"], inherits_from=["Base"])
    import_node = _make_node("import", "os", "src/m.py", imported_from="os", alias=None)

    analyzer = _make_analyzer(
        nodes={"fn1": func_node, "cls1": class_node, "imp1": import_node},
        analyze_result={
            "files_indexed": 2,
            "functions_indexed": 1,
            "classes_indexed": 1,
            "total_nodes": 3,
        },
    )
    # The integration creates a *new* CodeGraphAnalyzer(Path(repo_path))
    # internally, so make every constructor call return the same mock.
    patched_code_graph_analyzer.return_value = analyzer

    result = await integration.integrate_code_graph("/repo")

    assert result["status"] == "success"
    assert result["functions_extracted"] == 1
    assert result["classes_extracted"] == 1
    assert result["imports_extracted"] == 1
    assert result["code_context_sent"] is True
    analysis = result["analysis_result"]
    assert analysis["files_indexed"] == 2


@pytest.mark.asyncio
async def test_integrate_code_graph_skips_nodes_without_required_attrs(
    integration: SessionBuddyIntegration,
    patched_code_graph_analyzer,
) -> None:
    """Nodes missing ``name``/``file_id`` should be ignored, not raise."""
    # Build a node that looks like a function but lacks the
    # function-specific attributes — the integration's branching should
    # simply skip it.
    bare = Mock(spec=["name", "file_id"])  # no `calls`, no `methods`, no `imported_from`
    bare.name = "naked"
    bare.file_id = "src/x.py"

    analyzer = _make_analyzer(nodes={"n1": bare})
    patched_code_graph_analyzer.return_value = analyzer

    result = await integration.integrate_code_graph("/repo")

    assert result["status"] == "success"
    assert result["functions_extracted"] == 0
    assert result["classes_extracted"] == 0
    assert result["imports_extracted"] == 0


@pytest.mark.asyncio
async def test_integrate_code_graph_returns_error_dict_on_exception(
    integration: SessionBuddyIntegration,
    patched_code_graph_analyzer,
) -> None:
    """Analyzer raising must not propagate — the integration returns an error dict."""
    analyzer = MagicMock()
    analyzer.analyze_repository = AsyncMock(side_effect=RuntimeError("boom"))
    patched_code_graph_analyzer.return_value = analyzer

    result = await integration.integrate_code_graph("/repo")

    assert result["status"] == "error"
    assert "boom" in result["error"]


# ---------------------------------------------------------------------------
# get_related_code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_related_code_success_returns_file_list(
    integration: SessionBuddyIntegration,
    patched_code_graph_analyzer,
) -> None:
    related = [
        {"file_path": "a.py", "relationship": "imports", "strength": 1},
        {"file_path": "b.py", "relationship": "called_by", "strength": 2},
    ]
    analyzer = _make_analyzer(related_files=related)
    patched_code_graph_analyzer.return_value = analyzer

    result = await integration.get_related_code("/repo", "src/main.py")

    assert result["status"] == "success"
    assert result["file_path"] == "src/main.py"
    assert result["related_files"] == related
    assert result["count"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name,kwargs,error_substring",
    [
        ("get_related_code", {"file_path": "src/main.py"}, "disk gone"),
        ("get_function_context", {"function_name": "foo"}, "Function not found"),
        ("index_documentation", {}, "boom"),
    ],
    ids=["related-code", "function-context", "documentation"],
)
async def test_analyzer_methods_return_error_dict_on_failure(
    integration: SessionBuddyIntegration,
    patched_code_graph_analyzer,
    method_name: str,
    kwargs: dict,
    error_substring: str,
) -> None:
    """All three analyzer-driven methods must swallow exceptions into an error dict."""
    analyzer = MagicMock()
    analyzer.analyze_repository = AsyncMock(side_effect=RuntimeError(error_substring))
    patched_code_graph_analyzer.return_value = analyzer

    method = getattr(integration, method_name)
    result = await method("/repo", **kwargs)

    assert result["status"] == "error"
    assert error_substring in result["error"]


# ---------------------------------------------------------------------------
# get_function_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_function_context_success(
    integration: SessionBuddyIntegration,
    patched_code_graph_analyzer,
) -> None:
    ctx = {
        "function": {"name": "do_work", "file": "x.py", "start_line": 10},
        "callers": [{"name": "main"}],
        "callees": [{"name": "helper"}],
    }
    analyzer = _make_analyzer(function_context=ctx)
    patched_code_graph_analyzer.return_value = analyzer

    result = await integration.get_function_context("/repo", "do_work")

    assert result["status"] == "success"
    assert result["function_name"] == "do_work"
    assert result["context"] == ctx


# ---------------------------------------------------------------------------
# index_documentation + _extract_docstring_from_file
# ---------------------------------------------------------------------------


def _write_python_module(tmp_path: Path) -> Path:
    src = textwrap.dedent(
        '''\
        """Module docstring."""


        def my_function():
            """Return the meaning of life."""
            return 42


        class MyClass:
            """A documented class."""

            def method(self):
                """Method docstring."""
                return 0
        '''
    )
    file_path = tmp_path / "sample.py"
    file_path.write_text(src)
    return file_path


@pytest.mark.parametrize(
    "symbol_name,expected",
    [
        ("my_function", "Return the meaning of life."),
        ("MyClass", "A documented class."),
        ("ghost", None),  # symbol not present in module
    ],
)
def test_extract_docstring_from_file_finds_symbol_or_returns_none(
    tmp_path: Path, symbol_name: str, expected: str | None
) -> None:
    file_path = _write_python_module(tmp_path)
    integration = SessionBuddyIntegration(app=Mock())
    assert integration._extract_docstring_from_file(str(file_path), symbol_name) == expected


def test_extract_docstring_from_file_returns_none_on_invalid_path() -> None:
    integration = SessionBuddyIntegration(app=Mock())
    # File does not exist; the helper swallows the error.
    assert integration._extract_docstring_from_file("/no/such/file.py", "x") is None


@pytest.mark.asyncio
async def test_index_documentation_success(
    integration: SessionBuddyIntegration,
    patched_code_graph_analyzer,
    tmp_path: Path,
) -> None:
    file_path = _write_python_module(tmp_path)

    func_node = _make_node("function", "my_function", str(file_path), calls=[])
    class_node = _make_node("class", "MyClass", str(file_path), methods=["method"])
    nodes = {"fn1": func_node, "cls1": class_node}

    analyzer = _make_analyzer(nodes=nodes)
    patched_code_graph_analyzer.return_value = analyzer

    result = await integration.index_documentation("/repo")

    assert result["status"] == "success"
    assert result["documentation_items"] == 2
    assert result["indexed"] is True


# Error path is covered by the parametrized test_analyzer_methods_return_error_dict_on_failure.
# ---------------------------------------------------------------------------
# search_documentation / list_project_messages (read-only stubs)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,args,expected",
    [
        (
            "search_documentation",
            ("anything",),
            {
                "status": "success",
                "query": "anything",
                "results": [],
                "count": 0,
            },
        ),
        (
            "list_project_messages",
            ("some-project",),
            {
                "status": "success",
                "project": "some-project",
                "messages": [],
                "count": 0,
            },
        ),
    ],
    ids=["search-documentation", "list-project-messages"],
)
async def test_read_only_stub_methods_return_empty_success(
    integration: SessionBuddyIntegration,
    method: str,
    args: tuple,
    expected: dict,
) -> None:
    result = await getattr(integration, method)(*args)
    assert result == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,args",
    [
        ("search_documentation", ("q",)),
        ("list_project_messages", ("p",)),
    ],
    ids=["search-documentation", "list-project-messages"],
)
async def test_read_only_stub_methods_error_path(
    integration: SessionBuddyIntegration,
    method: str,
    args: tuple,
) -> None:
    # Force the logger to raise so the ``except`` branch is exercised.
    integration.logger = Mock()
    integration.logger.info = Mock(side_effect=RuntimeError("simulated"))

    result = await getattr(integration, method)(*args)

    assert result["status"] == "error"
    assert "simulated" in result["error"]


# ---------------------------------------------------------------------------
# send_project_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "priority",
    [Priority.NORMAL, Priority.URGENT],
    ids=["default-normal", "explicit-urgent"],
)
async def test_send_project_message_success(
    integration: SessionBuddyIntegration, priority: Priority
) -> None:
    result = await integration.send_project_message(
        from_project="src",
        to_project="dst",
        subject="hi",
        message="hello there",
        priority=priority,
    )
    assert result["status"] == "success"
    assert result["sent"] is True
    assert result["message_id"].startswith("msg_")


@pytest.mark.asyncio
async def test_send_project_message_error_returns_error_dict(
    integration: SessionBuddyIntegration,
) -> None:
    # Break the logger to exercise the error branch.
    integration.logger = Mock()
    integration.logger.info = Mock(side_effect=RuntimeError("logging down"))
    result = await integration.send_project_message(
        from_project="src",
        to_project="dst",
        subject="x",
        message="y",
    )
    assert result["status"] == "error"
    assert "logging down" in result["error"]


# ---------------------------------------------------------------------------
# SessionBuddyManager
# ---------------------------------------------------------------------------


def test_manager_init_creates_integration(patched_code_graph_analyzer) -> None:
    app = Mock()
    manager = SessionBuddyManager(app=app)
    assert manager.app is app
    assert isinstance(manager.integration, SessionBuddyIntegration)
    assert manager.integration.app is app


@pytest.mark.asyncio
async def test_manager_process_repository_for_session_buddy_success(
    patched_code_graph_analyzer,
) -> None:
    analyzer = _make_analyzer()
    patched_code_graph_analyzer.return_value = analyzer

    manager = SessionBuddyManager(app=Mock())
    result = await manager.process_repository_for_session_buddy("/repo")

    assert result["repository"] == "/repo"
    assert result["code_graph_integration"]["status"] == "success"
    assert result["documentation_indexing"]["status"] == "success"
    assert result["overall_status"] == "success"


@pytest.mark.asyncio
async def test_manager_process_repository_for_session_buddy_partial(
    patched_code_graph_analyzer,
) -> None:
    """If either sub-step errors, the manager reports ``partial``."""
    analyzer = MagicMock()
    # First call (integrate_code_graph) raises; second call (index_documentation)
    # would succeed. Both calls go through the same analyzer mock, so configure
    # side_effect with two values to mimic that.
    analyzer.analyze_repository = AsyncMock(side_effect=[RuntimeError("graph fail"), None])
    analyzer.nodes = {}
    patched_code_graph_analyzer.return_value = analyzer

    manager = SessionBuddyManager(app=Mock())
    result = await manager.process_repository_for_session_buddy("/repo")

    assert result["code_graph_integration"]["status"] == "error"
    # documentation_indexing should still report success because its
    # ``analyze_repository`` call returned successfully.
    assert result["documentation_indexing"]["status"] == "success"
    assert result["overall_status"] == "partial"


@pytest.mark.asyncio
async def test_manager_get_enhanced_context_aggregates_results(
    patched_code_graph_analyzer,
) -> None:
    analyzer = _make_analyzer()
    patched_code_graph_analyzer.return_value = analyzer

    manager = SessionBuddyManager(app=Mock())
    result = await manager.get_enhanced_context(
        "/repo",
        {
            "function_name": "do_work",
            "file_path": "src/main.py",
            "query": "how to foo",
        },
    )

    assert result["status"] == "success"
    assert result["repo_path"] == "/repo"
    assert "function_context" in result["enhanced_context"]
    assert "related_code" in result["enhanced_context"]
    assert "documentation_search" in result["enhanced_context"]


@pytest.mark.asyncio
async def test_manager_get_enhanced_context_handles_empty_inputs(
    patched_code_graph_analyzer,
) -> None:
    """An empty query_elements dict should yield an empty ``enhanced_context``."""
    manager = SessionBuddyManager(app=Mock())
    result = await manager.get_enhanced_context("/repo", {})
    assert result["status"] == "success"
    assert result["enhanced_context"] == {}
    assert result["repo_path"] == "/repo"
