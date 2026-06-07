"""Unit tests for the pgvector adapter (mahavishnu/adapters/pgvector_adapter.py).

All DB interactions are mocked via an in-memory AsyncMock connection so the
tests run without asyncpg/pgvector installed.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.adapters.pgvector_adapter import (
    HNSWConfig,
    IndexType,
    IVFFlatConfig,
    PgvectorAdapter,
    PgvectorSettings,
)

pytestmark = pytest.mark.unit


# ============================== Fixtures ==============================


@pytest.fixture
def settings() -> PgvectorSettings:
    """Default settings (no DSN, plain config)."""
    return PgvectorSettings(
        host="localhost",
        port=5432,
        user="testuser",
        database="testdb",
        db_schema="public",
        collection_prefix="vectors_",
    )


@pytest.fixture
def mock_conn() -> AsyncMock:
    """A fake asyncpg connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchval = AsyncMock(return_value=0)
    conn.fetchrow = AsyncMock(return_value={"id": "rec-1"})
    return conn


@pytest.fixture
def adapter_with_mock_conn(settings: PgvectorSettings, mock_conn: AsyncMock) -> PgvectorAdapter:
    """Adapter whose `_connection()` context yields `mock_conn`."""
    adapter = PgvectorAdapter(settings)

    @asynccontextmanager
    async def _fake_connection() -> Any:
        yield mock_conn

    adapter._connection = _fake_connection  # type: ignore[assignment]
    return adapter


# ============================== HNSWConfig ==============================


class TestHNSWConfig:
    """Validation for HNSWConfig dataclass."""

    def test_defaults(self):
        cfg = HNSWConfig()
        assert cfg.m == 16
        assert cfg.ef_construction == 64
        assert cfg.ef_search == 40

    def test_custom_values(self):
        cfg = HNSWConfig(m=24, ef_construction=128, ef_search=80)
        assert cfg.m == 24
        assert cfg.ef_construction == 128
        assert cfg.ef_search == 80

    def test_m_below_range_raises(self):
        with pytest.raises(ValueError, match="m must be between 4 and 48"):
            HNSWConfig(m=2)

    def test_m_above_range_raises(self):
        with pytest.raises(ValueError, match="m must be between 4 and 48"):
            HNSWConfig(m=64)

    def test_ef_construction_invalid(self):
        with pytest.raises(ValueError, match="ef_construction"):
            HNSWConfig(ef_construction=4)

    def test_ef_search_invalid(self):
        with pytest.raises(ValueError, match="ef_search"):
            HNSWConfig(ef_search=300)


# ============================== IVFFlatConfig ==============================


class TestIVFFlatConfig:
    """Validation for IVFFlatConfig dataclass."""

    def test_default(self):
        assert IVFFlatConfig().lists == 100

    def test_lists_zero_raises(self):
        with pytest.raises(ValueError, match="lists must be >= 1"):
            IVFFlatConfig(lists=0)

    def test_lists_custom(self):
        assert IVFFlatConfig(lists=300).lists == 300


# ============================== PgvectorSettings ==============================


class TestPgvectorSettings:
    """Validation for the settings Pydantic model."""

    def test_defaults(self):
        s = PgvectorSettings()
        assert s.host == "localhost"
        assert s.port == 5432
        assert s.user == "postgres"
        assert s.database == "mahavishnu"
        assert s.db_schema == "public"
        assert s.collection_prefix == "vectors_"
        assert s.index_type == IndexType.HNSW
        assert s.default_distance_metric == "cosine"

    def test_with_dsn(self):
        s = PgvectorSettings(dsn="postgresql://user@host/db")
        assert s.dsn == "postgresql://user@host/db"


# ============================== Distance / Index Operators ==============================


