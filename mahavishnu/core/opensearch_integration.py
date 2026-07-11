"""OpenSearch integration for log analytics and search."""

from datetime import UTC, datetime

UTC = UTC
import logging
from typing import Any

from mahavishnu.core.opensearch_constants import OPENSEARCH_AVAILABLE


class MockIndicesClient:
    async def __call__(self):
        return self

    async def create(self, *args, **kwargs):
        return {"acknowledged": True}

    async def exists(self, *args, **kwargs):
        return False


class MockAsyncOpenSearch:
    def __init__(self, *args, **kwargs):
        self.indices = MockIndicesClient()

    async def ping(self):
        return True

    async def index(self, *args, **kwargs):
        return {"result": "created"}

    async def search(self, *args, **kwargs):
        return {"hits": {"hits": [], "total": {"value": 0}}}

    async def close(self):
        return None


if OPENSEARCH_AVAILABLE:
    from opensearchpy import AsyncOpenSearch
else:
    AsyncOpenSearch = MockAsyncOpenSearch  # type: ignore[misc]


class OpenSearchLogAnalytics:
    """OpenSearch integration for log analytics and search functionality."""

    def __init__(self, config):
        self.config = config
        self.client = None
        self.log_index = getattr(config, "opensearch_log_index", "mahavishnu-logs")
        self.workflow_index = getattr(config, "opensearch_workflow_index", "mahavishnu-workflows")

        if OPENSEARCH_AVAILABLE:
            try:
                self.client = AsyncOpenSearch(
                    hosts=[
                        config.opensearch.endpoint.replace("https://", "").replace("http://", "")
                    ],
                    http_auth=None,  # Add authentication if needed
                    use_ssl=config.opensearch.use_ssl,
                    verify_certs=config.opensearch.verify_certs,
                    ssl_assert_hostname=config.opensearch.ssl_assert_hostname,
                    ssl_show_warn=config.opensearch.ssl_show_warn,
                    ca_certs=config.opensearch.ca_certs,
                )

                # Defer index initialization to first async call
                # Cannot use asyncio.create_task() in sync __init__ context
                self._indices_initialized = False
            except Exception as e:
                logging.warning(f"Failed to initialize OpenSearch client: {e}")
                self.client = MockAsyncOpenSearch()
        else:
            self.client = MockAsyncOpenSearch()

        # Track whether indices have been initialized
        self._indices_initialized = False

    async def _ensure_indices(self):
        """Lazily initialize indices on first async access."""
        if not self._indices_initialized:
            await self._init_indices()
            self._indices_initialized = True

    async def _init_indices(self):
        """Initialize required indices."""
        await self._create_log_index()
        await self._create_workflow_index()

    async def _create_log_index(self):
        """Create the log index with appropriate mapping."""
        if not self.client:
            return

        try:
            if not await self.client.indices.exists(index=self.log_index):
                mapping = {
                    "mappings": {
                        "properties": {
                            "timestamp": {"type": "date"},
                            "level": {"type": "keyword"},
                            "message": {"type": "text"},
                            "attributes": {"type": "object", "enabled": True},
                            "trace_id": {"type": "keyword"},
                            "workflow_id": {"type": "keyword"},
                            "repo_path": {"type": "keyword"},
                            "adapter": {"type": "keyword"},
                        }
                    }
                }
                await self.client.indices.create(index=self.log_index, body=mapping)
        except Exception as e:
            logging.warning(f"Failed to create log index: {e}")

    async def _create_workflow_index(self):
        """Create the workflow index with appropriate mapping."""
        if not self.client:
            return

        try:
            if not await self.client.indices.exists(index=self.workflow_index):
                mapping = {
                    "mappings": {
                        "properties": {
                            "workflow_id": {"type": "keyword"},
                            "adapter": {"type": "keyword"},
                            "task_type": {"type": "keyword"},
                            "status": {"type": "keyword"},
                            "created_at": {"type": "date"},
                            "updated_at": {"type": "date"},
                            "completed_at": {"type": "date"},
                            "progress": {"type": "integer"},
                            "repos_processed": {"type": "integer"},
                            "execution_time_seconds": {"type": "float"},
                            "results_count": {"type": "integer"},
                            "errors_count": {"type": "integer"},
                            "error": {"type": "text"},
                            "repos": {"type": "keyword"},
                        }
                    }
                }
                await self.client.indices.create(index=self.workflow_index, body=mapping)
        except Exception as e:
            logging.warning(f"Failed to create workflow index: {e}")

    async def log_event(
        self,
        level: str,
        message: str,
        attributes: dict[str, Any] | None = None,
        trace_id: str | None = None,
        workflow_id: str | None = None,
        repo_path: str | None = None,
        adapter: str | None = None,
    ):
        """Log an event to OpenSearch."""
        if not self.client:
            return

        await self._ensure_indices()

        try:
            doc = {
                "timestamp": datetime.now(tz=UTC).isoformat(),
                "level": level,
                "message": message,
                "attributes": attributes or {},
                "trace_id": trace_id,
                "workflow_id": workflow_id,
                "repo_path": repo_path,
                "adapter": adapter,
            }

            await self.client.index(index=self.log_index, body=doc)
        except Exception as e:
            logging.warning(f"Failed to log event to OpenSearch: {e}")

    async def log_workflow_event(
        self, workflow_id: str, adapter: str, task_type: str, status: str, **kwargs
    ):
        """Log a workflow event to OpenSearch."""
        if not self.client:
            return

        await self._ensure_indices()

        try:
            doc = {
                "workflow_id": workflow_id,
                "adapter": adapter,
                "task_type": task_type,
                "status": status,
                "timestamp": datetime.now(tz=UTC).isoformat(),
                **kwargs,
            }

            await self.client.index(index=self.workflow_index, body=doc)
        except Exception as e:
            logging.warning(f"Failed to log workflow event to OpenSearch: {e}")

    async def search_logs(
        self,
        query: str | None = None,
        level: str | None = None,
        workflow_id: str | None = None,
        repo_path: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        size: int = 100,
    ) -> list[dict[str, Any]]:
        """Search logs with various filters."""
        if not self.client:
            return []

        try:
            search_body = {"query": {"bool": {"must": []}}, "size": size}

            if query:
                search_body["query"]["bool"]["must"].append(  # type: ignore[invalid-index]
                    {"simple_query_string": {"query": query}}
                )

            if level:
                search_body["query"]["bool"]["must"].append({"term": {"level": level}})  # type: ignore[invalid-index]

            if workflow_id:
                search_body["query"]["bool"]["must"].append({"term": {"workflow_id": workflow_id}})  # type: ignore[invalid-index]

            if repo_path:
                search_body["query"]["bool"]["must"].append({"term": {"repo_path": repo_path}})  # type: ignore[invalid-index]

            if start_time or end_time:
                date_range = {}
                if start_time:
                    date_range["gte"] = start_time
                if end_time:
                    date_range["lte"] = end_time
                search_body["query"]["bool"]["must"].append({"range": {"timestamp": date_range}})  # type: ignore[invalid-index]

            # If no filters, match all
            if not search_body["query"]["bool"]["must"]:  # type: ignore[invalid-index]
                search_body["query"] = {"match_all": {}}

            response = await self.client.search(index=self.log_index, body=search_body)

            return [hit["_source"] for hit in response["hits"]["hits"]]
        except Exception as e:
            logging.warning(f"Failed to search logs in OpenSearch: {e}")
            return []

    async def search_workflows(
        self,
        workflow_id: str | None = None,
        adapter: str | None = None,
        task_type: str | None = None,
        status: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        size: int = 100,
    ) -> list[dict[str, Any]]:
        """Search workflows with various filters."""
        if not self.client:
            return []

        try:
            search_body = {"query": {"bool": {"must": []}}, "size": size}

            if workflow_id:
                search_body["query"]["bool"]["must"].append({"term": {"workflow_id": workflow_id}})  # type: ignore[invalid-index]

            if adapter:
                search_body["query"]["bool"]["must"].append({"term": {"adapter": adapter}})  # type: ignore[invalid-index]

            if task_type:
                search_body["query"]["bool"]["must"].append({"term": {"task_type": task_type}})  # type: ignore[invalid-index]

            if status:
                search_body["query"]["bool"]["must"].append({"term": {"status": status}})  # type: ignore[invalid-index]

            if start_time or end_time:
                date_range = {}
                if start_time:
                    date_range["gte"] = start_time
                if end_time:
                    date_range["lte"] = end_time
                search_body["query"]["bool"]["must"].append({"range": {"timestamp": date_range}})  # type: ignore[invalid-index]

            # If no filters, match all
            if not search_body["query"]["bool"]["must"]:  # type: ignore[invalid-index]
                search_body["query"] = {"match_all": {}}

            response = await self.client.search(index=self.workflow_index, body=search_body)

            return [hit["_source"] for hit in response["hits"]["hits"]]
        except Exception as e:
            logging.warning(f"Failed to search workflows in OpenSearch: {e}")
            return []

    async def get_workflow_stats(self) -> dict[str, Any]:
        """Get workflow statistics."""
        if not self.client:
            return {}

        try:
            # Get total workflow count
            total_response = await self.client.search(
                index=self.workflow_index, body={"query": {"match_all": {}}, "size": 0}
            )
            total_workflows = total_response["hits"]["total"]["value"]

            # Get workflow status breakdown
            status_agg_response = await self.client.search(
                index=self.workflow_index,
                body={"size": 0, "aggs": {"status_breakdown": {"terms": {"field": "status"}}}},
            )
            status_breakdown = {
                bucket["key"]: bucket["doc_count"]
                for bucket in status_agg_response["aggregations"]["status_breakdown"]["buckets"]
            }

            # Get adapter breakdown
            adapter_agg_response = await self.client.search(
                index=self.workflow_index,
                body={"size": 0, "aggs": {"adapter_breakdown": {"terms": {"field": "adapter"}}}},
            )
            adapter_breakdown = {
                bucket["key"]: bucket["doc_count"]
                for bucket in adapter_agg_response["aggregations"]["adapter_breakdown"]["buckets"]
            }

            return {
                "total_workflows": total_workflows,
                "status_breakdown": status_breakdown,
                "adapter_breakdown": adapter_breakdown,
            }
        except Exception as e:
            logging.warning(f"Failed to get workflow stats from OpenSearch: {e}")
            return {}

    async def get_log_stats(self) -> dict[str, Any]:
        """Get log statistics."""
        if not self.client:
            return {}

        try:
            # Get total log count
            total_response = await self.client.search(
                index=self.log_index, body={"query": {"match_all": {}}, "size": 0}
            )
            total_logs = total_response["hits"]["total"]["value"]

            # Get log level breakdown
            level_agg_response = await self.client.search(
                index=self.log_index,
                body={"size": 0, "aggs": {"level_breakdown": {"terms": {"field": "level"}}}},
            )
            level_breakdown = {
                bucket["key"]: bucket["doc_count"]
                for bucket in level_agg_response["aggregations"]["level_breakdown"]["buckets"]
            }

            return {"total_logs": total_logs, "level_breakdown": level_breakdown}
        except Exception as e:
            logging.warning(f"Failed to get log stats from OpenSearch: {e}")
            return {}

    async def health_check(self) -> dict[str, Any]:
        """Check OpenSearch health."""
        if not self.client:
            return {"status": "unavailable", "error": "OpenSearch client not initialized"}

        try:
            is_connected = await self.client.ping()
            if is_connected:
                return {
                    "status": "healthy",
                    "indices": {
                        "logs": await self.client.indices.exists(index=self.log_index),
                        "workflows": await self.client.indices.exists(index=self.workflow_index),
                    },
                }
            else:
                return {"status": "unhealthy", "error": "Cannot connect to OpenSearch"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def close(self):
        """Close the OpenSearch client."""
        if self.client and hasattr(self.client, "close"):
            await self.client.close()


class OpenSearchIntegration:
    """Integration layer between Mahavishnu and OpenSearch."""

    def __init__(self, config):
        self.analytics = OpenSearchLogAnalytics(config)
        self.config = config

    async def log_workflow_start(
        self, workflow_id: str, adapter: str, task_type: str, repos: list[str]
    ):
        """Log workflow start event."""
        await self.analytics.log_workflow_event(
            workflow_id=workflow_id,
            adapter=adapter,
            task_type=task_type,
            status="started",
            repos=repos,
            start_time=datetime.now(tz=UTC).isoformat(),
        )

        await self.analytics.log_event(
            level="INFO",
            message=f"Workflow {workflow_id} started with adapter {adapter}",
            attributes={"workflow_id": workflow_id, "adapter": adapter, "task_type": task_type},
            workflow_id=workflow_id,
            adapter=adapter,
        )

    async def log_workflow_update(
        self, workflow_id: str, status: str, progress: int | None = None, **kwargs
    ):
        """Log workflow update event."""
        details = dict(kwargs)
        adapter = details.pop("adapter", "unknown")
        task_type = details.pop("task_type", "unknown")

        await self.analytics.log_workflow_event(
            workflow_id=workflow_id,
            adapter=adapter,
            task_type=task_type,
            status=status,
            progress=progress,
            **details,
        )

        await self.analytics.log_event(
            level="INFO",
            message=f"Workflow {workflow_id} updated to status {status}",
            attributes={"workflow_id": workflow_id, "status": status, "progress": progress},
            workflow_id=workflow_id,
        )

    async def log_workflow_completion(
        self,
        workflow_id: str,
        status: str,
        execution_time: float,
        results_count: int,
        errors_count: int,
        **kwargs,
    ):
        """Log workflow completion event."""
        details = dict(kwargs)
        adapter = details.pop("adapter", "unknown")
        task_type = details.pop("task_type", "unknown")

        await self.analytics.log_workflow_event(
            workflow_id=workflow_id,
            adapter=adapter,
            task_type=task_type,
            status=status,
            execution_time_seconds=execution_time,
            results_count=results_count,
            errors_count=errors_count,
            completed_at=datetime.now(tz=UTC).isoformat(),
            **details,
        )

        await self.analytics.log_event(
            level="INFO",
            message=f"Workflow {workflow_id} completed with status {status}",
            attributes={
                "workflow_id": workflow_id,
                "status": status,
                "execution_time": execution_time,
                "results_count": results_count,
                "errors_count": errors_count,
            },
            workflow_id=workflow_id,
        )

    async def log_error(
        self,
        workflow_id: str,
        error_msg: str,
        repo_path: str | None = None,
        adapter: str | None = None,
        attributes: dict[str, Any] | None = None,
    ):
        """Log an error event."""
        await self.analytics.log_event(
            level="ERROR",
            message=error_msg,
            attributes={
                "workflow_id": workflow_id,
                "repo_path": repo_path,
                **(attributes or {}),
            },
            workflow_id=workflow_id,
            repo_path=repo_path,
            adapter=adapter,
        )

    async def search_logs(self, **kwargs) -> list[dict[str, Any]]:
        """Search logs with provided filters."""
        return await self.analytics.search_logs(**kwargs)

    async def search_workflows(self, **kwargs) -> list[dict[str, Any]]:
        """Search workflows with provided filters."""
        return await self.analytics.search_workflows(**kwargs)

    async def get_workflow_stats(self) -> dict[str, Any]:
        """Get workflow statistics."""
        return await self.analytics.get_workflow_stats()

    async def get_log_stats(self) -> dict[str, Any]:
        """Get log statistics."""
        return await self.analytics.get_log_stats()

    async def health_check(self) -> dict[str, Any]:
        """Check OpenSearch health."""
        return await self.analytics.health_check()
