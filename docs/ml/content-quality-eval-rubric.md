# Content Quality Evaluation Rubric

> **Version**: 1.0.0
> **Scope**: Mahavishnu content ingestion pipeline
> **Applies to**: All ingested content (webpages, blogs, PDFs, EPUBs, markdown, text)

## Overview

This rubric defines how ingested content is scored for quality across five dimensions.
It is designed to produce **human-labeled ground truth** for training and evaluating
automated content quality classifiers used in the Mahavishnu ingestion pipeline.

### Relationship to existing code

| Component | Location | Notes |
|-----------|----------|-------|
| `QualityMetric` enum | `mahavishnu/ingesters/quality_evaluator.py` | Defines 4 of 5 dimensions (missing *depth*) |
| `QualityEvaluator` class | `mahavishnu/ingesters/quality_evaluator.py` | Stub — always returns 1.0 |
| Manual checklist | `docs/CONTENT_QUALITY_EVALUATION.md` | 0–100 holistic score, relevance/uniqueness/quality/freshness/retrievability |
| `ContentIngester` | `mahavishnu/ingesters/content_ingester.py` | Fetch → chunk → embed → store pipeline |

This rubric refines the existing framework into a **per-dimension 1–5 scale** suitable
for labeled dataset creation and automated scoring.

---

## Dimensions

| # | Dimension | Definition | Maps to `QualityMetric` |
|---|-----------|------------|------------------------|
| 1 | **Readability** | How easily a human reader can understand the extracted text | `READABILITY` |
| 2 | **Depth** | How thoroughly the content explores its topic beyond surface-level treatment | *(new — see §Additions)* |
| 3 | **Completeness** | Whether the content is self-contained and not truncated, stub-like, or missing key sections | `COMPLETENESS` |
| 4 | **Accuracy** | Factual correctness and technical precision of claims, code, and data | `ACCURACY` |
| 5 | **Relevance** | Alignment with the knowledge base's target domains and utility for downstream RAG retrieval | `RELEVANCE` |

---

## Scoring Scale (1–5)

Each dimension is scored independently. A label is then derived from the aggregate
(see §Aggregate Labels below).

### Dimension: Readability

| Score | Label | Criteria |
|-------|-------|----------|
| **5** | Excellent | Clear sentence structure, proper grammar, logical flow. No parsing artifacts (HTML tags, nav boilerplate, cookie banners). Headings and lists used effectively. Jargon used appropriately with context. |
| **4** | Good | Generally clear prose with minor issues (occasional long sentences, slight flow awkwardness). Minimal extraction artifacts. Structured with at least some headings or sections. |
| **3** | Acceptable | Readable but effortful. May contain moderate extraction noise (footers, sidebars, repeated headers). Sentence fragments or run-on sentences present but not dominant. |
| **2** | Poor | Difficult to follow. Heavy extraction artifacts dominate the text (nav menus, cookie consent text, CSS class names). Grammar issues frequent. Lacks any structure. |
| **1** | Unusable | Giberish, encoding corruption, or nearly 100% boilerplate/nav text. No coherent prose. |

### Dimension: Depth

| Score | Label | Criteria |
|-------|-------|----------|
| **5** | Excellent | Content goes deep into the topic: explains *why*, not just *what*. Includes edge cases, trade-offs, performance implications, comparisons to alternatives. Practical examples with explanations. Suitable as a definitive reference. |
| **4** | Good | Covers topic thoroughly with substantive examples. Explains reasoning behind recommendations. May lack deep comparison or edge-case discussion but is far from superficial. |
| **3** | Acceptable | Covers the basics adequately. Describes the *what* and *how* but rarely the *why*. Examples may be present but shallow. Useful as an introduction, not a reference. |
| **2** | Poor | Very surface-level. Bullet-point lists without explanation. Copy-pasted API docs without context. "X does Y" without any elaboration. |
| **1** | Unusable | Title + 1–2 sentences only. Placeholder or stub content. Marketing tagline without substance. |

### Dimension: Completeness

| Score | Label | Criteria |
|-------|-------|----------|
| **5** | Excellent | Self-contained document with introduction, body, and conclusion. All code examples are complete and runnable. No "continued on next page" or paywall truncation. Tables and figures render as readable text. |
| **4** | Good | Mostly complete. Minor omissions (e.g., missing a single code listing or image description). Any truncation affects <10% of the content. |
| **3** | Acceptable | Core content is present but notable gaps exist. May be missing intro/outro. Some code blocks are incomplete. Paywall-visible portion only. Useful but requires external context. |
| **2** | Poor | Significantly truncated. Missing large sections. Code blocks are just function signatures without bodies. Reads like a table of contents or abstract rather than full content. |
| **1** | Unusable | Only metadata or title extracted. Body is empty or a single line. HTTP error page captured instead of content. |

### Dimension: Accuracy

| Score | Label | Criteria |
|-------|-------|----------|
| **5** | Excellent | All factual claims are correct and current. Code examples are syntactically valid and follow best practices. Data/statistics are cited. No hallucinated content. |
| **4** | Good | Minor inaccuracies (e.g., deprecated API mentioned without note, slight version mismatch). Code is valid but may use older patterns. No major factual errors. |
| **3** | Acceptable | Some inaccuracies present but content is mostly correct. Code may have minor bugs or missing imports. Claims that are technically debatable but not wrong. |
| **2** | Poor | Multiple factual errors. Outdated information presented as current. Code examples have syntax errors or wrong API usage. Misleading claims about technology. |
| **1** | Unusable | Fabricated content, completely wrong technical claims, or deliberately misleading information. Anti-patterns presented as best practices. |

