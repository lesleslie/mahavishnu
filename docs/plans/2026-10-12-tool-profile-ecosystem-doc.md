---
status: active
role: implementation
kind: plan
date: 2026-10-12
last_reviewed: 2026-10-12
superseded_by: null
blocks_on: []
topic: mcp-tool-profile-ecosystem-doc
title: "Generate docs/ecosystem/MCP_TOOL_PROFILES.md via scripts/generate_tool_profiles_doc.py"
---

# Generate `docs/ecosystem/MCP_TOOL_PROFILES.md` via `scripts/generate_tool_profiles_doc.py`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the W4 cross-cutting deliverable from `2026-08-18-mcp-tool-profile-adoption.md` — produce the operator-facing summary doc at `docs/ecosystem/MCP_TOOL_PROFILES.md` describing the per-repo `apply_tool_profile` wiring, the env-var convention, and the mandatory groups per profile. The original draft proposed a hand-curated markdown table; the parent spec (`docs/specs/2026-08-18-mcp-tool-profile-adoption-design.md:306`) explicitly says the doc should be "Generated from `mcp.list_tools()` programmatically" and cites the `docs-audit-mcp-tool-hallucination` memory rule against hand-maintained tool counts. This plan aligns with the parent: a small generator script in `scripts/generate_tool_profiles_doc.py` walks the verified adopter repos, extracts their `apply_tool_profile` wiring, and writes the markdown. The doc is regenerated on every script run; no manual edits to the markdown.

**Architecture:** The script is a one-pass walk over a list of known adopter repos. For each, it reads the repo's `mcp/tools/profiles.py` (or equivalent) and extracts: the env var name (look for `MAHAVISHNU_TOOL_PROFILE` / `AKOSHA_TOOL_PROFILE` / etc.), the default profile (`ToolProfile.FULL` or similar), and the mandatory groups. The output is a markdown file with three sections: the per-repo table, the per-profile mandatory groups table, and the "how to override" / "how to add a new tool" reference.

**Tech Stack:** Python 3.14, stdlib (`re`, `pathlib`, `ast`), `crackerjack run -v` gate, no new dependencies.

## Why the original draft's 17-repos + hand-curated approach was rejected

Three structural issues with the original draft:

1. **Count drift** — the plan text said "17 adopter repos" but Phase 1 listed 22 paths; agent-verified the actual count is 19 MCP-server adopters (4 Tier-A core Bodai + 15 Tier-B MCP servers). Per `docs-audit-mcp-tool-hallucination`, hand-maintained counts drift; the fix is to generate from the actual code.
2. **Wrong inclusion of `mcp-common`** — `mcp_common.tools.dispatch.apply_tool_profile` is the helper itself, not a consumer. The doc would mis-label it as an adopter. The right move is a separate "substrate" callout section, not a per-repo table row.
3. **Wrong inclusion of `fastblocks` / `splashstand`** — per `feedback-no-bodai-mentions-in-mcp-repos` memory, FastBlocks apps are not Bodai ecosystem members. They have `profiles.py` for FastBlocks framework reasons, not Bodai wiring.

The original draft's "this file is a hand-curated summary" claim directly contradicts the parent spec's "Generated from `mcp.list_tools()` programmatically" directive and reproduces the exact failure mode the parent spec warns against.

## Global Constraints

- `from __future__ import annotations` first non-comment line of every new Python module.
- Ruff line length 100; per-file ignores in `pyproject.toml` apply unchanged.
- mypy strict; `X | None` (not `Optional[X]`), `list[str]` (not `List[str]`), `pathlib.Path`.
- No `assert` in production code. Use `mahavishnu/core/errors.py` exception hierarchy.
- In `except` blocks, use `logger.exception(...)`, never `logger.error(..., exc_info=True)`.
- File encoding: UTF-8, LF line endings, single trailing newline.
- No version bumps (per `feedback-mcp-common-version-bump-is-user.md`).
- No `Co-Authored-By` trailer (per `feedback-no-claude-code-coauthor-attribution.md`).
- Use `user.email="les@wedgwoodwebworks.com"` for any commits.

## Phase 1 — Inventory: grep-based verification of adopter count

