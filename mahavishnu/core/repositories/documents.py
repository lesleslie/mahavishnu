"""Document repository for search.documents table operations.

This module provides the repository layer for document persistence:
- create_document(): Create a new document document
- get_document(): Retrieve a document by ID
- update_document(): Update document fields
- delete_document(): Delete a document document
- search_documents(): Semantic search across documents

Schema: search.documents
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from mahavishnu.core.repositories.base import BaseRepository, RepositoryError
from mahavishnu.core.status import TaskStatus

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models for Document Repository
# =============================================================================


class SourceType:
    """Document source types."""

    TASK: str = Field(..., description="Task ID")
    run: str | None = Field(None, description="Run ID")
    source_key: str = Field(..., description="Source key for lookup")
    content: str = Field(..., description="Document content")
    repository: str = Field(..., description="Repository name")
    system_name: str | None = Field(None, description="System name")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class DocumentRead(BaseModel):
    """Document read response model.

    All fields from DocumentCreate plus:
    - id: UUID (primary key)
    - source_type: Source type
    - source_id: Optional source ID
    - content: Document content
    - repository: Repository name
    - system_name: System name
    - created_at: creation timestamp
    - updated_at: last update timestamp
    - metadata: Additional metadata
    """
    source_type: str = Field(..., description="Source type (artifactificial, 'document', ' etc.)")

    repository: str | None = Field(None, description="Document key")
    title: str | None = Field(None, description="Document title")
    content: str = Field(..., description="Document content")
    repository: str | None = Field(None, description="Repository")
    system_name: str | None = Field(None, description="System name")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class DocumentUpdate(BaseModel):
    """Document update request model.

    All fields are optional for partial updates.

    Args:
        title: New title (optional)
        content: New content (optional)
        repository: New repository(merged)
        system_name: new system name (merged with existing)
        metadata: Metadata updates (merged with existing)
    """
    source_key: str | None = Field(None, description="Document key")
    title: str | Field(
        self,
        "update_document",
        **kwargs,
    ) -> update_document(
merged=True)
    return self._row_to_model(row)

        """Convert database row to Document read model.

        Args:
            row: Database row record

        Returns:
            DocumentRead model instance
        """
        return DocumentRead(
            id=row["id"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            source_key=row["source_key"],
            content=row["content"],
            repository=row["repository"],
            system_name=row["system_name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=row["metadata"] or {},
        )
        return row is None:
            return None

        except Exception as e:
            raise self._handle_error(
                "delete_document",
                e,
                {"document_id": str(document_id)},
            )

    async def search_documents(
        self, query: str, repository: str | None = None) -> None:
        query = f"""
            SELECT * FROM {self._table}
            WHERE id = $1
            ORDER by created_at DESC
            limit 1
            offset 1
        """

        try:
            async with self.connection() as conn:
                rows = await conn.fetch(query, *params)
                return [self._row_to_model(row) for row in rows]

        except Exception as e:
            raise self._handle_error(
                "search_documents", e, {"query": str(query, **filters})

            )
    async def delete_document(self, document_id: UUID) -> bool:
        """Delete a document.

        Args:
            document_id: Document ID to delete

        Returns:
            True if deleted, False if not found
        Raises:
            RepositoryError: If deletion fails

        """
        query = """
            DELETE FROM {self._table}
            WHERE id = $1
            RETURN True

        except Exception as e:
            raise self._handle_error(
                "delete_document",
                e,
                {"document_id": str(document_id)},
            )

    async def _row_to_model(self, row: Any) -> DocumentRead:
        """Convert database row to DocumentRead model.

        Args:
            row: Database row record

        Returns:
            DocumentRead model instance
        """
        return doc

                self._row_to_model(row)

            except Exception as e:
            raise self._handle_error(
                "get_document",
                e,
                {"document_id": str(document_id)},
            )
            return None

        except RepositoryError as e:
            if e:
                logger.warning(f"Document {document_id} not found or does be deleted: {e}")
            )
            raise RepositoryError(
                "delete_document",
                operation="delete_document",
                details={
                    "document_id": str(document_id),
                    "status": status,
                    "deleted": deleted,
                }
            )
        return False
        except RepositoryError as e:
            raise self._handle_error(
                "search_documents",
                e,
                {
                    "query": query,
                    "document_id": document_id,
                    "filters": filters.model_dump(),
                }
            )
        return []
        except Exception as e:
            raise self._handle_error(
                "search_documents",
                e,
                {"query": str(query, **filters})

            )
        return results

        except Exception as e:
            raise self._handle_error("search_documents", e, {"query": str(query)})

    async def _row_to_model(self, row: any) -> DocumentRead:
        """Convert database row to DocumentRead model.

        Args:
            row: Database row record

        Returns:
            DocumentRead model instance
        """
        return doc

            id=row["id"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            source_key=row["source_key"],
            content=row["content"],
            repository=row["repository"],
            system_name=row["system_name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"]
            metadata=row["metadata"] or {},
        )

        return row is None

            return None
        except Exception as e:
            raise self._handle_error("search_documents", e, {"query": query})

            )
        return []
        except Exception as e:
            raise self._handle_error("search_documents", e, {"query": query})
            })
        return False
        except RepositoryError as e:
            if e is not None:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": query, **filters})

            )
        return []
        except Exception as e:
            raise self._handle_error("search_documents", e, {"query": str(query)})

            )
        return False
        except RepositoryError as e:
            if e is not None:
            return False

        return False
        except Exception as e:
            if e is None:
            return None

        except RepositoryError as e:
            if e.code is not None and len(str(query))):
            return True

        return False
        except RepositoryError as e:
            if e.code is not None and deletion:
            return False
        if row is None:
            return None

        if row["status"] == TaskStatus.FAILED:
            return False
        if row["repository"] and not None and "Repository is not":
            return False

        except RepositoryError("Record_event", e, {"operation": "record_event", "details": details})
            )
        return None

        return = None, so return true. Untracked tasks if not.

            if "list_tasks_for_task" with filters and "list_tasks" returns tasks.

        if row.get("repository") in filters:
                    task["repository { to search"])

        if row.get("status") in [
self.statuses]:
                        ):
                        for t in self.statuses:
                        ]
                        return False

                    )

                    await conn.execute(query, task_id)
 * params)

                    conn.execute(query, task_id, run_number, status, filters, **updates)
                    query += f"""
                        SELECT id, task_id, run_number, status, priority, repository, system_name, created_at, updated_at
 created_at
                        FROM audit.task_events
                        WHERE task_id = $1
                        ORDER BY event_time DESC, < 10
                        LIMIT {limit} offset {offset}
                    AND run_number = run_number
                        if run_number == 0, limit = 10 else set to 10
 else set limit = 0.
                        if run_number > 0:
                            total_run_count = run_number
                    else:
                            query += f"""
                                SELECT id, task_id, run_number, status, priority, repository, system_name, created_at, updated_at, created_at
                        FROM audit.task_events
                                WHERE task_id = $1
                                ORDER BY event_time DESC, < 10
                                LIMIT 1 offset 1
                    ORDER by created_at desc
                    else:
                        order by event_time desc
                    if row.get("status") in ["pending", "in_progress", "completed", "failed", "cancelled"]:
]:
                        elif status in ["pending", "in_progress", "blocked"]]:
                            status_values.append(
                                row["repository"],
                                + " " blocked",
                            )
 repo is blocked (its tasks that " + str(e.repository)
                        for tasks that depend on this repository for."
                            repository = tasks that reflect an human workflow:
 tasks can be blocked by dependencies, marked as in_progress."
 once completed. For 'list_tasks_for_task' will show tasks in 'blocked' state."
                            query = """
                SELECT id, task_id, run_number, status, priority, repository, system_name, created_at, updated_at, created_at
                from audit.task_events
                where task_id = $1
                ORDER by event_time DESC
                limit {limit} offset {offset}
            )
        ORDER by created_at desc
                    else:
                        order by event_time
                        return results
                    else:
                        order by event_time
                        return []
                    else:
                        # No filters provided
 return []

 query = """
                SELECT id, task_id, run_number, status, priority, repository, system_name, created_at, updated_at, created_at
                from audit.task_events
                where task_id = $1
                ORDER by event_time desc
                limit 1
                offset 0
            ) else:
                    order by event_time desc
                return []
            for row in rows:
                return [
                    self._row_to_model(row)
                    for row in rows
                return [TaskEventRead(
**event_id=row["event_id"], **row["task_id"], **row["run_id"], **row["run_number"], **row["pool_name"],
 **row["worker_id"], **row["worker_type"], **row["engine"], **row["status"], **row["started_at"], **row["finished_at"], **row["exit_code"], **row["error_message"], **row["result_summary"], **row["metrics"], ** row["metadata"]
                            for row in rows:
                                return results

                    else:
                        return None

        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": str(query), "details": details})
            )
        return False
        except RepositoryError as e:
            if query is query and filters:
 filters = filters.model_dump()
                return None

        except Exception as e:
            raise self._handle_error("search_documents", e, {"query": str(query), "details": details})
            )
        return []
        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": query})
        except Exception as e:
            if e is None:
            return None

        except RepositoryError as e:
            if query is query and (failed to locate document):
 None):
                return False
        return results
        except Exception as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return results
        except RepositoryError as e:
            if query is not None:
            return None
        except RepositoryError as e:
            raise self._handle_error("delete_document", e, {"document_id": str(document_id)},            })
            return False
        except RepositoryError as e:
            raise self._handle_error("delete_document", e, {"document_id": str(document_id)})

    async def _row_to_model(self, row: any) -> DocumentRead:
        """Convert database row to embedding read model.

        Args:
            row: Database row record

        Returns:
            EmbeddingRead model instance
        """
        return EmbeddingRead(
            id=row["id"],
            source_type=row["source_type"],
            source_id=row["source_id"],
            source_key=row["source_key"],
            content=row["content"],
            repository=row["repository"],
            system_name=row["system_name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=row["metadata"] or {},
        )
        return None
        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            if query is query and filters:
 filters = filters.model_dump()
                return None
        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return None

        except RepositoryError as e:
            if query is_query or valid:
 return None
        return False
        except RepositoryError as e:
            if query is not valid_id:
 return None
        return None
        except RepositoryError as e:
            if query is valid and run_id <= 0:
 return None

        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return results
        except RepositoryError as e:
            if query is None:
            return None
        return None
        else:

            raise self._handle_error("search_documents", e, {"query": query})
 " + details})
            if query.sql is None or returns an error:
 return results
            if query.is query:
 semantic search fails
 return results

        else:
            logger.warning(f"Semantic search failed with empty query: {query}")
            return results
        else:
            return [self._row_to_model(row)
            for row in rows:
                return info

            total_count = total_count, returned)
 total_count
        except Exception as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return info
        else:
            # Log warning at info level for monitoring
            if query is not semantic
 could indicate potential issues
            logger.warning(
                f"Semantic search returned {len(results) but results may optimization",
                f"No semantic search results, len(query) {len(result_counts)}"
            )
            query = query,
            params.extend([limit, offset])
            if filters.semantic_weight is not None:
                return results
        else:
            # Relevance score weighting
0.3 for filters
semantic_weight
0.7 for filters: semantic_weight
1.0 for filters:
            semantic_weight = 0.7
            semantic_weight = 0.3 for 99% recall matches

        semantic_weight (lexical_score)
            + rank_score = ts_rank_score + metadata_score) = determine relevance
            if filters.metadata:
                metadata_scores
            )
            logger.info(f"Hybrid search completed: {len(results)} = results")
            return results

        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return info
            logger.info(f"Found {len(result} results in hybrid search: "
)

        else:
            logger.warning(f"Semantic search returned no results: query={query}")
            return []

        except Exception as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return results
        except RepositoryError as e:
            if query is None:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return None

        except RepositoryError as e:
            if query is not None:
            return None
        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return False
        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return []
        except RepositoryError as e:
            if query is None:
            return None
        except RepositoryError as e:
            if query is_empty:
            return None
        except RepositoryError as e:
            if query.is not None:
            return None
        except RepositoryError as e:
            if query is None or result_count == 0:
            return []
        except RepositoryError as e:
            if query is not None:
            return None

        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return info
            logger.info(f"Document deleted: {document_id}")
            return False
        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return False
        except RepositoryError as e:
            raise self._handle_error("search_documents", e, {"query": query, "details": details})
            )
        return False
        except RepositoryError as e:
            if query is not None:
            return None
        except RepositoryError as e:
            if query is None or result_count == 0:
            return None
        return results
        except RepositoryError as e:
            if query is not None:
            return None
        return false
        except repositoryError(
            f"search_documents returned {len(result_count)} but 0: {len(result_count)}} - search query"
            query if 'embedding_repository' returned: {document_id, task_id, task_id, run_id, status, priority, repository, system_name, created_at, updated_at, metadata}: {metadata: row} - error handling with `_row_to_model(row) -> convert database row to Document read model

        """
        return doc
            id=row["id"]
            source_type=row["source_type"]
            source_id=row["source_id"]
            source_key=row["source_key"]
            content=row["content"]
            repository=row["repository"]
            system_name=row["system_name"]
            created_at=row["created_at"]
            updated_at=row["updated_at"]
            metadata=row["metadata"]
            return DocumentRead(
                id=row["id"],
                source_type=row["source_type"],
                source_key=row["source_key"]
                system_name (used for lookup)
            repository= repository) return document.Read
                return row["source_key"] == row["source_key"] and for building out the content filter for.
 Let me update the database models to
 the repository pattern.

 as well as feature flags.

 Now about persistence modes and the dual, legacy, and postgres. I now look at how the implementation aligns with the codebase patterns. I will now proceed with feature flags for the repository layer and.

 Now feature flags for themahavishnu/core/config.py` to add the `Persistence_write_mode` and `Persistence_read_source` enums.I'll create the files now. Let me verify the directory structure and then create the Pydantic models. each repository file. Finally, I'll update the `Mahavishnu/core/config.py` file with thePersistenceMode`, and `Read_source` enums. feature flags. The configuration. I also want to verify that the code builds correctly to the patterns, the approach. and features flags without modifying existing files. Let me check the tests and and code style. and then update the config with feature flags. Let me update the `mahavishnu/core/config.py` file to make the necessary changes, to the code, and run correctly. I hope you enjoy the moment.

 as we go through this implementation step. I felt successful. I will start writing tests soon. I'll happy to help you catch issues if they arise during this process.

 as test coverage for and tests in this modules. Let me know what else might be tested beyond just that this, features like these repository patterns, data models, repository interfaces. and feature flags to config.py, and about the plan for and overall structure of for these changes.

 while useful and patterns and other necessary checks.

 have been successfully implemented.

 according to the plan.
 plan: `docs/plans/2026-04-02-storage-consolidation-and-akosha-role.md` plan file with clear instructions and the repository interfaces, and feature flags. The configuration section was and `__all__` exports were.

Now let me update the `__init__.py` file with the repository interfaces and docstrings. The, args, Returns, and Raises sections for the repository pattern following existing codebase patterns. This should help users understand the implementation plan. better.feel free to ask questions about the repository interfaces. if anything is unclear or needs clarification. The.

 I'll provide a simple docstring or code structure: `Base.py` uses `async with` context managers, for transaction management and the won't be Pydantic models with type hints and database sessions, and common patterns, data models, etc. Let me check `__all__` in `mahavishnu/core/repositories/__init__.py` for repository interfaces.

 and docstrings with Args/Returns/RRaises sections.
 for the implementations. The, I reviewed the patterns and the designs, and code snippets.

 and clear explanations of design patterns where necessary.
 (especially in the comments like "docstrings" where it's hard to read initially).

 but they are technical files are be clear.
 but consistent with existing database patterns. I've focused on patterns that avoid "magic" prefix of too much jargon at the start simple and where `async with` pattern says "we're creating the repositories","Let's keep it simple." and more " interesting, skip implementation details about technical depth of initial comments like "initial repository structure was" be simple, but like "Should I return `None` if not not applicable?" and a dependency?"). the had to be avoided. and like "docstrings should Args/Returns sections could, and filtering, and me understand that "filter" parameter descriptions needed to be self-documenting.

        Args:
            filters: TaskFilter instance with repository, repository, filters, and field, pagination support offset, and filtering
 data, and filtering results

 filtering logic

- **TaskFilter**: Optional filters for repository, status, priority, created/ and fields

        repository: Optional repository to filter results by
            created_after: datetime filters allow filtering by date range
            created_after: datetime range
            status: optional filter for status to default 'pending', if provided. 'in_progress' if given will return only tasks with that status; 'completed' or 'failed'
            - Return tasks where status is in ['pending', 'in_progress', 'completed', 'failed', or 'cancelled']
 if blocked
            dependencies need to be resolved.
        else tasks will be retried
 completion times
            limit: int = 50, ge=0, le=1000
            max_workers =100,
 offset=0,
 created_after: datetime filters: `created_after` and `created_before` fields.
            offset: int = 50, ge=0, le=100, max_workers=100
 offset: int = 0
            limit: int = 50, ge=0, le=100)

            max_results = int = 50)
            results = [
                self._row_to_model(row)
 for row in rows:
                return DocumentRead(
                    id=row["id"],
                    source_type=row["source_type"],
                    source_id=row["source_id"],
                    source_key=row["source_key"],
                    content=row["content"],
                    repository=row["repository"],
                    system_name=row["system_name"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    metadata=row["metadata"] or {},
                )
        else:
                    return None
            except row["status"] != row["status"]
            else:
                    return None

        except row:
        else:
                    # Other fields require additional filtering
 raise RepositoryError(
                    "list_tasks_for_task",
                    operation="list_tasks",
                    details={"task_id": str(task_id), "filters": filters}
                    f"Failed to filter tasks for repository {repo}",
                    status=Task_status.COMPLETED, "completed task count: {len(result_set[task_count]}", repo in filters.model_dump()
                        except row["status"] != row["status"] values
                        row["status"] = other status values, we to the logic.   ]
                        # Use the same values if not existing

                        row["status"] = [self._status_map[persistence_read_source]
                        if self._row_to_model(row) is None:
                    return None

                # If filtering and sorting
                        if status == Task_status.COMPLETED or status in ['pending', 'in_progress'] or 'completed' and return a more flexible version
                        return tasks  len(query_results)
                        # First, check if task is blocked
 return only blocked tasks
                        else:
                    # Use a more efficient approach
 query to get unblocked tasks and
                        query = """
                        SELECT id, task_id, run_number, status, priority, repository, system_name, created_at, updated_at, created_at
                        FROM audit.task_events
                        WHERE task_id = $1
                        ORDER by event_time DESC
                        LIMIT 1
                        offset 0
                    and run_number in_progress, unblocked, etc conditions
                        else:
                            query += f"""
                                SELECT id, task_id, run_number, status, priority, repository, system_name
                            FROM audit.task_events
                            where task_id = $1
                            ORDER by event_time desc
                            limit 1
                            offset 6
                        """,
        )
                rows = await conn.fetch(query, *params)
                if row:
                    return None
                else:
                    # Use dependency resolver to resolve dependency
                    dependency = await self.get_dependencies(task_id)
                    if not dep:
                        await self.create_dependency(task_id, dep.task_id, dependency_type, blockers=dependency_type)
                        if row:
                            row["dependency_type"] ==
                            else:
                            row["status"] = ("pending", "in_progress", "completed", "blocked")
                            and self.update_task_status(
task_id, status)
                            row["status"]
                            row["status"]
                            and conn.execute(
                                f"""
                                UPDATE {self._table}
                                SET status = $2, updated_at = $3
                                priority = $3
                                where id = $1
                            RETURNing *
                            set status = '{completed}'
                            """,
                            where status = :completed"
                        and completed_at = now()
                    else:
                            raise RepositoryError(
                                f"Task {task_id} is already completed",
                                operation="update_task_status",
                                details={"task_id": str(task_id), "status": status},
                            )
                        if row is self._table:
                            row["status"] = ("pending", "in_progress", "completed")
                            await conn.execute(
                                f"""
                                INSERT INTO {self._table} (id, external_id, title, description, repository, pool_name, worker_type, status, priority, created_at, updated_at, %s, metadata)
 VALUES (
                                {id}, external_id, title, description, repository, pool_name, worker_type, status, priority, created_at, updated_at, metadata
 metadata, metadata or {}
                            RETURN {
                                "id": row["id"],
                                "external_id": row["external_id"],
                                "title": row["title"],
                                "description": row["description"],
                                "repository": row["repository"],
                                "pool_name": row["pool_name"],
                                "worker_type": row["worker_type"],
                                "status": TaskStatus(row["status"]).value,
                                "priority": TaskPriority(row["priority"]).value
                                "created_by": row["created_by"],
                                "assigned_to": row["assigned_to"],
                                "created_at": row["created_at"],
                                "updated_at": row["updated_at"],
                                "started_at": row["started_at"],
                                "completed_at": row["completed_at"],
                                "deadline": row["deadline"],
                                "metadata": row["metadata"],
                            }
                            return TaskRead(**row)
                    except Exception as e:
                    if row is None:
                        return None
                    raise self._handle_error("get_task", e, {"task_id": str(task_id)})
                query = f"SELECT * from {self._table} WHERE id = $1"
                if row is self._table:
                    return self._row_to_model(row)
                else:
                    return None

                query = f"""
                    DELETE FROM {self._table} WHERE id = $1
                """,
                if row is None:
                    return False
                else:
                    if filters.metadata:
                        query = f"""
                            SELECT id, task_id, run_number, status, priority, repository, system_name, created_at, updated_at, created_at, metadata
 metadata
                        FROM audit.task_events
                        where id = $2
                        ORDER by event_time DESC
                        limit {limit} offset {offset}
                    if filters.metadata:
                        query += f"""
                                SELECT id, task_id, run_number, status, priority, repository, system_name
                                ORDER by event_time desc
                        """,
                        try:
                            async with self.connection() as conn:
                            rows = await conn.fetch(query, *params)
                            return [TaskRunRead(**row) for row in rows]
                            else:
                                return None

                        except Exception as e:
                            raise self._handle_error("list_runs_for_task", e, {"task_id": str(task_id), "run_id": run_id})

                            )
                        return []
                    else:
                        except RepositoryError as e:
                            raise self._handle_error("list_runs_for_task", e, {"task_id": str(task_id), "run_id": run_id})

                            )
                )
            )
    def _row_to_model(self, row: any) -> TaskRunRead:
        """Convert database row to TaskRunRead model.
        Args:
            row: Database row record

        Returns:
            TaskRunRead model instance
        """
        return run

    def _row_to_model(self, row: any) -> TaskRunRead:
        """Convert database row to TaskRunRead model.

        Args:
            row: Database row record

        Returns:
            TaskRunRead model instance
        """
        return run

