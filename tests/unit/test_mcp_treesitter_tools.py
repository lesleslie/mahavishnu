"""Unit tests for mahavishnu.mcp.tools.treesitter_tools.

The module decorates async functions with ``@mcp.tool()`` at registration
time. Tests use a ``_StubMCP`` to capture the tool functions, then invoke
them directly with a mocked ``TreeSitterParser`` (the lazy global
``_parser`` is reset per test).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools import treesitter_tools as tt
from mahavishnu.mcp.tools.treesitter_tools import register_treesitter_tools

pytestmark = pytest.mark.unit


# =============================================================================
# Helpers
# =============================================================================


class _StubMCP:
    """Minimal FastMCP stand-in that records decorated functions."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _run(coro):
    return asyncio.run(coro)


def _make_parse_result(
    success: bool = True,
    symbols=None,
    imports=None,
    relationships=None,
    error: str | None = None,
    from_cache: bool = False,
):
    res = MagicMock()
    res.success = success
    res.file_path = "/tmp/foo.py"
    res.language = MagicMock()
    res.language.value = "python"
    res.symbols = symbols or []
    res.imports = imports or []
    res.relationships = relationships or []
    res.parse_time_ms = 1.23
    res.from_cache = from_cache
    res.error_node_count = 0
    res.error = error
    return res


def _make_symbol(name: str = "foo", kind_value: str = "function"):
    sym = MagicMock()
    sym.name = name
    sym.kind = MagicMock()
    sym.kind.value = kind_value
    sym.line_start = 1
    sym.line_end = 10
    sym.column_start = 0
    sym.column_end = 20
    sym.signature = "def foo()"
    sym.docstring = "A docstring."
    sym.modifiers = {"public"}
    sym.parameters = [{"name": "x", "type": "int"}]
    sym.return_type = "None"
    sym.parent_context = None
    return sym


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _reset_parser():
    """The module-level _parser cache must be reset between tests."""
    tt._parser = None
    yield
    tt._parser = None


@pytest.fixture
def stub_mcp() -> _StubMCP:
    return _StubMCP()


@pytest.fixture
def fake_parser() -> MagicMock:
    parser = MagicMock(name="TreeSitterParser")
    parser.parse_file = AsyncMock(return_value=_make_parse_result())
    parser.detect_language = MagicMock(return_value=MagicMock(value="python", name="PYTHON"))
    parser.get_cache_stats = MagicMock(return_value={"hits": 5, "misses": 3, "hit_rate": 0.625})
    parser.clear_cache = MagicMock(return_value=42)
    return parser


@pytest.fixture
def registered(stub_mcp, fake_parser) -> _StubMCP:
    """Register tools and pre-populate the module-level parser cache.

    The module caches its parser in the module-level ``_parser`` global and
    ``_get_parser()`` only instantiates a real ``TreeSitterParser`` on cache
    miss. By pre-populating ``tt._parser = fake_parser`` for the duration of
    the test, every ``_get_parser()`` call from inside the tools returns the
    fake. (Using ``patch.object`` inside the registration block doesn't work
    because the patch is reverted when the ``with`` block exits, before the
    test calls the tool function.)
    """
    tt._parser = fake_parser
    register_treesitter_tools(stub_mcp)
    return stub_mcp


# =============================================================================
# treesitter_parse
# =============================================================================


class TestTreesitterParse:
    """Tests for treesitter_parse tool."""

    def test_parses_with_explicit_language(self, registered, fake_parser):
        """Explicit language is honoured when the value is in the enum."""
        tool = registered.tools["treesitter_parse"]
        result = _run(tool(file_path="/tmp/foo.py", language="python"))
        assert result["success"] is True
        assert result["file_path"] == "/tmp/foo.py"
        assert result["language"] == "python"
        assert result["from_cache"] is False

    def test_invalid_language_falls_back_to_unknown(self, registered, fake_parser):
        """Invalid language string falls back to UNKNOWN enum value."""
        tool = registered.tools["treesitter_parse"]
        result = _run(tool(file_path="/tmp/foo.py", language="klingon"))
        assert result["success"] is True
        # parse_file was called with whatever language was resolved
        fake_parser.parse_file.assert_awaited_once()

    def test_detects_language_when_unspecified(self, registered, fake_parser):
        """Without language, parser.detect_language is consulted."""
        tool = registered.tools["treesitter_parse"]
        result = _run(tool(file_path="/tmp/foo.py"))
        assert result["success"] is True
        fake_parser.detect_language.assert_called_once()
        # parse_file was awaited
        fake_parser.parse_file.assert_awaited_once()

    def test_failed_parse_reports_error(self, registered, fake_parser):
        """A failed parse surfaces the parser's error message."""
        fake_parser.parse_file = AsyncMock(
            return_value=_make_parse_result(success=False, error="parse failed")
        )
        tool = registered.tools["treesitter_parse"]
        result = _run(tool(file_path="/tmp/foo.py"))
        assert result["success"] is False
        assert result["error"] == "parse failed"

    def test_exception_in_parse_returns_error_dict(self, stub_mcp, fake_parser):
        """A raised exception in the tool body is caught and returned."""
        fake_parser.parse_file = AsyncMock(side_effect=RuntimeError("boom"))
        tt._parser = fake_parser
        register_treesitter_tools(stub_mcp)
        tool = stub_mcp.tools["treesitter_parse"]
        result = _run(tool(file_path="/tmp/foo.py"))
        assert result["success"] is False
        assert "boom" in result["error"]


