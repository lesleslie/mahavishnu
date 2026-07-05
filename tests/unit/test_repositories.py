"""Tests for mahavishnu/core/repositories/ modules.

All repositories use asyncpg connections managed by BaseRepository's
connection() and transaction() context managers. We mock the database
layer so no real PostgreSQL is needed.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """Mock Database object with connection/transaction context managers."""

    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock()
    mock_conn.fetch = AsyncMock()
    mock_conn.fetchval = AsyncMock()
    mock_conn.execute = AsyncMock()

    @asynccontextmanager
    async def mock_connection():
        yield mock_conn

    @asynccontextmanager
    async def mock_transaction():
        yield mock_conn

    db = MagicMock()
    db.connection = mock_connection
    db.transaction = mock_transaction
    return mock_conn, db


def _make_task_row(**overrides):
    """Build a fake database row for orchestration.tasks."""
    defaults = {
        "id": uuid4(),
        "external_id": None,
        "title": "Test task",
        "description": None,
        "repository": "mahavishnu",
        "pool_name": None,
        "worker_type": None,
        "status": "pending",
        "priority": "medium",
        "created_by": "claude",
        "assigned_to": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "started_at": None,
        "completed_at": None,
        "deadline": None,
        "metadata": {},
    }
    defaults.update(overrides)
    return defaults


def _make_run_row(**overrides):
    """Build a fake database row for orchestration.task_runs."""
    defaults = {
        "id": uuid4(),
        "task_id": uuid4(),
        "run_number": 1,
        "pool_name": None,
        "worker_id": None,
        "worker_type": None,
        "engine": "prefect",
        "status": "running",
        "started_at": datetime.now(UTC),
        "finished_at": None,
        "exit_code": None,
        "error_message": None,
        "result_summary": None,
        "metrics": {},
        "metadata": {},
    }
    defaults.update(overrides)
    return defaults


def _make_event_row(**overrides):
    """Build a fake database row for audit.task_events."""
    defaults = {
        "id": uuid4(),
        "task_id": uuid4(),
        "run_id": None,
        "event_type": "status_changed",
        "event_time": datetime.now(UTC),
        "actor": "claude",
        "payload": {"old": "pending", "new": "in_progress"},
        "metadata": {},
    }
    defaults.update(overrides)
    return defaults


def _make_document_row(**overrides):
    """Build a fake database row for search.documents."""
    defaults = {
        "id": uuid4(),
        "source_type": "task",
        "source_id": None,
        "source_key": "task-123",
        "content": "Test document content",
        "repository": "mahavishnu",
        "system_name": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "metadata": {},
    }
    defaults.update(overrides)
    return defaults


def _make_embedding_row(**overrides):
    """Build a fake database row for search.document_embeddings."""
    defaults = {
        "document_id": uuid4(),
        "model_name": "all-MiniLM-L6-v2",
        "embedding_dim": 384,
        "embedding": [0.1] * 384,
        "created_at": datetime.now(UTC),
        "metadata": {},
    }
    defaults.update(overrides)
    return defaults


# =========================================================================
# Base repository
# =========================================================================


class TestBaseRepository:
    """Test BaseRepository utility methods."""

    def test_repository_error_has_operation(self):
        from mahavishnu.core.repositories.base import RepositoryError

        err = RepositoryError("something broke", operation="create")
        assert err.operation == "create"
        assert err.details["operation"] == "create"

    def test_handle_error_wraps_exception(self):
        from mahavishnu.core.repositories.base import RepositoryError

        MagicMock()  # Not a real subclass, just for utility testing
        from mahavishnu.core.repositories.base import BaseRepository

        # Use a concrete-like instance to test _handle_error
        class FakeRepo(BaseRepository):
            async def create(self, data): ...
            async def get(self, id): ...
            async def update(self, id, data): ...
            async def delete(self, id): ...
            async def list(self, **kw): ...

        r = FakeRepo(database=MagicMock())
        result = r._handle_error("create", ValueError("bad value"))
        assert isinstance(result, RepositoryError)
        assert result.operation == "create"
        assert "bad value" in result.details["original_error"]


# =========================================================================
# TaskRepository
# =========================================================================


class TestTaskRepository:
    """Test TaskRepository CRUD operations."""

    async def test_create_task(self, mock_db):
        mock_conn, db = mock_db
        row = _make_task_row()
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.tasks.TaskRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.tasks import TaskCreate, TaskRepository

            repo = TaskRepository()
            repo._database = db  # shortcut: skip lazy init
            task = await repo.create_task(TaskCreate(title="New task"))

            assert task.title == "Test task"  # Mock row defines the title
            mock_conn.fetchrow.assert_called_once()

    async def test_get_task_found(self, mock_db):
        mock_conn, db = mock_db
        row = _make_task_row()
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.tasks.TaskRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.tasks import TaskRepository

            repo = TaskRepository()
            repo._database = db
            task = await repo.get_task(row["id"])

            assert task is not None
            assert task.id == row["id"]

    async def test_get_task_not_found(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.fetchrow.return_value = None

        with patch(
            "mahavishnu.core.repositories.tasks.TaskRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.tasks import TaskRepository

            repo = TaskRepository()
            repo._database = db
            task = await repo.get_task(uuid4())

            assert task is None

    async def test_get_task_by_external_id(self, mock_db):
        mock_conn, db = mock_db
        row = _make_task_row(external_id="ext-42")
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.tasks.TaskRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.tasks import TaskRepository

            repo = TaskRepository()
            repo._database = db
            task = await repo.get_task_by_external_id("ext-42")

            assert task is not None
            assert task.external_id == "ext-42"

    async def test_update_task_status(self, mock_db):
        mock_conn, db = mock_db
        row = _make_task_row(status="in_progress")
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.tasks.TaskRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.tasks import TaskRepository
            from mahavishnu.core.status import TaskStatus

            repo = TaskRepository()
            repo._database = db
            task = await repo.update_task_status(row["id"], TaskStatus.IN_PROGRESS)

            assert task is not None
            mock_conn.fetchrow.assert_called_once()

    async def test_update_task_status_not_found(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.fetchrow.return_value = None

        with patch(
            "mahavishnu.core.repositories.tasks.TaskRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.tasks import TaskRepository
            from mahavishnu.core.status import TaskStatus

            repo = TaskRepository()
            repo._database = db
            task = await repo.update_task_status(uuid4(), TaskStatus.COMPLETED)

            assert task is None

    async def test_list_tasks(self, mock_db):
        mock_conn, db = mock_db
        rows = [_make_task_row(title=f"Task {i}") for i in range(3)]
        mock_conn.fetch.return_value = rows

        with patch(
            "mahavishnu.core.repositories.tasks.TaskRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.tasks import TaskFilter, TaskRepository

            repo = TaskRepository()
            repo._database = db
            tasks = await repo.list_tasks(TaskFilter())

            assert len(tasks) == 3
            mock_conn.fetch.assert_called_once()

    async def test_list_tasks_with_filters(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.fetch.return_value = []

        with patch(
            "mahavishnu.core.repositories.tasks.TaskRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.tasks import (
                TaskFilter,
                TaskPriority,
                TaskRepository,
            )
            from mahavishnu.core.status import TaskStatus

            repo = TaskRepository()
            repo._database = db
            tasks = await repo.list_tasks(
                TaskFilter(status=TaskStatus.PENDING, priority=TaskPriority.HIGH),
            )

            assert tasks == []
            # Verify the query included filter params
            call_args = mock_conn.fetch.call_args
            all_params = call_args[0][1:]  # Everything after the query string
            assert "pending" in all_params
            assert "high" in all_params

    async def test_delete_task_success(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.execute.return_value = "DELETE 1"

        with patch(
            "mahavishnu.core.repositories.tasks.TaskRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.tasks import TaskRepository

            repo = TaskRepository()
            repo._database = db
            result = await repo.delete_task(uuid4())

            assert result is True

    async def test_delete_task_not_found(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.execute.return_value = "DELETE 0"

        with patch(
            "mahavishnu.core.repositories.tasks.TaskRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.tasks import TaskRepository

            repo = TaskRepository()
            repo._database = db
            result = await repo.delete_task(uuid4())

            assert result is False

    async def test_add_dependency(self, mock_db):
        mock_conn, db = mock_db
        task_id = uuid4()
        dep_id = uuid4()
        now = datetime.now(UTC)
        mock_conn.fetchrow.return_value = {
            "task_id": task_id,
            "depends_on_task_id": dep_id,
            "dependency_type": "blocks",
            "created_at": now,
        }

        with patch(
            "mahavishnu.core.repositories.tasks.TaskRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.tasks import DependencyType, TaskRepository

            repo = TaskRepository()
            repo._database = db
            dep = await repo.add_dependency(task_id, dep_id, DependencyType.BLOCKS)

            assert dep.task_id == task_id
            assert dep.depends_on_task_id == dep_id

    async def test_get_dependencies(self, mock_db):
        mock_conn, db = mock_db
        task_id = uuid4()
        now = datetime.now(UTC)
        mock_conn.fetch.return_value = [
            {
                "task_id": task_id,
                "depends_on_task_id": uuid4(),
                "dependency_type": "requires",
                "created_at": now,
            },
        ]

        with patch(
            "mahavishnu.core.repositories.tasks.TaskRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.tasks import TaskRepository

            repo = TaskRepository()
            repo._database = db
            deps = await repo.get_dependencies(task_id)

            assert len(deps) == 1

    async def test_update_task_partial(self, mock_db):
        mock_conn, db = mock_db
        row = _make_task_row(title="Updated title")
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.tasks.TaskRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.tasks import TaskRepository, TaskUpdate

            repo = TaskRepository()
            repo._database = db
            task = await repo.update_task(uuid4(), TaskUpdate(title="Updated title"))

            assert task is not None
            mock_conn.fetchrow.assert_called_once()

    async def test_database_error_handling(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.fetchrow.side_effect = Exception("Connection refused")

        with patch(
            "mahavishnu.core.repositories.tasks.TaskRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.base import RepositoryError
            from mahavishnu.core.repositories.tasks import TaskCreate, TaskRepository

            repo = TaskRepository()
            repo._database = db

            with pytest.raises(RepositoryError, match="create_task"):
                await repo.create_task(TaskCreate(title="Fail"))


# =========================================================================
# TaskRunRepository
# =========================================================================


class TestTaskRunRepository:
    """Test TaskRunRepository CRUD operations."""

    async def test_create_run(self, mock_db):
        mock_conn, db = mock_db
        row = _make_run_row()
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.runs.TaskRunRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.runs import TaskRunCreate, TaskRunRepository

            repo = TaskRunRepository()
            repo._database = db
            run = await repo.create_run(
                TaskRunCreate(task_id=uuid4(), run_number=1),
            )

            assert run is not None
            assert run.run_number == 1

    async def test_get_run(self, mock_db):
        mock_conn, db = mock_db
        row = _make_run_row()
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.runs.TaskRunRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.runs import TaskRunRepository

            repo = TaskRunRepository()
            repo._database = db
            run = await repo.get_run(row["id"])

            assert run is not None

    async def test_get_run_not_found(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.fetchrow.return_value = None

        with patch(
            "mahavishnu.core.repositories.runs.TaskRunRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.runs import TaskRunRepository

            repo = TaskRunRepository()
            repo._database = db
            run = await repo.get_run(uuid4())

            assert run is None

    async def test_list_runs_for_task(self, mock_db):
        mock_conn, db = mock_db
        task_id = uuid4()
        mock_conn.fetch.return_value = [
            _make_run_row(task_id=task_id, run_number=i) for i in (1, 2)
        ]

        with patch(
            "mahavishnu.core.repositories.runs.TaskRunRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.runs import TaskRunRepository

            repo = TaskRunRepository()
            repo._database = db
            runs = await repo.list_runs_for_task(task_id)

            assert len(runs) == 2

    async def test_get_latest_run_for_task(self, mock_db):
        mock_conn, db = mock_db
        row = _make_run_row(run_number=5)
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.runs.TaskRunRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.runs import TaskRunRepository

            repo = TaskRunRepository()
            repo._database = db
            run = await repo.get_latest_run_for_task(row["task_id"])

            assert run is not None

    async def test_get_next_run_number(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.fetchval.return_value = 4

        with patch(
            "mahavishnu.core.repositories.runs.TaskRunRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.runs import TaskRunRepository

            repo = TaskRunRepository()
            repo._database = db
            next_num = await repo.get_next_run_number(uuid4())

            assert next_num == 4

    async def test_get_next_run_number_no_runs(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.fetchval.return_value = 1

        with patch(
            "mahavishnu.core.repositories.runs.TaskRunRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.runs import TaskRunRepository

            repo = TaskRunRepository()
            repo._database = db
            next_num = await repo.get_next_run_number(uuid4())

            assert next_num == 1

    async def test_update_run(self, mock_db):
        mock_conn, db = mock_db
        row = _make_run_row(status="completed", exit_code=0)
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.runs.TaskRunRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.runs import TaskRunRepository, TaskRunUpdate

            repo = TaskRunRepository()
            repo._database = db
            run = await repo.update_run(
                uuid4(),
                TaskRunUpdate(status="completed", exit_code=0),
            )

            assert run is not None

    async def test_list_runs_with_filters(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.fetch.return_value = []

        with patch(
            "mahavishnu.core.repositories.runs.TaskRunRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.runs import TaskRunFilter, TaskRunRepository

            repo = TaskRunRepository()
            repo._database = db
            runs = await repo.list_runs(
                TaskRunFilter(status="failed", engine="prefect"),
            )

            assert runs == []


# =========================================================================
# TaskEventRepository
# =========================================================================


class TestTaskEventRepository:
    """Test TaskEventRepository operations."""

    async def test_record_event(self, mock_db):
        mock_conn, db = mock_db
        row = _make_event_row()
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.events.TaskEventRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.events import TaskEventCreate, TaskEventRepository

            repo = TaskEventRepository()
            repo._database = db
            event = await repo.record_event(
                TaskEventCreate(task_id=row["task_id"], event_type="status_changed"),
            )

            assert event is not None
            assert event.event_type == "status_changed"

    async def test_get_events_for_task(self, mock_db):
        mock_conn, db = mock_db
        task_id = uuid4()
        mock_conn.fetch.return_value = [_make_event_row(task_id=task_id)]

        with patch(
            "mahavishnu.core.repositories.events.TaskEventRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.events import TaskEventRepository

            repo = TaskEventRepository()
            repo._database = db
            events = await repo.get_events_for_task(task_id)

            assert len(events) == 1

    async def test_get_events_for_run(self, mock_db):
        mock_conn, db = mock_db
        task_id = uuid4()
        run_id = uuid4()
        mock_conn.fetch.return_value = [
            _make_event_row(task_id=task_id, run_id=run_id),
        ]

        with patch(
            "mahavishnu.core.repositories.events.TaskEventRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.events import TaskEventRepository

            repo = TaskEventRepository()
            repo._database = db
            events = await repo.get_events_for_run(task_id, run_id)

            assert len(events) == 1

    async def test_list_events(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.fetch.return_value = []

        with patch(
            "mahavishnu.core.repositories.events.TaskEventRepository._get_database", return_value=db
        ):
            from mahavishnu.core.repositories.events import TaskEventFilter, TaskEventRepository

            repo = TaskEventRepository()
            repo._database = db
            events = await repo.list_events(
                TaskEventFilter(event_type="status_changed"),
            )

            assert events == []


# =========================================================================
# DocumentRepository
# =========================================================================


class TestDocumentRepository:
    """Test DocumentRepository operations."""

    async def test_create_document(self, mock_db):
        mock_conn, db = mock_db
        row = _make_document_row()
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.documents.DocumentRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.documents import DocumentCreate, DocumentRepository

            repo = DocumentRepository()
            repo._database = db
            doc = await repo.create_document(
                DocumentCreate(
                    source_type="task",
                    source_key="task-123",
                    content="Test content",
                ),
            )

            assert doc is not None
            assert doc.source_key == "task-123"

    async def test_get_document(self, mock_db):
        mock_conn, db = mock_db
        row = _make_document_row()
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.documents.DocumentRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.documents import DocumentRepository

            repo = DocumentRepository()
            repo._database = db
            doc = await repo.get_document(row["id"])

            assert doc is not None

    async def test_get_document_not_found(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.fetchrow.return_value = None

        with patch(
            "mahavishnu.core.repositories.documents.DocumentRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.documents import DocumentRepository

            repo = DocumentRepository()
            repo._database = db
            doc = await repo.get_document(uuid4())

            assert doc is None

    async def test_get_document_by_key(self, mock_db):
        mock_conn, db = mock_db
        row = _make_document_row(source_key="unique-key")
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.documents.DocumentRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.documents import DocumentRepository

            repo = DocumentRepository()
            repo._database = db
            doc = await repo.get_document_by_key("unique-key")

            assert doc is not None

    async def test_get_document_by_key_with_type(self, mock_db):
        mock_conn, db = mock_db
        row = _make_document_row(source_type="run")
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.documents.DocumentRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.documents import DocumentRepository

            repo = DocumentRepository()
            repo._database = db
            doc = await repo.get_document_by_key("key", source_type="run")

            assert doc is not None

    async def test_delete_document_success(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.execute.return_value = "DELETE 1"

        with patch(
            "mahavishnu.core.repositories.documents.DocumentRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.documents import DocumentRepository

            repo = DocumentRepository()
            repo._database = db
            result = await repo.delete_document(uuid4())

            assert result is True

    async def test_delete_document_not_found(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.execute.return_value = "DELETE 0"

        with patch(
            "mahavishnu.core.repositories.documents.DocumentRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.documents import DocumentRepository

            repo = DocumentRepository()
            repo._database = db
            result = await repo.delete_document(uuid4())

            assert result is False

    async def test_search_documents(self, mock_db):
        mock_conn, db = mock_db
        row = _make_document_row()
        # search_documents reads "score" from the row
        mock_conn.fetch.return_value = [{**row, "score": 7.5}]

        with patch(
            "mahavishnu.core.repositories.documents.DocumentRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.documents import DocumentRepository

            repo = DocumentRepository()
            repo._database = db
            results = await repo.search_documents("error handling")

            assert len(results) == 1
            assert 0.0 <= results[0].score <= 1.0
            assert results[0].match_type == "lexical"

    async def test_list_documents(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.fetch.return_value = [_make_document_row()]

        with patch(
            "mahavishnu.core.repositories.documents.DocumentRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.documents import DocumentRepository

            repo = DocumentRepository()
            repo._database = db
            docs = await repo.list_documents(repository="mahavishnu")

            assert len(docs) == 1

    async def test_update_document(self, mock_db):
        mock_conn, db = mock_db
        row = _make_document_row(content="Updated content")
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.documents.DocumentRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.documents import DocumentRepository, DocumentUpdate

            repo = DocumentRepository()
            repo._database = db
            doc = await repo.update_document(
                uuid4(),
                DocumentUpdate(content="Updated content"),
            )

            assert doc is not None


# =========================================================================
# EmbeddingRepository
# =========================================================================


class TestEmbeddingRepository:
    """Test EmbeddingRepository operations."""

    async def test_store_embedding(self, mock_db):
        mock_conn, db = mock_db
        doc_id = uuid4()
        row = _make_embedding_row(document_id=doc_id)
        # store_embedding converts embedding to string for storage
        row_with_str = {**row, "embedding": str(row["embedding"])}
        mock_conn.fetchrow.return_value = row_with_str

        with patch(
            "mahavishnu.core.repositories.embeddings.EmbeddingRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.embeddings import (
                EmbeddingCreate,
                EmbeddingRepository,
            )

            repo = EmbeddingRepository()
            repo._database = db
            emb = await repo.store_embedding(
                EmbeddingCreate(
                    document_id=doc_id,
                    model_name="all-MiniLM-L6-v2",
                    embedding=[0.1] * 384,
                ),
            )

            assert emb is not None
            assert emb.document_id == doc_id

    async def test_get_embedding(self, mock_db):
        mock_conn, db = mock_db
        row = _make_embedding_row()
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.embeddings.EmbeddingRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.embeddings import EmbeddingRepository

            repo = EmbeddingRepository()
            repo._database = db
            emb = await repo.get_embedding(row["document_id"])

            assert emb is not None
            assert isinstance(emb.embedding, list)

    async def test_get_embedding_not_found(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.fetchrow.return_value = None

        with patch(
            "mahavishnu.core.repositories.embeddings.EmbeddingRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.embeddings import EmbeddingRepository

            repo = EmbeddingRepository()
            repo._database = db
            emb = await repo.get_embedding(uuid4())

            assert emb is None

    async def test_get_embedding_parses_string_vector(self, mock_db):
        """_row_to_model should parse string embedding back to list of floats."""
        mock_conn, db = mock_db
        doc_id = uuid4()
        row = _make_embedding_row(document_id=doc_id, embedding="0.1, 0.2, 0.3")
        mock_conn.fetchrow.return_value = row

        with patch(
            "mahavishnu.core.repositories.embeddings.EmbeddingRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.embeddings import EmbeddingRepository

            repo = EmbeddingRepository()
            repo._database = db
            emb = await repo.get_embedding(doc_id)

            assert emb is not None
            assert emb.embedding == [0.1, 0.2, 0.3]

    async def test_search_similar(self, mock_db):
        mock_conn, db = mock_db
        doc_id = uuid4()
        mock_conn.fetch.return_value = [
            {
                "document_id": doc_id,
                "model_name": "all-MiniLM-L6-v2",
                "embedding_dim": 384,
                "score": 0.87,
                "metadata": {},
            },
        ]

        with patch(
            "mahavishnu.core.repositories.embeddings.EmbeddingRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.embeddings import EmbeddingRepository

            repo = EmbeddingRepository()
            repo._database = db
            results = await repo.search_similar([0.1] * 384, limit=5)

            assert len(results) == 1
            assert results[0].score == 0.87

    async def test_delete_embedding_success(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.execute.return_value = "DELETE 1"

        with patch(
            "mahavishnu.core.repositories.embeddings.EmbeddingRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.embeddings import EmbeddingRepository

            repo = EmbeddingRepository()
            repo._database = db
            result = await repo.delete_embedding(uuid4())

            assert result is True

    async def test_delete_embedding_not_found(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.execute.return_value = "DELETE 0"

        with patch(
            "mahavishnu.core.repositories.embeddings.EmbeddingRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.embeddings import EmbeddingRepository

            repo = EmbeddingRepository()
            repo._database = db
            result = await repo.delete_embedding(uuid4())

            assert result is False

    async def test_list_embeddings(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.fetch.return_value = [_make_embedding_row()]

        with patch(
            "mahavishnu.core.repositories.embeddings.EmbeddingRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.embeddings import EmbeddingRepository

            repo = EmbeddingRepository()
            repo._database = db
            embs = await repo.list_embeddings(model_name="all-MiniLM-L6-v2")

            assert len(embs) == 1

    async def test_list_embeddings_no_filter(self, mock_db):
        mock_conn, db = mock_db
        mock_conn.fetch.return_value = []

        with patch(
            "mahavishnu.core.repositories.embeddings.EmbeddingRepository._get_database",
            return_value=db,
        ):
            from mahavishnu.core.repositories.embeddings import EmbeddingRepository

            repo = EmbeddingRepository()
            repo._database = db
            embs = await repo.list_embeddings()

            assert embs == []


# =========================================================================
# Pydantic model validation
# =========================================================================


class TestPydanticModels:
    """Test that Pydantic models validate correctly."""

    def test_task_create_validation(self):
        from mahavishnu.core.repositories.tasks import TaskCreate

        t = TaskCreate(title="Valid task")
        assert t.title == "Valid task"
        assert t.status.value == "pending"
        assert t.priority.value == "medium"

    def test_task_create_rejects_empty_title(self):
        import pydantic

        from mahavishnu.core.repositories.tasks import TaskCreate

        with pytest.raises(pydantic.ValidationError):
            TaskCreate(title="")

    def test_task_filter_defaults(self):
        from mahavishnu.core.repositories.tasks import TaskFilter

        f = TaskFilter()
        assert f.limit == 50
        assert f.offset == 0
        assert f.status is None

    def test_run_create_validation(self):
        from mahavishnu.core.repositories.runs import TaskRunCreate

        r = TaskRunCreate(task_id=uuid4(), run_number=1)
        assert r.run_number == 1
        assert r.status == "pending"

    def test_run_create_rejects_zero_run_number(self):
        import pydantic

        from mahavishnu.core.repositories.runs import TaskRunCreate

        with pytest.raises(pydantic.ValidationError):
            TaskRunCreate(task_id=uuid4(), run_number=0)

    def test_event_create_defaults(self):
        from mahavishnu.core.repositories.events import TaskEventCreate

        e = TaskEventCreate(task_id=uuid4(), event_type="status_changed")
        assert e.payload == {}
        assert e.actor is None

    def test_document_create(self):
        from mahavishnu.core.repositories.documents import DocumentCreate

        d = DocumentCreate(
            source_type="task",
            source_key="task-1",
            content="Hello world",
        )
        assert d.source_type == "task"
        assert d.metadata == {}

    def test_embedding_create_dimension_validation(self):
        import pydantic

        from mahavishnu.core.repositories.embeddings import EmbeddingCreate

        with pytest.raises(pydantic.ValidationError):
            EmbeddingCreate(
                document_id=uuid4(),
                model_name="test",
                embedding=[0.1] * 127,  # Below min_length=128
            )

    def test_embedding_create_valid(self):
        from mahavishnu.core.repositories.embeddings import EmbeddingCreate

        e = EmbeddingCreate(
            document_id=uuid4(),
            model_name="test",
            embedding=[0.1] * 256,
            embedding_dim=256,
        )
        assert e.embedding_dim == 256
        assert len(e.embedding) == 256

    def test_task_enums(self):
        from mahavishnu.core.repositories.tasks import DependencyType, TaskPriority

        assert TaskPriority.LOW == "low"
        assert TaskPriority.CRITICAL == "critical"
        assert DependencyType.BLOCKS == "blocks"
        assert DependencyType.REQUIRES == "requires"

    def test_run_status_enum(self):
        from mahavishnu.core.repositories.runs import RunStatus

        assert RunStatus.PENDING == "pending"
        assert RunStatus.COMPLETED == "completed"
