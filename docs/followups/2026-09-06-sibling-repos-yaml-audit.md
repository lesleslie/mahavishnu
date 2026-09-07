---
status: complete
role: historical
date: 2026-09-06
last_reviewed: 2026-09-06
superseded_by: null
topic: mcp-stub-activation
---

# Sibling `repos.yaml` Audit

Opened by Plan 0a (`docs/superpowers/plans/2026-09-06-registry-manifest-migration.md`,
Task 8) to bound its own scope. `crackerjack/settings/repos.yaml` and
`mcp-common/settings/repos.yaml` exist alongside Mahavishnu's; their relationship was
unverified.

## Findings

### crackerjack/settings/repos.yaml

- **Entries:** 4 (but **not** a list of repos — see below).
- **Top-level keys:** `repos` only at first glance; `repos:` here is a **mapping** keyed by `mcp_type`, `default_branch`, `allow_forks`, and `mcp_configurations`, **not** a list.
- **Content:** Crackerjack's `repos.yaml` is a *configuration* file, not a *catalog*. It declares `mcp_type`, default branch policy, and per-MCP-integration-type timeout/retry settings. It contains zero repository entries.
- **Python readers (sample, 5 hits):** `docs/archive/session-artifacts/check_gitignore.py:39` references the file path as part of a config-file list, not as a data source.
- **Verdict for crackerjack:** Independent manifest — entirely different shape and purpose.

### mcp-common/settings/repos.yaml

- **Entries:** 1.
- **Names:** `['mahavishnu']`.
- **Top-level keys:** `repos` only.
- **Content:** A single entry registering `mahavishnu` as the orchestrator (role `orchestrator`, package `mahavishnu`, path `/Users/les/Projects/mahavishnu`). Marked `mcp: native`. Tags: `orchestration`, `multi-engine`. The description is one sentence shorter than the canonical `settings/ecosystem.yaml` entry ("Multi-engine orchestration platform" vs. "Multi-agent orchestration system").
- **Python readers:** None found in `mcp-common/**/*.py` (after excluding `.venv` and `.claude`). The file is on disk but not consumed by any module in the repo.
- **Verdict for mcp-common:** A stale, single-entry remnant — the only repo named is `mahavishnu` itself (the parent), which is already in Mahavishnu's canonical manifest with a fuller description. No Python reader consumes it.

### Summary table

| Repo | File shape | Repo entries | Read by Python code? | Disposition |
|---|---|---|---|---|
| `mahavishnu/settings/ecosystem.yaml` | list-of-dicts | 35 | yes (`mahavishnu/core/bootstrap.py:187`) | canonical |
| `mahavishnu/settings/repos.yaml` | list-of-dicts | 32 | yes (`mahavishnu/repo_cli.py`, legacy fallback `bootstrap.py:130`) | deprecated (this plan) |
| `crackerjack/settings/repos.yaml` | mapping (config) | 0 | no (only path-listed in archive script) | independent |
| `mcp-common/settings/repos.yaml` | list-of-dicts | 1 (`mahavishnu`) | no | stale remnant |

## Verdict

**Independent manifests, with one stale remnant in `mcp-common`.** Crackerjack's
file is unrelated in shape and intent. `mcp-common/settings/repos.yaml` is a
single-entry relic — it lists only `mahavishnu`, which is already in the canonical
Mahavishnu manifest with no behavioural impact (no Python reader consumes it).

## Consequence

- **crackerjack:** No migration needed. Its `repos.yaml` is a config file, not a catalog; the name collision is incidental.
- **mcp-common:** Safe to delete `settings/repos.yaml` in a follow-up PR. Until then, it is dead weight — it carries one entry pointing at the parent repo with no behavioural effect.
- **No routing risk:** Neither sibling file is read by any tool that affects which repos Mahavishnu or its workers route to. The 24-repo drift in Mahavishnu was contained to the two files inside this repo.
