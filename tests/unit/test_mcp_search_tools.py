"""Unit tests for mahavishnu.mcp.tools.search_tools.

The module exposes a single ``register_search_tools`` function that wires up
``hybrid_search``, ``index_document``, ``delete_document``, and
``search_by_repository`` to a ``FastMCP`` server. The tools lazily create a
``HybridSearchEngine`` via ``get_database`` and ``HybridSearchConfig``; tests
patch those source modules to keep the suite hermetic.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.mcp.tools import search_tools as st
from mahavishnu.mcp.tools.search_tools import register_search_tools

pytestmark = pytest.mark.unit


# =============================================================================
# Helpers
# =============================================================================


class _StubMCP:
    """Minimal stand-in for FastMCP that records decorated functions."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _search_result(doc_id: str = "11111111-1111-1111-1111-111111111111", title: str = "T"):
    result = MagicMock()
    result.model_dump = MagicMock(return_value={"id": doc_id, "title": title, "score": 0.91})
    return result


def _patch_engine(monkeypatch: pytest.MonkeyPatch, engine: MagicMock) -> None:
    """Stub out get_database and the lazy HybridSearchConfig default."""
    fake_db = MagicMock(name="fake_db")
    monkeypatch.setattr(st, "get_database", AsyncMock(return_value=fake_db))


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def stub_mcp() -> _StubMCP:
    return _StubMCP()


@pytest.fixture
def fake_engine() -> MagicMock:
    engine = MagicMock(name="HybridSearchEngine")
    engine.search = AsyncMock(return_value=[])
    engine.index_document = AsyncMock(return_value=None)
    engine.delete_document = AsyncMock(return_value=True)
    engine.config = MagicMock()
    engine.get_cache_stats = MagicMock(return_value={"hits": 0, "misses": 0})
    return engine


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch: pytest.MonkeyPatch):
    """Force ``register_search_tools`` to re-create the engine on every test."""
    # The source module binds _search_engine inside the closure each
    # register call, so we just need to ensure get_database returns a fresh
    # MagicMock every time. (No global state to reset.)
    yield


# =============================================================================
# Registration
# =============================================================================


class TestRegistration:
    """register_search_tools attaches the four tool functions."""

    def test_registers_all_four_tools(self, stub_mcp: _StubMCP) -> None:
        register_search_tools(stub_mcp)
        assert set(stub_mcp.tools) == {
            "hybrid_search",
            "index_document",
            "delete_document",
            "search_by_repository",
        }

    def test_module_exports_register(self) -> None:
        assert "register_search_tools" in st.__all__
        assert callable(register_search_tools)


# =============================================================================
# hybrid_search
# =============================================================================


class TestHybridSearchTool:
    """hybrid_search delegates to HybridSearchEngine.search."""

    async def test_returns_serialized_results(
        self, stub_mcp: _StubMCP, fake_engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine.search = AsyncMock(return_value=[_search_result("a"), _search_result("b")])
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.HybridSearchEngine",
            lambda database, config: fake_engine,
        )
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.get_database",
            AsyncMock(return_value=MagicMock()),
        )

        register_search_tools(stub_mcp)
        fn = stub_mcp.tools["hybrid_search"]
        result = await fn(query="test", limit=5)

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == "a"
        assert result[1]["id"] == "b"

    async def test_uses_custom_weights(
        self, stub_mcp: _StubMCP, fake_engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine.search = AsyncMock(return_value=[])
        ctor = MagicMock(return_value=fake_engine)
        monkeypatch.setattr("mahavishnu.mcp.tools.search_tools.HybridSearchEngine", ctor)
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.get_database",
            AsyncMock(return_value=MagicMock()),
        )

        register_search_tools(stub_mcp)
        fn = stub_mcp.tools["hybrid_search"]
        await fn(
            query="x",
            semantic_weight=0.2,
            lexical_weight=0.8,
            limit=7,
            min_score=0.42,
        )

        # The tool creates a HybridSearchConfig with the caller-supplied
        # weights and assigns it onto the engine's .config attribute
        # after retrieving the engine.
        assert fake_engine.config.semantic_weight == 0.2
        assert fake_engine.config.lexical_weight == 0.8
        assert fake_engine.config.default_limit == 7
        assert fake_engine.config.min_score == 0.42

    async def test_propagates_engine_exception(
        self, stub_mcp: _StubMCP, fake_engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine.search = AsyncMock(side_effect=RuntimeError("db down"))
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.HybridSearchEngine",
            lambda database, config: fake_engine,
        )
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.get_database",
            AsyncMock(return_value=MagicMock()),
        )

        register_search_tools(stub_mcp)
        fn = stub_mcp.tools["hybrid_search"]
        with pytest.raises(RuntimeError, match="db down"):
            await fn(query="q")


# =============================================================================
# index_document
# =============================================================================


