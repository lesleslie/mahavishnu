# Bodai Repo Registry

Maintained by `les` and the Bodai ecosystem. Authoritative source for
Python version coordination, dependency mapping, and Phase 4 (3.15) planning.

<!--
  ⚠️  THIS FILE IS GENERATED FROM settings/ecosystem.yaml + settings/registry_metadata.yaml.

  Regenerate with:    python3 scripts/regen_bodai_registry.py
  Drift check (CI):   python3 scripts/regen_bodai_registry.py --check

  Do NOT hand-edit the catalog tables below; edit the sources and regenerate.
  The "Per-project MCP server and agent scoping" section and the "Phase 4"
  footer are exempt from generation and may be edited by hand.
-->

## Discovery process (per Phase 0.0)

1. Read MEMORY.md for inventory hints (e.g., `bodai-mcp-servers-not-mycelium-core.md`)
1. `ls /Users/les/Projects/` for git repos
1. For each candidate, read `pyproject.toml` head; confirm Bodai-authored + Python-pinned
1. Document in [`settings/ecosystem.yaml`](settings/ecosystem.yaml) — the canonical source
1. Add registry-only annotations (Phase, FastMCP pin, provenance) to [`settings/registry_metadata.yaml`](settings/registry_metadata.yaml)
1. **Verification step** — every entry below is generated from the YAML files above; run `python3 scripts/regen_bodai_registry.py --check` to detect registry-vs-source drift.

A repo is **Bodai-maintained** if: (a) `pyproject.toml` exists, (b) author = `Les Leslie`
(variants: `les@wedgwoodwebworks.com`, `les@wedgwood.us`, `les@lesleslie.com`) or the
`fastblocks-ui.dev` team (a Bodai team alias), (c) `requires-python` is pinned to >=3.13
or higher.

## Confirmed Bodai repos (>=3.13 currently; bumping to >=3.14 in Phases 0.1–0.N)


### Core 7 (in-scope for streaming tar Phase 3)

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| mcp-common | /Users/les/Projects/mcp-common/ | >=3.14 | **Phase 0.1**. Leaf dep. FastMCP **>=4.0.3** (`2026-09-06`) |
| oneiric | /Users/les/Projects/oneiric/ | >=3.14 | **Phase 0.2**. needed by Phase A |
| dhara | /Users/les/Projects/dhara/ | >=3.14 | **Phase 0.3**. FastMCP **>=4.0.3** (`2026-09-06`) |
| session-buddy | /Users/les/Projects/session-buddy/ | >=3.14 | **Phase 0.4**. FastMCP **>=4.0.3** (`2026-09-06`) |
| akosha | /Users/les/Projects/akosha/ | >=3.14 | **Phase 0.5**. required akosha/mcp/client.py transport-fix for streamable_http_client 2-tuple return. FastMCP **>=4.0.3** (`2026-09-06`) |
| crackerjack | /Users/les/Projects/crackerjack/ | >=3.14 | **Phase 0.6**. FastMCP >=3.4.2 (already open ceiling); already 4.0.3 capable. FastMCP **>=4.0.3** (`2026-09-06`) |
| mahavishnu | /Users/les/Projects/mahavishnu/ | >=3.14 | **Phase 0.N**. needed for Phase D; last in rollout. FastMCP **>=4.0.3** (`2026-09-06`) |

### Web / framework libraries

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| fastblocks | /Users/les/Projects/fastblocks/ | >=3.14 | **Phase 0.7** |
| fastblocks-ui | /Users/les/Projects/fastblocks-ui/ | >=3.14 | fastblocks runtime CSS dep |
| jinja2-async-environment | /Users/les/Projects/jinja2-async-environment/ | >=3.14 | fastblocks transitive |
| jinja2-inflection | /Users/les/Projects/jinja2-inflection/ | >=3.14 | fastblocks transitive |
| starlette-async-jinja | /Users/les/Projects/starlette-async-jinja/ | >=3.14 | fastblocks transitive |

