# Content Quality Dataset Specification

> **Version**: 1.0.0
> **Purpose**: Define the structure, collection strategy, and management of labeled
> content quality samples for training and evaluating automated quality scorers.

______________________________________________________________________

## Overview

This dataset provides **human-labeled ground truth** for content quality scoring in
Mahavishnu's ingestion pipeline. Each sample is a piece of content (webpage, blog
post, document) annotated with per-dimension quality scores according to the
[Content Quality Evaluation Rubric](./content-quality-eval-rubric.md).

The dataset serves two purposes:

1. **Training**: Supervise an automated quality scorer that replaces the current
   stub in `mahavishnu/ingesters/quality_evaluator.py`.
1. **Evaluation**: Benchmark automated scoring against human judgment.

______________________________________________________________________

## Schema

Each sample is a single JSON object (one per line in JSONL format) with the
following fields:

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | Unique identifier. Use ULID or `source-{hash}`. |
| `source` | `string` | URL or file path where the content was obtained. |
| `source_type` | `string` | One of: `"webpage"`, `"blog"`, `"pdf"`, `"epub"`, `"markdown"`, `"text"`. Matches `ContentType` enum. |
| `title` | `string` or `null` | Extracted title of the content. |
| `content` | `string` | The full extracted text content (post-cleaning, pre-chunking). May be truncated to first 10,000 chars for storage efficiency. |
| `content_length` | `integer` | Character count of the original full content (before any truncation). |
| `word_count` | `integer` | Word count of the stored `content` field. |
| `label` | `string` | Aggregate label: `"good"`, `"acceptable"`, or `"poor"`. |
| `scores` | `object` | Per-dimension scores (see below). |
| `annotator` | `string` | Who labeled this sample (e.g., `"human"`, `"human:les"`, `"synthetic"`). |
| `annotated_at` | `string` | ISO 8601 timestamp of annotation. |
| `notes` | `string` | Free-text justification for the scores (required for human labels). |

### `scores` Object

| Field | Type | Description |
|-------|------|-------------|
| `readability` | `integer` | 1–5 score for readability. |
| `depth` | `integer` | 1–5 score for topical depth. |
| `completeness` | `integer` | 1–5 score for completeness. |
| `accuracy` | `integer` | 1–5 score for accuracy. |
| `relevance` | `integer` | 1–5 score for relevance. |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `language` | `string` | ISO 639-1 code (default `"en"`). |
| `has_code` | `boolean` | Whether content contains code blocks. |
| `code_languages` | `list[string]` | Languages found in code blocks (e.g., `["python", "yaml"]`). |
| `has_images` | `boolean` | Whether original content contained images (even if not extracted). |
| `extraction_artifacts` | `list[string]` | Types of extraction noise found (e.g., `["nav_menu", "cookie_banner"]`). |
| `paywall_truncated` | `boolean` | Whether content was truncated by a paywall. |
| `publish_date` | `string` or `null` | Original publication date if known. |
| `domain` | `string` | Domain name extracted from URL (for web sources). |
| `tags` | `list[string]` | Content categorization tags (e.g., `["python", "async", "tutorial"]`). |

### Example Record

```json
{
  "id": "01JMQT1XKGRM5F0R8P2BNV4ABC",
  "source": "https://docs.python.org/3/library/asyncio-task.html",
  "source_type": "webpage",
  "title": "Coroutines and Tasks — Python 3.13 documentation",
  "content": "# Coroutines and Tasks\n\n## Coroutines\n\nCoroutines declared with the async/await syntax is the preferred way...",
  "content_length": 45230,
  "word_count": 6800,
  "label": "good",
  "scores": {
    "readability": 5,
    "depth": 3,
    "completeness": 5,
    "accuracy": 5,
    "relevance": 5
  },
  "annotator": "human",
  "annotated_at": "2026-04-05T10:00:00Z",
  "notes": "Official Python docs. Very readable and complete. Depth is only 3 because it's reference material without much 'why' explanation.",
  "language": "en",
  "has_code": true,
  "code_languages": ["python"],
  "domain": "docs.python.org",
  "tags": ["python", "asyncio", "documentation"]
}
```

______________________________________________________________________

## Storage Format

### Primary: JSONL

```
data/ml/content-quality-samples.jsonl
```

- One JSON object per line
- UTF-8 encoded
- No trailing newline after last line
- `content` field limited to first 10,000 characters (store `content_length` for full-length reference)

### Why JSONL?

| Requirement | JSONL | CSV | SQLite | Parquet |
|-------------|-------|-----|--------|---------|
| Human-readable | ✅ | ✅ | ❌ | ❌ |
| Append-friendly | ✅ | ✅ | ✅ | ❌ |
| Nested structures | ✅ | ❌ | ✅ | ✅ |
| No schema migration | ✅ | ✅ | ❌ | ✅ |
| Git-friendly (diff) | ⚠️ (line-level) | ✅ | ❌ | ❌ |
| Tooling (jq, pandas) | ✅ | ✅ | ✅ | ✅ |

JSONL is the best fit for a growing, human-inspectable dataset with nested fields.

