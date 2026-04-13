"""Content quality scorer — readability, depth, completeness metrics.

Replaces the stub QualityEvaluator with real heuristic-based scoring.

Scoring dimensions:
- **Readability**: Sentence length, paragraph structure, jargon density, formatting
- **Technical depth**: Code examples, API mentions, edge cases, architecture
- **Completeness**: Topic coverage, prerequisites, next steps, examples

Thresholds (from docs/specs/content-quality-dataset.md):
  overall < 0.70 → flag for review
  readability < 0.50 → flag for rewriting
  technical_depth < 0.40 → skip (low-value)
  completeness < 0.50 → flag for augmentation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
import re
from typing import Any


# ---------------------------------------------------------------------------
# Quality types (merged from quality_evaluator.py)
# ---------------------------------------------------------------------------


class QualityMetric(str, Enum):
    """Quality metric types."""

    READABILITY = "readability"
    COMPLETENESS = "completeness"
    ACCURACY = "accuracy"
    RELEVANCE = "relevance"


@dataclass
class MetricScore:
    """Quality metric score."""

    name: str
    score: float
    description: str | None = None


@dataclass
class EvaluationReport:
    """Quality evaluation report."""

    content_id: str
    score: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    metrics: list[MetricScore] = field(default_factory=list)


@dataclass
class QualityThresholds:
    """Configurable thresholds for quality decisions."""

    overall_flag: float = 0.70
    readability_rewrite: float = 0.50
    technical_depth_skip: float = 0.40
    completeness_augment: float = 0.50

    def should_flag(self, report: EvaluationReport) -> tuple[bool, str]:
        """Check if content should be flagged.

        Returns:
            (flagged, reason) tuple.
        """
        metrics = {m.name: m.score for m in report.metrics}

        overall = report.score
        if overall < self.overall_flag:
            return True, f"Overall score {overall:.2f} below threshold {self.overall_flag}"

        readability = metrics.get(QualityMetric.READABILITY.value, 1.0)
        if readability < self.readability_rewrite:
            return True, f"Readability {readability:.2f} below threshold {self.readability_rewrite}"

        depth = metrics.get("technical_depth", 1.0)
        if depth < self.technical_depth_skip:
            return True, f"Technical depth {depth:.2f} below threshold {self.technical_depth_skip}"

        completeness = metrics.get(QualityMetric.COMPLETENESS.value, 1.0)
        if completeness < self.completeness_augment:
            return True, f"Completeness {completeness:.2f} below threshold {self.completeness_augment}"

        return False, ""


def _score_sentence_length(text: str) -> float:
    """Score based on average sentence length. Best ≤ 25 words."""
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return 0.0

    avg_len = sum(len(s.split()) for s in sentences) / len(sentences)
    # Ideal: 15–25 words. Score degrades above 35.
    if avg_len <= 25:
        return 1.0
    if avg_len <= 35:
        return 1.0 - (avg_len - 25) / 20.0
    return max(0.0, 0.5 - (avg_len - 35) / 40.0)


def _score_paragraph_structure(text: str) -> float:
    """Score based on paragraph length. Best ≤ 5 sentences."""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return 0.5

    good = 0
    for para in paragraphs:
        sent_count = len([s for s in re.split(r"[.!?]+", para) if s.strip()])
        if sent_count <= 5:
            good += 1

    return good / len(paragraphs)


def _score_jargon(text: str) -> float:
    """Score based on whether technical terms seem contextualized.

    Penalizes dense jargon without surrounding explanatory text.
    """
    # Common tech patterns that indicate jargon
    jargon_patterns = [
        r"\b[A-Z]{2,}\b",  # Acronyms
        r"\b[a-z]+(?:_[a-z]+)+\b",  # snake_case terms
        r"\b(?:implement|configure|deploy|orchestrate|provision)\b",
    ]
    jargon_count = sum(len(re.findall(p, text)) for p in jargon_patterns)
    word_count = len(text.split())

    if word_count == 0:
        return 0.5

    jargon_ratio = jargon_count / word_count
    # Up to 5% jargon is fine; above 10% is penalized
    if jargon_ratio <= 0.05:
        return 1.0
    if jargon_ratio <= 0.10:
        return 0.8
    return max(0.2, 1.0 - jargon_ratio * 5)


def _score_formatting(text: str) -> float:
    """Score based on use of headers, lists, code blocks."""
    has_headers = bool(re.search(r"^#+\s", text, re.MULTILINE))
    has_lists = bool(re.search(r"^\s*[-*]\s", text, re.MULTILINE))
    has_code = bool(re.search(r"```", text)) or bool(re.search(r"`[^`]+`", text))

    score = 0.3  # baseline
    if has_headers:
        score += 0.25
    if has_lists:
        score += 0.25
    if has_code:
        score += 0.20
    return min(1.0, score)


def score_readability(text: str) -> float:
    """Compute readability score (0.0–1.0)."""
    if not text.strip():
        return 0.0
    s1 = _score_sentence_length(text)
    s2 = _score_paragraph_structure(text)
    s3 = _score_jargon(text)
    s4 = _score_formatting(text)
    return 0.25 * s1 + 0.25 * s2 + 0.25 * s3 + 0.25 * s4


def _score_code_examples(text: str) -> float:
    """Score based on code block presence and size."""
    code_blocks = re.findall(r"```[\s\S]*?```", text)
    if not code_blocks:
        inline_code = re.findall(r"`[^`]+`", text)
        if inline_code:
            return 0.3
        return 0.0
    # 1-3 blocks is ideal
    if len(code_blocks) <= 3:
        return 1.0
    if len(code_blocks) <= 6:
        return 0.8
    return 0.6


def _score_api_coverage(text: str) -> float:
    """Score based on API/function/method references."""
    # Look for function call patterns, class references
    api_patterns = [
        r"\b\w+\(",  # Function calls
        r"\b[A-Z]\w+\.[a-z]+\b",  # Class.method
        r"\bdef\s+\w+",  # Python def
        r"\bfunction\s+\w+",  # JS function
        r"\bclass\s+\w+",  # Class definition
    ]
    matches = sum(len(re.findall(p, text)) for p in api_patterns)
    if matches == 0:
        return 0.0
    if matches <= 5:
        return 0.7
    if matches <= 15:
        return 1.0
    return 0.9


def _score_edge_cases(text: str) -> float:
    """Score based on error/edge case discussion."""
    edge_patterns = [
        r"\berror\b", r"\bexception\b", r"\bfallback\b",
        r"\btimeout\b", r"\bretry\b", r"\bvalidation\b",
        r"\bhandle\b", r"\bsafety\b", r"\bcheck\b",
    ]
    matches = sum(len(re.findall(p, text, re.IGNORECASE)) for p in edge_patterns)
    if matches == 0:
        return 0.1
    if matches <= 3:
        return 0.5
    if matches <= 10:
        return 0.8
    return 1.0


def _score_architecture(text: str) -> float:
    """Score based on architectural discussion."""
    arch_patterns = [
        r"\bpattern\b", r"\bdesign\b", r"\barchitecture\b",
        r"\btrade-?off\b", r"\bdecision\b", r"\bstrategy\b",
        r"\babstraction\b", r"\bcomponent\b", r"\bmodule\b",
    ]
    matches = sum(len(re.findall(p, text, re.IGNORECASE)) for p in arch_patterns)
    if matches == 0:
        return 0.1
    if matches <= 3:
        return 0.5
    if matches <= 8:
        return 0.8
    return 1.0


def score_technical_depth(text: str) -> float:
    """Compute technical depth score (0.0–1.0)."""
    if not text.strip():
        return 0.0
    s1 = _score_code_examples(text)
    s2 = _score_api_coverage(text)
    s3 = _score_edge_cases(text)
    s4 = _score_architecture(text)
    return 0.30 * s1 + 0.30 * s2 + 0.20 * s3 + 0.20 * s4


def _score_topic_coverage(text: str) -> float:
    """Score based on text length and section structure."""
    word_count = len(text.split())
    sections = len(re.findall(r"^#+\s", text, re.MULTILINE))

    # Length score
    if word_count < 50:
        length_score = 0.1
    elif word_count < 200:
        length_score = 0.5
    elif word_count < 1000:
        length_score = 0.8
    else:
        length_score = 1.0

    # Section score
    if sections == 0:
        section_score = 0.3
    elif sections <= 3:
        section_score = 0.7
    else:
        section_score = 1.0

    return 0.5 * length_score + 0.5 * section_score


def _score_prerequisites(text: str) -> float:
    """Score based on prerequisites/requirements mentions."""
    prereq_patterns = [
        r"\bprerequisite\b", r"\brequir(?:e|ment)\b",
        r"\bdepend(?:enc(?:y|ies))?\b", r"\binstall\b",
        r"\bsetup\b", r"\bconfigure\b", r"\bbefore you\b",
        r"\bfirst\b",
    ]
    matches = sum(len(re.findall(p, text, re.IGNORECASE)) for p in prereq_patterns)
    if matches == 0:
        return 0.1
    if matches <= 2:
        return 0.5
    if matches <= 5:
        return 0.8
    return 1.0


def _score_next_steps(text: str) -> float:
    """Score based on follow-up / next step references."""
    next_patterns = [
        r"\bnext\b", r"\bfollow\b", r"\bsee also\b",
        r"\bfor more\b", r"\breference\b", r"\bdocs\b",
        r"\bhttp[s]?://\b", r"\bfurther\b", r"\bcontinue\b",
    ]
    matches = sum(len(re.findall(p, text, re.IGNORECASE)) for p in next_patterns)
    if matches == 0:
        return 0.1
    if matches <= 2:
        return 0.5
    if matches <= 5:
        return 0.8
    return 1.0


def _score_examples(text: str) -> float:
    """Score based on worked examples."""
    example_patterns = [
        r"\bexample\b", r"\be\.g\.", r"\bsample\b",
        r"\bdemo\b", r"\btutorial\b",
    ]
    matches = sum(len(re.findall(p, text, re.IGNORECASE)) for p in example_patterns)
    code_blocks = len(re.findall(r"```[\s\S]*?```", text))

    example_score = min(1.0, matches / 3.0) if matches > 0 else 0.1
    code_score = min(1.0, code_blocks / 2.0) if code_blocks > 0 else 0.1

    return 0.5 * example_score + 0.5 * code_score


def score_completeness(text: str) -> float:
    """Compute completeness score (0.0–1.0)."""
    if not text.strip():
        return 0.0
    s1 = _score_topic_coverage(text)
    s2 = _score_prerequisites(text)
    s3 = _score_next_steps(text)
    s4 = _score_examples(text)
    return 0.30 * s1 + 0.25 * s2 + 0.25 * s3 + 0.20 * s4


class ContentQualityScorer:
    """Heuristic-based content quality scorer.

    Replaces the stub QualityEvaluator with real metrics.

    Usage:
        scorer = ContentQualityScorer()
        report = scorer.score(markdown_text, content_id="doc-123")
        print(f"Overall: {report.score:.2f}")
        for m in report.metrics:
            print(f"  {m.name}: {m.score:.2f}")
    """

    def __init__(self, thresholds: QualityThresholds | None = None) -> None:
        self.thresholds = thresholds or QualityThresholds()
        self._history: list[dict[str, Any]] = []

    def score(self, content: str, content_id: str = "unknown") -> EvaluationReport:
        """Score content quality across all dimensions.

        Args:
            content: Text content to evaluate
            content_id: Identifier for this content

        Returns:
            EvaluationReport with scores and flags
        """
        readability = score_readability(content)
        depth = score_technical_depth(content)
        completeness = score_completeness(content)

        overall = 0.30 * readability + 0.40 * depth + 0.30 * completeness

        metrics = [
            MetricScore(
                name=QualityMetric.READABILITY.value,
                score=round(readability, 3),
                description="Content readability (sentence length, structure, jargon, formatting)",
            ),
            MetricScore(
                name="technical_depth",
                score=round(depth, 3),
                description="Technical depth (code examples, API coverage, edge cases, architecture)",
            ),
            MetricScore(
                name=QualityMetric.COMPLETENESS.value,
                score=round(completeness, 3),
                description="Content completeness (topic coverage, prerequisites, next steps, examples)",
            ),
        ]

        issues: list[str] = []
        suggestions: list[str] = []

        flagged, reason = self.thresholds.should_flag(
            EvaluationReport(content_id=content_id, score=overall, metrics=metrics)
        )
        if flagged:
            issues.append(reason)

        if readability < 0.50:
            suggestions.append("Consider shorter sentences, more headers, and code formatting")
        if depth < 0.40:
            suggestions.append("Add code examples and API references to increase technical depth")
        if completeness < 0.50:
            suggestions.append("Add prerequisites section, examples, and next-step references")

        report = EvaluationReport(
            content_id=content_id,
            score=round(overall, 3),
            issues=issues,
            suggestions=suggestions,
            metrics=metrics,
        )

        self._history.append(
            {
                "content_id": content_id,
                "score": overall,
                "readability": readability,
                "technical_depth": depth,
                "completeness": completeness,
                "flagged": flagged,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        return report

    def get_history(self) -> list[dict[str, Any]]:
        """Get scoring history for drift monitoring."""
        return list(self._history)

    def get_drift_stats(self) -> dict[str, Any]:
        """Compute drift statistics from scoring history.

        Returns mean and variance of overall scores for drift detection.
        """
        if not self._history:
            return {"count": 0, "mean": 0.0, "variance": 0.0}

        scores = [h["score"] for h in self._history]
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)

        return {
            "count": len(scores),
            "mean": round(mean, 3),
            "variance": round(variance, 4),
            "min": round(min(scores), 3),
            "max": round(max(scores), 3),
        }

    def check_drift(self, baseline_mean: float, baseline_variance: float) -> dict[str, Any]:
        """Check for drift from baseline statistics.

        Alerts when:
        - Mean overall score drops > 0.10 from baseline
        - Variance increases > 50% from baseline
        """
        stats = self.get_drift_stats()
        if stats["count"] == 0:
            return {"drift_detected": False, "reason": "No history data"}

        alerts: list[str] = []

        mean_drop = baseline_mean - stats["mean"]
        if mean_drop > 0.10:
            alerts.append(f"Mean dropped {mean_drop:.3f} from baseline {baseline_mean:.3f}")

        if baseline_variance > 0 and stats["variance"] > baseline_variance * 1.5:
            alerts.append(
                f"Variance {stats['variance']:.4f} exceeds 1.5x baseline {baseline_variance:.4f}"
            )

        return {
            "drift_detected": len(alerts) > 0,
            "alerts": alerts,
            "current_stats": stats,
            "baseline_mean": baseline_mean,
            "baseline_variance": baseline_variance,
        }


__all__ = [
    "ContentQualityScorer",
    "EvaluationReport",
    "MetricScore",
    "QualityMetric",
    "QualityThresholds",
    "score_readability",
    "score_technical_depth",
    "score_completeness",
]