### Dimension: Relevance

| Score | Label | Criteria |
|-------|-------|----------|
| **5** | Excellent | Directly addresses core knowledge base domains (software engineering, ML/AI, DevOps, security, systems design). Would be retrieved by likely user queries and add unique value. |
| **4** | Good | Primarily relevant with minor off-topic sections. Covers adjacent topics that may still be useful (e.g., a DevOps article that includes relevant Python tips). |
| **3** | Acceptable | Partially relevant. Some useful information but significant off-topic content. Would need filtering/chunking to extract value. Tangentially related to target domains. |
| **2** | Poor | Mostly irrelevant to the knowledge base. General tech news, opinion pieces without technical depth, or content from unrelated domains. |
| **1** | Unusable | Completely off-topic (e.g., recipe blog, sports news, celebrity gossip captured by URL). Adds noise to the knowledge base. |

---

## Aggregate Labels

The overall quality label is derived from the **mean** of all five dimension scores.

| Mean Score | Label | Description | Ingestion Action |
|------------|-------|-------------|-----------------|
| **4.0 – 5.0** | ✅ **Good** | High-quality content, ready for ingestion and embedding | Ingest immediately |
| **3.0 – 3.9** | ⚠️ **Acceptable** | Usable with caveats, may need cleaning or partial ingestion | Ingest with quality flag |
| **1.0 – 2.9** | ❌ **Poor** | Low quality, would degrade knowledge base | Reject or require manual review |

### Example Compositions

| Content Type | Read. | Depth | Comp. | Acc. | Rel. | Mean | Label |
|-------------|-------|-------|-------|------|------|------|-------|
| Official API reference (well-formatted) | 5 | 3 | 5 | 5 | 5 | 4.6 | Good |
| In-depth technical blog post | 4 | 5 | 4 | 4 | 5 | 4.4 | Good |
| Medium article with ads/boilerplate | 3 | 3 | 3 | 4 | 4 | 3.4 | Acceptable |
| Tutorial with broken code examples | 4 | 3 | 3 | 2 | 4 | 3.2 | Acceptable |
| SEO-optimized listicle (shallow) | 3 | 1 | 4 | 3 | 3 | 2.8 | Poor |
| Paywall-only abstract | 2 | 1 | 1 | 4 | 4 | 2.4 | Poor |
| Error page or empty extraction | 1 | 1 | 1 | 1 | 1 | 1.0 | Poor |

---

## Edge Cases

### Code-Heavy Content

Code-heavy articles (tutorials, API docs, repositories' README files) are scored on the
**prose around the code**, not on raw token count.

| Sub-dimension | Guidance |
|---------------|----------|
| Readability | Code blocks should be syntactically valid. Surrounding prose should explain the code. If only code is present (no explanation), depth ≤ 2. |
| Depth | Does the code include error handling, edge cases, comments? Or is it a minimal "hello world"? |
| Completeness | Are imports included? Is the code self-contained and runnable? Missing `import` statements reduce completeness. |
| Accuracy | Is the code syntactically correct for the stated language/version? Do claims about the code's behavior match reality? |
| Relevance | Same as general relevance. |

### Mixed Media Content

Articles with embedded images, videos, or interactive widgets are evaluated based on
the **extracted text only** (since Mahavishnu's pipeline processes text).

| Situation | Guidance |
|-----------|----------|
| Image-heavy article with alt text | Score on the alt text + captions. Note in metadata that visual content was lost. |
| Video transcript | Treat as prose. Evaluate readability of transcript (may have "um", "uh", timestamps). |
| Slide deck (PDF) | Often low completeness (bullet points without elaboration). Depth ≤ 3 unless speaker notes are included. |
| Infographic (extracted as text) | Usually scores low on all dimensions — minimal text, no depth. Completeness ≤ 2. |

### Partial Content / Truncation

| Situation | Guidance |
|-----------|----------|
| Paywall — only abstract visible | Completeness ≤ 2. Note `paywall_truncated: true` in metadata. |
| Pagination — single page of multi-page article | Completeness ≤ 2. The pipeline should ideally detect and fetch all pages. |
| "Loading…" or JavaScript-rendered content that failed | Completeness = 1. Readability = 1. All other dimensions N/A — label as Poor. |
| RSS feed snippet | Depth ≤ 1, Completeness ≤ 2. Should not be ingested as a standalone article. |

### Multilingual Content

| Situation | Guidance |
|-----------|----------|
| Non-English content | Score normally if the target knowledge base includes that language. If not, Relevance ≤ 2. |
| Code-switching (English + code) | Normal scoring — code is language-agnostic. |
| Machine-translated content | Accuracy may be reduced (2–3) depending on translation quality. Note `translation: machine` in metadata. |

---

## Integration with Existing Code

The `QualityMetric` enum in `mahavishnu/ingesters/quality_evaluator.py` currently defines:

```python
class QualityMetric(str, Enum):
    READABILITY = "readability"
    COMPLETENESS = "completeness"
    ACCURACY = "accuracy"
    RELEVANCE = "relevance"
```

**Recommended addition**: Add `DEPTH = "depth"` to align with this rubric.

The `QualityEvaluator.evaluate()` method currently returns stub scores (always 1.0).
Once labeled data is available, this class should be extended to produce real scores
that correlate with human labels (see `docs/ml/content-quality-dataset-spec.md` for
dataset details).
