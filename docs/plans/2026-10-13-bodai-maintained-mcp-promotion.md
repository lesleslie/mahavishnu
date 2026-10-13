---
status: active
role: implementation
kind: plan
date: 2026-10-13
last_reviewed: 2026-10-13
superseded_by: null
blocks_on: []
# Sequencing note: this plan is independent of the 2026-10-12
# post-regrowth plans. The per-repo work (add apply_tool_profile
# wiring in cmux-mcp and chat-bridge-mcp) is per-repo; the
# cross-repo doc update is in the companion tool-profile-ecosystem-doc
# plan (Phase 4 cross-link and Phase 1 inventory).
topic: bodai-maintained-mcp-promotion
title: "Promote Bodai-maintained *-mcp servers to active adopters (cmux-mcp + chat-bridge-mcp)"
---

# Promote Bodai-maintained `*-mcp` servers to active adopters

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `apply_tool_profile()` in the 2 Bodai-managed `*-mcp` servers that are currently missing it (`cmux-mcp` and `chat-bridge-mcp`), so they become active 19-adopter contributors in the cross-ecosystem tool-profile doc (`docs/ecosystem/MCP_TOOL_PROFILES.md` from the `2026-10-12-tool-profile-ecosystem-doc.md` plan). This creates a "Bodai-maintained `*-mcp`" subcategory in the doc — distinct from Tier-A (4 core Bodai: mahavishnu, session-buddy, akosha, crackerjack) and Tier-B (15 third-party MCP servers) — that allows the cross-link to the cross-ecosystem doc without violating `feedback-no-bodai-mentions-in-mcp-repos`. Both repos are owned by `les@wedgwoodwebworks.com` and have explicit `mcp-common` + (transitive) `oneiric` deps; the only thing missing is the `apply_tool_profile` call.

**Architecture:** The work is 2 per-repo `apply_tool_profile` wirings + 1 cross-ecosystem doc update (in the companion plan). Per-repo wiring mirrors the existing Tier-B pattern at e.g. `graphics-mcp/graphics_mcp/mcp/tools/profiles.py` — a `REGISTRATION_MAP`-style dispatch + the `STANDARD_REGISTRATIONS` / `FULL_REGISTRATIONS` lists. The cross-ecosystem doc update is in Phase 1 (inventory) and Phase 4 (cross-link) of the tool-profile-ecosystem-doc plan.

