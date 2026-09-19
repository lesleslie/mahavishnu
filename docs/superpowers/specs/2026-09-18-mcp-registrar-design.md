---
status: draft
role: implementation
kind: plan
date: 2026-09-18
last_reviewed: 2026-09-18
superseded_by: null
blocks_on: []
topic: mcp-registrar
---

# Mahavishnu MCP Registrar

## Context

`.mcp.json` files in the Bodai ecosystem are currently hand-edited
and Claude Code-only. The 2026-08-24 audit
(`.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md`)
established per-project scoping and a secrets-in-shell-env rule, but
no provision exists for non-Claude harnesses. Qwen Code is now
shipping with its own MCP loader (see `docs/runbooks/qwen-hook-setup.md`
for the parallel hook bridge) and a manual `.qwen/settings.json`
write today.

The Qwen-side is unpopulated (`{"$version": 4, "permissions": {"allow":
["WebSearch"]}}` — confirmed 2026-09-18). Every project that wants MCP
servers in Qwen has to copy/paste between two files by hand. Drift is
inevitable.

A second concern: `.mcp.json` has no validation beyond the pre-commit
secret audit. Adding a server (transport + URL + env) is currently a
guess-and-commit exercise.

This spec introduces a **registrar** that owns the canonical MCP
server list per project, validates it, and emits both Claude-side
and Qwen-side configs from one source.

## Goals

- **Single source of truth** per project (one YAML per project).
- **No drift** between Claude's `.mcp.json` and Qwen's config — both
  derived from the same canonical.
- **Pre-commit enforced** — invalid YAML or inlined secrets block the
  commit, not just the audit.
- **Zero net-new infra** — no daemon, no runtime service. Pure
  transform-on-write.
- **Compatible with existing scoping rules** — per-project
  `.mcp.json` (decision rule 2) is preserved; the registrar emits it,
  it doesn't replace it.

## Non-goals

- **Multi-machine sync.** Each operator's `~/.qwen/settings.json` is
  theirs to commit/push. The registrar writes locally.
- **Runtime health monitoring.** That's `mcp__mahavishnu__pool_health`
  territory.
- **Replacing `.mcp.json` as Claude's input.** Claude Code still
  reads `.mcp.json`; the registrar just owns what gets written to it.
- **Crackerjack `--fail-fast` iteration mode.** Tracked separately in
  crackerjack (different repo).

## Architecture

```
┌─────────────────────────────────┐
│  <project>/mcp-servers.yaml     │  ← canonical (hand-edited, in git)
└──────────────┬──────────────────┘
               │  (read + Pydantic-validate)
               ▼
┌────────────────────────────────────────────┐
│  mahavishnu/mcp/registrar.py               │
│  - load_yaml -> MCPServerSpec              │
│  - audit (inline call to                  │
│    audit_no_secrets_in_mcp.py logic)       │
│  - emit .mcp.json (Claude)                 │
│  - emit ~/.qwen/settings.json (Qwen)       │
└──────────────┬─────────────────────────────┘
               │  (write, atomic: tmp + rename)
       ┌───────┴────────┐
       ▼                ▼
┌─────────────┐  ┌──────────────────────────┐
│ .mcp.json   │  │ ~/.qwen/settings.json    │
│ (Claude)    │  │ (Qwen, user-global)      │
│ git-tracked │  │ gitignored               │
└─────────────┘  └──────────────────────────┘
```

The registrar is a **normalizer**, not a service — same shape as
`mahavishnu/bodai_hook_bridge.py`. One canonical input, multiple
harness-shaped outputs, no runtime state.

## Canonical YAML schema

`mahavishnu/mcp_servers_schema.py` defines the Pydantic models.
Versioned via `schema_version: 1` field at the top.

```yaml
# <project>/mcp-servers.yaml
schema_version: 1
servers:
  akosha:
    transport: http
    url: http://localhost:8682/mcp
  crackerjack:
    transport: http
    url: http://localhost:8676/mcp
  minimax-coding-plan:
    transport: stdio
    command: uvx
    args: ["--from", "minimax-coding-plan-mcp", "--with", "mcp<2", "minimax-coding-plan-mcp", "-y"]
    env:
      MINIMAX_API_HOST: https://api.minimax.io
      # MINIMAX_API_KEY MUST come from shell env, NEVER inlined
```