class TestIndexDocumentTool:
    """index_document calls engine.index_document and returns a success envelope."""

    async def test_indexes_valid_uuid(
        self, stub_mcp: _StubMCP, fake_engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine.index_document = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.HybridSearchEngine",
            lambda database, config: fake_engine,
        )
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.get_database",
            AsyncMock(return_value=MagicMock()),
        )

        register_search_tools(stub_mcp)
        fn = stub_mcp.tools["index_document"]
        result = await fn(
            doc_id="11111111-1111-1111-1111-111111111111",
            title="Hello",
            content="Body text",
            repository="repo",
            source_type="markdown",
            metadata={"k": "v"},
        )

        assert result["success"] is True
        assert result["doc_id"] == "11111111-1111-1111-1111-111111111111"
        assert "indexed" in result["message"].lower()
        fake_engine.index_document.assert_awaited_once()
        kwargs = fake_engine.index_document.await_args.kwargs
        assert kwargs["title"] == "Hello"
        assert kwargs["content"] == "Body text"
        assert kwargs["metadata"] == {"k": "v"}

    async def test_rejects_invalid_uuid(
        self, stub_mcp: _StubMCP, fake_engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.HybridSearchEngine",
            lambda database, config: fake_engine,
        )
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.get_database",
            AsyncMock(return_value=MagicMock()),
        )

        register_search_tools(stub_mcp)
        fn = stub_mcp.tools["index_document"]
        with pytest.raises(ValueError, match="Invalid document UUID"):
            await fn(doc_id="not-a-uuid", title="T", content="c")

    async def test_propagates_engine_exception(
        self, stub_mcp: _StubMCP, fake_engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine.index_document = AsyncMock(side_effect=RuntimeError("write fail"))
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.HybridSearchEngine",
            lambda database, config: fake_engine,
        )
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.get_database",
            AsyncMock(return_value=MagicMock()),
        )

        register_search_tools(stub_mcp)
        fn = stub_mcp.tools["index_document"]
        with pytest.raises(RuntimeError, match="write fail"):
            await fn(
                doc_id="11111111-1111-1111-1111-111111111111",
                title="T",
                content="c",
            )


# =============================================================================
# delete_document
# =============================================================================


class TestDeleteDocumentTool:
    """delete_document returns success envelope with deleted flag."""

    async def test_delete_existing(
        self, stub_mcp: _StubMCP, fake_engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine.delete_document = AsyncMock(return_value=True)
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.HybridSearchEngine",
            lambda database, config: fake_engine,
        )
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.get_database",
            AsyncMock(return_value=MagicMock()),
        )

        register_search_tools(stub_mcp)
        fn = stub_mcp.tools["delete_document"]
        result = await fn(doc_id="11111111-1111-1111-1111-111111111111")

        assert result["success"] is True
        assert result["deleted"] is True
        assert "successfully" in result["message"].lower()

    async def test_delete_missing_reports_not_found(
        self, stub_mcp: _StubMCP, fake_engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine.delete_document = AsyncMock(return_value=False)
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.HybridSearchEngine",
            lambda database, config: fake_engine,
        )
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.get_database",
            AsyncMock(return_value=MagicMock()),
        )

        register_search_tools(stub_mcp)
        fn = stub_mcp.tools["delete_document"]
        result = await fn(doc_id="11111111-1111-1111-1111-111111111111")

        assert result["success"] is True
        assert result["deleted"] is False
        assert "not found" in result["message"].lower()

    async def test_invalid_uuid_raises_value_error(
        self, stub_mcp: _StubMCP, fake_engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.HybridSearchEngine",
            lambda database, config: fake_engine,
        )
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.get_database",
            AsyncMock(return_value=MagicMock()),
        )

        register_search_tools(stub_mcp)
        fn = stub_mcp.tools["delete_document"]
        with pytest.raises(ValueError, match="Invalid document UUID"):
            await fn(doc_id="nope")

    async def test_propagates_engine_exception(
        self, stub_mcp: _StubMCP, fake_engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine.delete_document = AsyncMock(side_effect=RuntimeError("delete fail"))
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.HybridSearchEngine",
            lambda database, config: fake_engine,
        )
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.get_database",
            AsyncMock(return_value=MagicMock()),
        )

        register_search_tools(stub_mcp)
        fn = stub_mcp.tools["delete_document"]
        with pytest.raises(RuntimeError, match="delete fail"):
            await fn(doc_id="11111111-1111-1111-1111-111111111111")


# =============================================================================
# search_by_repository
# =============================================================================


class TestSearchByRepositoryTool:
    """search_by_repository calls engine.search and returns serialized results."""

    async def test_returns_results(
        self, stub_mcp: _StubMCP, fake_engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine.search = AsyncMock(return_value=[_search_result("a")])
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.HybridSearchEngine",
            lambda database, config: fake_engine,
        )
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.get_database",
            AsyncMock(return_value=MagicMock()),
        )

        register_search_tools(stub_mcp)
        fn = stub_mcp.tools["search_by_repository"]
        result = await fn(repository="mahavishnu", query="how to", limit=3)

        assert isinstance(result, list)
        assert result[0]["id"] == "a"
        # Repository was forwarded
        fake_engine.search.assert_awaited_once()
        kwargs = fake_engine.search.await_args.kwargs
        assert kwargs["repository"] == "mahavishnu"
        assert kwargs["limit"] == 3

    async def test_empty_query_uses_minimal_placeholder(
        self, stub_mcp: _StubMCP, fake_engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine.search = AsyncMock(return_value=[])
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.HybridSearchEngine",
            lambda database, config: fake_engine,
        )
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.get_database",
            AsyncMock(return_value=MagicMock()),
        )

        register_search_tools(stub_mcp)
        fn = stub_mcp.tools["search_by_repository"]
        await fn(repository="mahavishnu", query="   ")

        kwargs = fake_engine.search.await_args.kwargs
        # Whitespace-only query is replaced with a single char so the
        # engine returns *something* without erroring out.
        assert kwargs["query"].strip() != ""
        assert kwargs["repository"] == "mahavishnu"

    async def test_propagates_engine_exception(
        self, stub_mcp: _StubMCP, fake_engine: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine.search = AsyncMock(side_effect=RuntimeError("search down"))
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.HybridSearchEngine",
            lambda database, config: fake_engine,
        )
        monkeypatch.setattr(
            "mahavishnu.mcp.tools.search_tools.get_database",
            AsyncMock(return_value=MagicMock()),
        )

        register_search_tools(stub_mcp)
        fn = stub_mcp.tools["search_by_repository"]
        with pytest.raises(RuntimeError, match="search down"):
            await fn(repository="mahavishnu", query="hi")
