"""Unit tests for mahavishnu/core/evidence_retriever.py.

The EvidenceRetriever uses httpx.AsyncClient for HTTP calls to Akosha
and Session-Buddy; these are mocked so no network calls happen.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.evidence_retriever import (
    EvidenceCluster,
    EvidenceRetriever,
    RetrievalContext,
    RetrievedEvidence,
    _extract_keywords,
)
from mahavishnu.core.skill_governance import LearningEvidence

pytestmark = pytest.mark.unit


# ============================== Fixtures ==============================


@pytest.fixture
def retriever() -> EvidenceRetriever:
    """Default retriever instance with localhost URLs."""
    return EvidenceRetriever(
        akosha_url="http://akosha.local",
        session_buddy_url="http://sb.local",
        timeout_seconds=5,
    )


@pytest.fixture
def sample_evidence() -> LearningEvidence:
    """A sample LearningEvidence used as the query base."""
    return LearningEvidence(
        evidence_id="le_sample",
        session_id="sess1",
        goal="Add pgvector index for HNSW",
        outcome="success",
        repo_paths=["/repo/a"],
        observations=["used CREATE INDEX", "verified plan"],
    )


@pytest.fixture
def akosha_success_response() -> MagicMock:
    """A 200 OK Akosha response with two items."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(
        return_value={
            "result": {
                "results": [
                    {
                        "id": "ev-1",
                        "score": 0.91,
                        "text": "Add HNSW index",
                        "outcome": "success",
                        "observations": ["x", "y"],
                    },
                    {
                        "id": "ev-2",
                        "score": 0.55,
                        "text": "Tune ef_search",
                        "outcome": "partial_success",
                        "observations": [],
                    },
                ]
            }
        }
    )
    return resp


# ============================== Pydantic models ==============================


class TestRetrievedEvidence:
    """RetrievedEvidence model."""

    def test_required_fields(self):
        ev = RetrievedEvidence(
            evidence_id="x",
            similarity=0.5,
            goal="goal",
            outcome="success",
        )
        assert ev.source == "akosha"
        assert ev.observations == []

    def test_custom_source(self):
        ev = RetrievedEvidence(
            evidence_id="x",
            similarity=0.5,
            goal="g",
            outcome="o",
            source="session_buddy",
        )
        assert ev.source == "session_buddy"


class TestEvidenceCluster:
    """EvidenceCluster model."""

    def test_construction(self):
        c = EvidenceCluster(
            cluster_id="cl_1",
            representative_goal="goal",
            repo_paths=["/r"],
            member_count=3,
            success_rate=0.66,
            evidence_ids=["a", "b", "c"],
        )
        assert c.cluster_id == "cl_1"
        assert c.member_count == 3


class TestRetrievalContext:
    """RetrievalContext model."""

    def test_default_retrieved_at(self):
        ctx = RetrievalContext(query="hello")
        assert ctx.similar_evidence == []
        assert ctx.clusters == []
        assert isinstance(ctx.retrieved_at, datetime)
        assert ctx.query == "hello"


# ============================== Keyword extraction ==============================


class TestExtractKeywords:
    """The private _extract_keywords helper."""

    def test_filters_stopwords(self):
        out = _extract_keywords("the quick brown fox")
        # `the` is a stopword, the rest are kept
        assert "the" not in out
        assert {"quick", "brown", "fox"}.issubset(out)

    def test_filters_short_words(self):
        out = _extract_keywords("a an it")
        # Words <= 2 chars are excluded
        assert out == set()

    def test_lowercases(self):
        out = _extract_keywords("HELLO World")
        assert "hello" in out
        assert "world" in out

    def test_empty_string(self):
        assert _extract_keywords("") == set()


# ============================== Retriever init / URL handling ==============================


class TestRetrieverInit:
    """URL normalization on init."""

    def test_strips_trailing_slash(self):
        r = EvidenceRetriever(
            akosha_url="http://akosha.local/",
            session_buddy_url="http://sb.local/",
        )
        assert r._akosha_url == "http://akosha.local"
        assert r._session_buddy_url == "http://sb.local"

    def test_timeout_default(self):
        r = EvidenceRetriever("http://a", "http://b")
        assert r._timeout == 15

    def test_custom_timeout(self):
        r = EvidenceRetriever("http://a", "http://b", timeout_seconds=30)
        assert r._timeout == 30


# ============================== find_similar ==============================


