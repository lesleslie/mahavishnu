# MCP Server Family: MCPBaseSettings → OneiricMCPConfig Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate all remaining MCPBaseSettings/MCPServerSettings usages across the standalone Bodai MCP servers (css-mcp, graphics-mcp, splashstand, etc.) to OneiricMCPConfig, completing the cross-ecosystem deprecation migration started in the 2026-07-13 Bodai session.

**Architecture:** Per-repo `class <Name>Settings(OneiricMCPConfig)` swap + (where applicable) `.load()` classmethod rewrite using `oneiric.core.config.load_settings` plus a flat-YAML merge to preserve MCPBaseSettings's flat-key schema compatibility.

**Tech Stack:** Pydantic v2, oneiric.core.config, mcp_common (consumer side), pytest, ruff.

## Global Constraints

- Every change inherits from `OneiricMCPConfig` (already vendored via oneiric).
- `.load()` callers must be replaced with a classmethod that uses `oneiric.core.config.load_settings` + flat-YAML merge (session-buddy pattern, see commit `05bc2622`).
- Backward-compat instance methods (`get_api_key`, `get_api_key_secure`) added where tests rely on them.
- Each commit is **single-repo + single-purpose**; no cross-repo bundles.
- Tests pass at every step; commit only on GREEN.
- The `mcp-common` package itself emits the deprecation by intent (per its own comment: "silencing is left to the consumer") and is **not** in this plan's scope.

______________________________________________________________________

## Audit summary

Audit at session end (2026-07-13):

| Repo | MCPBaseSettings usages | Status |
|---|---|---|
| css-mcp | 3 | ❌ pending |
| graphics-mcp | 3 | ❌ pending |
| langsmith-mcp | 2 | ❌ pending |
| splashstand | 9 | ❌ pending |
| opera-cloud-mcp | 1 | ❌ pending |
| porkbun-domain-mcp | 3 | ❌ pending |
| raindropio-mcp | 0 | ✅ clean |
| jinja2-inflection | 0 | ✅ clean |
| n8n-mcp | 0 | ✅ clean |
| excalidraw-mcp | 0 | ✅ clean |

**Total: 6 repos, 21 usages to migrate.**