**Why is cmux-mcp "Bodai-maintained" rather than third-party?** Verified 2026-10-13:
- Git remote: `https://github.com/lesleslie/cmux-mcp.git` (Les's own GitHub)
- Author: `Les Leslie <les@wedgwoodwebworks.com>`
- Description: "MCP server for cmux terminal automation (macOS only)"
- Dependencies: `oneiric>=0.21.0`, `mcp-common>=0.30.0`
- Architecture: `BaseOneiricServerMixin` (oneiric mixin)
- The third-party is the `cmux` app itself (manaflow-ai, https://github.com/manaflow-ai/cmux) — a Ghostty-based terminal. `cmux-mcp` is the Bodai-maintained bridge to it. Per `feedback-no-bodai-mentions-in-mcp-repos`, the rule's intent is "managed by Bodai but NOT part of the **Tier-A core**" — cmux-mcp IS Bodai-managed, so it qualifies for a new "Bodai-maintained `*-mcp`" subcategory.

**Why is chat-bridge-mcp "Bodai-maintained"?** Same signals (Les's GitHub, `mcp-common` dep, `oneiric` transitive dep via `mcp-common`).

**Tech Stack:** Python 3.14, FastMCP, `mcp_common.tools.dispatch.apply_tool_profile` (the W0 helper from `mcp-common` at `mcp_common/tools/dispatch.py:269`).

## Global Constraints

- `from __future__ import annotations` first non-comment line of every new module.
- Ruff line length 100; per-file ignores in `pyproject.toml` apply unchanged.
- No `Co-Authored-By` trailer in commit message (per `feedback-no-claude-code-coauthor-attribution.md`).
- Use `user.email="les@wedgwoodwebworks.com"` for any commits.

## Phase 1 — Verify the per-repo wiring shape

- [ ] Read `/Users/les/Projects/graphics-mcp/graphics_mcp/mcp/tools/profiles.py` (a confirmed Tier-B adopter with `apply_tool_profile` wired) and capture the exact shape: env-var name, REGISTRATION_MAP keys, STANDARD/FULL/MINIMAL_REGISTRATIONS lists.
- [ ] Read `/Users/les/Projects/cmux-mcp/cmux_mcp/mcp/tools/profiles.py` (the file may not exist yet — confirm) and the parent `cmux_mcp/server.py` to see how the server starts up.
- [ ] Read `/Users/les/Projects/chat-bridge-mcp/chat_bridge_mcp/mcp/tools/profiles.py` (the file may not exist yet) and the parent startup.

#### Integration Contract ← REQUIRED
- **Triggered from**: developer / agent reading the existing Tier-B pattern before wiring the missing ones.
- **Returns to / updates**: nothing persisted; a captured shape for the per-repo wiring.
- **Demonstrable by**: the rg output shows the Tier-B pattern at `graphics-mcp/graphics_mcp/mcp/tools/profiles.py`; the cmux-mcp / chat-bridge-mcp files are identified as either present (skeleton) or absent (needs creation).
- **Rollback signal**: not applicable — Phase 1 is read-only.
- **Observability added**: none.

## Phase 2 — Wire `apply_tool_profile` in `cmux-mcp`

- [ ] Create `cmux-mcp/cmux_mcp/mcp/tools/profiles.py` (if it doesn't exist) with the Tier-B shape:
  - Env var: `CMUX_MCP_TOOL_PROFILE` (default `full`).
  - `MINIMAL_REGISTRATIONS` / `STANDARD_REGISTRATIONS` / `FULL_REGISTRATIONS` lists per the Tier-B pattern.
  - `REGISTRATION_MAP` (W0 helper) keyed by string registrar-name → lambda trampoline.
  - `CRACKERJACK_MANDATORY_GROUPS` (a list, possibly empty) per the Tier-B pattern.
- [ ] Edit `cmux-mcp/cmux_mcp/server.py` (or equivalent) to call `apply_tool_profile(mcp_app, profile=os.environ.get("CMUX_MCP_TOOL_PROFILE", "full"))` at server startup. Mirror how `graphics-mcp` does this.
- [ ] Add `CMUX_MCP_TOOL_PROFILE` to `cmux-mcp/README.md` env-var section (and `.envrc` if applicable).
- [ ] Add a smoke test in `cmux-mcp/tests/` that asserts `apply_tool_profile` is called at startup (mirror the `tests/unit/test_wiring.py::test_apply_tool_profile_called` pattern in crackerjack).
- [ ] Run `crackerjack run -v` (or `pytest cmux-mcp/ -v --no-cov` at minimum).

#### Integration Contract ← REQUIRED
- **Triggered from**: server startup.
- **Returns to / updates**: `cmux-mcp` now honors the `CMUX_MCP_TOOL_PROFILE` env var; the `apply_tool_profile` call is wired in production.
- **Demonstrable by**: `rg "apply_tool_profile" cmux-mcp/ --type py` returns ≥1 production hit (in `cmux_mcp/mcp/tools/profiles.py` or `server.py`); `pytest` exits 0.
- **Rollback signal**: server fails to start; `crackerjack run` fails.
- **Observability added**: standard `mcp_common.tools.dispatch` log lines on profile apply.

## Phase 3 — Wire `apply_tool_profile` in `chat-bridge-mcp`

- [ ] Create `chat-bridge-mcp/chat_bridge_mcp/mcp/tools/profiles.py` with the same shape as Phase 2 (env var `CHAT_BRIDGE_MCP_TOOL_PROFILE` default `full`).
- [ ] Edit `chat-bridge-mcp/chat_bridge_mcp/server.py` to call `apply_tool_profile` at startup.
- [ ] Add `CHAT_BRIDGE_MCP_TOOL_PROFILE` to the README and `.envrc`.
- [ ] Add a smoke test in `chat-bridge-mcp/tests/`.
- [ ] Run `crackerjack run -v` (or `pytest chat-bridge-mcp/ -v --no-cov` at minimum).

#### Integration Contract ← REQUIRED
- **Triggered from**: server startup.
- **Returns to / updates**: `chat-bridge-mcp` now honors `CHAT_BRIDGE_MCP_TOOL_PROFILE`.
- **Demonstrable by**: `rg "apply_tool_profile" chat-bridge-mcp/ --type py` returns ≥1 production hit; `pytest` exits 0.
- **Rollback signal**: server fails to start; `crackerjack run` fails.
- **Observability added**: standard `mcp_common.tools.dispatch` log lines.

## Phase 4 — Cross-ecosystem doc update (in the tool-profile-ecosystem-doc plan)

- [ ] **Not in this plan.** The cross-ecosystem doc update lives in the companion `2026-10-12-tool-profile-ecosystem-doc.md` plan (Phase 1 inventory + Phase 4 cross-link). After this plan's Phases 2 and 3 land, the inventory count grows from 19 → 21 (the 2 newly-wired repos). The companion plan's `scripts/generate_tool_profiles_doc.py` re-reads the inventory on every run, so the doc regenerates automatically.
- [ ] **Tier classification update for the doc:** `cmux-mcp` and `chat-bridge-mcp` move from Tier-C (excluded — no `apply_tool_profile`) to a new "Bodai-maintained `*-mcp`" subcategory. The cross-link policy extends: Tier-A and "Bodai-maintained" both link to the cross-ecosystem doc; Tier-B (third-party MCP) does not, per `feedback-no-bodai-mentions-in-mcp-repos`.
- [ ] The companion plan's Phase 1 step "verify 19 adopter count" needs to be updated to "verify 21 adopter count" — a one-line frontmatter or body-text edit in the companion plan. **This plan does NOT make that edit; the user does it after the 2 per-repo wirings land.**

## Phase 5 — Per-repo commits

- [ ] Two commits, one per repo, on each repo's `main`:
  - cmux-mcp: `feat(cmux-mcp): wire apply_tool_profile (CMUX_MCP_TOOL_PROFILE env var)`
  - chat-bridge-mcp: `feat(chat-bridge-mcp): wire apply_tool_profile (CHAT_BRIDGE_MCP_TOOL_PROFILE env var)`
- [ ] For each commit: `git -c user.email="les@wedgwoodwebworks.com"` per `git-author-email-correct-domain.md`.
- [ ] Do NOT add `Co-Authored-By` trailer (per `feedback-no-claude-code-coauthor-attribution.md`).
- [ ] Do NOT push (per `feedback-bodai-push-is-user-controlled.md`).

#### Integration Contract ← REQUIRED
- **Triggered from**: per-repo CI.
- **Returns to / updates**: 2 commits land on cmux-mcp `main` and chat-bridge-mcp `main`.
- **Demonstrable by**: `git log --oneline -1` on each repo shows the commit message; the new `profiles.py` exists on disk.
- **Rollback signal**: `pytest` fails in either repo.
- **Observability added: per-repo.

## Rollback signal

If Phase 2 or 3 fails: revert the per-repo commit. If Phase 4 (doc update) fails: revert the companion plan's doc edit (out of scope for this plan; user-managed).

## Observability added

- Per-repo: standard `mcp_common.tools.dispatch.apply_tool_profile` log lines on server startup.
- Cross-repo: when `scripts/generate_tool_profiles_doc.py` re-runs (post-Phase 2/3), the doc picks up the 2 new adopters automatically.

## Cross-references

- `docs/plans/2026-10-12-tool-profile-ecosystem-doc.md` (active) — the companion plan that generates the cross-ecosystem doc
- `feedback-no-bodai-mentions-in-mcp-repos.md` — the rule that distinguishes Tier-A / Tier-B / "Bodai-maintained `*-mcp`" subcategories
- `mcp-common/mcp_common/tools/dispatch.py:269` — the `apply_tool_profile` helper
- `graphics-mcp/graphics_mcp/mcp/tools/profiles.py` — the Tier-B pattern to mirror
- `cmux-mcp/cmux_mcp/server.py` — the cmux-mcp server startup to edit
- `chat-bridge-mcp/chat_bridge_mcp/server.py` — the chat-bridge-mcp server startup to edit
- `feedback-bodai-push-is-user-controlled.md` — push policy
- `feedback-no-claude-code-coauthor-attribution.md` — commit message policy
- `git-author-email-correct-domain.md` — author email policy