# =============================================================================
# treesitter_extract_symbols
# =============================================================================


class TestTreesitterExtractSymbols:
    """Tests for treesitter_extract_symbols tool."""

    def test_no_filter_returns_all_symbols(self, registered, fake_parser):
        """Without symbol_kinds, all symbols are returned."""
        fake_parser.parse_file = AsyncMock(
            return_value=_make_parse_result(symbols=[_make_symbol("a"), _make_symbol("b")])
        )
        tool = registered.tools["treesitter_extract_symbols"]
        result = _run(tool(file_path="/tmp/foo.py"))
        assert result["success"] is True
        assert result["total_symbols"] == 2
        assert result["filtered_symbols"] == 2
        assert {s["name"] for s in result["symbols"]} == {"a", "b"}

    def test_filter_by_symbol_kinds(self, registered, fake_parser):
        """symbol_kinds limits which symbols appear in the response."""
        syms = [
            _make_symbol("a", kind_value="function"),
            _make_symbol("B", kind_value="class"),
        ]
        fake_parser.parse_file = AsyncMock(return_value=_make_parse_result(symbols=syms))
        tool = registered.tools["treesitter_extract_symbols"]
        result = _run(tool(file_path="/tmp/foo.py", symbol_kinds=["function"]))
        assert result["success"] is True
        assert result["total_symbols"] == 2
        assert result["filtered_symbols"] == 1
        assert result["symbols"][0]["name"] == "a"
        assert result["symbols"][0]["kind"] == "function"

    def test_long_docstring_truncated(self, registered, fake_parser):
        """Docstrings longer than 100 chars are truncated with ellipsis."""
        sym = _make_symbol()
        sym.docstring = "x" * 200
        fake_parser.parse_file = AsyncMock(return_value=_make_parse_result(symbols=[sym]))
        tool = registered.tools["treesitter_extract_symbols"]
        result = _run(tool(file_path="/tmp/foo.py"))
        assert result["symbols"][0]["docstring"].endswith("...")
        assert len(result["symbols"][0]["docstring"]) < 200

    def test_exception_returns_error(self, stub_mcp, fake_parser):
        fake_parser.parse_file = AsyncMock(side_effect=ValueError("nope"))
        tt._parser = fake_parser
        register_treesitter_tools(stub_mcp)
        tool = stub_mcp.tools["treesitter_extract_symbols"]
        result = _run(tool(file_path="/tmp/foo.py"))
        assert result["success"] is False
        assert "nope" in result["error"]


# =============================================================================
# treesitter_find_usages
# =============================================================================


