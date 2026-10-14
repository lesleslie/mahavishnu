______________________________________________________________________

## status: active role: canonical kind: tracker date: 2026-09-26 last_reviewed: 2026-09-26 superseded_by: null topic: mcp-launcher-migration

# MCP Server Migration Tracker

> **For agentic workers:** This tracker gates Phase 5b (per-server migration). Each per-server PR
> updates exactly one row. Cross-reference Phase 3 of the MCP Launcher Standardization plan
> ([`docs/plans/2026-09-26-mcp-launcher-standardization.md`](../plans/2026-09-26-mcp-launcher-standardization.md))
> §5 Phase 3.

## Status legend

| status | meaning |
|---|---|
| `todo` | Migration not started |
| `in-progress` | Migration in flight (Phase 4a / Phase 4b / Phase 2 wrapper) |
| `done` | Migrated; commit hash captured |
| `out-of-scope` | Not a Core component OR no MCP server OR a desktop / Swift / library repo |
| `special` | Listed as `mcp: 3rd-party` in `settings/ecosystem.yaml` BUT registry classifies as a non-FastMCP transport — needs separate investigation before per-server cookbook migration |

## Core 5 (migrate-now)

| repo | path | status | migrated_at_commit | notes |
|---|---|---|---|---|
| vishnu (mahavishnu) | `/Users/les/Projects/mahavishnu/` | todo | — | Phase 4a Task 4a.1 — collapse `scripts/launch_mcp_with_secrets.py` to a thin wrapper around `mcp_common.server.launcher.launch()`. Secrets regex/parsing moves to `launcher.load_secrets()` (Phase 1 REQ-002) |
| ak (akosha) | `/Users/les/Projects/akosha/` | todo | — | Phase 4b Task 4b.3 — requires discovery subtask 4b.1 first (mode-dispatch investigation in `akosha/cli.py:_start_server`) |
| sb (session-buddy) | `/Users/les/Projects/session-buddy/` | todo | — | Phase 4b Task 4b.5 — requires discovery subtask 4b.4 first (`server` subcommand signal/pid semantics vs. bare launcher) |
| cj (crackerjack) | `/Users/les/Projects/crackerjack/` | todo | — | Phase 4a Task 4a.2 — refactor `crackerjack/mcp/server_core.py:_run_mcp_server` to delegate to launcher |
| oneiric | `/Users/les/Projects/oneiric/` | in-progress | 2.5a (commit pending user review) | Phase 2 wrapper-only migration; `scripts/launch_mcp.py` rewritten to ~25 LOC calling `launch(build_server=...)`. Wrapper exists in working tree but commit not yet recorded (post-validation land) |

## mcp-common foundation

| repo | path | status | migrated_at_commit | notes |
|---|---|---|---|---|
| mcp-common | `/Users/les/Projects/mcp-common/` | done | bdbdcb4 (2026-09-26) | Phase 1 — `mcp_common.server.launcher.launch()` + `load_secrets` / `warm_settings_feed` / `run_with_uvicorn_config` helpers + `tests/server/test_launcher.py` (TDD) + `docs/mcp/launcher-cookbook.md` + signal-handling smoke (REQ-014) |

## Standalone MCP servers (defer-to-cookbook, 20)

Authoritative source: `settings/ecosystem.yaml` (`mcp: 3rd-party` entries that are NOT
Core or foundation). BODAI_REPO_REGISTRY's standalone MCP table adds `splashstand`
(`mcp: 3rd-party` in ecosystem.yaml BUT `mcp: native` per registry) as a special row.

