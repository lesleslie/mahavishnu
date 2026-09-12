---
status: active
role: implementation
date: 2026-09-12
last_reviewed: 2026-09-12
topic: plan-audit-2026-09-12
---

# Plan Audit — 2026-09-12

**Date:** 2026-09-12
**Scope:** All 37 non-canonical active plans from `docs/plans/PLAN_INDEX.md`
**Method:** Read-only audit via 4 parallel subagents (one per directory), each
inspecting plan frontmatter + body, running `git log` against referenced
files, and grepping for keyword evidence. No files were modified by the
audit phase.
**Completion criteria:** Code-shipped loose (per user direction in this
session) — does not enforce the full Integration Contract (Triggered-from
/ Returns-to / Demonstrable-by / Rollback signal / Observability added).

## Probability → Status mapping

| Probability | Proposed status |
|---|---|
| ≥ 80% | `complete` |
| 50–79% | `partial` |
| < 50% | keep `active` |

Plans already at `status: complete` on disk but mislabeled as `active` in
`PLAN_INDEX.md` are flagged as **index-drift** and require only an index
regeneration to surface their true status.

## Aggregate result

| Proposed status | Count |
|---|---|
| `complete` (new flips from `active`) | 16 |
| `complete` (already on disk, index-drift) | 4 |
| `partial` | 8 |
| keep `active` | 16 |
| **Total audited** | **44** |

Per-store breakdown (40 audited + 4 already-complete = 44 in scope):

| Store | → complete | → partial | keep active |
|---|---|---|---|
| `docs/plans/` (16 audited) | 9 | 3 | 4 |
| `docs/superpowers/plans/` (12) | 2 | 3 | 7 |
| `docs/superpowers/specs/` (10) | 5 | 2 | 3 |
| `docs/followups/` (2) | 0 | 0 | 2 |
| **Subtotal audited** | **16** | **8** | **16** |
| Index drift (already complete on disk) | 4 | — | — |
| **Grand total** | **20** | **8** | **16** |

## Index drift (already complete on disk, index says active)

These four files are already `status: complete` in their frontmatter but
the `PLAN_INDEX.md` still labels them `active`. A single regeneration of
`PLAN_INDEX.md` will surface their true status. **No frontmatter edits
needed** — only the index regeneration.

| Path | Disk status | Index labels | Why already complete |
|---|---|---|---|
| `docs/plans/2026-07-29-mcpretentious-wiring.md` | complete (historical) | active | Author marked complete; underlying problem resolved by switching to live adapters (tmux/crow/mock); mcpretentious removed. |
| `docs/plans/2026-02-20-self-improvement-design.md` | complete (historical) | active | Frontmatter shows complete; design-as-historical; companion implementation plan shipped MCP tools. |
| `docs/plans/2026-02-27-health-check-system-design.md` | complete (historical) | active | Frontmatter shows complete; `/health` + `/readiness` shipped across Bodai servers. |
| `docs/plans/.archive/2025-02-11-adaptive-router-feedback-loops.md` | complete (superseded) | active | Archived; superseded by `2026-05-23-bodai-routing-feedback-loop-v4.md`. |

## Per-plan audit (proposed frontmatter changes)

### `docs/plans/` (main plans) — 16 audited