- [ ] Run `python -c "import os; [print(p) for p in sorted(os.listdir('/Users/les/Projects'))]"` to enumerate the actual on-disk repos. The verified adopter set (per 2026-10-12 review) is:
  - Tier-A core Bodai (4): `mahavishnu`, `session-buddy`, `akosha`, `crackerjack`
  - Tier-B MCP servers (15): `graphics-mcp`, `langsmith-mcp`, `synxis-crs-mcp`, `unifi-mcp`, `css-mcp`, `excalidraw-mcp`, `neo4j-mcp`, `penpot-api-mcp`, `porkbun-dns-mcp`, `porkbun-domain-mcp`, `raindropio-mcp`, `synxis-pms-mcp`, `mailgun-mcp`, `opera-cloud-mcp`, `spline-mcp`
  - Tier-C MCP servers (5, under construction — listed for completeness but excluded from the 19-adopter count until they wire `apply_tool_profile`): `archive-org-mcp`, `chat-bridge-mcp`, `cmux-mcp`, `medium-mcp`, `scapy-mcp`
  - **NOTE (2026-10-13 verification):** the prior draft listed `cmux-cua-mcp` — the actual dir on disk is `cmux-mcp` (Les's own cmux-mcp, owned by `les@wedgwoodwebworks.com`, with `oneiric>=0.21.0` and `mcp-common>=0.30.0` deps). This is a Bodai-managed `*-mcp` server (not third-party) — when it wires `apply_tool_profile` (per the separate `2026-10-13-bodai-maintained-mcp-promotion.md` plan), it should move from Tier-C to a new "Bodai-maintained `*-mcp`" subcategory. The cross-link policy (Tier-A links to the doc; Tier-B doesn't per `feedback-no-bodai-mentions-in-mcp-repos`) extends to "Bodai-maintained" too.
  - **Total: 19 active adopter repos.** (Do not include `mcp-common` — that's the substrate where the helper lives. Do not include `fastblocks` / `splashstand` — those are FastBlocks apps, not Bodai members per `feedback-no-bodai-mentions-in-mcp-repos`. Tier-C is excluded because they don't yet have `apply_tool_profile` wired — re-verify at next regeneration.)
- [ ] For each of the 19 active adopter repos, verify `apply_tool_profile` is actually called: `rg "apply_tool_profile" <repo_path>/<package>/mcp/tools/profiles.py`. The hit count is the per-repo evidence; a repo with 0 hits is NOT an adopter and gets dropped from the table.
- [ ] The verification step is the source of truth. The 19-repo list is the upper bound; the actual adopter count is `len([r for r in 19_repos if rg hit > 0])`. If the actual count is < 19, the generator must reflect that.
- [ ] **Special case: `medium-mcp`** is listed in Tier-C but verified 2026-10-12 to have an orphan `from dhara.lock.in_memory import InMemoryDharaLock` import in `medium_mcp/dhara/client.py:7`. This import will break once `dhara/dhara/lock/` is deleted (per the companion `2026-10-12-dhara-lock-delete.md` plan). Either (a) move medium-mcp to Tier-C with an explicit "blocking on dhara-lock-delete" note, or (b) ensure the medium-mcp import is migrated to `mahavishnu.core._lock_sentinel.Lock` before this plan's Phase 1 completes. The second-round re-review (mcp-integration-expert) flagged this.

#### Integration Contract ← REQUIRED
- **Triggered from**: developer / agent running the inventory before writing the generator.
- **Returns to / updates**: a confirmed adopter list (path + per-repo grep hit count).
- **Demonstrable by**: the inventory output is logged to stdout and saved to `/tmp/mcp_tool_profile_inventory.json` for the generator to consume in Phase 2.
- **Rollback signal**: not applicable — Phase 1 is read-only.
- **Observability added**: `mcp_tool_profile_inventory_verified` (info) emitted with the final count.

## Phase 2 — Build `scripts/generate_tool_profiles_doc.py`