class TestTreesitterFindUsages:
    """Tests for treesitter_find_usages tool."""

    def test_symbol_not_in_definition(self, registered, fake_parser):
        """When the symbol isn't in the definition file, return definition=None and empty usages."""
        fake_parser.parse_file = AsyncMock(return_value=_make_parse_result(symbols=[]))
        tool = registered.tools["treesitter_find_usages"]
        result = _run(tool(file_path="/tmp/foo.py", symbol_name="missing"))
        assert result["success"] is True
        assert result["definition"] is None
        assert result["usages"] == []
        assert "not found" in result["message"]

    def test_parse_failure_short_circuits(self, registered, fake_parser):
        """If the definition file fails to parse, return failure with the parse error."""
        fake_parser.parse_file = AsyncMock(
            return_value=_make_parse_result(success=False, error="bad")
        )
        tool = registered.tools["treesitter_find_usages"]
        result = _run(tool(file_path="/tmp/foo.py", symbol_name="x"))
        assert result["success"] is False
        assert "bad" in result["error"]

    def test_finds_usages_in_search_dir(self, registered, fake_parser, tmp_path):
        """When the symbol is in the definition file, usages are searched in the directory."""
        # Create a usage file
        usage_file = tmp_path / "other.py"
        usage_file.write_text("def foo():\n    pass\n# foo is also here\n")
        definition = tmp_path / "defn.py"
        definition.write_text("def foo():\n    pass\n")

        # The parse_file call returns symbols from the definition file
        fake_parser.parse_file = AsyncMock(
            return_value=_make_parse_result(symbols=[_make_symbol("foo")])
        )
        # detect_language returns python
        tool = registered.tools["treesitter_find_usages"]
        result = _run(
            tool(
                file_path=str(definition),
                symbol_name="foo",
                search_directory=str(tmp_path),
            )
        )
        assert result["success"] is True
        assert result["symbol_name"] == "foo"
        # usages should include the file we just wrote
        files = {u["file"] for u in result["usages"]}
        assert str(usage_file) in files
        # the definition file itself should NOT be in the usages
        assert str(definition) not in files

    def test_exception_returns_error(self, stub_mcp, fake_parser):
        fake_parser.parse_file = AsyncMock(side_effect=OSError("disk full"))
        tt._parser = fake_parser
        register_treesitter_tools(stub_mcp)
        tool = stub_mcp.tools["treesitter_find_usages"]
        result = _run(tool(file_path="/tmp/foo.py", symbol_name="x"))
        assert result["success"] is False


# =============================================================================
# treesitter_query
# =============================================================================


class TestTreesitterQuery:
    """Tests for treesitter_query tool."""

    def test_unknown_language_rejected(self, registered, fake_parser):
        """A language of 'unknown' short-circuits with a clear error."""
        unknown_lang = MagicMock()
        unknown_lang.value = "unknown"
        fake_parser.detect_language = MagicMock(return_value=unknown_lang)
        tool = registered.tools["treesitter_query"]
        result = _run(tool(file_path="/tmp/foo.py", query="(function_definition)"))
        assert result["success"] is False
        assert result["error"] == "Unknown language"
        assert result["matches"] == []

    def test_query_returns_placeholder_response(self, registered, fake_parser):
        """A successful parse returns a tip that custom queries need direct API access."""
        tool = registered.tools["treesitter_query"]
        result = _run(tool(file_path="/tmp/foo.py", query="(function_definition)"))
        assert result["success"] is True
        assert result["matches"] == []
        assert "direct tree-sitter API access" in result["message"]
        assert result["tip"] is not None

    def test_failed_parse_returns_error(self, registered, fake_parser):
        fake_parser.parse_file = AsyncMock(
            return_value=_make_parse_result(success=False, error="parse failed")
        )
        tool = registered.tools["treesitter_query"]
        result = _run(tool(file_path="/tmp/foo.py", query="(x)"))
        assert result["success"] is False
        assert result["error"] == "parse failed"

    def test_exception_returns_error(self, stub_mcp, fake_parser):
        fake_parser.parse_file = AsyncMock(side_effect=RuntimeError("boom"))
        tt._parser = fake_parser
        register_treesitter_tools(stub_mcp)
        tool = stub_mcp.tools["treesitter_query"]
        result = _run(tool(file_path="/tmp/foo.py", query="(x)"))
        assert result["success"] is False


# =============================================================================
# treesitter_batch_analyze
# =============================================================================


