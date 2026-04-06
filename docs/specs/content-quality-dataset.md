# Content Quality Dataset & Evaluation Rubric

## Overview

Defines the labeled dataset schema and evaluation rubric for the content quality
scoring system (Initiative 15).

## Labeled Dataset Schema

Each entry in the labeled dataset follows this structure:

```json
{
  "id": "uuid-string",
  "content": "Full text of the content to evaluate",
  "source_type": "webpage|blog|book|code_doc",
  "labels": {
    "readability": 0.85,
    "technical_depth": 0.72,
    "completeness": 0.90,
    "overall": 0.82
  },
  "annotator": "human|llm-judge",
  "created_at": "2026-04-05T12:00:00Z"
}
```

### Label Scale

| Score Range | Rating     | Description                                    |
|-------------|------------|------------------------------------------------|
| 0.0–0.3     | Poor       | Unusable, no value, severely incomplete        |
| 0.3–0.5     | Below Avg  | Marginal utility, missing key information      |
| 0.5–0.7     | Average    | Adequate but not exceptional                   |
| 0.7–0.9     | Good       | Well-structured, comprehensive, useful         |
| 0.9–1.0     | Excellent  | Outstanding clarity, depth, and completeness   |

### Minimum Dataset Size

| Split     | Count | Purpose                        |
|-----------|-------|--------------------------------|
| Train     | 200   | Threshold tuning & calibration  |
| Validate  | 50    | Hyperparameter selection        |
| Test      | 100   | Final quality reporting         |

## Evaluation Rubric

### Readability (0.0–1.0)

| Criterion           | Weight | Description                                   |
|---------------------|--------|-----------------------------------------------|
| Sentence length     | 0.25   | Average sentence ≤ 25 words                   |
| Paragraph structure | 0.25   | Paragraphs ≤ 5 sentences, logical flow         |
| Jargon density      | 0.25   | Technical terms defined or contextualized      |
| Formatting          | 0.25   | Headers, lists, code blocks used appropriately |

### Technical Depth (0.0–1.0)

| Criterion           | Weight | Description                                   |
|---------------------|--------|-----------------------------------------------|
| Code examples       | 0.30   | Includes runnable code snippets                |
| API coverage        | 0.30   | Covers relevant APIs/functions/methods          |
| Edge cases          | 0.20   | Addresses error handling, edge cases           |
| Architecture        | 0.20   | Explains design decisions and trade-offs        |

### Completeness (0.0–1.0)

| Criterion           | Weight | Description                                   |
|---------------------|--------|-----------------------------------------------|
| Topic coverage      | 0.30   | Covers stated topic comprehensively             |
| Prerequisites        | 0.25   | Lists requirements/dependencies                |
| Next steps          | 0.25   | Provides links, references, or follow-up       |
| Examples            | 0.20   | Multiple worked examples                       |

## Scoring Algorithm

```
overall = 0.30 * readability + 0.40 * technical_depth + 0.30 * completeness
```

Technical depth is weighted highest because Mahavishnu ingests primarily
developer-facing content (documentation, blog posts, books) where depth matters.

## Thresholds

| Metric            | Threshold | Action if below             |
|-------------------|-----------|------------------------------|
| Overall           | 0.70      | Flag for review              |
| Readability        | 0.50      | Flag for rewriting           |
| Technical Depth    | 0.40      | Skip (low-value content)     |
| Completeness       | 0.50      | Flag for augmentation        |

## Drift Monitoring

Track score distribution over time. Alert when:
- Mean overall score drops > 0.10 from baseline
- Variance increases > 50% from baseline
- Any single metric drops > 0.15 from baseline