______________________________________________________________________

## Sampling Strategy

### Sources

Samples should be drawn from content that the ingestion pipeline actually processes.
Prioritize:

1. **Official documentation** (docs.python.org, developer.mozilla.org, etc.)
1. **Technical blog posts** (realpython.com, martinfowler.com, engineering blogs)
1. **Research papers / preprints** (arxiv.org, ACL anthology)
1. **Stack Overflow answers** (high-score answers on relevant topics)
1. **Tutorial / how-to content** (medium.com/dev.to technical articles)
1. **PDFs and EPUBs** (technical books, O'Reilly chapters)
1. **Edge cases**: error pages, paywalled content, non-English, SEO spam, listicles

### Distribution Targets (v0.1)

| Label | Target Count | Percentage |
|-------|-------------|------------|
| `good` | ~15 | ~35% |
| `acceptable` | ~15 | ~35% |
| `poor` | ~13 | ~30% |

Aim for **balanced classes** to avoid a skewed classifier. Deliberately include
hard examples near label boundaries.

### Dimension Coverage

Ensure the dataset contains examples that stress each dimension:

| Dimension | Easy (5) | Medium (3) | Hard (1) |
|-----------|----------|------------|----------|
| Readability | Clean docs, well-formatted blogs | Medium articles with some noise | Raw HTML dumps, encoding errors |
| Depth | In-depth guides, RFCs | Introductory tutorials | Listicles, SEO content |
| Completeness | Full articles, books | Blog posts with minor gaps | Abstracts, stubs, truncated pages |
| Accuracy | Official docs, peer-reviewed | Blogs with minor issues | Outdated tutorials, wrong code |
| Relevance | Core domain content | Adjacent topics | Off-topic content |

### Minimum Dataset Size

| Phase | Samples | Purpose |
|-------|---------|---------|
| **v0.1 (prototype)** | **40–50** | Sanity-check scoring logic, test eval script, validate rubric. Current deliverable. |
| **v0.2 (development)** | **150–200** | Train a v1 automated scorer with reasonable coverage. |
| **v0.3 (validation)** | **500+** | Proper train/test split, measure inter-annotator agreement. |
| **v1.0 (production)** | **1000+** | Production-grade scorer with statistical significance. |

**Recommendation**: Start with 40–50 samples (v0.1), validate the rubric makes sense,
then scale to 150–200 (v0.2) for initial model training.

______________________________________________________________________

## Versioning

### Naming Convention

```
data/ml/content-quality-samples.v{VERSION}.jsonl
data/ml/content-quality-samples.jsonl          # always latest
```

### Changelog

Maintain `data/ml/CHANGELOG.md`:

```markdown
## v0.1.0 (2026-04-05)
- Initial dataset with 10 samples
- Covers: official docs, blog posts, SEO spam, paywall truncation, code-heavy content
- All labels: human (author)
```

### Semantic Versioning Rules

- **PATCH** (x.y.Z): Add or correct individual samples (typo fix, score adjustment)
- **MINOR** (x.Y.0): Add new batch of samples, extend tag coverage, add new fields
- **MAJOR** (X.0.0): Schema change (add/remove required fields), re-label existing samples, change scoring scale

### Git Tracking

- JSONL files ≤ 1 MB are tracked in git (human-reviewable)
- Files > 1 MB use Git LFS or are stored externally with a pointer file
- Every version change gets a commit with the version tag

______________________________________________________________________

## Quality Assurance

### Annotation Guidelines

1. **Read the rubric** before labeling (`docs/ml/content-quality-eval-rubric.md`)
1. **Read the full content** before scoring — don't skim
1. **Score independently** — don't look at other annotators' scores
1. **Justify in notes** — every score needs a brief explanation
1. **Use edge case guidance** — code-heavy, mixed media, truncated content have specific rules

### Inter-Annotator Agreement

Starting at v0.2, require **at least 2 annotators** for 20% of samples. Measure:

- **Cohen's kappa** per dimension (target ≥ 0.6)
- **Label agreement** for aggregate label (target ≥ 80%)
- Resolve disagreements through discussion

### Validation Script

Use `scripts/eval-content-quality.py` to:

- Validate schema conformance
- Print summary statistics (label distribution, dimension means)
- Flag samples where dimension scores don't match the aggregate label
- Detect potential annotation errors (e.g., all-5s without justification)

______________________________________________________________________

## Relationships

| Artifact | Location | Relationship |
|----------|----------|--------------|
| Eval rubric | `docs/ml/content-quality-eval-rubric.md` | Defines scoring criteria |
| Sample data | `data/ml/content-quality-samples.jsonl` | This spec's output |
| Eval script | `scripts/eval-content-quality.py` | Validates and summarizes dataset |
| Quality evaluator | `mahavishnu/ingesters/quality_evaluator.py` | Code that will consume this dataset |
| Content ingester | `mahavishnu/ingesters/content_ingester.py` | Source of content to label |
| Manual guide | `docs/CONTENT_QUALITY_EVALUATION.md` | Pre-existing evaluation guidance |
