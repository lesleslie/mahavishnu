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

## Path resolution

The `Path` column is **relative to the projects root** — the directory that
holds the fleet checkouts. No absolute path appears in this file, so it is
machine-independent and safe to publish.

Resolve the projects root in this order:

1. `$BODAI_PROJECTS_ROOT` — explicit override.
1. The parent of this repository — this file lives at
   `<projects root>/mahavishnu/BODAI_REPO_REGISTRY.md`.
1. `~/Projects` — the standard developer layout.

A repo's location is then `<projects root>/<Path column>`.

## Discovery process (per Phase 0.0)

1. Read MEMORY.md for inventory hints (e.g., `bodai-mcp-servers-not-mycelium-core.md`)
1. `ls ~/Projects/` for git repos
1. For each candidate, read `pyproject.toml` head; confirm Bodai-authored + Python-pinned
1. Document in `settings/ecosystem.yaml` (gitignored per-machine catalog) — copy [`settings/ecosystem.yaml.example`](settings/ecosystem.yaml.example) and populate
1. Add registry-only annotations (Phase, FastMCP pin, provenance) to [`settings/registry_metadata.yaml`](settings/registry_metadata.yaml)
1. **Verification step** — every entry below is generated from the YAML files above; run `python3 scripts/regen_bodai_registry.py --check` to detect registry-vs-source drift.

A repo is **Bodai-maintained** if: (a) `pyproject.toml` exists, (b) author = `Les Leslie`
(variants: `les@wedgwoodwebworks.com`, `les@wedgwood.us`, `les@lesleslie.com`) or the
`fastblocks-ui.dev` team (a Bodai team alias), (c) `requires-python` is pinned to >=3.13
or higher.

## Confirmed Bodai repos (>=3.13 currently; bumping to >=3.14 in Phases 0.1–0.N)


### Core 6 (in-scope for streaming tar Phase 3)

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| mcp-common | mcp-common/ | >=3.14 | **Phase 0.1**. Leaf dep. FastMCP **>=4.0.3** (`2026-09-06`) |
| oneiric | oneiric/ | >=3.14 | **Phase 0.2**. needed by Phase A |
| session-buddy | session-buddy/ | >=3.14 | **Phase 0.4**. FastMCP **>=4.0.3** (`2026-09-06`) |
| akosha | akosha/ | >=3.14 | **Phase 0.5**. required akosha/mcp/client.py transport-fix for streamable_http_client 2-tuple return. FastMCP **>=4.0.3** (`2026-09-06`) |
| crackerjack | crackerjack/ | >=3.14 | **Phase 0.6**. FastMCP >=3.4.2 (already open ceiling); already 4.0.3 capable. FastMCP **>=4.0.3** (`2026-09-06`) |
| mahavishnu | mahavishnu/ | >=3.14 | **Phase 0.N**. needed for Phase D; last in rollout. FastMCP **>=4.0.3** (`2026-09-06`) |

### Web / framework libraries

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| fastblocks | fastblocks/ | >=3.14 | **Phase 0.7** |
| fastblocks-ui | fastblocks-ui/ | >=3.14 | fastblocks runtime CSS dep |
| jinja2-async-environment | jinja2-async-environment/ | >=3.14 | fastblocks transitive |
| jinja2-inflection | jinja2-inflection/ | >=3.14 | fastblocks transitive |
| starlette-async-jinja | starlette-async-jinja/ | >=3.14 | fastblocks transitive |

