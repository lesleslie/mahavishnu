# Bodai Ecosystem Diagram Audit — Cross-Repo Synthesis

**Date:** 2026-08-16
**Scope:** All `.md` files with fenced mermaid/plantuml/dot/image refs in 6 Bodai repos:
mahavishnu, akosha, dhara, session-buddy, crackerjack, oneiric
**Method:** Six parallel read-only audits (one per repo), each cataloguing every diagram, validating
syntax where possible, and assigning KEEP / UPDATE / REMOVE / ADD verdicts. Synthesis combines
the six reports and surfaces cross-repo patterns.
**Total diagrams catalogued:** ~360

______________________________________________________________________

## Aggregate stats

| Repo | Total | KEEP | UPDATE | REMOVE | ADD | Broken-syntax |
|---|---:|---:|---:|---:|---:|---:|
| mahavishnu | 141 | 25 | 12 | 104 | 5 | 0 |
| oneiric | 95 | 53 | 14 | 18 | 10 | 0 |
| session-buddy | 77 | 64 | 7 | 4 | 2 | 0 |
| crackerjack | 24 | 4 | 21 | 0 | 3 | **3** |
| akosha | 16 | 11 | 4 | 0 | 5 | 0 |
| dhara | 7 | small repo, mostly accurate | | | | 0 |
| **TOTAL** | **~360** | **~155 (43%)** | **~58 (16%)** | **~126 (35%)** | **~25 (7%)** | **3** |

Only **3 of 360 diagrams actually fail to render** (all in crackerjack, all 1-line syntax defects).
The dominant problem is content staleness, not syntax.

`★ Render-defect note:` The 3 broken diagrams in crackerjack are all easily fixable:

1. `docs/diagrams/skills-ecosystem-mermaid.md:13` — unescaped `"` in a node label
1. `docs/architecture/MEMORY_ARCHITECTURE.md:399` — `Over` keyword collision + `;` in `Note over` text
1. `docs/architecture/MEMORY_ARCHITECTURE.md:1247` — same `Over` keyword + `;` in `Note over` text

______________________________________________________________________

## Cross-repo patterns

### 1. Stale references to removed modules (the wave-1..7 drift pattern, in diagrams)

The same **permanently-removed** modules leak into multiple repositories' diagrams:

| Removed module | Found in |
|---|---|
| `mcpretentious` | mahavishnu (ARCHITECTURE.md:258, VISUAL_GUIDE.md:30) |
| `iTerm2.adapter` | mahavishnu (same diagrams) |
| `KubernetesPool` | mahavishnu (VISUAL_GUIDE.md:141) |
| `OpenSearch` DLQ | mahavishnu (VISUAL_GUIDE.md:824) |
| `sentence-transformers` runtime | akosha (MEMORY_ARCHITECTURE.md:300, 753) |
| `layered_cache` (Redis L2) | akosha (ARCHITECTURE.md:435, DEPLOYMENT_GUIDE.md:65) |
| `optparse` legacy CLI | dhara (the wave-6 cleanup may have missed a docstring reference) |
| 12-agent system | crackerjack (README.md:249 PNG, ADR-002, multiple diagrams) |
| `FixStrategyStorage` / `AgentCoordinator` | crackerjack (MEMORY_ARCHITECTURE.md:1216) |
| Prefab/Agno labeled "stub only" | mahavishnu (ARCHITECTURE.md:258) |

This is the same drift pattern as wave-1..7, in a different artifact class. Doc audit fixed prose
references; the diagrams were not in scope. Code outpaces docs; the docs class shifts.

### 2. Cross-repo duplicates of the Bodai ecosystem diagram

The "ecosystem view" diagram appears in at least 4 places, with subtle drift between copies:

- `mahavishnu/docs/architecture/ARCHITECTURE.md:258` (canonical, but stale)
- `session-buddy/ARCHITECTURE.md:145` (duplicate, symmetric arrows)
- `session-buddy/docs/reference/service-dependencies.md:563` (recommended canonical target)
- `session-buddy/docs/archive/uncategorized/DOCS_CONSOLIDATION_PLAN.md:593` (archived paste)