| Path | Current | Prob | Proposed | Evidence summary |
|---|---|---|---|---|
| `2026-04-04-ecosystem-execution-board.md` | active (umbrella) | 95% | **complete** | Initiatives I0–I8+ all marked [x] complete with linked initiative files; commits 884fa25a, 028e8ab8, 0f780b0c, 3e62bb6e, 671a3886 (2026-04 to 2026-06). |
| `2026-05-23-bodai-routing-feedback-loop-v4.md` | active | 35% | keep active | Multi-version design-only; v3 plan's Phase 1.5 ed25519 signing shipped (akosha 09cef76); v4 phases lack mahavishnu-side implementation commits. |
| `2026-07-26-mahavishnu-acp-server.md` | active | 5% | keep active | Zero implementation; `mahavishnu/acp/` does not exist; only the plan-authoring commit (3b38eb24) touches this path. |
| `2026-07-29-pyscn-ty-quality-repair.md` | active | 90% | **complete** | All three outcome criteria evidenced: c02c7e9a, c268fc8b, 8b96021b, 378ad7cc — pyscn exit 0, ty zero unresolved-import, focused pytest passes. |
| `2026-08-20-bodai-mcp-surface-standardization.md` | active | 80% | **complete** | 4-tool baseline live across 5 Bodai servers per cross-server review §10.5; `discover_tools`, `get_liveness`, `get_readiness`, `health_check_all` exposed. |
| `2026-08-24-claude-env-audit-remediation.md` | active | 75% | **partial** | Goal 4 explicitly DONE 2026-08-25 (move fastblocks-stack agents); ce9739e1, 8871646d, e3e3d522. Other goals partially evidenced. |
| `2026-08-25-bodai-cli-audit.md` | active | 90% | **complete** | Companion implementation plan fully done; spec body shipped through 8+ review rounds; inventory script shipped. |
| `2026-08-25-bodai-cli-audit-implementation.md` | active | 100% | **complete** | Explicit commit 3e43e127 marks all 95 boxes ticked; Phase 0/1/2/4 all evidenced (d34fd257, 6c860a2f, b839e3ff, 26e39d3c, c6322fa8, 1cdb7399, 5421620f, 212d3d8d, bb51c537). |
| `2026-08-25-bodai-tui-shell-surface.md` | active | 15% | keep active | Companion design exists but no implementation commits; `mahavishnu/tui/` (per bodai-cli-audit scope) exists, but `bodai/admin/shell.py` / `bodai/tui/dashboard.py` not found. |
| `dhara-outstanding-items-plan.md` | active | 25% | keep active | Cross-repo (Dhara); only frontmatter-migration commit on mahavishnu side; Dhara repo state not audited here. |
| `2026-09-07-goose-terminal-adapter.md` | active | 85% | **complete** | `mahavishnu/terminal/adapters/goose.py` exists; version bumps 22c95f74 (0.22.1), 4aae187d (0.22.0); 7 REQ-GOO-001..007 satisfied. |
| `2026-09-07-pi-pool-backend.md` | active | 85% | **complete** | `mahavishnu/pools/pi_pool.py` + `pi_observability.py` exist; PiPool is 4th pool type; 8 REQ-PI-001..008 satisfied. |
| `2026-09-09-bodai-skill-agent-distribution.md` | active | 90% | **complete** | Phase 1 shipped 2026-09-10 across 5 servers (akosha 4951ee8, mahavishnu d722d2fa, session-buddy 02235271+987c3096, dhara 2e3a65fa, crackerjack e99edb6a); Phase 1.5 ed25519 signing landed akosha 09cef76; 0 blockers in cross-server reviews. |
| `2026-09-10-bodai-math-initiatives-tier1.md` | active | 85% | **complete** | `mahavishnu/observability/changepoint/` modules exist (cusum, page_hinkley, anomaly); 3f61fa3a round-6 fixes, ed9b2e6e two-stage architecture; plan body marked ready-for-ship. |
| `2026-09-10-settle-semantic-merge.md` | active | 75% | **partial** | `mahavishnu/settle/merge.py` exists; 16a61969, 83acd9a2, 4239c8cf, 212d3d8d landed; some requirements (git-merge-tree diagnostic, /health merge_driver signals) deferred per design. |
| `2026-09-12-finish-partial-implementations.md` | active | 60% | **partial** | Brand-new plan just promoted from draft post 3-agent re-review; targets tracked workstreams not yet flipped. |

### `docs/superpowers/plans/` — 12 audited

