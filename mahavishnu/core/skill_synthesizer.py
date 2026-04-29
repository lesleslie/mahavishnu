"""Synthesize stage of the review-gated learning pipeline.

Clusters retrieved evidence and drafts SkillDraft proposals from
recurring patterns observed across sessions.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import uuid4

from mahavishnu.core.evidence_retriever import EvidenceCluster, RetrievedEvidence
from mahavishnu.core.skill_governance import SkillDraft, SkillPromotionState
from mahavishnu.core.skill_security import sanitize_skill_body

logger = logging.getLogger(__name__)


class SkillSynthesizer:
    """Converts evidence clusters into reviewable SkillDraft proposals.

    The synthesizer applies lightweight heuristics to derive skill names,
    trigger conditions, and body templates from clustered evidence.  Drafts
    are passed through security sanitization before being returned.
    """

    def __init__(
        self,
        min_evidence: int = 5,
        max_drafts_per_cycle: int = 3,
    ) -> None:
        self._min_evidence = min_evidence
        self._max_drafts_per_cycle = max_drafts_per_cycle

    async def synthesize_from_cluster(
        self,
        cluster: EvidenceCluster,
        similar_evidence: list[RetrievedEvidence],
    ) -> SkillDraft | None:
        if cluster.member_count < self._min_evidence:
            logger.debug(
                "Skipping cluster %s: %d members < min_evidence %d",
                cluster.cluster_id,
                cluster.member_count,
                self._min_evidence,
            )
            return None

        name = self._derive_name(cluster.representative_goal)
        description = self._derive_description(cluster)
        triggers = self._derive_trigger_conditions(cluster, similar_evidence)
        trigger_text = "; ".join(triggers)

        body = (
            f"# Auto-generated skill from evidence cluster {cluster.cluster_id}\n\n"
            f"## Trigger\n{trigger_text}\n\n"
            f"## Pattern\n{description}\n\n"
            f"## Recommended Actions\n(To be filled by reviewer)"
        )

        body = sanitize_skill_body(body)

        draft = SkillDraft(
            skill_id=f"skill_{uuid4().hex}",
            name=name,
            version="0.1.0",
            description=description,
            trigger_conditions=triggers,
            body=body,
            source_evidence_ids=cluster.evidence_ids,
            proposed_by="learning_pipeline",
            state=SkillPromotionState.DRAFT,
        )

        logger.info(
            "Synthesized draft '%s' from cluster %s (%d evidence items)",
            draft.name,
            cluster.cluster_id,
            cluster.member_count,
        )
        return draft

    async def synthesize_batch(
        self,
        clusters: list[EvidenceCluster],
        similar: list[RetrievedEvidence],
    ) -> list[SkillDraft]:
        drafts: list[SkillDraft] = []
        for cluster in clusters:
            if len(drafts) >= self._max_drafts_per_cycle:
                break
            draft = await self.synthesize_from_cluster(cluster, similar)
            if draft is not None:
                drafts.append(draft)
        return drafts

    def _derive_name(self, goal: str) -> str:
        name = goal.lower().strip()
        name = re.sub(r"[^a-z0-9\s-]", "", name)
        name = re.sub(r"\s+", "-", name)
        name = re.sub(r"-{2,}", "-", name)
        name = name.strip("-")
        name = name[:50]
        return f"learned-{name}"

    def _derive_description(self, cluster: EvidenceCluster) -> str:
        repos = cluster.repo_paths or []
        parts = [f"Pattern across {cluster.member_count} sessions"]
        if repos:
            parts.append(f"involving {len(repos)} repositories")
        if cluster.representative_goal:
            parts.append(f"with goals like: {cluster.representative_goal}")
        return ", ".join(parts) + "."

    def _derive_trigger_conditions(
        self,
        cluster: EvidenceCluster,
        evidence: list[RetrievedEvidence],
    ) -> list[str]:
        conditions: list[str] = []

        all_goals: list[str] = [e.goal for e in evidence]
        repo_extensions: set[str] = set()
        for path in cluster.repo_paths or []:
            ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if ext and len(ext) <= 10:
                repo_extensions.add(ext)

        lang_map: dict[str, str] = {
            "py": "Python",
            "ts": "TypeScript",
            "js": "JavaScript",
            "go": "Go",
            "rs": "Rust",
            "java": "Java",
            "yaml": "YAML configuration",
            "yml": "YAML configuration",
            "toml": "TOML configuration",
        }

        for ext, lang in lang_map.items():
            if ext in repo_extensions:
                conditions.append(f"{lang} task")

        goal_keywords: set[str] = set()
        for goal in all_goals:
            for word in goal.lower().split():
                if len(word) >= 4:
                    goal_keywords.add(word)

        frequent_keywords = [
            kw for kw in goal_keywords
            if sum(1 for g in all_goals if kw in g.lower()) >= 2
        ]
        for kw in frequent_keywords[:3]:
            conditions.append(f"Goal mentions '{kw}'")

        if not conditions:
            conditions.append(f"Recurring pattern in {cluster.member_count} sessions")

        return conditions


__all__ = [
    "SkillSynthesizer",
]