Pydantic model (`MCPServerSpec`):

- `transport: Literal["http", "stdio"]` — required, disambiguates
  field requirements.
- For `http`: `url: HttpUrl` required; `headers: dict[str, str]`
  optional.
- For `stdio`: `command: str` required; `args: list[str]`,
  `env: dict[str, str]` optional.
- `name` derived from YAML key, not duplicated inside the value.

`MCPServersFile` validates the whole file: `schema_version: int`,
`servers: dict[str, MCPServerSpec]`. Reserved server names
(`__proto__`, names starting with `__`) rejected — protects against
the `mcpServers` key being shadowed by accident.

## Sync flow

### Manual: `mahavishnu mcp sync [path]`

```
mahavishnu mcp sync                    # sync current project (cwd)
mahavishnu mcp sync /path/to/project   # sync a specific project
mahavishnu mcp sync --dry-run          # show diff, no writes
mahavishnu mcp sync --emit qwen-only   # skip Claude-side
mahavishnu mcp sync --emit claude-only # skip Qwen-side
mahavishnu mcp sync --verbose          # log every server emitted
```

CLI registered at `mahavishnu/cli/mcp_cli.py`, hooked into
`mahavishnu/cli.py` alongside `index`, `pool`, `repo`, etc.

Output envelope (JSON, machine-parseable):

```json
{
  "wrote": ["<project>/.mcp.json", "/Users/<user>/.qwen/settings.json"],
  "unchanged": [],
  "skipped": [],
  "errors": [],
  "audit": {"violations": 0, "scanned_files": 2},
  "diff_summary": {"added": 0, "removed": 0, "changed": 0}
}
```

Matches the structured-envelope pattern used elsewhere
(`mcp__mahavishnu__pool_route_execute`, `mcp__mahavishnu__list_repos`).

### Atomic writes

Both targets written via `tmp + os.replace()` so a partial write
can't leave Claude or Qwen reading a half-formed file. If the Qwen
write fails after the Claude write succeeds, the next `sync` will
re-emit both — idempotent.

### Auto-sync: pre-commit hook

`mahavishnu/core/code_index/git_hooks.py::PRE_COMMIT_CONTENT` already
runs `scripts/audit_no_secrets_in_mcp.py` for `.mcp.json` changes.
This spec adds a sibling step:

```bash
# Pseudocode — added to PRE_COMMIT_CONTENT
if git diff --cached --name-only | grep -qE '(^|/)mcp-servers\.yaml$'; then
    mahavishnu mcp sync --quiet || exit 1
fi
```

`--quiet` suppresses the JSON envelope; failures show only the error
that blocked the commit. The install path (`mahavishnu index
install-hooks <path>`) already wires this template.

If `mcp-servers.yaml` is staged but `mahavishnu mcp sync` isn't on
PATH (e.g., fresh clone without `uv pip install -e .`), the hook
prints a clear remediation message instead of failing silently. The
check is: `command -v mahavishnu` first, bail with exit 0 + warning
otherwise (the operator should finish setup first).

## Audit + secrets

The registrar calls the audit logic inline. Currently
`scripts/audit_no_secrets_in_mcp.py` is a CLI-only script; this spec
promotes it to a library (`scripts/audit_no_secrets_in_mcp.py` exports
`audit_dict(config: dict, source_path: Path) -> list[Violation]`)
without changing the existing CLI behavior. The CLI wrapper keeps
working as before.

The audit runs on:

1. The parsed YAML (before emission) — catches inlined secrets in
   source.
2. The emitted `.mcp.json` (after emission) — defense in depth.

Same `*_KEY`/`*_TOKEN`/`*_SECRET`/`*_PASSWORD` patterns, same
allowlist (`*_HOST`/`*_URL`/`*_PORT`/`*_DOMAIN`/`*_PATH`/`*_DIR`/
`*_NAME`/`*_REGION`/`*_TIMEOUT`). Non-zero exit blocks the emit.

## Migration: `mahavishnu mcp migrate-from-json`

