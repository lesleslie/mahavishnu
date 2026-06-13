"""Coverage tests for mahavishnu.core.repositories.documents module.

Targets the DocumentRepository and its Pydantic models (DocumentCreate,
DocumentRead, DocumentUpdate, DocumentSearchResult). Mocks the database
context managers (connection/transaction) and the asyncpg connection
methods (fetchrow, fetch, execute) so the SQL never runs.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from mahavishnu.core.repositories.base import BaseRepository, RepositoryError
from mahavishnu.core.repositories.documents import (
    DocumentCreate,
    DocumentRead,
    DocumentRepository,
    DocumentSearchResult,
    DocumentUpdate,
)


# ---------------------------------------------------------------------------
# Helpers: fake asyncpg connection + pool wiring
# ---------------------------------------------------------------------------


def make_row(
    *,
    row_id: UUID | None = None,
    source_type: str = "repo",
    source_id: UUID | None = None,
    source_key: str = "key-1",
    content: str = "hello world",
    repository: str | None = "repo-1",
    system_name: str | None = "sys-1",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
    score: float | None = None,
) -> dict[str, Any]:
    """Build a dict that mimics an asyncpg Record (dict-style access)."""
    now = datetime.now(UTC)
    row: dict[str, Any] = {
        "id": row_id or uuid4(),
        "source_type": source_type,
        "source_id": source_id,
        "source_key": source_key,
        "content": content,
        "repository": repository,
        "system_name": system_name,
        "created_at": created_at or now,
        "updated_at": updated_at or now,
        "metadata": metadata if metadata is not None else {},
    }
    if score is not None:
        row["score"] = score
    return row


class FakeConn:
    """In-memory fake asyncpg connection with record-style dict access."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = list(rows or [])
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []
        # Index of next row to return from fetchrow
        self._fetchrow_idx = 0

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.fetchrow_calls.append((query, args))
        if self._rows:
            row = self._rows[self._fetchrow_idx]
            self._fetchrow_idx += 1
            return row
        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.fetch_calls.append((query, args))
        return list(self._rows)

    async def execute(self, query: str, *args: Any) -> str:
        self.execute_calls.append((query, args))
        return "DELETE 1"


class FakeDatabase:
    """Stands in for the real Database; offers connection() and transaction() CM."""

    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn
        self.connection_calls = 0
        self.transaction_calls = 0

    @asynccontextmanager
    async def connection(self):
        self.connection_calls += 1
        yield self._conn

    @asynccontextmanager
    async def transaction(self):
        self.transaction_calls += 1
        yield self._conn


def make_repo(conn: FakeConn) -> DocumentRepository:
    """Build a DocumentRepository wired to a FakeDatabase with one FakeConn."""
    repo = DocumentRepository(database=FakeDatabase(conn))  # type: ignore[arg-type]
    return repo


# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPydanticModels:
    def test_document_create_required_fields(self) -> None:
        d = DocumentCreate(source_type="repo", source_key="k1", content="body")
        assert d.source_type == "repo"
        assert d.source_key == "k1"
        assert d.content == "body"
        assert d.source_id is None
        assert d.repository is None
        assert d.system_name is None
        assert d.metadata == {}

    def test_document_create_full_fields(self) -> None:
        sid = uuid4()
        d = DocumentCreate(
            source_type="repo",
            source_id=sid,
            source_key="k1",
            content="body",
            repository="r1",
            system_name="s1",
            metadata={"a": 1},
        )
        assert d.source_id == sid
        assert d.repository == "r1"
        assert d.system_name == "s1"
        assert d.metadata == {"a": 1}

    def test_document_create_missing_required_raises(self) -> None:
        with pytest.raises(ValidationError):
            DocumentCreate(source_type="repo", source_key="k1")  # type: ignore[call-arg]

    def test_document_read_parses(self) -> None:
        rid = uuid4()
        d = DocumentRead(
            id=rid,
            source_type="repo",
            source_key="k1",
            content="body",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert d.id == rid
        assert d.metadata == {}

    def test_document_update_all_optional(self) -> None:
        d = DocumentUpdate()
        assert d.content is None
        assert d.repository is None
        assert d.system_name is None
        assert d.metadata is None

    def test_document_search_result_validation(self) -> None:
        rid = uuid4()
        doc = DocumentRead(
            id=rid,
            source_type="repo",
            source_key="k1",
            content="body",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        r = DocumentSearchResult(document=doc, score=0.5)
        assert r.score == 0.5
        assert r.match_type == "hybrid"

    def test_document_search_result_score_bounds(self) -> None:
        rid = uuid4()
        doc = DocumentRead(
            id=rid,
            source_type="repo",
            source_key="k1",
            content="body",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        with pytest.raises(ValidationError):
            DocumentSearchResult(document=doc, score=1.5)
        with pytest.raises(ValidationError):
            DocumentSearchResult(document=doc, score=-0.1)


# ---------------------------------------------------------------------------
# Abstract base + NotImplementedError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBaseClassBehavior:
    def test_create_method_raises_not_implemented(self) -> None:
        conn = FakeConn()
        repo = make_repo(conn)
        with pytest.raises(NotImplementedError, match="create_document"):
            import asyncio
            asyncio.run(repo.create(DocumentCreate(
                source_type="t", source_key="k", content="c"
            )))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# create_document
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateDocument:
    async def test_create_document_success(self) -> None:
        row = make_row()
        conn = FakeConn(rows=[row])
        repo = make_repo(conn)

        data = DocumentCreate(
            source_type="repo", source_key="key-1", content="hello world"
        )
        result = await repo.create_document(data)

        assert isinstance(result, DocumentRead)
        assert result.id == row["id"]
        assert result.source_key == "key-1"
        assert result.content == "hello world"
        # Used transaction context
        assert conn.fetchrow_calls and len(conn.fetchrow_calls) == 1

    async def test_create_document_no_row_raises(self) -> None:
        conn = FakeConn(rows=[])  # fetchrow returns None
        repo = make_repo(conn)
        data = DocumentCreate(
            source_type="repo", source_key="missing", content="x"
        )
        with pytest.raises(RepositoryError) as exc:
            await repo.create_document(data)
        assert exc.value.operation == "create_document"
        assert "Failed to create document" in str(exc.value)

    async def test_create_document_db_exception_wrapped(self) -> None:
        class BoomConn(FakeConn):
            async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
                raise RuntimeError("db down")

        conn = BoomConn()
        repo = make_repo(conn)
        with pytest.raises(RepositoryError) as exc:
            await repo.create_document(
                DocumentCreate(source_type="t", source_key="k", content="c")
            )
        assert exc.value.operation == "create_document"
        assert "db down" in str(exc.value)


# ---------------------------------------------------------------------------
# get_document
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDocument:
    async def test_get_document_found(self) -> None:
        doc_id = uuid4()
        row = make_row(row_id=doc_id)
        conn = FakeConn(rows=[row])
        repo = make_repo(conn)

        result = await repo.get_document(doc_id)
        assert result is not None
        assert result.id == doc_id

    async def test_get_document_not_found_returns_none(self) -> None:
        conn = FakeConn(rows=[])
        repo = make_repo(conn)
        assert await repo.get_document(uuid4()) is None

    async def test_get_document_exception_wrapped(self) -> None:
        class BoomConn(FakeConn):
            async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
                raise RuntimeError("select failed")

        conn = BoomConn()
        repo = make_repo(conn)
        with pytest.raises(RepositoryError) as exc:
            await repo.get_document(uuid4())
        assert exc.value.operation == "get_document"


# ---------------------------------------------------------------------------
# get_document_by_key
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDocumentByKey:
    async def test_with_source_type(self) -> None:
        row = make_row(source_type="wiki", source_key="k42")
        conn = FakeConn(rows=[row])
        repo = make_repo(conn)
        result = await repo.get_document_by_key("k42", "wiki")
        assert result is not None
        assert result.source_key == "k42"
        # Second positional arg should be source_type
        call_args = conn.fetchrow_calls[0][1]
        assert "k42" in call_args
        assert "wiki" in call_args

    async def test_without_source_type(self) -> None:
        row = make_row(source_key="k7")
        conn = FakeConn(rows=[row])
        repo = make_repo(conn)
        result = await repo.get_document_by_key("k7")
        assert result is not None
        assert result.source_key == "k7"
        call_args = conn.fetchrow_calls[0][1]
        assert call_args == ("k7",)

    async def test_returns_none_when_not_found(self) -> None:
        conn = FakeConn(rows=[])
        repo = make_repo(conn)
        assert await repo.get_document_by_key("absent", "t") is None

    async def test_exception_wrapped(self) -> None:
        class BoomConn(FakeConn):
            async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
                raise RuntimeError("key lookup failed")

        conn = BoomConn()
        repo = make_repo(conn)
        with pytest.raises(RepositoryError) as exc:
            await repo.get_document_by_key("k")
        assert exc.value.operation == "get_document_by_key"


# ---------------------------------------------------------------------------
# update_document
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateDocument:
    async def test_no_fields_set_returns_existing(self) -> None:
        """When all fields are None, update_document falls through to get_document."""
        doc_id = uuid4()
        row = make_row(row_id=doc_id)
        conn = FakeConn(rows=[row])
        repo = make_repo(conn)

        result = await repo.update_document(doc_id, DocumentUpdate())
        assert result is not None
        assert result.id == doc_id
        # The get path uses _SELECT_BY_ID and the connection() context
        assert conn.fetchrow_calls
        assert "WHERE id = $1" in conn.fetchrow_calls[0][0]

    async def test_update_with_metadata_only(self) -> None:
        """Single field metadata uses jsonb || merge."""
        doc_id = uuid4()
        row = make_row(row_id=doc_id)
        conn = FakeConn(rows=[row])
        repo = make_repo(conn)

        result = await repo.update_document(
            doc_id, DocumentUpdate(metadata={"tag": "x"})
        )
        assert result is not None
        # Verify it picked the single-field metadata query
        sql, params = conn.fetchrow_calls[0]
        assert "metadata = metadata || $2::jsonb" in sql
        # params: document_id, metadata dict, now-timestamp
        assert params[0] == doc_id
        assert params[1] == {"tag": "x"}

    async def test_update_with_content_only(self) -> None:
        doc_id = uuid4()
        row = make_row(row_id=doc_id)
        conn = FakeConn(rows=[row])
        repo = make_repo(conn)

        result = await repo.update_document(
            doc_id, DocumentUpdate(content="new body")
        )
        assert result is not None
        sql, params = conn.fetchrow_calls[0]
        assert "content = $2" in sql
        assert params[0] == doc_id
        assert params[1] == "new body"

    async def test_update_all_four_fields(self) -> None:
        doc_id = uuid4()
        row = make_row(row_id=doc_id)
        conn = FakeConn(rows=[row])
        repo = make_repo(conn)

        result = await repo.update_document(
            doc_id,
            DocumentUpdate(
                content="x", repository="r", system_name="s", metadata={"k": "v"}
            ),
        )
        assert result is not None
        sql, params = conn.fetchrow_calls[0]
        # All four fields plus document_id and now = 6 params
        assert sql.count("$") == 6
        assert "content = $2" in sql
        assert "metadata = metadata || $5::jsonb" in sql

    async def test_update_two_fields(self) -> None:
        doc_id = uuid4()
        row = make_row(row_id=doc_id)
        conn = FakeConn(rows=[row])
        repo = make_repo(conn)

        await repo.update_document(
            doc_id, DocumentUpdate(content="x", repository="r")
        )
        sql, params = conn.fetchrow_calls[0]
        assert "content = $2" in sql
        assert "repository = $3" in sql
        # 2 fields + id + now = 4 params
        assert len(params) == 4

    async def test_update_three_fields(self) -> None:
        doc_id = uuid4()
        row = make_row(row_id=doc_id)
        conn = FakeConn(rows=[row])
        repo = make_repo(conn)

        await repo.update_document(
            doc_id,
            DocumentUpdate(content="x", repository="r", metadata={"k": "v"}),
        )
        sql, params = conn.fetchrow_calls[0]
        # 3 fields + id + now = 5 params
        assert len(params) == 5
        assert "metadata = metadata || $4::jsonb" in sql

    async def test_update_returns_none_when_no_row(self) -> None:
        conn = FakeConn(rows=[])
        repo = make_repo(conn)
        result = await repo.update_document(
            uuid4(), DocumentUpdate(content="x")
        )
        assert result is None

    async def test_update_exception_wrapped(self) -> None:
        class BoomConn(FakeConn):
            async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
                raise RuntimeError("update failed")

        conn = BoomConn()
        repo = make_repo(conn)
        with pytest.raises(RepositoryError) as exc:
            await repo.update_document(uuid4(), DocumentUpdate(content="x"))
        assert exc.value.operation == "update_document"


# ---------------------------------------------------------------------------
# delete_document
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteDocument:
    async def test_delete_success(self) -> None:
        conn = FakeConn()
        repo = make_repo(conn)
        assert await repo.delete_document(uuid4()) is True
        assert len(conn.execute_calls) == 1

    async def test_delete_exception_wrapped(self) -> None:
        class BoomConn(FakeConn):
            async def execute(self, query: str, *args: Any) -> str:
                raise RuntimeError("delete failed")

        conn = BoomConn()
        repo = make_repo(conn)
        with pytest.raises(RepositoryError) as exc:
            await repo.delete_document(uuid4())
        assert exc.value.operation == "delete_document"


# ---------------------------------------------------------------------------
# search_documents
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchDocuments:
    async def test_search_no_repository(self) -> None:
        rows = [
            make_row(score=5.0),
            make_row(score=15.0),  # Will be clamped to 1.0
        ]
        conn = FakeConn(rows=rows)
        repo = make_repo(conn)

        results = await repo.search_documents("query")
        assert len(results) == 2
        # First: 5.0 / 10 = 0.5
        assert results[0].score == 0.5
        # Second: clamped to 1.0
        assert results[1].score == 1.0
        assert results[0].match_type == "lexical"
        sql, params = conn.fetch_calls[0]
        # Base search should not reference $2 = repository
        assert "AND repository" not in sql
        assert params == ("query", 20, 0)

    async def test_search_with_repository(self) -> None:
        rows = [make_row(score=2.0)]
        conn = FakeConn(rows=rows)
        repo = make_repo(conn)

        results = await repo.search_documents("query", repository="r1", limit=5, offset=10)
        assert len(results) == 1
        assert results[0].score == 0.2
        sql, params = conn.fetch_calls[0]
        assert "AND repository = $2" in sql
        assert params == ("query", "r1", 5, 10)

    async def test_search_empty_results(self) -> None:
        conn = FakeConn(rows=[])
        repo = make_repo(conn)
        assert await repo.search_documents("nothing") == []

    async def test_search_score_clamp_lower(self) -> None:
        # Negative score is clamped to 0.0
        rows = [make_row(score=-3.0)]
        conn = FakeConn(rows=rows)
        repo = make_repo(conn)
        results = await repo.search_documents("q")
        assert results[0].score == 0.0

    async def test_search_score_missing_defaults_to_zero(self) -> None:
        # No 'score' key in row
        rows = [make_row()]
        conn = FakeConn(rows=rows)
        repo = make_repo(conn)
        results = await repo.search_documents("q")
        assert results[0].score == 0.0

    async def test_search_exception_wrapped(self) -> None:
        class BoomConn(FakeConn):
            async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
                raise RuntimeError("search failed")

        conn = BoomConn()
        repo = make_repo(conn)
        with pytest.raises(RepositoryError) as exc:
            await repo.search_documents("q")
        assert exc.value.operation == "search_documents"


# ---------------------------------------------------------------------------
# list_documents
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListDocuments:
    async def test_list_all(self) -> None:
        rows = [make_row(), make_row(source_key="k2")]
        conn = FakeConn(rows=rows)
        repo = make_repo(conn)
        results = await repo.list_documents()
        assert len(results) == 2
        sql, params = conn.fetch_calls[0]
        # No WHERE clause beyond base
        assert "WHERE" not in sql
        assert params == (50, 0)

    async def test_list_by_repository(self) -> None:
        rows = [make_row()]
        conn = FakeConn(rows=rows)
        repo = make_repo(conn)
        results = await repo.list_documents(repository="r1")
        assert len(results) == 1
        sql, params = conn.fetch_calls[0]
        assert "WHERE repository = $1" in sql
        assert params == ("r1", 50, 0)

    async def test_list_by_type(self) -> None:
        rows = [make_row()]
        conn = FakeConn(rows=rows)
        repo = make_repo(conn)
        results = await repo.list_documents(source_type="t1")
        assert len(results) == 1
        sql, params = conn.fetch_calls[0]
        assert "WHERE source_type = $1" in sql
        assert params == ("t1", 50, 0)

    async def test_list_by_repo_and_type(self) -> None:
        rows = [make_row()]
        conn = FakeConn(rows=rows)
        repo = make_repo(conn)
        results = await repo.list_documents(repository="r1", source_type="t1", limit=10, offset=20)
        assert len(results) == 1
        sql, params = conn.fetch_calls[0]
        assert "WHERE repository = $1 AND source_type = $2" in sql
        assert params == ("r1", "t1", 10, 20)

    async def test_list_empty(self) -> None:
        conn = FakeConn(rows=[])
        repo = make_repo(conn)
        assert await repo.list_documents() == []

    async def test_list_exception_wrapped(self) -> None:
        class BoomConn(FakeConn):
            async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
                raise RuntimeError("list failed")

        conn = BoomConn()
        repo = make_repo(conn)
        with pytest.raises(RepositoryError) as exc:
            await repo.list_documents()
        assert exc.value.operation == "list_documents"


# ---------------------------------------------------------------------------
# _row_to_model
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRowToModel:
    def test_row_to_model_handles_null_metadata(self) -> None:
        conn = FakeConn()
        repo = make_repo(conn)
        row = make_row(metadata=None)
        # The implementation falls back to {} via `or {}`
        doc = repo._row_to_model(row)
        assert doc.metadata == {}

    def test_row_to_model_preserves_metadata(self) -> None:
        conn = FakeConn()
        repo = make_repo(conn)
        row = make_row(metadata={"a": 1, "b": 2})
        doc = repo._row_to_model(row)
        assert doc.metadata == {"a": 1, "b": 2}

    def test_row_to_model_all_fields(self) -> None:
        conn = FakeConn()
        repo = make_repo(conn)
        rid = uuid4()
        sid = uuid4()
        now = datetime.now(UTC)
        row = make_row(
            row_id=rid,
            source_type="wiki",
            source_id=sid,
            source_key="k",
            content="c",
            repository="r",
            system_name="s",
            created_at=now,
            updated_at=now,
            metadata={"x": 1},
        )
        doc = repo._row_to_model(row)
        assert doc.id == rid
        assert doc.source_id == sid
        assert doc.source_type == "wiki"
        assert doc.created_at == now
        assert doc.updated_at == now


# ---------------------------------------------------------------------------
# Inherited base class default behavior
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInheritedBaseMethods:
    async def test_base_get_raises(self) -> None:
        repo = make_repo(FakeConn())
        with pytest.raises(NotImplementedError):
            await repo.get("id")

    async def test_base_update_raises(self) -> None:
        repo = make_repo(FakeConn())
        with pytest.raises(NotImplementedError):
            await repo.update("id", DocumentUpdate())  # type: ignore[arg-type]

    async def test_base_delete_raises(self) -> None:
        repo = make_repo(FakeConn())
        with pytest.raises(NotImplementedError):
            await repo.delete("id")

    async def test_base_list_raises(self) -> None:
        repo = make_repo(FakeConn())
        with pytest.raises(NotImplementedError):
            await repo.list()


# ---------------------------------------------------------------------------
# Repository error structure
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRepositoryErrorDetails:
    async def test_error_carries_details(self) -> None:
        class BoomConn(FakeConn):
            async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
                raise ValueError("bad value")

        conn = BoomConn()
        repo = make_repo(conn)
        with pytest.raises(RepositoryError) as exc:
            await repo.get_document(uuid4())
        # The exception's details should include the document_id and original error
        assert exc.value.details is not None
        assert "original_error" in exc.value.details
        assert exc.value.details["original_error"] == "bad value"
        assert "document_id" in exc.value.details

    async def test_repository_error_inherits_mahavishnu_error(self) -> None:
        from mahavishnu.core.errors import MahavishnuError
        assert issubclass(RepositoryError, MahavishnuError)