### Bodai MCP servers (standalone; per `bodai-mcp-servers-not-mycelium-core.md`)

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| archive-org-mcp | /Users/les/Projects/archive-org-mcp/ | >=3.14 | requires-python >=3.14 |
| css-mcp | /Users/les/Projects/css-mcp/ | >=3.14 | **Phase 0.8**. FastMCP **>=4.0.3** (`2026-09-06`) |
| excalidraw-mcp | /Users/les/Projects/excalidraw-mcp/ | >=3.14 | discovered |
| graphics-mcp | /Users/les/Projects/graphics-mcp/ | >=3.14 | **Phase 0.8**. pulled in httpcore2/httpx2 transitively. FastMCP **>=4.0.3** (`2026-09-06`) |
| langsmith-mcp | /Users/les/Projects/langsmith-mcp/ | >=3.14 | **Phase 0.8** |
| mailgun-mcp | /Users/les/Projects/mailgun-mcp/ | >=3.14 | discovered |
| medium-mcp | /Users/les/Projects/medium-mcp/ | >=3.14 | requires-python >=3.14 |
| neo4j-mcp | /Users/les/Projects/neo4j-mcp/ | >=3.14 | discovered |
| opera-cloud-mcp | /Users/les/Projects/opera-cloud-mcp/ | >=3.14 | **Phase 0.8** |
| penpot-api-mcp | /Users/les/Projects/penpot-api-mcp/ | >=3.14 | discovered |
| porkbun-dns-mcp | /Users/les/Projects/porkbun-dns-mcp/ | >=3.14 | discovered |
| porkbun-domain-mcp | /Users/les/Projects/porkbun-domain-mcp/ | >=3.14 | **Phase 0.8** |
| raindropio-mcp | /Users/les/Projects/raindropio-mcp/ | >=3.14 | also named in bodai-mcp-servers-not-mycelium-core.md |
| scapy-mcp | /Users/les/Projects/scapy-mcp/ | >=3.14 | requires-python >=3.14 |
| splashstand | /Users/les/Projects/splashstand/ | >=3.14 | **Phase 0.8** |
| spline-mcp | /Users/les/Projects/spline-mcp/ | >=3.14 | discovered |
| synxis-crs-mcp | /Users/les/Projects/synxis-crs-mcp/ | >=3.14 | discovered |
| synxis-pms-mcp | /Users/les/Projects/synxis-pms-mcp/ | >=3.14 | discovered |
| unifi-mcp | /Users/les/Projects/unifi-mcp/ | >=3.14 | discovered |

### Extensions

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| jinja2-custom-delimiters | /Users/les/Projects/jinja2-custom-delimiters/ | n/a | PyCharm plugin for custom Jinja2 delimiter syntax highlighting (Python); role: extension in ecosystem.yaml |

### Desktop / GUI

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| mdinject | /Users/les/Projects/mdinject/ | >=3.14 | PySide6 desktop app; also exposes MCP server (mdinject-mcp) |

### Meta

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| bodai | /Users/les/Projects/bodai/ | >=3.14 | The Orb — ecosystem meta-project |

### Deprecated / Archived (moved to `~/Projects/ARCHIVED/`)

| Repo | Archive path | `requires-python` | Notes |
|---|---|---|---|
| fastblocks-htmy | /Users/les/Projects/ARCHIVED/fastblocks-htmy/ | n/a (archived) | Self-declared Development Status :: 7 - Inactive; absorbed into fastblocks>=0.31.0 |
| peanutbutterpub | /Users/les/Projects/ARCHIVED/peanutbutterpub/ | n/a (archived) | Les-authored; not part of orchestrated ecosystem |

## Summary counts

- Core 7 (in-scope for streaming tar Phase 3): 7
- Web / framework libraries: 5
- Bodai MCP servers (standalone; per `bodai-mcp-servers-not-mycelium-core.md`): 19
- Extensions: 1
- Desktop / GUI: 1
- Meta: 1
- Deprecated/Archived: 2

**Total active Bodai repos: 34**

## Per-project MCP server and agent scoping

> Established 2026-08-24 per the post-audit architectural decision
> `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md`. Update
> this table whenever a project gains or loses MCP servers.

_(Hand-maintained. Not generated. See `settings/ecosystem.yaml` for the
authoritative per-project MCP server assignments.)_

## Phase 4 (3.15) reuse

This registry is the canonical list for Phase 4. When Phase 4 lands,
update the `Current requires-python` column to `>=3.14` and start
fresh dependency-ordered sequencing. Note that `mahavishnu` already
declares `>=3.13, <3.15` in its own `pyproject.toml`, so it will
need a top-of-stack bump alongside the Phase 4 rollout.

_(Hand-maintained footer. Not generated.)_

## Excluded from scope (verified non-Bodai or non-Python)

- `www-mcp-servers/` — no pyproject.toml; docs-only
  Removed from `settings/ecosystem.yaml` 2026-09-09.
