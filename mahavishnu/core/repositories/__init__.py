"""Repository layer for Mahavishnu persistence.

This module provides the repository pattern for database operations:
- Abstract base repository with async context manager pattern
- Type-specific repositories for tasks, runs, events, documents, embeddings
- Pydantic model returns for type safety

Architecture:
- All repositories use async context managers for database sessions
- Methods return Pydantic models, not raw dicts
- Status enums from mahavishnu.core.status are used consistently
- Repository methods are fully type-annotated

Usage:
    from mahavishnu.core.repositories import TaskRepository, get_task_repository

    async with get_task_repository() as repo:
        task = await repo.create_task(
            title="Fix bug",
            repository="mahavishnu",
            priority="high",
        )
"""

from mahavishnu.core.repositories.base import (
    BaseRepository,
    RepositoryError,
)
from mahavishnu.core.repositories.documents import (
    DocumentCreate,
    DocumentRead,
    DocumentRepository,
    DocumentSearchResult,
    DocumentUpdate,
)
from mahavishnu.core.repositories.embeddings import (
    EmbeddingCreate,
    EmbeddingRead,
    EmbeddingRepository,
    EmbeddingSearchResult,
)
from mahavishnu.core.repositories.events import (
    TaskEventCreate,
    TaskEventFilter,
    TaskEventRead,
    TaskEventRepository,
)
from mahavishnu.core.repositories.runs import (
    TaskRunCreate,
    TaskRunRead,
    TaskRunRepository,
    TaskRunUpdate,
)
from mahavishnu.core.repositories.tasks import (
    TaskCreate,
    TaskFilter,
    TaskRead,
    TaskRepository,
    TaskUpdate,
)

__all__ = [
    # Base
    "BaseRepository",
    "RepositoryError",
    # Tasks
    "TaskCreate",
    "TaskFilter",
    "TaskRead",
    "TaskUpdate",
    "TaskRepository",
    # Runs
    "TaskRunCreate",
    "TaskRunRead",
    "TaskRunUpdate",
    "TaskRunRepository",
    # Events
    "TaskEventCreate",
    "TaskEventFilter",
    "TaskEventRead",
    "TaskEventRepository",
    # Documents
    "DocumentCreate",
    "DocumentRead",
    "DocumentUpdate",
    "DocumentSearchResult",
    "DocumentRepository",
    # Embeddings
    "EmbeddingCreate",
    "EmbeddingRead",
    "EmbeddingSearchResult",
    "EmbeddingRepository",
]
