"""Integration tests for Oneiric pgvector adapter."""

import os

from oneiric.adapters.vector.common import VectorDocument
from oneiric.adapters.vector.pgvector import PgvectorAdapter, PgvectorSettings
import pytest


@pytest.mark.integration
@pytest.mark.vector
class TestOneiricPgvectorAdapter:
    """Test Oneiric's pgvector adapter functionality."""

    @pytest.fixture
    async def adapter(self):
        """Create pgvector adapter for testing."""
        # Get connection details from environment
        settings = PgvectorSettings(
            host=os.getenv("VECTOR_DB_HOST", "localhost"),
            port=int(os.getenv("VECTOR_DB_PORT", "5432")),
            user=os.getenv("VECTOR_DB_USER", "postgres"),
            password=os.getenv("VECTOR_DB_PASSWORD"),
            database=os.getenv("VECTOR_DB_NAME", "mahavishnu_test"),
            db_schema="public",
            collection_prefix="test_",
            ensure_extension=True,
            default_dimension=1536,
            default_distance_metric="cosine",
            ivfflat_lists=100,
            max_connections=5,
        )

        adapter = PgvectorAdapter(settings)
        await adapter.init()
        yield adapter
        await adapter.cleanup()

    @pytest.mark.asyncio
    async def test_adapter_initialization(self, adapter):
        """Test adapter initializes successfully."""
        assert adapter is not None
        health = await adapter.health()
        assert health is True

    @pytest.mark.asyncio
    async def test_create_collection(self, adapter):
        """Test creating a collection."""
        collection_name = "test_collection"
        success = await adapter.create_collection(
            name=collection_name, dimension=1536, distance_metric="cosine"
        )
        assert success is True

        # Verify collection exists
        collections = await adapter.list_collections()
        assert f"test_{collection_name}" in collections

    @pytest.mark.asyncio
    async def test_insert_documents(self, adapter):
        """Test inserting documents into collection."""
        collection_name = "test_insert"

        # Create collection first
        await adapter.create_collection(
            name=collection_name,
            dimension=3,  # Small dimension for testing
            distance_metric="cosine",
        )

        # Insert test documents
        documents = [
            VectorDocument(
                id="doc1", vector=[1.0, 0.0, 0.0], metadata={"category": "tech", "title": "AI"}
            ),
            VectorDocument(
                id="doc2", vector=[0.0, 1.0, 0.0], metadata={"category": "tech", "title": "ML"}
            ),
            VectorDocument(
                id="doc3",
                vector=[0.0, 0.0, 1.0],
                metadata={"category": "science", "title": "Physics"},
            ),
        ]

        ids = await adapter.insert(collection_name, documents)
        assert len(ids) == 3
        assert "doc1" in ids
        assert "doc2" in ids
        assert "doc3" in ids

    @pytest.mark.asyncio
    async def test_vector_search(self, adapter):
        """Test vector similarity search."""
        collection_name = "test_search"

        # Create collection and insert documents
        await adapter.create_collection(name=collection_name, dimension=3, distance_metric="cosine")

        documents = [
            VectorDocument(id="doc1", vector=[1.0, 0.0, 0.0], metadata={"category": "tech"}),
            VectorDocument(id="doc2", vector=[0.9, 0.1, 0.0], metadata={"category": "tech"}),
            VectorDocument(id="doc3", vector=[0.0, 0.0, 1.0], metadata={"category": "science"}),
        ]
        await adapter.insert(collection_name, documents)

        # Search for similar vectors
        results = await adapter.search(
            collection=collection_name, query_vector=[1.0, 0.0, 0.0], limit=2, include_vectors=False
        )

        assert len(results) == 2
        assert results[0].id == "doc1"  # Most similar (exact match)
        assert results[0].score < 0.1  # Should be very close
        assert results[0].metadata == {"category": "tech"}

    @pytest.mark.asyncio
    async def test_search_with_metadata_filter(self, adapter):
        """Test vector search with metadata filtering."""
        collection_name = "test_filter"

        await adapter.create_collection(name=collection_name, dimension=3, distance_metric="cosine")

        documents = [
            VectorDocument(
                id="doc1", vector=[1.0, 0.0, 0.0], metadata={"category": "tech", "tag": "ai"}
            ),
            VectorDocument(
                id="doc2",
                vector=[0.9, 0.1, 0.0],
                metadata={"category": "science", "tag": "physics"},
            ),
            VectorDocument(
                id="doc3", vector=[0.8, 0.2, 0.0], metadata={"category": "tech", "tag": "ml"}
            ),
        ]
        await adapter.insert(collection_name, documents)

        # Search with metadata filter
        results = await adapter.search(
            collection=collection_name,
            query_vector=[1.0, 0.0, 0.0],
            limit=10,
            filter_expr={"category": "tech"},
        )

        assert len(results) == 2
        assert all(r.metadata["category"] == "tech" for r in results)

    @pytest.mark.asyncio
    async def test_upsert_documents(self, adapter):
        """Test upserting documents (insert or update)."""
        collection_name = "test_upsert"

        await adapter.create_collection(name=collection_name, dimension=3, distance_metric="cosine")

        # Insert initial documents
        documents = [
            VectorDocument(id="doc1", vector=[1.0, 0.0, 0.0], metadata={"version": 1}),
        ]
        await adapter.insert(collection_name, documents)

        # Upsert to update doc1 and add doc2
        updated_documents = [
            VectorDocument(
                id="doc1",
                vector=[0.9, 0.1, 0.0],  # Updated vector
                metadata={"version": 2},  # Updated metadata
            ),
            VectorDocument(id="doc2", vector=[0.0, 1.0, 0.0], metadata={"version": 1}),
        ]
        ids = await adapter.upsert(collection_name, updated_documents)

        assert len(ids) == 2

        # Verify doc1 was updated
        docs = await adapter.get(collection_name, ["doc1"], include_vectors=True)
        assert len(docs) == 1
        assert docs[0].vector == [0.9, 0.1, 0.0]
        assert docs[0].metadata == {"version": 2}

    @pytest.mark.asyncio
    async def test_get_documents(self, adapter):
        """Test retrieving documents by IDs."""
        collection_name = "test_get"

        await adapter.create_collection(name=collection_name, dimension=3, distance_metric="cosine")

        documents = [
            VectorDocument(id="doc1", vector=[1.0, 0.0, 0.0], metadata={"title": "Doc 1"}),
            VectorDocument(id="doc2", vector=[0.0, 1.0, 0.0], metadata={"title": "Doc 2"}),
        ]
        await adapter.insert(collection_name, documents)

        # Get documents without vectors
        docs = await adapter.get(collection_name, ["doc1", "doc2"], include_vectors=False)
        assert len(docs) == 2
        assert docs[0].id == "doc1"
        assert docs[0].vector == []  # Empty when not included
        assert docs[0].metadata == {"title": "Doc 1"}

        # Get documents with vectors
        docs_with_vectors = await adapter.get(collection_name, ["doc1"], include_vectors=True)
        assert len(docs_with_vectors) == 1
        assert docs_with_vectors[0].vector == [1.0, 0.0, 0.0]

    @pytest.mark.asyncio
    async def test_count_documents(self, adapter):
        """Test counting documents."""
        collection_name = "test_count"

        await adapter.create_collection(name=collection_name, dimension=3, distance_metric="cosine")

        documents = [
            VectorDocument(
                id=f"doc{i}",
                vector=[1.0, 0.0, 0.0],
                metadata={"category": "tech" if i % 2 == 0 else "science"},
            )
            for i in range(10)
        ]
        await adapter.insert(collection_name, documents)

        # Count all documents
        total = await adapter.count(collection_name)
        assert total == 10

        # Count with filter
        tech_count = await adapter.count(collection_name, filter_expr={"category": "tech"})
        assert tech_count == 5

    @pytest.mark.asyncio
    async def test_delete_documents(self, adapter):
        """Test deleting documents."""
        collection_name = "test_delete"

        await adapter.create_collection(name=collection_name, dimension=3, distance_metric="cosine")

        documents = [
            VectorDocument(id="doc1", vector=[1.0, 0.0, 0.0], metadata={}),
            VectorDocument(id="doc2", vector=[0.0, 1.0, 0.0], metadata={}),
        ]
        await adapter.insert(collection_name, documents)

        # Delete one document
        success = await adapter.delete(collection_name, ["doc1"])
        assert success is True

        # Verify deletion
        remaining = await adapter.count(collection_name)
        assert remaining == 1

    @pytest.mark.asyncio
    async def test_delete_collection(self, adapter):
        """Test deleting a collection."""
        collection_name = "test_drop"

        await adapter.create_collection(name=collection_name, dimension=3, distance_metric="cosine")

        # Verify collection exists
        collections = await adapter.list_collections()
        assert f"test_{collection_name}" in collections

        # Delete collection
        success = await adapter.delete_collection(collection_name)
        assert success is True

        # Verify deletion
        collections = await adapter.list_collections()
        assert f"test_{collection_name}" not in collections

    @pytest.mark.asyncio
    async def test_dynamic_collection_access(self, adapter):
        """Test accessing collections dynamically via attributes."""
        collection_name = "test_dynamic"

        await adapter.create_collection(name=collection_name, dimension=3, distance_metric="cosine")

        # Access collection dynamically
        collection = getattr(adapter, collection_name)
        assert collection is not None
        assert collection.name == collection_name

        # Use collection interface
        documents = [VectorDocument(id="doc1", vector=[1.0, 0.0, 0.0], metadata={})]
        ids = await collection.insert(documents)
        assert len(ids) == 1

        results = await collection.search(query_vector=[1.0, 0.0, 0.0], limit=1)
        assert len(results) == 1
        assert results[0].id == "doc1"