class TestTreesitterBatchAnalyze:
    """Tests for treesitter_batch_analyze tool."""

    def test_analyzes_files_in_directory(self, registered, fake_parser, tmp_path):
        """Files in the directory are parsed and aggregated."""
        for i in range(3):
            (tmp_path / f"f{i}.py").write_text(f"x = {i}\n")
        fake_parser.parse_file = AsyncMock(
            return_value=_make_parse_result(symbols=[_make_symbol("x")], imports=[MagicMock()])
        )
        tool = registered.tools["treesitter_batch_analyze"]
        result = _run(tool(directory=str(tmp_path), file_pattern="*.py"))
        assert result["success"] is True
        assert result["files_analyzed"] == 3
        assert result["total_symbols"] == 3
        assert result["total_imports"] == 3
        assert result["cache_hit_rate"] == 0.625

    def test_max_files_truncates(self, registered, fake_parser, tmp_path):
        """max_files=2 only parses the first 2 files."""
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text("x = 1\n")
        tool = registered.tools["treesitter_batch_analyze"]
        result = _run(tool(directory=str(tmp_path), file_pattern="*.py", max_files=2))
        assert result["files_analyzed"] == 2

    def test_collects_errors(self, registered, fake_parser, tmp_path):
        """Failed parses are aggregated into the errors list."""
        (tmp_path / "good.py").write_text("x = 1\n")
        (tmp_path / "bad.py").write_text("x = 2\n")

        async def parse_side_effect(path, language=None):
            if "bad" in str(path):
                return _make_parse_result(success=False, error="bad file")
            return _make_parse_result(symbols=[_make_symbol()])

        fake_parser.parse_file = AsyncMock(side_effect=parse_side_effect)
        tool = registered.tools["treesitter_batch_analyze"]
        result = _run(tool(directory=str(tmp_path), file_pattern="*.py"))
        assert result["success"] is True
        assert result["error_count"] == 1
        assert result["errors"][0]["error"] == "bad file"

    def test_exception_in_loop_collected_as_error(self, registered, fake_parser, tmp_path):
        (tmp_path / "f.py").write_text("x = 1\n")

        async def parse_side_effect(path, language=None):
            raise OSError("disk")

        fake_parser.parse_file = AsyncMock(side_effect=parse_side_effect)
        tool = registered.tools["treesitter_batch_analyze"]
        result = _run(tool(directory=str(tmp_path), file_pattern="*.py"))
        assert result["success"] is True
        assert result["error_count"] == 1
        assert "disk" in result["errors"][0]["error"]

    def test_per_file_exception_collected_in_errors(self, stub_mcp, fake_parser):
        """A RuntimeError raised by parse_file is caught in the per-file try/except
        and added to the ``errors`` list. The overall call still returns
        ``success: True`` with ``error_count > 0`` — that's by design, so the
        caller can still see which files failed.
        """
        fake_parser.parse_file = AsyncMock(side_effect=RuntimeError("boom"))
        tt._parser = fake_parser
        register_treesitter_tools(stub_mcp)
        tool = stub_mcp.tools["treesitter_batch_analyze"]
        result = _run(tool(directory="/tmp"))
        assert result["success"] is True
        assert result["error_count"] >= 1
        assert "boom" in result["errors"][0]["error"]


# =============================================================================
# treesitter_cache_stats
# =============================================================================


class TestTreesitterCacheStats:
    """Tests for treesitter_cache_stats tool."""

    def test_returns_parser_stats(self, registered, fake_parser):
        tool = registered.tools["treesitter_cache_stats"]
        result = _run(tool())
        assert result["success"] is True
        assert result["hits"] == 5
        assert result["misses"] == 3
        assert result["hit_rate"] == 0.625

    def test_exception_returns_error(self, stub_mcp, fake_parser):
        fake_parser.get_cache_stats = MagicMock(side_effect=RuntimeError("boom"))
        tt._parser = fake_parser
        register_treesitter_tools(stub_mcp)
        tool = stub_mcp.tools["treesitter_cache_stats"]
        result = _run(tool())
        assert result["success"] is False


# =============================================================================
# treesitter_clear_cache
# =============================================================================


class TestTreesitterClearCache:
    """Tests for treesitter_clear_cache tool."""

    def test_returns_entries_cleared(self, registered, fake_parser):
        tool = registered.tools["treesitter_clear_cache"]
        result = _run(tool())
        assert result["success"] is True
        assert result["entries_cleared"] == 42
        fake_parser.clear_cache.assert_called_once()

    def test_exception_returns_error(self, stub_mcp, fake_parser):
        fake_parser.clear_cache = MagicMock(side_effect=RuntimeError("boom"))
        tt._parser = fake_parser
        register_treesitter_tools(stub_mcp)
        tool = stub_mcp.tools["treesitter_clear_cache"]
        result = _run(tool())
        assert result["success"] is False


# =============================================================================
# Module-level helpers
# =============================================================================


class TestGetParser:
    """Tests for the module-level _get_parser lazy cache."""

    def test_cache_hit_returns_existing(self):
        """When _parser is set, _get_parser returns it without instantiating."""
        sentinel = MagicMock(name="cached parser")
        tt._parser = sentinel
        assert tt._get_parser() is sentinel
        # Cache should still be the same object afterwards
        assert tt._parser is sentinel

    def test_cache_miss_populates_and_reuses(self):
        """First call instantiates the parser and caches it; second call reuses."""
        # The source does `from mcp_common.parsing.tree_sitter import TreeSitterParser`
        # inside the function, so we patch the class on the source module.
        import mcp_common.parsing.tree_sitter as ts_module

        with patch.object(ts_module, "TreeSitterParser") as cls:
            cls.return_value = MagicMock(name="newly-created parser")
            tt._parser = None
            parser1 = tt._get_parser()
            parser2 = tt._get_parser()
        assert parser1 is parser2
        assert cls.call_count == 1

    def test_global_parser_resets_via_fixture(self):
        """The autouse _reset_parser fixture keeps the cache empty between tests."""
        assert tt._parser is None
