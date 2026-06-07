"""Unit tests for DocumentRepository (mahavishnu.core.repositories.documents)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from mahavishnu.core.repositories.base import RepositoryError
from mahavishnu.core.repositories.documents import (
    DocumentCreate,
    DocumentRepository,
    DocumentSearchResult,
    DocumentUpdate,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Helpers and Fixtures
# =============================================================================


def make_doc_row(**overrides):
    base = {
        "id": uuid4(),
        "source_type": "blog",
        "source_id": None,
        "source_key": "post-1",
        "content": "Hello world",
        "repository": "mahavishnu",
        "system_name": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "metadata": {},
    }
    base.update(overrides)
    return base


class _FakeConn:
    def __init__(self, fetchrow_result=None, fetch_results=None, execute_result="DELETE 1"):
        self._fetchrow_result = fetchrow_result
        self._fetch_results = fetch_results or []
        self._execute_result = execute_result
        self.last_query = None
        self.last_params = None

    async def fetchrow(self, query, *params):
        self.last_query = query
        self.last_params = params
        return self._fetchrow_result

    async def fetch(self, query, *params):
        self.last_query = query
        self.last_params = params
        return self._fetch_results

    async def execute(self, query, *params):
        self.last_query = query
        self.last_params = params
        return self._execute_result


def patch_repo_connection(repo, conn: _FakeConn) -> None:
    @asynccontextmanager
    async def fake_connection():
        yield conn

    @asynccontextmanager
    async def fake_transaction():
        yield conn

    repo.connection = fake_connection  # type: ignore[assignment]
    repo.transaction = fake_transaction  # type: ignore[assignment]


@pytest.fixture
def repo():
    return DocumentRepository()


@pytest.fixture
def sample_create():
    return DocumentCreate(
        source_type="blog",
        source_key="post-1",
        content="Hello world",
    )


# =============================================================================
# Model Tests
# =============================================================================


class TestDocumentModels:
    def test_create_required_fields(self):
        d = DocumentCreate(source_type="blog", source_key="k1", content="c")
        assert d.source_type == "blog"
        assert d.source_key == "k1"
        assert d.content == "c"
        assert d.metadata == {}

    def test_update_all_optional(self):
        u = DocumentUpdate()
        assert u.content is None
        assert u.metadata is None

    def test_search_result_score_bounds(self):
        with pytest.raises(Exception):
            DocumentSearchResult(
                document=make_doc_row(),
                score=1.5,
            )
        with pytest.raises(Exception):
            DocumentSearchResult(
                document=make_doc_row(),
                score=-0.1,
            )

    def test_search_result_default_match_type(self):
        row = make_doc_row()
        from mahavishnu.core.repositories.documents import DocumentRead

        r = DocumentSearchResult(
            document=DocumentRead(
                id=row["id"],
                source_type=row["source_type"],
                source_key=row["source_key"],
                content=row["content"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            ),
            score=0.5,
        )
        assert r.match_type == "hybrid"


# =============================================================================
# Init
# =============================================================================


class TestInit:
    def test_create_raises_not_implemented(self, repo):
        import asyncio

        with pytest.raises(NotImplementedError):
            asyncio.run(repo.create(DocumentCreate(source_type="x", source_key="y", content="z")))


# =============================================================================
# create_document
# =============================================================================


class TestCreateDocument:
    async def test_create_document_success(self, repo, sample_create):
        row = make_doc_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.create_document(sample_create)
        assert result.source_key == "post-1"
        assert "INSERT INTO search.documents" in conn.last_query
        assert "RETURNING *" in conn.last_query

    async def test_create_document_passes_fields_in_order(self, repo, sample_create):
        row = make_doc_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        await repo.create_document(sample_create)
        params = conn.last_params
        # Order: source_type, source_id, source_key, content, repository, system_name, metadata
        assert params[0] == "blog"
        assert params[1] is None
        assert params[2] == "post-1"
        assert params[3] == "Hello world"

    async def test_create_document_with_source_id(self, repo):
        sid = uuid4()
        row = make_doc_row(source_id=sid)
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        d = DocumentCreate(
            source_type="blog",
            source_id=sid,
            source_key="k1",
            content="c",
        )
        result = await repo.create_document(d)
        assert result.source_id == sid

    async def test_create_document_no_row_raises(self, repo, sample_create):
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        with pytest.raises(RepositoryError):
            await repo.create_document(sample_create)


# =============================================================================
# get_document
# =============================================================================


class TestGetDocument:
    async def test_get_document_found(self, repo):
        doc_id = uuid4()
        row = make_doc_row(id=doc_id, content="hi")
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.get_document(doc_id)
        assert result is not None
        assert result.id == doc_id
        assert result.content == "hi"
        assert "WHERE id = $1" in conn.last_query

    async def test_get_document_not_found(self, repo):
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        result = await repo.get_document(uuid4())
        assert result is None


# =============================================================================
# get_document_by_key
# =============================================================================


class TestGetDocumentByKey:
    async def test_get_by_key_with_type(self, repo):
        row = make_doc_row(source_key="k1")
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.get_document_by_key("k1", "blog")
        assert result is not None
        assert "source_key = $1 AND source_type = $2" in conn.last_query
        assert conn.last_params == ("k1", "blog")

    async def test_get_by_key_without_type(self, repo):
        row = make_doc_row(source_key="k1")
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.get_document_by_key("k1")
        assert result is not None
        assert "source_key = $1" in conn.last_query
        assert "source_type" not in conn.last_query.split("WHERE")[1].split("ORDER BY")[0]

    async def test_get_by_key_not_found(self, repo):
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        result = await repo.get_document_by_key("missing")
        assert result is None


# =============================================================================
# update_document
# =============================================================================


class TestUpdateDocument:
    async def test_update_no_fields_returns_current(self, repo):
        row = make_doc_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.update_document(uuid4(), DocumentUpdate())
        assert result is not None
        # Should have used SELECT (via get_document)
        assert "SELECT" in conn.last_query

    async def test_update_content_only(self, repo):
        row = make_doc_row(content="new content")
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.update_document(uuid4(), DocumentUpdate(content="new content"))
        assert result is not None
        assert "UPDATE search.documents" in conn.last_query
        assert "content = $2" in conn.last_query
        assert "updated_at = $3" in conn.last_query

    async def test_update_repository_only(self, repo):
        row = make_doc_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        await repo.update_document(uuid4(), DocumentUpdate(repository="other-repo"))
        assert "repository = $2" in conn.last_query

    async def test_update_system_name_only(self, repo):
        row = make_doc_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        await repo.update_document(uuid4(), DocumentUpdate(system_name="sys"))
        assert "system_name = $2" in conn.last_query

    async def test_update_metadata_uses_merge(self, repo):
        row = make_doc_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        await repo.update_document(uuid4(), DocumentUpdate(metadata={"k": "v"}))
        assert "metadata = metadata || $2::jsonb" in conn.last_query

    async def test_update_all_fields(self, repo):
        row = make_doc_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        await repo.update_document(
            uuid4(),
            DocumentUpdate(
                content="c",
                repository="r",
                system_name="s",
                metadata={"k": "v"},
            ),
        )
        # All four fields, all six params: $1=id, $2..$5=fields, $6=updated_at
        assert "$6" in conn.last_query
        assert "content = $2" in conn.last_query

    async def test_update_returns_none_when_missing(self, repo):
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        result = await repo.update_document(uuid4(), DocumentUpdate(content="x"))
        assert result is None


# =============================================================================
# delete_document
# =============================================================================


class TestDeleteDocument:
    async def test_delete_document_success(self, repo):
        conn = _FakeConn(execute_result="DELETE 1")
        patch_repo_connection(repo, conn)

        result = await repo.delete_document(uuid4())
        assert result is True
        assert "DELETE FROM search.documents" in conn.last_query

    async def test_delete_document_not_found(self, repo):
        conn = _FakeConn(execute_result="DELETE 0")
        patch_repo_connection(repo, conn)

        result = await repo.delete_document(uuid4())
        assert result is False


# =============================================================================
# search_documents
# =============================================================================


class TestSearchDocuments:
    async def test_search_without_repository(self, repo):
        row = make_doc_row()
        row["score"] = 0.8
        conn = _FakeConn(fetch_results=[row])
        patch_repo_connection(repo, conn)

        result = await repo.search_documents("query text")
        assert len(result) == 1
        assert "to_tsvector" in conn.last_query
        assert "ts_rank" in conn.last_query
        assert result[0].match_type == "lexical"

    async def test_search_with_repository(self, repo):
        row = make_doc_row()
        row["score"] = 0.5
        conn = _FakeConn(fetch_results=[row])
        patch_repo_connection(repo, conn)

        result = await repo.search_documents("query", repository="mahavishnu")
        assert "repository = $2" in conn.last_query
        assert conn.last_params[1] == "mahavishnu"
        assert len(result) == 1

    async def test_search_empty(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        result = await repo.search_documents("nothing")
        assert result == []

    async def test_search_score_normalized(self, repo):
        row = make_doc_row()
        # Score 5.0 raw -> 5/10 = 0.5 normalized
        row["score"] = 5.0
        conn = _FakeConn(fetch_results=[row])
        patch_repo_connection(repo, conn)

        result = await repo.search_documents("q")
        assert 0.0 <= result[0].score <= 1.0

    async def test_search_score_clamped_high(self, repo):
        row = make_doc_row()
        row["score"] = 999.0
        conn = _FakeConn(fetch_results=[row])
        patch_repo_connection(repo, conn)

        result = await repo.search_documents("q")
        assert result[0].score == 1.0

    async def test_search_score_clamped_low(self, repo):
        row = make_doc_row()
        row["score"] = -1.0
        conn = _FakeConn(fetch_results=[row])
        patch_repo_connection(repo, conn)

        result = await repo.search_documents("q")
        assert result[0].score == 0.0


# =============================================================================
# list_documents
# =============================================================================


class TestListDocuments:
    async def test_list_all(self, repo):
        conn = _FakeConn(fetch_results=[make_doc_row()])
        patch_repo_connection(repo, conn)

        result = await repo.list_documents()
        assert len(result) == 1
        assert "ORDER BY created_at DESC" in conn.last_query

    async def test_list_by_repository(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        await repo.list_documents(repository="mahavishnu")
        assert "WHERE repository = $1" in conn.last_query

    async def test_list_by_source_type(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        await repo.list_documents(source_type="blog")
        assert "WHERE source_type = $1" in conn.last_query

    async def test_list_by_repo_and_type(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        await repo.list_documents(repository="mahavishnu", source_type="blog")
        assert "repository = $1 AND source_type = $2" in conn.last_query

    async def test_list_pagination(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        await repo.list_documents(limit=5, offset=10)
        assert conn.last_params[0] == 5
        assert conn.last_params[1] == 10


# =============================================================================
# _row_to_model
# =============================================================================


class TestRowToModel:
    def test_row_to_model_defaults(self, repo):
        row = make_doc_row(metadata=None)
        model = repo._row_to_model(row)
        assert model.metadata == {}

    def test_row_to_model_preserves_fields(self, repo):
        doc_id = uuid4()
        row = make_doc_row(
            id=doc_id,
            source_type="doc",
            source_key="k1",
            content="c",
            repository="r",
            system_name="s",
            metadata={"k": "v"},
        )
        model = repo._row_to_model(row)
        assert model.id == doc_id
        assert model.source_type == "doc"
        assert model.source_key == "k1"
        assert model.content == "c"
        assert model.repository == "r"
        assert model.system_name == "s"
        assert model.metadata == {"k": "v"}


# =============================================================================
# __all__ exports
# =============================================================================


class TestExports:
    def test_all_exports(self):
        from mahavishnu.core.repositories import documents as d

        for name in (
            "DocumentCreate",
            "DocumentRead",
            "DocumentUpdate",
            "DocumentSearchResult",
            "DocumentRepository",
        ):
            assert name in d.__all__
