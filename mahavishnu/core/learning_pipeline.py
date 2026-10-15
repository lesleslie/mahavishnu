"""Learning pipeline orchestrator for the Bodai ecosystem.

Wires the observe→store→retrieve→synthesize stages into a periodic
asyncio loop, following the MemoryAggregator pattern.  Does NOT auto-
activate skills — all drafts remain in DRAFT state awaiting human review.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mahavishnu.core.evidence_collector import EvidenceCollector
from mahavishnu.core.evidence_retriever import EvidenceRetriever
from mahavishnu.core.evidence_store import EvidenceStore
from mahavishnu.core.review_gate import ReviewGate
from mahavishnu.core.skill_synthesizer import SkillSynthesizer

if TYPE_CHECKING:
    from mahavishnu.core.config import LearningConfig

logger = logging.getLogger(__name__)


class PipelineCycleResult(BaseModel):
    """Summary of a single pipeline collection cycle."""

    cycle_started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    cycle_completed_at: datetime | None = None
    evidence_collected: int = 0
    evidence_stored: int = 0
    store_failures: int = 0
    clusters_found: int = 0
    drafts_synthesized: int = 0
    drafts_passed_review: int = 0
    errors: list[str] = Field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        if not self.cycle_completed_at:
            return 0.0
        return (self.cycle_completed_at - self.cycle_started_at).total_seconds() * 1000


class LearningPipelineService:
    """Periodic learning pipeline: observe→store→retrieve→synthesize→review.

    Follows the MemoryAggregator pattern:
    - ``start()`` launches an asyncio task that runs collection cycles
    - ``stop()`` signals graceful shutdown via an asyncio.Event
    - All external calls are wrapped in try/except for graceful degradation
    - Never auto-activates skills (review-gated by design)
    """

    def __init__(
        self,
        config: LearningConfig,
        session_buddy_url: str = "http://localhost:8678/mcp",
        akosha_url: str = "http://localhost:8682/mcp",
    ) -> None:
        self._config = config
        self._collector = EvidenceCollector(
            session_buddy_url=session_buddy_url,
            max_per_cycle=config.max_evidence_per_cycle,
            store_timeout=config.store_timeout_seconds,
        )
        self._store = EvidenceStore(
            session_buddy_url=session_buddy_url,
            timeout_seconds=config.store_timeout_seconds,
        )
        self._retriever = EvidenceRetriever(
            akosha_url=akosha_url,
            session_buddy_url=session_buddy_url,
            timeout_seconds=config.retrieve_timeout_seconds,
        )
        self._synthesizer = SkillSynthesizer(
            min_evidence=config.synthesis_min_evidence,
            max_drafts_per_cycle=config.max_drafts_per_cycle,
        )
        self._review_gate = ReviewGate()

        self._task: asyncio.Task[Any] | None = None
        self._shutdown = asyncio.Event()
        self._cycle_count = 0
        self._total_drafts = 0
        self._last_result: PipelineCycleResult | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    @property
    def total_drafts(self) -> int:
        return self._total_drafts

    @property
    def last_result(self) -> PipelineCycleResult | None:
        return self._last_result

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            logger.warning("learning_pipeline_already_running")
            return
        self._shutdown.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "learning_pipeline_started: interval=%ds, max_evidence=%d, min_synthesis=%d",
            self._config.collection_interval_seconds,
            self._config.max_evidence_per_cycle,
            self._config.synthesis_min_evidence,
        )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._shutdown.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        logger.info(
            "learning_pipeline_stopped: cycles=%d, total_drafts=%d",
            self._cycle_count,
            self._total_drafts,
        )

    async def run_once(self) -> PipelineCycleResult:
        """Execute a single pipeline cycle (useful for testing and manual trigger)."""
        return await self._run_cycle()

    async def _run_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                result = await self._run_cycle()
                self._last_result = result
                self._cycle_count += 1
                logger.info(
                    "learning_pipeline_cycle_%d: collected=%d stored=%d drafts=%d review_passed=%d duration=%.0fms",
                    self._cycle_count,
                    result.evidence_collected,
                    result.evidence_stored,
                    result.drafts_synthesized,
                    result.drafts_passed_review,
                    result.duration_ms,
                )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("learning_pipeline_cycle_error")

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self._config.collection_interval_seconds,
                )

    async def _run_cycle(self) -> PipelineCycleResult:
        result = PipelineCycleResult()

        # Stage 1: Observe
        try:
            evidence = await self._collector.collect_recent_outcomes()
        except Exception:
            logger.warning("learning_pipeline_collect_failed", exc_info=True)
            result.cycle_completed_at = datetime.now(UTC)
            return result
        result.evidence_collected = len(evidence)

        if not evidence:
            result.cycle_completed_at = datetime.now(UTC)
            return result

        # Stage 2: Store
        batch_result = await self._store.store_batch(evidence)
        result.evidence_stored = batch_result.stored_count
        result.store_failures = batch_result.failed_count
        if batch_result.errors:
            result.errors.extend(batch_result.errors[:5])

        # Stage 3: Retrieve
        all_goals = " ".join(e.goal for e in evidence[:10])
        all_repos = list({p for e in evidence for p in e.repo_paths})
        try:
            ctx = await self._retriever.get_retrieval_context(all_goals, all_repos)
            result.clusters_found = len(ctx.clusters)
        except Exception:
            logger.warning("learning_pipeline_retrieve_failed", exc_info=True)
            result.cycle_completed_at = datetime.now(UTC)
            return result

        if not ctx.clusters:
            result.cycle_completed_at = datetime.now(UTC)
            return result

        # Stage 4: Synthesize
        try:
            drafts = await self._synthesizer.synthesize_batch(ctx.clusters, ctx.similar_evidence)
        except Exception:
            logger.warning("learning_pipeline_synthesize_failed", exc_info=True)
            result.cycle_completed_at = datetime.now(UTC)
            return result

        result.drafts_synthesized = len(drafts)

        # Stage 5: Review gate (automated quality check only — NOT promotion)
        for draft in drafts:
            gate_result = self._review_gate.validate_for_promotion(draft)
            if gate_result.passed:
                result.drafts_passed_review += 1
            else:
                result.errors.append(
                    f"Draft '{draft.name}' ({draft.skill_id}): {gate_result.summary}"
                )
            logger.info(
                "learning_pipeline_draft: name=%s id=%s review=%s",
                draft.name,
                draft.skill_id,
                "passed" if gate_result.passed else "failed",
            )

        self._total_drafts += len(drafts)
        result.cycle_completed_at = datetime.now(UTC)
        return result


__all__ = [
    "LearningPipelineService",
    "PipelineCycleResult",
]
