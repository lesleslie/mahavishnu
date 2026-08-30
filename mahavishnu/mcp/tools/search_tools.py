"""MCP tools for hybrid search operations.

This module provides MCP tools that expose the hybrid search functionality:
- hybrid_search: Search across documents using semantic + lexical search
- index_document: Index a new document for search
- delete_document: Remove a document from the search index
- cross_repo_search: Fan out to Akosha + Session-Buddy and aggregate results

These tools integrate with the HybridSearchEngine and follow the MCP tool
patterns established in the mahavishnu.mcp.tools module.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx  # exposed for tests via patch()
from mcp_common.websocket import (  # exposed for tests via patch()
    MessageType,
    WebSocketMessage,
)

from mahavishnu.core.config import get_settings as _get_settings
from mahavishnu.core.database import get_database
from mahavishnu.core.search import HybridSearchConfig, HybridSearchEngine
from mahavishnu.factories import (  # exposed for tests via patch()
    get_websocket_server as _get_websocket_server,
)

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Registration
# =============================================================================


def register_search_tools(mcp: FastMCP) -> None:
    """Register hybrid search tools with MCP server.

    Args:
        mcp: FastMCP server instance
    """
    # Global search engine instance (lazy initialization)
    _search_engine: HybridSearchEngine | None = None

    async def get_search_engine() -> HybridSearchEngine:
        """Get or create hybrid search engine instance."""
        nonlocal _search_engine
        if _search_engine is None:
            db = await get_database()
            config = HybridSearchConfig()  # Uses defaults
            _search_engine = HybridSearchEngine(database=db, config=config)
        return _search_engine

    @mcp.tool()
    async def hybrid_search(
        query: str,
        repository: str | None = None,
        limit: int = 20,
        semantic_weight: float = 0.7,
        lexical_weight: float = 0.3,
        min_score: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Search across documents using hybrid semantic + lexical search."""
        try:
            # Create config with custom weights
            config = HybridSearchConfig(
                semantic_weight=semantic_weight,
                lexical_weight=lexical_weight,
                default_limit=limit,
                min_score=min_score,
            )

            # Get search engine with custom config
            engine = await get_search_engine()
            engine.config = config  # Update config for this search

            # Execute search
            results = await engine.search(
                query=query,
                repository=repository,
                limit=limit,
            )

            # Convert to dict for JSON serialization
            return [result.model_dump() for result in results]

        except Exception as e:
            logger.exception(
                "hybrid_search tool failed",
                extra={
                    "query": query[:100],
                    "repository": repository,
                    "error": str(e),
                },
            )
            raise

    @mcp.tool()
    async def index_document(
        doc_id: str,
        title: str,
        content: str,
        repository: str | None = None,
        source_type: str = "document",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Index a document for hybrid search."""
        try:
            # Parse UUID
            doc_uuid = UUID(doc_id)

            # Get search engine
            engine = await get_search_engine()

            # Index document
            await engine.index_document(
                doc_id=doc_uuid,
                title=title,
                content=content,
                metadata=metadata or {},
                repository=repository,
                source_type=source_type,
            )

            return {
                "success": True,
                "doc_id": doc_id,
                "message": "Document indexed successfully",
            }

        except ValueError as e:
            logger.error(
                "index_document tool failed: invalid UUID",
                extra={"doc_id": doc_id, "error": str(e)},
            )
            raise ValueError(f"Invalid document UUID: {doc_id}") from e
        except Exception as e:
            logger.exception(
                "index_document tool failed",
                extra={
                    "doc_id": doc_id,
                    "title": title[:50] if title else None,
                    "error": str(e),
                },
            )
            raise

    @mcp.tool()
    async def delete_document(doc_id: str) -> dict[str, Any]:
        """Delete a document from the search index."""
        try:
            # Parse UUID
            doc_uuid = UUID(doc_id)

            # Get search engine
            engine = await get_search_engine()

            # Delete document
            deleted = await engine.delete_document(doc_uuid)

            return {
                "success": True,
                "doc_id": doc_id,
                "deleted": deleted,
                "message": "Document deleted successfully" if deleted else "Document not found",
            }

        except ValueError as e:
            logger.error(
                "delete_document tool failed: invalid UUID",
                extra={"doc_id": doc_id, "error": str(e)},
            )
            raise ValueError(f"Invalid document UUID: {doc_id}") from e
        except Exception as e:
            logger.exception(
                "delete_document tool failed",
                extra={"doc_id": doc_id, "error": str(e)},
            )
            raise

    @mcp.tool()
    async def search_by_repository(
        repository: str,
        query: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search documents within a specific repository."""
        try:
            engine = await get_search_engine()

            # If query is empty, do a broad search (effectively recent docs)
            search_query = query if query.strip() else "a"  # Minimal query to get results

            results = await engine.search(
                query=search_query,
                repository=repository,
                limit=limit,
            )

            return [result.model_dump() for result in results]

        except Exception as e:
            logger.exception(
                "search_by_repository tool failed",
                extra={
                    "repository": repository,
                    "query": query[:100],
                    "error": str(e),
                },
            )
            raise

    @mcp.tool()
    async def cross_repo_search(
        query: str,
        scope: str = "capabilities",
        repo_filter: str | None = None,
        limit: int = 20,
        stream_channel: bool = False,
    ) -> dict[str, Any]:
        """Fan-out search across Akosha + Session-Buddy and aggregate results.

        Phase 1 of the v2 plan: aggregates capability descriptors
        (``scope="capabilities"``) and run-history records
        (``scope="runs"``) across every Bodai component.

        Args:
            query: Natural-language search query.
            scope: ``capabilities`` (default) fans out to Akosha's
                ``cross_repo_capability_search``; ``runs`` fans out to
                Session-Buddy's ``ecosystem_run_history`` (treats ``query``
                as ``workflow_id``).
            repo_filter: Optional repo key to narrow the search.
            limit: Maximum results to return per source (1-100). Default 20.
            stream_channel: When True, the tool publishes a
                ``cross-repo:{query_hash}`` event over WebSocket and
                returns the channel name in addition to the result.

        Returns:
            dict with keys:
                query: the original query
                scope: which scope was queried
                query_hash: sha1 hex of the query (used for channel naming)
                sources: list of {name, status, results, error}
                combined: aggregated results (deduped + ranked)
                channel: optional cross-repo:{query_hash} if stream_channel
                mode: ``fanout`` once both Akosha + Session-Buddy run;
                    ``stub`` when those services are unreachable.
        """
        if scope not in {"capabilities", "runs"}:
            raise ValueError(f"scope must be 'capabilities' or 'runs'; got {scope!r}")
        if not (1 <= limit <= 100):
            raise ValueError(f"limit must be 1-100; got {limit}")

        query_hash = hashlib.sha256(f"{scope}::{query}::{repo_filter or ''}".encode()).hexdigest()[
            :16
        ]

        settings = _get_settings()
        akosha_url = getattr(settings, "akosha_url", "http://localhost:8682/mcp")
        session_buddy_url = getattr(settings, "session_buddy_url", "http://localhost:8678/mcp")

        sources: list[dict[str, Any]] = []
        combined: list[dict[str, Any]] = []

        # ---- Akosha capability search ----
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if scope == "capabilities":
                    akosha_args: dict[str, Any] = {
                        "query": query,
                        "limit": limit,
                    }
                    if repo_filter:
                        akosha_args["repo_filter"] = repo_filter
                    akosha_resp = await client.post(
                        f"{akosha_url}/tools/call",
                        json={
                            "name": "cross_repo_capability_search",
                            "arguments": akosha_args,
                        },
                    )
                    akosha_resp.raise_for_status()
                    akosha_payload = akosha_resp.json()
                    akosha_results = (
                        akosha_payload.get("result", {}).get("results", [])
                        if isinstance(akosha_payload.get("result"), dict)
                        else akosha_payload.get("results", [])
                    )
                else:  # scope == "runs"
                    akosha_resp = await client.post(
                        f"{akosha_url}/tools/call",
                        json={
                            "name": "search_all_systems",
                            "arguments": {"query": query, "limit": limit},
                        },
                    )
                    akosha_resp.raise_for_status()
                    akosha_payload = akosha_resp.json()
                    akosha_results = (
                        akosha_payload.get("results", [])
                        if isinstance(akosha_payload, dict)
                        else []
                    )
                sources.append(
                    {
                        "name": "akosha",
                        "status": "ok",
                        "url": akosha_url,
                        "count": len(akosha_results),
                    }
                )
                for r in akosha_results:
                    r = dict(r)
                    r["source"] = "akosha"
                    combined.append(r)
        except Exception as exc:  # noqa: BLE001 - external service fan-out must not break the search response
            logger.warning("cross_repo_search: akosha fan-out failed: %s", exc)
            sources.append(
                {
                    "name": "akosha",
                    "status": "error",
                    "url": akosha_url,
                    "error": str(exc),
                    "count": 0,
                }
            )

        # ---- Session-Buddy run history ----
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if scope == "runs":
                    sb_args: dict[str, Any] = {
                        "workflow_id": query,
                        "scope": repo_filter or "all",
                    }
                    sb_tool = "ecosystem_run_history"
                else:
                    sb_args = {
                        "workflow_id": query,
                        "scope": "all",
                    }
                    sb_tool = "ecosystem_run_history"

                sb_resp = await client.post(
                    f"{session_buddy_url}/tools/call",
                    json={"name": sb_tool, "arguments": sb_args},
                )
                sb_resp.raise_for_status()
                sb_payload = sb_resp.json()
                sb_result = sb_payload.get("result", {})
                if isinstance(sb_result, str):
                    import json as _json

                    try:
                        sb_result = _json.loads(sb_result)
                    except _json.JSONDecodeError:
                        sb_result = {}
                sb_components = (
                    sb_result.get("components", []) if isinstance(sb_result, dict) else []
                )
                sources.append(
                    {
                        "name": "session-buddy",
                        "status": "ok",
                        "url": session_buddy_url,
                        "count": len(sb_components),
                    }
                )
                for c in sb_components:
                    c = dict(c)
                    c["source"] = "session-buddy"
                    combined.append(c)
        except Exception as exc:  # noqa: BLE001 - external service fan-out must not break the search response
            logger.warning("cross_repo_search: session-buddy fan-out failed: %s", exc)
            sources.append(
                {
                    "name": "session-buddy",
                    "status": "error",
                    "url": session_buddy_url,
                    "error": str(exc),
                    "count": 0,
                }
            )

        # Deduplicate by (repo, name) when possible, otherwise by source+hash.
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for entry in combined:
            key = "|".join(
                [
                    str(entry.get("source", "")),
                    str(entry.get("repo", "")),
                    str(entry.get("name", "")),
                ]
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(entry)

        deduped.sort(
            key=lambda e: float(e.get("score", 0.0) or 0.0),
            reverse=True,
        )

        repos_seen = sorted({e.get("repo", "") for e in deduped if e.get("repo")})
        ok_count = sum(1 for s in sources if s["status"] == "ok")
        mode = "fanout" if ok_count == len(sources) and sources else "degraded"

        result: dict[str, Any] = {
            "query": query,
            "scope": scope,
            "query_hash": query_hash,
            "sources": sources,
            "combined": deduped[:limit],
            "total_combined": len(deduped),
            "repos_seen": repos_seen,
            "spans_3_components": len(repos_seen) >= 3,
            "mode": mode,
        }

        if stream_channel:
            channel = f"cross-repo:{query_hash}"
            result["channel"] = channel
            try:
                server = _get_websocket_server()
                if server is not None:
                    msg = WebSocketMessage(
                        type=MessageType.EVENT,
                        data={
                            "event_type": "cross_repo_search_result",
                            "channel": channel,
                            "payload": result,
                        },
                    )
                    await server.broadcast_to_room(channel, msg)
            except Exception as exc:  # noqa: BLE001 - websocket broadcast failure must not block the search result
                logger.warning("cross_repo_search: websocket broadcast failed: %s", exc)

        return result

    logger.info("Registered hybrid search MCP tools")


# =============================================================================
# Module-level registration for auto-discovery
# =============================================================================

__all__ = ["register_search_tools"]
