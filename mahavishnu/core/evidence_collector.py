"""Evidence collection for the review-gated learning pipeline.

The Observe stage fetches recent session outcomes from Session-Buddy and
converts them into LearningEvidence objects for downstream skill synthesis.
Graceful degradation is mandatory: a failed fetch never blocks orchestration.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

import httpx

from mahavishnu.core.skill_governance import LearningEvidence

logger = logging.getLogger(__name__)


@runtime_checkable
class EvidenceSource(Protocol):
    """Abstraction over evidence providers for dependency injection."""

    async def get_recent_outcomes(self, limit: int) -> list[dict[str, Any]]: ...


class _SessionBuddyEvidenceSource:
    """Default implementation that queries Session-Buddy via MCP."""

    def __init__(self, session_buddy_url: str, store_timeout: int) -> None:
        self._url = session_buddy_url
        self._timeout = store_timeout

    async def get_recent_outcomes(self, limit: int) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._url}/tools/call",
                json={
                    "jsonrpc": "2.0",
                    "id": str(uuid4()),
                    "method": "tools/call",
                    "params": {
                        "name": "search_conversations",
                        "arguments": {"query": "outcome", "limit": limit},
                    },
                },
            )
            resp.raise_for_status()
            result = resp.json().get("result", {})
            return result.get("conversations", []) if isinstance(result, dict) else []


class EvidenceCollector:
    """Collects LearningEvidence from session outcomes.

    Accepts an optional EvidenceSource for testability; defaults to
    Session-Buddy MCP when none is provided.
    """

    def __init__(
        self,
        session_buddy_url: str = "http://localhost:8678/mcp",
        max_per_cycle: int = 50,
        store_timeout: int = 30,
        *,
        source: EvidenceSource | None = None,
    ) -> None:
        self._source = source or _SessionBuddyEvidenceSource(session_buddy_url, store_timeout)
        self._max_per_cycle = max_per_cycle

    async def collect_recent_outcomes(self) -> list[LearningEvidence]:
        try:
            raw = await self._source.get_recent_outcomes(self._max_per_cycle)
        except Exception:
            logger.warning("evidence_collection_failed: returning empty list", exc_info=True)
            return []

        evidence: list[LearningEvidence] = []
        for item in raw[: self._max_per_cycle]:
            try:
                evidence.append(self._parse_item(item))
            except Exception:
                logger.debug("skipping_unparseable_evidence_item: %s", item)
        return evidence

    async def record_outcome(
        self,
        session_id: str,
        goal: str,
        outcome: str,
        repo_paths: list[str] | None = None,
        tool_calls: list[str] | None = None,
        observations: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LearningEvidence:
        return LearningEvidence(
            evidence_id=f"le_{uuid4().hex}",
            session_id=session_id,
            goal=goal,
            outcome=outcome,
            repo_paths=repo_paths or [],
            tool_calls=tool_calls or [],
            observations=observations or [],
            collected_at=datetime.now(UTC),
            metadata=metadata or {},
        )

    @staticmethod
    def _parse_item(item: dict[str, Any]) -> LearningEvidence:
        return LearningEvidence(
            evidence_id=item.get("evidence_id", f"le_{uuid4().hex}"),
            session_id=item.get("session_id", "unknown"),
            goal=item.get("goal", item.get("summary", "")),
            outcome=item.get("outcome", item.get("status", "unknown")),
            repo_paths=item.get("repo_paths", []),
            tool_calls=item.get("tool_calls", []),
            observations=item.get("observations", []),
            collected_at=item.get("collected_at", datetime.now(UTC)),
            metadata=item.get("metadata", {}),
        )
