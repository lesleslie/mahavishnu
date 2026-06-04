# Removed Scripts — `required_scripts:` policy

One-line summary: documents the policy for handling `required_scripts:`
references in tool command frontmatter, and the current set of scripts
that are intentionally not committed.

## Background

A `required_scripts:` reference in a tool command's frontmatter
promises a future LLM that a script exists at the path given. If the
script isn't committed, the promise is broken — the tool will fail at
runtime. This document records scripts referenced from `required_scripts:`
blocks in tool command frontmatter that are not committed, and the
policy for handling such references.

## Scripts that stay removed

| Script | Reason | Revisit when |
|--------|--------|--------------|
| `scripts/dependency_report.py` | Defer. A thin wrapper around `pip-audit` / `osv-scanner` would suffice if needed. | Revisit when a CVE-feed integration is added to the project. |
| `scripts/release_checklist.py` | Defer. Release checklists are repo-context summaries that the LLM can generate from `git log` and `pyproject.toml` on demand; a pre-built script would freeze the checklist shape and rot against repo changes. | Revisit when a release-process automation needs stable, versioned inputs. |
| `scripts/privacy_matrix.py` | Permanently removed. Privacy classification requires legal/policy review on a case-by-case basis; a generic script would produce a false sense of authority. | Never. Reclassifying a script's authority would require human sign-off. |
| `scripts/support_health.py` | Permanently removed. No ticketing data source available to query. | Revisit when a real ticketing integration (Zendesk, Intercom, etc.) is added. |
| `scripts/telemetry_audit.py` | Defer. Needs a stable SLO contract first; scope is larger than it looks. | Revisit when SLO contracts land in `settings/slo.yaml`. |

## Script being added

| Script | Scope | Consumers |
|--------|-------|-----------|
| `scripts/test_matrix.py` | Test coverage matrix generator | `.claude/commands/tools/development/testing/quality-validation.md`, `.claude/commands/tools/development/testing/test-harness.md` |

The `required_scripts:` reference has been added back to those two tool commands now that the script is committed.

## Decision rule

Do not add speculative `required_scripts:` entries to tool command frontmatter. Either:

1. Implement the script (committed to `scripts/`, runnable today), or
2. Leave the reference out.

An empty list `required_scripts: []` is acceptable and means
"no required scripts"; only non-empty lists pointing at uncommitted
scripts are forbidden by this policy.

A `required_scripts:` entry pointing at a non-existent file is a bug, not a TODO.