Already-migrated repos (NOT in this plan's scope; reference for pattern):

- crackerjack (37 classes, commit `25e230e7`)
- akosha (12 usages, commit `18fda25`)
- session-buddy (~15 usages across 4 files, commit `05bc2622`)
- dhara (3 usages, commit `300e021`)
- mahavishnu uses Pydantic v2 `BaseSettings` directly (no MCPBaseSettings)

______________________________________________________________________

## Per-repo migration pattern (proven on session-buddy, dhara, akosha)

For each repo:

1. **Replace import** — `from mcp_common import MCPBaseSettings` → `from oneiric.core.config import OneiricMCPConfig` (and `MCPServerSettings` → `OneiricMCPConfig`).
1. **Replace inheritance** — `class <X>Settings(MCPBaseSettings):` → `class <X>Settings(OneiricMCPConfig):` (use `Edit` with `replace_all=true` for the `(MCPBaseSettings)` → `(OneiricMCPConfig)` swap).
1. **Rewrite `.load()` classmethod** — preserve the legacy `(server_name, config_path=...)` signature but route through `oneiric.core.config.load_settings(project_name=server_name, path=config_path)` + a `yaml.safe_load()` flat-YAML merge for backward compat.
1. **Add `get_api_key` / `get_api_key_secure` instance methods** where tests patch them.
1. **Verify tests pass** — `uv run pytest tests/ --no-cov` for the touched paths.
1. **Single-repo commit** with the standard message format.

______________________________________________________________________

## Task 1: splashstand migration (9 usages — largest scope)

**Files:**

- Modify: `splashstand/splashstand/config/*.py` (likely several files; verify with `grep -rln`)
- Test: existing tests in `splashstand/tests/` should pass without modification.

**Steps:**

- [ ] `grep -rn "MCPBaseSettings\|MCPServerSettings" splashstand/splashstand` to enumerate exact files.
- [ ] For each file: replace import + inheritance + `.load()` method (use session-buddy commit `05bc2622` as the reference implementation).
- [ ] Add `get_api_key` / `get_api_key_secure` instance methods if `grep` shows tests patching them.
- [ ] `uv run pytest tests/ --no-cov -q` — must be all GREEN.
- [ ] `git add splashstand/` (splashstand paths only) + commit.

## Task 2: css-mcp migration (3 usages)

**Files:**

- Modify: `css-mcp/css_mcp/config.py` (or wherever the 3 usages live; verify with grep)
- Test: existing tests should pass.

**Steps:**

- [ ] `grep -rn "MCPBaseSettings\|MCPServerSettings" css-mcp/css_mcp` to enumerate exact files.
- [ ] Apply the per-repo migration pattern.
- [ ] `uv run pytest tests/ --no-cov -q` — must be all GREEN.
- [ ] `git add css-mcp/` + commit.

## Task 3: graphics-mcp migration (3 usages)

**Files:**

- Modify: `graphics-mcp/graphics_mcp/config.py`
- Test: existing tests should pass.

**Steps:**

- [ ] `grep -rn "MCPBaseSettings\|MCPServerSettings" graphics-mcp/graphics_mcp`.
- [ ] Apply the per-repo migration pattern.
- [ ] `uv run pytest tests/ --no-cov -q` — must be all GREEN.
- [ ] `git add graphics-mcp/` + commit.

## Task 4: porkbun-domain-mcp migration (3 usages)

**Files:**

- Modify: `porkbun-domain-mcp/porkbun_domain_mcp/config.py`
- Test: existing tests should pass.

**Steps:**

- [ ] `grep -rn "MCPBaseSettings\|MCPServerSettings" porkbun-domain-mcp/porkbun_domain_mcp`.
- [ ] Apply the per-repo migration pattern.
- [ ] `uv run pytest tests/ --no-cov -q` — must be all GREEN.
- [ ] `git add porkbun-domain-mcp/` + commit.

## Task 5: langsmith-mcp migration (2 usages)

**Files:**

- Modify: `langsmith-mcp/langsmith_mcp/config.py`
- Test: existing tests should pass.

**Steps:**

- [ ] `grep -rn "MCPBaseSettings\|MCPServerSettings" langsmith-mcp/langsmith_mcp`.
- [ ] Apply the per-repo migration pattern.
- [ ] `uv run pytest tests/ --no-cov -q` — must be all GREEN.
- [ ] `git add langsmith-mcp/` + commit.

## Task 6: opera-cloud-mcp migration (1 usage)

**Files:**

- Modify: `opera-cloud-mcp/opera_cloud_mcp/config.py`
- Test: existing tests should pass.

**Steps:**

- [ ] `grep -rn "MCPBaseSettings\|MCPServerSettings" opera-cloud-mcp/opera_cloud_mcp`.
- [ ] Apply the per-repo migration pattern.
- [ ] `uv run pytest tests/ --no-cov -q` — must be all GREEN.
- [ ] `git add opera-cloud-mcp/` + commit.

## Task 7: Final audit

**Steps:**

- [ ] Run the audit script across ALL /Users/les/Projects repos:

```bash
for repo in /Users/les/Projects/*/; do
  count=$(grep -rn "MCPBaseSettings\|MCPServerSettings" "$repo" --include="*.py" 2>/dev/null | grep -v ".venv" | grep -v "__pycache__" | grep -v ".cache/" | grep -v "/.claude/worktrees/" | wc -l)
  if [ "$count" -gt 0 ]; then echo "$repo: $count"; fi
done
```

- [ ] Expected output: **0 repos** with usages (modulo mcp-common itself, which is the source of the warning).
- [ ] If any remaining, file a follow-up plan with the residual audit.

## Integration Contract

- **Triggered from:** operator runs `mahavishnu metrics engines --source auto --output table` and sees deprecation warning count drop per migrated repo.
- **Returns to / updates:** `pytest -W error::DeprecationWarning` no longer fails on the migrated repos; deprecation count drops to 0.
- **Demonstrable by:** `grep -rn "MCPBaseSettings\|MCPServerSettings" <repo>` returns nothing in source code (excluding `mcp-common` itself).
- **Rollback signal:** tests fail → `git revert` the per-repo commit.
- **Observability added:** `git log --oneline` per migrated repo shows the migration commit; deprecation warnings drop on `pytest` runs.

## Out of scope

- **`mcp-common` package itself.** It emits the deprecation by intent ("silencing is left to the consumer"). Editing it would change the contract — separate, larger plan.
- **The mycelium-core plugin / agent definitions.** Those have their own MCPBaseSettings usages and are managed separately from these standalone Bodai MCP servers.

## Estimated effort

~6 commits, one per repo. Per-repo effort is small (~5–15 min) following the established pattern. Total: ~1–2 hours.

## Reference: established migration pattern

See session-buddy commit `05bc2622` for the canonical `.load()` rewrite that preserves both:

1. The legacy `(server_name, config_path=...)` MCPBaseSettings signature
1. The flat-YAML schema that MCPBaseSettings used (read via `yaml.safe_load` and merged on top of oneiric's nested defaults)

The crackerjack commit `25e230e7` shows the simple bulk-replace variant when `.load()` isn't used (just inheritance swap).