- [ ] Create `scripts/generate_tool_profiles_doc.py` with `from __future__ import annotations` as the first non-comment line.
- [ ] The script takes `--output-path` (default `docs/ecosystem/MCP_TOOL_PROFILES.md`) and `--inventory-path` (default `/tmp/mcp_tool_profile_inventory.json`) CLI args. If `--inventory-path` doesn't exist, Phase 1 is re-run inline.
- [ ] For each adopter repo in the inventory, the script:
  1. Reads the `mcp/tools/profiles.py` file (relative to the repo path).
  2. Uses `ast` to parse the file and extract: (a) the env var name (look for `os.environ.get(...)` or `MAHAVISHNU_TOOL_PROFILE` style references), (b) the default profile (look for `ToolProfile.FULL` or similar), (c) the mandatory groups dict.
  3. Falls back to a regex scan if `ast` parsing fails (the file is dynamic — some repos use a `MANDATORY_GROUPS` constant, others use a class method).
- [ ] The script writes the markdown with this structure:
  ```markdown
  # MCP Tool Profiles — Bodai Ecosystem Reference

  > Generated YYYY-MM-DD by `scripts/generate_tool_profiles_doc.py` against the 19 adopter repos that have `apply_tool_profile()` wired. Source of truth: each repo's `mcp/tools/profiles.py`; this file is regenerated on every script run — do not edit by hand.

  ## Substrate

  `mcp_common.tools.dispatch.apply_tool_profile` is the canonical helper. The 19 adopter repos below all call it from their `mcp/server.py` (or equivalent) startup path.

  ## Per-repo wiring

  | Repo | Env var | Default | Mandatory groups |
  |---|---|---|---|
  | ... | ... | ... | ... |

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

  1. Add the tool to the appropriate group in `<repo>/<package>/mcp/tools/<group>.py`.
  2. Add the group to `STANDARD_REGISTRATIONS` or `FULL_REGISTRATIONS` in the repo's `mcp/tools/profiles.py`.
  3. Re-run `python scripts/generate_tool_profiles_doc.py` to refresh this file.
  ```
- [ ] Add a unit test `tests/unit/scripts/test_generate_tool_profiles_doc.py` that runs the script against a fixture inventory (3-4 fake repos) and asserts the output markdown matches an expected snapshot.

#### Integration Contract ← REQUIRED
- **Triggered from**: developer / agent running `python scripts/generate_tool_profiles_doc.py` (or `crackerjack docs regen` if a wrapper is added later).
- **Returns to / updates**: a new script at `scripts/generate_tool_profiles_doc.py` and a new test at `tests/unit/scripts/test_generate_tool_profiles_doc.py`.
- **Demonstrable by**: `python scripts/generate_tool_profiles_doc.py --output-path /tmp/test.md` produces a non-empty markdown file with the expected section headers.
- **Rollback signal**: import error on `from pathlib import Path`; the script raises on a missing `--output-path` directory.
- **Observability added**: `mcp_tool_profile_doc_generated` (info) with the per-repo row count.

## Phase 3 — Run the generator