class TestFindSimilar:
    """Tests for find_similar via Akosha and fallback."""

    async def test_akosha_success(
        self,
        retriever: EvidenceRetriever,
        sample_evidence: LearningEvidence,
        akosha_success_response: MagicMock,
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=akosha_success_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await retriever.find_similar(sample_evidence, limit=10)

        assert len(results) == 2
        # Sorted by similarity descending
        assert results[0].similarity >= results[1].similarity
        assert results[0].source == "akosha"

    async def test_akosha_failure_falls_back_to_session_buddy(
        self, retriever: EvidenceRetriever, sample_evidence: LearningEvidence
    ):
        # When _search_akosha raises, _search_session_buddy is called
        with (
            patch.object(retriever, "_search_akosha", side_effect=RuntimeError("offline")),
            patch.object(
                retriever,
                "_search_session_buddy",
                AsyncMock(
                    return_value=[
                        RetrievedEvidence(
                            evidence_id="sb-1",
                            similarity=0.7,
                            goal="from sb",
                            outcome="success",
                            source="session_buddy",
                        )
                    ]
                ),
            ) as mock_sb,
        ):
            results = await retriever.find_similar(sample_evidence)

        assert mock_sb.await_count == 1
        assert results[0].source == "session_buddy"

    async def test_limit_truncates_results(
        self,
        retriever: EvidenceRetriever,
        sample_evidence: LearningEvidence,
        akosha_success_response: MagicMock,
    ):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=akosha_success_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await retriever.find_similar(sample_evidence, limit=1)

        assert len(results) == 1


# ============================== _search_akosha ==============================


class TestSearchAkosha:
    """Direct unit tests for the private _search_akosha helper."""

    async def test_http_error_returns_empty(self, retriever: EvidenceRetriever):
        resp = MagicMock()
        resp.status_code = 500
        resp.json = MagicMock(return_value={})
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await retriever._search_akosha("query", 5)
        assert results == []

    async def test_handles_content_key_fallback(self, retriever: EvidenceRetriever):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(
            return_value={
                "result": {
                    "content": [{"id": "c1", "score": 0.3, "text": "foo", "outcome": "success"}]
                }
            }
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await retriever._search_akosha("q", 5)
        assert len(results) == 1
        assert results[0].evidence_id == "c1"

    async def test_handles_metadata_observations(self, retriever: EvidenceRetriever):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(
            return_value={
                "result": {
                    "results": [
                        {
                            "id": "x",
                            "score": 0.5,
                            "goal": "g",
                            "metadata": {
                                "outcome": "failure",
                                "observations": ["a", "b"],
                            },
                        }
                    ]
                }
            }
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await retriever._search_akosha("q", 5)
        assert results[0].outcome == "failure"
        assert results[0].observations == ["a", "b"]


# ============================== _search_session_buddy ==============================


class TestSearchSessionBuddy:
    """Direct unit tests for _search_session_buddy."""

    async def test_returns_only_learning_evidence(self, retriever: EvidenceRetriever):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(
            return_value={
                "result": {
                    "conversations": [
                        {
                            "id": "sb1",
                            "summary": "real evidence",
                            "score": 0.8,
                            "metadata": {
                                "artifact_type": "learning_evidence",
                                "outcome": "success",
                                "observations": ["o1"],
                            },
                        },
                        {
                            "id": "sb2",
                            "summary": "not evidence",
                            "metadata": {"artifact_type": "chat"},
                        },
                    ]
                }
            }
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await retriever._search_session_buddy("q", 10)

        assert len(results) == 1
        assert results[0].evidence_id == "sb1"
        assert results[0].source == "session_buddy"

    async def test_http_error_returns_empty(self, retriever: EvidenceRetriever):
        resp = MagicMock()
        resp.status_code = 500
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = await retriever._search_session_buddy("q", 10)
        assert results == []

    async def test_exception_returns_empty(self, retriever: EvidenceRetriever):
        with patch("httpx.AsyncClient", side_effect=RuntimeError("boom")):
            results = await retriever._search_session_buddy("q", 10)
        assert results == []


# ============================== cluster_by_pattern ==============================


class TestClusterByPattern:
    """Tests for cluster_by_pattern."""

    async def test_empty_returns_empty(self, retriever: EvidenceRetriever):
        out = await retriever.cluster_by_pattern([])
        assert out == []

    async def test_single_member_excluded(self, retriever: EvidenceRetriever):
        ev = LearningEvidence(
            session_id="s", goal="solo goal", outcome="success", repo_paths=["/r1"]
        )
        out = await retriever.cluster_by_pattern([ev])
        # min_cluster_size=2 by default → solo not clustered
        assert out == []

    async def test_clusters_by_repo_and_keywords(self, retriever: EvidenceRetriever):
        e1 = LearningEvidence(
            session_id="s",
            goal="install pgvector index hnsw",
            outcome="success",
            repo_paths=["/r1"],
        )
        e2 = LearningEvidence(
            session_id="s",
            goal="install pgvector index hnsw",
            outcome="failure",
            repo_paths=["/r1"],
        )
        out = await retriever.cluster_by_pattern([e1, e2], min_cluster_size=2)
        assert len(out) == 1
        assert out[0].member_count == 2
        # 1 of 2 has 'success' → 0.5 success rate
        assert out[0].success_rate == 0.5
        # cluster_id is deterministic by repo + keyword hash
        assert out[0].cluster_id.startswith("cl_")

    async def test_unclassified_when_no_repo_paths(self, retriever: EvidenceRetriever):
        e1 = LearningEvidence(session_id="s", goal="alpha beta", outcome="success", repo_paths=[])
        e2 = LearningEvidence(session_id="s", goal="alpha beta", outcome="success", repo_paths=[])
        out = await retriever.cluster_by_pattern([e1, e2], min_cluster_size=2)
        assert len(out) == 1


# ============================== get_retrieval_context ==============================


class TestGetRetrievalContext:
    """End-to-end shape test for get_retrieval_context."""

    async def test_context_returns_results(self, retriever: EvidenceRetriever):
        fake_similar = [
            RetrievedEvidence(
                evidence_id=f"ev-{i}",
                similarity=0.9 - i * 0.05,
                goal="install pgvector index hnsw",
                outcome="success",
                observations=[],
            )
            for i in range(3)
        ]
        with patch.object(retriever, "find_similar", AsyncMock(return_value=fake_similar)):
            ctx = await retriever.get_retrieval_context("install pgvector index hnsw", ["/r"])
        assert isinstance(ctx, RetrievalContext)
        assert ctx.query == "install pgvector index hnsw"
        assert len(ctx.similar_evidence) == 3

    async def test_context_with_empty_similar(self, retriever: EvidenceRetriever):
        with patch.object(retriever, "find_similar", AsyncMock(return_value=[])):
            ctx = await retriever.get_retrieval_context("goal", [])
        assert ctx.similar_evidence == []
        assert ctx.clusters == []
