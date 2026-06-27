# Source Provenance Gate (Plan 5 audit H4)

The Plan 5 distillation pipeline decides which workflow run records
are eligible to feed the LLM synthesizer. The gate lives at
`mahavishnu.distill.provenance.check_source_purity` and is wired
into the distiller pre-filter (`mahavishnu.distill.distiller.
distill_workflows`).

## Why this exists

A compromised workflow run is the entry point for poisoned
distillation. The reviewer-identity gate (H6,
`mahavishnu.distill.reviewer`) protects the reviewer side. H4
closes the other half — the *source* side — by demanding every run
record admitted into the distiller prove it came from a trusted
Mahavishnu workflow execution.

## Verdict classes (`SourcePurity`)

| Class | Meaning |
|-------|---------|
| `pure` | The record is eligible for distillation. |
| `rejected_external` | `source_type` is not `mahavishnu_workflow` (or is missing). External / unknown sources are rejected outright. |
| `rejected_unattributed` | `source_type` is trusted but `reviewer_id` is missing or empty. Attribution is required regardless of allowlist state. |
| `rejected_reviewer` | `source_type` is trusted AND a reviewer is present BUT the reviewer is not in `MAHAVISHNU_PUBLISHER_ALLOWLIST`. |

## Configuration

The gate's allowlist is sourced from either:

1. `MAHAVISHNU_PUBLISHER_ALLOWLIST` env var (path to a
   newline-delimited file, OR an inline comma-separated list).
2. `distill.publisher_allowlist` in `settings/mahavishnu.yaml`.

When both are configured the env var wins (matches the H6 reviewer
gate). When neither is set the gate enters **bootstrap mode** — any
mahavishnu_workflow record with ANY reviewer identity is accepted
(WARNING + audit log entry). Operators should configure an allowlist
before promoting distillers out of single-tenant development.

### Example `settings/mahavishnu.yaml`

```yaml
distill:
  publisher_allowlist: settings/distill_publishers.txt
  evidence_threshold: 3
  require_reviewer: true
```

### Example env-var allowlist file

```
# settings/distill_publishers.txt
alice
bob
```

### Environment variable overrides

```bash
MAHAVISHNU_DISTILL__PUBLISHER_ALLOWLIST=/etc/mahavishnu/publishers.txt
MAHAVISHNU_DISTILL__EVIDENCE_THRESHOLD=5
MAHAVISHNU_DISTILL__REQUIRE_REVIEWER=true
```

## How the distiller uses it

```python
from mahavishnu.distill.distiller import distill_workflows

distill_workflows(
    conn,
    reviewer=ReviewerIdentity.from_env(),       # H6 gate
    reviewer_allowlist=frozenset({"alice"}),   # H4 gate
)
```

The distiller calls `_find_session_run_record(conn, session_id)` for
each candidate session, then `check_source_purity(run_record,
allowlist=reviewer_allowlist)`. Records that fail the gate are
logged at WARNING level (with `extra={"audit": True}`) and skipped.
The distiller's per-candidate isolation contract is preserved — one
rejection does NOT abort the pass.

## Forensic visibility

Every rejection is logged with:

- `session_id`
- `purity` (one of the four `SourcePurity` values)
- `reason` (human-readable explanation)
- `reviewer_id`, `source_type` (echoed for forensics)

Use the audit log subscriber (Dhara event bus) to ingest these
events into your SIEM.

## Tests

- `tests/unit/test_distill_provenance.py` — gate contract (11 tests)
- `tests/unit/test_distill_provenance_wired.py` — distiller wiring (7 tests)

Both run green. The gate is a pure function with no side effects; it
is safe to call directly from any caller that has a run record at
hand (not just the distiller).