@pytest.mark.unit
class TestPgvectorSettings:
    """Test PgvectorSettings configuration."""

    def test_default_settings(self):
        """Test default settings values."""
        settings = PgvectorSettings()

        assert settings.host == "localhost"
        assert settings.port == 5432
        assert settings.user == "postgres"
        assert settings.database == "postgres"
        assert settings.db_schema == "public"
        assert settings.collection_prefix == "vectors_"
        assert settings.default_dimension == 1536
        assert settings.default_distance_metric == "cosine"
        assert settings.ensure_extension is True
        assert settings.ivfflat_lists == 100
        assert settings.max_connections == 10

    def test_custom_settings(self):
        """Test custom settings values."""
        settings = PgvectorSettings(
            host="custom-host",
            port=5433,
            user="custom-user",
            password="secret-password",
            database="custom-db",
            db_schema="custom-schema",
            collection_prefix="custom_prefix_",
            default_dimension=768,
            default_distance_metric="euclidean",
            ensure_extension=False,
            ivfflat_lists=200,
            max_connections=20,
        )

        assert settings.host == "custom-host"
        assert settings.port == 5433
        assert settings.user == "custom-user"
        assert settings.password.get_secret_value() == "secret-password"
        assert settings.database == "custom-db"
        assert settings.db_schema == "custom-schema"
        assert settings.collection_prefix == "custom_prefix_"
        assert settings.default_dimension == 768
        assert settings.default_distance_metric == "euclidean"
        assert settings.ensure_extension is False
        assert settings.ivfflat_lists == 200
        assert settings.max_connections == 20

    def test_dsn_override(self):
        """Test DSN string overrides discrete settings."""
        settings = PgvectorSettings(
            dsn="postgresql://user:pass@host:5433/dbname",
            host="localhost",  # Should be ignored
            port=5432,  # Should be ignored
        )

        assert settings.dsn == "postgresql://user:pass@host:5433/dbname"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