One-shot converter. Reads `<project>/.mcp.json`, emits
`<project>/mcp-servers.yaml`. Idempotent: refuses to overwrite an
existing YAML unless `--force`.

```bash
mahavishnu mcp migrate-from-json              # current project
mahavishnu mcp migrate-from-json --dry-run    # show diff only
mahavishnu mcp migrate-from-json --force      # overwrite existing
```

After migration:

1. `git rm .mcp.json` (will be re-emitted by the next `sync`).
2. `git add mcp-servers.yaml`.
3. Commit.

For each project (mahavishnu, fastblocks, splashstand per decision
rule 2's table), the migration is run once. Subsequent commits use
the registrar only.

## Qwen-side concerns

**Unknown:** exact Qwen Code MCP config schema and load order. As of
2026-09-18 the `qwen --version` installed locally was not exercised
to confirm whether MCP config lives in `~/.qwen/settings.json` under
an `mcpServers` key, or elsewhere.

The emitter is built to **the standard MCP transport shape** (HTTP
with `url`; stdio with `command`+`args`+`env`), which is the schema
shared across Claude Code, Cursor, and other MCP-aware harnesses as
of 2026-09. If Qwen diverges, the emitter has a single seam
(`_emit_qwen(servers: dict) -> dict` in `mahavishnu/mcp/registrar.py`)
that adapts the output to whatever Qwen's actual loader expects.

If Qwen doesn't read `~/.qwen/settings.json` for MCP at all, the
emitter's failure mode is benign: the file is written, Qwen ignores
it. No operator-visible harm beyond a stale file. We do NOT
auto-delete on detection of "Qwen doesn't read this" — operators
decide.

**Open question (filed):** confirm Qwen's actual MCP config schema
before shipping. Tracking will land in the rollout section.

## CLI surface

`mahavishnu/cli/mcp_cli.py` (new):

| Subcommand | Purpose |
|---|---|
| `mahavishnu mcp sync [path]` | Emit configs from YAML (default cwd) |
| `mahavishnu mcp migrate-from-json [path]` | Convert `.mcp.json` → YAML |
| `mahavishnu mcp validate [path]` | YAML-validate + audit (no writes) |
| `mahavishnu mcp show [path]` | Print the resolved YAML as a tree |

All four respect `--dry-run`, `--verbose`, `--quiet`. The
`sync` command additionally accepts `--emit {claude-only,qwen-only,all}`.

## Pre-commit integration

Existing template at
`mahavishnu/core/code_index/git_hooks.py::PRE_COMMIT_CONTENT`
currently has three hooks (post-commit, post-merge, post-rewrite)
plus the secret audit. Add a fourth step: when
`mcp-servers.yaml` is staged, run `mahavishnu mcp sync --quiet`.

The installer (`mahavishnu index install-hooks <path>`) is unchanged
— the existing pre-commit template is regenerated to include the new
step. No new install path.

A test pins this:
`tests/integration/test_pre_commit_emits_mcp.py` — modifies
`mcp-servers.yaml`, runs the pre-commit template in a temp clone,
asserts `.mcp.json` was rewritten with the new content.

## Testing strategy

### Unit (`tests/unit/test_mcp_registrar.py`)

- Pydantic validation: missing required field per transport type →
  validation error with field name.
- Reserved server names rejected.
- Audit: inlined `*_KEY`/`*_TOKEN`/`*_SECRET` values caught at both
  YAML-parse and JSON-emit phases.
- Allowlist (`*_HOST`, etc.) preserved.
- Atomic write: tmp file created, `os.replace` called, no partial
  state on disk.

### Integration (`tests/integration/test_mcp_sync_e2e.py`)

- Round-trip: `mcp-servers.yaml` → `.mcp.json` + `~/.qwen/settings.json`
  (latter via `tmp_path` override) — content matches expected JSON
  fixture.
- Idempotent: second `sync` with no YAML change writes zero files
  (`unchanged: [both]`).
- `--dry-run`: no files written, envelope shows what *would* have
  been written.
- `--emit qwen-only`: Claude file untouched, Qwen file updated.

### Migration (`tests/integration/test_mcp_migrate_e2e.py`)

- `.mcp.json` → YAML: every server preserved, env vars preserved
  (literal `MINIMAX_API_HOST` allowed; inlined `*_KEY` rejected with
  clear error pointing at the offending key).
- `--force`: overwrites existing YAML with a confirmation prompt
  (auto-yes in CI via `--yes`).
- Idempotent: second run on already-migrated project errors clearly
  ("already migrated, use --force to overwrite").

### Pre-commit (`tests/integration/test_pre_commit_emits_mcp.py`)

- Modifies `mcp-servers.yaml` → pre-commit hook runs → `.mcp.json`
  is rewritten.
- Modifies `.mcp.json` directly without touching YAML → pre-commit
  hook flags drift (`mcp-servers.yaml` is older than `.mcp.json`,
  commit warned, not blocked — warning only, since some legacy
  workflows may still hand-edit).

### E2E smoke (`tests/e2e/test_mcp_harness_smoke.py`)

Per `wire-up-contract.md`: every registered tool must have a
working data feed. After `sync`:

- Claude Code can list tools from each emitted server (via
  `mcp__mahavishnu__ecosystem_status` or direct probe).
- Qwen Code can list tools from each emitted server (gated by
  `qwen` being installed; skip if not).

This test is `requires_tool: qwen`-marked and runs only when Qwen is
discoverable.

## Rollout

Phased to avoid breaking the existing `.mcp.json` workflow:

1. **Phase 1 — library + CLI, no enforcement.** Ship
   `mahavishnu/mcp/registrar.py` and `mahavishnu mcp sync`. Existing
   hand-edited `.mcp.json` continues to work unchanged.
2. **Phase 2 — opt-in migration.** Run
   `mahavishnu mcp migrate-from-json` on each project (mahavishnu,
   fastblocks, splashstand). After migration, `git rm .mcp.json` is
   manual — operator decides when to commit.
3. **Phase 3 — pre-commit hook.** Update
   `PRE_COMMIT_CONTENT` to auto-sync on `mcp-servers.yaml` changes.
   Existing pre-commit audit on `.mcp.json` remains (defense in
   depth).
4. **Phase 4 — Qwen verification.** Once Qwen's actual MCP schema is
   confirmed, update `_emit_qwen` if needed. If Qwen doesn't support
   `mcpServers` in `~/.qwen/settings.json`, the seam degrades to
   "log a warning that Qwen support is unverified."

## Observability

- `mahavishnu mcp sync` envelope is JSON-parseable for downstream
  automation.
- Akosha trace emitted on each `sync` via existing
  `mahavishnu/observability` (one trace per server emitted, not per
  file — keeps cardinality sane).
- Crackerjack audit (`crackerjack run`) reuses the existing audit
  logic on the emitted `.mcp.json`; no new audit code.

## Out of scope / future work

- **Crackerjack `--fail-fast` iteration mode.** Tracked separately
  in the crackerjack repo.
- **Multi-machine Qwen config sync.** Each operator's
  `~/.qwen/settings.json` is theirs. We could later add a
  `mahavishnu mcp sync --target <path>` to support operator-chosen
  destinations, but YAGNI until asked.
- **Qwen-side schema verification.** Open question above; not
  blocking, but should be resolved before phase 4.
- **Plugin manifests.** Decision rule 4 prefers plugins over bare
  `.mcp.json` entries for some servers. This spec doesn't change
  that — the registrar emits bare entries today; plugin substitution
  is a separate refactor.

## Cross-references

- `.claude/decisions/2026-08-24-bodai-mcp-routing-pattern.md` — the
  rules this spec respects (secrets in shell env, per-project
  `.mcp.json`).
- `scripts/audit_no_secrets_in_mcp.py` — the audit logic we promote
  to a library.
- `mahavishnu/core/code_index/git_hooks.py::PRE_COMMIT_CONTENT` —
  the pre-commit template we extend.
- `mahavishnu/bodai_hook_bridge.py` — the architectural pattern
  (canonical input → harness-shaped outputs, no runtime state) this
  spec mirrors.
- `docs/runbooks/qwen-hook-setup.md` — sibling runbook for Qwen
  hooks; same operator-side / gitignored pattern applies to the
  Qwen MCP config.