| repo | path | status | migrated_at_commit | notes |
|---|---|---|---|---|
| archive-org-mcp | `/Users/les/Projects/archive-org-mcp/` | planned-cookbook | — | Phase 5b — cookbook-driven; one PR per server |
| cmux-mcp | `/Users/les/Projects/cmux-mcp/` | planned-cookbook | — | Phase 5b — flat-layout migration 2026-09-20 (per registry); cookbook applies cleanly |
| css-mcp | `/Users/les/Projects/css-mcp/` | planned-cookbook | — | Phase 5b |
| excalidraw-mcp | `/Users/les/Projects/excalidraw-mcp/` | planned-cookbook | — | Phase 5b |
| graphics-mcp | `/Users/les/Projects/graphics-mcp/` | planned-cookbook | — | Phase 5b — pulls `httpcore2` / `httpx2` transitively; FastMCP `>=4.0.3` pinned |
| langsmith-mcp | `/Users/les/Projects/langsmith-mcp/` | planned-cookbook | — | Phase 5b |
| mailgun-mcp | `/Users/les/Projects/mailgun-mcp/` | planned-cookbook | — | Phase 5b |
| medium-mcp | `/Users/les/Projects/medium-mcp/` | planned-cookbook | — | Phase 5b |
| neo4j-mcp | `/Users/les/Projects/neo4j-mcp/` | planned-cookbook | — | Phase 5b |
| opera-cloud-mcp | `/Users/les/Projects/opera-cloud-mcp/` | planned-cookbook | — | Phase 5b |
| penpot-api-mcp | `/Users/les/Projects/penpot-api-mcp/` | planned-cookbook | — | Phase 5b |
| porkbun-dns-mcp | `/Users/les/Projects/porkbun-dns-mcp/` | planned-cookbook | — | Phase 5b |
| porkbun-domain-mcp | `/Users/les/Projects/porkbun-domain-mcp/` | planned-cookbook | — | Phase 5b |
| raindropio-mcp | `/Users/les/Projects/raindropio-mcp/` | planned-cookbook | — | Phase 5b — also named in `bodai-mcp-servers-not-mycelium-core.md` |
| scapy-mcp | `/Users/les/Projects/scapy-mcp/` | planned-cookbook | — | Phase 5b |
| spline-mcp | `/Users/les/Projects/spline-mcp/` | planned-cookbook | — | Phase 5b |
| synxis-crs-mcp | `/Users/les/Projects/synxis-crs-mcp/` | planned-cookbook | — | Phase 5b |
| synxis-pms-mcp | `/Users/les/Projects/synxis-pms-mcp/` | planned-cookbook | — | Phase 5b |
| unifi-mcp | `/Users/les/Projects/unifi-mcp/` | planned-cookbook | — | Phase 5b |
| **splashstand** | `/Users/les/Projects/splashstand/` | **special** | — | `mcp: 3rd-party` per `settings/ecosystem.yaml`; BODAI_REPO_REGISTRY flags as a non-FastMCP transport (`mcp: native` per the architecture review's note). Needs separate discovery subtask before per-server cookbook migration. **Do not** migrate via cookbook until transport investigation completes |

## Out-of-scope (~10)

These repos do not adopt `mcp_common.server.launcher` because they are: not MCP servers,
desktop applications, Swift-only clients, libraries without MCP servers, or the meta-project.

| repo | path | status | reason |
|---|---|---|---|
| bodai | `/Users/les/Projects/bodai/` | out-of-scope | Ecosystem meta-project (`mcp: native`); no standalone MCP server |
| dhara | `/Users/les/Projects/dhara/` | out-of-scope | No MCP server as of 2026-09-26. Revisit if MCP server is reintroduced |
| fastblocks | `/Users/les/Projects/fastblocks/` | out-of-scope | Web framework library; no MCP server. Will adopt when (and if) it gets one |
| fastblocks-ui | `/Users/les/Projects/fastblocks-ui/` | out-of-scope | fastblocks runtime CSS dep; no MCP server |
| jinja2-async-environment | `/Users/les/Projects/jinja2-async-environment/` | out-of-scope | fastblocks transitive library; no MCP server |
| jinja2-inflection | `/Users/les/Projects/jinja2-inflection/` | out-of-scope | fastblocks transitive library; no MCP server |
| starlette-async-jinja | `/Users/les/Projects/starlette-async-jinja/` | out-of-scope | fastblocks transitive library; no MCP server |
| flowscape | `/Users/les/Projects/flowscape/` | out-of-scope | Desktop application; no MCP server |
| mdinject | `/Users/les/Projects/mdinject/` | out-of-scope | PySide6 desktop app. **Not Core** — clarified by user 2026-09-26 (per Phase 3 architecture-review correction). May expose `mdinject-mcp` later, which would be a separate per-server cookbook migration |
| swiftui-ipc-client | `/Users/les/Projects/swiftui-ipc-client/` | out-of-scope | Swift Package Manager client (Unix Domain Socket / JSON-RPC 2.0). Not Python; not an MCP server |

## How to update this tracker

When a per-server PR lands:

1. Change `status` from `todo` / `in-progress` / `planned-cookbook` to `done`.
1. Set `migrated_at_commit` to the commit SHA (full 7-char hash minimum; full 40-char preferred).
1. Append a `notes` line: `Phase X.Y — REQ-XXX satisfied` (e.g. `Phase 5b — REQ-001..005, REQ-007, REQ-013`).

When starting a migration:

1. Change `status` from `todo` / `planned-cookbook` to `in-progress`.
1. Append the planned commit ID placeholder (e.g. `2.5a` or `5b.splashstand-discovery`).

When the transport is non-FastMCP and the cookbook does not apply:

1. Keep `status: special`.
1. Add a `notes` line documenting the discovery subtask outcome (e.g. `Phase 5b — discovery complete; uses stdio transport via custom subprocess manager, cookbook not applicable`).

## Cross-references

- **Plan**: [`docs/plans/2026-09-26-mcp-launcher-standardization.md`](../plans/2026-09-26-mcp-launcher-standardization.md) §5 Phase 3 Task 3.2 (this file) and Phase 5a (this file's maintenance contract).
- **Cookbook**: `/Users/les/Projects/mcp-common/docs/mcp/launcher-cookbook.md` — 4 worked examples (oneiric, vishnu, ak, cj) generated in Phase 1 Task 1.7.
- **Audit script**: `scripts/audit_mcp_launchers.py` — to be created in Phase 3 Task 3.1; detects MCP server presence per repo (`mcp.py`, `mcp/`, `*-mcp` pattern, `~/Library/LaunchAgents/com.mcp.*.plist`).
- **Source of truth for repo list**: [`BODAI_REPO_REGISTRY.md`](../../BODAI_REPO_REGISTRY.md) (generated from `settings/ecosystem.yaml` + `settings/registry_metadata.yaml`; regenerate via `python3 scripts/regen_bodai_registry.py`).
- **Source of truth for `mcp:` classification**: `settings/ecosystem.yaml` (hand-edit only — never regenerate).
- **Memory**: `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/feedback-bodai-core-component-taxonomy.md` — defines the Core-vs-not-Core taxonomy this tracker enforces.
- **Phase 5b per-server PR template**: see cookbook `recipes/css-mcp` for the canonical 5-LOC pattern; adapt per component.
