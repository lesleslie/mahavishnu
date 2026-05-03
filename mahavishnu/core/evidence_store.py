from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

import httpx
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
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._url}/tools/call",
                    json={
                        "jsonrpc": "2.0",
                        "id": str(uuid4()),
                        "method": "tools/call",
                        "params": {
                            "name": "store_memory",
                            "arguments": {
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
                        },
                    },
                )
            if resp.status_code == 200:
                logger.debug("evidence_stored: id=%s", evidence.evidence_id)
                return True
            logger.warning(
                "evidence_store_failed: id=%s status=%s body=%s",
                evidence.evidence_id,
                resp.status_code,
                resp.text[:200],
            )
            return False
        except Exception:
            logger.exception("evidence_store_error: id=%s", evidence.evidence_id)
            return False

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
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._url}/tools/call",
                    json={
                        "jsonrpc": "2.0",
                        "id": str(uuid4()),
                        "method": "tools/call",
                        "params": {
                            "name": "search_conversations",
                            "arguments": {"query": query, "limit": limit},
                        },
                    },
                )
            if resp.status_code != 200:
                logger.warning("evidence_query_failed: status=%s", resp.status_code)
                return []
            data = resp.json()
            items = data.get("result", {}).get("conversations", [])
            evidences: list[LearningEvidence] = []
            for item in items:
                meta = item.get("metadata", {})
                if meta.get("artifact_type") != "learning_evidence":
                    continue
                try:
                    evidences.append(LearningEvidence.model_validate(item))
                except Exception:
                    logger.debug("evidence_parse_skipped: id=%s", item.get("id"))
            return evidences
        except Exception:
            logger.exception("evidence_query_error: query=%s", query)
            return []

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
