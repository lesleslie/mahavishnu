---
status: active
role: umbrella
date: 2026-10-15
last_reviewed: 2026-10-15
superseded_by: null
blocks_on: []
topic: mcp-server-fleet-modernization
title: "MCP Server Fleet Modernization — Consolidated Parent Plan"

---

# MCP Server Fleet Modernization — Consolidated Parent Plan

**Date:** 2026-10-15
**Status:** `active`, `umbrella`
**Purpose:** Consolidate three overlapping plans that together describe bringing the *-mcp fleet (Mahavishnu, Bodai core, and standalone *-mcp repos) onto FastMCP 3.4+ with tool-profile dispatch and launcher standardization.

This is a **consolidation plan**, not a new workstream — the actual work is described in the three child plans below. This plan adds: (1) a single index of in-flight work; (2) a sequenced view of remaining gaps; (3) explicit `superseded_by` pointers on the child plans so future readers see this umbrella.

## Child Plans

| Plan | Topic | Status (per 2026-10-15 audit) | Role in this umbrella |
|---|---|---|---|
| `2026-06-26-fastmcp-3-upgrade.md` (removed) | FastMCP 2.x → 3.4+ pin migration across 15 *-mcp repos | `stale-status` (Phases 1-3 done; 7/15 repos still on 2.x) | Foundation: every other plan here depends on FastMCP 3.4+ public API. |
| [`2026-08-18-mcp-tool-profile-adoption.md`](2026-08-18-mcp-tool-profile-adoption.md) (+ design spec, removed: `../specs/2026-08-18-mcp-tool-profile-adoption-design.md`) | `MAHAVISHNU_TOOL_PROFILE` dispatch via `mcp_common._apply_tool_profile` | `complete, superseded` (W0/W1/W2a shipped; tail of W2b-W4 absorbed by this umbrella 2026-10-18) | Profile-aware tool surface across the fleet. |
| [`2026-09-26-mcp-launcher-standardization.md`](2026-09-26-mcp-launcher-standardization.md) | Unified `mcp_common.launcher` for consumer CLI bootstrap | `complete, superseded` (Phase 1 foundation shipped; Phases 2-5 tail absorbed by this umbrella 2026-10-18) | Launcher path convergence so per-standalone CLI bugs get one fix per Stack Overflow. |

## Sequenced Remaining Work

> Two of three child plans (tool-profile, launcher) are now `complete, superseded` (triaged 2026-10-18). Their remaining work has been absorbed by this umbrella and is tracked below. The third child (fastmcp-3-upgrade) was already removed per its plan frontmatter.

1. **Finish fastmcp pin migration for 2.x holdouts** (fastmcp-3-upgrade plan Phase 5):
   - `penpot-api-mcp`, `raindropio-mcp`, `mailgun-mcp`, `chat-bridge-mcp` (these are the actual 2.x/unpinned holdouts per the 2026-10-15 audit)
   - `archive-org-mcp`, `medium-mcp`, `scapy-mcp` are covered by `docs/specs/2026-09-06-mcp-stub-activation-design.md` (removed; originally marked `complete`)
2. **Land tool-profile waves W2b-W4** (tool-profile plan): requires fastmcp 3.4+ so blocked on #1
3. **Land launcher Phase 2** (launcher plan): oneiric vendored CLI fixes (REQ-009 + REQ-010) — known bugs
4. **Defer launcher Phases 3-5** (cuttable per the plan's own §9): per-standalone migrations to launcher-call shape

## Decision Rules

- **Add a new tool profile wave?** Only after the corresponding *-mcp repo passes fastmcp 3.4+ pin migration.
- **Add a new launcher consumer?** Only if the consumer's CLI is affected by REQ-009 / REQ-010 (the oneiric vendored CLI bugs).
- **Mark a child plan superseded_by this umbrella?** Done for the three child plans (this umbrella is the canonical index).

## Acceptance Criteria

- All 15 *-mcp repos pinned to `fastmcp>=3.4.0,<5` (or equivalent)
- `_apply_tool_profile` wired in every Bodai core MCP server (mahavishnu, session-buddy, akosha, crackerjack, dhara)
- `mcp_common.launcher` consumed by every per-standalone CLI that needs startup lifecycle
- Each child plan's status field either `complete` (work done) or `superseded_by` this umbrella — **satisfied 2026-10-18** (2 of 3 children confirmed: tool-profile, launcher)

## Provenance

Created by the 2026-10-15 plan audit (10-batch parallel workflow). Supersedes the consolidation suggestion in:

- `2026-06-26-fastmcp-3-upgrade.md` (removed) recommendation (last paragraph)
- `docs/specs/2026-08-20-mcp-deps-crackerjack-loop-design.md` (removed) recommendation (last paragraph)
- Cluster 1 in the audit synthesis