| Path | Current | Prob | Proposed | Evidence summary |
|---|---|---|---|---|
| `2026-05-14-doc-sync-and-channel-phase2.md` | active | 60% | **partial** | Track A (docs) fully landed (ARCHITECTURE 174fae9a, PLAN_INDEX regen 44cb1c15). Track B (DharaChannelPublisher) cross-repo; no matching commit in session-buddy logs. |
| `2026-07-15-sb-checkpoint-stash-clobber-fix.md` | active | 35% | keep active | Cross-repo; plan body says "NOT executed now"; 11 files exist under `session_buddy/checkpoint/` but authored as future-execution. |
| `2026-07-16-bodai-plugin-standardization.md` | active | 55% | **partial** | bodai-plugins scaffolding + mahavishnu plugin migration landed (b96b24d0, 44e39c5e, 9c0f4111); sibling-server migrations missing. |
| `2026-08-23-oneiric-action-kit-promotion.md` | active | 92% | **complete** | All 3 deliverable layers (catalog, decision doc, skill) plus Wave 3 breadcrumbs landed; merge commit 5ac802be confirms W4 completion. |
| `2026-08-31-flowscape.md` | active | 5% | keep active | Zero implementation; `/Users/les/Projects/flowscape` contains only `.claude/`, `.claude-plugin/`, `.git/`. |
| `2026-08-31-zsh-modernization.md` | active | 8% | keep active | Personal-shell plan; not repo-trackable. |
| `2026-09-06-archive-org-mcp.md` | active | 18% | keep active | Plan + registration landed (a8214058, 4bae6c24, d013862b); `archive_org_mcp/` only `__init__.py` (448 B) + `__main__.py` (473 B) — pure stub. |
| `2026-09-06-medium-mcp.md` | active | 15% | keep active | Plan + registration landed (890e6ac3, 4bae6c24); `medium_mcp/` only `__init__.py` (195 B) + `__main__.py` (450 B). |
| `2026-09-06-port-bodai-reconciliation.md` | active | 12% | keep active | Cross-repo; no implementation commits; only plan-authoring commit (611e9e0d). |
| `2026-09-06-registry-manifest-migration.md` | active | 85% | **complete** | Core registry migration + repo_cli repointing + ecosystem.yaml anchor fix all landed (8e95c8d9, 4bae6c24, cfd33240, e37eb8ea). |
| `2026-09-06-scapy-mcp.md` | active | 25% | keep active | Feed registry landed (784b3f88) but full Phase 0a/0b/1 surface shows no evidence. |
| `2026-09-12-jot-drain-polish.md` | active | 55% | **partial** | Items 2, 5, 6 (and partial 3) landed (444fa4a9, 4239c8cf, 655143b9, 664eed32, 8bb0a466, ce27c697, def3eb7a); items 1 (slash command) and 4 (spec-lock) show no commit yet. |

### `docs/superpowers/specs/` — 10 audited

