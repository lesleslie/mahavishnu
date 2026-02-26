"""Extended pgvector adapter with HNSW support for Mahavishnu.

Extends Oneiric's PgvectorAdapter to support HNSW (Hierarchical Navigable Small World)
indexing for high-performance approximate nearest neighbor search.

HNSW vs IVFFlat:
- HNSW: Better recall, higher memory, slower builds, faster queries (10K+ QPS)
- IVFFlat: Faster builds, lower memory, good for exact search (< 100K vectors)

This adapter is designed for production workloads requiring:
- Persistent vector storage
- High query throughput (1000+ QPS)
- Sub-20ms query latency
- Large-scale vector datasets (100K+ vectors)
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import uuid4

import pydantic
from pydantic import Field, SecretStr

logger = logging.getLogger(__name__)

# Safe identifier pattern for SQL
SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class IndexType(StrEnum):
    """Vector index types for pgvector."""

    HNSW = "hnsw"  # Better recall, higher memory, faster queries
    IVFFLAT = "ivfflat"  # Faster builds, lower memory


@dataclass
class HNSWConfig:
    """HNSW index configuration.

    Attributes:
        m: Number of bi-directional links (4-48, higher = better recall, more memory)
        ef_construction: Search depth during build (16-256, higher = better index, slower build)
        ef_search: Query-time search depth (10-200, higher = better recall, slower query)
    """

    m: int = 16
    ef_construction: int = 64
    ef_search: int = 40

    def __post_init__(self) -> None:
        """Validate configuration."""
        if not 4 <= self.m <= 48:
            raise ValueError(f"HNSW m must be between 4 and 48, got {self.m}")
        if not 16 <= self.ef_construction <= 256:
            raise ValueError(
                f"HNSW ef_construction must be between 16 and 256, got {self.ef_construction}"
            )
        if not 10 <= self.ef_search <= 200:
            raise ValueError(f"HNSW ef_search must be between 10 and 200, got {self.ef_search}")


@dataclass
class IVFFlatConfig:
    """IVFFlat index configuration.

    Attributes:
        lists: Number of clusters (typically sqrt(rows) for best performance)
    """

    lists: int = 100

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.lists < 1:
            raise ValueError(f"IVFFlat lists must be >= 1, got {self.lists}")


class PgvectorSettings(pydantic.BaseModel):  # type: ignore[misc]
    """Settings for Mahavishnu's pgvector adapter.

    This extends Oneiric's settings with HNSW support.
    """

    dsn: str | None = Field(default=None, description="PostgreSQL DSN (overrides other fields)")
    host: str = Field(default="localhost", description="PostgreSQL host")
    port: int = Field(default=5432, description="PostgreSQL port")
    user: str = Field(default="postgres", description="PostgreSQL user")
    password: SecretStr | None = Field(default=None, description="PostgreSQL password")
    database: str = Field(default="mahavishnu", description="PostgreSQL database name")
    db_schema: str = Field(default="public", description="Database schema")
    collection_prefix: str = Field(default="vectors_", description="Table name prefix")

    # Connection settings
    min_connections: int = Field(default=1, ge=1, description="Minimum pool connections")
    max_connections: int = Field(default=10, ge=1, description="Maximum pool connections")
    statement_timeout_ms: int | None = Field(default=None, ge=1, description="Statement timeout")
    ssl: bool = Field(default=False, description="Enable SSL/TLS")

    # Extension settings
    ensure_extension: bool = Field(default=True, description="Create vector extension if missing")

    # Index configuration
    index_type: IndexType = Field(default=IndexType.HNSW, description="Vector index type")
    hnsw_config: HNSWConfig = Field(default_factory=HNSWConfig, description="HNSW settings")
    ivfflat_config: IVFFlatConfig = Field(
        default_factory=IVFFlatConfig, description="IVFFlat settings"
    )

    # Default distance metric
    default_distance_metric: str = Field(
        default="cosine", description="Default distance metric (cosine, euclidean, dot_product)"
    )


class PgvectorAdapter:
    """Production pgvector adapter with HNSW support.

    Features:
    - HNSW indexing for high QPS workloads
    - IVFFlat indexing for smaller datasets
    - Async connection pooling via asyncpg
    - Automatic schema management
    - Batch operations for efficiency

    Example:
        >>> settings = PgvectorSettings(
        ...     host="localhost",
        ...     database="mahavishnu",
        ...     index_type=IndexType.HNSW,
        ...     hnsw_config=HNSWConfig(m=16, ef_construction=64)
        ... )
        >>> adapter = PgvectorAdapter(settings)
        >>> await adapter.init()
        >>> await adapter.create_collection("traces", dimension=384)
        >>> await adapter.insert("traces", [VectorDocument(...)])
        >>> results = await adapter.search("traces", query_vector, limit=10)
    """

    def __init__(self, settings: PgvectorSettings) -> None:
        """Initialize adapter with settings.

        Args:
            settings: PgvectorSettings configuration
        """
        self._settings = settings
        self._pool: Any | None = None
        self._logger = logging.getLogger("mahavishnu.adapters.pgvector")

    async def init(self) -> None:
        """Initialize connection pool and ensure extension."""
        await self._ensure_pool()
        if self._settings.ensure_extension:
            await self._ensure_extension()
        self._logger.info(
            "pgvector-adapter-init",
            extra={"index_type": self._settings.index_type.value},
        )

    async def health(self) -> bool:
        """Check connection health.

        Returns:
            True if healthy, False otherwise
        """
        try:
            async with self._connection() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception as exc:
            self._logger.warning("pgvector-health-failed", extra={"error": str(exc)})
            return False

    async def cleanup(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._logger.info("pgvector-cleanup-complete")

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 10,
        filter_expr: dict[str, Any] | None = None,
        include_vectors: bool = False,
        ef_search: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar vectors.

        Args:
            collection: Collection/table name
            query_vector: Query embedding vector
            limit: Maximum results to return
            filter_expr: Optional metadata filter (JSONB containment)
            include_vectors: Include vectors in results
            ef_search: Override HNSW ef_search for this query

        Returns:
            List of search results with id, score, metadata, and optionally vector
        """
        table = self._qualified_table(collection)
        operator = self._distance_operator()
        params: list[Any] = []

        # Set ef_search for HNSW queries if specified
        if ef_search is not None and self._settings.index_type == IndexType.HNSW:
            async with self._connection() as conn:
                await conn.execute(f"SET LOCAL hnsw.ef_search = {ef_search}")

        # Build query
        select_fields = f"id, metadata, {'embedding' if include_vectors else 'NULL'} AS embedding, "
        select_fields += f"embedding {operator} $1::vector AS distance"

        sql_parts = [f"SELECT {select_fields} FROM {table}"]
        params.append(query_vector)

        if filter_expr:
            sql_parts.append("WHERE metadata @> $2::jsonb")
            params.append(json.dumps(filter_expr))
            limit_param = "$3"
        else:
            limit_param = "$2"

        params.append(limit)
        sql_parts.append(f"ORDER BY distance ASC LIMIT {limit_param}")

        async with self._connection() as conn:
            records = await conn.fetch("\n".join(sql_parts), *params)

        return [
            {
                "id": record["id"],
                "score": float(record["distance"]),
                "metadata": record["metadata"] or {},
                "vector": record["embedding"] if include_vectors else None,
            }
            for record in records
        ]

    async def insert(
        self,
        collection: str,
        documents: list[dict[str, Any]],
    ) -> list[str]:
        """Insert documents into collection.

        Args:
            collection: Collection/table name
            documents: List of documents with id, vector, metadata

        Returns:
            List of inserted document IDs
        """
        return await self._write_documents(collection, documents, upsert=False)

    async def upsert(
        self,
        collection: str,
        documents: list[dict[str, Any]],
    ) -> list[str]:
        """Upsert documents into collection.

        Args:
            collection: Collection/table name
            documents: List of documents with id, vector, metadata

        Returns:
            List of upserted document IDs
        """
        return await self._write_documents(collection, documents, upsert=True)

    async def delete(self, collection: str, ids: list[str]) -> bool:
        """Delete documents by ID.

        Args:
            collection: Collection/table name
            ids: List of document IDs to delete

        Returns:
            True if successful
        """
        if not ids:
            return True

        table = self._qualified_table(collection)
        async with self._connection() as conn:
            await conn.execute(f"DELETE FROM {table} WHERE id = ANY($1::text[])", ids)
        return True

    async def get(
        self,
        collection: str,
        ids: list[str],
        include_vectors: bool = False,
    ) -> list[dict[str, Any]]:
        """Get documents by ID.

        Args:
            collection: Collection/table name
            ids: List of document IDs
            include_vectors: Include vectors in results

        Returns:
            List of documents
        """
        if not ids:
            return []

        table = self._qualified_table(collection)
        fields = "id, metadata" + (", embedding" if include_vectors else "")

        async with self._connection() as conn:
            records = await conn.fetch(
                f"SELECT {fields} FROM {table} WHERE id = ANY($1::text[])", ids
            )

        return [
            {
                "id": record["id"],
                "metadata": record["metadata"] or {},
                "vector": record["embedding"] if include_vectors else [],
            }
            for record in records
        ]

    async def count(
        self,
        collection: str,
        filter_expr: dict[str, Any] | None = None,
    ) -> int:
        """Count documents in collection.

        Args:
            collection: Collection/table name
            filter_expr: Optional metadata filter

        Returns:
            Document count
        """
        table = self._qualified_table(collection)

        if filter_expr:
            sql = f"SELECT COUNT(*) FROM {table} WHERE metadata @> $1::jsonb"
            params: tuple[Any, ...] = (json.dumps(filter_expr),)
        else:
            sql = f"SELECT COUNT(*) FROM {table}"
            params = ()

        async with self._connection() as conn:
            value = await conn.fetchval(sql, *params)
        return int(value or 0)

    async def create_collection(
        self,
        name: str,
        dimension: int,
        distance_metric: str = "cosine",
    ) -> bool:
        """Create a new collection with vector index.

        Args:
            name: Collection name
            dimension: Vector dimension
            distance_metric: Distance metric (cosine, euclidean, dot_product)

        Returns:
            True if successful
        """
        table_name = self._normalize_name(name)
        schema = self._sanitize_identifier(self._settings.db_schema)
        qualified = f'"{schema}"."{table_name}"'
        operator_class = self._index_operator_class(distance_metric)

        async with self._connection() as conn:
            # Ensure extension
            if self._settings.ensure_extension:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

            # Create table
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {qualified} (
                    id TEXT PRIMARY KEY,
                    embedding vector({dimension}),
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )

            # Create appropriate index
            if self._settings.index_type == IndexType.HNSW:
                config = self._settings.hnsw_config
                await conn.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS {table_name}_embedding_hnsw_idx
                    ON {qualified}
                    USING hnsw (embedding {operator_class})
                    WITH (m = {config.m}, ef_construction = {config.ef_construction})
                    """
                )
            else:  # IVFFlat
                config = self._settings.ivfflat_config
                await conn.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS {table_name}_embedding_ivf_idx
                    ON {qualified}
                    USING ivfflat (embedding {operator_class})
                    WITH (lists = {config.lists})
                    """
                )

            # Create metadata GIN index
            await conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {table_name}_metadata_idx
                ON {qualified} USING GIN (metadata)
                """
            )

        self._logger.info(
            "pgvector-collection-created",
            extra={
                "name": name,
                "dimension": dimension,
                "index_type": self._settings.index_type.value,
            },
        )
        return True

    async def delete_collection(self, name: str) -> bool:
        """Delete a collection.

        Args:
            name: Collection name

        Returns:
            True if successful
        """
        table_name = self._normalize_name(name)
        schema = self._sanitize_identifier(self._settings.db_schema)
        qualified = f'"{schema}"."{table_name}"'

        async with self._connection() as conn:
            await conn.execute(f"DROP TABLE IF EXISTS {qualified}")

        self._logger.info("pgvector-collection-deleted", extra={"name": name})
        return True

    async def list_collections(self) -> list[str]:
        """List all collections.

        Returns:
            List of collection names
        """
        prefix = self._normalize_name("")

        async with self._connection() as conn:
            records = await conn.fetch(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = $1 AND table_name LIKE $2
                """,
                self._sanitize_identifier(self._settings.db_schema),
                f"{prefix}%",
            )

        return [record["table_name"] for record in records or []]

    # Private methods

    async def _ensure_pool(self) -> Any:
        """Ensure connection pool exists."""
        if self._pool:
            return self._pool

        try:
            import asyncpg
            from pgvector.asyncpg import register_vector
        except ImportError as exc:
            raise RuntimeError(
                "asyncpg and pgvector required: pip install asyncpg pgvector"
            ) from exc

        kwargs = self._connection_kwargs()

        async def init_conn(conn: Any) -> None:
            await register_vector(conn)

        self._pool = await asyncpg.create_pool(init=init_conn, **kwargs)
        return self._pool

    async def _ensure_extension(self) -> None:
        """Ensure pgvector extension is installed."""
        async with self._connection() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

    @asynccontextmanager
    async def _connection(self) -> AsyncGenerator[Any]:
        """Get connection from pool."""
        pool = await self._ensure_pool()
        conn = await pool.acquire()
        try:
            yield conn
        finally:
            await pool.release(conn)

    def _connection_kwargs(self) -> dict[str, Any]:
        """Build connection kwargs."""
        if self._settings.dsn:
            return {"dsn": self._settings.dsn}

        kwargs: dict[str, Any] = {
            "host": self._settings.host,
            "port": self._settings.port,
            "user": self._settings.user,
            "database": self._settings.database,
            "min_size": self._settings.min_connections,
            "max_size": self._settings.max_connections,
        }

        if self._settings.password:
            kwargs["password"] = self._settings.password.get_secret_value()

        if self._settings.ssl:
            kwargs["ssl"] = True

        if self._settings.statement_timeout_ms:
            kwargs["command_timeout"] = self._settings.statement_timeout_ms / 1000

        return kwargs

    def _distance_operator(self) -> str:
        """Get distance operator for queries."""
        metric = self._settings.default_distance_metric.lower()
        if metric in {"euclidean", "l2"}:
            return "<->"
        if metric in {"dot_product", "inner_product"}:
            return "<#>"
        return "<=>"  # cosine

    def _index_operator_class(self, distance_metric: str) -> str:
        """Get index operator class."""
        metric = distance_metric.lower()
        if metric in {"euclidean", "l2"}:
            return "vector_l2_ops"
        if metric in {"dot_product", "inner_product"}:
            return "vector_ip_ops"
        return "vector_cosine_ops"

    def _qualified_table(self, collection: str) -> str:
        """Get qualified table name."""
        schema = self._sanitize_identifier(self._settings.db_schema)
        name = self._normalize_name(collection)
        return f'"{schema}"."{name}"'

    def _normalize_name(self, name: str) -> str:
        """Normalize collection name to valid table name."""
        base = f"{self._settings.collection_prefix}{name}"
        sanitized = re.sub(r"[^A-Za-z0-9_]", "_", base)
        if not sanitized:
            raise ValueError("Invalid collection name")
        if sanitized[0].isdigit():
            sanitized = f"v_{sanitized}"
        return sanitized

    def _sanitize_identifier(self, identifier: str) -> str:
        """Sanitize SQL identifier."""
        normalized = re.sub(r"[^A-Za-z0-9_]", "_", identifier)
        if not normalized:
            raise ValueError("Invalid identifier")
        if normalized[0].isdigit():
            normalized = f"v_{normalized}"
        if not SAFE_IDENTIFIER_PATTERN.fullmatch(normalized):
            raise ValueError(f"Unsafe identifier: {identifier}")
        return normalized

    async def _write_documents(
        self,
        collection: str,
        documents: list[dict[str, Any]],
        *,
        upsert: bool,
    ) -> list[str]:
        """Write documents to collection."""
        table = self._qualified_table(collection)

        statement = f"""
            INSERT INTO {table} (id, embedding, metadata)
            VALUES ($1, $2::vector, $3::jsonb)
            """
        if upsert:
            statement += """
                ON CONFLICT (id) DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                """
        else:
            statement += "ON CONFLICT (id) DO NOTHING "
        statement += "RETURNING id"

        inserted: list[str] = []
        async with self._connection() as conn:
            for doc in documents:
                doc_id = doc.get("id") or str(uuid4())
                record = await conn.fetchrow(
                    statement,
                    doc_id,
                    doc.get("vector", doc.get("embedding")),
                    json.dumps(doc.get("metadata", {})),
                )
                if record and record.get("id"):
                    inserted.append(record["id"])

        return inserted


__all__ = [
    "PgvectorAdapter",
    "PgvectorSettings",
    "HNSWConfig",
    "IVFFlatConfig",
    "IndexType",
]
