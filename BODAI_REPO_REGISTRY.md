# Bodai Repo Registry

Maintained by `les` and the Bodai ecosystem. Authoritative source for
Python version coordination, dependency mapping, and Phase 4 (3.15)
planning. Filed 2026-08-23 during Phase 3 3.14 migration.

## Discovery process (per Phase 0.0)

1. Read MEMORY.md for inventory hints (e.g., `bodai-mcp-servers-not-mycelium-core.md`)
2. `ls /Users/les/Projects/` for git repos
3. For each candidate, read `pyproject.toml` head; confirm Bodai-authored + Python-pinned
4. Document in this file
5. **Verification step** — the brief listed 14 entries with "(verify)" markers; the discovery pass
   confirmed all 14 and surfaced **17 additional** Bodai-authored Python-pinned repos that
   belong in the registry (MCP servers not yet in scope for streaming tar, but in scope for
   the 3.14 / 3.15 rollout per the user's directive that ALL Bodai repos must migrate).

A repo is **Bodai-maintained** if: (a) `pyproject.toml` exists, (b) author = `Les Leslie`
(variants: `les@wedgwoodwebworks.com`, `les@wedgwood.us`, `les@lesleslie.com`) or the
`fastblocks-ui.dev` team (a Bodai team alias), (c) `requires-python` is pinned to >=3.13
or higher.

## Confirmed Bodai repos (>=3.13 currently; bumping to >=3.14 in Phases 0.1–0.N)

### Core 7 (in-scope for streaming tar Phase 3)

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| mcp-common | /Users/les/Projects/mcp-common/ | >=3.13 | Leaf dep; Phase 0.1 |
| oneiric | /Users/les/Projects/oneiric/ | >=3.13 | Phase 0.2; needed by Phase A |
| dhara | /Users/les/Projects/dhara/ | >=3.13 | Phase 0.3 |
| session-buddy | /Users/les/Projects/session-buddy/ | >=3.13 | Phase 0.4 |
| akosha | /Users/les/Projects/akosha/ | >=3.13 | Phase 0.5 |
| crackerjack | /Users/les/Projects/crackerjack/ | >=3.13 | Phase 0.6 |
| mahavishnu | /Users/les/Projects/mahavishnu/ | >=3.13, <3.15 | Phase 0.N (last); needed for Phase D |

### Web / framework libraries

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| fastblocks | /Users/les/Projects/fastblocks/ | >=3.13 | Phase 0.7 |
| fastblocks-ui | /Users/les/Projects/fastblocks-ui/ | >=3.13 | fastblocks runtime CSS dep |
| jinja2-async-environment | /Users/les/Projects/jinja2-async-environment/ | >=3.13 | fastblocks transitive |
| jinja2-inflection | /Users/les/Projects/jinja2-inflection/ | >=3.13 | fastblocks transitive |
| starlette-async-jinja | /Users/les/Projects/starlette-async-jinja/ | >=3.13 | fastblocks transitive |

### Bodai MCP servers (standalone; per `bodai-mcp-servers-not-mycelium-core.md`)

The 6 servers explicitly named in the brief plus 10 additional Bodai MCP servers
discovered during this audit (raindropio, excalidraw, mailgun, neo4j, penpot-api,
porkbun-dns, spline, synxis-crs, synxis-pms, unifi).

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| css-mcp | /Users/les/Projects/css-mcp/ | >=3.13 | Phase 0.8 |
| graphics-mcp | /Users/les/Projects/graphics-mcp/ | >=3.13 | Phase 0.8 |
| splashstand | /Users/les/Projects/splashstand/ | >=3.13 | Phase 0.8 |
| porkbun-domain-mcp | /Users/les/Projects/porkbun-domain-mcp/ | >=3.13 | Phase 0.8 |
| langsmith-mcp | /Users/les/Projects/langsmith-mcp/ | >=3.13 | Phase 0.8 |
| opera-cloud-mcp | /Users/les/Projects/opera-cloud-mcp/ | >=3.13 | Phase 0.8 |
| raindropio-mcp | /Users/les/Projects/raindropio-mcp/ | >=3.13 | Discovered — also named in `bodai-mcp-servers-not-mycelium-core.md` |
| excalidraw-mcp | /Users/les/Projects/excalidraw-mcp/ | >=3.13 | Discovered |
| mailgun-mcp | /Users/les/Projects/mailgun-mcp/ | >=3.13 | Discovered |
| neo4j-mcp | /Users/les/Projects/neo4j-mcp/ | >=3.13 | Discovered |
| penpot-api-mcp | /Users/les/Projects/penpot-api-mcp/ | >=3.13 | Discovered |
| porkbun-dns-mcp | /Users/les/Projects/porkbun-dns-mcp/ | >=3.13 | Discovered |
| spline-mcp | /Users/les/Projects/spline-mcp/ | >=3.13 | Discovered |
| synxis-crs-mcp | /Users/les/Projects/synxis-crs-mcp/ | >=3.13 | Discovered |
| synxis-pms-mcp | /Users/les/Projects/synxis-pms-mcp/ | >=3.13 | Discovered |
| unifi-mcp | /Users/les/Projects/unifi-mcp/ | >=3.13 | Discovered |

### Desktop / GUI

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| mdinject | /Users/les/Projects/mdinject/ | >=3.13 | PySide6 desktop app; also exposes MCP server (`mdinject-mcp`) |

### Meta

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| bodai | /Users/les/Projects/bodai/ | >=3.13 | The Orb — ecosystem meta-project |
| peanutbutterpub | /Users/les/Projects/peanutbutterpub/ | >=3.13 | Discovered (Les-authored) |

### Deprecated (kept for traceability only — NOT in migration scope)

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| fastblocks-htmy | /Users/les/Projects/fastblocks-htmy/ | >=3.13 | Self-declared "Development Status :: 7 - Inactive" shim; absorbed into `fastblocks>=0.31.0`. Skip migration. |

## Per-project MCP server and agent scoping

> Established 2026-08-24 per the post-audit architectural decision
> `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md`. Update
> this table whenever a project gains or loses MCP servers.

### MCP server assignments

| Project | Local `.mcp.json` | Bodai core | Project-specific | Notes |
|---|---|---|---|---|
| **mahavishnu** | `/Users/les/Projects/mahavishnu/.mcp.json` | akosha, crackerjack, dhara, mahavishnu, session-buddy, minimax-coding-plan | (none — mahavishnu is control plane) | Also contains 10 noise entries (chart-antv, css, excalidraw, grafana, graphics, langsmith, mermaid, neo4j, penpot-api, pycharm); see Phase 5 of plan for cleanup |
| **fastblocks** | `/Users/les/Projects/fastblocks/.mcp.json` | crackerjack, session-buddy | mailgun, porkbun-dns, porkbun-domain, splashstand | fastblocks workers + splashstand stdio launch |
| **splashstand** | `/Users/les/Projects/splashstand/.mcp.json` | crackerjack, session-mgmt | (none — inherits fastblocks' splashstand MCP via fastblocks sessions) | Minimal config; splashstand capability token moved to shell env (see decision §1) |
| **akosha** | `/Users/les/Projects/akosha/.mcp.json` | (self) | — | Standalone MCP server; loaded when CWD is akosha/ |
| **dhara** | `/Users/les/Projects/dhara/.mcp.json` | (self) | — | Standalone MCP server |
| **session-buddy** | `/Users/les/Projects/session-buddy/.mcp.json` | (self) | — | Standalone MCP server |
| **crackerjack** | `/Users/les/Projects/crackerjack/.mcp.json` | (self) | — | Standalone MCP server |

Other `*-mcp` repos (css-mcp, graphics-mcp, excalidraw-mcp, neo4j-mcp,
mailgun-mcp, porkbun-dns-mcp, porkbun-domain-mcp, spline-mcp,
synxis-crs-mcp, synxis-pms-mcp, unifi-mcp, langsmith-mcp,
opera-cloud-mcp, raindropio-mcp, penpot-api-mcp) each ship their own
`.mcp.json` for self-testing but are not yet wired into any
consuming project's `.mcp.json`. Plugin packaging is the planned
distribution mechanism.

### Agent scoping rules

| Project | Agent location | Notes |
|---|---|---|
| Global | `/Users/les/.claude/agents/` | Stack-agnostic specialists + mycelium-core backups |
| **mahavishnu** | `/Users/les/Projects/mahavishnu/.claude/agents/` | Backend orchestration + Bodai-specific specialists. **Excludes** fastblocks-stack frontend agents (moved out 2026-08-24) |
| **fastblocks** | `/Users/les/Projects/fastblocks/.claude/agents/` | Frontend-stack specialists: web-components-specialist, pwa-specialist, htmx-specialist, htmy-specialist, fastblocks-specialist |
| **splashstand** | inherits via CLAUDE.md → fastblocks/.claude/agents/ | splashstand is built on fastblocks |

See `.claude/decisions/agent-curation-strategy.md` for the broader
agent-curation rule (15k token budget, mycelium-core deduplication).

### Secret rule

**No** literal `*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD` values in any
`.mcp.json` file. All secrets must come from shell env (via `.zshrc`,
direnv `.envrc`, or 1Password CLI). Enforced by
`scripts/audit_no_secrets_in_mcp.py` in pre-commit + crackerjack quality gate.

Allowed exception: `*_HOST`, `*_URL`, `*_PORT` (non-secret config).

## Summary counts

- Core 7 (streaming-tar Phase 3 in-scope)
- Web/framework libraries: 5 (1 from brief + 4 transitive)
- Bodai MCP servers: 16 (6 from brief + 10 discovered)
- Desktop/GUI: 1 (discovered)
- Meta: 2 (discovered)
- Deprecated: 1 (excluded from scope)

**Total active Bodai repos: 31** (14 from brief + 17 newly-discovered)

## Excluded from scope (verified non-Bodai or non-Python)

- `jinja2-custom-delimiters/` — Kotlin/Gradle project, not Python
- `www-mcp-servers/` — no `pyproject.toml`; docs-only
- `sites/` — no `pyproject.toml`; non-Python
- `SCRATCH/`, `BACKUP/`, `ARCHIVED/` — not active repos
- `fb-1a/`, `fb-1b*/`, `fb-1c3/`, `fastblocks-task*/` — worktrees/feature-branches of fastblocks, not separate repos
- `bodai-plugins/`, `.crush/`, `.cache/`, `.benchmarks/` — meta/tooling dirs

## Phase 4 (3.15) reuse

This registry is the canonical list for Phase 4. When Phase 4 lands,
update the `Current requires-python` column to `>=3.14` and start
fresh dependency-ordered sequencing. Note that `mahavishnu` already
declares `>=3.13, <3.15` in its own `pyproject.toml`, so it will
need a top-of-stack bump alongside the Phase 4 rollout.