class TestOperators:
    """The private _distance_operator and _index_operator_class helpers."""

    def test_cosine_default(self, settings: PgvectorSettings):
        adapter = PgvectorAdapter(settings)
        assert adapter._distance_operator() == "<=>"
        assert adapter._index_operator_class("cosine") == "vector_cosine_ops"

    def test_euclidean(self):
        s = PgvectorSettings(default_distance_metric="euclidean")
        adapter = PgvectorAdapter(s)
        assert adapter._distance_operator() == "<->"
        assert adapter._index_operator_class("L2") == "vector_l2_ops"

    def test_dot_product(self):
        s = PgvectorSettings(default_distance_metric="dot_product")
        adapter = PgvectorAdapter(s)
        assert adapter._distance_operator() == "<#>"
        assert adapter._index_operator_class("inner_product") == "vector_ip_ops"

    def test_unknown_falls_back_to_cosine(self):
        s = PgvectorSettings(default_distance_metric="random")
        assert PgvectorAdapter(s)._distance_operator() == "<=>"
        assert PgvectorAdapter(s)._index_operator_class("nope") == "vector_cosine_ops"


# ============================== Identifier sanitization ==============================


class TestIdentifierSanitization:
    """Coverage for _normalize_name, _sanitize_identifier, _qualified_table."""

    def test_normalize_name_simple(self, settings: PgvectorSettings):
        adapter = PgvectorAdapter(settings)
        assert adapter._normalize_name("traces") == "vectors_traces"

    def test_normalize_name_strips_unsafe(self, settings: PgvectorSettings):
        adapter = PgvectorAdapter(settings)
        # `-` is not alphanumeric → replaced with `_`
        assert adapter._normalize_name("foo-bar") == "vectors_foo_bar"

    def test_normalize_name_digit_prefix_gets_prefixed(self):
        s = PgvectorSettings(collection_prefix="9_")
        adapter = PgvectorAdapter(s)
        assert adapter._normalize_name("x").startswith("v_")

    def test_sanitize_identifier_safe(self, settings: PgvectorSettings):
        adapter = PgvectorAdapter(settings)
        assert adapter._sanitize_identifier("public") == "public"

    def test_sanitize_identifier_rejects_empty(self, settings: PgvectorSettings):
        adapter = PgvectorAdapter(settings)
        with pytest.raises(ValueError, match="Invalid identifier"):
            adapter._sanitize_identifier("")

    def test_sanitize_identifier_replaces_unsafe_chars(self, settings: PgvectorSettings):
        adapter = PgvectorAdapter(settings)
        # Hyphens get replaced by underscores → still valid identifier
        assert adapter._sanitize_identifier("foo-bar") == "foo_bar"

    def test_qualified_table_contains_quotes(self, settings: PgvectorSettings):
        adapter = PgvectorAdapter(settings)
        qt = adapter._qualified_table("evt")
        assert qt == '"public"."vectors_evt"'


# ============================== _connection_kwargs ==============================


class TestConnectionKwargs:
    """Coverage for _connection_kwargs branches."""

    def test_dsn_takes_priority(self):
        s = PgvectorSettings(dsn="postgresql://localhost/db")
        adapter = PgvectorAdapter(s)
        assert adapter._connection_kwargs() == {"dsn": "postgresql://localhost/db"}

    def test_basic_kwargs(self, settings: PgvectorSettings):
        adapter = PgvectorAdapter(settings)
        kwargs = adapter._connection_kwargs()
        assert kwargs["host"] == "localhost"
        assert kwargs["port"] == 5432
        assert kwargs["user"] == "testuser"
        assert kwargs["database"] == "testdb"
        assert kwargs["min_size"] == 1
        assert kwargs["max_size"] == 10

    def test_password_extracted_from_secret(self):
        from pydantic import SecretStr

        s = PgvectorSettings(password=SecretStr("secret"))
        adapter = PgvectorAdapter(s)
        assert adapter._connection_kwargs()["password"] == "secret"

    def test_ssl_enabled(self):
        s = PgvectorSettings(ssl=True)
        adapter = PgvectorAdapter(s)
        assert adapter._connection_kwargs()["ssl"] is True

    def test_statement_timeout_converted(self):
        s = PgvectorSettings(statement_timeout_ms=5000)
        adapter = PgvectorAdapter(s)
        assert adapter._connection_kwargs()["command_timeout"] == 5.0


# ============================== Public API: search/insert/get/delete/count ==============================


