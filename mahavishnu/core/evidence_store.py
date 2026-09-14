from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol, runtime_checkable

from mcp_common.clients.common_mcp_client import CommonMCPClient
from mcp_common.exceptions import MCPServerError
from pydantic import BaseModel, Field

from mahavishnu.core.skill_governance import LearningEvidence

logger = logging.getLogger(__name__)


class StoreBatchResult(BaseModel):
    stored_count: int = 0
    failed_count: int = 0
    errors: list[str] = Field(default_factory=list)


@runtime_checkable
class EvidenceStorage(Protocol):
    async def store_evidence(self, evidence: LearningEvidence) -> bool: ...
    async def query_evidence(self, query: str, limit: int) -> list[dict[str, Any]]: ...


class EvidenceStore:
    """Persist LearningEvidence artifacts to Session-Buddy via MCP.

    Follows the same graceful-degradation pattern as MemoryAggregator:
    every method returns a result rather than raising, so upstream callers
    never need to handle transport-level exceptions.
    """

    def __init__(self, session_buddy_url: str, timeout_seconds: int = 10) -> None:
        self._url = session_buddy_url.rstrip("/")
        self._timeout = timeout_seconds

    async def store(self, evidence: LearningEvidence) -> bool:
        client = CommonMCPClient(base_url=self._url, timeout=self._timeout)
        try:
            try:
                await client.call_tool(
                    "store_memory",
                    {
                        "memory_id": evidence.evidence_id,
                        "text": evidence.goal,
                        "metadata": {
                            "artifact_type": "learning_evidence",
                            "evidence_id": evidence.evidence_id,
                            "session_id": evidence.session_id,
                            "outcome": evidence.outcome,
                            "repo_paths": evidence.repo_paths,
                            "tool_calls": evidence.tool_calls,
                            "collected_at": evidence.collected_at.isoformat(),
                        },
                    },
                )
                logger.debug("evidence_stored: id=%s", evidence.evidence_id)
                return True
            except MCPServerError as exc:
                logger.warning("evidence_store_failed: id=%s err=%s", evidence.evidence_id, exc)
                return False
            except Exception:
                logger.exception("evidence_store_error: id=%s", evidence.evidence_id)
                return False
        finally:
            await client.aclose()

    async def store_batch(self, evidences: list[LearningEvidence]) -> StoreBatchResult:
        results = await asyncio.gather(
            *(self.store(e) for e in evidences),
            return_exceptions=True,
        )
        stored = 0
        failed = 0
        errors: list[str] = []
        for ev, result in zip(evidences, results, strict=False):
            if result is True:
                stored += 1
            else:
                failed += 1
                msg = str(result) if isinstance(result, Exception) else "store returned False"
                errors.append(f"{ev.evidence_id}: {msg}")
        return StoreBatchResult(stored_count=stored, failed_count=failed, errors=errors)

    async def query_evidence(self, query: str, limit: int = 20) -> list[LearningEvidence]:
        client = CommonMCPClient(base_url=self._url, timeout=self._timeout)
        try:
            try:
                result = await client.call_tool(
                    "search_conversations",
                    {"query": query, "limit": limit},
                )
            except MCPServerError as exc:
                logger.warning("evidence_query_failed: err=%s", exc)
                return []
            except Exception:
                logger.exception("evidence_query_error: query=%s", query)
                return []

            if isinstance(result, dict):
                items = result.get("conversations", [])
            elif isinstance(result, list):
                items = result
            else:
                items = []

            evidences: list[LearningEvidence] = []
            for item in items:
                meta = item.get("metadata", {})
                if meta.get("artifact_type") != "learning_evidence":
                    continue
                try:
                    evidences.append(LearningEvidence.model_validate(item))
                except ValueError, TypeError:
                    logger.debug("evidence_parse_skipped: id=%s", item.get("id"))
            return evidences
        finally:
            await client.aclose()

    async def prune_expired(self, retention_days: int) -> int:
        logger.warning(
            "evidence_prune_noop: retention_days=%d — cleanup deferred to Session-Buddy TTL",
            retention_days,
        )
        return 0


__all__ = [
    "EvidenceStorage",
    "EvidenceStore",
    "StoreBatchResult",
]