### Bodai MCP servers (standalone; per `bodai-mcp-servers-not-mycelium-core.md`)

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| archive-org-mcp | archive-org-mcp/ | >=3.14 | requires-python >=3.14 |
| cmux-mcp | cmux-mcp/ | >=3.14 | MCP server for cmux terminal automation; flat-layout migration 2026-09-20 from src-layout |
| css-mcp | css-mcp/ | >=3.14 | **Phase 0.8**. FastMCP **>=4.0.3** (`2026-09-06`) |
| excalidraw-mcp | excalidraw-mcp/ | >=3.14 | discovered |
| graphics-mcp | graphics-mcp/ | >=3.14 | **Phase 0.8**. pulled in httpcore2/httpx2 transitively. FastMCP **>=4.0.3** (`2026-09-06`) |
| langsmith-mcp | langsmith-mcp/ | >=3.14 | **Phase 0.8** |
| mailgun-mcp | mailgun-mcp/ | >=3.14 | discovered |
| medium-mcp | medium-mcp/ | >=3.14 | requires-python >=3.14 |
| neo4j-mcp | neo4j-mcp/ | >=3.14 | discovered |
| opera-cloud-mcp | opera-cloud-mcp/ | >=3.14 | **Phase 0.8** |
| penpot-api-mcp | penpot-api-mcp/ | >=3.14 | discovered |
| porkbun-dns-mcp | porkbun-dns-mcp/ | >=3.14 | discovered |
| porkbun-domain-mcp | porkbun-domain-mcp/ | >=3.14 | **Phase 0.8** |
| raindropio-mcp | raindropio-mcp/ | >=3.14 | also named in bodai-mcp-servers-not-mycelium-core.md |
| scapy-mcp | scapy-mcp/ | >=3.14 | requires-python >=3.14 |
| splashstand | splashstand/ | >=3.14 | **Phase 0.8** |
| spline-mcp | spline-mcp/ | >=3.14 | discovered |
| synxis-crs-mcp | synxis-crs-mcp/ | >=3.14 | discovered |
| synxis-pms-mcp | synxis-pms-mcp/ | >=3.14 | discovered |
| unifi-mcp | unifi-mcp/ | >=3.14 | discovered |

### Desktop / GUI

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| flowscape | flowscape/ | >=3.14 | active |
| mdinject | mdinject/ | >=3.14 | PySide6 desktop app; also exposes MCP server (mdinject-mcp) |

### Meta

| Repo | Path | Current `requires-python` | Notes |
|---|---|---|---|
| bodai | bodai/ | >=3.14 | The Orb — ecosystem meta-project |

### Deprecated / Archived (moved to `~/Projects/ARCHIVED/`)

| Repo | Archive path | `requires-python` | Notes |
|---|---|---|---|
| fastblocks-htmy | ARCHIVED/fastblocks-htmy/ | n/a (archived) | Self-declared Development Status :: 7 - Inactive; absorbed into fastblocks>=0.31.0 |
| peanutbutterpub | ARCHIVED/peanutbutterpub/ | n/a (archived) | Authored for personal exploration; not part of the orchestrated ecosystem |

## Summary counts

- Core 6 (in-scope for streaming tar Phase 3): 6
- Web / framework libraries: 5
- Bodai MCP servers (standalone; per `bodai-mcp-servers-not-mycelium-core.md`): 20
- Extensions: 0
- Desktop / GUI: 2
- Meta: 1
- Deprecated/Archived: 2

**Total active Bodai repos: 34**

## Per-project MCP server and agent scoping

> Established 2026-08-24 per the post-audit architectural decision
> `docs/decisions/2026-08-24-bodai-mcp-routing-pattern.md`. Update
> this table whenever a project gains or loses MCP servers.

_(Hand-maintained. Not generated. See `settings/ecosystem.yaml` (gitignored
per-machine) for the authoritative per-project MCP server assignments; the
[`settings/ecosystem.yaml.example`](settings/ecosystem.yaml.example) template
documents the schema.)_

## Phase 4 (3.15) reuse

This registry is the canonical list for Phase 4. When Phase 4 lands,
update the `Current requires-python` column to `>=3.14` and start
fresh dependency-ordered sequencing. Note that `mahavishnu` already
declares `>=3.13, <3.15` in its own `pyproject.toml`, so it will
need a top-of-stack bump alongside the Phase 4 rollout.

_(Hand-maintained footer. Not generated.)_

## Excluded from scope (not a fleet member)

- `dhara/` — Decommissioned as a core component (ADR 019, 2026-10-17); still maintained by Bodai, but outside the six-repo fleet release set
  Removed from `settings/ecosystem.yaml` 2026-10-28.
- `jinja2-custom-delimiters/` — IntelliJ Platform plugin (Gradle/Kotlin), not a Python package
  Removed from `settings/ecosystem.yaml` 2026-10-28.
- `www-mcp-servers/` — no pyproject.toml; docs-only
  Removed from `settings/ecosystem.yaml` 2026-09-09.
  Archived at: `www-mcp-servers/`.
