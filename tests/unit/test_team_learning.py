"""Unit tests for core.team_learning."""

from __future__ import annotations

from datetime import UTC, datetime

import mahavishnu.core.team_learning as tl


def _outcome(
    *,
    team_id: str = "t1",
    intent: str = "review",
    domain: str = "security",
    skills: list[str] | None = None,
    mode: str = "coordinate",
    success: bool = True,
    latency_ms: float = 1000.0,
    quality: float | None = None,
    feedback: str | None = None,
) -> tl.TeamExecutionOutcome:
    return tl.TeamExecutionOutcome(
        team_id=team_id,
        goal="review auth",
        parsed_intent=intent,
        parsed_domain=domain,
        parsed_skills=skills or ["security"],
        team_mode=mode,
        task="scan",
        success=success,
        latency_ms=latency_ms,
        tokens_used=123,
        quality_score=quality,
        timestamp=datetime.now(UTC),
        user_feedback=feedback,
    )


def test_models_to_dict_and_properties() -> None:
    outcome = _outcome(quality=85.0, feedback="positive")
    d = outcome.to_storage_dict()
    assert d["team_id"] == "t1"
    assert d["quality_score"] == 85.0
    assert isinstance(d["timestamp"], str)

    stats = tl.TeamLearningStats()
    assert stats.success_rate == 0.0
    assert stats.avg_latency_ms == 0.0
    assert stats.avg_quality_score is None
    assert stats.feedback_ratio is None

    stats.total_executions = 4
    stats.successful_executions = 3
    stats.total_latency_ms = 2000.0
    stats.total_quality_score = 150.0
    stats.quality_samples = 2
    stats.positive_feedback_count = 3
    stats.negative_feedback_count = 1
    assert stats.success_rate == 0.75
    assert stats.avg_latency_ms == 500.0
    assert stats.avg_quality_score == 75.0
    assert stats.feedback_ratio == 0.75
    assert stats.to_dict()["success_rate"] == 0.75


def test_record_outcome_and_basic_stats() -> None:
    engine = tl.TeamLearningEngine(max_recent_outcomes=3)
    engine.record_outcome(
        _outcome(mode="coordinate", success=True, quality=90, feedback="positive")
    )
    engine.record_outcome(
        _outcome(mode="coordinate", success=False, quality=50, feedback="negative")
    )
    engine.record_outcome(_outcome(mode="route", success=True, quality=None))
    engine.record_outcome(
        _outcome(mode="route", success=True)
    )  # pushes out oldest due to max_recent=3

    assert len(engine.get_recent_outcomes(limit=10)) == 3
    assert engine.get_skill_success_rate(["security"]) > 0.0
    assert engine.get_skill_success_rate(["missing"]) == 0.0
    assert engine.get_intent_stats("review") is not None
    assert engine.get_mode_stats("coordinate") is not None

    summary = engine.get_learning_summary()
    assert summary["total_outcomes"] == 3
    assert summary["modes_tracked"] >= 2
    assert isinstance(summary["mode_performance"], dict)
    assert isinstance(summary["intent_performance"], dict)
    assert 0.0 <= summary["recent_success_rate"] <= 1.0


def test_mode_recommendation_none_and_ranked() -> None:
    engine = tl.TeamLearningEngine()
    assert engine.get_mode_recommendation("review", min_samples=2) is None

    # coordinate: high success + quality + feedback
    for _ in range(4):
        engine.record_outcome(
            _outcome(
                intent="review",
                mode="coordinate",
                success=True,
                quality=95.0,
                feedback="positive",
            )
        )
    # route: lower performance
    for i in range(4):
        engine.record_outcome(
            _outcome(
                intent="review",
                mode="route",
                success=(i % 2 == 0),
                quality=60.0,
                feedback="negative",
            )
        )

    engine._intent_mode_stats["other:ignored"] = tl.TeamLearningStats(  # noqa: SLF001
        total_executions=10,
        successful_executions=10,
    )
    engine._intent_mode_stats["review:tiny"] = tl.TeamLearningStats(  # noqa: SLF001
        total_executions=1,
        successful_executions=1,
    )

    rec = engine.get_mode_recommendation("review", min_samples=3)
    assert rec is not None
    assert rec.mode == "coordinate"
    assert 0.0 <= rec.confidence <= 1.0
    assert rec.sample_count >= 3
    assert "success rate" in rec.reason


def test_top_skills_and_recent_window_and_clear() -> None:
    engine = tl.TeamLearningEngine(max_recent_outcomes=100)
    for i in range(6):
        engine.record_outcome(
            _outcome(
                skills=["security", "quality"] if i < 4 else ["performance"],
                success=i != 4,
                latency_ms=500 + i,
                quality=80 if i < 4 else 70,
            )
        )
    top = engine._get_top_skills(limit=5)  # noqa: SLF001
    assert top
    assert top[0]["executions"] >= 3
    assert 0.0 <= engine._get_recent_success_rate(window=3) <= 1.0  # noqa: SLF001

    engine.clear_stats()
    assert engine.get_learning_summary()["total_outcomes"] == 0


def test_export_import_and_context_singleton() -> None:
    engine = tl.TeamLearningEngine()
    engine.record_outcome(_outcome(intent="build", mode="broadcast", success=True, quality=88))
    exported = engine.export_stats()
    assert "skill_stats" in exported
    assert "intent_stats" in exported

    e2 = tl.TeamLearningEngine()
    e2.import_stats(exported)
    assert e2.get_intent_stats("build") is not None
    assert e2.get_mode_stats("broadcast") is not None
    # recent outcomes intentionally not restored
    assert e2.get_recent_outcomes() == []

    tl.reset_learning_engine()
    g1 = tl.get_learning_engine()
    g2 = tl.get_learning_engine()
    assert g1 is g2

    tl.set_learning_engine_in_context(g1)
    assert tl.get_learning_engine_from_context() is g1
    tl.set_learning_engine_in_context(None)
    assert tl.get_learning_engine_from_context() is None
    tl.reset_learning_engine()
