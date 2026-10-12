---
status: active
role: implementation
kind: plan
date: 2026-10-12
last_reviewed: 2026-10-12
superseded_by: null
blocks_on: []
topic: mcp-tool-profile-ecosystem-doc
title: "Generate docs/ecosystem/MCP_TOOL_PROFILES.md (W4 cross-cutting deliverable)"
---

# Generate `docs/ecosystem/MCP_TOOL_PROFILES.md` (W4 cross-cutting deliverable)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the W4 cross-cutting deliverable from `2026-08-18-mcp-tool-profile-adoption.md` — generate the operator-facing summary doc at `docs/ecosystem/MCP_TOOL_PROFILES.md` describing the per-repo `apply_tool_profile` wiring, the env-var convention, and the mandatory_groups per profile. Verified 2026-10-12: the file is MISSING and the `docs/ecosystem/` directory itself does not exist.

**Architecture:** The doc is a hand-written markdown summary cross-referenced from each adopter repo's `mcp/tools/profiles.py`. Generation is mechanical: 17 adopter repos each have a `PROFILES` dict and a `_register_*_tools` function. The doc presents the cross-repo summary in a single table; the per-repo detail lives in each repo's `profiles.py`.

**Tech Stack:** Markdown, optional `crackerjack` gate (not strictly needed for a doc-only change).

## Global Constraints

- `from __future__ import annotations` is N/A for markdown.
- File encoding: UTF-8, LF line endings, single trailing newline.
- No version bumps (per `feedback-mcp-common-version-bump-is-user.md`).
- No `Co-Authored-By` trailer (per `feedback-no-claude-code-coauthor-attribution.md`).
- Use `user.email="les@wedgwoodwebworks.com"` for any commits.

## Phase 1 — Inventory the cross-repo surface

- [ ] From each of the 17 adopter repos, read the top of `mcp/tools/profiles.py` to extract the per-repo `PROFILES` dict (or equivalent) and the `MAHAVISHNU_TOOL_PROFILE`-style env var
  - [ ] `/Users/les/Projects/mahavishnu/mahavishnu/mcp/tools/profiles.py`
  - [ ] `/Users/les/Projects/session-buddy/session_buddy/mcp/tools/profiles.py`
  - [ ] `/Users/les/Projects/akosha/akosha/mcp/tools/profiles.py`
  - [ ] `/Users/les/Projects/crackerjack/crackerjack/mcp/tools/profiles.py`
  - [ ] `/Users/les/Projects/graphics-mcp/` (Tier-B; has `apply_tool_profile` per the W3 verification)
  - [ ] `/Users/les/Projects/langsmith-mcp/`
  - [ ] `/Users/les/Projects/synxis-crs-mcp/`
  - [ ] `/Users/les/Projects/unifi-mcp/`
  - [ ] `/Users/les/Projects/css-mcp/` (Tier-A)
  - [ ] `/Users/les/Projects/excalidraw-mcp/`
  - [ ] `/Users/les/Projects/neo4j-mcp/`
  - [ ] `/Users/les/Projects/penpot-api-mcp/`
  - [ ] `/Users/les/Projects/porkbun-dns-mcp/`
  - [ ] `/Users/les/Projects/porkbun-domain-mcp/`
  - [ ] `/Users/les/Projects/raindropio-mcp/`
  - [ ] `/Users/les/Projects/synxis-pms-mcp/`
  - [ ] `/Users/les/Projects/mailgun-mcp/`
  - [ ] `/Users/les/Projects/opera-cloud-mcp/`
  - [ ] `/Users/les/Projects/spline-mcp/`
  - [ ] `/Users/les/Projects/fastblocks/`
  - [ ] `/Users/les/Projects/splashstand/`
  - [ ] `/Users/les/Projects/mcp-common/` (the substrate where the helper lives)

- [ ] Capture per repo: env var name, default profile, mandatory groups, registration shape

## Phase 2 — Author the doc

Create `/Users/les/Projects/mahavishnu/docs/ecosystem/MCP_TOOL_PROFILES.md` with this structure:

```markdown
# MCP Tool Profiles — Bodai Ecosystem Reference

> Generated 2026-10-12 against the 17 adopter repos that have
> `apply_tool_profile()` wired. Source of truth: each repo's
> `mcp/tools/profiles.py`; this file is a hand-curated summary, not
> auto-generated.

## Convention

Each Bodai MCP server reads a single env var to select its tool profile:

| Repo | Env var | Default | Profiles |
|---|---|---|---|
| ... (one row per repo) |

## Per-profile mandatory groups

| Profile | Mandatory groups | Why |
|---|---|---|
| `full` | ... | (default for development) |
| `standard` | ... | (default for production CLI deployments) |
| `minimal` | ... | (default for tight-budget serverless deployments) |

## How to override

| Need | Env var | Effect |
|---|---|---|
| Disable optional tools | `<REPO>_TOOL_PROFILE=standard` | ... |
| Force minimal | `<REPO>_TOOL_PROFILE=minimal` | ... |

## How to add a new tool to a profile

...

## Source-of-truth links

| Repo | profiles.py |
|---|---|
| ... | ... |
```

## Phase 3 — Cross-link from each adopter repo

- [ ] From each adopter repo's `mcp/tools/profiles.py` docstring, add: "See the cross-ecosystem reference at `https://github.com/lesleslie/mahavishnu/blob/main/docs/ecosystem/MCP_TOOL_PROFILES.md`." (or the in-repo equivalent path if Bodai uses a vendored doc).
- [ ] This is a one-line addition per repo (17 repos).

## Phase 4 — Verification

- [ ] `docs/ecosystem/MCP_TOOL_PROFILES.md` exists and is well-formed markdown
- [ ] Every row in the per-repo table references a file that exists on disk
- [ ] `rg -n "MCP_TOOL_PROFILES" mahavishnu/ --type py` returns at least 1 hit (the cross-link from the new doc back to the helper)
- [ ] `crackerjack run -v` (or at minimum `ruff format --check` on the new doc) clean

## Phase 5 — Commit

- [ ] Single commit on `main` (mahavishnu repo) with message: `docs(ecosystem): generate MCP_TOOL_PROFILES.md (W4 cross-cutting deliverable)`
- [ ] Use `git -c user.email="les@wedgwoodwebworks.com" commit ...`
- [ ] Do NOT add `Co-Authored-By` trailer
- [ ] Do NOT push

## Phase 6 — Mark the parent plan shipped

- [ ] After this plan lands, edit `2026-08-18-mcp-tool-profile-adoption.md` frontmatter:
  - `status: active` → `status: shipped`
  - `last_reviewed: 2026-09-13` → `last_reviewed: 2026-10-12`
- [ ] Regen `docs/plans/PLAN_INDEX.md` to reflect the new state

## Rollback signal

If any per-repo cross-link is wrong, the rollback is per-repo: remove the cross-link line from that repo's `mcp/tools/profiles.py` docstring. The central doc itself can be regenerated from the same Phase 1 inventory.

## Observability added

- N/A (doc-only change; no runtime behavior change)

## Cross-references

- `docs/plans/2026-08-18-mcp-tool-profile-adoption.md` (active) — the parent plan
- `mcp-common/mcp_common/tools/dispatch.py` — the `apply_tool_profile` helper (source of truth for the cross-repo contract)
- `feedback-keep-plan-files-tracked.md` — the memory note: stage the new doc before any subsequent `git reset`/`git clean -fd` runs
