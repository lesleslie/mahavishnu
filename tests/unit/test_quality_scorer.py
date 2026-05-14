"""Tests for ContentQualityScorer — readability, depth, completeness, drift monitoring."""

from __future__ import annotations

from mahavishnu.ingesters.quality_scorer import (
    ContentQualityScorer,
    EvaluationReport,
    MetricScore,
    QualityMetric,
    QualityThresholds,
    score_completeness,
    score_readability,
    score_technical_depth,
)


class TestReadability:
    def test_empty_content(self) -> None:
        assert score_readability("") == 0.0

    def test_well_structured_markdown(self) -> None:
        text = (
            "# Title\n\n"
            "Short intro paragraph.\n\n"
            "## Section\n\n"
            "Another paragraph with `code` inline.\n\n"
            "- List item 1\n"
            "- List item 2\n"
        )
        score = score_readability(text)
        assert 0.6 <= score <= 1.0

    def test_long_sentences_penalized(self) -> None:
        text = "A " * 100 + "."  # Very long single sentence
        score = score_readability(text)
        assert score < 0.6


class TestTechnicalDepth:
    def test_empty_content(self) -> None:
        assert score_technical_depth("") == 0.0

    def test_code_examples(self) -> None:
        text = "## Example\n\n```python\nprint('hello')\n```\n\nUses `process()` function."
        score = score_technical_depth(text)
        assert score >= 0.5

    def test_plain_text_no_code(self) -> None:
        text = "Just some plain text with no code or technical references."
        score = score_technical_depth(text)
        assert score < 0.4


class TestCompleteness:
    def test_empty_content(self) -> None:
        assert score_completeness("") == 0.0

    def test_comprehensive_doc(self) -> None:
        text = (
            "# Guide\n\n"
            "## Prerequisites\n\nInstall Python.\n\n"
            "## Steps\n\nDo step 1. Do step 2.\n\n"
            "## Example\n\n```python\nx = 1\n```\n\n"
            "## Next Steps\n\nSee docs for more info.\n"
        )
        score = score_completeness(text)
        assert score >= 0.5

    def test_minimal_content(self) -> None:
        text = "Short blurb."
        score = score_completeness(text)
        assert score < 0.4


class TestContentQualityScorer:
    def test_score_returns_report(self) -> None:
        scorer = ContentQualityScorer()
        report = scorer.score("# Hello\n\nSome content.", content_id="test-1")
        assert isinstance(report, EvaluationReport)
        assert report.content_id == "test-1"
        assert 0.0 <= report.score <= 1.0
        assert len(report.metrics) == 3

    def test_overall_is_weighted(self) -> None:
        scorer = ContentQualityScorer()
        report = scorer.score("# Good doc\n\nWith ```code```.", content_id="t")
        # overall = 0.30 * readability + 0.40 * depth + 0.30 * completeness
        metrics = {m.name: m.score for m in report.metrics}
        expected = (
            0.30 * metrics["readability"]
            + 0.40 * metrics["technical_depth"]
            + 0.30 * metrics["completeness"]
        )
        assert abs(report.score - round(expected, 3)) < 0.01

    def test_history_tracks_scores(self) -> None:
        scorer = ContentQualityScorer()
        scorer.score("Content A", "a")
        scorer.score("Content B", "b")
        history = scorer.get_history()
        assert len(history) == 2
        assert history[0]["content_id"] == "a"

    def test_drift_stats(self) -> None:
        scorer = ContentQualityScorer()
        scorer.score("Good content", "a")
        scorer.score("Bad", "b")
        stats = scorer.get_drift_stats()
        assert stats["count"] == 2
        assert "mean" in stats

    def test_check_drift_no_alert(self) -> None:
        scorer = ContentQualityScorer()
        scorer.score("Content", "a")
        result = scorer.check_drift(baseline_mean=0.5, baseline_variance=0.01)
        assert "drift_detected" in result

    def test_quality_thresholds_flag(self) -> None:
        thresholds = QualityThresholds(overall_flag=0.70)
        report = EvaluationReport(
            content_id="test",
            score=0.50,
            metrics=[
                MetricScore(QualityMetric.READABILITY.value, 0.8),
                MetricScore("technical_depth", 0.3),
                MetricScore(QualityMetric.COMPLETENESS.value, 0.4),
            ],
        )
        flagged, reason = thresholds.should_flag(report)
        assert flagged
        assert "0.50" in reason
