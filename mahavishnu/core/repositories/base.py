"""Abstract base repository with async context manager pattern.

This module provides the foundation for all repository implementations:
- Async context manager for database sessions
- Common CRUD operations interface
- Error handling patterns
- Type safety with generics

Usage:
    from mahavishnu.core.repositories.base import BaseRepository

    class TaskRepository(BaseRepository[TaskRead]):
        async def create(self, data: TaskCreate) -> TaskRead:
            ...
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Generic, TypeVar

from asyncpg import Connection, Pool

from mahavishnu.core.database import Database, get_database
from mahavishnu.core.errors import DatabaseError, MahavishnuError

logger = logging.getLogger(__name__)

# Generic type variables for repository patterns
CreateModel = TypeVar("CreateModel")
ReadModel = TypeVar("ReadModel")
UpdateModel = TypeVar("UpdateModel")


class RepositoryError(MahavishnuError):
    """Repository operation error.

    Raised when a repository operation fails due to:
    - Database constraints
    - Invalid data
    - Connection issues
    - Query failures
    """

    def __init__(
        self,
        message: str,
        operation: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize repository error.

        Args:
            message: Human-readable error message
            operation: The operation that failed (create, read, update, delete)
            details: Additional context about the error
        """
        merged_details = {"operation": operation, **(details or {})}
        super().__init__(
            message=message,
            error_code=None,  # Will use INTERNAL_ERROR from base
            details=merged_details,
        )
        self.operation = operation


class BaseRepository(ABC, Generic[CreateModel, ReadModel, UpdateModel]):
    """Abstract base repository with async context manager pattern.

    Provides:
    - Database connection management via context managers
    - Common CRUD operation interface
    - Error handling and logging
    - Type safety with generics

    Subclasses must implement:
    - create(): Insert new records
    - get(): Retrieve single record by ID
    - update(): Update existing records
    - delete(): Remove records
    - list(): Retrieve multiple records with filters

    Example:
        class TaskRepository(BaseRepository[TaskCreate, TaskRead, TaskUpdate]):
            async def create(self, data: TaskCreate) -> TaskRead:
                async with self.connection() as conn:
                    row = await conn.fetchrow(
                        "INSERT INTO tasks (...) VALUES (...) RETURNING *",
                        ...
                    )
                    return TaskRead.model_validate(dict(row))
    """

    def __init__(self, database: Database | None = None) -> None:
        """Initialize repository.

        Args:
            database: Optional database instance. If None, uses singleton.
        """
        self._database = database
        self._pool: Pool | None = None

    async def _get_database(self) -> Database:
        """Get database instance.

        Returns:
            Database instance (singleton if not provided)

        Raises:
            DatabaseError: If database cannot be initialized
        """
        if self._database is None:
            self._database = await get_database()
        return self._database

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[Connection]:
        """Get a database connection from the pool.

        Yields:
            Database connection

        Raises:
            DatabaseError: If connection cannot be acquired
        """
        db = await self._get_database()
        async with db.connection() as conn:
            yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Connection]:
        """Start a database transaction.

        Yields:
            Database connection with active transaction

        Raises:
            DatabaseError: If transaction fails
        """
        db = await self._get_database()
        async with db.transaction() as conn:
            yield conn

    # Abstract CRUD operations

    @abstractmethod
    async def create(self, data: CreateModel) -> ReadModel:
        """Create a new record.

        Args:
            data: Data to create the record with

        Returns:
            The created record

        Raises:
            RepositoryError: If creation fails
        """
        ...

    @abstractmethod
    async def get(self, id: str) -> ReadModel | None:
        """Retrieve a record by ID.

        Args:
            id: Record identifier (UUID string)

        Returns:
            The record if found, None otherwise

        Raises:
            RepositoryError: If retrieval fails
        """
        ...

    @abstractmethod
    async def update(self, id: str, data: UpdateModel) -> ReadModel | None:
        """Update an existing record.

        Args:
            id: Record identifier (UUID string)
            data: Data to update the record with

        Returns:
            The updated record if found, None otherwise

        Raises:
            RepositoryError: If update fails
        """
        ...

    @abstractmethod
    async def delete(self, id: str) -> bool:
        """Delete a record by ID.

        Args:
            id: Record identifier (UUID string)

        Returns:
            True if deleted, False if not found

        Raises:
            RepositoryError: If deletion fails
        """
        ...

    @abstractmethod
    async def list(
        self,
        limit: int = 50,
        offset: int = 0,
        **filters: Any,
    ) -> list[ReadModel]:
        """List records with optional filters.

        Args:
            limit: Maximum number of records to return
            offset: Number of records to skip
            **filters: Additional filter criteria

        Returns:
            List of records matching filters

        Raises:
            RepositoryError: If query fails
        """
        ...

    # Utility methods

    def _log_operation(
        self,
        operation: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log repository operation.

        Args:
            operation: Operation name (create, read, update, delete)
            details: Additional context to log
        """
        log_data = {"repository": self.__class__.__name__, "operation": operation}
        if details:
            log_data.update(details)
        logger.debug(f"Repository operation: {log_data}")

    def _handle_error(
        self,
        operation: str,
        error: Exception,
        details: dict[str, Any] | None = None,
    ) -> RepositoryError:
        """Handle and wrap database errors.

        Args:
            operation: Operation that failed
            error: Original exception
            details: Additional context

        Returns:
            RepositoryError with context
        """
        error_details = {
            "original_error": str(error),
            "error_type": type(error).__name__,
            **(details or {}),
        }
        self._log_operation(f"{operation}_error", error_details)
        return RepositoryError(
            message=f"Repository operation '{operation}' failed: {error}",
            operation=operation,
            details=error_details,
        )


__all__ = [
    "RepositoryError",
    "BaseRepository",
]
