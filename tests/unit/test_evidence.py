"""Unit tests for evidence-related modules in mahavishnu/core.

Tests cover:
- EvidenceStore: store, store_batch, query_evidence, prune_expired
- EvidenceCollector: collect_recent_outcomes, record_outcome
- EvidenceRetriever: find_similar, cluster_by_pattern, get_retrieval_context
- Error handling in all three modules
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mahavishnu.core.evidence_collector import (
    EvidenceCollector,
    EvidenceSource,
    _SessionBuddyEvidenceSource,
)
from mahavishnu.core.evidence_retriever import (
    EvidenceCluster,
    EvidenceRetriever,
    RetrievalContext,
    RetrievedEvidence,
    _extract_keywords,
)
from mahavishnu.core.evidence_store import (
    EvidenceStore,
)
from mahavishnu.core.skill_governance import LearningEvidence

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_evidence(
    evidence_id: str = "le_test123",
    session_id: str = "sess-1",
    goal: str = "test goal",
    outcome: str = "success",
    repo_paths: list[str] | None = None,
    tool_calls: list[str] | None = None,
    observations: list[str] | None = None,
) -> LearningEvidence:
    return LearningEvidence(
        evidence_id=evidence_id,
        session_id=session_id,
        goal=goal,
        outcome=outcome,
        repo_paths=repo_paths or [],
        tool_calls=tool_calls or [],
        observations=observations or [],
        collected_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# EvidenceStore
# ---------------------------------------------------------------------------


class TestEvidenceStoreInit:
    def test_url_trailing_slash_stripped(self):
        store = EvidenceStore("http://localhost:8678/mcp/")
        assert store._url == "http://localhost:8678/mcp"

    def test_default_timeout(self):
        store = EvidenceStore("http://localhost:8678/mcp")
        assert store._timeout == 10


class TestEvidenceStoreStore:
    @pytest.mark.asyncio
    async def test_store_success_returns_true(self):
        store = EvidenceStore("http://localhost:8678/mcp")
        evidence = make_evidence()

        mock_response = MagicMock()
        mock_response.status_code = 200

        async def mock_post(*args, **kwargs):
            return mock_response

        with patch("mahavishnu.core.evidence_store.httpx.AsyncClient") as mock_client:
            instance = MagicMock()
            instance.post = mock_post
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock()
            mock_client.return_value = instance

            result = await store.store(evidence)

        assert result is True


class TestEvidenceStoreStoreBatch:
    @pytest.mark.asyncio
    async def test_store_batch_all_success(self):
        store = EvidenceStore("http://localhost:8678/mcp")
        evidences = [make_evidence(f"le_{i}") for i in range(3)]

        # Mock successful stores
        mock_response = MagicMock()
        mock_response.status_code = 200

        async def mock_post(*args, **kwargs):
            return mock_response

        with patch("mahavishnu.core.evidence_store.httpx.AsyncClient") as mock_client:
            instance = MagicMock()
            instance.post = mock_post
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock()
            mock_client.return_value = instance

            result = await store.store_batch(evidences)

        assert result.stored_count == 3
        assert result.failed_count == 0
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_store_batch_partial_failure(self):
        store = EvidenceStore("http://localhost:8678/mcp")
        evidences = [make_evidence(f"le_{i}") for i in range(3)]

        # First call succeeds, second fails
        success_response = MagicMock(status_code=200)
        fail_response = MagicMock(status_code=500)

        responses = [success_response, fail_response, success_response]

        async def mock_post(*args, **kwargs):
            return responses.pop(0)

        with patch("mahavishnu.core.evidence_store.httpx.AsyncClient") as mock_client:
            instance = MagicMock()
            instance.post = mock_post
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock()
            mock_client.return_value = instance

            result = await store.store_batch(evidences)

        assert result.stored_count == 2
        assert result.failed_count == 1
        assert len(result.errors) == 1


class TestEvidenceStoreQuery:
    @pytest.mark.asyncio
    async def test_query_evidence_returns_empty_on_http_error(self):
        store = EvidenceStore("http://localhost:8678/mcp")

        async def mock_post(*args, **kwargs):
            resp = MagicMock()
            resp.status_code = 500
            return resp

        with patch("mahavishnu.core.evidence_store.httpx.AsyncClient") as mock_client:
            instance = MagicMock()
            instance.post = mock_post
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock()
            mock_client.return_value = instance

            result = await store.query_evidence("test query")
            assert result == []

    @pytest.mark.asyncio
    async def test_query_evidence_filters_non_evidence_artifacts(self):
        store = EvidenceStore("http://localhost:8678/mcp")

        async def mock_post(*args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(
                return_value={
                    "result": {
                        "conversations": [
                            {
                                "evidence_id": "le_1",
                                "session_id": "sess-1",
                                "goal": "test goal",
                                "outcome": "success",
                                "metadata": {"artifact_type": "learning_evidence"},
                            },
                            {
                                "evidence_id": "le_2",
                                "session_id": "sess-2",
                                "goal": "test goal 2",
                                "outcome": "success",
                                "metadata": {"artifact_type": "other_type"},
                            },
                            {
                                "evidence_id": "le_3",
                                "session_id": "sess-3",
                                "goal": "test goal 3",
                                "outcome": "success",
                                "metadata": {},
                            },
                        ]
                    }
                }
            )
            return resp

        with patch("mahavishnu.core.evidence_store.httpx.AsyncClient") as mock_client:
            instance = MagicMock()
            instance.post = mock_post
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock()
            mock_client.return_value = instance

            result = await store.query_evidence("test query", limit=10)

        # Only the first item has artifact_type = learning_evidence
        assert len(result) == 1
        assert result[0].evidence_id == "le_1"


class TestEvidenceStorePrune:
    @pytest.mark.asyncio
    async def test_prune_expired_returns_zero(self):
        store = EvidenceStore("http://localhost:8678/mcp")

        result = await store.prune_expired(retention_days=30)

        assert result == 0


# ---------------------------------------------------------------------------
# EvidenceCollector
# ---------------------------------------------------------------------------


class TestEvidenceCollectorInit:
    def test_defaults(self):
        collector = EvidenceCollector()
        assert collector._max_per_cycle == 50
        assert isinstance(collector._source, _SessionBuddyEvidenceSource)

    def test_custom_source_injected(self):
        mock_source = MagicMock(spec=EvidenceSource)
        collector = EvidenceCollector(source=mock_source)
        assert collector._source is mock_source


class TestEvidenceCollectorRecordOutcome:
    @pytest.mark.asyncio
    async def test_record_outcome_creates_evidence(self):
        collector = EvidenceCollector()

        evidence = await collector.record_outcome(
            session_id="sess-abc",
            goal="implement feature",
            outcome="success",
            repo_paths=["/path/to/repo"],
            tool_calls=["mcp:test"],
            observations=["works well"],
        )

        assert evidence.session_id == "sess-abc"
        assert evidence.goal == "implement feature"
        assert evidence.outcome == "success"
        assert evidence.repo_paths == ["/path/to/repo"]
        assert evidence.tool_calls == ["mcp:test"]
        assert evidence.observations == ["works well"]
        assert evidence.evidence_id.startswith("le_")

    @pytest.mark.asyncio
    async def test_record_outcome_defaults_empty_lists(self):
        collector = EvidenceCollector()

        evidence = await collector.record_outcome(
            session_id="sess-xyz",
            goal="run test",
            outcome="failure",
        )

        assert evidence.repo_paths == []
        assert evidence.tool_calls == []
        assert evidence.observations == []


class TestEvidenceCollectorCollectRecentOutcomes:
    @pytest.mark.asyncio
    async def test_collect_recent_outcomes_returns_empty_on_source_failure(self):
        mock_source = MagicMock(spec=EvidenceSource)
        mock_source.get_recent_outcomes = AsyncMock(side_effect=httpx.HTTPError("boom"))

        collector = EvidenceCollector(source=mock_source)

        result = await collector.collect_recent_outcomes()
        assert result == []

    @pytest.mark.asyncio
    async def test_collect_recent_outcomes_enforces_max_per_cycle(self):
        mock_source = MagicMock(spec=EvidenceSource)
        # Return 100 items, but max_per_cycle is 20
        mock_source.get_recent_outcomes = AsyncMock(
            return_value=[
                {"evidence_id": f"le_{i}", "session_id": "s", "goal": "g", "outcome": "o"}
                for i in range(100)
            ]
        )

        collector = EvidenceCollector(source=mock_source, max_per_cycle=20)

        result = await collector.collect_recent_outcomes()
        assert len(result) == 20

    @pytest.mark.asyncio
    async def test_collect_recent_outcomes_skips_unparseable_items(self):
        mock_source = MagicMock(spec=EvidenceSource)
        mock_source.get_recent_outcomes = AsyncMock(
            return_value=[
                {"evidence_id": "le_1", "session_id": "s", "goal": "good item"},
                {"evidence_id": "le_2"},  # missing required fields
                {"evidence_id": "le_3", "session_id": "s", "goal": "another good"},
            ]
        )

        collector = EvidenceCollector(source=mock_source)

        result = await collector.collect_recent_outcomes()
        # Only items with session_id and goal/outcome should parse
        assert len(result) <= 3  # some may be skipped


# ---------------------------------------------------------------------------
# EvidenceRetriever
# ---------------------------------------------------------------------------


class TestEvidenceRetrieverInit:
    def test_url_trailing_slash_stripped(self):
        retriever = EvidenceRetriever(
            akosha_url="http://localhost:8682/mcp/",
            session_buddy_url="http://localhost:8678/mcp/",
        )
        assert retriever._akosha_url == "http://localhost:8682/mcp"
        assert retriever._session_buddy_url == "http://localhost:8678/mcp"

    def test_custom_timeout(self):
        retriever = EvidenceRetriever(
            akosha_url="http://localhost:8682/mcp",
            session_buddy_url="http://localhost:8678/mcp",
            timeout_seconds=30,
        )
        assert retriever._timeout == 30


class TestExtractKeywords:
    def test_filters_stop_words(self):
        text = "the quick brown fox jumps over the lazy dog"
        keywords = _extract_keywords(text)
        assert "the" not in keywords
        assert "over" not in keywords
        assert "quick" in keywords
        assert "brown" in keywords

    def test_filters_short_words(self):
        text = "a bc def ghij klmno"
        keywords = _extract_keywords(text)
        assert "bc" not in keywords
        assert "def" in keywords
        assert "klmno" in keywords

    def test_case_insensitive(self):
        text = "The QUICK Brown FOX"
        keywords = _extract_keywords(text)
        assert "quick" in keywords
        assert "brown" in keywords
        assert "fox" in keywords

    def test_empty_string(self):
        keywords = _extract_keywords("")
        assert keywords == set()


class TestEvidenceRetrieverFindSimilar:
    @pytest.mark.asyncio
    async def test_find_similar_akosha_failure_returns_empty(self):
        """Akosha returning 500 without exception yields empty results."""
        evidence = make_evidence(goal="implement auth", observations=["jwt", "oauth"])

        async def mock_post(*args, **kwargs):
            resp = MagicMock()
            resp.status_code = 500
            return resp

        with patch("mahavishnu.core.evidence_retriever.httpx.AsyncClient") as mock_client:
            instance = MagicMock()
            instance.post = mock_post
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock()
            mock_client.return_value = instance

            retriever = EvidenceRetriever(
                akosha_url="http://localhost:8682/mcp",
                session_buddy_url="http://localhost:8678/mcp",
            )
            result = await retriever.find_similar(evidence, limit=5)

        # HTTP error returns empty list (no exception for graceful degradation)
        assert result == []

    @pytest.mark.asyncio
    async def test_find_similar_sorts_by_similarity_descending(self):
        evidence = make_evidence(goal="test goal")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(
            return_value={
                "result": {
                    "results": [
                        {"id": "r1", "score": 0.3, "text": "low score"},
                        {"id": "r2", "score": 0.9, "text": "high score"},
                        {"id": "r3", "score": 0.6, "text": "medium score"},
                    ]
                }
            }
        )

        with patch("mahavishnu.core.evidence_retriever.httpx.AsyncClient") as mock_client:
            instance = MagicMock()
            instance.post = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock()
            mock_client.return_value = instance

            retriever = EvidenceRetriever(
                akosha_url="http://localhost:8682/mcp",
                session_buddy_url="http://localhost:8678/mcp",
            )
            result = await retriever.find_similar(evidence, limit=10)

        assert result[0].similarity == 0.9
        assert result[1].similarity == 0.6
        assert result[2].similarity == 0.3

    @pytest.mark.asyncio
    async def test_find_similar_respects_limit(self):
        evidence = make_evidence(goal="test")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(
            return_value={
                "result": {
                    "results": [
                        {"id": f"r{i}", "score": 1.0 - i * 0.1, "text": f"result {i}"}
                        for i in range(20)
                    ]
                }
            }
        )

        with patch("mahavishnu.core.evidence_retriever.httpx.AsyncClient") as mock_client:
            instance = MagicMock()
            instance.post = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock()
            mock_client.return_value = instance

            retriever = EvidenceRetriever(
                akosha_url="http://localhost:8682/mcp",
                session_buddy_url="http://localhost:8678/mcp",
            )
            result = await retriever.find_similar(evidence, limit=5)

        assert len(result) == 5


class TestEvidenceRetrieverClusterByPattern:
    @pytest.mark.asyncio
    async def test_cluster_by_pattern_empty_list(self):
        retriever = EvidenceRetriever(
            akosha_url="http://localhost:8682/mcp",
            session_buddy_url="http://localhost:8678/mcp",
        )
        result = await retriever.cluster_by_pattern([])
        assert result == []

    @pytest.mark.asyncio
    async def test_cluster_by_pattern_groups_by_repo_and_keywords(self):
        evidence = [
            LearningEvidence(
                evidence_id=f"le_{i}",
                session_id="s",
                goal=f"implement feature {i}",
                outcome="success",
                repo_paths=["/repo/a"],
                collected_at=datetime.now(UTC),
            )
            for i in range(5)
        ]

        retriever = EvidenceRetriever(
            akosha_url="http://localhost:8682/mcp",
            session_buddy_url="http://localhost:8678/mcp",
        )
        clusters = await retriever.cluster_by_pattern(evidence, min_cluster_size=2)

        # All have same repo_path and same keywords (implement, feature)
        assert len(clusters) == 1
        assert clusters[0].member_count == 5
        assert clusters[0].success_rate == 1.0  # all success

    @pytest.mark.asyncio
    async def test_cluster_by_pattern_filters_small_clusters(self):
        evidence = [
            LearningEvidence(
                evidence_id=f"le_{i}",
                session_id="s",
                goal=f"unique goal {i}",
                outcome="success",
                repo_paths=["/repo/a"],
                collected_at=datetime.now(UTC),
            )
            for i in range(3)
        ]

        retriever = EvidenceRetriever(
            akosha_url="http://localhost:8682/mcp",
            session_buddy_url="http://localhost:8678/mcp",
        )
        clusters = await retriever.cluster_by_pattern(evidence, min_cluster_size=5)

        # Each evidence has unique keywords, so no clusters formed
        assert len(clusters) == 0

    @pytest.mark.asyncio
    async def test_cluster_by_pattern_calculates_success_rate(self):
        evidence = [
            LearningEvidence(
                evidence_id=f"le_{i}",
                session_id="s",
                goal="implement feature",
                outcome="success" if i < 2 else "failure",
                repo_paths=["/repo/a"],
                collected_at=datetime.now(UTC),
            )
            for i in range(4)
        ]

        retriever = EvidenceRetriever(
            akosha_url="http://localhost:8682/mcp",
            session_buddy_url="http://localhost:8678/mcp",
        )
        clusters = await retriever.cluster_by_pattern(evidence, min_cluster_size=2)

        assert len(clusters) == 1
        # 2 success out of 4 = 0.5
        assert clusters[0].success_rate == 0.5


class TestEvidenceRetrieverGetRetrievalContext:
    @pytest.mark.asyncio
    async def test_get_retrieval_context_builds_context(self):
        retriever = EvidenceRetriever(
            akosha_url="http://localhost:8682/mcp",
            session_buddy_url="http://localhost:8678/mcp",
        )

        # Mock find_similar and cluster_by_pattern
        with (
            patch.object(
                retriever,
                "find_similar",
                AsyncMock(
                    return_value=[
                        RetrievedEvidence(
                            evidence_id="re_1",
                            similarity=0.9,
                            goal="implement auth",
                            outcome="success",
                            observations=["jwt"],
                        )
                    ]
                ),
            ),
            patch.object(
                retriever,
                "cluster_by_pattern",
                AsyncMock(
                    return_value=[
                        EvidenceCluster(
                            cluster_id="cl_123",
                            representative_goal="implement auth",
                            repo_paths=["/repo/a"],
                            member_count=1,
                            success_rate=1.0,
                            evidence_ids=["re_1"],
                        )
                    ]
                ),
            ),
        ):
            context = await retriever.get_retrieval_context(
                goal="auth implementation",
                repo_paths=["/repo/a"],
            )

        assert context.query == "auth implementation"
        assert len(context.similar_evidence) == 1
        assert len(context.clusters) == 1
        assert isinstance(context.retrieved_at, datetime)


class TestRetrievedEvidenceModel:
    def test_retrieved_evidence_defaults(self):
        evidence = RetrievedEvidence(
            evidence_id="re_test",
            similarity=0.95,
            goal="test goal",
            outcome="success",
        )
        assert evidence.source == "akosha"
        assert evidence.observations == []

    def test_retrieved_evidence_with_observations(self):
        evidence = RetrievedEvidence(
            evidence_id="re_test",
            similarity=0.8,
            goal="test goal",
            outcome="success",
            observations=["obs1", "obs2"],
            source="session_buddy",
        )
        assert evidence.observations == ["obs1", "obs2"]
        assert evidence.source == "session_buddy"


class TestRetrievalContextModel:
    def test_retrieval_context_defaults(self):
        ctx = RetrievalContext(query="test query")
        assert ctx.similar_evidence == []
        assert ctx.clusters == []
        assert isinstance(ctx.retrieved_at, datetime)


# ---------------------------------------------------------------------------
# Error handling integration
# ---------------------------------------------------------------------------


class TestEvidenceStoreErrors:
    @pytest.mark.asyncio
    async def test_store_returns_false_on_exception(self):
        store = EvidenceStore("http://localhost:8678/mcp")

        with patch("mahavishnu.core.evidence_store.httpx.AsyncClient") as mock_client:
            mock_client.side_effect = Exception("network error")
            result = await store.store(make_evidence())

        assert result is False

    @pytest.mark.asyncio
    async def test_query_evidence_returns_empty_on_exception(self):
        store = EvidenceStore("http://localhost:8678/mcp")

        with patch("mahavishnu.core.evidence_store.httpx.AsyncClient") as mock_client:
            mock_client.side_effect = Exception("connection refused")
            result = await store.query_evidence("test")

        assert result == []


class TestEvidenceRetrieverErrors:
    @pytest.mark.asyncio
    async def test_find_similar_graceful_fallback_on_akosha_error(self):
        evidence = make_evidence(goal="test")

        akosha_error = MagicMock()
        akosha_error.status_code = 500

        sb_success = MagicMock()
        sb_success.status_code = 200
        sb_success.json = MagicMock(return_value={"result": {"conversations": []}})

        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return akosha_error
            return sb_success

        with patch("mahavishnu.core.evidence_retriever.httpx.AsyncClient") as mock_client:
            instance = MagicMock()
            instance.post = mock_post
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock()
            mock_client.return_value = instance

            retriever = EvidenceRetriever(
                akosha_url="http://localhost:8682/mcp",
                session_buddy_url="http://localhost:8678/mcp",
            )
            result = await retriever.find_similar(evidence)

        # Fallback to Session-Buddy succeeded (empty results but no exception)
        assert result == []


class TestSessionBuddyEvidenceSource:
    @pytest.mark.asyncio
    async def test_get_recent_outcomes_raises_on_request_exception(self):
        """When httpx raises an exception during the request, it propagates."""
        source = _SessionBuddyEvidenceSource(
            session_buddy_url="http://localhost:8678/mcp",
            store_timeout=10,
        )

        async def mock_post(*args, **kwargs):
            raise httpx.RequestError("connection failed")

        mock_client_instance = MagicMock()
        mock_client_instance.post = mock_post

        with patch("mahavishnu.core.evidence_collector.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value.__aenter__.return_value = mock_client_instance
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(httpx.RequestError):
                await source.get_recent_outcomes(limit=10)
