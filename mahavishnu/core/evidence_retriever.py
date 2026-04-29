from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import logging
from typing import Protocol, runtime_checkable
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

from mahavishnu.core.skill_governance import LearningEvidence

logger = logging.getLogger(__name__)


class RetrievedEvidence(BaseModel):
    evidence_id: str
    similarity: float
    goal: str
    outcome: str
    observations: list[str] = Field(default_factory=list)
    source: str = "akosha"


class EvidenceCluster(BaseModel):
    cluster_id: str
    representative_goal: str
    repo_paths: list[str] = Field(default_factory=list)
    member_count: int
    success_rate: float
    evidence_ids: list[str] = Field(default_factory=list)


class RetrievalContext(BaseModel):
    similar_evidence: list[RetrievedEvidence] = Field(default_factory=list)
    clusters: list[EvidenceCluster] = Field(default_factory=list)
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    query: str


@runtime_checkable
class EvidenceRetrieval(Protocol):
    async def find_similar(self, evidence: LearningEvidence, limit: int) -> list[RetrievedEvidence]: ...
    async def cluster_by_pattern(self, evidences: list[LearningEvidence]) -> list[EvidenceCluster]: ...


class EvidenceRetriever:
    """Retrieve stage of the learning pipeline.

    Uses Akosha semantic search to find similar past successes and failures,
    and clusters evidence by shared patterns for skill synthesis.
    """

    def __init__(
        self,
        akosha_url: str,
        session_buddy_url: str,
        timeout_seconds: int = 15,
    ) -> None:
        self._akosha_url = akosha_url.rstrip("/")
        self._session_buddy_url = session_buddy_url.rstrip("/")
        self._timeout = timeout_seconds

    async def find_similar(
        self, evidence: LearningEvidence, limit: int = 10
    ) -> list[RetrievedEvidence]:
        query = f"{evidence.goal} {' '.join(evidence.observations)}"
        results: list[RetrievedEvidence] = []

        try:
            akosha_results = await self._search_akosha(query, limit)
            results.extend(akosha_results)
        except Exception:
            logger.warning("akosha_search_failed: falling back to Session-Buddy", exc_info=True)
            results.extend(await self._search_session_buddy(query, limit))

        results.sort(key=lambda r: r.similarity, reverse=True)
        return results[:limit]

    async def cluster_by_pattern(
        self,
        evidences: list[LearningEvidence],
        min_cluster_size: int = 2,
    ) -> list[EvidenceCluster]:
        if not evidences:
            return []

        return self._build_clusters(evidences, min_cluster_size)

    async def get_retrieval_context(
        self, goal: str, repo_paths: list[str]
    ) -> RetrievalContext:
        synthetic_evidence = LearningEvidence(
            session_id="retrieval_query",
            goal=goal,
            outcome="query",
            repo_paths=repo_paths,
        )

        similar = await self.find_similar(synthetic_evidence)
        recent_evidences = [
            LearningEvidence(
                evidence_id=r.evidence_id,
                session_id="retrieved",
                goal=r.goal,
                outcome=r.outcome,
                observations=r.observations,
            )
            for r in similar
        ]
        clusters = await self.cluster_by_pattern(recent_evidences)

        return RetrievalContext(
            similar_evidence=similar,
            clusters=clusters,
            query=goal,
        )

    async def _search_akosha(
        self, query: str, limit: int
    ) -> list[RetrievedEvidence]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._akosha_url}/tools/call",
                json={
                    "jsonrpc": "2.0",
                    "id": str(uuid4()),
                    "method": "tools/call",
                    "params": {
                        "name": "search_all_systems",
                        "arguments": {"query": query, "limit": limit},
                    },
                },
            )
            if resp.status_code != 200:
                logger.warning("akosha_search_http_error: status=%s", resp.status_code)
                return []

            data = resp.json()
            items = data.get("result", {}).get("results", [])
            if not items:
                items = data.get("result", {}).get("content", [])
            if isinstance(items, dict):
                items = items.get("items", [])

            results: list[RetrievedEvidence] = []
            for item in items:
                if isinstance(item, dict):
                    results.append(
                        RetrievedEvidence(
                            evidence_id=item.get("id", item.get("evidence_id", f"re_{uuid4().hex}")),
                            similarity=float(item.get("score", item.get("similarity", 0.0))),
                            goal=item.get("text", item.get("goal", "")),
                            outcome=item.get("outcome", item.get("metadata", {}).get("outcome", "")),
                            observations=item.get("observations", item.get("metadata", {}).get("observations", [])),
                            source="akosha",
                        )
                    )
            return results

    async def _search_session_buddy(
        self, query: str, limit: int
    ) -> list[RetrievedEvidence]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._session_buddy_url}/tools/call",
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
                    logger.warning("session_buddy_search_http_error: status=%s", resp.status_code)
                    return []

                data = resp.json()
                items = data.get("result", {}).get("conversations", [])
                results: list[RetrievedEvidence] = []
                for item in items:
                    meta = item.get("metadata", {})
                    if meta.get("artifact_type") != "learning_evidence":
                        continue
                    results.append(
                        RetrievedEvidence(
                            evidence_id=item.get("id", item.get("evidence_id", f"re_{uuid4().hex}")),
                            similarity=float(item.get("score", 0.5)),
                            goal=item.get("summary", item.get("goal", "")),
                            outcome=meta.get("outcome", ""),
                            observations=meta.get("observations", []),
                            source="session_buddy",
                        )
                    )
                return results
        except Exception:
            logger.warning("session_buddy_search_failed: returning empty", exc_info=True)
            return []

    def _build_clusters(
        self,
        evidences: list[LearningEvidence],
        min_cluster_size: int,
    ) -> list[EvidenceCluster]:
        groups: dict[frozenset[str], list[LearningEvidence]] = defaultdict(list)

        for ev in evidences:
            repo_key = frozenset(ev.repo_paths) if ev.repo_paths else frozenset({"_unclassified"})
            groups[repo_key].append(ev)

        clusters: list[EvidenceCluster] = []
        for repo_key, members in groups.items():
            if len(members) < min_cluster_size:
                continue

            keyword_groups: dict[tuple[str, ...], list[LearningEvidence]] = defaultdict(list)
            for m in members:
                kw = tuple(sorted(_extract_keywords(m.goal)))
                keyword_groups[kw].append(m)

            for kw_tuple, kw_members in keyword_groups.items():
                if len(kw_members) < min_cluster_size:
                    continue

                sorted_members = sorted(kw_members, key=lambda e: e.collected_at, reverse=True)
                representative = sorted_members[0]

                success_count = sum(1 for e in kw_members if "success" in e.outcome.lower())
                success_rate = success_count / len(kw_members) if kw_members else 0.0

                cluster_id = f"cl_{abs(hash(repo_key)) % (10**12):012x}_{abs(hash(kw_tuple)) % (10**8):08x}"
                clusters.append(
                    EvidenceCluster(
                        cluster_id=cluster_id,
                        representative_goal=representative.goal,
                        repo_paths=sorted(repo_key),
                        member_count=len(kw_members),
                        success_rate=round(success_rate, 3),
                        evidence_ids=[e.evidence_id for e in kw_members],
                    )
                )

        return clusters


_STOP_WORDS = frozenset(
    ["a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "can", "this", "that", "these", "those", "it", "its", "from", "into", "about", "as", "if", "then", "than", "so", "no", "not", "when", "where", "how", "what", "which", "who", "whom", "up", "out", "off", "over", "under", "between", "after", "before", "during", "without", "through", "against"]
)


def _extract_keywords(text: str) -> set[str]:
    return {
        word.lower()
        for word in text.split()
        if len(word) > 2 and word.lower() not in _STOP_WORDS
    }


__all__ = [
    "EvidenceCluster",
    "EvidenceRetrieval",
    "EvidenceRetriever",
    "RetrievedEvidence",
    "RetrievalContext",
]