| Path | Current | Prob | Proposed | Evidence summary |
|---|---|---|---|---|
| `2026-04-27-bodai-auth-standardization-design.md` | active | 15% | keep active | Cross-repo (mcp-common/auth + 5 Bodai services); no implementation commits visible. |
| `2026-05-16-llm-routing-standardization-design.md` | active | 55% | **partial** | Mahavishnu-specific migration landed (cloud_worker + models.yaml + TaskCategory); canonical `oneiric/llm/` and sibling-repo migrations deferred. |
| `2026-06-19-external-integrations-design.md` | active | 85% | **complete** | Tracks 1, 2, 4 substantially implemented (OpenHandsWorker, CrowTerminalAdapter, openhands MCP tools, TurboVec fallback); Track 3 TUI partial. |
| `2026-06-19-wave2a-chaos-hardening-design.md` | active | 90% | **complete** | All 5 chaos scenarios landed (test_openhands_chaos.py, test_crow_chaos.py); production error paths hardened. |
| `2026-06-19-wave2b-a2a-worker-design.md` | active | 92% | **complete** | All architectural units (card, server, worker, error codes, auth middleware) plus post-merge hardening landed; `mahavishnu/a2a/` + `mahavishnu/workers/a2a.py` exist. |
| `2026-07-14-multi-backend-pty-design.md` | active | 95% | **complete** | PTY backend registry lived and served; mcpretentious removal refactored the module out, validating the registry approach. |
| `2026-07-15-constellation-tui-design.md` | active | 55% | **partial** | Track 3 `mahavishnu/tui/` module shipped; surfaces 1 (statusLine extension) and 3 (activity-stream bridge) live in user-owned `~/.claude/scripts/`. Spec states "awaiting plan". |
| `2026-07-15-mahavishnu-acp-server-design.md` | active | 5% | keep active | Explicitly deferred per user direction; zero code under any acp path. |
| `2026-07-15-sb-checkpoint-stash-clobber-fix-design.md` | active | 8% | keep active | Gated behind user signal; location not yet verified; implementation gate TBD. |
| `2026-08-22-oneiric-action-kit-promotion-design.md` | active | 80% | **complete** | Decision doc + skill shipped (Wave 2); cross-repo catalog/breadcrumbs (Wave 3) not verifiable here but design intent met. |

### `docs/followups/` — 2 audited

| Path | Current | Prob | Proposed | Evidence summary |
|---|---|---|---|---|
| `2026-09-05-ai-dep-group-transitive-bloat.md` | active | 5% | keep active | `pyproject.toml` lines 200-202 still has consolidated `ai = [...]`; no commits since 2026-09-05 modified the ai group; author marked "Documented; remediation deferred". |
| `2026-09-05-terminal-validate-command-safety.md` | active | 3% | keep active | `mahavishnu/mcp/tools/terminal_tools.py` lines 39-60 still has the original DANGEROUS_COMMAND_PATTERNS list; tests still enforce strict behavior; no commits since 2026-09-05. |

## Notes & caveats

1. **Probability is loose.** Plans with 80%+ are *probably* complete, not
   *verified* complete. For plans that drive user-facing behavior (e.g.
   `claude-env-audit-remediation.md`, `jot-drain-polish.md`), the user
   should still spot-check that the implementation contract is met.
2. **Cross-repo evidence is limited.** Several plans reference Bodai
   sibling repos (akosha, dhara, session-buddy, crackerjack, mcp-common,
   oneiric, bodai-plugins). The audit could only verify mahavishnu-side
   commits. For plans that target cross-repo work, the proposed status
   reflects what is visible from this checkout.
3. **Dirty working tree.** ~30 files modified in working tree already.
   Some overlapping with this audit (notably `2026-07-29-mcpretentious-wiring.md`,
   `2026-08-25-bodai-cli-audit-implementation.md`, `2026-09-09-bodai-skill-agent-distribution.md`).
   When applying changes, I will reconcile against the working tree to
   avoid duplicate writes.
4. **Index drift is real.** Four plans already have `status: complete`
   on disk but the index labels them `active`. This is a regeneration
   gap, not a content issue.
5. **No production verification.** `shipped` status (per schema line 30,
   "delivered and verified in production") is intentionally not proposed
   here — production verification requires worker context that Mahavishnu
   pools are currently down for.

## Recommended action set (waiting on user approval)

1. Edit frontmatter on **24 plan files**:
   - 16 active → complete
   - 8 active → partial
2. Do **not** edit the 4 already-complete plans (they already have
   `status: complete` on disk).
3. Do **not** edit the 16 plans staying active.
4. Run `uv run python scripts/regenerate_plan_index.py` to regenerate
   `PLAN_INDEX.md` from updated frontmatter. This will surface the
   index-drift fixes plus the 24 new flips.
5. Show the resulting PLAN_INDEX diff for final user approval before
   any commit.