**Recommendation:** pick the canonical once, link from the others. The audit recommends
`session-buddy/docs/reference/service-dependencies.md:563` as the canonical home since it has
the most accurate topology.

### 3. Same diagram mirrored 2-4× within the same repo

- **mahavishnu**: `embedding-architecture.md` content re-rendered in `README.md`, `diagrams/README.md`, `EMBEDDINGS_SETUP_GUIDE.md` (5+ duplicates each)
- **oneiric**: 4-tier precedence flow in `RESOLUTION_LAYER_SPEC.md:27`, `VISUAL_GUIDE.md:104`, `NEW_ARCH_SPEC.md:122` (3 copies)
- **oneiric**: lifecycle state machine in `VISUAL_GUIDE.md:215` and `NEW_ARCH_SPEC.md:228` (2 copies, names don't match)
- **session-buddy**: user-session lifecycle in `README.md:279`, `README.md:328`, `QUICK_START.md:149`, archived DOCS_CONSOLIDATION_PLAN.md:364 (4 copies)
- **session-buddy**: JWT auth flow in `JWT_AUTHENTICATION.md` + archived `JWT_AUTH_IMPLEMENTATION_SUMMARY.md` (2 copies)
- **session-buddy**: WebSocket server arch in `WEBSOCKET_SERVER.md` + `WEBSOCKET_DELIVERY_REPORT.md` (2 copies)

**Pattern:** a "Visual Guide" was created to onboard new contributors, then the underlying docs were
re-edited without removing the visual guide copies. The visual guide is now the stale one.

### 4. Self-contradicting diagrams

- **mahavishnu** `WORKFLOW_DIAGRAMS.md:488` says "49 Total" tools; actual is 174+.
- **mahavishnu** `WORKFLOW_DIAGRAMS.md:211` says "9 total" repos; actual is 7.
- **akosha**: `README.md:391-400` lists "25 tools" in the FULL profile; CAPTION says "Cross-System Semantic Search" but BULLETS describe "Core Memory Aggregation".
- **crackerjack**: `skills-ecosystem-mermaid.md` claims Dhara DB-backed storage; `oneiric-skills-integration.mmd` (same diagram concept) claims local JSON storage. Both are wrong (the code path is gone).
- **crackerjack**: `MEMORY_ARCHITECTURE.md:79` ER diagram references 5 SQLite files that no longer exist.

**Pattern:** when a subsystem collapses, the two diagram children that described it disagree on
which storage backend it had. This is the diagram equivalent of two code paths that silently drifted.

### 5. Orphaned assets (3 categories)

- **mahavishnu**: `docs/diagrams/system-architecture.svg` is the only `.svg` in the repo, referenced by zero markdown files.
- **crackerjack**: `agent-selection.png`, `layered-architecture.png`, `decision-framework.png` all have orphan status (claimed "Used In: CLAUDE.md" in `docs/diagrams/README.md` but no embed exists).
- **crackerjack**: `docs/diagrams/oneiric-skills-integration.mmd` is `.mmd`-suffixed but contains markdown-with-fences, unreferenced by any tracked `.md`.

**Pattern:** the diagram index claims attributions that don't exist. Same shape as the
documented-but-not-wired pattern. Even when diagrams are accurate, their attribution table lies.

### 6. Wrong table/code-path references in ER diagrams

- **session-buddy** `MEMORY_ARCHITECTURE.md:55` — ER diagram references `fix_attempts`, `git_metrics`, `serverless_sessions`, `session_acl` — none exist. Actual is `causal_fix_attempts`.
- **session-buddy** `developer/ARCHITECTURE.md:344` — wrong table names (`knowledge_graph_entities` vs. actual `kg_entities`).
- **session-buddy** `developer/ARCHITECTURE.md:840` — claims "L2: Redis Cache" but no Redis client in `session_buddy/` (no `redis`/`aioredis` import).
- **akosha** `MEMORY_ARCHITECTURE.md:300` — still says "all-MiniLM-L6-v2 via sentence-transformers ONNX" but `is_available()` always returns False.

**Pattern:** ER diagrams are the highest-staleness category because they're written against the
schema intent, not the current schema. They're the diagrams that "looked right" when last edited
but never re-validated against the live `CREATE TABLE` statements.

### 7. CLI surface diagrams that lag reality

- **mahavishnu** `WORKFLOW_DIAGRAMS.md:133` — routing decision tree missing `peer_affinity` (added in ADR-014 May 2026).
- **oneiric** `VISUAL_GUIDE.md:1047-1071` — CLI diagram shows `pause/drain` as one node; actual CLI has them as separate commands, plus 9 more (`swap`, `manifest`, `secrets`, `event`, `workflow`, `shell`, `action-invoke`, `plugins`, `remote-status`, `supervisor-info`).
- **oneiric** `VISUAL_GUIDE.md:415` — class diagram has wrong method signatures (`use(key) Handle` vs. actual `async use(key, *, provider, capabilities, require_all, force_reload)`).

**Pattern:** CLI diagrams drift fast because CLI surface expands frequently. The oneiric case is
the most acute (15+ commands vs. 7 in the diagram).

______________________________________________________________________

## Top 10 highest-impact actions, prioritized

| # | Action | Repo | Severity | Effort |
|---|---|---|---|---|
| 1 | Fix 3 broken mermaid renderers in `MEMORY_ARCHITECTURE.md` (lines 399, 1247) + `skills-ecosystem-mermaid.md:13` | crackerjack | **HIGH** (diagrams literally don't render) | S (1-line patches, agent verified with mmdc) |
| 2 | Regenerate `ai-agent-orchestration.png` to match the new caption (or revert caption) | crackerjack | **HIGH** (caption/image contradiction) | M |
| 3 | Update `docs/architecture/ARCHITECTURE.md:258` (replace iTerm2/MCPretentious/K8sPool with tmux/crow/AppleContainer/E2B/RunPodPool) | mahavishnu | **HIGH** (canonical arch diagram references removed modules) | M |
| 4 | Update `docs/VISUAL_GUIDE.md:30, 141, 824` (same drift pattern) | mahavishnu | HIGH | M |
| 5 | Update `docs/NEW_ARCH_SPEC.md:23-29` (top-level packages diagram has wrong bridge paths) | oneiric | HIGH (recommended for code copy-paste) | S |
| 6 | Update `docs/VISUAL_GUIDE.md:1047-1071` (CLI surface diagram missing 9+ commands) | oneiric | HIGH | S |
| 7 | Update `docs/architecture/MEMORY_ARCHITECTURE.md:79` (replace 5 SQLite stores with the surviving 5) | crackerjack | HIGH | M |
| 8 | Delete ~50 archive diagrams in `docs/archive/guides/` and `docs/archive/reports/` (file-level `git rm`) | mahavishnu | MEDIUM (bloat, not user-facing) | S |
| 9 | Update session-buddy `MEMORY_ARCHITECTURE.md:55` (4 tables that don't exist) | session-buddy | MEDIUM | S |
| 10 | Update session-buddy `developer/ARCHITECTURE.md:344` (wrong table names) | session-buddy | MEDIUM | S |

______________________________________________________________________

## Wire-up candidates (recommended ADDs)

The audits surfaced 30+ recommended additions across all 6 repos. The highest-impact:

1. **mahavishnu**: Pool topology diagram (CLAUDE.md names `MahavishnuPool`, `SessionBuddyPool`, `RunPodPool` but no canonical diagram exists)
1. **mahavishnu**: Terminal adapter selection flowchart (replaces the stale `iTerm2+MCPretentious` diagram)
1. **mahavishnu**: Worker-isolation topology (`AppleContainer` + `E2BSandbox` — replaced removed Docker/OrbStack)
1. **mahavishnu**: MCP tool topology (174+ tools × 14 groups)
1. **mahavishnu**: LLM routing sequence for `mahavishnu/workers/task_router.py`
1. **akosha**: Embedding pipeline flow (mock-only embedding path is currently invisible in any diagram)
1. **akosha**: Fitness signal flow (the 60s `loop` that writes to `routing_fitness/{tc}/{selector}`)
1. **akosha**: End-to-end query → embedding → search → result flow
1. **session-buddy**: `track_channel_session` state machine (the new MCP tool has zero diagrams)
1. **session-buddy**: Worktree lifecycle (creating → listing → pruning → removing, with the wave-4 fixed bugs)
1. **crackerjack**: Post-removal architecture diagram (the canonical answer to "what runs when you say `crackerjack run`")
1. **crackerjack**: External ai-fix-loop diagram (the proposed replacement architecture in the spec)
1. **crackerjack**: Ratchet CLI defects diagram (the 4 defects in `crackerjack-ratchet-cli-defects.md`)

______________________________________________________________________

## Strategic recommendations

1. **Adopt a canonical-diagram-per-concept convention.** Each repo gets a `docs/diagrams/` directory where each diagram is defined ONCE. Cross-references go through `![…](<path>)` embeds. The wave-1..7 cascade for prose, applied to diagrams, would prevent the 5–6 duplicate mirrors per repo.

1. **CI guard for mermaid render.** Crackerjack already proves this is feasible (`mmdc` v11.16.0 + system Chrome). Add a `pytest --mermaid-render` that runs all fenced mermaid blocks through `mmdc -i` and fails on syntax error. Existing `tests/unit/test_mcp_tool_inventory.py` for tool-counts is the template.

1. **Documentation-update contract for module removals.** When a module is removed (matches the wave-6 commit pattern), the same PR must include an inventory of diagrams that reference it. Could be a `dep-check` script that greps `git grep -l <removed_module>` across all fenced mermaid + ASCII art fences.

1. **`[^]` footnote convention for diagrams referencing soon-to-be-removed subsystems.** Like `!!! note "Diagram predates 2026-08-10 cleanup — see ADR-NNN."` at the top of the diagram block. Lets the diagram stay useful while flagging that it's not canonical.

1. **One ecosystem diagram, shared.** The Bodai topology (Mahavishnu ↔ Akosha ↔ Dhara ↔ Session-Buddy ↔ Crackerjack ↔ Oneiric) should live in ONE place (recommend session-buddy `docs/reference/service-dependencies.md:563`) and be re-embedded from there cross-repo. Six repositories can't all draw the same picture and stay in sync.

______________________________________________________________________

## Auditing methodology notes

- **Render verification:** Where Playwright Chromium was available, agents used `mcp__mermaid__generate_mermaid_diagram` or `mmdc v11.16.0` to validate parseability. In most environments the Mermaid MCP tool returned `browserType.launch: Executable doesn't exist` (Playwright missing), so parseability was confirmed by source inspection against the Mermaid spec.
- **Code verification:** Each diagram's "useful life" claim was checked against actual file existence (`ls`), class definitions (`grep -rn "class .*"`), and live tool-surface registration — not against documentation narrative.
- **Outdated reference verification:** Module paths and method signatures were cross-checked against the live source files of each repo.
- **Strictly read-only:** No file edits, no installs, no `git` mutations beyond `git ls-files`-equivalent inventory operations.

______________________________________________________________________

## Repo-by-repo detailed reports

Each repo's full report (with file:line entries, update diffs, and remove-candidate groupings) is
preserved in this session's transcript. The reports are large; this synthesis distills the
common patterns so they can be acted on as a coordinated wave rather than five uncoordinated
drifts.

For deeper drill-down per repo, refer to:

- `mahavishnu` — 141 entries
- `oneiric` — 95 entries
- `session-buddy` — 77 entries
- `crackerjack` — 24 entries (incl. 3 broken)
- `akosha` — 16 entries
- `dhara` — 7 entries