class TestPublicAPI:
    """Exercise the public adapter methods via a mocked _connection."""

    async def test_health_returns_true(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        assert await adapter_with_mock_conn.health() is True
        mock_conn.execute.assert_awaited()

    async def test_health_returns_false_on_error(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        mock_conn.execute.side_effect = RuntimeError("boom")
        assert await adapter_with_mock_conn.health() is False

    async def test_cleanup_with_no_pool(self, settings: PgvectorSettings):
        adapter = PgvectorAdapter(settings)
        # Should not raise
        await adapter.cleanup()
        assert adapter._pool is None

    async def test_cleanup_closes_pool(self, settings: PgvectorSettings):
        adapter = PgvectorAdapter(settings)
        pool = AsyncMock()
        pool.close = AsyncMock()
        adapter._pool = pool
        await adapter.cleanup()
        pool.close.assert_awaited_once()
        assert adapter._pool is None

    async def test_search_returns_formatted_results(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        mock_conn.fetch.return_value = [
            {"id": "a", "metadata": {"k": "v"}, "embedding": None, "distance": 0.1},
            {"id": "b", "metadata": None, "embedding": None, "distance": 0.3},
        ]

        results = await adapter_with_mock_conn.search("traces", [0.1, 0.2], limit=2)

        assert len(results) == 2
        assert results[0]["id"] == "a"
        assert results[0]["score"] == pytest.approx(0.1)
        assert results[1]["metadata"] == {}  # None coerced to empty dict
        assert results[0]["vector"] is None

    async def test_search_with_filter_expr(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        await adapter_with_mock_conn.search(
            "traces",
            [0.1, 0.2],
            limit=5,
            filter_expr={"tenant": "a"},
        )
        # The 3rd param should be JSON-encoded filter
        call_args = mock_conn.fetch.call_args[0]
        # call_args[0] = SQL, call_args[1+] are positional params
        assert json.loads(call_args[2]) == {"tenant": "a"}

    async def test_search_include_vectors_passes_through(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        mock_conn.fetch.return_value = [
            {"id": "x", "metadata": {}, "embedding": [0.1, 0.2], "distance": 0.0}
        ]
        out = await adapter_with_mock_conn.search("c", [0.1], limit=1, include_vectors=True)
        assert out[0]["vector"] == [0.1, 0.2]

    async def test_insert_returns_ids(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        mock_conn.fetchrow.return_value = {"id": "x"}
        ids = await adapter_with_mock_conn.insert(
            "traces", [{"id": "x", "vector": [0.1], "metadata": {"a": 1}}]
        )
        assert ids == ["x"]

    async def test_insert_auto_generates_id(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        mock_conn.fetchrow.return_value = {"id": "auto-generated"}
        ids = await adapter_with_mock_conn.insert("traces", [{"vector": [0.1], "metadata": {}}])
        assert ids == ["auto-generated"]
        # Verify the SQL invocation passed something for id
        assert mock_conn.fetchrow.call_args[0][1]  # doc_id arg is non-empty

    async def test_upsert_uses_on_conflict(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        mock_conn.fetchrow.return_value = {"id": "y"}
        await adapter_with_mock_conn.upsert(
            "traces", [{"id": "y", "vector": [0.1], "metadata": {}}]
        )
        sql = mock_conn.fetchrow.call_args[0][0]
        assert "ON CONFLICT" in sql
        assert "DO UPDATE" in sql

    async def test_insert_does_not_upsert(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        mock_conn.fetchrow.return_value = {"id": "z"}
        await adapter_with_mock_conn.insert(
            "traces", [{"id": "z", "vector": [0.1], "metadata": {}}]
        )
        sql = mock_conn.fetchrow.call_args[0][0]
        assert "DO NOTHING" in sql

    async def test_delete_empty_returns_true_without_call(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        result = await adapter_with_mock_conn.delete("c", [])
        assert result is True
        mock_conn.execute.assert_not_called()

    async def test_delete_executes_sql(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        result = await adapter_with_mock_conn.delete("c", ["a", "b"])
        assert result is True
        mock_conn.execute.assert_awaited_once()
        sql, ids = mock_conn.execute.call_args[0]
        assert "DELETE" in sql
        assert ids == ["a", "b"]

    async def test_get_empty_returns_empty_list(self, adapter_with_mock_conn: PgvectorAdapter):
        assert await adapter_with_mock_conn.get("c", []) == []

    async def test_get_returns_formatted_docs(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        mock_conn.fetch.return_value = [
            {"id": "a", "metadata": {"k": 1}},
            {"id": "b", "metadata": None},
        ]
        docs = await adapter_with_mock_conn.get("c", ["a", "b"])
        assert docs[0] == {"id": "a", "metadata": {"k": 1}, "vector": []}
        assert docs[1]["metadata"] == {}

    async def test_count_without_filter(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        mock_conn.fetchval.return_value = 42
        assert await adapter_with_mock_conn.count("c") == 42

    async def test_count_with_filter(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        mock_conn.fetchval.return_value = 7
        out = await adapter_with_mock_conn.count("c", filter_expr={"a": 1})
        assert out == 7
        sql = mock_conn.fetchval.call_args[0][0]
        assert "WHERE metadata @> $1::jsonb" in sql

    async def test_count_returns_zero_when_none(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        mock_conn.fetchval.return_value = None
        assert await adapter_with_mock_conn.count("c") == 0

    async def test_list_collections_returns_table_names(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        mock_conn.fetch.return_value = [
            {"table_name": "vectors_a"},
            {"table_name": "vectors_b"},
        ]
        out = await adapter_with_mock_conn.list_collections()
        assert out == ["vectors_a", "vectors_b"]

    async def test_list_collections_handles_empty(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        mock_conn.fetch.return_value = []
        assert await adapter_with_mock_conn.list_collections() == []

    async def test_create_collection_hnsw(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        ok = await adapter_with_mock_conn.create_collection("test", dimension=384)
        assert ok is True
        # Should have called execute at least 3 times (extension, table, index, GIN)
        assert mock_conn.execute.await_count >= 3

    async def test_create_collection_ivfflat(self, settings: PgvectorSettings):
        settings.index_type = IndexType.IVFFLAT  # type: ignore[misc]
        adapter = PgvectorAdapter(settings)
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=None)

        @asynccontextmanager
        async def fake_conn() -> Any:
            yield mock_conn

        adapter._connection = fake_conn  # type: ignore[assignment]
        ok = await adapter.create_collection("test", dimension=128)
        assert ok is True

    async def test_delete_collection(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        ok = await adapter_with_mock_conn.delete_collection("traces")
        assert ok is True
        sql = mock_conn.execute.call_args[0][0]
        assert "DROP TABLE IF EXISTS" in sql


# ============================== _ensure_pool error path ==============================


class TestEnsurePool:
    """The _ensure_pool method has an ImportError branch worth covering."""

    async def test_returns_existing_pool(self, settings: PgvectorSettings):
        adapter = PgvectorAdapter(settings)
        sentinel = MagicMock(name="pool")
        adapter._pool = sentinel
        assert await adapter._ensure_pool() is sentinel

    async def test_missing_dependency_raises_runtime_error(self, settings: PgvectorSettings):
        adapter = PgvectorAdapter(settings)

        # Patch the import inside _ensure_pool by removing both modules
        with patch.dict("sys.modules", {"asyncpg": None, "pgvector.asyncpg": None}):
            with pytest.raises(RuntimeError, match="asyncpg and pgvector required"):
                await adapter._ensure_pool()


# ============================== init / _ensure_extension ==============================


class TestInit:
    """init / _ensure_extension behavior."""

    async def test_init_calls_ensure_extension(
        self, adapter_with_mock_conn: PgvectorAdapter, mock_conn: AsyncMock
    ):
        # patch _ensure_pool to a no-op so init doesn't try to actually connect
        adapter_with_mock_conn._ensure_pool = AsyncMock(return_value=None)  # type: ignore[assignment]
        await adapter_with_mock_conn.init()
        # _ensure_extension calls conn.execute("CREATE EXTENSION ...")
        executed_sql = [c.args[0] for c in mock_conn.execute.await_args_list]
        assert any("CREATE EXTENSION" in s for s in executed_sql)

    async def test_init_skips_extension_if_disabled(self, settings: PgvectorSettings):
        settings.ensure_extension = False  # type: ignore[misc]
        adapter = PgvectorAdapter(settings)
        adapter._ensure_pool = AsyncMock(return_value=None)  # type: ignore[assignment]

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=None)

        @asynccontextmanager
        async def fake_conn() -> Any:
            yield mock_conn

        adapter._connection = fake_conn  # type: ignore[assignment]
        await adapter.init()
        # Should NOT have called execute since extension is disabled and pool
        # is mocked
        mock_conn.execute.assert_not_called()
