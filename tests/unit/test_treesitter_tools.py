"""Tests for mcp/tools/treesitter_tools.py — covers exception paths and success paths."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools.treesitter_tools import register_treesitter_tools

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_mock_mcp() -> MagicMock:
    """Return a mock FastMCP where @tool() is the identity decorator."""
    mcp = MagicMock()
    captured: dict[str, object] = {}

    def tool():
        def decorator(fn):
            captured[fn.__name__] = fn
            return fn

        return decorator

    mcp.tool = tool
    mcp._captured = captured
    return mcp


def _register_and_get(mock_mcp: MagicMock) -> dict:
    register_treesitter_tools(mock_mcp)
    return mock_mcp._captured


def _make_parse_result(
    *,
    success: bool = True,
    language_value: str = "python",
    symbols=None,
    imports=None,
    relationships=None,
    parse_time_ms: float = 1.5,
    from_cache: bool = False,
    error_node_count: int = 0,
    error: str | None = None,
) -> SimpleNamespace:
    lang = SimpleNamespace(value=language_value)
    sym = SimpleNamespace(
        name="my_func",
        kind=SimpleNamespace(value="function"),
        line_start=1,
        line_end=10,
        column_start=0,
        column_end=20,
        signature="def my_func():",
        docstring=None,
        modifiers=set(),
        parameters=[],
        return_type=None,
        parent_context=None,
    )
    return SimpleNamespace(
        success=success,
        file_path="/fake/file.py",
        language=lang,
        symbols=symbols if symbols is not None else [sym],
        imports=imports if imports is not None else [],
        relationships=relationships if relationships is not None else [],
        parse_time_ms=parse_time_ms,
        from_cache=from_cache,
        error_node_count=error_node_count,
        error=error,
    )


# ---------------------------------------------------------------------------
# Exception path tests — each tool's except block
# ---------------------------------------------------------------------------


class TestTreesitterParseExceptions:
    @pytest.mark.asyncio
    async def test_parse_exception_returns_error_dict(self) -> None:
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch(
            "mahavishnu.mcp.tools.treesitter_tools._get_parser",
            side_effect=RuntimeError("parser unavailable"),
        ):
            result = await tools["treesitter_parse"]("/fake/file.py")
        assert result["success"] is False
        assert "parser unavailable" in result["error"]


class TestTreesitterExtractSymbolsExceptions:
    @pytest.mark.asyncio
    async def test_extract_exception_returns_error_dict(self) -> None:
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch(
            "mahavishnu.mcp.tools.treesitter_tools._get_parser",
            side_effect=RuntimeError("extract error"),
        ):
            result = await tools["treesitter_extract_symbols"]("/fake/file.py")
        assert result["success"] is False
        assert result["symbols"] == []
        assert "extract error" in result["error"]


class TestTreesitterFindUsagesExceptions:
    @pytest.mark.asyncio
    async def test_find_usages_exception_returns_error_dict(self) -> None:
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch(
            "mahavishnu.mcp.tools.treesitter_tools._get_parser",
            side_effect=RuntimeError("usages error"),
        ):
            result = await tools["treesitter_find_usages"]("/fake/file.py", "my_sym")
        assert result["success"] is False
        assert result["usages"] == []
        assert "usages error" in result["error"]


class TestTreesitterQueryExceptions:
    @pytest.mark.asyncio
    async def test_query_exception_returns_error_dict(self) -> None:
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch(
            "mahavishnu.mcp.tools.treesitter_tools._get_parser",
            side_effect=RuntimeError("query error"),
        ):
            result = await tools["treesitter_query"]("/fake/file.py", "(function_definition)")
        assert result["success"] is False
        assert result["matches"] == []
        assert "query error" in result["error"]


class TestTreesitterBatchAnalyzeExceptions:
    @pytest.mark.asyncio
    async def test_batch_exception_returns_error_dict(self) -> None:
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch(
            "mahavishnu.mcp.tools.treesitter_tools._get_parser",
            side_effect=RuntimeError("batch error"),
        ):
            result = await tools["treesitter_batch_analyze"]("/fake/dir")
        assert result["success"] is False
        assert result["results"] == []
        assert "batch error" in result["error"]


class TestTreesitterCacheStatsExceptions:
    @pytest.mark.asyncio
    async def test_cache_stats_exception_returns_error_dict(self) -> None:
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch(
            "mahavishnu.mcp.tools.treesitter_tools._get_parser",
            side_effect=RuntimeError("stats error"),
        ):
            result = await tools["treesitter_cache_stats"]()
        assert result["success"] is False
        assert "stats error" in result["error"]


class TestTreesitterClearCacheExceptions:
    @pytest.mark.asyncio
    async def test_clear_cache_exception_returns_error_dict(self) -> None:
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch(
            "mahavishnu.mcp.tools.treesitter_tools._get_parser",
            side_effect=RuntimeError("clear error"),
        ):
            result = await tools["treesitter_clear_cache"]()
        assert result["success"] is False
        assert "clear error" in result["error"]


# ---------------------------------------------------------------------------
# Success path tests — mock parser returning valid results
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_parser_and_result():
    """Provide a mock parser that returns a successful parse result."""
    parse_result = _make_parse_result()
    parser = MagicMock()
    lang = SimpleNamespace(value="python")
    parser.detect_language = MagicMock(return_value=lang)
    parser.parse_file = AsyncMock(return_value=parse_result)
    parser.get_cache_stats = MagicMock(return_value={"hit_rate": 0.5, "size": 3})
    parser.clear_cache = MagicMock(return_value=7)
    return parser, parse_result


class TestTreesitterParseSuccess:
    @pytest.mark.asyncio
    async def test_parse_with_explicit_language(self, mock_parser_and_result) -> None:
        parser, _ = mock_parser_and_result
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with (
            patch("mahavishnu.mcp.tools.treesitter_tools._get_parser", return_value=parser),
            patch(
                "mahavishnu.mcp.tools.treesitter_tools._ensure_grammar_loaded", return_value=True
            ),
            patch(
                "mahavishnu.mcp.tools.treesitter_tools.SupportedLanguage"
                if False
                else "builtins.open",
                create=True,
            ),
        ):
            # Patch SupportedLanguage at module level
            with patch(
                "mahavishnu.mcp.tools.treesitter_tools._ensure_grammar_loaded", return_value=True
            ):
                result = await tools["treesitter_parse"]("/fake/file.py")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_parse_success_returns_expected_keys(self, mock_parser_and_result) -> None:
        parser, _ = mock_parser_and_result
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch("mahavishnu.mcp.tools.treesitter_tools._get_parser", return_value=parser):
            result = await tools["treesitter_parse"]("/fake/file.py")
        assert "symbols_count" in result
        assert "imports_count" in result
        assert "from_cache" in result


class TestTreesitterExtractSymbolsSuccess:
    @pytest.mark.asyncio
    async def test_extract_success_returns_symbols(self, mock_parser_and_result) -> None:
        parser, _ = mock_parser_and_result
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch("mahavishnu.mcp.tools.treesitter_tools._get_parser", return_value=parser):
            result = await tools["treesitter_extract_symbols"]("/fake/file.py")
        assert result["success"] is True
        assert isinstance(result["symbols"], list)
        assert result["total_symbols"] == 1

    @pytest.mark.asyncio
    async def test_extract_with_kind_filter(self, mock_parser_and_result) -> None:
        parser, _ = mock_parser_and_result
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch("mahavishnu.mcp.tools.treesitter_tools._get_parser", return_value=parser):
            result = await tools["treesitter_extract_symbols"](
                "/fake/file.py", symbol_kinds=["function"]
            )
        assert result["filtered_symbols"] == 1

    @pytest.mark.asyncio
    async def test_extract_kind_filter_no_match(self, mock_parser_and_result) -> None:
        parser, _ = mock_parser_and_result
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch("mahavishnu.mcp.tools.treesitter_tools._get_parser", return_value=parser):
            result = await tools["treesitter_extract_symbols"](
                "/fake/file.py", symbol_kinds=["class"]
            )
        assert result["filtered_symbols"] == 0


class TestTreesitterCacheStatsSuccess:
    @pytest.mark.asyncio
    async def test_cache_stats_success(self, mock_parser_and_result) -> None:
        parser, _ = mock_parser_and_result
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch("mahavishnu.mcp.tools.treesitter_tools._get_parser", return_value=parser):
            result = await tools["treesitter_cache_stats"]()
        assert result["success"] is True
        assert result["hit_rate"] == 0.5


class TestTreesitterClearCacheSuccess:
    @pytest.mark.asyncio
    async def test_clear_cache_success(self, mock_parser_and_result) -> None:
        parser, _ = mock_parser_and_result
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch("mahavishnu.mcp.tools.treesitter_tools._get_parser", return_value=parser):
            result = await tools["treesitter_clear_cache"]()
        assert result["success"] is True
        assert result["entries_cleared"] == 7


class TestTreesitterFindUsagesSuccess:
    @pytest.mark.asyncio
    async def test_find_usages_parse_failure(self, mock_parser_and_result) -> None:
        parser, _ = mock_parser_and_result
        fail_result = _make_parse_result(success=False, error="parse failed", symbols=[])
        parser.parse_file = AsyncMock(return_value=fail_result)
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch("mahavishnu.mcp.tools.treesitter_tools._get_parser", return_value=parser):
            result = await tools["treesitter_find_usages"]("/fake/file.py", "sym")
        assert result["success"] is False
        assert "parse failed" in result["error"]

    @pytest.mark.asyncio
    async def test_find_usages_symbol_not_found(self, mock_parser_and_result) -> None:
        parser, _ = mock_parser_and_result
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch("mahavishnu.mcp.tools.treesitter_tools._get_parser", return_value=parser):
            result = await tools["treesitter_find_usages"]("/fake/file.py", "nonexistent_sym")
        assert result["success"] is True
        assert result["definition"] is None
        assert result["usages"] == []


class TestTreesitterQuerySuccess:
    @pytest.mark.asyncio
    async def test_query_unknown_language_returns_error(self, mock_parser_and_result) -> None:
        parser, _ = mock_parser_and_result
        parser.detect_language = MagicMock(return_value=SimpleNamespace(value="unknown"))
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch("mahavishnu.mcp.tools.treesitter_tools._get_parser", return_value=parser):
            result = await tools["treesitter_query"]("/fake/file.py", "(func)")
        assert result["success"] is False
        assert "Unknown language" in result["error"]

    @pytest.mark.asyncio
    async def test_query_success(self, mock_parser_and_result) -> None:
        parser, _ = mock_parser_and_result
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch("mahavishnu.mcp.tools.treesitter_tools._get_parser", return_value=parser):
            result = await tools["treesitter_query"]("/fake/file.py", "(func)")
        assert result["success"] is True
        assert result["matches"] == []


class TestTreesitterBatchAnalyzeSuccess:
    @pytest.mark.asyncio
    async def test_batch_empty_dir(self, tmp_path: Path, mock_parser_and_result) -> None:
        parser, _ = mock_parser_and_result
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch("mahavishnu.mcp.tools.treesitter_tools._get_parser", return_value=parser):
            result = await tools["treesitter_batch_analyze"](str(tmp_path))
        assert result["success"] is True
        assert result["files_analyzed"] == 0

    @pytest.mark.asyncio
    async def test_batch_with_files(self, tmp_path: Path, mock_parser_and_result) -> None:
        (tmp_path / "a.py").write_text("x = 1")
        parser, parse_result = mock_parser_and_result
        mcp = _make_mock_mcp()
        tools = _register_and_get(mcp)
        with patch("mahavishnu.mcp.tools.treesitter_tools._get_parser", return_value=parser):
            result = await tools["treesitter_batch_analyze"](str(tmp_path))
        assert result["success"] is True
        assert result["files_analyzed"] == 1