- [ ] Run `python scripts/generate_tool_profiles_doc.py` and write the output to `docs/ecosystem/MCP_TOOL_PROFILES.md`.
- [ ] Verify the output: `head -50 docs/ecosystem/MCP_TOOL_PROFILES.md` shows the expected preamble + substrate callout; `grep -c "^|" docs/ecosystem/MCP_TOOL_PROFILES.md` matches the expected row count (per-repo table + per-profile table + override table).
- [ ] Verify the per-repo row count matches the Phase 1 inventory (the `len(adopters)` rows). If the script emits 17 rows when the inventory has 19, that's a bug.
- [ ] Confirm `docs/ecosystem/` did not exist before (verified 2026-10-12 — it didn't) and now does, with the markdown file tracked.

#### Integration Contract ← REQUIRED
- **Triggered from**: Phase 2 (the script).
- **Returns to / updates**: a new tracked markdown at `docs/ecosystem/MCP_TOOL_PROFILES.md`.
- **Demonstrable by**: `head -50 docs/ecosystem/MCP_TOOL_PROFILES.md` shows the expected output; `wc -l` reports > 0 lines.
- **Rollback signal**: `docs/ecosystem/MCP_TOOL_PROFILES.md` is empty; the script failed silently.
- **Observability added**: `mcp_tool_profile_doc_written` (info) with the file path and line count.

## Phase 4 — Cross-link from each adopter repo (tier-aware)

- [ ] For each of the 4 Tier-A adopter repos (`mahavishnu`, `session-buddy`, `akosha`, `crackerjack`): add a one-line reference at the top of `mcp/tools/profiles.py`'s docstring:
  ```python
  # See the cross-ecosystem reference at
  # https://github.com/lesleslie/mahavishnu/blob/main/docs/ecosystem/MCP_TOOL_PROFILES.md
  ```
  (Or the in-repo equivalent path if Bodai uses a vendored doc.) Tier-A repos are explicitly allowed to mention Mahavishnu per `feedback-no-bodai-mentions-in-mcp-repos`.
- [ ] For each of the 15 Tier-B adopter repos (`graphics-mcp` through `spline-mcp`): **do NOT** link to a `github.com/lesleslie/mahavishnu` URL — that violates `feedback-no-bodai-mentions-in-mcp-repos` (the Tier-B `*-mcp` repos are not Bodai ecosystem members and must not mention Bodai/Vishnu/Mahavishnu component names). The Tier-B approach is: each Tier-B repo's own `profiles.py` docstring is the source of truth for that repo's profile surface; the cross-ecosystem doc is **only referenced from Tier-A repos and from a new "Bodai Tool Profile Reference" section in `mahavishnu/CLAUDE.md`** (which is already Tier-A and may mention Mahavishnu). The second-round re-review (mcp-integration-expert) flagged this.
- [ ] This is 4 Tier-A edits (one per Tier-A adopter) + 1 `CLAUDE.md` edit in `mahavishnu/`. The 15 Tier-B repos are intentionally cross-link-free.
- [ ] Each per-repo commit uses `git -c user.email="les@wedgwoodwebworks.com"` and does NOT add a `Co-Authored-By` trailer (per `feedback-no-claude-code-coauthor-attribution.md`).
- [ ] This is 19 single-line edits — one per adopter repo. Each edit is mechanical and reversible.

#### Integration Contract ← REQUIRED
- **Triggered from**: developer / agent applying the 19 cross-link edits.
- **Returns to / updates**: 19 `mcp/tools/profiles.py` files gain a one-line cross-link.
- **Demonstrable by**: `rg "MCP_TOOL_PROFILES.md" <each-adopter-repo>/<package>/mcp/tools/profiles.py` returns exactly 1 hit per adopter.
- **Rollback signal**: a per-repo `git diff` shows the line was added correctly; a 0-hit per-repo is a missed edit.
- **Observability added**: none.

## Phase 5 — Add a CI gate against doc drift

- [ ] Add a `pytest` test at `tests/unit/test_tool_profile_doc.py` that:
  1. Runs `python scripts/generate_tool_profiles_doc.py` (via subprocess in a tmpdir).
  2. Reads the generated `docs/ecosystem/MCP_TOOL_PROFILES.md`.
  3. Asserts the per-repo row count matches the inventory count (catches inventory-vs-doc drift).
  4. Asserts the substrate callout for `mcp-common` is present and is NOT in the per-repo table.
  5. Asserts no Tier-B repo's `mcp/tools/profiles.py` docstring contains a `github.com/lesleslie/mahavishnu` URL (catches `feedback-no-bodai-mentions-in-mcp-repos` violations).
- [ ] **Use `pytest`, not a `crackerjack` hook.** Per `feedback-crackerjack-hooks-not-pre-commit.md` and the parent spec's CI-guard pattern at line 317, hooks typically run on PreToolUse/PostToolUse events, not as state checks. A `pytest` test integrates with `crackerjack run` automatically and matches the existing pattern at `tests/unit/test_wiring.py::test_apply_tool_profile_called`.
- [ ] The test is added to `crackerjack`'s existing test surface (or a new file under `tests/unit/` if no such surface exists). Per `feedback-no-bodai-mentions-in-mcp-repos`, the test must NOT add a `mcp-common` row to the per-repo table — it's the substrate, not an adopter.

#### Integration Contract ← REQUIRED
- **Triggered from**: CI run (and developer local `crackerjack run`).
- **Returns to / updates**: a new doc-drift check in the project's test/hook surface.
- **Demonstrable by**: editing `docs/ecosystem/MCP_TOOL_PROFILES.md` by hand and running the hook — the test fails with a clear "regenerate via the script" message.
- **Rollback signal**: a real adopter change (Phase 4) generates an intentional diff; the hook treats it as drift and fails — operator must re-run the script.
- **Observability added**: `mcp_tool_profile_doc_drift_detected` (warning) when the hook fails.

## Phase 6 — Mark the parent plan shipped

- [ ] After this plan lands, edit `2026-08-18-mcp-tool-profile-adoption.md` frontmatter:
  - `status: active` → `status: shipped`
  - `last_reviewed: 2026-09-13` → `last_reviewed: 2026-10-12`
- [ ] Regen `docs/plans/PLAN_INDEX.md` to reflect the new state.
- [ ] This is a separate commit from the generator + cross-links — it's the parent-plan promotion, semantically distinct.

#### Integration Contract ← REQUIRED
- **Triggered from**: developer / agent after the generator lands.
- **Returns to / updates**: `2026-08-18-mcp-tool-profile-adoption.md` frontmatter flips; `PLAN_INDEX.md` regens.
- **Demonstrable by**: `rg "status: shipped" docs/plans/2026-08-18-mcp-tool-profile-adoption.md` returns 1 hit; `python -m crackerjack.tools.plan_index_sync` produces a new index.
- **Rollback signal**: PLAN_INDEX regen reports a frontmatter validation error.
- **Observability added**: none.**

## Phase 7 — Commit

- [ ] Two commits on `main` (mahavishnu repo):
  - Commit 1: `docs(ecosystem): generate MCP_TOOL_PROFILES.md via scripts/generate_tool_profiles_doc.py` (the generator + the new doc + 1 cross-link in mahavishnu's own profiles.py)
  - Commit 2: `docs(plans): mark W4 MCP tool profile parent plan shipped` (the parent promotion)
- [ ] For each commit, use `git -c user.email="les@wedgwoodwebworks.com" commit ...` (per `git-author-email-correct-domain.md`)
- [ ] Do NOT add `Co-Authored-By` trailer (per `feedback-no-claude-code-coauthor-attribution.md`)
- [ ] Do NOT push (per `feedback-bodai-push-is-user-controlled.md`)

## Rollback signal

If Phase 5's CI gate (or any Phase 1-5 verification) fails:
- Revert the relevant commit
- The script and doc are restored to the pre-rewrite state
- The 19 cross-link edits to adopter repos are NOT in this commit — they're per-repo commits in each adopter repo, so the rollback is per-repo

If the parent-plan promotion (Phase 6) is wrong: revert Commit 2; Commit 1's generator stays.

## Observability added

- `mcp_tool_profile_inventory_verified` (info) — Phase 1 final count
- `mcp_tool_profile_doc_generated` (info) — Phase 2 script output
- `mcp_tool_profile_doc_written` (info) — Phase 3 file written
- `mcp_tool_profile_doc_drift_detected` (warning) — Phase 5 CI gate failure

## Cross-references

- `docs/plans/2026-08-18-mcp-tool-profile-adoption.md` (active) — the parent plan this closes (W4)
- `docs/specs/2026-08-18-mcp-tool-profile-adoption-design.md:306` — the spec directive to "Generate from `mcp.list_tools()` programmatically" (the parent of the parent)
- `mcp-common/mcp_common/tools/dispatch.py:269` — the canonical `apply_tool_profile` helper
- `feedback-no-bodai-mentions-in-mcp-repos` — the memory rule that excludes `fastblocks` / `splashstand` from the adopter list
- `docs-audit-mcp-tool-hallucination` — the memory rule that motivates programmatic generation over hand-maintained tables
- `feedback-keep-plan-files-tracked.md` — the memory note: stage the new doc before any subsequent `git reset` / `git clean -fd` runs
- `feedback-bodai-push-is-user-controlled.md` — push policy
- `feedback-no-claude-code-coauthor-attribution.md` — commit message policy
- `git-author-email-correct-domain.md` — author email policy
