# Dogfood golden set — v0

`dogfood-v0.jsonl` is the first golden set for Mahavishnu's
model-evaluation framework: 29 questions about how Mahavishnu actually
behaves, each with the phrase a correct answer must contain.

This file describes the file's format and how to add to it. For the
why and the operating procedure, see [DOGFOOD.md](DOGFOOD.md).

## Format

One JSON object per line (JSONL — the format the
`mahavishnu.jsonl` dataset loader reads):

```json
{
  "id": "pool-selector-latency",
  "input": "In Mahavishnu, a workflow must be routed to the pool ...",
  "expected": "least_loaded",
  "metadata": {
    "added_by": "les",
    "failure_mode": "routing an ad-hoc task to a saturated pool",
    "last_reviewed": "2026-11-06"
  }
}
```

| Field | Meaning |
|-------|---------|
| `id` | Stable, kebab-case identifier. Never reused, never renamed — the id is what a run's `case_results` reference. |
| `input` | The question, phrased so a model can answer it without the repository open. Name the tool, the flag, or the setting explicitly. |
| `expected` | The phrase a correct answer must **contain**. Not the whole answer — the answer to "which selector minimizes latency?" is a sentence, and the gradeable part is `least_loaded`. |
| `metadata.added_by` | Who wrote the case. |
| `metadata.failure_mode` | One line: the mistake this case is meant to catch. A case with no plausible failure mode is not worth its runtime. |
| `metadata.last_reviewed` | ISO date the case was last checked against the current codebase. |

## Scoring

The set is scored with the `mahavishnu.contains` scorer by default. It
checks that the model's output contains `expected`, case-insensitively.
Use `mahavishnu.exact_match` only for cases whose answer is a single
exact token.

## Adding a case

1. Write the question so it stands alone. "Given a repo with tags
   `['backend', 'python']` and a query 'refactor the API layer', which
   adapter should Mahavishnu route this to?" is answerable; "which
   adapter?" is not.
1. Choose the *shortest* phrase that a wrong answer would not contain.
   `least_loaded` is gradeable; "the least-loaded pool selector" is not,
   because a model that says "round robin is often better" would fail
   it for the right reason but a model that says "least_loaded" for the
   wrong reason would pass.
1. Record the failure mode. This is the field that keeps the set
   honest when it grows.
1. Set `last_reviewed` to today.

Then run the freshness check and the suite:

```bash
pytest tests/integration/test_dogfood_freshness.py -v
mahavishnu eval run-suite --suite docs/eval/dogfood-v0.jsonl \
    --scorers mahavishnu.contains
```

## Removing a case

Delete the line. Do not leave it commented out — the loader counts
every non-empty line as a case, and a commented case that still scores
is a case nobody reads.

## Versioning

The filename carries a version (`v0`). When the set changes
substantially — cases rewritten, scorers changed, more than a handful
added — bump the version and keep the old file, so a report can be
traced back to the set that produced it.
