"""Tests for the Phase 1B learning pipeline (observe->store->retrieve->synthesize->review)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from mahavishnu.core.config import LearningConfig
from mahavishnu.core.evidence_collector import EvidenceCollector, EvidenceSource
from mahavishnu.core.evidence_retriever import (
    EvidenceCluster,
    EvidenceRetriever,
    RetrievedEvidence,
    RetrievalContext,
)
from mahavishnu.core.evidence_store import EvidenceStore, StoreBatchResult
from mahavishnu.core.learning_pipeline import LearningPipelineService, PipelineCycleResult
from mahavishnu.core.review_gate import ReviewGate, ReviewGateResult
from mahavishnu.core.skill_governance import (
    LearningEvidence,
    SkillDraft,
    SkillPromotionState,
)
from mahavishnu.core.skill_registry import SkillRegistry
from mahavishnu.core.skill_security import sanitize_skill_body
from mahavishnu.core.skill_synthesizer import SkillSynthesizer


DANGEROUS_CALL = "__import__('os').system('rm -rf /')"


class TestEvidenceCollector:
    def test_record_outcome_creates_evidence(self):
        collector = EvidenceCollector(session_buddy_url="http://localhost:8678/mcp")
        evidence = asyncio.get_event_loop().run_until_complete(
            collector.record_outcome(
                session_id="sess-1",
                goal="Fix authentication bug",
                outcome="success",
                repo_paths=["/repo/auth"],
                tool_calls=["search_code", "write_file"],
            )
        )
        assert evidence.session_id == "sess-1"
        assert evidence.goal == "Fix authentication bug"
        assert evidence.outcome == "success"
        assert evidence.evidence_id.startswith("le_")
        assert len(evidence.tool_calls) == 2

    @pytest.mark.asyncio
    async def test_collect_recent_outcomes_empty_source(self):
        source = AsyncMock()
        source.get_recent_outcomes.return_value = []
        collector = EvidenceCollector(source=source)
        results = await collector.collect_recent_outcomes()
        assert results == []
        source.get_recent_outcomes.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_collect_recent_outcomes_respects_max(self):
        items = [{"goal": f"task {i}", "outcome": "success"} for i in range(100)]
        source = AsyncMock()
        source.get_recent_outcomes.return_value = items
        collector = EvidenceCollector(source=source, max_per_cycle=10)
        results = await collector.collect_recent_outcomes()
        assert len(results) == 10

    @pytest.mark.asyncio
    async def test_collect_recent_outcomes_graceful_degradation(self):
        source = AsyncMock()
        source.get_recent_outcomes.side_effect = ConnectionError("Session-Buddy down")
        collector = EvidenceCollector(source=source)
        results = await collector.collect_recent_outcomes()
        assert results == []

    @pytest.mark.asyncio
    async def test_collect_parses_valid_items(self):
        items = [
            {
                "evidence_id": "le_abc",
                "session_id": "sess-1",
                "goal": "Test the API",
                "outcome": "success",
                "repo_paths": ["/repo/api"],
                "tool_calls": ["pytest"],
                "observations": ["All tests passed"],
                "collected_at": datetime.now(UTC).isoformat(),
            }
        ]
        source = AsyncMock()
        source.get_recent_outcomes.return_value = items
        collector = EvidenceCollector(source=source)
        results = await collector.collect_recent_outcomes()
        assert len(results) == 1
        assert results[0].evidence_id == "le_abc"
        assert results[0].outcome == "success"


class TestEvidenceStore:
    @pytest.mark.asyncio
    async def test_store_batch_with_empty_list(self):
        store = EvidenceStore(session_buddy_url="http://localhost:8678/mcp")
        result = await store.store_batch([])
        assert result.stored_count == 0
        assert result.failed_count == 0

    @pytest.mark.asyncio
    async def test_store_batch_counts_success_and_failure(self):
        store = EvidenceStore(session_buddy_url="http://localhost:8678/mcp")
        evidence = LearningEvidence(
            evidence_id="le_test",
            session_id="sess-1",
            goal="test goal",
            outcome="success",
            collected_at=datetime.now(UTC),
        )
        with patch.object(store, "store", new_callable=AsyncMock) as mock_store:
            mock_store.side_effect = [True, False, True, True, Exception("boom")]
            evidences = [evidence] * 5
            result = await store.store_batch(evidences)
            assert result.stored_count == 3
            assert result.failed_count == 2
            assert len(result.errors) == 2

    def test_prune_expired_is_noop(self):
        store = EvidenceStore(session_buddy_url="http://localhost:8678/mcp")
        count = asyncio.get_event_loop().run_until_complete(store.prune_expired(30))
        assert count == 0


class TestEvidenceRetriever:
    def test_cluster_by_pattern_empty_list(self):
        retriever = EvidenceRetriever(
            akosha_url="http://localhost:8682/mcp",
            session_buddy_url="http://localhost:8678/mcp",
        )
        result = asyncio.get_event_loop().run_until_complete(
            retriever.cluster_by_pattern([])
        )
        assert result == []

    def test_cluster_by_pattern_groups_by_repo(self):
        retriever = EvidenceRetriever(
            akosha_url="http://localhost:8682/mcp",
            session_buddy_url="http://localhost:8678/mcp",
        )
        evidences = [
            LearningEvidence(
                evidence_id=f"le_{i}",
                session_id="s1",
                goal="fix authentication bug in users service",
                outcome="success",
                repo_paths=["/repo/auth/users"],
                collected_at=datetime.now(UTC),
            )
            for i in range(3)
        ]
        result = asyncio.get_event_loop().run_until_complete(
            retriever.cluster_by_pattern(evidences, min_cluster_size=2)
        )
        assert len(result) >= 1
        assert result[0].member_count == 3

    def test_cluster_by_pattern_below_threshold(self):
        retriever = EvidenceRetriever(
            akosha_url="http://localhost:8682/mcp",
            session_buddy_url="http://localhost:8678/mcp",
        )
        evidences = [
            LearningEvidence(
                evidence_id=f"le_{i}",
                session_id="s1",
                goal=f"unique task {i}",
                outcome="success",
                repo_paths=[f"/repo/{i}"],
                collected_at=datetime.now(UTC),
            )
            for i in range(3)
        ]
        result = asyncio.get_event_loop().run_until_complete(
            retriever.cluster_by_pattern(evidences, min_cluster_size=3)
        )
        assert len(result) == 0


class TestSkillSynthesizer:
    @pytest.mark.asyncio
    async def test_synthesize_below_threshold_returns_none(self):
        synthesizer = SkillSynthesizer(min_evidence=5)
        cluster = EvidenceCluster(
            cluster_id="cl_test",
            representative_goal="fix auth bug",
            repo_paths=["/repo/auth"],
            member_count=2,
            success_rate=1.0,
            evidence_ids=["le_1", "le_2"],
        )
        result = await synthesizer.synthesize_from_cluster(cluster, [])
        assert result is None

    @pytest.mark.asyncio
    async def test_synthesize_creates_draft(self):
        synthesizer = SkillSynthesizer(min_evidence=3, max_drafts_per_cycle=5)
        cluster = EvidenceCluster(
            cluster_id="cl_test",
            representative_goal="fix python authentication tests",
            repo_paths=["/repo/auth"],
            member_count=5,
            success_rate=0.8,
            evidence_ids=["le_1", "le_2", "le_3", "le_4", "le_5"],
        )
        result = await synthesizer.synthesize_from_cluster(cluster, [])
        assert result is not None
        assert result.name.startswith("learned-")
        assert result.state == SkillPromotionState.DRAFT
        assert result.proposed_by == "learning_pipeline"
        assert len(result.trigger_conditions) >= 1
        assert result.source_evidence_ids == ["le_1", "le_2", "le_3", "le_4", "le_5"]

    @pytest.mark.asyncio
    async def test_synthesize_sanitizes_body(self):
        synthesizer = SkillSynthesizer(min_evidence=3)
        cluster = EvidenceCluster(
            cluster_id="cl_test",
            representative_goal="fix python code with dangerous patterns",
            repo_paths=["/repo/code"],
            member_count=5,
            success_rate=1.0,
            evidence_ids=[f"le_{i}" for i in range(5)],
        )
        result = await synthesizer.synthesize_from_cluster(cluster, [])
        assert result is not None
        assert "REDACTED" in result.body or DANGEROUS_CALL not in result.body

    @pytest.mark.asyncio
    async def test_synthesize_batch_respects_max(self):
        synthesizer = SkillSynthesizer(min_evidence=1, max_drafts_per_cycle=2)
        clusters = [
            EvidenceCluster(
                cluster_id=f"cl_{i}",
                representative_goal=f"pattern {i}",
                repo_paths=[f"/repo/{i}"],
                member_count=5,
                success_rate=1.0,
                evidence_ids=[f"le_{i}_1", f"le_{i}_2", f"le_{i}_3"],
            )
            for i in range(5)
        ]
        drafts = await synthesizer.synthesize_batch(clusters, [])
        assert len(drafts) == 2


class TestReviewGateIntegration:
    def test_gate_passes_valid_draft(self):
        gate = ReviewGate()
        draft = SkillDraft(
            skill_id=f"skill_{uuid4().hex}",
            name="learned-fix-auth-bug",
            version="0.1.0",
            description="Fixes authentication bugs across sessions",
            trigger_conditions=["Python task", "Goal mentions 'authentication'"],
            body="# Fix auth bug\n\n## Pattern\nFix auth issues.\n\n## Actions\nCheck token validity.",
            proposed_by="learning_pipeline",
        )
        result = gate.validate_for_promotion(draft)
        assert result.passed is True

    def test_gate_rejects_empty_body(self):
        gate = ReviewGate()
        draft = SkillDraft(
            skill_id=f"skill_{uuid4().hex}",
            name="learned-empty",
            version="0.1.0",
            description="Empty skill",
            trigger_conditions=["test"],
            body="   ",
            proposed_by="learning_pipeline",
        )
        result = gate.validate_for_promotion(draft)
        assert result.passed is False

    def test_gate_rejects_short_name(self):
        gate = ReviewGate()
        draft = SkillDraft(
            skill_id=f"skill_{uuid4().hex}",
            name="short",
            version="0.1.0",
            description="Short name skill",
            trigger_conditions=["test"],
            body="# Valid body content here that exceeds 10 characters",
            proposed_by="learning_pipeline",
        )
        result = gate.validate_for_promotion(draft)
        assert result.passed is False


class TestLearningPipelineService:
    def test_service_creation(self):
        config = LearningConfig(enabled=True)
        svc = LearningPipelineService(config=config)
        assert svc.is_running is False
        assert svc.cycle_count == 0
        assert svc.total_drafts == 0
        assert svc.last_result is None

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self):
        config = LearningConfig(enabled=True, collection_interval_seconds=300)
        svc = LearningPipelineService(config=config)
        await svc.start()
        assert svc.is_running is True
        await svc.stop()
        assert svc.is_running is False

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        config = LearningConfig(enabled=True)
        svc = LearningPipelineService(config=config)
        await svc.start()
        await svc.start()
        await svc.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        config = LearningConfig(enabled=True)
        svc = LearningPipelineService(config=config)
        await svc.stop()

    @pytest.mark.asyncio
    async def test_run_once_with_no_evidence(self):
        config = LearningConfig(enabled=True)
        svc = LearningPipelineService(config=config)
        svc._collector.collect_recent_outcomes = AsyncMock(return_value=[])
        result = await svc.run_once()
        assert result.evidence_collected == 0
        assert result.cycle_completed_at is not None

    @pytest.mark.asyncio
    async def test_run_once_full_cycle(self):
        config = LearningConfig(enabled=True, synthesis_min_evidence=2, max_drafts_per_cycle=5)
        svc = LearningPipelineService(config=config)

        svc._collector.collect_recent_outcomes = AsyncMock(
            return_value=[
                LearningEvidence(
                    evidence_id=f"le_{idx}",
                    session_id="sess-1",
                    goal="fix authentication bug in users service",
                    outcome="success",
                    repo_paths=["/repo/auth/users"],
                    collected_at=datetime.now(UTC),
                )
                for idx in range(3)
            ]
        )
        svc._store.store_batch = AsyncMock(return_value=StoreBatchResult(stored_count=3))
        svc._retriever.get_retrieval_context = AsyncMock(
            return_value=RetrievalContext(
                similar_evidence=[],
                clusters=[
                    EvidenceCluster(
                        cluster_id="cl_1",
                        representative_goal="fix auth bug",
                        repo_paths=["/repo/auth"],
                        member_count=5,
                        success_rate=1.0,
                        evidence_ids=[f"le_{i}" for i in range(5)],
                    )
                ],
                query="fix auth",
            )
        )
        svc._synthesizer.synthesize_batch = AsyncMock(return_value=[])

        result = await svc.run_once()
        assert result.evidence_collected == 3
        assert result.evidence_stored == 3
        assert result.clusters_found == 1
        assert result.cycle_completed_at is not None

    @pytest.mark.asyncio
    async def test_run_once_with_drafts_and_review(self):
        config = LearningConfig(enabled=True, synthesis_min_evidence=2)
        svc = LearningPipelineService(config=config)

        draft = SkillDraft(
            skill_id=f"skill_{uuid4().hex}",
            name="learned-fix-auth-bug-pattern",
            version="0.1.0",
            description="Fixes authentication bugs across sessions consistently",
            trigger_conditions=["Python task"],
            body="# Fix auth bug\n\n## Pattern\nConsistent auth fix pattern.\n\n## Actions\nCheck tokens.",
            proposed_by="learning_pipeline",
        )

        svc._collector.collect_recent_outcomes = AsyncMock(
            return_value=[
                LearningEvidence(
                    evidence_id="le_1",
                    session_id="s1",
                    goal="fix auth bug",
                    outcome="success",
                    repo_paths=["/repo/auth"],
                    collected_at=datetime.now(UTC),
                )
            ]
        )
        svc._store.store_batch = AsyncMock(return_value=StoreBatchResult(stored_count=1))
        svc._retriever.get_retrieval_context = AsyncMock(
            return_value=RetrievalContext(
                similar_evidence=[],
                clusters=[
                    EvidenceCluster(
                        cluster_id="cl_1",
                        representative_goal="fix auth bug",
                        repo_paths=["/repo/auth"],
                        member_count=5,
                        success_rate=1.0,
                        evidence_ids=[],
                    )
                ],
                query="fix auth",
            )
        )
        svc._synthesizer.synthesize_batch = AsyncMock(return_value=[draft])

        result = await svc.run_once()
        assert result.drafts_synthesized == 1
        assert result.drafts_passed_review == 1

    @pytest.mark.asyncio
    async def test_run_once_graceful_degradation_on_collect_failure(self):
        config = LearningConfig(enabled=True)
        svc = LearningPipelineService(config=config)
        svc._collector.collect_recent_outcomes = AsyncMock(
            side_effect=RuntimeError("DB down")
        )
        result = await svc.run_once()
        assert result.evidence_collected == 0
        assert result.cycle_completed_at is not None

    @pytest.mark.asyncio
    async def test_run_once_graceful_degradation_on_retrieve_failure(self):
        config = LearningConfig(enabled=True)
        svc = LearningPipelineService(config=config)

        svc._collector.collect_recent_outcomes = AsyncMock(
            return_value=[
                LearningEvidence(
                    evidence_id="le_1",
                    session_id="s1",
                    goal="test",
                    outcome="success",
                    collected_at=datetime.now(UTC),
                )
            ]
        )
        svc._store.store_batch = AsyncMock(return_value=StoreBatchResult(stored_count=1))
        svc._retriever.get_retrieval_context = AsyncMock(
            side_effect=RuntimeError("Akosha down")
        )

        result = await svc.run_once()
        assert result.evidence_stored == 1
        assert result.clusters_found == 0

    def test_duration_ms_when_not_completed(self):
        result = PipelineCycleResult()
        assert result.duration_ms == 0.0


class TestLearningConfig:
    def test_defaults(self):
        config = LearningConfig()
        assert config.enabled is False
        assert config.collection_interval_seconds == 300
        assert config.max_evidence_per_cycle == 50
        assert config.synthesis_min_evidence == 5
        assert config.retention_days == 90
        assert config.max_drafts_per_cycle == 3

    def test_custom_values(self):
        config = LearningConfig(
            enabled=True,
            collection_interval_seconds=60,
            max_evidence_per_cycle=100,
        )
        assert config.enabled is True
        assert config.collection_interval_seconds == 60
        assert config.max_evidence_per_cycle == 100

    def test_extra_forbid(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            LearningConfig(nonexistent_field=True)

    def test_bounds_enforced(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            LearningConfig(collection_interval_seconds=10)
        with pytest.raises(ValidationError):
            LearningConfig(retention_days=500)


class TestSkillSecurity:
    def test_sanitize_removes_dangerous_patterns(self):
        body = "def run():\n    exec(user_input)\n    eval(data)"
        result = sanitize_skill_body(body)
        assert "exec(user_input)" not in result
        assert "eval(data)" not in result
        assert "REDACTED" in result

    def test_sanitize_truncates_long_body(self):
        long_text = "x" * 200_000
        result = sanitize_skill_body(long_text)
        assert len(result) <= 100_000

    def test_sanitize_preserves_safe_content(self):
        body = "# Valid skill\n\n## Trigger\nWhen auth fails.\n\n## Actions\nCheck tokens."
        result = sanitize_skill_body(body)
        assert "## Trigger" in result
        assert "Check tokens" in result


class TestEvidenceSourceProtocol:
    def test_custom_source_satisfies_protocol(self):
        class CustomSource:
            async def get_recent_outcomes(self, limit: int) -> list[dict[str, Any]]:
                return []

        assert isinstance(CustomSource(), EvidenceSource)

    def test_collector_accepts_custom_source(self):
        source = AsyncMock(spec=EvidenceSource)
        collector = EvidenceCollector(source=source, max_per_cycle=5)
        assert collector._source is source
