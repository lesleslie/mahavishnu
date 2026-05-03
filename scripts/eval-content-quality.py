#!/usr/bin/env python3
"""Evaluate content quality scores against a labeled JSONL dataset.

This script loads content quality samples from a JSONL file, validates the schema,
computes summary statistics, and prints a report. It is a starting point for
developing automated quality scoring that correlates with human labels.

Usage:
    uv run python scripts/eval-content-quality.py data/ml/content-quality-samples.jsonl
    uv run python scripts/eval-content-quality.py --help
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

DIMENSIONS = ["readability", "depth", "completeness", "accuracy", "relevance"]

REQUIRED_FIELDS = {
    "id",
    "source",
    "source_type",
    "title",
    "content",
    "content_length",
    "word_count",
    "label",
    "scores",
    "annotator",
    "annotated_at",
    "notes",
}

VALID_LABELS = {"good", "acceptable", "poor"}
VALID_SOURCE_TYPES = {"webpage", "blog", "pdf", "epub", "markdown", "text"}

LABEL_THRESHOLDS = {"good": 4.0, "acceptable": 3.0, "poor": 0.0}


# ---------------------------------------------------------------------------
# Stub scoring functions — replace with real implementations
# ---------------------------------------------------------------------------


def score_readability(content: str) -> int:
    """Score content readability on a 1-5 scale.

    TODO: Implement using heuristics or a model. Ideas:
    - Flesch-Kincaid grade level
    - Average sentence length
    - Extraction artifact detection (HTML tags, nav text, cookie banners)
    - Presence of structure (headings, lists)

    Args:
        content: The extracted text content.

    Returns:
        Integer score from 1 to 5.
    """
    # TODO: Replace stub with real scoring logic
    return 3


def score_depth(content: str) -> int:
    """Score content topical depth on a 1-5 scale.

    TODO: Implement using heuristics or a model. Ideas:
    - Content length relative to topic breadth
    - Presence of comparisons, trade-offs, edge-case discussion
    - Keyword density for depth indicators ("however", "trade-off",
      "alternatives", "performance", "limitation")
    - Code complexity if code is present

    Args:
        content: The extracted text content.

    Returns:
        Integer score from 1 to 5.
    """
    # TODO: Replace stub with real scoring logic
    return 3


def score_completeness(content: str, content_length: int) -> int:
    """Score content completeness on a 1-5 scale.

    TODO: Implement using heuristics or a model. Ideas:
    - Truncation detection (paywall text, "continued on next page")
    - Length thresholds relative to content type
    - Presence of intro/body/conclusion structure
    - Code block completeness (imports present, runnable)

    Args:
        content: The extracted text content.
        content_length: Original full content length.

    Returns:
        Integer score from 1 to 5.
    """
    # TODO: Replace stub with real scoring logic
    return 3


def score_accuracy(content: str) -> int:
    """Score content accuracy on a 1-5 scale.

    TODO: Implement using heuristics or a model. Ideas:
    - Fact-checking via external API
    - Code syntax validation per detected language
    - Outdated version/API detection
    - Contradiction detection within the text

    Args:
        content: The extracted text content.

    Returns:
        Integer score from 1 to 5.
    """
    # TODO: Replace stub with real scoring logic
    return 3


def score_relevance(content: str, title: str | None) -> int:
    """Score content relevance to the knowledge base on a 1-5 scale.

    TODO: Implement using heuristics or a model. Ideas:
    - Keyword matching against target domain vocabulary
    - Embedding similarity to known-good content
    - URL/domain classification
    - Topic modeling (LDA or similar)

    Args:
        content: The extracted text content.
        title: The content title (may be None).

    Returns:
        Integer score from 1 to 5.
    """
    # TODO: Replace stub with real scoring logic
    return 3


SCORE_FUNCS = {
    "readability": score_readability,
    "depth": score_depth,
    "completeness": score_completeness,
    "accuracy": score_accuracy,
    "relevance": score_relevance,
}

# ---------------------------------------------------------------------------
# Data loading and validation
# ---------------------------------------------------------------------------


def load_samples(path: Path) -> list[dict]:
    """Load JSONL samples from a file.

    Args:
        path: Path to the JSONL file.

    Returns:
        List of parsed JSON objects.

    Raises:
        SystemExit: If the file cannot be read or parsed.
    """
    samples: list[dict] = []
    errors: list[str] = []

    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                sample = json.loads(line)
                samples.append(sample)
            except json.JSONDecodeError as e:
                errors.append(f"  Line {line_num}: JSON parse error: {e}")

    if errors:
        print("JSON parse errors:", file=sys.stderr)
        for err in errors:
            print(err, file=sys.stderr)

    if not samples:
        print(f"Error: no valid samples found in {path}", file=sys.stderr)
        sys.exit(1)

    return samples


def validate_sample(sample: dict, line_num: int) -> list[str]:
    """Validate a single sample against the schema.

    Args:
        sample: Parsed JSON object.
        line_num: Line number (for error messages).

    Returns:
        List of validation error messages (empty if valid).
    """
    issues: list[str] = []

    # Check required fields
    missing = REQUIRED_FIELDS - set(sample.keys())
    if missing:
        issues.append(f"  Line {line_num}: missing fields: {sorted(missing)}")

    # Check label
    label = sample.get("label")
    if label and label not in VALID_LABELS:
        issues.append(f"  Line {line_num}: invalid label '{label}', expected one of {VALID_LABELS}")

    # Check source_type
    source_type = sample.get("source_type")
    if source_type and source_type not in VALID_SOURCE_TYPES:
        issues.append(
            f"  Line {line_num}: invalid source_type '{source_type}', "
            f"expected one of {VALID_SOURCE_TYPES}"
        )

    # Check scores
    scores = sample.get("scores")
    if isinstance(scores, dict):
        missing_dims = set(DIMENSIONS) - set(scores.keys())
        if missing_dims:
            issues.append(f"  Line {line_num}: missing score dimensions: {sorted(missing_dims)}")
        for dim, val in scores.items():
            if not isinstance(val, int) or not 1 <= val <= 5:
                issues.append(f"  Line {line_num}: scores.{dim}={val} is not an integer in [1, 5]")
    elif scores is not None:
        issues.append(f"  Line {line_num}: 'scores' must be a dict, got {type(scores).__name__}")

    # Check label/scores consistency
    if isinstance(scores, dict) and label:
        mean_score = sum(scores.get(d, 0) for d in DIMENSIONS) / len(DIMENSIONS)
        if label == "good" and mean_score < 4.0:
            issues.append(
                f"  Line {line_num}: label='good' but mean score={mean_score:.1f} (< 4.0)"
            )
        elif label == "acceptable" and (mean_score < 3.0 or mean_score >= 4.0):
            issues.append(
                f"  Line {line_num}: label='acceptable' but mean score={mean_score:.1f} "
                f"(not in [3.0, 4.0))"
            )
        elif label == "poor" and mean_score >= 3.0:
            issues.append(
                f"  Line {line_num}: label='poor' but mean score={mean_score:.1f} (>= 3.0)"
            )

    return issues


# ---------------------------------------------------------------------------
# Analysis and reporting
# ---------------------------------------------------------------------------


def compute_statistics(samples: list[dict]) -> dict:
    """Compute summary statistics for the dataset.

    Args:
        samples: Validated sample list.

    Returns:
        Dictionary with summary statistics.
    """
    stats: dict = {
        "total": len(samples),
        "label_distribution": Counter(),
        "source_type_distribution": Counter(),
        "dimension_means": dict.fromkeys(DIMENSIONS, 0.0),
        "dimension_counts": dict.fromkeys(DIMENSIONS, 0),
        "has_code_count": 0,
        "mean_word_count": 0.0,
        "mean_content_length": 0.0,
        "label_mean_scores": {label: dict.fromkeys(DIMENSIONS, 0.0) for label in VALID_LABELS},
        "label_counts": dict.fromkeys(VALID_LABELS, 0),
    }

    for sample in samples:
        stats["label_distribution"][sample.get("label", "unknown")] += 1
        stats["source_type_distribution"][sample.get("source_type", "unknown")] += 1
        stats["mean_word_count"] += sample.get("word_count", 0)
        stats["mean_content_length"] += sample.get("content_length", 0)

        if sample.get("has_code"):
            stats["has_code_count"] += 1

        scores = sample.get("scores", {})
        label = sample.get("label", "unknown")
        stats["label_counts"][label] = stats["label_counts"].get(label, 0) + 1

        for dim in DIMENSIONS:
            val = scores.get(dim)
            if val is not None:
                stats["dimension_means"][dim] += val
                stats["dimension_counts"][dim] += 1
                if label in stats["label_mean_scores"]:
                    stats["label_mean_scores"][label][dim] += val

    n = stats["total"]
    if n > 0:
        stats["mean_word_count"] /= n
        stats["mean_content_length"] /= n
        for dim in DIMENSIONS:
            if stats["dimension_counts"][dim] > 0:
                stats["dimension_means"][dim] /= stats["dimension_counts"][dim]
        for label in VALID_LABELS:
            count = stats["label_counts"].get(label, 0)
            if count > 0:
                for dim in DIMENSIONS:
                    stats["label_mean_scores"][label][dim] /= count

    return stats


def print_report(samples: list[dict], stats: dict) -> None:
    """Print a formatted summary report.

    Args:
        samples: Validated sample list.
        stats: Computed statistics.
    """
    n = stats["total"]

    print()
    print("=" * 70)
    print("  Content Quality Evaluation Report")
    print("=" * 70)
    print()

    # Dataset overview
    print(f"  Total samples:  {n}")
    print(f"  Code-heavy:     {stats['has_code_count']} ({100 * stats['has_code_count'] / n:.0f}%)")
    print(f"  Avg word count: {stats['mean_word_count']:.0f}")
    print(f"  Avg content:    {stats['mean_content_length']:.0f} chars")
    print()

    # Label distribution
    print("  Label Distribution:")
    print("  " + "-" * 40)
    for label in ["good", "acceptable", "poor"]:
        count = stats["label_distribution"].get(label, 0)
        pct = 100 * count / n if n > 0 else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        symbol = {"good": "✅", "acceptable": "⚠️ ", "poor": "❌"}.get(label, "?")
        print(f"  {symbol} {label:<12} {count:>3} ({pct:>5.1f}%) {bar}")
    print()

    # Source type distribution
    print("  Source Types:")
    print("  " + "-" * 40)
    for stype, count in stats["source_type_distribution"].most_common():
        pct = 100 * count / n if n > 0 else 0
        print(f"  {stype:<12} {count:>3} ({pct:>5.1f}%)")
    print()

    # Dimension scores
    print("  Dimension Score Averages (human labels):")
    print("  " + "-" * 40)
    header = f"  {'Dimension':<15} {'Mean':>5}  {'Good':>5}  {'Acc':>5}  {'Poor':>5}"
    print(header)
    print("  " + "-" * len(header.lstrip()))
    for dim in DIMENSIONS:
        overall = stats["dimension_means"][dim]
        good_mean = stats["label_mean_scores"].get("good", {}).get(dim, 0)
        acc_mean = stats["label_mean_scores"].get("acceptable", {}).get(dim, 0)
        poor_mean = stats["label_mean_scores"].get("poor", {}).get(dim, 0)
        print(
            f"  {dim:<15} {overall:>5.2f}  {good_mean:>5.2f}  {acc_mean:>5.2f}  {poor_mean:>5.2f}"
        )
    print()

    # Per-sample detail table
    print("  Per-Sample Scores:")
    print("  " + "-" * 78)
    header = (
        f"  {'ID':<26} {'Label':<12} "
        + " ".join(f"{d[:3].upper():>4}" for d in DIMENSIONS)
        + f"  {'Mean':>5}"
    )
    print(header)
    print("  " + "-" * len(header.lstrip()))

    for sample in samples:
        sid = sample.get("id", "?")[:24]
        label = sample.get("label", "?")
        scores = sample.get("scores", {})
        dim_vals = [scores.get(d, 0) for d in DIMENSIONS]
        mean_val = sum(dim_vals) / len(dim_vals) if dim_vals else 0
        dim_str = " ".join(f"{v:>4}" for v in dim_vals)
        print(f"  {sid:<26} {label:<12} {dim_str}  {mean_val:>5.2f}")

    print()


# ---------------------------------------------------------------------------
# Automated scoring (stub)
# ---------------------------------------------------------------------------


def run_automated_scoring(samples: list[dict]) -> None:
    """Run automated scoring on all samples and compare to human labels.

    Uses ContentQualityScorer from mahavishnu.ingesters.quality_scorer for
    readability, technical_depth, and completeness. Accuracy and relevance
    remain stub functions.

    Args:
        samples: Validated sample list.
    """
    try:
        from mahavishnu.ingesters.quality_scorer import ContentQualityScorer

        scorer = ContentQualityScorer()
        use_scorer = True
    except ImportError:
        use_scorer = False

    label_str = "ContentQualityScorer" if use_scorer else "stub (all scores return 3)"
    print(f"  Automated Scoring ({label_str}):")
    print("  " + "-" * 78)
    header = (
        f"  {'ID':<26} "
        + " ".join(f"{d[:3].upper():>4}" for d in DIMENSIONS)
        + f"  {'Pred':<10} {'Human':<10}"
    )
    print(header)
    print("  " + "-" * len(header.lstrip()))

    agreement = 0
    total = 0

    for sample in samples:
        sid = sample.get("id", "?")[:24]
        content = sample.get("content", "")
        content_length = sample.get("content_length", 0)
        title = sample.get("title")

        if use_scorer:
            report = scorer.score(content, content_id=sid)
            metrics_map = {m.name: m.score for m in report.metrics}
            # Convert 0-1 scores to 1-5 scale for comparison
            auto_scores = {}
            auto_scores["readability"] = round(metrics_map.get("readability", 0.5) * 5)
            auto_scores["depth"] = round(metrics_map.get("technical_depth", 0.5) * 5)
            auto_scores["completeness"] = round(metrics_map.get("completeness", 0.5) * 5)
            # Accuracy and relevance remain stub
            auto_scores["accuracy"] = score_accuracy(content)
            auto_scores["relevance"] = score_relevance(content, title)
        else:
            auto_scores: dict[str, int] = {}
            for dim in DIMENSIONS:
                func = SCORE_FUNCS[dim]
                if dim == "completeness":
                    auto_scores[dim] = func(content, content_length)
                elif dim == "relevance":
                    auto_scores[dim] = func(content, title)
                else:
                    auto_scores[dim] = func(content)

        auto_mean = sum(auto_scores.values()) / len(auto_scores)
        if auto_mean >= 4.0:
            pred_label = "good"
        elif auto_mean >= 3.0:
            pred_label = "acceptable"
        else:
            pred_label = "poor"

        human_label = sample.get("label", "?")
        if pred_label == human_label:
            agreement += 1
        total += 1

        dim_str = " ".join(f"{auto_scores[d]:>4}" for d in DIMENSIONS)
        match = "✓" if pred_label == human_label else "✗"
        print(f"  {sid:<26} {dim_str}  {pred_label:<10} {human_label:<10} {match}")

    print()
    if total > 0:
        print(f"  Agreement: {agreement}/{total} ({100 * agreement / total:.0f}%)")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Evaluate content quality scores against a labeled JSONL dataset.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s data/ml/content-quality-samples.jsonl
  %(prog)s data/ml/content-quality-samples.jsonl --no-auto
  %(prog)s data/ml/content-quality-samples.jsonl --validate-only
        """,
    )
    parser.add_argument(
        "jsonl_path",
        type=Path,
        help="Path to the JSONL file containing labeled content quality samples.",
    )
    parser.add_argument(
        "--no-auto",
        action="store_true",
        help="Skip automated scoring (human-label summary only).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate schema, do not print statistics or scoring.",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Load samples
    samples = load_samples(args.jsonl_path)
    print(f"Loaded {len(samples)} samples from {args.jsonl_path}")

    # Validate schema
    all_issues: list[str] = []
    for i, sample in enumerate(samples, start=1):
        issues = validate_sample(sample, i)
        all_issues.extend(issues)

    if all_issues:
        print(f"\nValidation issues ({len(all_issues)}):")
        for issue in all_issues:
            print(issue, file=sys.stderr)
    else:
        print("All samples pass schema validation.")

    if args.validate_only:
        return

    # Compute and print statistics
    stats = compute_statistics(samples)
    print_report(samples, stats)

    # Run automated scoring
    if not args.no_auto:
        run_automated_scoring(samples)


if __name__ == "__main__":
    main()
